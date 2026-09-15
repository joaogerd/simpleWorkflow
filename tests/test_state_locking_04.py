from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from simpleworkflow.config import load_workflow
from simpleworkflow.engine import WorkflowEngine
from simpleworkflow.locking import WorkflowLock, WorkflowLockedError
from simpleworkflow.migrations import migrate_state
from simpleworkflow.state import WorkflowState

FIXTURES = Path(__file__).parent / "fixtures"


def test_reset_uses_same_lock_as_run(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: locked}\ntasks: []\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="locked",
        source_path=workflow,
    )
    state.set_status("analysis", "success", 0)
    state.close()
    engine = WorkflowEngine(load_workflow(workflow))

    with WorkflowLock(workdir, "locked"):
        with pytest.raises(WorkflowLockedError):
            engine.reset()

    verify = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="locked",
        source_path=workflow,
    )
    assert verify.get_status("analysis") == "success"
    verify.close()

    engine.reset()
    check = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="locked",
        source_path=workflow,
    )
    assert check.get_status("analysis") is None
    check.close()


def test_migration_uses_same_workflow_lock(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: legacy}\ntasks: []\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    state_path = workdir / "state.sqlite3"
    workdir.mkdir()
    connection = sqlite3.connect(state_path)
    connection.executescript(
        (FIXTURES / "state_v0_2.sql").read_text(encoding="utf-8")
    )
    connection.execute(
        "INSERT INTO task_state(workflow, task, status) VALUES ('legacy', 'a', 'success')"
    )
    connection.commit()
    connection.close()

    with WorkflowLock(workdir, "legacy"):
        with pytest.raises(WorkflowLockedError):
            migrate_state(
                state_path=state_path,
                workflow_name="legacy",
                source_path=workflow,
            )

    assert not (workdir / "backups").exists()
    connection = sqlite3.connect(state_path)
    assert connection.execute("SELECT workflow, task, status FROM task_state").fetchall() == [
        ("legacy", "a", "success")
    ]
    connection.close()
