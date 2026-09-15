from __future__ import annotations

import shutil
import sqlite3
import uuid
from pathlib import Path

from simpleworkflow.config import load_workflow
from simpleworkflow.engine import WorkflowEngine
from simpleworkflow.state import STATE_SCHEMA_VERSION, WorkflowState


def test_new_database_has_explicit_schema_and_single_instance(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: experiment}\ntasks: []\n", encoding="utf-8")
    state = WorkflowState(
        tmp_path / ".simpleworkflow" / "state.sqlite3",
        workflow_name="experiment",
        source_path=workflow,
    )
    instance = state.instance
    uuid.UUID(instance.instance_id)
    assert instance.workflow_name == "experiment"
    assert instance.source_filename == "workflow.yaml"
    assert instance.last_source_path == str(workflow.resolve())

    connection = state.connection
    assert connection.execute(
        "SELECT schema_version FROM schema_info WHERE singleton = 1"
    ).fetchone() == (STATE_SCHEMA_VERSION,)
    columns = [row[1] for row in connection.execute("PRAGMA table_info(task_state)")]
    assert "workflow" not in columns
    assert {"cycle_id", "task", "status", "signature_payload"} <= set(columns)
    assert connection.execute("SELECT COUNT(*) FROM workflow_instance").fetchone() == (1,)
    state.close()


def test_cycles_share_instance_but_keep_independent_task_state(tmp_path: Path) -> None:
    state = WorkflowState(
        tmp_path / ".simpleworkflow" / "state.sqlite3",
        workflow_name="cycling",
        source_path=tmp_path / "workflow.yaml",
    )
    instance_id = state.instance_id
    state.ensure_cycle("20180415T000000Z", "2018-04-15T00:00:00Z")
    state.ensure_cycle("20180415T060000Z", "2018-04-15T06:00:00Z")
    state.set_status("analysis", "success", 0, cycle_id="20180415T000000Z")
    state.set_status("analysis", "failed", 7, cycle_id="20180415T060000Z")

    assert state.instance_id == instance_id
    assert state.get_status("analysis", cycle_id="20180415T000000Z") == "success"
    assert state.get_status("analysis", cycle_id="20180415T060000Z") == "failed"
    assert state.get_status("analysis") is None
    assert state.connection.execute("SELECT COUNT(*) FROM workflow_instance").fetchone() == (1,)
    state.close()


def test_reset_clears_current_state_but_preserves_history(tmp_path: Path) -> None:
    state = WorkflowState(
        tmp_path / ".simpleworkflow" / "state.sqlite3",
        workflow_name="history",
        source_path=tmp_path / "workflow.yaml",
    )
    state.set_status("prepare", "success", 0, reason="done")
    state.set_status("prepare", "failed", 9, reason="later failure")
    before = state.connection.execute("SELECT COUNT(*) FROM state_event").fetchone()[0]
    state.reset()
    after = state.connection.execute("SELECT COUNT(*) FROM state_event").fetchone()[0]
    assert state.get_status("prepare") is None
    assert before == after == 2
    state.close()


def test_attempt_paths_are_relative_to_state_directory(tmp_path: Path) -> None:
    workdir = tmp_path / ".simpleworkflow"
    attempt = workdir / "runs" / "run-a" / "tasks" / "task-a" / "attempt-001"
    attempt.mkdir(parents=True)
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="portable",
        source_path=tmp_path / "workflow.yaml",
    )
    state.set_status("analysis", "running", attempt_path=attempt)
    record = state.get_task_state("analysis")
    assert record is not None
    assert record.attempt_path == "runs/run-a/tasks/task-a/attempt-001"
    assert state.resolve_path(record.attempt_path) == attempt
    state.close()


def test_complete_workflow_root_can_move_without_losing_restart_state(tmp_path: Path) -> None:
    first_root = tmp_path / "case-A"
    first_root.mkdir()
    workflow = first_root / "workflow.yaml"
    workflow.write_text(
        """
workflow:
  name: portable_case
tasks:
  - name: make_output
    cwd: .
    argv:
      - python
      - -c
      - "from pathlib import Path; Path('result.txt').write_text('done')"
    outputs:
      required:
        - result.txt
""".lstrip(),
        encoding="utf-8",
    )
    config = load_workflow(workflow)
    first = WorkflowEngine(config)
    assert first.run() == 0
    instance_id = first.state.instance_id
    first_signature = first.state.get_task_state("make_output").signature  # type: ignore[union-attr]
    first.state.close()
    assert (first_root / "result.txt").read_text(encoding="utf-8") == "done"

    second_root = tmp_path / "case-B"
    shutil.move(str(first_root), second_root)
    moved_workflow = second_root / "workflow.yaml"
    moved = WorkflowEngine(load_workflow(moved_workflow))
    assert moved.workdir == (second_root / ".simpleworkflow").resolve()
    assert moved.state.instance_id == instance_id
    assert moved.state.instance.last_source_path == str(moved_workflow.resolve())

    run_count_before = moved.state.connection.execute(
        "SELECT COUNT(*) FROM run_history"
    ).fetchone()[0]
    assert moved.run() == 0
    run_count_after = moved.state.connection.execute(
        "SELECT COUNT(*) FROM run_history"
    ).fetchone()[0]
    moved_state = moved.state.get_task_state("make_output")
    assert moved_state is not None and moved_state.status == "success"
    assert moved_state.signature == first_signature
    assert run_count_after == run_count_before
    moved.state.close()


def test_workflow_instance_metadata_tracks_latest_source_path(tmp_path: Path) -> None:
    first = tmp_path / "case-A"
    second = tmp_path / "case-B"
    first.mkdir()
    workflow = first / "workflow.yaml"
    workflow.write_text("workflow: {name: metadata}\ntasks: []\n", encoding="utf-8")
    state = WorkflowState(
        first / ".simpleworkflow" / "state.sqlite3",
        workflow_name="metadata",
        source_path=workflow,
    )
    state.close()
    shutil.move(str(first), second)

    reopened = WorkflowState(
        second / ".simpleworkflow" / "state.sqlite3",
        workflow_name="metadata",
        source_path=second / "workflow.yaml",
    )
    assert reopened.instance.last_source_path == str((second / "workflow.yaml").resolve())
    reopened.close()


def test_schema_can_be_inspected_with_plain_sqlite(tmp_path: Path) -> None:
    state_path = tmp_path / ".simpleworkflow" / "state.sqlite3"
    state = WorkflowState(
        state_path,
        workflow_name="inspectable",
        source_path=tmp_path / "workflow.yaml",
    )
    state.close()
    connection = sqlite3.connect(state_path)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    connection.close()
    assert {
        "schema_info",
        "workflow_instance",
        "cycle_state",
        "task_state",
        "state_event",
        "run_history",
        "attempt_history",
        "migration_history",
    } <= tables
