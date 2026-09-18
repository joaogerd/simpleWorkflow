from __future__ import annotations

import asyncio
import json
from pathlib import Path

from textual.widgets import DataTable

from simpleworkflow.runs import RunRecorder
from simpleworkflow.state import WorkflowState
from simpleworkflow.tui import WorkflowTui
from simpleworkflow.tui_inspector import TaskInspector
from simpleworkflow.tui_viewer import TextFileViewer


def _config(workflow: Path, *, executor: str = "local") -> dict[str, object]:
    task: dict[str, object] = {
        "name": "analysis",
        "argv": ["jedi", "analysis.yaml"],
        "executor": executor,
    }
    if executor == "pbs":
        task["pbs"] = {"queue": "pesqmini", "ncpus": 64}
    return {
        "workflow": {"name": "failure-flow"},
        "tasks": [task],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }


def _persist_failure(
    workflow: Path,
    workdir: Path,
    *,
    executor: str,
    status: str = "failed",
    stderr_text: str | None = "fatal: analysis exploded\n",
    stdout_text: str | None = "launcher output\n",
    pbs_stderr_text: str | None = None,
    pbs_stdout_text: str | None = None,
) -> None:
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="failure-flow",
        source_path=workflow,
    )
    state.ensure_cycle("2018041506", "2018-04-15T06:00:00Z")

    if status == "failed" and any(
        value is not None
        for value in (stderr_text, stdout_text, pbs_stderr_text, pbs_stdout_text)
    ):
        recorder = RunRecorder(
            workdir,
            "failure-flow",
            instance_id=state.instance_id,
            cycle_id="2018041506",
            cycle_time="2018-04-15T06:00:00Z",
            run_id="failed-run",
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
                "command": {
                    "argv": ["jedi", "analysis.yaml"],
                    "cwd": str(workflow.parent),
                    "env": {},
                },
                "signature": "sig",
            },
        )
        if stdout_text is not None:
            attempt.stdout_path.write_text(stdout_text, encoding="utf-8")
        else:
            attempt.stdout_path.unlink(missing_ok=True)
        if stderr_text is not None:
            attempt.stderr_path.write_text(stderr_text, encoding="utf-8")
        else:
            attempt.stderr_path.unlink(missing_ok=True)

        execution: dict[str, object] = {"executor": executor}
        if executor == "pbs":
            if pbs_stdout_text is not None:
                pbs_stdout = attempt.directory / "pbs.stdout.log"
                pbs_stdout.write_text(pbs_stdout_text, encoding="utf-8")
                execution["job_stdout"] = str(pbs_stdout)
            if pbs_stderr_text is not None:
                pbs_stderr = attempt.directory / "pbs.stderr.log"
                pbs_stderr.write_text(pbs_stderr_text, encoding="utf-8")
                execution["job_stderr"] = str(pbs_stderr)
            execution["job_id"] = "99123.pbs-ha"
            (attempt.directory / "scheduler.json").write_text(
                json.dumps(execution) + "\n",
                encoding="utf-8",
            )
        (attempt.directory / "metadata.json").write_text(
            json.dumps(
                {
                    "command": {
                        "argv": ["jedi", "analysis.yaml"],
                        "cwd": str(workflow.parent),
                        "env": {},
                    },
                    "execution": execution,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        state.record_attempt_started(
            run_id=attempt.run_id,
            task="analysis",
            attempt=attempt.attempt,
            attempt_path=attempt.directory,
            signature="sig",
            cycle_id="2018041506",
            started_at="2018-04-15T06:01:04Z",
        )
        state.record_attempt_finished(
            run_id=attempt.run_id,
            task="analysis",
            attempt=attempt.attempt,
            status="failed",
            return_code=7,
            reason="process exited with return code 7",
        )
        state.set_status(
            "analysis",
            status,
            7,
            "sig",
            "process exited with return code 7",
            attempt.directory,
            cycle_id="2018041506",
        )
    else:
        state.set_status(
            "analysis",
            status,
            4 if status == "blocked" else 7,
            reason=f"{status} without runtime stream",
            cycle_id="2018041506",
        )
    state.close()


def _app(
    tmp_path: Path,
    *,
    executor: str = "local",
    status: str = "failed",
    stderr_text: str | None = "fatal: analysis exploded\n",
    stdout_text: str | None = "launcher output\n",
    pbs_stderr_text: str | None = None,
    pbs_stdout_text: str | None = None,
) -> WorkflowTui:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: failure-flow\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    _persist_failure(
        workflow,
        workdir,
        executor=executor,
        status=status,
        stderr_text=stderr_text,
        stdout_text=stdout_text,
        pbs_stderr_text=pbs_stderr_text,
        pbs_stdout_text=pbs_stdout_text,
    )
    return WorkflowTui(
        config=_config(workflow, executor=executor),
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60,
    )


def _select_first_problem(app: WorkflowTui) -> DataTable:
    table = app.query_one("#problems-table", DataTable)
    table.focus()
    table.move_cursor(row=0)
    table.action_select_cursor()
    return table


def test_problem_enter_opens_stderr_for_failed_task(tmp_path: Path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.press("4")
            await pilot.pause()
            _select_first_problem(app)
            await pilot.pause()

            viewer = app.screen.query_one("#context-viewer", TextFileViewer)
            assert "analysis exploded" in viewer.text
            assert app.selected_task == "analysis"
            assert app.selected_cycle_id == "2018041506"

            await pilot.press("escape")
            await pilot.pause()
            assert app.query_one("#views").active == "problems"

    asyncio.run(scenario())


def test_problem_error_priority_prefers_pbs_stderr(tmp_path: Path) -> None:
    app = _app(
        tmp_path,
        executor="pbs",
        stderr_text="launcher stderr\n",
        stdout_text="launcher stdout\n",
        pbs_stderr_text="worker fatal\n",
        pbs_stdout_text="worker stdout\n",
    )

    async def scenario() -> None:
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.press("4")
            await pilot.pause()
            _select_first_problem(app)
            await pilot.pause()

            viewer = app.screen.query_one("#context-viewer", TextFileViewer)
            assert viewer.state.resource is not None
            assert viewer.state.resource.key == "pbs_stderr"
            assert "worker fatal" in viewer.text

    asyncio.run(scenario())


def test_problem_without_stream_routes_to_inspector_reason(tmp_path: Path) -> None:
    app = _app(
        tmp_path,
        status="blocked",
        stderr_text=None,
        stdout_text=None,
    )

    async def scenario() -> None:
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.press("4")
            await pilot.pause()
            _select_first_problem(app)
            await pilot.pause()

            assert app.query_one("#views").active == "monitor"
            inspector = app.query_one(TaskInspector)
            assert "blocked without runtime stream" in inspector.primary_text
            assert app.selected_task == "analysis"

    asyncio.run(scenario())
