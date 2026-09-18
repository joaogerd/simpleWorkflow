from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from simpleworkflow.runs import RunRecorder
from simpleworkflow.state import WorkflowState
from simpleworkflow.tui import WorkflowTui
from simpleworkflow.tui_viewer import TextFileViewer


def _config(workflow: Path) -> dict[str, object]:
    return {
        "workflow": {"name": "runtime_tui"},
        "tasks": [
            {
                "name": "analysis",
                "argv": ["jedi", "analysis.yaml"],
                "executor": "pbs",
                "pbs": {"queue": "pesqmini", "select": 1, "ncpus": 64, "walltime": "00:30:00"},
            }
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }


def _persist_running_attempt(workflow: Path, workdir: Path) -> None:
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="runtime_tui",
        source_path=workflow,
    )
    state.ensure_cycle("2018041506", "2018-04-15T06:00:00Z")
    recorder = RunRecorder(
        workdir,
        "runtime_tui",
        instance_id=state.instance_id,
        cycle_id="2018041506",
        cycle_time="2018-04-15T06:00:00Z",
        run_id="runtime-run",
    )
    state.record_run(
        recorder.run_id,
        recorder.directory,
        cycle_id="2018041506",
        cycle_time="2018-04-15T06:00:00Z",
    )
    attempt = recorder.begin_attempt("analysis")
    recorder.write_started(
        attempt,
        {
            "status": "running",
            "command": {"argv": ["jedi", "analysis.yaml"], "cwd": "/case/work", "env": {}},
            "signature": "sig",
        },
    )
    attempt.stdout_path.write_text("qsub accepted\n", encoding="utf-8")
    attempt.stderr_path.write_text("", encoding="utf-8")
    (attempt.directory / "pbs.stdout.log").write_text("JEDI iteration 1\n", encoding="utf-8")
    (attempt.directory / "pbs.stderr.log").write_text("warning from worker\n", encoding="utf-8")
    (attempt.directory / "scheduler.json").write_text(
        json.dumps({
            "executor": "pbs",
            "job_id": "381922.pbs-ha",
            "job_stdout": str(attempt.directory / "pbs.stdout.log"),
            "job_stderr": str(attempt.directory / "pbs.stderr.log"),
        }) + "\n",
        encoding="utf-8",
    )
    state.record_attempt_started(
        run_id=attempt.run_id,
        task="analysis",
        attempt=1,
        attempt_path=attempt.directory,
        signature="sig",
        cycle_id="2018041506",
        started_at="2018-04-15T06:01:04Z",
    )
    state.set_status(
        "analysis",
        "running",
        None,
        "sig",
        "tarefa iniciada",
        attempt.directory,
        cycle_id="2018041506",
    )
    state.close()


def test_inspector_shows_pbs_job_command_and_timing(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: runtime_tui\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    _persist_running_attempt(workflow, workdir)
    app = WorkflowTui(
        config=_config(workflow), workflow_path=workflow, workdir=workdir, refresh_seconds=60
    )

    async def scenario() -> None:
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            inspector = app.query_one("#inspector")
            assert "381922.pbs-ha" in inspector.primary_text
            assert "jedi analysis.yaml" in inspector.detail_values["command"]
            assert inspector.detail_values["working directory"] == "/case/work"
            assert inspector.detail_values["started"] == "2018-04-15T06:01:04Z"

    asyncio.run(scenario())


def test_logs_select_available_stdout_stderr_and_pbs_files(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: runtime_tui\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    _persist_running_attempt(workflow, workdir)
    app = WorkflowTui(
        config=_config(workflow), workflow_path=workflow, workdir=workdir, refresh_seconds=60
    )

    async def scenario() -> None:
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            app.action_open_logs()
            await pilot.pause()
            assert app.query_one("#views").active == "logs"
            viewer = app.query_one("#log-viewer", TextFileViewer)
            assert app.selected_log_key == "pbs_stdout"
            assert "JEDI iteration 1" in viewer.text
            await pilot.press("e")
            await pilot.pause()
            assert app.selected_log_key in {"pbs_stderr", "stderr"}
            assert "warning from worker" in viewer.text

    asyncio.run(scenario())


def test_missing_attempt_logs_do_not_break_monitor(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: runtime_tui\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3", workflow_name="runtime_tui", source_path=workflow
    )
    state.ensure_cycle("2018041506", "2018-04-15T06:00:00Z")
    state.set_status("analysis", "failed", 7, reason="submission failed", cycle_id="2018041506")
    state.close()
    app = WorkflowTui(
        config=_config(workflow), workflow_path=workflow, workdir=workdir, refresh_seconds=60
    )

    async def scenario() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app.action_open_logs()
            await pilot.pause()
            assert app.query_one("#views").active == "logs"
            viewer = app.query_one("#log-viewer", TextFileViewer)
            assert viewer.state.resource is None
            assert "No file selected" in viewer.status_message

    asyncio.run(scenario())


def test_same_process_tui_tolerates_state_database_initialization_window(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        "workflow: {name: initializing_state}\n"
        "tasks:\n"
        "  - name: analysis\n"
        "    argv: ['true']\n",
        encoding="utf-8",
    )
    workdir = tmp_path / ".simpleworkflow"
    workdir.mkdir()
    connection = sqlite3.connect(workdir / "state.sqlite3")
    connection.close()
    completion: Future[int] = Future()

    app = WorkflowTui(
        config={
            "workflow": {"name": "initializing_state"},
            "tasks": [{"name": "analysis", "argv": ["true"]}],
            "__simpleworkflow__": {
                "source_path": str(workflow),
                "source_dir": str(workflow.parent),
            },
        },
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60,
        completion_future=completion,
    )

    assert app.snapshot.instance_id is None
    assert [task.status for task in app.snapshot.tasks] == ["pending"]
