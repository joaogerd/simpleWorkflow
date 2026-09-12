from __future__ import annotations

import asyncio
from pathlib import Path

from simpleworkflow.runs import RunRecorder
from simpleworkflow.state import WorkflowState
from simpleworkflow.tui import WorkflowTui, _latest_attempt


def _config() -> dict[str, object]:
    return {
        "workflow": {"name": "tui_test"},
        "tasks": [
            {
                "name": "jedi06_prepare",
                "argv": ["python", "-c", "print('prepare')"],
            },
            {
                "name": "jedi06_validate",
                "argv": ["python", "-c", "print('validate')"],
                "depends_on": ["jedi06_prepare"],
            },
        ],
    }


def test_latest_attempt_finds_runtime_logs_and_metadata(tmp_path: Path) -> None:
    recorder = RunRecorder(tmp_path, "tui_test", run_id="20260912T000000.000000Z-test")
    attempt = recorder.begin_attempt("jedi06_prepare")
    attempt.stdout_path.write_text("launcher output\n", encoding="utf-8")
    (attempt.directory / "pbs.stdout.log").write_text("model output\n", encoding="utf-8")
    recorder.write_metadata(
        attempt,
        {
            "status": "success",
            "return_code": 0,
            "execution": {
                "executor": "pbs",
                "job_id": "471301.pbs-ha",
            },
        },
    )

    snapshot = _latest_attempt(tmp_path, "jedi06_prepare")

    assert snapshot is not None
    assert snapshot.job_id == "471301.pbs-ha"
    assert snapshot.executor == "pbs"
    assert snapshot.preferred_log_paths()[0].name == "pbs.stdout.log"


def test_textual_monitor_mounts_with_persisted_workflow_state(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: tui_test\n", encoding="utf-8")

    state = WorkflowState(tmp_path / "state.sqlite3")
    state.set_status("tui_test", "jedi06_prepare", "success", 0)
    state.close()

    app = WorkflowTui(
        config=_config(),
        workflow_path=workflow,
        workdir=tmp_path,
        refresh_seconds=60.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app.selected_task == "jedi06_prepare"
            assert set(app.task_nodes) == {"jedi06_prepare", "jedi06_validate"}
            assert app.engine.state.get_status("tui_test", "jedi06_prepare") == "success"

    asyncio.run(scenario())
