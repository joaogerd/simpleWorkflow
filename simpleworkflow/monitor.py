"""Read-only presentation model for workflow monitoring.

The monitor layer deliberately owns presentation-oriented aggregation. It reads
schema-1 state through :class:`WorkflowState` and never mutates workflow state.
Textual and other frontends consume immutable snapshots rather than issuing SQL
or reconstructing workflow semantics themselves.

Persisted ``cycle_state`` is preferred whenever the workflow uses the native
0.4 cycle dimension. Some scientific workflows are deliberately *unrolled* so
cross-cycle dependencies are real task edges inside one engine invocation. For
those workflows, cycle grouping is presentation metadata reconstructed from the
configured ``--cycle`` arguments and dependency inheritance while task status
still comes exclusively from the root SQLite task state.

Attempt rows are loaded from SQLite in one query. Filesystem provenance is read
lazily from an attempt only when the Inspector or Logs view asks for it; this
keeps the normal one-second monitor refresh inexpensive on shared HPC storage.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .state import WorkflowState

_COMPLETE_STATES = frozenset({"success", "skipped"})
_ATTENTION_STATES = frozenset(
    {
        "failed",
        "invalid-input",
        "invalid-output",
        "blocked",
        "interrupted",
        "unknown",
    }
)


def _read_json(path: Path) -> dict[str, Any] | None:
    """Read an optional JSON mapping without making monitoring fragile."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class AttemptSnapshot:
    """Persisted identity plus lazily read provenance for one task attempt."""

    run_id: str
    task_name: str
    cycle_id: str | None
    attempt: int
    status: str
    return_code: int | None
    reason: str | None
    directory: Path
    started_at: str | None
    finished_at: str | None

    @property
    def started_record(self) -> dict[str, Any] | None:
        return _read_json(self.directory / "started.json")

    @property
    def metadata(self) -> dict[str, Any] | None:
        return _read_json(self.directory / "metadata.json")

    @property
    def scheduler(self) -> dict[str, Any] | None:
        return _read_json(self.directory / "scheduler.json")

    @property
    def command_record(self) -> dict[str, Any]:
        metadata = _mapping(self.metadata)
        command = metadata.get("command")
        if isinstance(command, dict):
            return command
        started = _mapping(self.started_record)
        return _mapping(started.get("command"))

    @property
    def command(self) -> tuple[str, ...] | None:
        raw = self.command_record.get("argv")
        if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            return None
        return tuple(raw)

    @property
    def cwd(self) -> str | None:
        raw = self.command_record.get("cwd")
        return str(raw) if raw else None

    @property
    def execution(self) -> dict[str, Any]:
        metadata = _mapping(self.metadata)
        execution = metadata.get("execution")
        if isinstance(execution, dict):
            return execution
        return _mapping(self.scheduler)

    @property
    def executor(self) -> str | None:
        raw = self.execution.get("executor")
        return str(raw) if raw else None

    @property
    def job_id(self) -> str | None:
        raw = self.execution.get("job_id")
        return str(raw) if raw else None

    @property
    def log_paths(self) -> dict[str, Path]:
        execution = self.execution
        pbs_stdout = execution.get("job_stdout")
        pbs_stderr = execution.get("job_stderr")
        return {
            "stdout": self.directory / "stdout.log",
            "stderr": self.directory / "stderr.log",
            "pbs_stdout": (
                Path(str(pbs_stdout)) if pbs_stdout else self.directory / "pbs.stdout.log"
            ),
            "pbs_stderr": (
                Path(str(pbs_stderr)) if pbs_stderr else self.directory / "pbs.stderr.log"
            ),
        }

    @property
    def available_logs(self) -> dict[str, Path]:
        available: dict[str, Path] = {}
        for name, path in self.log_paths.items():
            try:
                if path.is_file():
                    available[name] = path
            except OSError:
                continue
        return available


@dataclass(frozen=True)
class TaskSnapshot:
    """Current persisted state of one task in one optional presentation cycle."""

    name: str
    status: str
    cycle_id: str | None = None
    return_code: int | None = None
    reason: str | None = None
    attempt_path: str | None = None
    updated_at: str | None = None
    attempt: AttemptSnapshot | None = None


@dataclass(frozen=True)
class CycleSnapshot:
    """Aggregated state for one persisted or presentation-derived cycle."""

    cycle_id: str
    cycle_time: str
    tasks: tuple[TaskSnapshot, ...]
    status: str
    updated_at: str | None = None
    persisted: bool = True

    @property
    def completed_tasks(self) -> int:
        return sum(task.status in _COMPLETE_STATES for task in self.tasks)

    @property
    def running_tasks(self) -> int:
        return sum(task.status == "running" for task in self.tasks)

    @property
    def failed_tasks(self) -> int:
        return sum(task.status in _ATTENTION_STATES for task in self.tasks)

    @property
    def pending_tasks(self) -> int:
        return len(self.tasks) - self.completed_tasks - self.running_tasks - self.failed_tasks


