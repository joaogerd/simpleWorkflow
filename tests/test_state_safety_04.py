from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

from simpleworkflow.cli import main
from simpleworkflow.state import StateBindingError, StateSchemaError, WorkflowState


def test_custom_workdir_rejects_second_existing_yaml_even_with_same_filename(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    shared = tmp_path / "shared-state"
    first_root.mkdir()
    second_root.mkdir()
    first = first_root / "workflow.yaml"
    second = second_root / "workflow.yaml"
    first.write_text("workflow: {name: experiment}\ntasks: []\n", encoding="utf-8")
    second.write_text("workflow: {name: experiment}\ntasks: []\n", encoding="utf-8")

    state = WorkflowState(
        shared / "state.sqlite3",
        workflow_name="experiment",
        source_path=first,
    )
    state.close()

    with pytest.raises(StateBindingError, match="já pertence"):
        WorkflowState(
            shared / "state.sqlite3",
            workflow_name="experiment",
            source_path=second,
        )


def test_future_state_schema_requires_newer_simpleworkflow(tmp_path: Path) -> None:
    state_path = tmp_path / ".simpleworkflow" / "state.sqlite3"
    state_path.parent.mkdir()
    connection = sqlite3.connect(state_path)
    connection.executescript(
        """
        CREATE TABLE schema_info (
            singleton INTEGER PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        INSERT INTO schema_info VALUES (1, 2, 'future');
        """
    )
    connection.commit()
    connection.close()

    with pytest.raises(StateSchemaError, match="requires a newer version"):
        WorkflowState(
            state_path,
            workflow_name="future",
            source_path=tmp_path / "workflow.yaml",
        )


def test_reset_preserves_history_and_forces_new_execution(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    counter = tmp_path / "counter.txt"
    workflow.write_text(
        f"""
workflow:
  name: reset_history
tasks:
  - name: analysis
    argv:
      - {sys.executable!r}
      - -c
      - "from pathlib import Path; p=Path(r'{counter}'); p.write_text(str(int(p.read_text()) + 1) if p.exists() else '1')"
    outputs:
      required: [{str(counter)!r}]
""".lstrip(),
        encoding="utf-8",
    )
    assert main(["run", str(workflow), "--color", "never"]) == 0
    state_path = tmp_path / ".simpleworkflow" / "state.sqlite3"
    state = WorkflowState(state_path, workflow_name="reset_history", source_path=workflow)
    state.record_migration(
        source_version="test",
        source_selector="reset_history",
        source_workflow_keys=["reset_history"],
        backup_path=tmp_path / "backup.sqlite3",
    )
    before = {
        table: state.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("state_event", "run_history", "attempt_history", "migration_history")
    }
    state.close()

    assert main(["reset", str(workflow), "--color", "never"]) == 0
    reset_state = WorkflowState(state_path, workflow_name="reset_history", source_path=workflow)
    assert reset_state.get_status("analysis") is None
    after = {
        table: reset_state.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("state_event", "run_history", "attempt_history", "migration_history")
    }
    reset_state.close()
    assert after == before

    assert main(["run", str(workflow), "--color", "never"]) == 0
    assert counter.read_text(encoding="utf-8") == "2"
    final = WorkflowState(state_path, workflow_name="reset_history", source_path=workflow)
    assert final.connection.execute("SELECT COUNT(*) FROM run_history").fetchone()[0] == (
        before["run_history"] + 1
    )
    assert final.connection.execute("SELECT COUNT(*) FROM attempt_history").fetchone()[0] == (
        before["attempt_history"] + 1
    )
    final.close()
