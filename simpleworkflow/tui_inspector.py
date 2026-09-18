"""Compact task/attempt inspector for the simpleWorkflow TUI."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Collapsible, DataTable, Static

from .monitor import AttemptSnapshot, TaskSnapshot
from .tui_resources import InspectableResource, discover_attempt_resources


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
}


@dataclass(frozen=True)
class InspectorContext:
    """Current task identity plus selected attempt index."""

    task_name: str | None
    cycle_id: str | None
    attempt_index: int = 0


def _elapsed(started_at: str | None, finished_at: str | None) -> float | None:
    if not started_at:
        return None
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finished = (
            datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
            if finished_at
            else datetime.now(started.tzinfo)
        )
    except ValueError:
        return None
    return max(0.0, (finished - started).total_seconds())


def _format_duration(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _status_markup(status: str, *, color: bool) -> tuple[str, str]:
    symbol, label, style = _STATUS.get(status, ("•", status.upper(), "white"))
    plain = f"{symbol} {label}"
    return plain, f"[{style}]{plain}[/{style}]" if color else plain


def _dependencies(config_task: dict[str, Any]) -> str | None:
    raw = config_task.get("depends_on", []) or []
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list) and raw:
        return ", ".join(str(value) for value in raw)
    return None


def _pbs_resources(config_task: dict[str, Any]) -> str | None:
    if config_task.get("executor", "local") != "pbs":
        return None
    pbs = config_task.get("pbs")
    if not isinstance(pbs, dict):
        return "PBS"
    parts: list[str] = []
    for key, label in (
        ("queue", "queue"),
        ("select", "nodes"),
        ("ncpus", "cpus"),
        ("mpiprocs", "ranks"),
        ("walltime", "walltime"),
    ):
        if pbs.get(key) is not None:
            parts.append(f"{label} {pbs[key]}")
    return " · ".join(parts) or "PBS"


class TaskInspector(Vertical):
    """Contextual task inspector with attempts and inspectable resources."""

    class OpenResource(Message):
        def __init__(self, resource: InspectableResource) -> None:
            super().__init__()
            self.resource = resource

    class CopyValue(Message):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    BINDINGS = [
        Binding("[", "previous_attempt", "Older attempt"),
        Binding("]", "next_attempt", "Newer attempt"),
        Binding("c", "copy_selected", "Copy"),
    ]

    DEFAULT_CSS = """
    TaskInspector {
        height: auto;
        max-height: 16;
        padding: 0 1;
        background: #0d0f13;
    }
    #inspector-primary {
        height: auto;
        max-height: 8;
        padding: 0 1;
    }
    #attempt-controls {
        height: 2;
        min-height: 2;
        padding: 0 1;
        align: left middle;
    }
    #attempt-prev, #attempt-next {
        width: 3;
        min-width: 3;
        height: 1;
        min-height: 1;
        padding: 0;
        border: none;
        background: #111318;
        color: #9fb9ff;
    }
    #attempt-label {
        width: 1fr;
        height: 1;
        content-align: left middle;
        color: #8c93a1;
        padding-left: 1;
    }
    #open-logs {
        width: auto;
        min-width: 10;
        height: 1;
        min-height: 1;
        padding: 0 1;
        border: none;
        background: #111318;
        color: #67e8f9;
    }
    #inspector-resources {
        height: auto;
        max-height: 5;
        min-height: 0;
        margin: 0;
    }
    #inspector-details {
        height: auto;
        max-height: 8;
        margin: 0;
        padding: 0;
    }
    #inspector-details-table {
        height: auto;
        max-height: 6;
        min-height: 0;
    }
    """

    def __init__(self, *, color: bool = True, id: str | None = None) -> None:
        super().__init__(id=id)
        self.color_enabled = color
        self.task_snapshot: TaskSnapshot | None = None
        self.config_task: dict[str, Any] = {}
        self.context = InspectorContext(None, None, 0)
        self.resources: tuple[InspectableResource, ...] = ()
        self.detail_values: dict[str, str] = {}
        self.primary_text = ""
        self.attempt_label = "No attempt"
        self._resource_keys: list[str] = []
        self._detail_keys: list[str] = []

    @property
    def selected_attempt(self) -> AttemptSnapshot | None:
        if self.task_snapshot is None or not self.task_snapshot.attempts:
            return None
        index = max(0, min(self.context.attempt_index, len(self.task_snapshot.attempts) - 1))
        return self.task_snapshot.attempts[index]

    def compose(self) -> ComposeResult:
        yield Static("No task selected.", id="inspector-primary")
        with Horizontal(id="attempt-controls"):
            yield Button("‹", id="attempt-prev")
            yield Static("No attempt", id="attempt-label")
            yield Button("›", id="attempt-next")
            yield Button("Logs", id="open-logs")
        yield DataTable(
            id="inspector-resources",
            cursor_type="row",
            zebra_stripes=False,
        )
        with Collapsible(title="Details", collapsed=True, id="inspector-details"):
            yield DataTable(
                id="inspector-details-table",
                cursor_type="row",
                zebra_stripes=False,
            )

    def on_mount(self) -> None:
        self._configure_tables()
        self._render()

    def _configure_tables(self) -> None:
        resources = self.query_one("#inspector-resources", DataTable)
        if not resources.columns:
            resources.add_columns("File", "State")
        details = self.query_one("#inspector-details-table", DataTable)
        if not details.columns:
            details.add_columns("Field", "Value")

    def set_task(
        self,
        task: TaskSnapshot | None,
        config_task: dict[str, Any] | None = None,
    ) -> None:
        previous_attempt = self.selected_attempt
        same_task = (
            self.task_snapshot is not None
            and task is not None
            and self.task_snapshot.name == task.name
            and self.task_snapshot.cycle_id == task.cycle_id
        )
        self.task_snapshot = task
        self.config_task = config_task if isinstance(config_task, dict) else {}
        index = 0
        if same_task and previous_attempt is not None and task is not None:
            key = (previous_attempt.run_id, previous_attempt.attempt)
            for candidate_index, candidate in enumerate(task.attempts):
                if (candidate.run_id, candidate.attempt) == key:
                    index = candidate_index
                    break
        self.context = InspectorContext(
            task.name if task else None,
            task.cycle_id if task else None,
            index,
        )
        self._render()

    def _render(self) -> None:
        try:
            self._configure_tables()
            primary = self.query_one("#inspector-primary", Static)
        except Exception:
            return

        if self.task_snapshot is None:
            self.primary_text = "No task selected."
            primary.update("[dim]No task selected.[/dim]")
            self.resources = ()
            self.detail_values = {}
            self._refresh_attempt_controls()
            self._refresh_resources()
            self._refresh_details()
            return

        attempt = self.selected_attempt
        backend = (
            attempt.executor
            if attempt is not None and attempt.executor
            else str(self.config_task.get("executor", "local"))
        )
        scope = self.task_snapshot.cycle_id or "workflow"
        status_plain, status_markup = _status_markup(
            self.task_snapshot.status,
            color=self.color_enabled,
        )
        plain_fields: list[tuple[str, str]] = [
            ("task", self.task_snapshot.name),
            ("status", status_plain),
            ("scope", scope),
            ("backend", backend),
        ]
        markup_fields: list[tuple[str, str]] = [
            ("task", escape(self.task_snapshot.name)),
            ("status", status_markup),
            ("scope", escape(scope)),
            ("backend", escape(backend)),
        ]

        if attempt is not None:
            duration = _format_duration(_elapsed(attempt.started_at, attempt.finished_at))
            if duration:
                plain_fields.append(("elapsed", duration))
                markup_fields.append(("elapsed", duration))
            if attempt.job_id:
                plain_fields.append(("PBS job", attempt.job_id))
                markup_fields.append(("PBS job", escape(attempt.job_id)))
        return_code = (
            self.task_snapshot.return_code
            if self.task_snapshot.return_code is not None
            else attempt.return_code if attempt is not None else None
        )
        if return_code is not None:
            plain_fields.append(("return", str(return_code)))
            markup_fields.append(("return", str(return_code)))
        reason = self.task_snapshot.reason or (attempt.reason if attempt is not None else None)
        if reason and self.task_snapshot.status in {
            "failed",
            "invalid-input",
            "invalid-output",
            "blocked",
            "interrupted",
            "unknown",
        }:
            plain_fields.append(("reason", reason))
            markup_fields.append(("reason", escape(reason)))

        self.primary_text = "\n".join(
            f"{name:<9} {value}" for name, value in plain_fields
        )
        primary.update(
            "\n".join(
                f"[dim]{name:<9}[/dim] {value}" for name, value in markup_fields
            )
        )

        self.resources = (
            discover_attempt_resources(self.task_snapshot, attempt, self.config_task)
            if attempt is not None
            else ()
        )
        self.detail_values = self._build_details(attempt)
        self._refresh_attempt_controls()
        self._refresh_resources()
        self._refresh_details()

    def _build_details(self, attempt: AttemptSnapshot | None) -> dict[str, str]:
        if self.task_snapshot is None:
            return {}
        details: dict[str, str] = {}
        if attempt is not None:
            if attempt.command:
                details["command"] = shlex.join(attempt.command)
            if attempt.cwd:
                details["working directory"] = attempt.cwd
            details["run id"] = attempt.run_id
            details["attempt path"] = str(attempt.directory)
            if attempt.started_at:
                details["started"] = attempt.started_at
            if attempt.finished_at:
                details["finished"] = attempt.finished_at
        dependencies = _dependencies(self.config_task)
        if dependencies:
            details["dependencies"] = dependencies
        outputs = self.config_task.get("outputs")
        if outputs is not None:
            details["outputs"] = str(outputs)
        pbs = _pbs_resources(self.config_task)
        if pbs:
            details["resources"] = pbs
        return details

    def _refresh_attempt_controls(self) -> None:
        try:
            previous = self.query_one("#attempt-prev", Button)
            following = self.query_one("#attempt-next", Button)
            label = self.query_one("#attempt-label", Static)
            logs = self.query_one("#open-logs", Button)
        except Exception:
            return
        attempts = self.task_snapshot.attempts if self.task_snapshot is not None else ()
        if not attempts:
            self.attempt_label = "No attempt"
            label.update(self.attempt_label)
            previous.disabled = True
            following.disabled = True
            logs.disabled = True
            logs.label = "Logs"
            return
        index = self.context.attempt_index
        attempt = attempts[index]
        self.attempt_label = f"Attempt {attempt.attempt} · {index + 1}/{len(attempts)}"
        label.update(self.attempt_label)
        previous.disabled = index >= len(attempts) - 1
        following.disabled = index <= 0
        available_logs = [
            resource
            for resource in self.resources
            if resource.key in {"stdout", "stderr", "pbs_stdout", "pbs_stderr"}
            and resource.available
        ]
        logs.disabled = not available_logs
        logs.label = f"Logs ({len(available_logs)})" if available_logs else "Logs"

    def _refresh_resources(self) -> None:
        try:
            table = self.query_one("#inspector-resources", DataTable)
        except Exception:
            return
        table.clear(columns=False)
        self._resource_keys = []
        for resource in self.resources:
            self._resource_keys.append(resource.key)
            table.add_row(
                resource.label,
                "ready" if resource.available else "missing",
                key=resource.key,
            )
        table.display = bool(self.resources)

    def _refresh_details(self) -> None:
        try:
            table = self.query_one("#inspector-details-table", DataTable)
        except Exception:
            return
        table.clear(columns=False)
        self._detail_keys = []
        for key, value in self.detail_values.items():
            self._detail_keys.append(key)
            table.add_row(key, value, key=key)

    def _select_attempt(self, index: int) -> None:
        if self.task_snapshot is None or not self.task_snapshot.attempts:
            return
        target = max(0, min(len(self.task_snapshot.attempts) - 1, index))
        if target == self.context.attempt_index:
            return
        self.context = InspectorContext(
            self.task_snapshot.name,
            self.task_snapshot.cycle_id,
            target,
        )
        self._render()

    def action_previous_attempt(self) -> None:
        self._select_attempt(self.context.attempt_index + 1)

    def action_next_attempt(self) -> None:
        self._select_attempt(self.context.attempt_index - 1)

    def focus_resource(self, key: str) -> bool:
        if key not in self._resource_keys:
            return False
        table = self.query_one("#inspector-resources", DataTable)
        table.move_cursor(row=self._resource_keys.index(key))
        return True

    def focus_detail(self, key: str) -> bool:
        if key not in self._detail_keys:
            return False
        collapsible = self.query_one("#inspector-details", Collapsible)
        collapsible.collapsed = False
        table = self.query_one("#inspector-details-table", DataTable)
        table.move_cursor(row=self._detail_keys.index(key))
        return True

    def _selected_resource(self) -> InspectableResource | None:
        try:
            table = self.query_one("#inspector-resources", DataTable)
        except Exception:
            return None
        row = table.cursor_row
        if row < 0 or row >= len(self._resource_keys):
            return None
        key = self._resource_keys[row]
        return next((item for item in self.resources if item.key == key), None)

    def _selected_detail_value(self) -> str | None:
        try:
            table = self.query_one("#inspector-details-table", DataTable)
        except Exception:
            return None
        row = table.cursor_row
        if row < 0 or row >= len(self._detail_keys):
            return None
        return self.detail_values.get(self._detail_keys[row])

    def action_copy_selected(self) -> None:
        focused = self.app.focused
        if isinstance(focused, DataTable) and focused.id == "inspector-resources":
            resource = self._selected_resource()
            if resource is not None:
                self.post_message(self.CopyValue(str(resource.path)))
            return
        if isinstance(focused, DataTable) and focused.id == "inspector-details-table":
            value = self._selected_detail_value()
            if value:
                self.post_message(self.CopyValue(value))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "attempt-prev":
            self.action_previous_attempt()
        elif event.button.id == "attempt-next":
            self.action_next_attempt()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "inspector-resources":
            return
        resource = self._selected_resource()
        if resource is not None and resource.available:
            self.post_message(self.OpenResource(resource))