@dataclass(frozen=True)
class RunSnapshot:
    """One persisted workflow invocation."""

    run_id: str
    cycle_id: str | None
    run_path: str
    status: str
    created_at: str
    finished_at: str | None


@dataclass(frozen=True)
class ProblemSnapshot:
    """Current workflow condition that deserves operator attention."""

    task_name: str
    status: str
    cycle_id: str | None
    reason: str | None
    return_code: int | None
    attempt_path: str | None
    updated_at: str | None


@dataclass(frozen=True)
class MonitorSnapshot:
    """Immutable read model consumed by interactive monitoring frontends."""

    workflow_name: str
    instance_id: str | None
    workflow_path: Path
    workdir: Path
    updated_at: str | None
    tasks: tuple[TaskSnapshot, ...]
    cycles: tuple[CycleSnapshot, ...]
    runs: tuple[RunSnapshot, ...]
    problems: tuple[ProblemSnapshot, ...]

    @property
    def current_run(self) -> RunSnapshot | None:
        running = next((run for run in self.runs if run.status == "running"), None)
        return running or (self.runs[0] if self.runs else None)

    @property
    def all_tasks(self) -> tuple[TaskSnapshot, ...]:
        cycle_tasks = tuple(task for cycle in self.cycles for task in cycle.tasks)
        return cycle_tasks + self.tasks

    @property
    def total_tasks(self) -> int:
        return len(self.all_tasks)

    @property
    def completed_tasks(self) -> int:
        return sum(task.status in _COMPLETE_STATES for task in self.all_tasks)

    @property
    def running_tasks(self) -> int:
        return sum(task.status == "running" for task in self.all_tasks)

    @property
    def failed_tasks(self) -> int:
        return sum(task.status in _ATTENTION_STATES for task in self.all_tasks)


@dataclass(frozen=True)
class _ConfigCycle:
    cycle_id: str
    cycle_time: str
    sort_key: datetime


