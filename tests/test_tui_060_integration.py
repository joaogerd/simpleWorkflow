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


def _config(workflow: Path, *, executor: str = "pbs") -> dict[str, object]:
    task: dict[str, object] = {
        "name": "analysis",
        "argv": ["jedi", "analysis.yaml"],
        "executor": executor,
    }
    if executor == "pbs":
        task["pbs"] = {
            "queue": "pesqmini",
            "select": 1,
            "ncpus": 64,
            "walltime": "00:30:00",
        }
    return {
        "workflow": {"name": "tui060"},
        "tasks": [task],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }


def _persist_attempt(
    workflow: Path,
    workdir: Path,
    *,
    executor: str = "pbs",
    stdout_text: str = "qsub accepted\n",
    stderr_text: str = "",
    pbs_stdout_text: str = "JEDI iteration 1\n",
    pbs_stderr_text: str = "warning from worker\n",
) -> dict[str, Path]:
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="tui060",
        source_path=workflow,
    )
    state.ensure_cycle("2018041506", "2018-04-15T06:00:00Z")
    recorder = RunRecorder(
        workdir,
        "tui060",
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
            "command": {
                "argv": ["jedi", "analysis.yaml"],
                "cwd": str(workflow.parent),
                "env": {},
            },
            "signature": "sig",
        },
    )
    attempt.stdout_path.write_text(stdout_text, encoding="utf-8")
    attempt.stderr_path.write_text(stderr_text, encoding="utf-8")
    paths = {
        "stdout": attempt.stdout_path,
        "stderr": attempt.stderr_path,
    }

    metadata: dict[str, object] = {
        "command": {
            "argv": ["jedi", "analysis.yaml"],
            "cwd": str(workflow.parent),
            "env": {},
        },
        "execution": {"executor": executor},
    }
    if executor == "pbs":
        pbs_stdout = attempt.directory / "pbs.stdout.log"
        pbs_stderr = attempt.directory / "pbs.stderr.log"
        pbs_stdout.write_text(pbs_stdout_text, encoding="utf-8")
        pbs_stderr.write_text(pbs_stderr_text, encoding="utf-8")
        scheduler = {
            "executor": "pbs",
            "job_id": "381922.pbs-ha",
            "job_stdout": str(pbs_stdout),
            "job_stderr": str(pbs_stderr),
        }
        (attempt.directory / "scheduler.json").write_text(
            json.dumps(scheduler) + "\n",
            encoding="utf-8",
        )
        metadata["execution"] = scheduler
        paths["pbs_stdout"] = pbs_stdout
        paths["pbs_stderr"] = pbs_stderr

    (attempt.directory / "metadata.json").write_text(
        json.dumps(metadata) + "\n",
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
    state.set_status(
        "analysis",
        "running",
        None,
        "sig",
        "running",
        attempt.directory,
        cycle_id="2018041506",
    )
    state.close()
    return paths


def _make_app(
    tmp_path: Path,
    *,
    executor: str = "pbs",
    stdout_text: str = "qsub accepted\n",
) -> WorkflowTui:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: tui060\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    _persist_attempt(
        workflow,
        workdir,
        executor=executor,
        stdout_text=stdout_text,
    )
    return WorkflowTui(
        config=_config(workflow, executor=executor),
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60,
    )


def test_resource_enter_opens_stdout_in_internal_viewer(tmp_path: Path) -> None:
    app = _make_app(tmp_path, stdout_text="hello from stdout\n")

    async def scenario() -> None:
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            inspector = app.query_one(TaskInspector)
            assert inspector.focus_resource("stdout")
            app.query_one("#inspector-resources", DataTable).focus()

            await pilot.press("enter")
            await pilot.pause()

            viewer = app.screen.query_one(TextFileViewer)
            assert "hello from stdout" in viewer.text

            await pilot.press("escape")
            await pilot.pause()
            assert app.query_one("#task-tree") is not None

    asyncio.run(scenario())


def test_inspector_opens_each_persisted_stream_with_same_viewer(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            inspector = app.query_one(TaskInspector)
            table = app.query_one("#inspector-resources", DataTable)
            table.focus()

            expected = {
                "stdout": "qsub accepted",
                "stderr": "",
                "pbs_stdout": "JEDI iteration 1",
                "pbs_stderr": "warning from worker",
            }
            for key, fragment in expected.items():
                assert inspector.focus_resource(key)
                table.focus()
                await pilot.pause()
                table.action_select_cursor()
                await pilot.pause()
                viewer = app.screen.query_one(TextFileViewer)
                if fragment:
                    assert fragment in viewer.text
                await pilot.press("escape")
                await pilot.pause()

    asyncio.run(scenario())


def test_logs_view_uses_reusable_text_viewer_for_selected_attempt(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.press("5")
            await pilot.pause()

            viewer = app.query_one("#log-viewer", TextFileViewer)
            assert viewer.state.resource is not None
            assert viewer.state.resource.key in {
                "pbs_stdout",
                "stdout",
                "pbs_stderr",
                "stderr",
            }
            assert viewer.search("JEDI") in {0, 1}
            viewer.set_follow(False)
            assert not viewer.state.follow
            viewer.set_follow(True)
            assert viewer.state.follow

    asyncio.run(scenario())


def test_local_attempt_logs_view_does_not_offer_pbs_streams(tmp_path: Path) -> None:
    app = _make_app(tmp_path, executor="local")

    async def scenario() -> None:
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            inspector = app.query_one(TaskInspector)
            keys = {resource.key for resource in inspector.resources}
            assert {"stdout", "stderr"} <= keys
            assert "pbs_stdout" not in keys
            assert "pbs_stderr" not in keys

    asyncio.run(scenario())


def test_log_manifest_path_becomes_openable_resource(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"accepted": true}\n', encoding="utf-8")
    app = _make_app(
        tmp_path,
        executor="local",
        stdout_text=f"[OK] validation manifest accepted: {manifest}\n",
    )

    async def scenario() -> None:
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.press("5")
            await pilot.pause()

            viewer = app.query_one("#log-viewer", TextFileViewer)
            assert [resource.path for resource in viewer.related_resources] == [manifest]
            assert viewer.select_related(manifest)
            related = app.query_one("#viewer-related", DataTable)
            related.focus()
            related.action_select_cursor()
            await pilot.pause()

            opened = app.screen.query_one("#context-viewer", TextFileViewer)
            assert '"accepted": true' in opened.text

    asyncio.run(scenario())
