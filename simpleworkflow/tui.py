"""Professional Textual monitor backed by the persisted workflow read model."""

from __future__ import annotations

import os
from concurrent.futures import Future
from datetime import date, datetime
from pathlib import Path
from typing import Any

from rich.markup import escape
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    Static,
    Tab,
    TabbedContent,
    TabPane,
    Tree,
)

from .monitor import (
    AttemptSnapshot,
    CycleSnapshot,
    MonitorSnapshot,
    TaskSnapshot,
    load_monitor_snapshot,
)
from .tui_inspector import TaskInspector
from .tui_resources import InspectableResource, discover_attempt_resources
from .tui_viewer import TextFileViewer, TextViewerScreen

_STATUS = {
    "pending": ("○", "PENDING", "dim"),
    "stale": ("↻", "STALE", "yellow"),
    "running": ("●", "RUNNING", "cyan"),
    "success": ("✓", "SUCCESS", "green"),
    "failed": ("✕", "FAILED", "red"),
    "invalid-input": ("!", "BAD INPUT", "red"),
    "invalid-output": ("!", "BAD OUTPUT", "red"),
    "blocked": ("!", "BLOCKED", "red"),
    "interrupted": ("!", "INTERRUPTED", "yellow"),
    "unknown": ("?", "UNKNOWN", "yellow"),
    "skipped": ("–", "SKIPPED", "dim"),
    "partial": ("◐", "PARTIAL", "yellow"),
}
_ATTENTION = {
    "failed",
    "invalid-input",
    "invalid-output",
    "blocked",
    "interrupted",
    "unknown",
}
_COMPLETE = {"success", "skipped"}
_VIEW_IDS = ("monitor", "cycles", "campaign", "problems", "logs")
_LOG_ORDER = ("pbs_stdout", "stdout", "pbs_stderr", "stderr")
_LOG_ERROR_ORDER = ("pbs_stderr", "stderr", "pbs_stdout", "stdout")
_LOG_BUTTONS = {
    "log-pbs-stdout": "pbs_stdout",
    "log-stdout": "stdout",
    "log-pbs-stderr": "pbs_stderr",
    "log-stderr": "stderr",
}
_LOG_LABELS = {
    "pbs_stdout": "pbs.stdout",
    "stdout": "stdout",
    "pbs_stderr": "pbs.stderr",
    "stderr": "stderr",
}
_CYCLE_SLOT_COUNT = 5
_PROCESS_ORDER = ("OBS", "JEDI", "MPAS")

_HELP_TEXT = """[bold]simpleWorkflow monitor[/bold]

↑ / ↓        select task
← / →        previous / next cycle
/            filter tasks
Enter        inspect on narrow terminals
Esc          clear filter / return to workflow
Tab          next view
Shift+Tab    previous view
1..5         Monitor / Ciclos / Campanha / Problemas / Logs
l            logs for selected task
o / e        output / error log
f            follow / pause log updates
r            refresh
?            help
q            close monitor

Dates, cycle buttons and campaign rows are clickable.
The monitor is read-only. Closing it never cancels the workflow.
[dim]Esc closes this help.[/dim]"""


class HelpScreen(ModalScreen[None]):
    CSS = """
    HelpScreen { align: center middle; background: rgba(0, 0, 0, 55%); }
    #help-dialog {
        width: 68; height: auto; max-height: 34; padding: 1 2;
        border: solid #394150; background: #111318; color: #d7dae0;
    }
    """
    BINDINGS = [Binding("escape", "dismiss_help", "Close", priority=True)]

    def compose(self) -> ComposeResult:
        yield Static(_HELP_TEXT, id="help-dialog")

    def action_dismiss_help(self) -> None:
        self.dismiss()


def _task_names(config: dict[str, Any]) -> list[str]:
    tasks = config.get("tasks", [])
    if not isinstance(tasks, list):
        return []
    return [
        str(task["name"])
        for task in tasks
        if isinstance(task, dict) and isinstance(task.get("name"), str)
    ]


def _task_label(name: str, cycle_id: str | None = None) -> str:
    """Return a compact display label without changing the internal task name."""
    display = name
    if cycle_id and cycle_id in display:
        display = display.replace(cycle_id, "", 1)
    return " ".join(display.replace("_", " ").split())


def _status_markup(status: str, *, color: bool = True) -> str:
    symbol, label, style = _STATUS.get(status, ("•", status.upper(), "white"))
    if not color:
        return f"{symbol} {label}"
    return f"[{style}]{symbol} {label}[/{style}]"


def _tree_status_text(status: str, label: str, *, color: bool = True) -> Text:
    """Render a compact status symbol while keeping the label visually quiet."""
    symbol, _, style = _STATUS.get(status, ("•", status.upper(), "white"))
    value = Text()
    value.append(symbol, style=style if color else None)
    value.append(f" {label}")
    return value


def _task_process_step(
    name: str,
    cycle: CycleSnapshot,
) -> tuple[str, str] | None:
    """Infer a presentation-only process/step pair conservatively.

    Scientific unrolled workflows commonly encode a process followed by the
    cycle id or synoptic hour, for example ``obs06_prepare`` or
    ``jedi2018041506_submit``. Only that explicit shape is grouped; names
    that do not match remain in the Workflow group.
    """
    parsed = _cycle_datetime(cycle.cycle_time)
    markers = [cycle.cycle_id]
    if parsed is not None:
        markers.append(parsed.strftime("%H"))
    for marker in markers:
        for separator in ("_", "-"):
            token = f"{marker}{separator}"
            index = name.find(token)
            if index <= 0:
                continue
            process = name[:index]
            step = name[index + len(token) :]
            if not step or not process[0].isalpha():
                continue
            if not all(char.isalnum() or char == "-" for char in process):
                continue
            return process.upper(), _task_label(step)
    return None