def _config_tasks(config: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    raw_tasks = config.get("tasks", [])
    if not isinstance(raw_tasks, list):
        return ()
    return tuple(task for task in raw_tasks if isinstance(task, dict))


def _task_names(config: dict[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    for task in _config_tasks(config):
        if isinstance(task.get("name"), str):
            names.append(task["name"])
    return tuple(names)


def _parse_config_cycle(task: dict[str, Any]) -> _ConfigCycle | None:
    """Extract an explicit ISO ``--cycle`` argument for presentation grouping."""
    argv = task.get("argv")
    if not isinstance(argv, list):
        return None
    try:
        index = argv.index("--cycle")
    except ValueError:
        return None
    if index + 1 >= len(argv) or not isinstance(argv[index + 1], str):
        return None
    raw = argv[index + 1]
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    utc = parsed.astimezone(timezone.utc)
    return _ConfigCycle(
        cycle_id=utc.strftime("%Y%m%d%H"),
        cycle_time=utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        sort_key=utc,
    )


def _presentation_cycles(
    config: dict[str, Any],
) -> tuple[dict[str, _ConfigCycle], dict[str, list[str]]]:
    """Group unrolled tasks without creating a second execution-state model.

    Explicit ``--cycle`` values establish presentation groups. A task without an
    explicit cycle inherits one only after every dependency is already assigned
    and those dependencies all point to the same cycle. Any global, unresolved,
    missing or cross-cycle dependency keeps the task outside cycle presentation.
    """
    tasks = _config_tasks(config)
    by_name = {
        str(task["name"]): task
        for task in tasks
        if isinstance(task.get("name"), str)
    }
    assignment: dict[str, _ConfigCycle] = {}
    for name, task in by_name.items():
        cycle = _parse_config_cycle(task)
        if cycle is not None:
            assignment[name] = cycle

    changed = True
    while changed:
        changed = False
        for name, task in by_name.items():
            if name in assignment:
                continue
            dependencies = task.get("depends_on", []) or []
            if isinstance(dependencies, str):
                dependencies = [dependencies]
            if not isinstance(dependencies, list) or not dependencies:
                continue
            dependency_names = [str(dependency) for dependency in dependencies]
            if not all(dependency in assignment for dependency in dependency_names):
                continue
            inherited = {assignment[dependency] for dependency in dependency_names}
            if len(inherited) == 1:
                assignment[name] = next(iter(inherited))
                changed = True

    cycles = {cycle.cycle_id: cycle for cycle in assignment.values()}
    groups: dict[str, list[str]] = {
        cycle_id: []
        for cycle_id, _ in sorted(cycles.items(), key=lambda item: item[1].sort_key)
    }
    for task in tasks:
        task_name = task.get("name")
        if not isinstance(task_name, str):
            continue
        cycle = assignment.get(task_name)
        if cycle is not None:
            groups[cycle.cycle_id].append(task_name)
    return assignment, groups


def _task_snapshot(
    name: str,
    row: tuple[Any, ...] | None,
    *,
    cycle_id: str | None,
    attempt: AttemptSnapshot | None = None,
) -> TaskSnapshot:
    if row is None:
        return TaskSnapshot(name=name, status="pending", cycle_id=cycle_id, attempt=attempt)
    return TaskSnapshot(
        name=name,
        status=str(row[0]),
        cycle_id=cycle_id,
        return_code=row[1],
        reason=row[2],
        attempt_path=row[3],
        updated_at=row[4],
        attempt=attempt,
    )


def _cycle_status(tasks: tuple[TaskSnapshot, ...]) -> str:
    if any(task.status in _ATTENTION_STATES for task in tasks):
        return "failed"
    if any(task.status == "running" for task in tasks):
        return "running"
    if tasks and all(task.status in _COMPLETE_STATES for task in tasks):
        return "success"
    if any(task.status in _COMPLETE_STATES for task in tasks):
        return "partial"
    return "pending"


def _max_timestamp(*values: str | None) -> str | None:
    present = [value for value in values if value]
    return max(present) if present else None


def _latest_attempts(state: WorkflowState) -> dict[tuple[str, str], AttemptSnapshot]:
    rows = state.connection.execute(
        """
        SELECT run_id, cycle_id, task, attempt, status, return_code, reason,
               attempt_path, started_at, finished_at
        FROM attempt_history
        ORDER BY cycle_id, task, COALESCE(started_at, '') DESC, run_id DESC, attempt DESC
        """
    ).fetchall()
    attempts: dict[tuple[str, str], AttemptSnapshot] = {}
    for row in rows:
        key = (str(row[1] or ""), str(row[2]))
        if key in attempts:
            continue
        directory = state.resolve_path(str(row[7]))
        if directory is None:
            continue
        attempts[key] = AttemptSnapshot(
            run_id=str(row[0]),
            cycle_id=str(row[1]) if row[1] else None,
            task_name=str(row[2]),
            attempt=int(row[3]),
            status=str(row[4]),
            return_code=row[5],
            reason=str(row[6]) if row[6] else None,
            directory=directory,
            started_at=str(row[8]) if row[8] else None,
            finished_at=str(row[9]) if row[9] else None,
        )
    return attempts


def load_monitor_snapshot(
    config: dict[str, Any],
    workflow_path: str | Path,
    workdir: str | Path,
) -> MonitorSnapshot:
    """Build a monitor snapshot from configuration and existing persisted state.

    Missing state is represented as an all-pending workflow and is never created
    by this function. Existing state is opened read-only.
    """

    workflow = Path(workflow_path).resolve(strict=False)
    state_dir = Path(workdir).resolve(strict=False)
    workflow_name = str(config.get("workflow", {}).get("name", "workflow"))
    names = _task_names(config)
    config_assignment, config_groups = _presentation_cycles(config)
    config_cycles = {
        cycle.cycle_id: cycle for cycle in config_assignment.values()
    }
    state_path = state_dir / "state.sqlite3"

    if not state_path.is_file():
        if config_groups:
            pending_cycles = tuple(
                CycleSnapshot(
                    cycle_id=cycle_id,
                    cycle_time=config_cycles[cycle_id].cycle_time,
                    tasks=tuple(
                        _task_snapshot(name, None, cycle_id=cycle_id)
                        for name in task_names
                    ),
                    status="pending",
                    persisted=False,
                )
                for cycle_id, task_names in config_groups.items()
            )
            grouped_names = set(config_assignment)
            pending_root_tasks = tuple(
                _task_snapshot(name, None, cycle_id=None)
                for name in names
                if name not in grouped_names
            )
        else:
            pending_cycles = ()
            pending_root_tasks = tuple(
                _task_snapshot(name, None, cycle_id=None) for name in names
            )
        return MonitorSnapshot(
            workflow_name=workflow_name,
            instance_id=None,
            workflow_path=workflow,
            workdir=state_dir,
            updated_at=None,
            tasks=pending_root_tasks,
            cycles=pending_cycles,
            runs=(),
            problems=(),
        )

    state = WorkflowState(
        state_path,
        workflow_name=workflow_name,
        source_path=workflow,
        read_only=True,
    )
    try:
        instance = state.instance
        connection = state.connection
        attempts = _latest_attempts(state)

        cycle_rows = connection.execute(
            """
            SELECT cycle_id, cycle_time, updated_at
            FROM cycle_state
            ORDER BY cycle_time, cycle_id
            """
        ).fetchall()

        def rows_for_cycle(cycle_key: str) -> dict[str, tuple[Any, ...]]:
            rows = connection.execute(
                """
                SELECT task, status, return_code, reason, attempt_path, updated_at
                FROM task_state
                WHERE cycle_id = ?
                ORDER BY task
                """,
                (cycle_key,),
            ).fetchall()
            return {
                str(row[0]): (row[1], row[2], row[3], row[4], row[5]) for row in rows
            }

        cycles: list[CycleSnapshot] = []
        root_rows = rows_for_cycle("")
        root_tasks: tuple[TaskSnapshot, ...]

        if cycle_rows:
            for cycle_id, cycle_time, cycle_updated_at in cycle_rows:
                cycle_key = str(cycle_id)
                task_rows = rows_for_cycle(cycle_key)
                cycle_tasks = tuple(
                    _task_snapshot(
                        name,
                        task_rows.get(name),
                        cycle_id=cycle_key,
                        attempt=attempts.get((cycle_key, name)),
                    )
                    for name in names
                )
                cycles.append(
                    CycleSnapshot(
                        cycle_id=cycle_key,
                        cycle_time=str(cycle_time),
                        tasks=cycle_tasks,
                        status=_cycle_status(cycle_tasks),
                        updated_at=_max_timestamp(
                            str(cycle_updated_at) if cycle_updated_at else None,
                            *(task.updated_at for task in cycle_tasks),
                        ),
                        persisted=True,
                    )
                )
            # Native cycle execution stores these task names per cycle. Root rows
            # from an older/no-cycle invocation must not be counted a second time.
            root_tasks = ()
        elif config_groups:
            for cycle_id, task_names in config_groups.items():
                cycle_tasks = tuple(
                    _task_snapshot(
                        name,
                        root_rows.get(name),
                        cycle_id=cycle_id,
                        attempt=attempts.get(("", name)),
                    )
                    for name in task_names
                )
                cycles.append(
                    CycleSnapshot(
                        cycle_id=cycle_id,
                        cycle_time=config_cycles[cycle_id].cycle_time,
                        tasks=cycle_tasks,
                        status=_cycle_status(cycle_tasks),
                        updated_at=_max_timestamp(
                            *(task.updated_at for task in cycle_tasks)
                        ),
                        persisted=False,
                    )
                )
            grouped_names = set(config_assignment)
            root_tasks = tuple(
                _task_snapshot(
                    name,
                    root_rows.get(name),
                    cycle_id=None,
                    attempt=attempts.get(("", name)),
                )
                for name in names
                if name not in grouped_names
            )
        else:
            root_tasks = tuple(
                _task_snapshot(
                    name,
                    root_rows.get(name),
                    cycle_id=None,
                    attempt=attempts.get(("", name)),
                )
                for name in names
            )

        run_rows = connection.execute(
            """
            SELECT run_id, cycle_id, run_path, status, created_at, finished_at
            FROM run_history
            ORDER BY created_at DESC, run_id DESC
            """
        ).fetchall()
        runs = tuple(
            RunSnapshot(
                run_id=str(row[0]),
                cycle_id=str(row[1]) if row[1] else None,
                run_path=str(row[2]),
                status=str(row[3]),
                created_at=str(row[4]),
                finished_at=str(row[5]) if row[5] else None,
            )
            for row in run_rows
        )

        visible_tasks = tuple(task for cycle in cycles for task in cycle.tasks) + root_tasks
        problems = tuple(
            ProblemSnapshot(
                task_name=task.name,
                status=task.status,
                cycle_id=task.cycle_id,
                reason=task.reason,
                return_code=task.return_code,
                attempt_path=task.attempt_path,
                updated_at=task.updated_at,
            )
            for task in visible_tasks
            if task.status in _ATTENTION_STATES
        )

        updated_at = _max_timestamp(
            instance.updated_at,
            *(cycle.updated_at for cycle in cycles),
            *(task.updated_at for task in root_tasks),
            *(run.finished_at or run.created_at for run in runs),
        )
        return MonitorSnapshot(
            workflow_name=instance.workflow_name,
            instance_id=instance.instance_id,
            workflow_path=workflow,
            workdir=state_dir,
            updated_at=updated_at,
            tasks=root_tasks,
            cycles=tuple(cycles),
            runs=runs,
            problems=problems,
        )
    finally:
        state.close()
