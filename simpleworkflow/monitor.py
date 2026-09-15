"""Read-only presentation model for workflow monitoring.

The monitor layer deliberately owns presentation-oriented aggregation.  It reads
schema-1 state through :class:`WorkflowState` and never mutates workflow state.
Textual and other frontends consume the immutable snapshots defined here rather
than issuing SQL or reconstructing workflow semantics themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class TaskSnapshot:
    """Current persisted state of one task in one optional cycle."""

    name: str
    status: str
    cycle_id: str | None = None
    return_code: int | None = None
    reason: str | None = None
    attempt_path: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class CycleSnapshot:
    """Aggregated state for one explicit workflow cycle."""

    cycle_id: str
    cycle_time: str
    tasks: tuple[TaskSnapshot, ...]
    status: str
    updated_at: str | None = None

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
        if self.cycles:
            return tuple(task for cycle in self.cycles for task in cycle.tasks)
        return self.tasks

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



def _task_names(config: dict[str, Any]) -> tuple[str, ...]:
    raw_tasks = config.get("tasks", [])
    if not isinstance(raw_tasks, list):
        return ()
    names: list[str] = []
    for task in raw_tasks:
        if isinstance(task, dict) and isinstance(task.get("name"), str):
            names.append(task["name"])
    return tuple(names)


def _task_snapshot(
    name: str,
    row: tuple[Any, ...] | None,
    *,
    cycle_id: str | None,
) -> TaskSnapshot:
    if row is None:
        return TaskSnapshot(name=name, status="pending", cycle_id=cycle_id)
    return TaskSnapshot(
        name=name,
        status=str(row[0]),
        cycle_id=cycle_id,
        return_code=row[1],
        reason=row[2],
        attempt_path=row[3],
        updated_at=row[4],
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


def load_monitor_snapshot(
    config: dict[str, Any],
    workflow_path: str | Path,
    workdir: str | Path,
) -> MonitorSnapshot:
    """Build a monitor snapshot from configuration and existing persisted state.

    Missing state is represented as an all-pending workflow and is never created
    by this function.  Existing state is opened read-only.
    """

    workflow = Path(workflow_path).resolve(strict=False)
    state_dir = Path(workdir).resolve(strict=False)
    workflow_name = str(config.get("workflow", {}).get("name", "workflow"))
    names = _task_names(config)
    state_path = state_dir / "state.sqlite3"

    if not state_path.is_file():
        pending = tuple(_task_snapshot(name, None, cycle_id=None) for name in names)
        return MonitorSnapshot(
            workflow_name=workflow_name,
            instance_id=None,
            workflow_path=workflow,
            workdir=state_dir,
            updated_at=None,
            tasks=pending,
            cycles=(),
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
        for cycle_id, cycle_time, cycle_updated_at in cycle_rows:
            task_rows = rows_for_cycle(str(cycle_id))
            cycle_tasks = tuple(
                _task_snapshot(name, task_rows.get(name), cycle_id=str(cycle_id))
                for name in names
            )
            cycles.append(
                CycleSnapshot(
                    cycle_id=str(cycle_id),
                    cycle_time=str(cycle_time),
                    tasks=cycle_tasks,
                    status=_cycle_status(cycle_tasks),
                    updated_at=_max_timestamp(
                        str(cycle_updated_at) if cycle_updated_at else None,
                        *(task.updated_at for task in cycle_tasks),
                    ),
                )
            )

        root_rows = rows_for_cycle("")
        root_tasks = tuple(
            _task_snapshot(name, root_rows.get(name), cycle_id=None) for name in names
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

        visible_tasks = (
            tuple(task for cycle in cycles for task in cycle.tasks) if cycles else root_tasks
        )
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
