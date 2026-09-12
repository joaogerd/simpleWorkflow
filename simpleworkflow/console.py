"""Rich terminal presentation for simpleWorkflow."""

from __future__ import annotations

import os
import re
import sys
import time
from collections import Counter, OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol, TextIO

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from . import __version__

ColorMode = Literal["auto", "always", "never"]

_TASK_PATTERN = re.compile(
    r"^(?P<component>[A-Za-z][A-Za-z0-9]*?)(?P<hour>\d{2})_(?P<action>.+)$"
)

_ACTION_LABELS = {
    "prepare": "Prepare",
    "submit": "Submit",
    "wait": "Wait",
    "validate": "Validate",
    "gate": "Validation gate",
    "doctor": "Pre-check",
    "run": "Run",
}

_STATUS_RENDER = {
    "pending": ("○", "WAITING", "dim"),
    "running": ("●", "RUNNING", "bold cyan"),
    "success": ("✔", "SUCCESS", "green"),
    "failed": ("✘", "FAILED", "bold red"),
    "invalid-input": ("✘", "BAD INPUT", "bold red"),
    "invalid-output": ("✘", "BAD OUTPUT", "bold red"),
    "skipped": ("↷", "SKIPPED", "yellow"),
    "reused": ("↷", "REUSED", "green"),
    "rerun": ("↻", "RERUN", "yellow"),
}


@dataclass(frozen=True)
class TaskDisplay:
    """Human-facing metadata derived from a stable internal task name."""

    raw_name: str
    component: str | None
    hour: str | None
    action: str

    @property
    def stage(self) -> str | None:
        if self.component is None or self.hour is None:
            return None
        return f"{self.component} {self.hour}Z"


class WorkflowReporter(Protocol):
    """Minimal presentation interface consumed by the workflow engine."""

    def event(
        self,
        kind: str,
        task_name: str,
        message: str | None = None,
        *,
        executor: str | None = None,
    ) -> None:
        """Render one task lifecycle event."""
        ...

    def status_table(self, entries: Iterable[tuple[str, str]]) -> None:
        """Render current task states."""
        ...


