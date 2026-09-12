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
from textual.widgets import (
    Button,
    DataTable,
    Label,
    RichLog,
    Static,
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
_VIEW_IDS = ("monitor", "cycles", "campaign", "problems", "logs", "help")


@dataclass(frozen=True)
class AttemptSnapshot:
    """Files and metadata belonging to the newest attempt of one task."""

    directory: Path
    metadata: dict[str, Any] | None
    stdout_path: Path
    stderr_path: Path
    pbs_stdout_path: Path
    pbs_stderr_path: Path

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

        return AttemptSnapshot(
            directory=attempt,
            metadata=metadata,
            stdout_path=attempt / "stdout.log",
            stderr_path=attempt / "stderr.log",
            pbs_stdout_path=attempt / "pbs.stdout.log",
            pbs_stderr_path=attempt / "pbs.stderr.log",
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


class WorkflowTui(App[None]):
    """Full-screen operational monitor for a simpleWorkflow workflow."""

    CSS = """
    Screen {
        background: #111318;
        color: #d7dae0;
    }

    #summary {
        height: 3;
        padding: 0 1;
        border-bottom: solid #303744;
        background: #171a21;
    }

    #date-bar {
        height: 3;
        align: center middle;
        background: #12151b;
        border-bottom: solid #202633;
    }

    #date-label {
        width: 32;
        content-align: center middle;
        text-align: center;
        color: #f8fafc;
    }

    #prev-date, #next-date {
        width: 5;
        min-width: 5;
        height: 3;
        border: none;
        background: #12151b;
        color: #94a3b8;
    }

    #prev-date:hover, #next-date:hover {
        background: #202633;
        color: #f8fafc;
    }

    TabbedContent {
        height: 1fr;
    }

    #monitor-main {
        height: 1fr;
    }

    #left {
        width: 38%;
        min-width: 38;
        border-right: solid #303744;
        background: #12151b;
    }

    #right {
        width: 62%;
    }

    .pane-title {
        height: 1;
        padding: 0 1;
        background: #202633;
        color: #7dd3fc;
        text-style: bold;
    }

    #task-tree {
        height: 1fr;
        padding: 0 1;
    }

    #inspector {
        height: 13;
        padding: 1;
        border-bottom: solid #303744;
        background: #171a21;
    }

    #log, #full-log {
        height: 1fr;
        background: #0d0f13;
        padding: 0 1;
    }

    #cycles-table, #problems-table {
        height: 1fr;
        margin: 1;
    }

    #campaign-view, #help-view {
        height: 1fr;
        padding: 1 2;
        background: #12151b;
    }

    #footer-help {
        height: 1;
        padding: 0 1;
        background: #0b1020;
        color: #cbd5e1;
        content-align: left middle;
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
        self.task_nodes: dict[str, Any] = {}
        self._last_log_signature: tuple[str, int, int] | None = None
        self._choose_initial_selection()

    def compose(self) -> ComposeResult:
        yield Static(id="summary")
        with Horizontal(id="date-bar"):
            yield Button("◀", id="prev-date")
            yield Static(id="date-label")
            yield Button("▶", id="next-date")

        with TabbedContent(initial="monitor", id="views"):
            with TabPane("Monitor", id="monitor"):
                with Horizontal(id="monitor-main"):
                    with Vertical(id="left"):
                        yield Label(id="workflow-title", classes="pane-title")
                        yield Tree(self.workflow_name, id="task-tree")
                    with Vertical(id="right"):
                        yield Label(" TASK INSPECTOR", classes="pane-title")
                        yield Static(id="inspector")
                        yield Label(" LATEST TASK OUTPUT", classes="pane-title")
                        yield RichLog(
                            id="log",
                            highlight=False,
                            markup=False,
                            wrap=False,
                            max_lines=300,
                        )
            with TabPane("Ciclos", id="cycles"):
                yield DataTable(id="cycles-table", cursor_type="cell", zebra_stripes=True)
            with TabPane("Campanha", id="campaign"):
                yield Static(id="campaign-view")
            with TabPane("Problemas", id="problems"):
                yield DataTable(id="problems-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Logs", id="logs"):
                yield RichLog(
                    id="full-log",
                    highlight=False,
                    markup=False,
                    wrap=False,
                    max_lines=1500,
                )
            with TabPane("Ajuda", id="help"):
                yield Static(id="help-view")

        yield Static(
            "[bold]q[/bold] Quit    [bold]←/→[/bold] Day    "
            "[bold]Tab[/bold] Views    [bold]?[/bold] Help",
            id="footer-help",
        )

    def on_mount(self) -> None:
        self._configure_tables()
        self._render_help()
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
        problems.add_columns("Data", "Ciclo", "Etapa", "Tarefa", "Estado")

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
        return f"{self._status_markup(status)}  {escape(display.action)}"

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
        groups: OrderedDict[str, list[str]] = OrderedDict()
        for task_name in visible_tasks:
            groups.setdefault(self._component(task_name), []).append(task_name)

        for component in _COMPONENT_ORDER:
            task_names = groups.pop(component, [])
            if not task_names:
                continue
            group = tree.root.add(
                f"[bold yellow]{escape(component)}[/bold yellow]", expand=True
            )
            for task_name in task_names:
                state = self.engine.state.get_status(self.workflow_name, task_name) or "pending"
                node = group.add_leaf(self._task_label(task_name, state), data=task_name)
                self.task_nodes[task_name] = node

        for component, task_names in groups.items():
            group = tree.root.add(
                f"[bold yellow]{escape(component)}[/bold yellow]", expand=True
            )
            for task_name in task_names:
                state = self.engine.state.get_status(self.workflow_name, task_name) or "pending"
                node = group.add_leaf(self._task_label(task_name, state), data=task_name)
                self.task_nodes[task_name] = node

        if self.selected_task not in self.task_nodes:
            self.selected_task = visible_tasks[0] if visible_tasks else None
        if self.selected_task is not None:
            node = self.task_nodes.get(self.selected_task)
            if node is not None:
                tree.select_node(node)

        title = " WORKFLOW"
        if self.selected_hour is not None:
            title += f" · {self.selected_hour}Z"
        self.query_one("#workflow-title", Label).update(title)

    def on_tree_node_selected(self, event: Tree.NodeSelected[str]) -> None:
        data = event.node.data
        if isinstance(data, str) and data in self.task_map:
            self.selected_task = data
            self._last_log_signature = None
            self._refresh_inspector()
            self._refresh_logs(force=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "prev-date":
            self.action_previous_day()
        elif button_id == "next-date":
            self.action_next_day()

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
        self.selected_hour = hour
        self.selected_task = None
        self._last_log_signature = None
        self._rebuild_tree()
        self.refresh_runtime()

    def action_next_view(self) -> None:
        views = self.query_one("#views", TabbedContent)
        current = views.active or _VIEW_IDS[0]
        try:
            index = _VIEW_IDS.index(current)
        except ValueError:
            index = 0
        views.active = _VIEW_IDS[(index + 1) % len(_VIEW_IDS)]

    def action_show_help(self) -> None:
        self.query_one("#views", TabbedContent).active = "help"

    def _date_changed(self) -> None:
        self.selected_task = None
        self._last_log_signature = None
        self._normalize_selected_hour()
        self._rebuild_tree()
        self.refresh_runtime()

    def action_refresh_now(self) -> None:
        self.refresh_runtime()

    def action_clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()
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
            f"[bold cyan]{escape(self.workflow_name)}[/bold cyan]\n"
            f"[green]{completed}/{len(self.plan)} complete[/green] | "
            f"[cyan]{counts['running']} running[/cyan] | "
            f"[red]{failed} failed[/red] | "
            f"[dim]updated {now}[/dim]"
        )

        self._refresh_date_bar()
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
            label.update("[dim]Workflow without explicit cycle dates[/dim]")
            previous.disabled = True
            following.disabled = True
            return

        previous.disabled = False
        following.disabled = False
        weekday = calendar.day_name[self.selected_date.weekday()]
        days_in_year = 366 if calendar.isleap(self.selected_date.year) else 365
        label.update(
            f"[bold]{self.selected_date.strftime('%d/%m/%Y')}[/bold]\n"
            f"[dim]{weekday} · day {self.selected_date.timetuple().tm_yday}/{days_in_year}[/dim]"
        )

    def _refresh_cycles_view(self) -> None:
        table = self.query_one("#cycles-table", DataTable)
        table.clear(columns=False)
        if self.selected_date is None:
            return

        components = list(_COMPONENT_ORDER)
        extras = [
            component
            for component in OrderedDict.fromkeys(
                self._component(name) for name in self.plan
            )
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
        names = [
            name for name, cycle in self.task_cycles.items() if cycle.day == day
        ]
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
                if current == self.selected_date:
                    cells.append(f"[reverse]{day_number:02d}{marker}[/reverse]")
                else:
                    cells.append(f"{day_number:02d}{marker}")
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
            )
        if table.row_count == 0:
            table.add_row("—", "—", "—", "No failures recorded", "✔")

    def _refresh_inspector(self) -> None:
        inspector = self.query_one("#inspector", Static)
        if self.selected_task is None:
            inspector.update("[dim]No task selected for this cycle.[/dim]")
            return

        task = self.task_map[self.selected_task]
        state = self.engine.state.get_task_state(self.workflow_name, self.selected_task)
        status = state.status if state else "pending"
        display = TerminalReporter._humanize_task(self.selected_task)
        executor = str(task.get("executor", "local"))
        attempt = _latest_attempt(self.workdir, self.selected_task)
        job_id = attempt.job_id if attempt else None
        attempt_executor = attempt.executor if attempt else None
        pbs = task.get("pbs") if isinstance(task.get("pbs"), dict) else {}
        cycle = self.task_cycles.get(self.selected_task)

        resources: list[str] = []
        if pbs:
            for key in (
                "queue",
                "walltime",
                "select",
                "ncpus",
                "mpiprocs",
                "omp_threads",
            ):
                if key in pbs:
                    resources.append(f"{key}={pbs[key]}")

        title = display.component or "Task"
        if cycle is not None:
            title += f" · {cycle.day.strftime('%d/%m/%Y')} {cycle.hour}Z"
        lines = [
            f"[bold yellow]{escape(title)} · {escape(display.action)}[/bold yellow]",
            f"Internal name : [bold]{escape(self.selected_task)}[/bold]",
            f"State         : {self._status_markup(status)}",
            f"Executor      : {escape(attempt_executor or executor)}",
            f"Return code   : "
            f"{state.return_code if state and state.return_code is not None else '—'}",
            f"PBS Job ID    : {escape(job_id) if job_id else '—'}",
        ]
        if resources:
            lines.append(f"Resources     : {escape('  '.join(resources))}")
        if attempt is not None:
            lines.append(f"Attempt dir   : {escape(str(attempt.directory))}")
        inspector.update("\n".join(lines))

    def _refresh_logs(self, *, force: bool = False) -> None:
        logs = [
            self.query_one("#log", RichLog),
            self.query_one("#full-log", RichLog),
        ]
        if self.selected_task is None:
            if force:
                for log in logs:
                    log.clear()
                    log.write("No task selected for this cycle.")
            return

        attempt = _latest_attempt(self.workdir, self.selected_task)
        if attempt is None:
            if force:
                for log in logs:
                    log.clear()
                    log.write("No runtime log is available for this task yet.")
            return

        paths = attempt.preferred_log_paths()
        if not paths:
            if force:
                for log in logs:
                    log.clear()
                    log.write(
                        f"Attempt exists at {attempt.directory}, but its logs are empty."
                    )
            return

        signature_parts: list[str] = []
        total_size = 0
        for path in paths:
            try:
                stat = path.stat()
            except OSError:
                continue
            total_size += stat.st_size
            signature_parts.extend(
                [str(path), str(stat.st_size), str(stat.st_mtime_ns)]
            )
        signature = ("|".join(signature_parts), total_size, len(paths))
        if not force and signature == self._last_log_signature:
            return
        self._last_log_signature = signature

        for log in logs:
            log.clear()
            for path in paths:
                log.write(f"--- {path.name} ---")
                content = _tail(
                    path,
                    max_lines=1000 if log.id == "full-log" else 250,
                )
                log.write(content or "(empty)")

    def _render_help(self) -> None:
        self.query_one("#help-view", Static).update(
            "[bold cyan]simpleWorkflow TUI[/bold cyan]\n\n"
            "[bold]Views[/bold]\n"
            "Monitor    Operational view for the selected cycle.\n"
            "Ciclos     OBS/JEDI/MPAS status across 00Z, 06Z, 12Z and 18Z.\n"
            "Campanha   Monthly execution map.\n"
            "Problemas  Failed validation/execution tasks only.\n"
            "Logs       Expanded output for the selected task.\n"
            "Ajuda      This page.\n\n"
            "[bold]Navigation[/bold]\n"
            "← / →          Previous / next day\n"
            "Tab            Next view\n"
            "?              Open this help page\n"
            "1 / 2 / 3 / 4  Select 00Z / 06Z / 12Z / 18Z\n"
            "Shift+← / →    Previous / next month\n"
            "r              Refresh now\n"
            "c              Clear displayed logs\n"
            "q              Quit\n\n"
            "[dim]The interface is read-only in this version: monitoring never "
            "changes workflow state.[/dim]"
        )


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
