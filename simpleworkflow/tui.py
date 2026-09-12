"""Interactive Textual monitor for simpleWorkflow runtime state."""

from __future__ import annotations

import calendar
import json
from collections import Counter, OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    RichLog,
    Static,
    Tab,
    TabbedContent,
    TabPane,
    Tree,
)

from .console import TerminalReporter
from .engine import WorkflowEngine
from .runs import _task_directory_name

_STATUS = {
    "pending": ("○", "WAITING", "dim"),
    "running": ("●", "RUNNING", "bold cyan"),
    "success": ("✔", "SUCCESS", "green"),
    "failed": ("✘", "FAILED", "bold red"),
    "invalid-input": ("✘", "BAD INPUT", "bold red"),
    "invalid-output": ("✘", "BAD OUTPUT", "bold red"),
    "skipped": ("↷", "SKIPPED", "yellow"),
}

_FAILED_STATES = {"failed", "invalid-input", "invalid-output"}
_COMPLETE_STATES = {"success", "skipped"}
_CYCLE_HOURS = ("00", "06", "12", "18")
_COMPONENT_ORDER = ("OBS", "JEDI", "MPAS")
_VIEW_IDS = ("monitor", "cycles", "campaign", "problems", "logs")
_LOG_BUTTONS = {
    "log-pbs-stdout": "pbs.stdout.log",
    "log-stdout": "stdout.log",
    "log-pbs-stderr": "pbs.stderr.log",
    "log-stderr": "stderr.log",
}

_HELP_TEXT = """[bold cyan]simpleWorkflow TUI[/bold cyan]

[bold]Navigation[/bold]
← / →          Previous / next day
1 / 2 / 3 / 4  Select 00Z / 06Z / 12Z / 18Z
Click cycle    Select that cycle
Tab            Next view
Shift+← / →    Previous / next month
r              Refresh now
v              View selected task logs
/              Filter tasks
c              Clear displayed log
?              Help
q              Quit

[bold]Logs[/bold]
Select a task, then click Logs in the inspector or the Logs tab.
Inside Logs, click a file name to switch between available output/error logs.

[dim]Operational actions are intentionally unavailable until scheduler job IDs
can be recorded while a task is still running.[/dim]

[bold]Esc[/bold] close help"""


@dataclass(frozen=True)
class AttemptSnapshot:
    """Files and metadata belonging to the newest attempt of one task."""

    directory: Path
    metadata: dict[str, Any] | None
    stdout_path: Path
    stderr_path: Path
    pbs_stdout_path: Path
    pbs_stderr_path: Path
    started_at: str | None = None

    @property
    def execution(self) -> dict[str, Any]:
        if not self.metadata:
            return {}
        raw = self.metadata.get("execution")
        return raw if isinstance(raw, dict) else {}

    @property
    def job_id(self) -> str | None:
        value = self.execution.get("job_id")
        return str(value) if value else None

    @property
    def executor(self) -> str | None:
        value = self.execution.get("executor")
        return str(value) if value else None

    @property
    def finished_at(self) -> str | None:
        value = self.metadata.get("finished_at") if self.metadata else None
        return str(value) if value else None

    @property
    def duration_seconds(self) -> float | None:
        value = self.metadata.get("duration_seconds") if self.metadata else None
        return float(value) if isinstance(value, (int, float)) else None

    def preferred_log_paths(self) -> list[Path]:
        paths: list[Path] = []
        for candidate in (
            self.pbs_stdout_path,
            self.stdout_path,
            self.pbs_stderr_path,
            self.stderr_path,
        ):
            if candidate.exists() and candidate.stat().st_size > 0:
                paths.append(candidate)
        return paths


@dataclass(frozen=True)
class TaskCycle:
    """Explicit cycle metadata extracted from one rendered task command."""

    cycle_time: datetime

    @property
    def day(self) -> date:
        return self.cycle_time.date()

    @property
    def hour(self) -> str:
        return self.cycle_time.strftime("%H")


def _latest_attempt(workdir: Path, task_name: str) -> AttemptSnapshot | None:
    """Locate the newest immutable attempt directory for ``task_name``."""
    runs_root = workdir / "runs"
    if not runs_root.is_dir():
        return None

    task_directory = _task_directory_name(task_name)
    run_dirs = sorted(
        (path for path in runs_root.iterdir() if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    )
    for run_dir in run_dirs:
        task_root = run_dir / "tasks" / task_directory
        if not task_root.is_dir():
            continue
        attempts = sorted(
            (path for path in task_root.iterdir() if path.is_dir()),
            key=lambda path: path.name,
            reverse=True,
        )
        if not attempts:
            continue

        attempt = attempts[0]
        metadata_path = attempt / "metadata.json"
        metadata: dict[str, Any] | None = None
        if metadata_path.is_file():
            try:
                raw = json.loads(metadata_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    metadata = raw
            except (OSError, json.JSONDecodeError):
                metadata = None

        started_at_path = attempt / "started_at"
        started_at = None
        if started_at_path.is_file():
            try:
                started_at = started_at_path.read_text(encoding="utf-8").strip() or None
            except OSError:
                started_at = None
        if metadata and metadata.get("started_at"):
            started_at = str(metadata["started_at"])

        return AttemptSnapshot(
            directory=attempt,
            metadata=metadata,
            stdout_path=attempt / "stdout.log",
            stderr_path=attempt / "stderr.log",
            pbs_stdout_path=attempt / "pbs.stdout.log",
            pbs_stderr_path=attempt / "pbs.stderr.log",
            started_at=started_at,
        )
    return None


def _tail(path: Path, *, max_lines: int = 250) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max_lines:])


