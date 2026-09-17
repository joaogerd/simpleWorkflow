from __future__ import annotations

import asyncio
import json
from pathlib import Path

from simpleworkflow.runs import RunRecorder
from simpleworkflow.state import WorkflowState
from simpleworkflow.tui import WorkflowTui


def _config(workflow: Path) -> dict[str, object]:
    return {
        "workflow": {"name": "interactive_campaign"},
        "tasks": [
            {"name": "prepare", "argv": ["true"]},
            {"name": "analysis", "argv": ["true"], "depends_on": ["prepare"]},
            {"name": "forecast", "argv": ["true"], "depends_on": ["analysis"]},
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }


def _persist_campaign(workflow: Path, workdir: Path) -> None:
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="interactive_campaign",
        source_path=workflow,
    )
    for cycle_id, cycle_time in (
        ("2018041500", "2018-04-15T00:00:00Z"),
        ("2018041506", "2018-04-15T06:00:00Z"),
        ("2018041512", "2018-04-15T12:00:00Z"),
        ("2018041518", "2018-04-15T18:00:00Z"),
        ("2018041600", "2018-04-16T00:00:00Z"),
    ):
        state.ensure_cycle(cycle_id, cycle_time)
    for task in ("prepare", "analysis", "forecast"):
        state.set_status(task, "success", 0, cycle_id="2018041500")
    state.set_status("prepare", "success", 0, cycle_id="2018041506")
    state.set_status("analysis", "running", None, cycle_id="2018041506")
    state.close()


