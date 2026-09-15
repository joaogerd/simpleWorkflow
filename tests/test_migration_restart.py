from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from simpleworkflow.cli import main
from simpleworkflow.config import load_workflow
from simpleworkflow.cycles import resolve_cycle_contexts
from simpleworkflow.engine import WorkflowEngine, render_argv
from simpleworkflow.migrations import migrate_state
from simpleworkflow.state import WorkflowState

FIXTURES = Path(__file__).parent / "fixtures"


def _legacy_v03_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        (FIXTURES / "state_v0_3.sql").read_text(encoding="utf-8")
    )
    return connection


def _legacy_value(value: Any, workflow_root: Path) -> Any:
    if isinstance(value, str):
        return value.replace("$WORKFLOW", str(workflow_root.resolve()))
    if isinstance(value, list):
        return [_legacy_value(item, workflow_root) for item in value]
    if isinstance(value, dict):
        return {key: _legacy_value(item, workflow_root) for key, item in value.items()}
    return value


def _v03_signature_from_current(
    engine: WorkflowEngine,
    task: dict[str, Any],
    workflow: Path,
) -> tuple[str, dict[str, Any]]:
    argv = render_argv(task["argv"], engine.context)
    signature = engine._task_signature(
        task["name"],
        task,
        argv,
        engine._task_cwd(task),
        engine._task_env(task),
        engine._task_artifacts(task),
    )
    payload = {
        "signature_schema": 2,
        "simpleworkflow_version": "0.3.0",
        "format_version": signature.payload["format_version"],
        "workflow_source": str(workflow.resolve()),
        "task": _legacy_value(signature.payload["task"], workflow.parent),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), payload


