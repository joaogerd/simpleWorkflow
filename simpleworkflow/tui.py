"""Professional Textual monitor backed by the persisted workflow read model."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, RichLog, Static, TabbedContent, TabPane, Tree

from .monitor import CycleSnapshot, MonitorSnapshot, TaskSnapshot, load_monitor_snapshot

_STATUS = {
    "pending": ("○", "PENDING", "dim"),
    "stale": ("↻", "STALE", "yellow"),
    "running": ("●", "RUNNING", "cyan"),
    "success": ("✓", "SUCCESS", "green"),
    "failed": ("!", "FAILED", "red"),
    "invalid-input": ("!", "BAD INPUT", "red"),
    "invalid-output": ("!", "BAD OUTPUT", "red"),
    "blocked": ("!", "BLOCKED", "red"),
    "interrupted": ("!", "INTERRUPTED", "yellow"),
    "unknown": ("?", "UNKNOWN", "yellow"),
    "skipped": ("–", "SKIPPED", "dim"),
}
_ATTENTION = {"failed", "invalid-input", "invalid-output", "blocked", "interrupted", "unknown"}
_COMPLETE = {"success", "skipped"}
_VIEW_IDS = ("monitor", "cycles", "campaign", "problems", "logs")

_HELP_TEXT = """[bold]simpleWorkflow monitor[/bold]

↑ / ↓        select task
← / →        previous / next cycle
Enter        inspect on narrow terminals
Tab          next view
Shift+Tab    previous view
1..5         Monitor / Ciclos / Campanha / Problemas / Logs
l            logs for selected task
r            refresh
?            help
q            close monitor

The monitor is read-only. Closing it never cancels the workflow.
[dim]Esc closes this help.[/dim]"""


class HelpScreen(ModalScreen[None]):
    CSS = """
    HelpScreen { align: center middle; background: rgba(0, 0, 0, 55%); }
    #help-dialog {
        width: 68; height: auto; max-height: 30; padding: 1 2;
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


def _task_label(name: str) -> str:
    return name.replace("_", " ")


def _status_markup(status: str, *, color: bool = True) -> str:
    symbol, label, style = _STATUS.get(status, ("•", status.upper(), "white"))
    if not color:
        return f"{symbol} {label}"
    return f"[{style}]{symbol} {label}[/{style}]"


def _format_cycle_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%d %HZ")


