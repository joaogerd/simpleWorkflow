from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import simpleworkflow.migrations as migrations
from simpleworkflow.migrations import MigrationError, inspect_state, migrate_state
from simpleworkflow.state import STATE_SCHEMA_VERSION, WorkflowState

FIXTURES = Path(__file__).parent / "fixtures"


def _legacy_v02(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        (FIXTURES / "state_v0_2.sql").read_text(encoding="utf-8")
    )
    connection.execute(
        """
        INSERT INTO task_state(workflow, task, status, return_code, signature)
        VALUES ('atomic', 'analysis', 'success', 0, 'legacy-signature')
        """
    )
    connection.commit()
    connection.close()


def test_replace_failure_preserves_legacy_state_backup_and_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: atomic}\ntasks: []\n", encoding="utf-8")
    state_path = tmp_path / ".simpleworkflow" / "state.sqlite3"
    _legacy_v02(state_path)
    original_replace = migrations.os.replace

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr(migrations.os, "replace", fail_replace)
    with pytest.raises(MigrationError, match="legado foi preservado"):
        migrate_state(
            state_path=state_path,
            workflow_name="atomic",
            source_path=workflow,
        )

    inspection = inspect_state(state_path)
    assert inspection.kind == "legacy"
    assert inspection.legacy_version == "0.2.x"
    legacy = sqlite3.connect(state_path)
    assert legacy.execute(
        "SELECT workflow, task, status, signature FROM task_state"
    ).fetchall() == [("atomic", "analysis", "success", "legacy-signature")]
    legacy.close()

    backups = list((state_path.parent / "backups").glob("*.sqlite3"))
    assert len(backups) == 1
    backup = sqlite3.connect(backups[0])
    assert backup.execute(
        "SELECT workflow, task, status, signature FROM task_state"
    ).fetchall() == [("atomic", "analysis", "success", "legacy-signature")]
    backup.close()
    assert list(state_path.parent.glob(".state.sqlite3.migrating-*")) == []

    monkeypatch.setattr(migrations.os, "replace", original_replace)
    result = migrate_state(
        state_path=state_path,
        workflow_name="atomic",
        source_path=workflow,
    )
    assert result.migrated is True
    assert inspect_state(state_path).schema_version == STATE_SCHEMA_VERSION
    state = WorkflowState(state_path, workflow_name="atomic", source_path=workflow)
    assert state.get_status("analysis") == "success"
    state.close()
