from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

from simpleworkflow.cli import main
from simpleworkflow.migrations import migrate_state
from simpleworkflow.state import WorkflowState

FIXTURES = Path(__file__).parent / "fixtures"


def _legacy_database(path: Path, version: str) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        (FIXTURES / f"state_v{version.replace('.', '_')}.sql").read_text(encoding="utf-8")
    )
    return connection


def _v02_success_provenance(
    workdir: Path,
    workflow: Path,
    *,
    workflow_name: str,
    task_name: str,
    signature_value: str,
) -> None:
    payload = {
        "signature_schema": 1,
        "simpleworkflow_version": "0.2.0",
        "workflow_sha256": hashlib.sha256(workflow.read_bytes()).hexdigest(),
        "task": {
            "name": task_name,
            "argv": ["legacy-command"],
            "cwd": None,
            "env": {},
            "input_fingerprint": "metadata",
            "inputs": {"required": [], "optional": []},
            "outputs": [],
        },
    }
    run_dir = workdir / "runs" / "legacy-run"
    attempt = run_dir / "tasks" / f"{task_name}-legacy" / "attempt-001"
    attempt.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "legacy-run",
                "workflow": workflow_name,
                "created_at": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (attempt / "metadata.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "legacy-run",
                "workflow": workflow_name,
                "task": task_name,
                "attempt": 1,
                "recorded_at": "2026-01-01T00:01:00Z",
                "status": "success",
                "return_code": 0,
                "signature": {"value": signature_value, "payload": payload},
            }
        ),
        encoding="utf-8",
    )


def test_partial_v02_upgrade_status_and_run_continue_only_pending_work(
    tmp_path: Path, capsys: object
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        f"""
workflow:
  name: partial02
tasks:
  - name: prepare
    cwd: .
    argv:
      - {sys.executable!r}
      - -c
      - "from pathlib import Path; Path('prepared.txt').write_text('rerun')"
    outputs:
      required: [prepared.txt]
  - name: analysis
    depends_on: [prepare]
    cwd: .
    argv:
      - {sys.executable!r}
      - -c
      - "from pathlib import Path; Path('analysis.txt').write_text('done')"
    outputs:
      required: [analysis.txt]
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "prepared.txt").write_text("legacy", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    state_path = workdir / "state.sqlite3"
    connection = _legacy_database(state_path, "0.2")
    connection.execute(
        """
        INSERT INTO task_state(workflow, task, status, return_code, signature)
        VALUES ('partial02', 'prepare', 'success', 0, 'legacy-prepare')
        """
    )
    connection.commit()
    connection.close()
    _v02_success_provenance(
        workdir,
        workflow,
        workflow_name="partial02",
        task_name="prepare",
        signature_value="legacy-prepare",
    )

    migrate_state(state_path=state_path, workflow_name="partial02", source_path=workflow)
    assert main(["status", str(workflow), "--color", "never"]) == 0
    output = capsys.readouterr().out.lower()  # type: ignore[attr-defined]
    assert "prepare" in output and "success" in output
    assert "analysis" in output and "pending" in output

    assert main(["run", str(workflow), "--color", "never"]) == 0
    assert (tmp_path / "prepared.txt").read_text(encoding="utf-8") == "legacy"
    assert (tmp_path / "analysis.txt").read_text(encoding="utf-8") == "done"

    state = WorkflowState(state_path, workflow_name="partial02", source_path=workflow)
    assert state.get_status("prepare") == "success"
    assert state.get_status("analysis") == "success"
    state.close()


def test_failed_v02_task_is_retried_after_upgrade(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    result = tmp_path / "result.txt"
    workflow.write_text(
        f"""
workflow:
  name: failed02
tasks:
  - name: analysis
    argv:
      - {sys.executable!r}
      - -c
      - "from pathlib import Path; Path(r'{result}').write_text('recovered')"
    outputs:
      required: [{str(result)!r}]
""".lstrip(),
        encoding="utf-8",
    )
    state_path = tmp_path / ".simpleworkflow" / "state.sqlite3"
    connection = _legacy_database(state_path, "0.2")
    connection.execute(
        """
        INSERT INTO task_state(workflow, task, status, return_code)
        VALUES ('failed02', 'analysis', 'failed', 7)
        """
    )
    connection.commit()
    connection.close()

    migrate_state(state_path=state_path, workflow_name="failed02", source_path=workflow)
    assert main(["run", str(workflow), "--color", "never"]) == 0
    assert result.read_text(encoding="utf-8") == "recovered"
    state = WorkflowState(state_path, workflow_name="failed02", source_path=workflow)
    assert state.get_status("analysis") == "success"
    state.close()


def test_v03_cli_selector_extracts_one_instance_and_backup_keeps_both(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: forecast}\ntasks: []\n", encoding="utf-8")
    state_path = tmp_path / ".simpleworkflow" / "state.sqlite3"
    connection = _legacy_database(state_path, "0.3")
    connection.executemany(
        "INSERT INTO task_state(workflow, task, status) VALUES (?, 'analysis', 'success')",
        [("forecast@aaaaaaaaaaaa",), ("forecast@bbbbbbbbbbbb",)],
    )
    connection.commit()
    connection.close()

    assert (
        main(
            [
                "migrate",
                str(workflow),
                "--legacy-workflow",
                "forecast@aaaaaaaaaaaa",
                "--color",
                "never",
            ]
        )
        == 0
    )
    state = WorkflowState(state_path, workflow_name="forecast", source_path=workflow)
    assert state.get_status("analysis") == "success"
    migration = state.connection.execute(
        "SELECT source_selector, source_workflow_keys, backup_path FROM migration_history"
    ).fetchone()
    assert migration is not None
    backup_path = state.resolve_path(migration[2])
    state.close()
    assert migration[0] == "forecast@aaaaaaaaaaaa"
    assert json.loads(migration[1]) == ["forecast@aaaaaaaaaaaa"]
    assert not Path(migration[2]).is_absolute()
    assert backup_path is not None

    backup = sqlite3.connect(backup_path)
    assert backup.execute("SELECT DISTINCT workflow FROM task_state ORDER BY workflow").fetchall() == [
        ("forecast@aaaaaaaaaaaa",),
        ("forecast@bbbbbbbbbbbb",),
    ]
    backup.close()