class WorkflowTui(App[None]):
    """Full-screen, read-only monitor for one logical workflow instance."""

    CSS = """
    Screen { background: #0d0f13; color: #d7dae0; }
    #topbar {
        height: 4; padding: 0 1; border-bottom: solid #303744; background: #111318;
    }
    #summary { width: 1fr; height: 3; content-align: left middle; }
    #current-cycle { width: 28; height: 3; text-align: right; content-align: right middle; color: #9fb9ff; }
    #cycle-line { height: 2; padding: 0 1; background: #171a21; content-align: left middle; }
    TabbedContent { height: 1fr; }
    #monitor-main { height: 1fr; }
    #left { width: 48%; min-width: 28; border-right: solid #303744; background: #0f1116; }
    #right { width: 52%; background: #0d0f13; }
    #monitor-main.narrow { layout: vertical; }
    #monitor-main.narrow #left { width: 1fr; min-width: 1; height: 1fr; border-right: none; }
    #monitor-main.narrow #right { display: none; }
    #monitor-main.narrow.inspecting #left { display: none; }
    #monitor-main.narrow.inspecting #right { display: block; width: 1fr; height: 1fr; }
    .pane-title { height: 2; padding: 0 1; color: #9fb9ff; text-style: bold; content-align: left middle; }
    #task-tree { height: 1fr; padding: 0 1; }
    #inspector { height: 1fr; padding: 1 2; }
    #cycles-table, #problems-table { height: 1fr; margin: 1 0; }
    #campaign-view { height: 1fr; padding: 1 2; }
    #log-title { height: 2; padding: 0 1; border-bottom: solid #303744; color: #9fb9ff; content-align: left middle; }
    #full-log { height: 1fr; padding: 1; background: #0d0f13; }
    #shortcut-line { height: 1; padding: 0 1; border-top: solid #252b35; background: #111318; color: #697180; }
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
        ("l", "open_logs", "Logs"),
        ("r", "refresh_now", "Refresh"),
        ("enter", "inspect", "Inspect"),
        ("escape", "workflow_panel", "Workflow"),
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
    ) -> None:
        super().__init__()
        self.config = config
        self.workflow_path = Path(workflow_path).resolve(strict=False)
        self.workdir = Path(workdir).resolve(strict=False)
        self.refresh_seconds = max(0.5, float(refresh_seconds))
        self.color_enabled = bool(color) and not bool(os.environ.get("NO_COLOR"))
        self.task_order = _task_names(config)
        self.snapshot = self._load_snapshot()
        self.selected_cycle_id: str | None = None
        self.selected_task: str | None = None
        self.task_nodes: dict[tuple[str | None, str], Any] = {}
        self._tree_signature: tuple[Any, ...] | None = None
        self._choose_initial_selection()

    def _load_snapshot(self) -> MonitorSnapshot:
        return load_monitor_snapshot(self.config, self.workflow_path, self.workdir)

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static(id="summary")
            yield Static(id="current-cycle")
        yield Static(id="cycle-line")
        with TabbedContent(initial="monitor", id="views"):
            with TabPane("Monitor", id="monitor"):
                with Horizontal(id="monitor-main"):
                    with Vertical(id="left"):
                        yield Label("WORKFLOW", classes="pane-title")
                        yield Tree(self.snapshot.workflow_name, id="task-tree")
                    with Vertical(id="right"):
                        yield Label("INSPECTOR", classes="pane-title")
                        yield Static(id="inspector")
            with TabPane("Ciclos", id="cycles"):
                yield DataTable(id="cycles-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Campanha", id="campaign"):
                yield Static(id="campaign-view")
            with TabPane("Problemas", id="problems"):
                yield DataTable(id="problems-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Logs", id="logs"):
                yield Static(id="log-title")
                yield RichLog(id="full-log", highlight=False, markup=False, wrap=False, max_lines=1500)
        yield Static(
            "↑↓ navigate   ←→ cycle   Enter inspect   Tab switch   l logs   r refresh   ? help   q quit",
            id="shortcut-line",
        )

    def on_mount(self) -> None:
        self._configure_tables()
        self._apply_responsive_layout()
        self.refresh_runtime(force=True)
        self.set_interval(self.refresh_seconds, self.refresh_runtime)

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
                    (cycle for cycle in self.snapshot.cycles if cycle.status in {"partial", "pending"}),
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
            (cycle for cycle in self.snapshot.cycles if cycle.cycle_id == self.selected_cycle_id),
            None,
        )

    def _selected_task_snapshot(self) -> TaskSnapshot | None:
        cycle = self._selected_cycle()
        tasks = cycle.tasks if cycle is not None else self.snapshot.tasks
        return next((task for task in tasks if task.name == self.selected_task), None)

    def _tree_state_signature(self) -> tuple[Any, ...]:
        return (
            self.selected_cycle_id,
            tuple(
                (cycle.cycle_id, tuple((task.name, task.status) for task in cycle.tasks))
                for cycle in self.snapshot.cycles
            ),
            tuple((task.name, task.status) for task in self.snapshot.tasks),
        )

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
            for cycle in self.snapshot.cycles:
                symbol = _STATUS.get(cycle.status, ("•", "", ""))[0]
                label = f"{symbol} {_format_cycle_time(cycle.cycle_time)}"
                node = tree.root.add(label, expand=cycle.cycle_id == self.selected_cycle_id)
                for task in cycle.tasks:
                    symbol = _STATUS.get(task.status, ("•", "", ""))[0]
                    leaf = node.add_leaf(
                        f"{symbol} {_task_label(task.name)}",
                        data=(cycle.cycle_id, task.name),
                    )
                    self.task_nodes[(cycle.cycle_id, task.name)] = leaf
        else:
            for task in self.snapshot.tasks:
                symbol = _STATUS.get(task.status, ("•", "", ""))[0]
                leaf = tree.root.add_leaf(
                    f"{symbol} {_task_label(task.name)}",
                    data=(None, task.name),
                )
                self.task_nodes[(None, task.name)] = leaf

        key = (self.selected_cycle_id, self.selected_task or "")
        selected = self.task_nodes.get(key)
        if selected is not None:
            tree.select_node(selected)

    def on_tree_node_selected(self, event: Tree.NodeSelected[object]) -> None:
        data = event.node.data
        if not isinstance(data, tuple) or len(data) != 2:
            return
        cycle_id, task_name = data
        if task_name not in self.task_order:
            return
        self.selected_cycle_id = str(cycle_id) if cycle_id is not None else None
        self.selected_task = str(task_name)
        self._refresh_inspector()
        self._refresh_logs(force=True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "cycles-table":
            cycle_id = str(event.row_key.value)
            cycle = next((item for item in self.snapshot.cycles if item.cycle_id == cycle_id), None)
            if cycle is None:
                return
            self.selected_cycle_id = cycle_id
            self.selected_task = self._preferred_task(cycle.tasks)
            self._tree_signature = None
            self._rebuild_tree(force=True)
            self.query_one("#views", TabbedContent).active = "monitor"
            self._refresh_inspector()
        elif event.data_table.id == "problems-table":
            value = event.row_key.value
            if not isinstance(value, str) or "::" not in value:
                return
            cycle_id, task_name = value.split("::", 1)
            self.selected_cycle_id = cycle_id or None
            self.selected_task = task_name
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
        cycle = self.snapshot.cycles[target]
        self.selected_cycle_id = cycle.cycle_id
        self.selected_task = self._preferred_task(cycle.tasks)
        self._tree_signature = None
        self.refresh_runtime(force=True)

    def action_next_view(self) -> None:
        self._move_view(1)

    def action_previous_view(self) -> None:
        self._move_view(-1)

    def _move_view(self, delta: int) -> None:
        views = self.query_one("#views", TabbedContent)
        current = views.active or _VIEW_IDS[0]
        index = _VIEW_IDS.index(current) if current in _VIEW_IDS else 0
        views.active = _VIEW_IDS[(index + delta) % len(_VIEW_IDS)]

    def action_select_view(self, view_id: str) -> None:
        if view_id in _VIEW_IDS:
            self.query_one("#views", TabbedContent).active = view_id

    def action_open_logs(self) -> None:
        if self.selected_task is not None:
            self.query_one("#views", TabbedContent).active = "logs"
            self._refresh_logs(force=True)

    def action_refresh_now(self) -> None:
        self.refresh_runtime(force=True)

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_inspect(self) -> None:
        body = self.query_one("#monitor-main")
        if body.has_class("narrow"):
            body.add_class("inspecting")

    def action_workflow_panel(self) -> None:
        body = self.query_one("#monitor-main")
        body.remove_class("inspecting")

    def refresh_runtime(self, *, force: bool = False) -> None:
        self.snapshot = self._load_snapshot()
        if self.selected_cycle_id and not any(
            cycle.cycle_id == self.selected_cycle_id for cycle in self.snapshot.cycles
        ):
            self._choose_initial_selection()
        self._rebuild_tree(force=force)
        self._refresh_header()
        self._refresh_cycle_line()
        self._refresh_cycles()
        self._refresh_campaign()
        self._refresh_problems()
        self._refresh_inspector()
        self._refresh_logs(force=force)

    def _refresh_header(self) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self.query_one("#summary", Static).update(
            f"[bold]{escape(self.snapshot.workflow_name)}[/bold]\n"
            f"{self.snapshot.completed_tasks}/{self.snapshot.total_tasks} tasks   "
            f"{self.snapshot.running_tasks} running   "
            f"{self.snapshot.failed_tasks} failed   [dim]updated {now}[/dim]"
        )
        cycle = self._selected_cycle()
        self.query_one("#current-cycle", Static).update(
            escape(_format_cycle_time(cycle.cycle_time)) if cycle else "[dim]no cycle[/dim]"
        )

    def _refresh_cycle_line(self) -> None:
        line = self.query_one("#cycle-line", Static)
        if not self.snapshot.cycles:
            line.update("[dim]No explicit cycles in this workflow.[/dim]")
            return
        ids = [cycle.cycle_id for cycle in self.snapshot.cycles]
        try:
            center = ids.index(self.selected_cycle_id or "")
        except ValueError:
            center = 0
        start = max(0, center - 2)
        end = min(len(ids), start + 5)
        start = max(0, end - 5)
        parts: list[str] = []
        for cycle in self.snapshot.cycles[start:end]:
            symbol = {
                "success": "✓",
                "running": "●",
                "failed": "!",
                "partial": "◐",
                "pending": "○",
            }.get(cycle.status, "○")
            label = _format_cycle_time(cycle.cycle_time)
            text = f"{symbol} {label}"
            if cycle.cycle_id == self.selected_cycle_id:
                text = f"[reverse]{escape(text)}[/reverse]"
            else:
                text = escape(text)
            parts.append(text)
        line.update("  ──  ".join(parts))

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

    def _refresh_campaign(self) -> None:
        view = self.query_one("#campaign-view", Static)
        if not self.snapshot.cycles:
            view.update("[dim]No cycle campaign is recorded yet.[/dim]")
            return
        lines = ["[bold]Campaign[/bold]", ""]
        for cycle in self.snapshot.cycles:
            lines.append(
                f"{escape(_format_cycle_time(cycle.cycle_time)):<20} "
                f"{_status_markup(cycle.status, color=self.color_enabled)}   "
                f"{cycle.completed_tasks}/{len(cycle.tasks)} done"
            )
        view.update("\n".join(lines))

    def _refresh_problems(self) -> None:
        table = self.query_one("#problems-table", DataTable)
        table.clear(columns=False)
        for problem in self.snapshot.problems:
            key = f"{problem.cycle_id or ''}::{problem.task_name}"
            table.add_row(
                problem.cycle_id or "—",
                _task_label(problem.task_name),
                _status_markup(problem.status, color=self.color_enabled),
                problem.reason or "See task details",
                key=key,
            )
        if table.row_count == 0:
            table.add_row("—", "No problems detected.", "", "")

    def _refresh_inspector(self) -> None:
        inspector = self.query_one("#inspector", Static)
        task = self._selected_task_snapshot()
        if task is None:
            inspector.update("[dim]No task selected.[/dim]")
            return
        fields = [
            ("task", escape(task.name)),
            ("cycle", escape(task.cycle_id or "—")),
            ("status", _status_markup(task.status, color=self.color_enabled)),
        ]
        if task.return_code is not None:
            fields.append(("return code", str(task.return_code)))
        if task.updated_at:
            fields.append(("updated", escape(task.updated_at)))
        if task.reason:
            fields.append(("reason", escape(task.reason)))
        if task.attempt_path:
            fields.append(("attempt", escape(task.attempt_path)))
        inspector.update("\n\n".join(f"[dim]{name:<12}[/dim] {value}" for name, value in fields))

    def _refresh_logs(self, *, force: bool = False) -> None:
        title = self.query_one("#log-title", Static)
        log = self.query_one("#full-log", RichLog)
        title.update(f"[bold]{escape(self.selected_task or 'No task selected')}[/bold]")
        if not force:
            return
        log.clear()
        task = self._selected_task_snapshot()
        if task is None or not task.attempt_path:
            log.write("No runtime log is available for this task yet.")
            return
        log.write(f"Attempt: {task.attempt_path}")
        log.write("Log file discovery is available when attempt provenance is present.")


def run_monitor(
    config: dict[str, Any],
    workflow_path: str | Path,
    workdir: str | Path,
    *,
    refresh_seconds: float = 1.0,
    color: bool = True,
) -> None:
    """Launch the interactive workflow monitor."""
    WorkflowTui(
        config=config,
        workflow_path=workflow_path,
        workdir=workdir,
        refresh_seconds=refresh_seconds,
        color=color,
    ).run()
