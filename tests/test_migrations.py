from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from simpleworkflow.cli import main
from simpleworkflow.config import load_workflow
from simpleworkflow.engine import WorkflowEngine
from simpleworkflow.migrations import (
    AmbiguousLegacyState,
    inspect_state,
    migrate_state,
)
from simpleworkflow.state import STATE_SCHEMA_VERSION, WorkflowState

FIXTURES = Path(__file__).parent / "fixtures"


def _legacy_database(path: Path, version: str) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    script = (FIXTURES / f"state_v{version.replace('.', '_')}.sql").read_text(encoding="utf-8")
    connection.executescript(script)
    return connection


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metadata_fingerprint(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "kind": "file",
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _legacy_v02_signature(
    workflow: Path,
    source: Path,
    output: Path,
) -> tuple[str, dict[str, object]]:
    payload: dict[str, object] = {
        "signature_schema": 1,
        "simpleworkflow_version": "0.2.0",
        "workflow_sha256": _sha256(workflow),
        "task": {
            "name": "analysis",
            "argv": [sys.executable, "-c", "print('analysis')"],
            "cwd": None,
            "env": {},
            "input_fingerprint": "metadata",
            "inputs": {
                "required": [_metadata_fingerprint(source)],
                "optional": [],
            },
            "outputs": [str(output.resolve())],
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    value = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return value, payload


def _write_v02_run_metadata(
    workdir: Path,
    *,
    workflow_name: str,
    signature_value: str,
    signature_payload: dict[str, object],
) -> None:
    run = workdir / "runs" / "legacy-run"
    attempt = run / "tasks" / "analysis-deadbeef00" / "attempt-001"
    attempt.mkdir(parents=True)
    (run / "run.json").write_text(
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
                "task": "analysis",
                "attempt": 1,
                "recorded_at": "2026-01-01T00:01:00Z",
                "status": "success",
                "return_code": 0,
                "signature": {
                    "value": signature_value,
                    "payload": signature_payload,
                },
            }
        ),
        encoding="utf-8",
    )


def test_inspect_and_migrate_real_v02_schema(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: legacy02}\ntasks: []\n", encoding="utf-8")
    state_path = tmp_path / ".simpleworkflow" / "state.sqlite3"
    connection = _legacy_database(state_path, "0.2")
    connection.execute(
        """
        INSERT INTO task_state(workflow, task, status, return_code, signature, updated_at)
        VALUES ('legacy02', 'prepare', 'success', 0, 'old-signature', '2026-01-02 03:04:05')
        """
    )
    connection.commit()
    connection.close()

    inspection = inspect_state(state_path)
    assert inspection.kind == "legacy"
    assert inspection.legacy_version == "0.2.x"
    assert [group.selector for group in inspection.groups] == ["legacy02"]

    result = migrate_state(
        state_path=state_path,
        workflow_name="legacy02",
        source_path=workflow,
    )
    assert result.migrated is True
    assert result.backup_path is not None and result.backup_path.is_file()

    state = WorkflowState(state_path, workflow_name="legacy02", source_path=workflow)
    assert state.get_status("prepare") == "success"
    record = state.get_task_state("prepare")
    assert record is not None
    assert record.signature == "old-signature"
    assert record.updated_at == "2026-01-02 03:04:05"
    assert state.connection.execute(
        "SELECT schema_version FROM schema_info WHERE singleton=1"
    ).fetchone() == (STATE_SCHEMA_VERSION,)
    assert state.connection.execute("SELECT COUNT(*) FROM migration_history").fetchone() == (1,)
    state.close()

    backup = sqlite3.connect(result.backup_path)
    assert backup.execute("SELECT workflow, task, status FROM task_state").fetchall() == [
        ("legacy02", "prepare", "success")
    ]
    backup.close()


def test_migration_is_idempotent_after_success(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: idempotent}\ntasks: []\n", encoding="utf-8")
    state_path = tmp_path / ".simpleworkflow" / "state.sqlite3"
    connection = _legacy_database(state_path, "0.2")
    connection.execute(
        "INSERT INTO task_state(workflow, task, status) VALUES ('idempotent', 'a', 'success')"
    )
    connection.commit()
    connection.close()

    first = migrate_state(
        state_path=state_path,
        workflow_name="idempotent",
        source_path=workflow,
    )
    second = migrate_state(
        state_path=state_path,
        workflow_name="idempotent",
        source_path=workflow,
    )
    assert first.migrated is True
    assert second.migrated is False
    assert len(list((tmp_path / ".simpleworkflow" / "backups").glob("*.sqlite3"))) == 1


def test_v02_running_state_becomes_unknown_conservatively(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: running}\ntasks: []\n", encoding="utf-8")
    state_path = tmp_path / ".simpleworkflow" / "state.sqlite3"
    connection = _legacy_database(state_path, "0.2")
    connection.execute(
        "INSERT INTO task_state(workflow, task, status) VALUES ('running', 'analysis', 'running')"
    )
    connection.commit()
    connection.close()

    migrate_state(state_path=state_path, workflow_name="running", source_path=workflow)
    state = WorkflowState(state_path, workflow_name="running", source_path=workflow)
    record = state.get_task_state("analysis")
    assert record is not None and record.status == "unknown"
    assert record.reason and "0.2.x" in record.reason
    state.close()


def test_ambiguous_v02_shared_database_is_never_merged_silently(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: first}\ntasks: []\n", encoding="utf-8")
    state_path = tmp_path / ".simpleworkflow" / "state.sqlite3"
    connection = _legacy_database(state_path, "0.2")
    connection.executemany(
        "INSERT INTO task_state(workflow, task, status) VALUES (?, 'task', 'success')",
        [("first",), ("second",)],
    )
    connection.commit()
    connection.close()
    original = state_path.read_bytes()

    with pytest.raises(AmbiguousLegacyState, match="mais de um workflow lógico"):
        migrate_state(state_path=state_path, workflow_name="first", source_path=workflow)

    assert state_path.read_bytes() == original
    assert not (tmp_path / ".simpleworkflow" / "backups").exists()


def test_explicit_selector_extracts_one_legacy_instance_and_backup_preserves_all(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: first}\ntasks: []\n", encoding="utf-8")
    state_path = tmp_path / ".simpleworkflow" / "state.sqlite3"
    connection = _legacy_database(state_path, "0.2")
    connection.executemany(
        "INSERT INTO task_state(workflow, task, status) VALUES (?, 'task', 'success')",
        [("first",), ("second",)],
    )
    connection.commit()
    connection.close()

    result = migrate_state(
        state_path=state_path,
        workflow_name="first",
        source_path=workflow,
        legacy_selector="first",
    )
    state = WorkflowState(state_path, workflow_name="first", source_path=workflow)
    assert state.get_status("task") == "success"
    state.close()
    assert result.backup_path is not None
    backup = sqlite3.connect(result.backup_path)
    assert backup.execute("SELECT DISTINCT workflow FROM task_state ORDER BY workflow").fetchall() == [
        ("first",),
        ("second",),
    ]
    backup.close()


def test_v03_cycle_keys_become_explicit_cycles_in_one_instance(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: cycling}\ntasks: []\n", encoding="utf-8")
    state_path = tmp_path / ".simpleworkflow" / "state.sqlite3"
    connection = _legacy_database(state_path, "0.3")
    digest = "abc123def456"
    rows = [
        (f"cycling__20180415T000000Z@{digest}", "analysis", "success", 0),
        (f"cycling__20180415T060000Z@{digest}", "analysis", "failed", 7),
        (f"cycling__20180415T120000Z@{digest}", "analysis", "success", 0),
    ]
    connection.executemany(
        """
        INSERT INTO task_state(workflow, task, status, return_code)
        VALUES (?, ?, ?, ?)
        """,
        rows,
    )
    connection.commit()
    connection.close()

    inspection = inspect_state(state_path)
    assert inspection.legacy_version == "0.3.x"
    assert [group.selector for group in inspection.groups] == [f"cycling@{digest}"]

    migrate_state(state_path=state_path, workflow_name="cycling", source_path=workflow)
    state = WorkflowState(state_path, workflow_name="cycling", source_path=workflow)
    assert state.get_status("analysis", cycle_id="20180415T000000Z") == "success"
    assert state.get_status("analysis", cycle_id="20180415T060000Z") == "failed"
    assert state.get_status("analysis", cycle_id="20180415T120000Z") == "success"
    assert state.connection.execute(
        "SELECT cycle_id FROM cycle_state ORDER BY cycle_id"
    ).fetchall() == [
        ("20180415T000000Z",),
        ("20180415T060000Z",),
        ("20180415T120000Z",),
    ]
    assert state.connection.execute("SELECT COUNT(*) FROM workflow_instance").fetchone() == (1,)
    state.close()


def test_v03_multiple_path_identities_are_ambiguous(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: shared}\ntasks: []\n", encoding="utf-8")
    state_path = tmp_path / ".simpleworkflow" / "state.sqlite3"
    connection = _legacy_database(state_path, "0.3")
    connection.executemany(
        "INSERT INTO task_state(workflow, task, status) VALUES (?, 'a', 'success')",
        [("shared@aaaaaaaaaaaa",), ("shared@bbbbbbbbbbbb",)],
    )
    connection.commit()
    connection.close()

    with pytest.raises(AmbiguousLegacyState):
        migrate_state(state_path=state_path, workflow_name="shared", source_path=workflow)


def test_v02_success_with_matching_provenance_continues_without_rerun(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    source = tmp_path / "background.nc"
    output = tmp_path / "analysis.nc"
    source.write_text("background", encoding="utf-8")
    output.write_text("old-analysis", encoding="utf-8")
    workflow.write_text(
        f"""
workflow:
  name: legacy_restart
context:
  python: {json.dumps(sys.executable)}
  source: {json.dumps(str(source))}
  output: {json.dumps(str(output))}
tasks:
  - name: analysis
    argv: ["{{python}}", "-c", "print('analysis')"]
    inputs:
      required: ["{{source}}"]
    outputs:
      required: ["{{output}}"]
    input_fingerprint: metadata
""".lstrip(),
        encoding="utf-8",
    )
    signature_value, signature_payload = _legacy_v02_signature(workflow, source, output)
    workdir = tmp_path / ".simpleworkflow"
    state_path = workdir / "state.sqlite3"
    connection = _legacy_database(state_path, "0.2")
    connection.execute(
        """
        INSERT INTO task_state(workflow, task, status, return_code, signature)
        VALUES ('legacy_restart', 'analysis', 'success', 0, ?)
        """,
        (signature_value,),
    )
    connection.commit()
    connection.close()
    _write_v02_run_metadata(
        workdir,
        workflow_name="legacy_restart",
        signature_value=signature_value,
        signature_payload=signature_payload,
    )

    migrate_state(
        state_path=state_path,
        workflow_name="legacy_restart",
        source_path=workflow,
    )
    engine = WorkflowEngine(load_workflow(workflow))

    class MustNotRun:
        def run(self, *_args: object, **_kwargs: object) -> int:
            raise AssertionError("migrated successful task should have been reused")

    engine.executor = MustNotRun()  # type: ignore[assignment]
    assert engine.run() == 0
    migrated = engine.state.get_task_state("analysis")
    assert migrated is not None
    assert migrated.status == "success"
    assert migrated.signature_schema == 4
    assert migrated.signature != signature_value
    assert output.read_text(encoding="utf-8") == "old-analysis"
    assert engine.state.connection.execute("SELECT COUNT(*) FROM attempt_history").fetchone() == (1,)
    engine.state.close()


def test_migrate_check_is_read_only(tmp_path: Path, capsys: object) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: check}\ntasks: []\n", encoding="utf-8")
    state_path = tmp_path / ".simpleworkflow" / "state.sqlite3"
    connection = _legacy_database(state_path, "0.2")
    connection.execute(
        "INSERT INTO task_state(workflow, task, status) VALUES ('check', 'a', 'success')"
    )
    connection.commit()
    connection.close()
    original = state_path.read_bytes()

    assert main(["migrate", str(workflow), "--check", "--color", "never"]) == 0
    assert state_path.read_bytes() == original
    assert not (tmp_path / ".simpleworkflow" / "backups").exists()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "0.2.x" in captured.out
    assert "check" in captured.out
