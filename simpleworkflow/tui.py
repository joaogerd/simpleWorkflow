"""Interactive Textual monitor for simpleWorkflow runtime state."""

from __future__ import annotations

import json
from collections import Counter, OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Label, RichLog, Static, Tree

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
        """Return useful stdout/stderr paths in display priority order."""
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


def _latest_attempt(workdir: Path, task_name: str) -> AttemptSnapshot | None:
    """Locate the newest immutable attempt directory for ``task_name``."""
    runs_root = workdir / "runs"
    if not runs_root.is_dir():
        return None

    task_directory = _task_directory_name(task_name)
    for run_dir in sorted(
        (path for path in runs_root.iterdir() if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    ):
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
    """Read the tail of one UTF-8-ish text file without failing on bad bytes."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max_lines:])


class WorkflowTui(App[None]):
    """Full-screen monitor for a materialized simpleWorkflow workflow."""

    CSS = """
    Screen {
        background: #111318;
        color: #d7dae0;
    }

    #summary {
        height: 4;
        padding: 0 1;
        border-bottom: heavy #3b82f6;
        background: #171a21;
    }

    #main {
        height: 1fr;
    }

    #left {
        width: 38%;
        min-width: 38;
        border-right: heavy #303744;
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
        height: 12;
        padding: 1;
        border-bottom: solid #303744;
        background: #171a21;
    }

    #log {
        height: 1fr;
        background: #0d0f13;
        padding: 0 1;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh_now", "Refresh"),
        ("c", "clear_log", "Clear log"),
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
        self.selected_task = self.plan[0] if self.plan else None
        self.task_nodes: dict[str, Any] = {}
        self._last_log_signature: tuple[str, int, int] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="summary")
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Label(" WORKFLOW", classes="pane-title")
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
        yield Footer()

    def on_mount(self) -> None:
        self._populate_tree()
        self.refresh_runtime()
        self.set_interval(self.refresh_seconds, self.refresh_runtime)

    def on_unmount(self) -> None:
        self.engine.state.close()

    @staticmethod
    def _status_markup(status: str) -> str:
        symbol, label, style = _STATUS.get(status, ("•", status.upper(), "white"))
        return f"[{style}]{symbol} {label}[/{style}]"

    def _task_label(self, task_name: str, status: str) -> str:
        display = TerminalReporter._humanize_task(task_name)
        return f"{self._status_markup(status)}  {escape(display.action)}"

    def _populate_tree(self) -> None:
        tree = self.query_one("#task-tree", Tree)
        tree.root.expand()
        groups: OrderedDict[str, list[str]] = OrderedDict()
        for task_name in self.plan:
            display = TerminalReporter._humanize_task(task_name)
            groups.setdefault(display.stage or "Tasks", []).append(task_name)

        for stage, task_names in groups.items():
            group = tree.root.add(f"[bold yellow]{escape(stage)}[/bold yellow]", expand=True)
            for task_name in task_names:
                state = self.engine.state.get_status(self.workflow_name, task_name) or "pending"
                node = group.add_leaf(
                    self._task_label(task_name, state),
                    data=task_name,
                )
                self.task_nodes[task_name] = node

        if self.selected_task is not None:
            node = self.task_nodes.get(self.selected_task)
            if node is not None:
                tree.select_node(node)

    def on_tree_node_selected(self, event: Tree.NodeSelected[str]) -> None:
        data = event.node.data
        if isinstance(data, str) and data in self.task_map:
            self.selected_task = data
            self._last_log_signature = None
            self._refresh_inspector()
            self._refresh_log(force=True)

    def action_refresh_now(self) -> None:
        self.refresh_runtime()

    def action_clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()
        self._last_log_signature = None

    def refresh_runtime(self) -> None:
        """Refresh persisted task states and the selected task details."""
        statuses: dict[str, str] = {}
        for task_name in self.plan:
            status = self.engine.state.get_status(self.workflow_name, task_name) or "pending"
            statuses[task_name] = status
            node = self.task_nodes.get(task_name)
            if node is not None:
                node.set_label(self._task_label(task_name, status))

        counts = Counter(statuses.values())
        completed = sum(
            1 for status in statuses.values() if status in {"success", "skipped"}
        )
        failed = sum(
            1
            for status in statuses.values()
            if status in {"failed", "invalid-input", "invalid-output"}
        )
        now = datetime.now().strftime("%H:%M:%S")
        summary = self.query_one("#summary", Static)
        summary.update(
            f"[bold cyan]{escape(self.workflow_name)}[/bold cyan]\n"
            f"[green]{completed}/{len(self.plan)} complete[/green]  │  "
            f"[cyan]{counts['running']} running[/cyan]  │  "
            f"[red]{failed} failed[/red]  │  "
            f"[dim]{counts['pending']} waiting  ·  updated {now}[/dim]"
        )
        self._refresh_inspector()
        self._refresh_log()

    def _refresh_inspector(self) -> None:
        inspector = self.query_one("#inspector", Static)
        if self.selected_task is None:
            inspector.update("[dim]No task selected.[/dim]")
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

        resources: list[str] = []
        if pbs:
            for key in ("queue", "walltime", "select", "ncpus", "mpiprocs", "omp_threads"):
                if key in pbs:
                    resources.append(f"{key}={pbs[key]}")

        lines = [
            f"[bold yellow]{escape(display.stage or 'Task')} · {escape(display.action)}[/bold yellow]",
            f"Internal name : [bold]{escape(self.selected_task)}[/bold]",
            f"State         : {self._status_markup(status)}",
            f"Executor      : {escape(attempt_executor or executor)}",
            f"Return code   : {state.return_code if state and state.return_code is not None else '—'}",
            f"PBS Job ID    : {escape(job_id) if job_id else '—'}",
        ]
        if resources:
            lines.append(f"Resources     : {escape('  '.join(resources))}")
        if attempt is not None:
            lines.append(f"Attempt dir   : {escape(str(attempt.directory))}")
        inspector.update("\n".join(lines))

    def _refresh_log(self, *, force: bool = False) -> None:
        log = self.query_one("#log", RichLog)
        if self.selected_task is None:
            return
        attempt = _latest_attempt(self.workdir, self.selected_task)
        if attempt is None:
            if force:
                log.clear()
                log.write("No runtime log is available for this task yet.")
            return

        paths = attempt.preferred_log_paths()
        if not paths:
            if force:
                log.clear()
                log.write(f"Attempt exists at {attempt.directory}, but its logs are empty.")
            return

        signature_parts: list[str] = []
        for path in paths:
            try:
                stat = path.stat()
            except OSError:
                continue
            signature_parts.extend([str(path), str(stat.st_size), str(stat.st_mtime_ns)])
        signature = (
            "|".join(signature_parts),
            sum(path.stat().st_size for path in paths if path.exists()),
            len(paths),
        )
        if not force and signature == self._last_log_signature:
            return
        self._last_log_signature = signature

        log.clear()
        for path in paths:
            log.write(f"--- {path.name} ---")
            content = _tail(path)
            log.write(content or "(empty)")


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