def _parse_cycle(task: dict[str, Any]) -> TaskCycle | None:
    """Extract an explicit ``--cycle`` ISO timestamp from one task command."""
    argv = task.get("argv")
    if not isinstance(argv, list):
        return None
    try:
        index = argv.index("--cycle")
    except ValueError:
        return None
    if index + 1 >= len(argv) or not isinstance(argv[index + 1], str):
        return None

    try:
        parsed = datetime.fromisoformat(argv[index + 1].replace("Z", "+00:00"))
    except ValueError:
        return None
    return TaskCycle(parsed)


class HelpScreen(ModalScreen[None]):
    """Small on-demand help overlay so the normal monitor stays uncluttered."""

    CSS = """
    HelpScreen {
        align: center middle;
        background: rgba(0, 0, 0, 55%);
    }

    #help-dialog {
        width: 70;
        height: auto;
        max-height: 34;
        padding: 1 2;
        border: solid #394150;
        background: #111318;
        color: #d7dae0;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss_help", "Close", priority=True),
        Binding("question_mark", "dismiss_help", "Close", priority=True),
    ]

    def compose(self) -> ComposeResult:
        yield Static(_HELP_TEXT, id="help-dialog")

    def action_dismiss_help(self) -> None:
        self.dismiss()


class WorkflowTui(App[None]):
    """Full-screen operational monitor for a simpleWorkflow workflow."""

    CSS = """
    Screen {
        background: #0d0f13;
        color: #d7dae0;
    }

    #topbar {
        height: 3;
        padding: 0 1;
        border-bottom: solid #303744;
        background: #111318;
    }

    #summary {
        width: 1fr;
        height: 2;
        content-align: left middle;
    }

    #date-nav {
        width: 34;
        height: 2;
        align: right middle;
    }

    #date-label {
        width: 27;
        height: 1;
        content-align: center middle;
        text-align: center;
        color: #f0c36a;
    }

    #prev-date, #next-date {
        width: 3;
        min-width: 3;
        height: 1;
        min-height: 1;
        padding: 0;
        border: none;
        background: #111318;
        color: #f0c36a;
    }

    #prev-date:hover, #next-date:hover {
        background: #20242d;
        color: #ffffff;
    }

    TabbedContent {
        height: 1fr;
    }

    #cycle-line {
        height: 1;
        padding: 0 1;
        background: #171a21;
        align: left middle;
    }

    #cycle-caption {
        width: 9;
        height: 1;
        color: #8c93a1;
        content-align: left middle;
    }

    .cycle-button {
        width: 10;
        min-width: 8;
        height: 1;
        min-height: 1;
        padding: 0 1;
        border: none;
        background: #171a21;
        color: #8c93a1;
    }

    .cycle-button:hover {
        background: #20242d;
        color: #ffffff;
    }

    .cycle-button.selected-cycle {
        color: #facc15;
        text-style: bold;
    }

    .cycle-button.status-success { color: #65a30d; }
    .cycle-button.status-running { color: #22d3ee; }
    .cycle-button.status-failed { color: #ef4444; }
    .cycle-button.status-partial { color: #eab308; }
    .cycle-button.status-pending { color: #8c93a1; }
    .cycle-button.status-absent { color: #555b66; }

    #monitor-main {
        height: 1fr;
        padding-top: 1;
    }

    #task-filter {
        height: 1;
        min-height: 1;
        margin: 0;
        padding: 0 1;
        border: none;
        background: #171a21;
        color: #d7dae0;
        display: none;
    }

    #left {
        width: 38%;
        min-width: 36;
        border-right: solid #303744;
        background: #0f1116;
    }

    #right {
        width: 62%;
        background: #0d0f13;
    }

    .pane-title {
        height: 2;
        padding: 0;
        background: #0d0f13;
        color: #7ba7ff;
        text-style: bold;
        content-align: left middle;
    }

    #task-tree {
        height: 1fr;
        padding: 0;
    }

    #inspector {
        height: 1fr;
        padding: 1 2;
        background: #0d0f13;
    }

    #open-logs {
        width: 14;
        height: 1;
        min-height: 1;
        margin: 0 0 1 2;
        padding: 0 1;
        border: none;
        background: #0d0f13;
        color: #67e8f9;
        text-style: underline;
    }

    #open-logs:hover {
        background: #20242d;
        color: #ffffff;
    }

    #log-toolbar {
        height: 2;
        padding: 0 1;
        background: #111318;
        border-bottom: solid #303744;
        align: left middle;
    }

    #log-title {
        width: 1fr;
        height: 1;
        color: #9fb9ff;
        content-align: left middle;
    }

    .log-button {
        width: auto;
        min-width: 12;
        height: 1;
        min-height: 1;
        padding: 0 1;
        margin-left: 1;
        border: none;
        background: #111318;
        color: #8c93a1;
    }

    .log-button:hover {
        background: #20242d;
        color: #ffffff;
    }

    .log-button.selected-log {
        color: #67e8f9;
        text-style: bold underline;
    }

    #full-log {
        height: 1fr;
        background: #0d0f13;
        padding: 1;
    }

    #cycles-table, #problems-table {
        height: 1fr;
        margin: 1 0;
    }

    #campaign-view {
        height: 1fr;
        padding: 1 2;
        background: #0d0f13;
    }

    #shortcut-line {
        height: 1;
        padding: 0 1;
        background: #111318;
        color: #697180;
        border-top: solid #252b35;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("left", "previous_day", "Previous day"),
        ("right", "next_day", "Next day"),
        ("shift+left", "previous_month", "Previous month"),
        ("shift+right", "next_month", "Next month"),
        ("1", "select_cycle('00')", "00Z"),
        ("2", "select_cycle('06')", "06Z"),
        ("3", "select_cycle('12')", "12Z"),
        ("4", "select_cycle('18')", "18Z"),
        ("r", "refresh_now", "Refresh"),
        ("v", "open_logs", "View logs"),
        ("slash", "show_filter", "Filter"),
        Binding("escape", "clear_filter", "Clear filter", priority=True),
        ("c", "clear_log", "Clear log"),
        Binding("tab", "next_view", "Views", priority=True),
        ("question_mark", "show_help", "Help"),
    ]

    def __init__(
        self,
        *,
        config: dict[str, Any],
        workflow_path: str | Path,
        workdir: str | Path,
        refresh_seconds: float = 1.0,
    ) -> None:
        super().__init__()
        self.config = config
        self.workflow_path = Path(workflow_path).resolve()
        self.workdir = Path(workdir).resolve()
        self.refresh_seconds = refresh_seconds
        self.engine = WorkflowEngine(config=config, workdir=self.workdir)
        self.workflow_name = self.engine.workflow_name
        self.plan = self.engine.plan()
        self.task_map = {str(task["name"]): task for task in self.engine.tasks}
        self.task_cycles = {
            name: cycle
            for name, task in self.task_map.items()
            if (cycle := _parse_cycle(task)) is not None
        }
        self.available_dates = sorted({cycle.day for cycle in self.task_cycles.values()})
        self.selected_date: date | None = None
        self.selected_hour: str | None = None
        self.selected_task: str | None = None
        self.selected_log_name: str | None = None
        self.task_filter = ""
        self.task_nodes: dict[str, Any] = {}
        self._last_log_signature: tuple[str, int, int] | None = None
        self._choose_initial_selection()

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static(id="summary")
            with Horizontal(id="date-nav"):
                yield Button("◀", id="prev-date")
                yield Static(id="date-label")
                yield Button("▶", id="next-date")

        with TabbedContent(initial="monitor", id="views"):
            with TabPane("Monitor", id="monitor"):
                with Horizontal(id="cycle-line"):
                    yield Static("CICLOS:", id="cycle-caption")
                    for hour in _CYCLE_HOURS:
                        yield Button(
                            f"{hour}Z",
                            id=f"cycle-{hour}",
                            classes="cycle-button",
                        )
                with Horizontal(id="monitor-main"):
                    with Vertical(id="left"):
                        yield Label("WORKFLOW", classes="pane-title")
                        yield Input(placeholder="Filter tasks…", id="task-filter")
                        yield Tree(self.workflow_name, id="task-tree")
                    with Vertical(id="right"):
                        yield Label("INSPECTOR", classes="pane-title")
                        yield Static(id="inspector")
                        yield Button("Logs", id="open-logs")
            with TabPane("Ciclos", id="cycles"):
                yield DataTable(id="cycles-table", cursor_type="cell", zebra_stripes=True)
            with TabPane("Campanha", id="campaign"):
                yield Static(id="campaign-view")
            with TabPane("Problemas", id="problems"):
                yield DataTable(id="problems-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Logs", id="logs"):
                with Horizontal(id="log-toolbar"):
                    yield Static(id="log-title")
                    for button_id, filename in _LOG_BUTTONS.items():
                        yield Button(filename, id=button_id, classes="log-button")
                yield RichLog(
                    id="full-log",
                    highlight=False,
                    markup=False,
                    wrap=False,
                    max_lines=1500,
                )
        yield Static(
            "[q] Quit   [←/→] Day   [Tab] Views   [/] Filter   [v] Logs   [?] Help",
            id="shortcut-line",
        )

    def on_mount(self) -> None:
        self._configure_tables()
        self._rebuild_tree()
        self.refresh_runtime()
        self.set_interval(self.refresh_seconds, self.refresh_runtime)

    def on_unmount(self) -> None:
        self.engine.state.close()

    def _choose_initial_selection(self) -> None:
        if not self.task_cycles:
            self.selected_task = self.plan[0] if self.plan else None
            return

        statuses = {
            name: self.engine.state.get_status(self.workflow_name, name) or "pending"
            for name in self.task_cycles
        }
        preferred = next(
            (name for name in self.plan if statuses.get(name) == "running"),
            None,
        )
        if preferred is None:
            preferred = next(
                (name for name in self.plan if statuses.get(name) in _FAILED_STATES),
                None,
            )
        if preferred is None:
            completed = [
                name for name in self.plan if statuses.get(name) in _COMPLETE_STATES
            ]
            preferred = completed[-1] if completed else self.plan[0]

        cycle = self.task_cycles.get(preferred)
        if cycle is not None:
            self.selected_date = cycle.day
            self.selected_hour = cycle.hour
        self.selected_task = preferred

    def _configure_tables(self) -> None:
        cycles = self.query_one("#cycles-table", DataTable)
        cycles.add_columns("Etapa", "00Z", "06Z", "12Z", "18Z")
        problems = self.query_one("#problems-table", DataTable)
        problems.add_columns("Data", "Ciclo", "Etapa", "Tarefa", "Estado", "Mensagem")

    @staticmethod
    def _status_markup(status: str) -> str:
        symbol, label, style = _STATUS.get(status, ("•", status.upper(), "white"))
        return f"[{style}]{symbol} {label}[/{style}]"

    @staticmethod
    def _aggregate_status(statuses: list[str]) -> str:
        if not statuses:
            return "absent"
        if any(status in _FAILED_STATES for status in statuses):
            return "failed"
        if "running" in statuses:
            return "running"
        if all(status in _COMPLETE_STATES for status in statuses):
            return "success"
        if any(status in _COMPLETE_STATES for status in statuses):
            return "partial"
        return "pending"

    @staticmethod
    def _aggregate_markup(status: str) -> str:
        mapping = {
            "absent": "[dim]—[/dim]",
            "failed": "[bold red]✘ FAILED[/bold red]",
            "running": "[bold cyan]● RUNNING[/bold cyan]",
            "success": "[green]✔ SUCCESS[/green]",
            "partial": "[yellow]◐ PARTIAL[/yellow]",
            "pending": "[dim]○ WAITING[/dim]",
        }
        return mapping.get(status, escape(status.upper()))

    @staticmethod
    def _component(task_name: str) -> str:
        display = TerminalReporter._humanize_task(task_name)
        return display.component or "TASK"

    def _tasks_for_cycle(self, day: date | None, hour: str | None) -> list[str]:
        if not self.task_cycles:
            return list(self.plan)
        if day is None or hour is None:
            return []
        return [
            name
            for name in self.plan
            if (cycle := self.task_cycles.get(name)) is not None
            and cycle.day == day
            and cycle.hour == hour
        ]

    def _statuses_for_cycle(self, day: date, hour: str) -> list[str]:
        return [
            self.engine.state.get_status(self.workflow_name, name) or "pending"
            for name in self._tasks_for_cycle(day, hour)
        ]

    def _task_label(self, task_name: str, status: str) -> str:
        display = TerminalReporter._humanize_task(task_name)
        symbol, _, style = _STATUS.get(status, ("•", status.upper(), "white"))
        return f"{escape(display.action):<16} [{style}]{symbol}[/{style}]"

    def _available_hours_for_day(self, day: date | None) -> list[str]:
        if day is None:
            return []
        return [hour for hour in _CYCLE_HOURS if self._tasks_for_cycle(day, hour)]

    def _normalize_selected_hour(self) -> None:
        if not self.task_cycles:
            return
        available = self._available_hours_for_day(self.selected_date)
        if available and self.selected_hour not in available:
            self.selected_hour = available[0]

    def _rebuild_tree(self) -> None:
        tree = self.query_one("#task-tree", Tree)
        tree.clear()
        self.task_nodes.clear()
        tree.root.set_label(self.workflow_name)
        tree.root.expand()

        self._normalize_selected_hour()
        visible_tasks = self._tasks_for_cycle(self.selected_date, self.selected_hour)
        if self.task_filter:
            needle = self.task_filter.casefold()
            visible_tasks = [
                name
                for name in visible_tasks
                if needle in name.casefold()
                or needle in TerminalReporter._humanize_task(name).action.casefold()
                or needle in (TerminalReporter._humanize_task(name).component or "").casefold()
            ]
        groups: OrderedDict[str, list[str]] = OrderedDict()
        for task_name in visible_tasks:
            groups.setdefault(self._component(task_name), []).append(task_name)

        for component in _COMPONENT_ORDER:
            task_names = groups.pop(component, [])
            if task_names:
                self._add_tree_group(tree, component, task_names)
        for component, task_names in groups.items():
            self._add_tree_group(tree, component, task_names)

        if self.selected_task not in self.task_nodes:
            self.selected_task = visible_tasks[0] if visible_tasks else None
        if self.selected_task is not None:
            node = self.task_nodes.get(self.selected_task)
            if node is not None:
                tree.select_node(node)

    def _add_tree_group(self, tree: Tree, component: str, task_names: list[str]) -> None:
        group = tree.root.add(f"[bold]{escape(component)}[/bold]", expand=True)
        for task_name in task_names:
            state = self.engine.state.get_status(self.workflow_name, task_name) or "pending"
            node = group.add_leaf(self._task_label(task_name, state), data=task_name)
            self.task_nodes[task_name] = node

    def on_tree_node_selected(self, event: Tree.NodeSelected[str]) -> None:
        data = event.node.data
        if isinstance(data, str) and data in self.task_map:
            self.selected_task = data
            self.selected_log_name = None
            self._last_log_signature = None
            self._refresh_inspector()
            self._refresh_logs(force=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "prev-date":
            self.action_previous_day()
        elif button_id == "next-date":
            self.action_next_day()
        elif button_id.startswith("cycle-"):
            self.action_select_cycle(button_id.removeprefix("cycle-"))
        elif button_id == "open-logs":
            self.action_open_logs()
        elif button_id in _LOG_BUTTONS:
            self.selected_log_name = _LOG_BUTTONS[button_id]
            self._last_log_signature = None
            self._refresh_logs(force=True)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "task-filter":
            self.task_filter = event.value.strip()
            self._rebuild_tree()
            self._refresh_inspector()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "task-filter":
            event.input.display = False
            self.query_one("#task-tree", Tree).focus()

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        if event.data_table.id != "cycles-table":
            return
        column = event.coordinate.column
        if column <= 0 or column > len(_CYCLE_HOURS):
            return
        hour = _CYCLE_HOURS[column - 1]
        if not self._tasks_for_cycle(self.selected_date, hour):
            return
        self.action_select_cycle(hour)
        self.query_one("#views", TabbedContent).active = "monitor"

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "problems-table":
            return
        task_name = str(event.row_key.value)
        if task_name not in self.task_map:
            return
        self.selected_task = task_name
        cycle = self.task_cycles.get(task_name)
        if cycle is not None:
            self.selected_date = cycle.day
            self.selected_hour = cycle.hour
        attempt = _latest_attempt(self.workdir, task_name)
        if attempt is not None:
            available = {path.name for path in attempt.preferred_log_paths()}
            self.selected_log_name = next(
                (name for name in ("pbs.stderr.log", "stderr.log") if name in available),
                None,
            )
        self._rebuild_tree()
        self.query_one("#views", TabbedContent).active = "logs"
        self._refresh_logs(force=True)

    def action_previous_day(self) -> None:
        if self.selected_date is not None:
            self.selected_date -= timedelta(days=1)
            self._date_changed()

    def action_next_day(self) -> None:
        if self.selected_date is not None:
            self.selected_date += timedelta(days=1)
            self._date_changed()

    def action_previous_month(self) -> None:
        self._shift_month(-1)

    def action_next_month(self) -> None:
        self._shift_month(1)

    def _shift_month(self, delta: int) -> None:
        if self.selected_date is None:
            return
        index = self.selected_date.year * 12 + self.selected_date.month - 1 + delta
        year, month_index = divmod(index, 12)
        month = month_index + 1
        last_day = calendar.monthrange(year, month)[1]
        self.selected_date = date(year, month, min(self.selected_date.day, last_day))
        self._date_changed()

    def action_select_cycle(self, hour: str) -> None:
        if hour not in _CYCLE_HOURS or not self.task_cycles:
            return
        if not self._tasks_for_cycle(self.selected_date, hour):
            return
        self.selected_hour = hour
        self.selected_task = None
        self.selected_log_name = None
        self._last_log_signature = None
        self._rebuild_tree()
        self.refresh_runtime()

    def action_open_logs(self) -> None:
        if self.selected_task is None:
            return
        self.query_one("#views", TabbedContent).active = "logs"
        self._refresh_logs(force=True)

    def action_show_filter(self) -> None:
        field = self.query_one("#task-filter", Input)
        field.display = True
        field.focus()

    def action_clear_filter(self) -> None:
        field = self.query_one("#task-filter", Input)
        if not field.display and not self.task_filter:
            return
        field.value = ""
        field.display = False
        self.task_filter = ""
        self._rebuild_tree()
        self.query_one("#task-tree", Tree).focus()

    def action_next_view(self) -> None:
        views = self.query_one("#views", TabbedContent)
        current = views.active or _VIEW_IDS[0]
        try:
            index = _VIEW_IDS.index(current)
        except ValueError:
            index = 0
        views.active = _VIEW_IDS[(index + 1) % len(_VIEW_IDS)]

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def _date_changed(self) -> None:
        self.selected_task = None
        self.selected_log_name = None
        self._last_log_signature = None
        self._normalize_selected_hour()
        self._rebuild_tree()
        self.refresh_runtime()

    def action_refresh_now(self) -> None:
        self.refresh_runtime()

    def action_clear_log(self) -> None:
        self.query_one("#full-log", RichLog).clear()
        self._last_log_signature = None

    def refresh_runtime(self) -> None:
        """Refresh persisted task states and all operational views."""
        statuses: dict[str, str] = {}
        for task_name in self.plan:
            status = self.engine.state.get_status(self.workflow_name, task_name) or "pending"
            statuses[task_name] = status
            node = self.task_nodes.get(task_name)
            if node is not None:
                node.set_label(self._task_label(task_name, status))

        counts = Counter(statuses.values())
        completed = sum(1 for status in statuses.values() if status in _COMPLETE_STATES)
        failed = sum(1 for status in statuses.values() if status in _FAILED_STATES)
        now = datetime.now().strftime("%H:%M:%S")
        self.query_one("#summary", Static).update(
            f"[bold #9fb9ff]{escape(self.workflow_name)}[/bold #9fb9ff]\n"
            f"[dim]{completed}/{len(self.plan)}[/dim] [green]✓[/green]   |   "
            f"[cyan]{counts['running']} ●[/cyan]   |   "
            f"[red]{failed} ✘[/red]   |   "
            f"[green]● live[/green] [dim]{self.refresh_seconds:g}s · updated {now}[/dim]"
        )

        problems_tab = self.query_one("#--content-tab-problems", Tab)
        problems_tab.label = (
            f"Problemas [bold red]{failed} ✘[/bold red]" if failed else "Problemas"
        )

        self._refresh_date_bar()
        self._refresh_cycle_line()
        self._refresh_cycles_view()
        self._refresh_campaign()
        self._refresh_problems()
        self._refresh_inspector()
        self._refresh_logs()

    def _refresh_date_bar(self) -> None:
        label = self.query_one("#date-label", Static)
        previous = self.query_one("#prev-date", Button)
        following = self.query_one("#next-date", Button)
        if self.selected_date is None:
            label.update("[dim]no cycle date[/dim]")
            previous.disabled = True
            following.disabled = True
            return

        previous.disabled = False
        following.disabled = False
        days_in_year = 366 if calendar.isleap(self.selected_date.year) else 365
        label.update(
            f"[bold]{self.selected_date.strftime('%d/%m/%Y')}[/bold]  "
            f"[dim]({self.selected_date.timetuple().tm_yday}/{days_in_year})[/dim]"
        )

    def _refresh_cycle_line(self) -> None:
        if self.selected_date is None:
            for hour in _CYCLE_HOURS:
                button = self.query_one(f"#cycle-{hour}", Button)
                button.disabled = True
                button.label = f"{hour}Z ·"
            return

        symbol_map = {
            "success": "✓",
            "running": "●",
            "failed": "✘",
            "partial": "◐",
            "pending": "○",
            "absent": "·",
        }
        status_classes = {f"status-{name}" for name in symbol_map}
        for hour in _CYCLE_HOURS:
            button = self.query_one(f"#cycle-{hour}", Button)
            aggregate = self._aggregate_status(
                self._statuses_for_cycle(self.selected_date, hour)
            )
            for class_name in status_classes:
                button.remove_class(class_name)
            button.add_class(f"status-{aggregate}")
            button.set_class(hour == self.selected_hour, "selected-cycle")
            button.disabled = aggregate == "absent"
            prefix = "▶ " if hour == self.selected_hour else ""
            button.label = f"{prefix}{hour}Z {symbol_map[aggregate]}"

    def _refresh_cycles_view(self) -> None:
        table = self.query_one("#cycles-table", DataTable)
        table.clear(columns=False)
        if self.selected_date is None:
            return

        components = list(_COMPONENT_ORDER)
        extras = [
            component
            for component in OrderedDict.fromkeys(self._component(name) for name in self.plan)
            if component not in components
        ]
        for component in [*components, *extras]:
            row: list[str] = [component]
            for hour in _CYCLE_HOURS:
                names = [
                    name
                    for name in self._tasks_for_cycle(self.selected_date, hour)
                    if self._component(name) == component
                ]
                statuses = [
                    self.engine.state.get_status(self.workflow_name, name) or "pending"
                    for name in names
                ]
                row.append(self._aggregate_markup(self._aggregate_status(statuses)))
            table.add_row(*row)

    def _day_status(self, day: date) -> str:
        names = [name for name, cycle in self.task_cycles.items() if cycle.day == day]
        statuses = [
            self.engine.state.get_status(self.workflow_name, name) or "pending"
            for name in names
        ]
        return self._aggregate_status(statuses)

    def _refresh_campaign(self) -> None:
        view = self.query_one("#campaign-view", Static)
        if self.selected_date is None:
            view.update("[dim]No dated campaign information is available.[/dim]")
            return

        year = self.selected_date.year
        month = self.selected_date.month
        weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
        lines = [
            f"[bold cyan]{calendar.month_name[month].upper()} {year}[/bold cyan]",
            "",
            "[bold]Mon   Tue   Wed   Thu   Fri   Sat   Sun[/bold]",
        ]
        symbols = {
            "success": "[green]✔[/green]",
            "running": "[bold cyan]●[/bold cyan]",
            "failed": "[bold red]✘[/bold red]",
            "partial": "[yellow]◐[/yellow]",
            "pending": "[dim]○[/dim]",
            "absent": "[dim]·[/dim]",
        }
        for week in weeks:
            cells: list[str] = []
            for day_number in week:
                if day_number == 0:
                    cells.append("     ")
                    continue
                current = date(year, month, day_number)
                marker = symbols[self._day_status(current)]
                cell = f"{day_number:02d}{marker}"
                if current == self.selected_date:
                    cell = f"[reverse]{cell}[/reverse]"
                cells.append(cell)
            lines.append("  ".join(cells))
        lines.extend(
            [
                "",
                "[dim]✔ complete   ● running   ✘ failed   ◐ partial   "
                "○ waiting   · no tasks[/dim]",
            ]
        )
        view.update("\n".join(lines))

    def _refresh_problems(self) -> None:
        table = self.query_one("#problems-table", DataTable)
        table.clear(columns=False)
        for task_name in self.plan:
            state = self.engine.state.get_status(self.workflow_name, task_name) or "pending"
            if state not in _FAILED_STATES:
                continue
            cycle = self.task_cycles.get(task_name)
            display = TerminalReporter._humanize_task(task_name)
            table.add_row(
                cycle.day.strftime("%d/%m/%Y") if cycle else "—",
                f"{cycle.hour}Z" if cycle else "—",
                display.component or "TASK",
                display.action,
                self._status_markup(state),
                self._problem_message(task_name),
                key=task_name,
            )
        if table.row_count == 0:
            table.add_row("—", "—", "—", "No failures recorded", "✔", "—")

    def _problem_message(self, task_name: str) -> str:
        attempt = _latest_attempt(self.workdir, task_name)
        if attempt is None:
            return "No failure detail recorded"
        if attempt.metadata and attempt.metadata.get("reason"):
            return str(attempt.metadata["reason"])
        for path in (attempt.pbs_stderr_path, attempt.stderr_path):
            text = _tail(path, max_lines=20)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if lines:
                return lines[-1][-160:]
        return "See task logs"

    def _refresh_inspector(self) -> None:
        inspector = self.query_one("#inspector", Static)
        open_logs = self.query_one("#open-logs", Button)
        if self.selected_task is None:
            inspector.update("[dim]No task selected for this cycle.[/dim]")
            open_logs.disabled = True
            open_logs.label = "Logs"
            return

        state = self.engine.state.get_task_state(self.workflow_name, self.selected_task)
        status = state.status if state else "pending"
        display = TerminalReporter._humanize_task(self.selected_task)
        attempt = _latest_attempt(self.workdir, self.selected_task)
        cycle = self.task_cycles.get(self.selected_task)
        job_id = attempt.job_id if attempt else None
        return_code = state.return_code if state and state.return_code is not None else None
        log_paths = attempt.preferred_log_paths() if attempt is not None else []

        open_logs.disabled = not log_paths
        open_logs.label = f"Logs ({len(log_paths)})" if log_paths else "Logs"

        task_title = display.component or "Task"
        if cycle is not None:
            task_title += f"  {cycle.hour}Z"
        task_title += f"  {display.action}"

        _, state_label, state_style = _STATUS.get(
            status, ("•", status.upper(), "white")
        )
        state_text = f"[{state_style}]{state_label}[/{state_style}]"
        if return_code is not None:
            state_text += f" [dim]({return_code})[/dim]"

        path = str(attempt.directory) if attempt is not None else "—"
        started_at = attempt.started_at if attempt else None
        finished_at = attempt.finished_at if attempt else None
        duration = attempt.duration_seconds if attempt else None
        if duration is None and started_at and status == "running":
            try:
                started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                duration = (datetime.now(started.tzinfo) - started).total_seconds()
            except ValueError:
                duration = None
        elapsed = self._format_duration(duration)
        resources = self._task_resources(self.task_map[self.selected_task])
        inspector.update(
            "[dim #7883a6]Task[/dim #7883a6]        "
            f"[bold]{escape(task_title)}[/bold]\n\n"
            "[dim #7883a6]Internal[/dim #7883a6]    "
            f"{escape(self.selected_task)}\n\n\n"
            "[dim #7883a6]State[/dim #7883a6]       "
            f"{state_text}\n\n\n"
            "[dim #7883a6]PBS ID[/dim #7883a6]      "
            f"{escape(job_id) if job_id else '—'}\n\n\n"
            "[dim #7883a6]Elapsed[/dim #7883a6]     "
            f"{elapsed}\n\n"
            "[dim #7883a6]Started[/dim #7883a6]     "
            f"{self._display_timestamp(started_at)}\n"
            "[dim #7883a6]Finished[/dim #7883a6]    "
            f"{self._display_timestamp(finished_at)}\n\n"
            "[dim #7883a6]Resources[/dim #7883a6]   "
            f"{escape(resources)}\n\n"
            "[dim #7883a6]Path[/dim #7883a6]        "
            f"[cyan]{escape(path)}[/cyan]"
        )

    @staticmethod
    def _display_timestamp(value: str | None) -> str:
        if not value:
            return "—"
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return escape(value)
        return parsed.strftime("%d/%m/%Y %H:%M:%S")

    @staticmethod
    def _format_duration(seconds: float | None) -> str:
        if seconds is None:
            return "—"
        total = max(0, int(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def _task_resources(task: dict[str, Any]) -> str:
        if task.get("executor", "local") != "pbs":
            return "local"
        pbs = task.get("pbs")
        if not isinstance(pbs, dict):
            return "PBS"
        parts: list[str] = []
        if pbs.get("queue"):
            parts.append(f"queue {pbs['queue']}")
        if pbs.get("select"):
            parts.append(f"{pbs['select']} node(s)")
        if pbs.get("ncpus"):
            parts.append(f"{pbs['ncpus']} CPUs/node")
        if pbs.get("mpiprocs"):
            parts.append(f"{pbs['mpiprocs']} MPI ranks/node")
        if pbs.get("walltime"):
            parts.append(f"walltime {pbs['walltime']}")
        return " · ".join(parts) or "PBS"

    def _refresh_log_toolbar(self, paths: list[Path]) -> None:
        available = {path.name for path in paths}
        if self.selected_log_name not in available:
            self.selected_log_name = paths[0].name if paths else None

        title = self.query_one("#log-title", Static)
        task_label = self.selected_task or "no task selected"
        title.update(f"[bold]{escape(task_label)}[/bold]")

        for button_id, filename in _LOG_BUTTONS.items():
            button = self.query_one(f"#{button_id}", Button)
            button.display = filename in available
            button.set_class(filename == self.selected_log_name, "selected-log")

    def _refresh_logs(self, *, force: bool = False) -> None:
        log = self.query_one("#full-log", RichLog)
        if self.selected_task is None:
            self._refresh_log_toolbar([])
            if force:
                log.clear()
                log.write("No task selected for this cycle.")
            return

        attempt = _latest_attempt(self.workdir, self.selected_task)
        if attempt is None:
            self._refresh_log_toolbar([])
            if force:
                log.clear()
                log.write("No runtime log is available for this task yet.")
            return

        paths = attempt.preferred_log_paths()
        self._refresh_log_toolbar(paths)
        if not paths:
            if force:
                log.clear()
                log.write(f"Attempt exists at {attempt.directory}, but its logs are empty.")
            return

        path_by_name = {path.name: path for path in paths}
        path = path_by_name.get(self.selected_log_name or "", paths[0])
        try:
            stat = path.stat()
        except OSError:
            if force:
                log.clear()
                log.write(f"Unable to read {path}.")
            return

        signature = (str(path), stat.st_size, stat.st_mtime_ns)
        if not force and signature == self._last_log_signature:
            return
        self._last_log_signature = signature

        log.clear()
        log.write(f"--- {path.name} ---")
        log.write(_tail(path, max_lines=1000) or "(empty)")


def run_tui(
    config: dict[str, Any],
    workflow_path: str | Path,
    workdir: str | Path,
    *,
    refresh_seconds: float = 1.0,
) -> None:
    """Launch the interactive workflow monitor."""
    WorkflowTui(
        config=config,
        workflow_path=workflow_path,
        workdir=workdir,
        refresh_seconds=refresh_seconds,
    ).run()