def _write_v03_attempt(
    workdir: Path,
    *,
    run_id: str,
    workflow_name: str,
    task_name: str,
    signature_value: str,
    signature_payload: dict[str, Any],
) -> None:
    run_dir = workdir / "runs" / run_id
    attempt = run_dir / "tasks" / f"{task_name}-legacy" / "attempt-001"
    attempt.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "workflow": workflow_name,
                "created_at": "2026-02-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (attempt / "started.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "workflow": workflow_name,
                "task": task_name,
                "attempt": 1,
                "started_at": "2026-02-01T00:00:01Z",
                "signature": signature_value,
            }
        ),
        encoding="utf-8",
    )
    (attempt / "metadata.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "workflow": workflow_name,
                "task": task_name,
                "attempt": 1,
                "recorded_at": "2026-02-01T00:00:02Z",
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


def test_partial_v03_cycle_campaign_continues_only_remaining_cycle(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    products = tmp_path / "products"
    marker = tmp_path / "executed.log"
    workflow.write_text(
        f"""
workflow:
  name: cycling_restart
cycle:
  start: "2018-04-15T00:00:00Z"
  end: "2018-04-15T12:00:00Z"
  step: PT6H
context:
  python: {json.dumps(sys.executable)}
  products: {json.dumps(str(products))}
  marker: {json.dumps(str(marker))}
tasks:
  - name: analysis
    cwd: .
    argv:
      - "{{python}}"
      - -c
      - "from pathlib import Path; root=Path(r'{{products}}'); root.mkdir(parents=True, exist_ok=True); (root/'cycle_{{cycle_yyyymmddhh}}.txt').write_text('{{cycle_time}}'); Path(r'{{marker}}').open('a').write('{{cycle_id}}\\n')"
    outputs:
      required:
        - "{{products}}/cycle_{{cycle_yyyymmddhh}}.txt"
""".lstrip(),
        encoding="utf-8",
    )
    products.mkdir()
    (products / "cycle_2018041500.txt").write_text(
        "2018-04-15T00:00:00Z", encoding="utf-8"
    )
    (products / "cycle_2018041506.txt").write_text(
        "2018-04-15T06:00:00Z", encoding="utf-8"
    )

    config = load_workflow(workflow)
    cycles = resolve_cycle_contexts(config["cycle"])
    workdir = tmp_path / ".simpleworkflow"
    state_path = workdir / "state.sqlite3"
    connection = _legacy_v03_database(state_path)
    digest = "a1b2c3d4e5f6"

    for index, cycle in enumerate(cycles[:2], start=1):
        resolved = deepcopy(config)
        resolved["context"] = {
            **resolved.get("context", {}),
            **cycle.render_context(),
        }
        engine = WorkflowEngine(
            resolved,
            workdir=tmp_path / "unused-state",
            cycle_id=cycle.cycle_id,
            cycle_time=cycle.cycle_time,
        )
        signature_value, signature_payload = _v03_signature_from_current(
            engine, resolved["tasks"][0], workflow
        )
        engine.state.close()
        legacy_workflow = f"cycling_restart__{cycle.cycle_id}"
        state_key = f"{legacy_workflow}@{digest}"
        connection.execute(
            """
            INSERT INTO task_state(
                workflow, task, status, return_code, signature, reason, attempt_dir
            ) VALUES (?, 'analysis', 'success', 0, ?, 'concluída com sucesso', ?)
            """,
            (
                state_key,
                signature_value,
                f".simpleworkflow/runs/legacy-cycle-{index}/tasks/analysis-legacy/attempt-001",
            ),
        )
        _write_v03_attempt(
            workdir,
            run_id=f"legacy-cycle-{index}",
            workflow_name=legacy_workflow,
            task_name="analysis",
            signature_value=signature_value,
            signature_payload=signature_payload,
        )
    connection.commit()
    connection.close()

    migrate_state(
        state_path=state_path,
        workflow_name="cycling_restart",
        source_path=workflow,
    )
    assert main(["run", str(workflow), "--color", "never"]) == 0

    assert marker.read_text(encoding="utf-8").splitlines() == ["20180415T120000Z"]
    assert (products / "cycle_2018041512.txt").read_text(encoding="utf-8") == (
        "2018-04-15T12:00:00Z"
    )
    state = WorkflowState(
        state_path,
        workflow_name="cycling_restart",
        source_path=workflow,
    )
    for cycle in cycles:
        assert state.get_status("analysis", cycle_id=cycle.cycle_id) == "success"
    assert state.connection.execute("SELECT COUNT(*) FROM run_history").fetchone() == (3,)
    state.close()


def test_failed_v03_task_is_retried_after_migration(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    output = tmp_path / "result.txt"
    workflow.write_text(
        f"""
workflow:
  name: retry_after_upgrade
tasks:
  - name: analysis
    argv:
      - {json.dumps(sys.executable)}
      - -c
      - "from pathlib import Path; Path(r'{output}').write_text('recovered')"
    outputs:
      required:
        - {json.dumps(str(output))}
""".lstrip(),
        encoding="utf-8",
    )
    state_path = tmp_path / ".simpleworkflow" / "state.sqlite3"
    connection = _legacy_v03_database(state_path)
    connection.execute(
        """
        INSERT INTO task_state(workflow, task, status, return_code, reason)
        VALUES ('retry_after_upgrade@123456abcdef', 'analysis', 'failed', 7, 'old failure')
        """
    )
    connection.commit()
    connection.close()

    migrate_state(
        state_path=state_path,
        workflow_name="retry_after_upgrade",
        source_path=workflow,
    )
    before = WorkflowState(
        state_path,
        workflow_name="retry_after_upgrade",
        source_path=workflow,
    )
    assert before.get_status("analysis") == "failed"
    before.close()

    assert main(["run", str(workflow), "--color", "never"]) == 0
    assert output.read_text(encoding="utf-8") == "recovered"
    after = WorkflowState(
        state_path,
        workflow_name="retry_after_upgrade",
        source_path=workflow,
    )
    assert after.get_status("analysis") == "success"
    events = after.connection.execute(
        "SELECT status FROM state_event WHERE task='analysis' ORDER BY id"
    ).fetchall()
    assert events[0] == ("failed",)
    assert events[-1] == ("success",)
    after.close()