class TerminalReporter:
    """Render a Rich live dashboard with a plain-log fallback.

    Interactive terminals use an ecFlow/Cylc-inspired dashboard: workflow hierarchy
    on the left and a cycle/status matrix on the right. Redirected output and
    ``--plain`` keep a stable linear representation suitable for logs and CI.
    """

    def __init__(
        self,
        color: ColorMode = "auto",
        stream: TextIO | None = None,
        *,
        verbose: bool = False,
        plain: bool = False,
    ) -> None:
        if color not in {"auto", "always", "never"}:
            raise ValueError(f"Unsupported color mode: {color!r}")

        self.stream = stream or sys.stdout
        self.color = color
        self.verbose = verbose
        self.plain = plain
        force_terminal: bool | None
        if color == "always":
            force_terminal = True
        elif color == "never":
            force_terminal = False
        else:
            force_terminal = bool(getattr(self.stream, "isatty", lambda: False)())

        self.console = Console(
            file=self.stream,
            force_terminal=force_terminal,
            color_system="standard" if force_terminal else None,
            no_color=color == "never" or bool(os.environ.get("NO_COLOR")),
            highlight=False,
            soft_wrap=False,
        )
        self._dashboard_enabled = not plain and (
            color == "always" or bool(getattr(self.stream, "isatty", lambda: False)())
        )

        self._workflow_name = "workflow"
        self._command = "run"
        self._workdir = ".simpleworkflow"
        self._mode = "normal"
        self._cycle_time: str | None = None
        self._task_names: list[str] = []
        self._task_states: OrderedDict[str, str] = OrderedDict()
        self._task_started: dict[str, float] = {}
        self._task_elapsed: dict[str, float] = {}
        self._task_messages: dict[str, str] = {}
        self._task_executors: dict[str, str] = {}
        self._event_counts: Counter[str] = Counter()
        self._active_task: str | None = None
        self._live: Live | None = None

    @staticmethod
    def _humanize_task(task_name: str) -> TaskDisplay:
        match = _TASK_PATTERN.fullmatch(task_name)
        if match is None:
            return TaskDisplay(
                raw_name=task_name,
                component=None,
                hour=None,
                action=task_name.replace("_", " ").replace("-", " ").title(),
            )

        action_raw = match.group("action")
        action = _ACTION_LABELS.get(
            action_raw,
            action_raw.replace("_", " ").replace("-", " ").title(),
        )
        return TaskDisplay(
            raw_name=task_name,
            component=match.group("component").upper(),
            hour=match.group("hour"),
            action=action,
        )

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        total = max(0, int(round(seconds)))
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def _status_parts(status: str) -> tuple[str, str, str]:
        return _STATUS_RENDER.get(status, ("•", status.upper(), "white"))

    def _status_markup(self, status: str) -> str:
        symbol, label, style = self._status_parts(status)
        return f"[{style}]{symbol} {label}[/{style}]"

    def _reset_view(self, task_names: Iterable[str] = ()) -> None:
        self._task_names = list(task_names)
        self._task_states = OrderedDict((name, "pending") for name in self._task_names)
        self._task_started.clear()
        self._task_elapsed.clear()
        self._task_messages.clear()
        self._task_executors.clear()
        self._event_counts.clear()
        self._active_task = None

    def workflow_header(
        self,
        *,
        command: str,
        workflow_name: str,
        workdir: str,
        cycle_time: str | None = None,
        mode: str = "normal",
        task_names: Iterable[str] = (),
    ) -> None:
        """Initialize presentation metadata for one workflow invocation."""
        self._workflow_name = workflow_name
        self._command = command
        self._workdir = workdir
        self._cycle_time = cycle_time
        self._mode = mode
        self._reset_view(task_names)

        if not self._dashboard_enabled:
            cycle = f" · {cycle_time}" if cycle_time else ""
            self.console.print(
                f"[bold cyan]━━ {command.title()} · {escape(workflow_name)}{cycle} ━━[/bold cyan]"
            )
            self.console.print(
                f"[dim]simpleWorkflow {__version__} · mode={escape(mode)} · "
                f"tasks={len(self._task_names)} · workdir={escape(workdir)}[/dim]"
            )

    def begin_run(self, entries: Iterable[tuple[str, str]]) -> None:
        """Seed existing state and start a live dashboard when interactive."""
        for task_name, status in entries:
            if task_name not in self._task_states:
                self._task_states[task_name] = status
                self._task_names.append(task_name)
            else:
                self._task_states[task_name] = status

        if self._dashboard_enabled and self._live is None:
            self._live = Live(
                self._render_dashboard(),
                console=self.console,
                refresh_per_second=4,
                transient=False,
            )
            self._live.start(refresh=True)

    def close(self) -> None:
        """Stop any active Rich live display."""
        if self._live is not None:
            self._live.stop()
            self._live = None

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.update(self._render_dashboard(), refresh=True)

    def _grouped_tasks(self) -> OrderedDict[str, list[str]]:
        groups: OrderedDict[str, list[str]] = OrderedDict()
        for task_name in self._task_names:
            display = self._humanize_task(task_name)
            key = display.stage or "Other"
            groups.setdefault(key, []).append(task_name)
        return groups

    def _task_tree_line(self, task_name: str) -> str:
        display = self._humanize_task(task_name)
        status = self._task_states.get(task_name, "pending")
        symbol, _label, style = self._status_parts(status)
        elapsed = self._task_elapsed.get(task_name)
        duration = f" [dim]({self._format_elapsed(elapsed)})[/dim]" if elapsed is not None else ""
        technical = f" [dim]task={escape(task_name)}[/dim]" if self.verbose else ""
        return f"[{style}]{symbol}[/{style}] {escape(display.action)}{duration}{technical}"

    def _build_tree(self) -> Tree:
        root = Tree(f"[bold blue]{escape(self._workflow_name)}[/bold blue]")
        for stage, task_names in self._grouped_tasks().items():
            stage_node = root.add(f"[bold yellow]{escape(stage)}[/bold yellow]")
            for task_name in task_names:
                stage_node.add(self._task_tree_line(task_name))
        return root

    @staticmethod
    def _aggregate_stage_status(statuses: list[str]) -> str:
        if any(status in {"failed", "invalid-input", "invalid-output"} for status in statuses):
            return "failed"
        if "running" in statuses:
            return "running"
        if "rerun" in statuses:
            return "rerun"
        if statuses and all(status in {"success", "reused", "skipped"} for status in statuses):
            return "success"
        return "pending"

    def _build_cycle_matrix(self) -> RenderableType:
        parsed = [self._humanize_task(name) for name in self._task_names]
        hours = sorted({item.hour for item in parsed if item.hour is not None}, key=int)
        components = list(
            OrderedDict.fromkeys(
                item.component for item in parsed if item.component is not None
            )
        )
        if not hours or not components:
            table = Table(show_header=True, header_style="bold cyan", expand=True)
            table.add_column("Task")
            table.add_column("State", justify="center")
            for task_name in self._task_names:
                display = self._humanize_task(task_name)
                table.add_row(
                    escape(display.action),
                    self._status_markup(self._task_states.get(task_name, "pending")),
                )
            return table

        table = Table(show_header=True, header_style="bold cyan", expand=True)
        table.add_column("Stage", style="bold white", no_wrap=True)
        for hour in hours:
            table.add_column(f"{hour}Z", justify="center", no_wrap=True)

        for component in components:
            row = [component]
            for hour in hours:
                matching = [
                    name
                    for name in self._task_names
                    if (
                        (display := self._humanize_task(name)).component == component
                        and display.hour == hour
                    )
                ]
                if not matching:
                    row.append("[dim]—[/dim]")
                    continue
                statuses = [self._task_states.get(name, "pending") for name in matching]
                row.append(self._status_markup(self._aggregate_stage_status(statuses)))
            table.add_row(*row)
        return table

    def _header_panel(self) -> Panel:
        progress = Counter(self._task_states.values())
        completed = sum(
            1
            for status in self._task_states.values()
            if status in {"success", "reused", "skipped"}
        )
        failed = sum(
            1
            for status in self._task_states.values()
            if status in {"failed", "invalid-input", "invalid-output"}
        )
        details = Table.grid(expand=True)
        details.add_column(ratio=3)
        details.add_column(justify="right", ratio=2)
        left = (
            f"[bold]{escape(self._command.upper())}[/bold]  "
            f"[dim]mode={escape(self._mode)} · simpleWorkflow {__version__}[/dim]"
        )
        if self._cycle_time:
            left += f"  [dim]cycle={escape(self._cycle_time)}[/dim]"
        right = (
            f"[green]{completed}/{len(self._task_states)} complete[/green]  "
            f"[red]{failed} failed[/red]  [cyan]{progress['running']} running[/cyan]"
        )
        details.add_row(left, right)
        return Panel(details, title="Workflow", border_style="blue")

    def _footer_panel(self) -> Panel:
        if self._active_task is None:
            text = f"[dim]workdir: {escape(self._workdir)}[/dim]"
            return Panel(text, title="Current activity", border_style="dim")

        display = self._humanize_task(self._active_task)
        text = f"[bold cyan]{escape(display.stage or 'Task')}[/bold cyan] · {escape(display.action)}"
        message = self._task_messages.get(self._active_task)
        if self.verbose and message:
            text += f"\n[dim]{escape(message)}[/dim]"
        return Panel(text, title="Current activity", border_style="cyan")

    def _render_dashboard(self) -> RenderableType:
        hierarchy = Panel(
            self._build_tree(),
            title="Execution hierarchy",
            border_style="blue",
            padding=(0, 1),
        )
        matrix = Panel(
            self._build_cycle_matrix(),
            title="Cycle status",
            border_style="cyan",
            padding=(0, 1),
        )

        if self.console.width >= 110:
            body = Table.grid(expand=True)
            body.add_column(ratio=1)
            body.add_column(ratio=2)
            body.add_row(hierarchy, matrix)
            body_renderable: RenderableType = body
        else:
            body_renderable = Group(hierarchy, matrix)

        return Group(self._header_panel(), body_renderable, self._footer_panel())

    @staticmethod
    def _friendly_message(kind: str, message: str | None) -> str | None:
        if message is None:
            return None
        if kind == "skip" and message == "already successful":
            return None
        if kind == "rerun" and message == "dependency executed again":
            return "upstream step ran again"
        if kind == "rerun" and message == "task signature changed":
            return "inputs or configuration changed"
        return message

    def _linear_event(
        self,
        kind: str,
        task_name: str,
        message: str | None,
        executor: str | None,
    ) -> None:
        display = self._humanize_task(task_name)
        stage = f"{display.stage} · " if display.stage else ""
        status = self._task_states.get(task_name, "pending")
        symbol, label, style = self._status_parts(status)
        line = f"[{style}]{symbol} {label:<8}[/{style}] {escape(stage + display.action)}"
        if self.verbose:
            details = [f"task={task_name}"]
            if executor:
                details.append(f"executor={executor}")
            line += f" [dim]{escape(' · '.join(details))}"
            if message:
                line += f" · {escape(message)}"
            line += "[/dim]"
        else:
            friendly = self._friendly_message(kind, message)
            if kind == "fail" and friendly:
                line += f" [red]— {escape(friendly)}[/red]"
        self.console.print(line)

    def event(
        self,
        kind: str,
        task_name: str,
        message: str | None = None,
        *,
        executor: str | None = None,
    ) -> None:
        """Update dashboard state from one engine lifecycle event."""
        self._event_counts[kind] += 1
        if task_name not in self._task_states:
            self._task_names.append(task_name)
            self._task_states[task_name] = "pending"
        if message:
            self._task_messages[task_name] = message
        if executor:
            self._task_executors[task_name] = executor

        now = time.monotonic()
        if kind == "run":
            self._task_states[task_name] = "running"
            self._task_started[task_name] = now
            self._active_task = task_name
        elif kind == "ok":
            self._task_states[task_name] = "success"
            started = self._task_started.pop(task_name, None)
            if started is not None:
                self._task_elapsed[task_name] = now - started
            if self._active_task == task_name:
                self._active_task = None
        elif kind == "fail":
            self._task_states[task_name] = "failed"
            started = self._task_started.pop(task_name, None)
            if started is not None:
                self._task_elapsed[task_name] = now - started
            self._active_task = task_name
        elif kind == "skip":
            self._task_states[task_name] = (
                "reused" if message == "already successful" else "skipped"
            )
        elif kind == "rerun":
            self._task_states[task_name] = "rerun"
            self._active_task = task_name
        elif kind == "plan":
            self._task_states[task_name] = "pending"

        if self._live is not None:
            self._refresh()
        else:
            self._linear_event(kind, task_name, message, executor)

    def plan_view(self, task_names: Iterable[str]) -> None:
        """Render dependency-resolved execution order as a hierarchy."""
        names = list(task_names)
        self._reset_view(names)
        if self._dashboard_enabled:
            self.console.print(self._render_dashboard())
            return

        tree = self._build_tree()
        self.console.print(Panel(tree, title="Execution plan", border_style="cyan"))

    def plan_item(self, index: int, task_name: str) -> None:
        """Compatibility helper for older callers."""
        del index
        if task_name not in self._task_states:
            self._task_names.append(task_name)
            self._task_states[task_name] = "pending"

    def status_table(self, entries: Iterable[tuple[str, str]]) -> None:
        """Render the current workflow state as hierarchy plus cycle matrix."""
        rows = list(entries)
        self._reset_view(name for name, _ in rows)
        for name, status in rows:
            self._task_states[name] = status
        self.console.print(self._render_dashboard())

    def run_summary(
        self,
        entries: Iterable[tuple[str, str]],
        *,
        elapsed_seconds: float,
        exit_code: int,
    ) -> None:
        """Stop the live dashboard and render a concise final result."""
        rows = list(entries)
        for name, status in rows:
            self._task_states[name] = status
        self.close()

        counts: Counter[str] = Counter(status for _, status in rows)
        failed = counts["failed"] + counts["invalid-input"] + counts["invalid-output"]
        success = exit_code == 0 and failed == 0
        title = "SUCCESS" if success else "FAILED"
        border = "green" if success else "red"
        next_step = (
            "Workflow complete."
            if success
            else "Fix the failing step and rerun the same workflow; validated steps will be reused."
        )
        summary = Table.grid(padding=(0, 1))
        summary.add_column(style="bold")
        summary.add_column()
        summary.add_row("Tasks", f"{counts['success']} success · {failed} failed · {counts['pending']} pending")
        summary.add_row(
            "This run",
            f"{self._event_counts['ok']} executed · {self._event_counts['skip']} reused/skipped · {self._event_counts['rerun']} rerun",
        )
        summary.add_row("Elapsed", self._format_elapsed(elapsed_seconds))
        summary.add_row("Next", next_step)
        self.console.print(Panel(summary, title=f"Result · {title}", border_style=border))

    def note(self, message: str) -> None:
        """Render neutral informational text outside the live dashboard."""
        if self._live is not None:
            self._task_messages[self._active_task or ""] = message
            self._refresh()
        else:
            self.console.print(f"[dim]{escape(message)}[/dim]")