def _cycle_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _cycle_date(value: str) -> date | None:
    parsed = _cycle_datetime(value)
    return parsed.date() if parsed is not None else None


def _format_cycle_time(value: str) -> str:
    parsed = _cycle_datetime(value)
    if parsed is None:
        return value
    return parsed.strftime("%Y-%m-%d %HZ")


def _format_cycle_hour(value: str) -> str:
    parsed = _cycle_datetime(value)
    if parsed is None:
        return value
    return parsed.strftime("%HZ")


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _elapsed(started_at: str | None, finished_at: str | None = None) -> float | None:
    if not started_at:
        return None
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        if finished_at:
            finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
        else:
            finished = datetime.now(started.tzinfo)
    except ValueError:
        return None
    return max(0.0, (finished - started).total_seconds())


def _tail(path: Path, max_lines: int = 1000) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max_lines:])


class WorkflowTui(App[None]):
    """Full-screen, read-only monitor for one logical workflow instance."""

    CSS = """
    Screen { background: #0d0f13; color: #d7dae0; }
    #topbar {
        height: 4; padding: 0 1; border-bottom: solid #303744; background: #111318;
    }
    #summary { width: 1fr; height: 3; content-align: left middle; }
    #date-nav { width: 34; height: 3; align: right middle; }
    #prev-date, #next-date {
        width: 3; min-width: 3; height: 1; min-height: 1; padding: 0;
        border: none; background: #111318; color: #9fb9ff;
    }
    #date-current {
        width: 26; min-width: 18; height: 1; min-height: 1; padding: 0 1;
        border: none; background: #111318; color: #9fb9ff;
    }
    #prev-date:hover, #next-date:hover, #date-current:hover,
    .cycle-button:hover, #open-logs:hover, #log-follow:hover {
        background: #20242d; color: #ffffff;
    }
    #date-label { display: none; }
    #cycle-line {
        height: 2; padding: 0 1; background: #171a21; align: left middle;
    }
    #cycle-caption { width: 8; height: 1; color: #697180; content-align: left middle; }
    #cycle-prev, #cycle-next {
        width: 3; min-width: 3; height: 1; min-height: 1; padding: 0;
        border: none; background: #171a21; color: #697180;
    }
    .cycle-button {
        width: 13; min-width: 9; height: 1; min-height: 1; padding: 0 1;
        border: none; background: #171a21; color: #8c93a1;
    }
    .cycle-button.selected-cycle { color: #facc15; text-style: bold; }
    .cycle-button.status-success { color: #65a30d; }
    .cycle-button.status-running { color: #22d3ee; }
    .cycle-button.status-failed { color: #ef4444; }
    .cycle-button.status-partial { color: #eab308; }
    .cycle-button.status-pending { color: #8c93a1; }
    TabbedContent { height: 1fr; }
    #monitor-main { height: 1fr; }
    #left {
        width: 48%; min-width: 28; border-right: solid #303744; background: #0f1116;
    }
    #right { width: 52%; background: #0d0f13; }
    #monitor-main.narrow { layout: vertical; }
    #monitor-main.narrow #left {
        width: 1fr; min-width: 1; height: 1fr; border-right: none;
    }
    #monitor-main.narrow #right { display: none; }
    #monitor-main.narrow.inspecting #left { display: none; }
    #monitor-main.narrow.inspecting #right {
        display: block; width: 1fr; height: 1fr;
    }
    .pane-title {
        height: 2; padding: 0 1; color: #9fb9ff; text-style: bold;
        content-align: left middle;
    }
    #task-filter {
        display: none; height: 1; min-height: 1; margin: 0; padding: 0 1;
        border: none; background: #171a21; color: #d7dae0;
    }
    #task-tree { height: 1fr; padding: 0 1; }
    #inspector { height: auto; max-height: 16; }
    #period-title {
        height: 2; padding: 0 1; border-top: solid #303744;
        color: #9fb9ff; text-style: bold; content-align: left middle;
    }
    #period-matrix { height: 9; min-height: 5; margin: 0; }
    #cycles-table, #problems-table, #campaign-table { height: 1fr; margin: 1 0; }
    #campaign-view { height: 1fr; }
    #campaign-summary { height: auto; max-height: 7; padding: 1 2 0 2; }
    #log-toolbar {
        height: 2; padding: 0 1; border-bottom: solid #303744; background: #111318;
    }
    #log-title {
        width: 1fr; height: 1; color: #9fb9ff; content-align: left middle;
    }
    .log-button, #log-follow {
        width: auto; min-width: 10; height: 1; min-height: 1; padding: 0 1;
        margin-left: 1; border: none; background: #111318; color: #8c93a1;
    }
    .log-button.selected-log { color: #67e8f9; text-style: bold underline; }
    #log-follow.following { color: #65a30d; text-style: bold; }
    #full-log { height: 1fr; padding: 1; background: #0d0f13; }
    #shortcut-line {
        height: 1; padding: 0 1; border-top: solid #252b35;
        background: #111318; color: #697180;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("left", "previous_cycle", "Previous cycle"),
        ("right", "next_cycle", "Next cycle"),
        Binding("tab", "next_view", "Next view", priority=True),
        Binding("shift+tab", "previous_view", "Previous view", priority=True),
        ("1", "select_view('monitor')", "Monitor"),
        ("2", "select_view('cycles')", "Cycles"),
        ("3", "select_view('campaign')", "Campaign"),
        ("4", "select_view('problems')", "Problems"),
        ("5", "select_view('logs')", "Logs"),
        ("slash", "show_filter", "Filter"),
        ("l", "open_logs", "Logs"),
        ("o", "select_output", "Output"),
        ("e", "select_error", "Error"),
        ("f", "toggle_follow", "Follow logs"),
        ("r", "refresh_now", "Refresh"),
        ("enter", "inspect", "Inspect"),
        Binding("escape", "escape_context", "Back", priority=True),
        ("question_mark", "show_help", "Help"),
    ]

    def __init__(
        self,
        *,
        config: dict[str, Any],
        workflow_path: str | Path,
        workdir: str | Path,
        refresh_seconds: float = 1.0,
        color: bool = True,
        completion_future: Future[int] | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.workflow_path = Path(workflow_path).resolve(strict=False)
        self.workdir = Path(workdir).resolve(strict=False)
        self.refresh_seconds = max(0.5, float(refresh_seconds))
        self.color_enabled = bool(color) and not bool(os.environ.get("NO_COLOR"))
        self.completion_future = completion_future
        self.task_order = _task_names(config)
        raw_tasks = config.get("tasks", [])
        self.task_map = {
            str(task["name"]): task
            for task in raw_tasks
            if isinstance(raw_tasks, list)
            and isinstance(task, dict)
            and isinstance(task.get("name"), str)
        }
        self.snapshot = self._load_snapshot()
        self.selected_cycle_id: str | None = None
        self.selected_task: str | None = None
        self.selected_log_key: str | None = None
        self.task_filter = ""
        self.cycle_slots: dict[str, str] = {}
        self.task_nodes: dict[tuple[str | None, str], Any] = {}
        self._tree_signature: tuple[Any, ...] | None = None
        self._choose_initial_selection()

    def _load_snapshot(self) -> MonitorSnapshot:
        return load_monitor_snapshot(self.config, self.workflow_path, self.workdir)

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static(id="summary")
            with Horizontal(id="date-nav"):
                yield Button("◀", id="prev-date")
                yield Button("", id="date-current")
                yield Static("", id="date-label")
                yield Button("▶", id="next-date")
        with Horizontal(id="cycle-line"):
            yield Static("CICLOS", id="cycle-caption")
            yield Button("‹", id="cycle-prev")
            for index in range(_CYCLE_SLOT_COUNT):
                yield Button("", id=f"cycle-slot-{index}", classes="cycle-button")
            yield Button("›", id="cycle-next")
        with TabbedContent(initial="monitor", id="views"):
            with TabPane("Monitor", id="monitor"):
                with Horizontal(id="monitor-main"):
                    with Vertical(id="left"):
                        yield Label("WORKFLOW", classes="pane-title")
                        yield Input(placeholder="Filter tasks…", id="task-filter")
                        yield Tree(self.snapshot.workflow_name, id="task-tree")
                    with Vertical(id="right"):
                        yield Label("INSPECTOR", classes="pane-title")
                        yield TaskInspector(color=self.color_enabled, id="inspector")
                        yield Label("", id="period-title")
                        yield DataTable(
                            id="period-matrix",
                            cursor_type="cell",
                            zebra_stripes=False,
                        )
            with TabPane("Ciclos", id="cycles"):
                yield DataTable(id="cycles-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Campanha", id="campaign"):
                with Vertical(id="campaign-view"):
                    yield Static(id="campaign-summary")
                    yield DataTable(id="campaign-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Problemas", id="problems"):
                yield DataTable(id="problems-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Logs", id="logs"):
                with Horizontal(id="log-toolbar"):
                    yield Static(id="log-title")
                    for button_id, key in _LOG_BUTTONS.items():
                        yield Button(_LOG_LABELS[key], id=button_id, classes="log-button")
                    yield Button("FOLLOW ●", id="log-follow")
                yield TextFileViewer(
                    refresh_seconds=self.refresh_seconds,
                    id="log-viewer",
                )
        yield Static(
            "↑↓ task   ←→ cycle   / filter   Enter inspect   Tab view   l logs   "
            "f follow   r refresh   ? help   q quit",
            id="shortcut-line",
        )

    def on_mount(self) -> None:
        self._configure_tables()
        self._apply_responsive_layout()
        self.refresh_runtime(force=True)
        self.set_interval(self.refresh_seconds, self.refresh_runtime)
        if self.completion_future is not None:
            self.set_interval(0.2, self._check_completion)

    def _check_completion(self) -> None:
        if self.completion_future is not None and self.completion_future.done():
            self.refresh_runtime(force=True)
            self.exit()

    def on_resize(self) -> None:
        self._apply_responsive_layout()

    def _apply_responsive_layout(self) -> None:
        try:
            body = self.query_one("#monitor-main")
        except Exception:
            return
        body.set_class(self.size.width < 86, "narrow")
        if self.size.width >= 86:
            body.remove_class("inspecting")

    def _configure_tables(self) -> None:
        cycles = self.query_one("#cycles-table", DataTable)
        cycles.add_columns("Cycle", "Done", "Running", "Failed", "Pending", "State")
        campaign = self.query_one("#campaign-table", DataTable)
        campaign.add_columns("Date", "Cycles", "Done", "Running", "Failed", "Pending", "State")
        problems = self.query_one("#problems-table", DataTable)
        problems.add_columns("Cycle", "Task", "State", "Message")

    def _choose_initial_selection(self) -> None:
        if self.snapshot.cycles:
            preferred = next(
                (cycle for cycle in self.snapshot.cycles if cycle.status == "running"),
                None,
            )
            if preferred is None:
                preferred = next(
                    (cycle for cycle in self.snapshot.cycles if cycle.status == "failed"),
                    None,
                )
            if preferred is None:
                preferred = next(
                    (
                        cycle
                        for cycle in self.snapshot.cycles
                        if cycle.status in {"partial", "pending"}
                    ),
                    None,
                )
            preferred = preferred or self.snapshot.cycles[-1]
            self.selected_cycle_id = preferred.cycle_id
            self.selected_task = self._preferred_task(preferred.tasks)
        else:
            self.selected_cycle_id = None
            self.selected_task = self._preferred_task(self.snapshot.tasks)

    @staticmethod
    def _preferred_task(tasks: tuple[TaskSnapshot, ...]) -> str | None:
        for status_group in ("running", "attention", "pending"):
            for task in tasks:
                if status_group == "running" and task.status == "running":
                    return task.name
                if status_group == "attention" and task.status in _ATTENTION:
                    return task.name
                if status_group == "pending" and task.status not in _COMPLETE:
                    return task.name
        return tasks[-1].name if tasks else None

    def _selected_cycle(self) -> CycleSnapshot | None:
        return next(
            (
                cycle
                for cycle in self.snapshot.cycles
                if cycle.cycle_id == self.selected_cycle_id
            ),
            None,
        )

    def _selected_task_snapshot(self) -> TaskSnapshot | None:
        cycle = self._selected_cycle()
        if cycle is not None:
            selected = next(
                (task for task in cycle.tasks if task.name == self.selected_task),
                None,
            )
            if selected is not None:
                return selected
        return next(
            (task for task in self.snapshot.tasks if task.name == self.selected_task),
            None,
        )

    def _available_dates(self) -> list[date]:
        values = {
            parsed
            for cycle in self.snapshot.cycles
            if (parsed := _cycle_date(cycle.cycle_time)) is not None
        }
        return sorted(values)

    def _selected_date(self) -> date | None:
        cycle = self._selected_cycle()
        return _cycle_date(cycle.cycle_time) if cycle is not None else None

    def _cycles_for_date(self, target: date | None) -> list[CycleSnapshot]:
        if target is None:
            return []
        return [
            cycle
            for cycle in self.snapshot.cycles
            if _cycle_date(cycle.cycle_time) == target
        ]

    def _select_cycle(self, cycle_id: str, *, switch_to_monitor: bool = False) -> None:
        cycle = next(
            (item for item in self.snapshot.cycles if item.cycle_id == cycle_id),
            None,
        )
        if cycle is None:
            return
        self.selected_cycle_id = cycle.cycle_id
        self.selected_task = self._preferred_task(cycle.tasks)
        self.selected_log_key = None
        self._tree_signature = None
        if switch_to_monitor:
            self.query_one("#views", TabbedContent).active = "monitor"
        self.refresh_runtime(force=True)

    def _select_date(self, target: date, *, switch_to_monitor: bool = True) -> None:
        cycles = self._cycles_for_date(target)
        if not cycles:
            return
        current = self._selected_cycle()
        current_hour = None
        if current is not None and (parsed := _cycle_datetime(current.cycle_time)) is not None:
            current_hour = (parsed.hour, parsed.minute, parsed.second)
        chosen = None
        if current_hour is not None:
            for cycle in cycles:
                parsed = _cycle_datetime(cycle.cycle_time)
                if parsed is not None and (parsed.hour, parsed.minute, parsed.second) == current_hour:
                    chosen = cycle
                    break
        if chosen is None:
            chosen = next((cycle for cycle in cycles if cycle.status == "running"), None)
        if chosen is None:
            chosen = next((cycle for cycle in cycles if cycle.status in _ATTENTION), None)
        if chosen is None:
            chosen = next(
                (cycle for cycle in cycles if cycle.status in {"partial", "pending"}),
                None,
            )
        chosen = chosen or cycles[0]
        self._select_cycle(chosen.cycle_id, switch_to_monitor=switch_to_monitor)

    def _move_date(self, delta: int) -> None:
        dates = self._available_dates()
        if not dates:
            return
        current = self._selected_date()
        try:
            index = dates.index(current) if current is not None else 0
        except ValueError:
            index = 0
        target = max(0, min(len(dates) - 1, index + delta))
        if target == index and current is not None:
            return
        self._select_date(dates[target])

    def _tree_state_signature(self) -> tuple[Any, ...]:
        return (
            self.selected_cycle_id,
            self.task_filter,
            tuple(
                (
                    cycle.cycle_id,
                    tuple((task.name, task.status) for task in cycle.tasks),
                )
                for cycle in self.snapshot.cycles
            ),
            tuple((task.name, task.status) for task in self.snapshot.tasks),
        )

    def _task_matches_filter(self, task: TaskSnapshot, cycle_id: str | None) -> bool:
        if not self.task_filter:
            return True
        needle = self.task_filter.casefold()
        label = _task_label(task.name, cycle_id).casefold()
        return needle in task.name.casefold() or needle in label or needle in task.status.casefold()

    def _rebuild_tree(self, *, force: bool = False) -> None:
        signature = self._tree_state_signature()
        if not force and signature == self._tree_signature:
            return
        self._tree_signature = signature
        tree = self.query_one("#task-tree", Tree)
        tree.clear()
        self.task_nodes.clear()
        tree.root.set_label(self.snapshot.workflow_name)
        tree.root.expand()

        if self.snapshot.cycles:
            cycle = self._selected_cycle()
            process_groups: dict[str, list[tuple[TaskSnapshot, str]]] = {}
            workflow_entries: list[tuple[TaskSnapshot, str | None, str]] = []

            if cycle is not None:
                for task in cycle.tasks:
                    process_step = _task_process_step(task.name, cycle)
                    if process_step is None:
                        workflow_entries.append(
                            (task, cycle.cycle_id, _task_label(task.name, cycle.cycle_id))
                        )
                        continue
                    process, step = process_step
                    process_groups.setdefault(process, []).append((task, step))

                for process, entries in process_groups.items():
                    visible = [
                        (task, step)
                        for task, step in entries
                        if self._task_matches_filter(task, cycle.cycle_id)
                    ]
                    if not visible:
                        continue
                    group_status = self._aggregate_status(
                        [task.status for task, _ in entries]
                    )
                    process_node = tree.root.add(
                        _tree_status_text(
                            group_status,
                            process,
                            color=self.color_enabled,
                        ),
                        expand=True,
                    )
                    for task, step in visible:
                        leaf = process_node.add_leaf(
                            _tree_status_text(
                                task.status,
                                step,
                                color=self.color_enabled,
                            ),
                            data=(cycle.cycle_id, task.name),
                        )
                        self.task_nodes[(cycle.cycle_id, task.name)] = leaf

            workflow_entries.extend(
                (task, None, _task_label(task.name)) for task in self.snapshot.tasks
            )
            workflow_visible = [
                (task, cycle_id, label)
                for task, cycle_id, label in workflow_entries
                if self._task_matches_filter(task, cycle_id)
            ]
            if workflow_visible:
                workflow_status = self._aggregate_status(
                    [task.status for task, _, _ in workflow_entries]
                )
                workflow_node = tree.root.add(
                    _tree_status_text(
                        workflow_status,
                        "Workflow",
                        color=self.color_enabled,
                    ),
                    expand=True,
                )
                for task, cycle_id, label in workflow_visible:
                    leaf = workflow_node.add_leaf(
                        _tree_status_text(
                            task.status,
                            label,
                            color=self.color_enabled,
                        ),
                        data=(cycle_id, task.name),
                    )
                    self.task_nodes[(cycle_id, task.name)] = leaf
        else:
            for task in self.snapshot.tasks:
                if not self._task_matches_filter(task, None):
                    continue
                leaf = tree.root.add_leaf(
                    _tree_status_text(
                        task.status,
                        _task_label(task.name),
                        color=self.color_enabled,
                    ),
                    data=(None, task.name),
                )
                self.task_nodes[(None, task.name)] = leaf

        key = (self.selected_cycle_id, self.selected_task or "")
        selected = self.task_nodes.get(key)
        if selected is None and self.selected_task:
            selected = self.task_nodes.get((None, self.selected_task))
        if selected is None and self.task_nodes:
            first_key, selected = next(iter(self.task_nodes.items()))
            node_cycle_id, self.selected_task = first_key
            if node_cycle_id is not None:
                self.selected_cycle_id = node_cycle_id
        if selected is not None:
            tree.select_node(selected)

    def on_tree_node_selected(self, event: Tree.NodeSelected[object]) -> None:
        data = event.node.data
        if not isinstance(data, tuple) or len(data) != 2:
            return
        cycle_id, task_name = data
        if task_name not in self.task_order:
            return
        if cycle_id is not None:
            self.selected_cycle_id = str(cycle_id)
        self.selected_task = str(task_name)
        self.selected_log_key = None
        self._refresh_header()
        self._refresh_date_nav()
        self._refresh_cycle_line()
        self._refresh_inspector()
        self._refresh_logs(force=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "prev-date":
            self._move_date(-1)
            return
        if button_id == "next-date":
            self._move_date(1)
            return
        if button_id == "date-current":
            self.query_one("#views", TabbedContent).active = "campaign"
            self._sync_campaign_cursor()
            return
        if button_id == "cycle-prev":
            self.action_previous_cycle()
            return
        if button_id == "cycle-next":
            self.action_next_cycle()
            return
        if button_id.startswith("cycle-slot-"):
            cycle_id = self.cycle_slots.get(button_id)
            if cycle_id:
                self._select_cycle(cycle_id)
            return
        if button_id == "open-logs":
            self.action_open_logs()
            return
        if button_id == "log-follow":
            self.action_toggle_follow()
            return

        key = _LOG_BUTTONS.get(button_id)
        if key is None:
            return
        task = self._selected_task_snapshot()
        attempt = task.attempt if task is not None else None
        if attempt is None or key not in attempt.available_logs:
            return
        self.selected_log_key = key
        self._refresh_logs(force=True)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "task-filter":
            return
        self.task_filter = event.value.strip()
        self._tree_signature = None
        self._rebuild_tree(force=True)
        self._refresh_inspector()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "task-filter":
            return
        event.input.display = False
        self.query_one("#task-tree", Tree).focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "cycles-table":
            cycle_id = str(event.row_key.value)
            self._select_cycle(cycle_id, switch_to_monitor=True)
            return

        if event.data_table.id == "campaign-table":
            value = event.row_key.value
            if not isinstance(value, str):
                return
            try:
                target = date.fromisoformat(value)
            except ValueError:
                return
            self._select_date(target, switch_to_monitor=True)
            return

        if event.data_table.id == "problems-table":
            value = event.row_key.value
            if not isinstance(value, str) or "::" not in value:
                return
            cycle_id, task_name = value.split("::", 1)
            self.selected_cycle_id = cycle_id or None
            self.selected_task = task_name
            self.selected_log_key = None
            self._select_preferred_log(error=True)
            self.action_open_logs()

    def action_previous_cycle(self) -> None:
        self._move_cycle(-1)

    def action_next_cycle(self) -> None:
        self._move_cycle(1)

    def _move_cycle(self, delta: int) -> None:
        if not self.snapshot.cycles:
            return
        ids = [cycle.cycle_id for cycle in self.snapshot.cycles]
        try:
            current = ids.index(self.selected_cycle_id or "")
        except ValueError:
            current = 0
        target = max(0, min(len(ids) - 1, current + delta))
        if target == current:
            return
        self._select_cycle(ids[target])

    def action_next_view(self) -> None:
        self._move_view(1)

    def action_previous_view(self) -> None:
        self._move_view(-1)

    def _move_view(self, delta: int) -> None:
        views = self.query_one("#views", TabbedContent)
        current = views.active or _VIEW_IDS[0]
        index = _VIEW_IDS.index(current) if current in _VIEW_IDS else 0
        views.active = _VIEW_IDS[(index + delta) % len(_VIEW_IDS)]
        if views.active == "campaign":
            self._sync_campaign_cursor()

    def action_select_view(self, view_id: str) -> None:
        if view_id in _VIEW_IDS:
            self.query_one("#views", TabbedContent).active = view_id
            if view_id == "campaign":
                self._sync_campaign_cursor()

    def action_show_filter(self) -> None:
        field = self.query_one("#task-filter", Input)
        field.display = True
        field.focus()

    def action_escape_context(self) -> None:
        field = self.query_one("#task-filter", Input)
        if field.display or self.task_filter:
            field.value = ""
            field.display = False
            self.task_filter = ""
            self._tree_signature = None
            self._rebuild_tree(force=True)
            self.query_one("#task-tree", Tree).focus()
            return
        self.action_workflow_panel()

    def action_open_logs(self) -> None:
        if self.selected_task is not None:
            self.query_one("#views", TabbedContent).active = "logs"
            self._refresh_logs(force=True)

    def action_select_output(self) -> None:
        self._select_preferred_log(error=False)
        self._refresh_logs(force=True)

    def action_select_error(self) -> None:
        self._select_preferred_log(error=True)
        self._refresh_logs(force=True)

    def _select_preferred_log(self, *, error: bool) -> None:
        task = self._selected_task_snapshot()
        attempt = task.attempt if task is not None else None
        if attempt is None:
            self.selected_log_key = None
            return
        available = self._available_log_resources(task, attempt)
        order = _LOG_ERROR_ORDER if error else _LOG_ORDER
        self.selected_log_key = next((key for key in order if key in available), None)

    def action_toggle_follow(self) -> None:
        viewer = self.query_one("#log-viewer", TextFileViewer)
        viewer.set_follow(not viewer.state.follow)
        self._refresh_follow_button()

    def action_refresh_now(self) -> None:
        self.refresh_runtime(force=True)

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_inspect(self) -> None:
        body = self.query_one("#monitor-main")
        if body.has_class("narrow"):
            body.add_class("inspecting")

    def action_workflow_panel(self) -> None:
        self.query_one("#monitor-main").remove_class("inspecting")

    def refresh_runtime(self, *, force: bool = False) -> None:
        self.snapshot = self._load_snapshot()
        if self.selected_cycle_id and not any(
            cycle.cycle_id == self.selected_cycle_id for cycle in self.snapshot.cycles
        ):
            self._choose_initial_selection()
        self._rebuild_tree(force=force)
        self._refresh_header()
        self._refresh_date_nav()
        self._refresh_cycle_line()
        self._refresh_cycles()
        self._refresh_campaign()
        self._refresh_problems()
        self._refresh_inspector()
        self._refresh_period_matrix()
        self._refresh_follow_button()
        self._refresh_logs(force=force)

    def _refresh_header(self) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self.query_one("#summary", Static).update(
            f"[bold]{escape(self.snapshot.workflow_name)}[/bold]\n"
            f"{self.snapshot.completed_tasks}/{self.snapshot.total_tasks} tasks   "
            f"{self.snapshot.running_tasks} running   "
            f"{self.snapshot.failed_tasks} failed   "
            f"[green]● live[/green] [dim]{self.refresh_seconds:g}s · updated {now}[/dim]"
        )

    def _refresh_date_nav(self) -> None:
        previous = self.query_one("#prev-date", Button)
        current_button = self.query_one("#date-current", Button)
        following = self.query_one("#next-date", Button)
        label = self.query_one("#date-label", Static)
        dates = self._available_dates()
        selected = self._selected_date()
        if not dates or selected is None:
            current_button.label = "no cycle date"
            label.update("no cycle date")
            previous.disabled = True
            following.disabled = True
            current_button.disabled = True
            return
        text = selected.strftime("%d/%m/%Y")
        current_button.label = text
        label.update(text)
        current_button.disabled = False
        try:
            index = dates.index(selected)
        except ValueError:
            index = 0
        previous.disabled = index <= 0
        following.disabled = index >= len(dates) - 1

    def _refresh_cycle_line(self) -> None:
        self.cycle_slots.clear()
        selected_date = self._selected_date()
        cycles = self._cycles_for_date(selected_date)
        selected_index = 0
        for index, cycle in enumerate(cycles):
            if cycle.cycle_id == self.selected_cycle_id:
                selected_index = index
                break
        start = max(0, selected_index - (_CYCLE_SLOT_COUNT // 2))
        end = min(len(cycles), start + _CYCLE_SLOT_COUNT)
        start = max(0, end - _CYCLE_SLOT_COUNT)
        visible = cycles[start:end]

        for slot_index in range(_CYCLE_SLOT_COUNT):
            slot_id = f"cycle-slot-{slot_index}"
            button = self.query_one(f"#{slot_id}", Button)
            if slot_index >= len(visible):
                button.display = False
                button.disabled = True
                continue
            cycle = visible[slot_index]
            button.display = True
            button.disabled = False
            self.cycle_slots[slot_id] = cycle.cycle_id
            symbol = _STATUS.get(cycle.status, ("○", "", ""))[0]
            prefix = "▶ " if cycle.cycle_id == self.selected_cycle_id else ""
            button.label = f"{prefix}{symbol} {_format_cycle_hour(cycle.cycle_time)}"
            for status in _STATUS:
                button.remove_class(f"status-{status}")
            button.add_class(f"status-{cycle.status}")
            button.set_class(cycle.cycle_id == self.selected_cycle_id, "selected-cycle")

        previous = self.query_one("#cycle-prev", Button)
        following = self.query_one("#cycle-next", Button)
        if not self.snapshot.cycles or self.selected_cycle_id is None:
            previous.disabled = True
            following.disabled = True
            return
        ids = [cycle.cycle_id for cycle in self.snapshot.cycles]
        try:
            global_index = ids.index(self.selected_cycle_id)
        except ValueError:
            global_index = 0
        previous.disabled = global_index <= 0
        following.disabled = global_index >= len(ids) - 1

    def _refresh_cycles(self) -> None:
        table = self.query_one("#cycles-table", DataTable)
        table.clear(columns=False)
        for cycle in self.snapshot.cycles:
            table.add_row(
                _format_cycle_time(cycle.cycle_time),
                f"{cycle.completed_tasks}/{len(cycle.tasks)}",
                str(cycle.running_tasks),
                str(cycle.failed_tasks),
                str(cycle.pending_tasks),
                _status_markup(cycle.status, color=self.color_enabled),
                key=cycle.cycle_id,
            )

    @staticmethod
    def _aggregate_status(statuses: list[str]) -> str:
        if not statuses:
            return "pending"
        if any(status in _ATTENTION for status in statuses):
            return "failed"
        if "running" in statuses:
            return "running"
        if all(status in _COMPLETE for status in statuses):
            return "success"
        if any(status in _COMPLETE for status in statuses):
            return "partial"
        return "pending"

    def _refresh_period_matrix(self) -> None:
        title = self.query_one("#period-title", Label)
        table = self.query_one("#period-matrix", DataTable)
        table.clear(columns=True)

        selected_date = self._selected_date()
        if selected_date is None:
            title.update("PERÍODO / CICLAGEM")
            table.add_column("Process")
            return

        cycles = self._cycles_for_date(selected_date)
        title.update(f"PERÍODO / CICLAGEM · {selected_date.strftime('%d/%m/%Y')}")
        table.add_columns(
            "Process",
            *(_format_cycle_hour(cycle.cycle_time) for cycle in cycles),
        )

        discovered: list[str] = []
        statuses_by_cycle: list[dict[str, list[str]]] = []
        for cycle in cycles:
            by_process: dict[str, list[str]] = {}
            for task in cycle.tasks:
                process_step = _task_process_step(task.name, cycle)
                process = process_step[0] if process_step is not None else "Workflow"
                by_process.setdefault(process, []).append(task.status)
                if process not in discovered:
                    discovered.append(process)
            statuses_by_cycle.append(by_process)

        processes = [process for process in _PROCESS_ORDER if process in discovered]
        processes.extend(
            process for process in discovered if process not in _PROCESS_ORDER
        )

        for process in processes:
            row: list[str] = [process]
            for by_process in statuses_by_cycle:
                statuses = by_process.get(process, [])
                row.append(
                    _status_markup(
                        self._aggregate_status(statuses),
                        color=self.color_enabled,
                    )
                    if statuses
                    else "—"
                )
            table.add_row(*row, key=process)

        if not processes:
            table.add_row("Workflow", *("—" for _ in cycles), key="Workflow")

    def _refresh_campaign(self) -> None:
        summary = self.query_one("#campaign-summary", Static)
        table = self.query_one("#campaign-table", DataTable)
        table.clear(columns=False)
        run = self.snapshot.current_run
        summary.update(
            f"[bold]Campaign[/bold]  {escape(self.snapshot.workflow_name)}\n"
            f"{len(self.snapshot.cycles)} cycles · {self.snapshot.completed_tasks}/"
            f"{self.snapshot.total_tasks} tasks complete · "
            f"{self.snapshot.running_tasks} running · {self.snapshot.failed_tasks} failed\n"
            f"[dim]run {escape(run.run_id if run else '—')} · "
            f"{escape(run.status if run else '—')} · "
            f"instance {escape(self.snapshot.instance_id or '—')}[/dim]"
        )

        groups: dict[date, list[CycleSnapshot]] = {}
        for cycle in self.snapshot.cycles:
            current = _cycle_date(cycle.cycle_time)
            if current is not None:
                groups.setdefault(current, []).append(cycle)
        for current in sorted(groups):
            cycles = groups[current]
            tasks = [task for cycle in cycles for task in cycle.tasks]
            completed = sum(task.status in _COMPLETE for task in tasks)
            running = sum(task.status == "running" for task in tasks)
            failed = sum(task.status in _ATTENTION for task in tasks)
            pending = len(tasks) - completed - running - failed
            state = self._aggregate_status([cycle.status for cycle in cycles])
            hours = " ".join(_format_cycle_hour(cycle.cycle_time) for cycle in cycles)
            table.add_row(
                current.strftime("%d/%m/%Y"),
                hours,
                f"{completed}/{len(tasks)}",
                str(running),
                str(failed),
                str(pending),
                _status_markup(state, color=self.color_enabled),
                key=current.isoformat(),
            )
        self._sync_campaign_cursor()

    def _sync_campaign_cursor(self) -> None:
        try:
            table = self.query_one("#campaign-table", DataTable)
        except Exception:
            return
        selected = self._selected_date()
        if selected is None or table.row_count == 0:
            return
        dates = sorted(
            {
                current
                for cycle in self.snapshot.cycles
                if (current := _cycle_date(cycle.cycle_time)) is not None
            }
        )
        try:
            row = dates.index(selected)
        except ValueError:
            return
        table.move_cursor(row=row)

    def _refresh_problems(self) -> None:
        table = self.query_one("#problems-table", DataTable)
        table.clear(columns=False)
        for problem in self.snapshot.problems:
            key = f"{problem.cycle_id or ''}::{problem.task_name}"
            table.add_row(
                problem.cycle_id or "workflow",
                _task_label(problem.task_name, problem.cycle_id),
                _status_markup(problem.status, color=self.color_enabled),
                problem.reason or "See task details",
                key=key,
            )
        if table.row_count == 0:
            table.add_row("—", "No problems detected.", "", "")
        try:
            problems_tab = self.query_one("#--content-tab-problems", Tab)
            problems_tab.label = (
                f"Problemas {len(self.snapshot.problems)} !"
                if self.snapshot.problems
                else "Problemas"
            )
        except Exception:
            pass

    def _refresh_inspector(self) -> None:
        inspector = self.query_one("#inspector", TaskInspector)
        task = self._selected_task_snapshot()
        config_task = self.task_map.get(task.name, {}) if task is not None else {}
        inspector.set_task(
            task,
            config_task if isinstance(config_task, dict) else {},
        )

    def _selected_attempt(self) -> AttemptSnapshot | None:
        task = self._selected_task_snapshot()
        if task is None:
            return None
        try:
            inspector = self.query_one("#inspector", TaskInspector)
        except Exception:
            inspector = None
        if (
            inspector is not None
            and inspector.task_snapshot is not None
            and inspector.task_snapshot.name == task.name
            and inspector.task_snapshot.cycle_id == task.cycle_id
        ):
            return inspector.selected_attempt
        return task.attempt

    def _resources_for_attempt(
        self,
        task: TaskSnapshot,
        attempt: AttemptSnapshot,
    ) -> tuple[InspectableResource, ...]:
        config_task = self.task_map.get(task.name, {})
        return discover_attempt_resources(
            task,
            attempt,
            config_task if isinstance(config_task, dict) else {},
        )

    def _available_log_resources(
        self,
        task: TaskSnapshot | None,
        attempt: AttemptSnapshot | None,
    ) -> dict[str, InspectableResource]:
        if task is None or attempt is None:
            return {}
        return {
            resource.key: resource
            for resource in self._resources_for_attempt(task, attempt)
            if resource.key in _LOG_ORDER and resource.available
        }

    def _refresh_log_buttons(self, attempt: AttemptSnapshot | None) -> None:
        task = self._selected_task_snapshot()
        available = self._available_log_resources(task, attempt)
        for button_id, key in _LOG_BUTTONS.items():
            button = self.query_one(f"#{button_id}", Button)
            button.display = key in available
            button.set_class(key == self.selected_log_key, "selected-log")

    def _refresh_follow_button(self) -> None:
        button = self.query_one("#log-follow", Button)
        try:
            viewer = self.query_one("#log-viewer", TextFileViewer)
        except Exception:
            button.label = "FOLLOW ●"
            button.set_class(True, "following")
            return
        following = viewer.state.follow
        button.label = "FOLLOW ●" if following else "FOLLOW ‖"
        button.set_class(following, "following")

    def _select_log_resource(self, key: str | None, *, force: bool = True) -> None:
        task = self._selected_task_snapshot()
        attempt = self._selected_attempt()
        available = self._available_log_resources(task, attempt)
        viewer = self.query_one("#log-viewer", TextFileViewer)
        resource = available.get(key or "")
        if resource is None:
            viewer.open_resource(None)
            self.selected_log_key = None
            self._refresh_log_buttons(attempt)
            self._refresh_follow_button()
            return
        self.selected_log_key = resource.key
        if (
            viewer.state.resource is None
            or viewer.state.resource.path != resource.path
            or viewer.state.resource.key != resource.key
        ):
            viewer.open_resource(resource)
        elif force:
            viewer.reload(force=True)
        self._refresh_log_buttons(attempt)
        self._refresh_follow_button()

    def _refresh_logs(self, *, force: bool = False) -> None:
        title = self.query_one("#log-title", Static)
        task = self._selected_task_snapshot()
        attempt = self._selected_attempt()
        available = self._available_log_resources(task, attempt)
        title.update(f"[bold]{escape(self.selected_task or 'No task selected')}[/bold]")

        if self.selected_log_key not in available:
            self.selected_log_key = next(
                (key for key in _LOG_ORDER if key in available),
                None,
            )
        self._select_log_resource(self.selected_log_key, force=force)
        if self.selected_log_key is not None:
            resource = available.get(self.selected_log_key)
            if resource is not None:
                title.update(
                    f"[bold]{escape(self.selected_task or '')}[/bold]  "
                    f"[dim]{escape(resource.path.name)}[/dim]"
                )

    def on_task_inspector_open_resource(
        self,
        event: TaskInspector.OpenResource,
    ) -> None:
        self.push_screen(
            TextViewerScreen(
                event.resource,
                refresh_seconds=self.refresh_seconds,
            )
        )

    def on_task_inspector_copy_value(
        self,
        event: TaskInspector.CopyValue,
    ) -> None:
        self.copy_to_clipboard(event.value)


def run_monitor(
    config: dict[str, Any],
    workflow_path: str | Path,
    workdir: str | Path,
    *,
    refresh_seconds: float = 1.0,
    color: bool = True,
    completion_future: Future[int] | None = None,
) -> None:
    """Launch the interactive workflow monitor."""
    WorkflowTui(
        config=config,
        workflow_path=workflow_path,
        workdir=workdir,
        refresh_seconds=refresh_seconds,
        color=color,
        completion_future=completion_future,
    ).run()
