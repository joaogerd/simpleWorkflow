from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
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



def _cycle_ids_13() -> list[tuple[str, str]]:
    start = datetime(2018, 4, 15, tzinfo=timezone.utc)
    values: list[tuple[str, str]] = []
    for index in range(13):
        current = start + timedelta(hours=6 * index)
        values.append(
            (
                current.strftime("%Y%m%d%H"),
                current.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        )
    return values


def _monan_jedi_185_config(workflow: Path) -> dict[str, object]:
    cycles = _cycle_ids_13()
    stages = ("prepare", "submit", "wait", "validate", "gate")
    tasks: list[dict[str, object]] = [
        {"name": f"global_{index}", "argv": ["true"]}
        for index in range(5)
    ]

    for cycle_id, cycle_time in cycles:
        for stage in stages:
            task: dict[str, object] = {
                "name": f"jedi{cycle_id}_{stage}",
                "argv": ["jedi", stage, "--cycle", cycle_time],
            }
            if cycle_id == cycles[-2][0] and stage == "submit":
                task["executor"] = "pbs"
                task["pbs"] = {
                    "queue": "pesqmini",
                    "select": 1,
                    "ncpus": 64,
                    "walltime": "00:30:00",
                }
            tasks.append(task)

    for cycle_id, cycle_time in cycles[1:]:
        for stage in stages:
            tasks.append(
                {
                    "name": f"obs{cycle_id}_{stage}",
                    "argv": ["obs", stage, "--cycle", cycle_time],
                }
            )

    for cycle_id, cycle_time in cycles[:-2]:
        for stage in stages:
            tasks.append(
                {
                    "name": f"mpas{cycle_id}_{stage}",
                    "argv": ["mpas", stage, "--cycle", cycle_time],
                }
            )

    assert len(tasks) == 185
    return {
        "workflow": {"name": "m3-3days"},
        "tasks": tasks,
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }


def _persist_monan_jedi_185(
    workflow: Path,
    workdir: Path,
    config: dict[str, object],
) -> tuple[str, str]:
    cycles = _cycle_ids_13()
    running_task = f"jedi{cycles[-2][0]}_submit"
    failed_task = f"obs{cycles[-1][0]}_gate"

    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="m3-3days",
        source_path=workflow,
    )
    raw_tasks = config["tasks"]
    assert isinstance(raw_tasks, list)
    for task in raw_tasks:
        assert isinstance(task, dict)
        name = str(task["name"])
        if name == running_task:
            continue
        if name == failed_task:
            state.set_status(
                name,
                "failed",
                7,
                reason="observation gate failed",
            )
        else:
            state.set_status(name, "success", 0)

    recorder = RunRecorder(
        workdir,
        "m3-3days",
        instance_id=state.instance_id,
        run_id="pbs-retry-run",
    )
    state.record_run(recorder.run_id, recorder.directory)

    first = recorder.begin_attempt(running_task)
    recorder.write_started(
        first,
        {
            "status": "running",
            "command": {
                "argv": ["jedi", "submit"],
                "cwd": str(workflow.parent),
                "env": {},
            },
            "signature": "sig-1",
        },
    )
    first.stderr_path.write_text("first attempt failed\n", encoding="utf-8")
    state.record_attempt_started(
        run_id=first.run_id,
        task=running_task,
        attempt=first.attempt,
        attempt_path=first.directory,
        signature="sig-1",
        started_at="2018-04-17T18:00:10Z",
    )
    state.record_attempt_finished(
        run_id=first.run_id,
        task=running_task,
        attempt=first.attempt,
        status="failed",
        return_code=7,
        reason="first attempt failed",
    )

    second = recorder.begin_attempt(running_task)
    recorder.write_started(
        second,
        {
            "status": "running",
            "command": {
                "argv": ["jedi", "submit"],
                "cwd": str(workflow.parent),
                "env": {},
            },
            "signature": "sig-2",
        },
    )
    second.stdout_path.write_text("qsub accepted\n", encoding="utf-8")
    second.stderr_path.write_text("", encoding="utf-8")
    pbs_stdout = second.directory / "pbs.stdout.log"
    pbs_stderr = second.directory / "pbs.stderr.log"
    pbs_stdout.write_text("JEDI running\n", encoding="utf-8")
    pbs_stderr.write_text("", encoding="utf-8")
    job_script = second.directory / "job.pbs"
    job_script.write_text("#!/bin/bash\necho JEDI\n", encoding="utf-8")
    scheduler = {
        "executor": "pbs",
        "job_id": "99123.pbs-ha",
        "script": str(job_script),
        "job_stdout": str(pbs_stdout),
        "job_stderr": str(pbs_stderr),
    }
    (second.directory / "scheduler.json").write_text(
        json.dumps(scheduler) + "\n",
        encoding="utf-8",
    )
    (second.directory / "metadata.json").write_text(
        json.dumps(
            {
                "command": {
                    "argv": ["jedi", "submit"],
                    "cwd": str(workflow.parent),
                    "env": {},
                },
                "execution": scheduler,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    state.record_attempt_started(
        run_id=second.run_id,
        task=running_task,
        attempt=second.attempt,
        attempt_path=second.directory,
        signature="sig-2",
        started_at="2018-04-17T18:10:00Z",
    )
    state.set_status(
        running_task,
        "running",
        None,
        "sig-2",
        "PBS job running",
        second.directory,
    )
    state.close()
    return running_task, failed_task


def test_monan_jedi_185_reconstructs_cycles_attempts_and_failures(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: m3-3days\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    config = _monan_jedi_185_config(workflow)
    running_task, failed_task = _persist_monan_jedi_185(
        workflow,
        workdir,
        config,
    )

    app_a = WorkflowTui(
        config=config,
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60,
    )

    async def first_open() -> None:
        async with app_a.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            assert len(app_a.snapshot.cycles) == 13
            assert app_a.snapshot.total_tasks == 185
            running = next(
                task
                for cycle in app_a.snapshot.cycles
                for task in cycle.tasks
                if task.name == running_task
            )
            assert [attempt.attempt for attempt in running.attempts] == [2, 1]
            assert running.attempt is not None
            assert running.attempt.job_id == "99123.pbs-ha"
            assert any(
                problem.task_name == failed_task
                for problem in app_a.snapshot.problems
            )
            await pilot.press("q")

    asyncio.run(first_open())

    app_b = WorkflowTui(
        config=config,
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60,
    )

    async def reopened() -> None:
        async with app_b.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            assert len(app_b.snapshot.cycles) == 13
            assert app_b.snapshot.total_tasks == 185
            assert app_b.selected_task == running_task
            inspector = app_b.query_one(TaskInspector)
            assert len(inspector.attempts) == 2
            assert "99123.pbs-ha" in inspector.primary_text
            resource_keys = {resource.key for resource in inspector.resources}
            assert {"stdout", "stderr", "pbs_stdout", "pbs_stderr", "pbs_script"} <= resource_keys

    asyncio.run(reopened())


def test_pbs_monitoring_reads_persisted_metadata_without_scheduler_calls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import simpleworkflow.pbs as pbs

    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: m3-3days\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    config = _monan_jedi_185_config(workflow)
    running_task, _ = _persist_monan_jedi_185(workflow, workdir, config)

    def forbidden_scheduler_call(*args: object, **kwargs: object) -> object:
        raise AssertionError("TUI must not invoke qstat, qdel, or qsub")

    monkeypatch.setattr(pbs.subprocess, "run", forbidden_scheduler_call)

    app = WorkflowTui(
        config=config,
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60,
    )

    async def scenario() -> None:
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            assert app.selected_task == running_task
            inspector = app.query_one(TaskInspector)
            assert "99123.pbs-ha" in inspector.primary_text
            keys = {resource.key for resource in inspector.resources}
            assert "pbs_script" in keys
            assert "pbs_stdout" in keys
            assert "pbs_stderr" in keys

    asyncio.run(scenario())
