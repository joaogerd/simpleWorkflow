from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

from simpleworkflow.cli import main
from simpleworkflow.migrations import inspect_state, migrate_state
from simpleworkflow.state import WorkflowState

FIXTURES = Path(__file__).parent / "fixtures"


def test_handled_failure_finalizes_existing_run_history(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        f"""
workflow:
  name: finalize_failed_run
tasks:
  - name: prepare
    cwd: .
    argv:
      - {sys.executable!r}
      - -c
      - "from pathlib import Path; Path('prepared.txt').write_text('ok')"
    outputs:
      required: [prepared.txt]
  - name: analysis
    cwd: .
    argv:
      - {sys.executable!r}
      - -c
      - "print('must not run')"
    inputs:
      required: [missing-input.txt]
""".lstrip(),
        encoding="utf-8",
    )

    assert main(["run", str(workflow), "--color", "never"]) == 2

    state = WorkflowState(
        tmp_path / ".simpleworkflow" / "state.sqlite3",
        workflow_name="finalize_failed_run",
        source_path=workflow,
    )
    runs = state.connection.execute(
        "SELECT status, finished_at FROM run_history ORDER BY created_at"
    ).fetchall()
    state.close()

    assert len(runs) == 1
    assert runs[0][0] == "failed"
    assert runs[0][1] is not None


@pytest.mark.parametrize("version", ["0.2", "0.3"])
def test_empty_legacy_database_migrates_and_backup_stays_portable(
    tmp_path: Path,
    version: str,
) -> None:
    first_root = tmp_path / "case-A"
    first_root.mkdir()
    workflow = first_root / "workflow.yaml"
    workflow.write_text("workflow: {name: empty_legacy}\ntasks: []\n", encoding="utf-8")
    state_path = first_root / ".simpleworkflow" / "state.sqlite3"
    state_path.parent.mkdir()

    connection = sqlite3.connect(state_path)
    connection.executescript(
        (FIXTURES / f"state_v{version.replace('.', '_')}.sql").read_text(encoding="utf-8")
    )
    connection.close()

    inspection = inspect_state(state_path)
    assert inspection.kind == "legacy"
    assert inspection.groups == ()

    result = migrate_state(
        state_path=state_path,
        workflow_name="empty_legacy",
        source_path=workflow,
    )
    assert result.migrated is True
    assert result.backup_path is not None and result.backup_path.is_file()
    assert result.selected_group is not None
    assert result.selected_group.selector == "empty_legacy"
    assert result.selected_group.workflow_keys == ()

    state = WorkflowState(
        state_path,
        workflow_name="empty_legacy",
        source_path=workflow,
    )
    migration = state.connection.execute(
        "SELECT source_selector, source_workflow_keys, backup_path FROM migration_history"
    ).fetchone()
    assert migration is not None
    assert migration[0] == "empty_legacy"
    assert json.loads(migration[1]) == []
    assert not Path(migration[2]).is_absolute()
    backup_before_move = state.resolve_path(migration[2])
    assert backup_before_move is not None and backup_before_move.is_file()
    state.close()

    second_root = tmp_path / "case-B"
    shutil.move(str(first_root), second_root)
    moved_workflow = second_root / "workflow.yaml"
    moved_state_path = second_root / ".simpleworkflow" / "state.sqlite3"
    moved = WorkflowState(
        moved_state_path,
        workflow_name="empty_legacy",
        source_path=moved_workflow,
    )
    stored_backup = moved.connection.execute(
        "SELECT backup_path FROM migration_history"
    ).fetchone()[0]
    backup_after_move = moved.resolve_path(stored_backup)
    assert backup_after_move is not None and backup_after_move.is_file()
    assert moved.connection.execute("SELECT COUNT(*) FROM task_state").fetchone() == (0,)
    moved.close()