def _persist_running_attempt(workflow: Path, workdir: Path) -> Path:
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="interactive_campaign",
        source_path=workflow,
    )
    recorder = RunRecorder(
        workdir,
        "interactive_campaign",
        instance_id=state.instance_id,
        cycle_id="2018041506",
        cycle_time="2018-04-15T06:00:00Z",
        run_id="interactive-run",
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
            "command": {"argv": ["python", "analysis.py"], "cwd": "/case", "env": {}},
            "signature": "sig",
        },
    )
    attempt.stdout_path.write_text("first line\n", encoding="utf-8")
    (attempt.directory / "scheduler.json").write_text(
        json.dumps({"executor": "pbs", "job_id": "494313.pbs-ha"}) + "\n",
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
    return attempt.stdout_path


def test_date_and_cycle_controls_navigate_persisted_cycles(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: interactive_campaign\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    _persist_campaign(workflow, workdir)
    app = WorkflowTui(
        config=_config(workflow),
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60,
    )

    async def scenario() -> None:
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            assert app.selected_cycle_id == "2018041506"
            assert "15/04/2018" in str(app.query_one("#date-label").render())
            assert app.cycle_slots["cycle-slot-2"] == "2018041512"

            await pilot.click("#cycle-slot-2")
            await pilot.pause()
            assert app.selected_cycle_id == "2018041512"

            await pilot.click("#next-date")
            await pilot.pause()
            assert app.selected_cycle_id == "2018041600"

            await pilot.click("#prev-date")
            await pilot.pause()
            assert app.selected_cycle_id == "2018041500"

            await pilot.click("#date-current")
            await pilot.pause()
            assert app.query_one("#views").active == "campaign"

    asyncio.run(scenario())


def test_workflow_tree_shows_only_selected_cycle_plus_global_tasks(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: mixed_unrolled}\n", encoding="utf-8")
    config: dict[str, object] = {
        "workflow": {"name": "mixed_unrolled"},
        "tasks": [
            {"name": "global_setup", "argv": ["true"]},
            {
                "name": "jedi2018041500_prepare",
                "argv": ["tool", "run", "--cycle", "2018-04-15T00:00:00Z"],
            },
            {
                "name": "jedi2018041506_prepare",
                "argv": ["tool", "run", "--cycle", "2018-04-15T06:00:00Z"],
            },
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="mixed_unrolled",
        source_path=workflow,
    )
    state.set_status("global_setup", "success", 0)
    state.set_status("jedi2018041500_prepare", "success", 0)
    state.set_status("jedi2018041506_prepare", "running", None)
    state.close()

    app = WorkflowTui(
        config=config,
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60,
    )

    async def scenario() -> None:
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            assert app.selected_cycle_id == "2018041506"
            assert ("2018041506", "jedi2018041506_prepare") in app.task_nodes
            assert ("2018041500", "jedi2018041500_prepare") not in app.task_nodes
            assert (None, "global_setup") in app.task_nodes

            await pilot.click("#cycle-slot-0")
            await pilot.pause()
            assert app.selected_cycle_id == "2018041500"
            assert ("2018041500", "jedi2018041500_prepare") in app.task_nodes
            assert ("2018041506", "jedi2018041506_prepare") not in app.task_nodes
            assert (None, "global_setup") in app.task_nodes

            tree = app.query_one("#task-tree")
            tree.select_node(app.task_nodes[(None, "global_setup")])
            await pilot.pause()
            assert app.selected_cycle_id == "2018041500"
            assert app.selected_task == "global_setup"
            assert "15/04/2018" in str(app.query_one("#date-label").render())
            assert "global_setup" in str(app.query_one("#inspector").render())

    asyncio.run(scenario())


def test_filter_inspector_logs_and_follow_are_interactive(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: interactive_campaign\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    _persist_campaign(workflow, workdir)
    stdout_path = _persist_running_attempt(workflow, workdir)
    app = WorkflowTui(
        config=_config(workflow),
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60,
    )

    async def scenario() -> None:
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            open_logs = app.query_one("#open-logs")
            assert not open_logs.disabled
            assert "Logs" in str(open_logs.label)

            await pilot.press("/")
            await pilot.pause()
            field = app.query_one("#task-filter")
            assert field.display
            await pilot.press("a", "n", "a", "l", "y", "s", "i", "s")
            await pilot.pause()
            assert app.task_filter == "analysis"
            assert app.task_nodes
            assert all(task_name == "analysis" for _, task_name in app.task_nodes)
            await pilot.press("escape")
            await pilot.pause()
            assert not field.display
            assert app.task_filter == ""
            assert app.selected_task == "analysis"
            assert not open_logs.disabled
            assert open_logs.region.height > 0

            # Use Button.press(), Textual's documented user-press simulation. This
            # exercises the real Button.Pressed message without Pilot's coordinate
            # hit-testing layer, which can be unstable after dynamic tree reflow.
            open_logs.press()
            await pilot.pause()
            assert app.query_one("#views").active == "logs"
            assert "first line" in app.current_log_text
            assert app.follow_logs

            await pilot.click("#log-follow")
            await pilot.pause()
            assert not app.follow_logs
            stdout_path.write_text("first line\nsecond line\n", encoding="utf-8")
            app.refresh_runtime()
            assert "second line" not in app.current_log_text

            await pilot.press("f")
            await pilot.pause()
            assert app.follow_logs
            assert "second line" in app.current_log_text

    asyncio.run(scenario())


def test_campaign_rows_select_a_day_and_return_to_monitor(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: interactive_campaign\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    _persist_campaign(workflow, workdir)
    app = WorkflowTui(
        config=_config(workflow),
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60,
    )

    async def scenario() -> None:
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            table = app.query_one("#campaign-table")
            assert table.row_count == 2
            table.focus()
            table.move_cursor(row=1)
            await pilot.press("enter")
            await pilot.pause()
            assert app.selected_cycle_id == "2018041600"
            assert app.query_one("#views").active == "monitor"

    asyncio.run(scenario())


def test_unrolled_tree_does_not_repeat_cycle_id_in_task_labels(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: unrolled}\n", encoding="utf-8")
    config: dict[str, object] = {
        "workflow": {"name": "unrolled"},
        "tasks": [
            {
                "name": "jedi2018041500_prepare",
                "argv": ["tool", "run", "--cycle", "2018-04-15T00:00:00Z"],
            }
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="unrolled",
        source_path=workflow,
    )
    state.set_status("jedi2018041500_prepare", "success", 0)
    state.close()
    app = WorkflowTui(
        config=config,
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60,
    )

    async def scenario() -> None:
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            node = app.task_nodes[("2018041500", "jedi2018041500_prepare")]
            assert "2018041500" not in str(node.label)
            assert "jedi" not in str(node.label).lower()
            assert "prepare" in str(node.label).lower()
            assert any("JEDI" in str(group.label) for group in node.parent.parent.children)

    asyncio.run(scenario())
