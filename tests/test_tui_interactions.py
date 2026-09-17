from __future__ import annotations

import asyncio
from pathlib import Path

from simpleworkflow.runs import RunRecorder
from simpleworkflow.state import WorkflowState
from simpleworkflow.tui_interactive import InteractiveWorkflowTui


def _config(workflow: Path) -> dict[str, object]:
    return {
        "workflow": {"name": "interactive_campaign"},
        "tasks": [
            {"name": "prepare", "argv": ["true"]},
            {"name": "analysis", "argv": ["true"], "depends_on": ["prepare"]},
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }


def _persist(workflow: Path, workdir: Path) -> None:
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
        ("2018041606", "2018-04-16T06:00:00Z"),
    ):
        state.ensure_cycle(cycle_id, cycle_time)
    for task in ("prepare", "analysis"):
        state.set_status(task, "success", 0, cycle_id="2018041500")
        state.set_status(task, "success", 0, cycle_id="2018041506")
    state.set_status("prepare", "success", 0, cycle_id="2018041512")
    state.set_status("analysis", "running", None, cycle_id="2018041512")
    state.close()


def _app(tmp_path: Path) -> tuple[InteractiveWorkflowTui, Path, Path]:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: interactive_campaign\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    _persist(workflow, workdir)
    return (
        InteractiveWorkflowTui(
            config=_config(workflow),
            workflow_path=workflow,
            workdir=workdir,
            refresh_seconds=60.0,
        ),
        workflow,
        workdir,
    )


def test_cycle_and_date_controls_are_clickable(tmp_path: Path) -> None:
    app, _, _ = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            assert app.selected_cycle_id == "2018041512"
            assert "15/04/2018" in str(app.query_one("#date-label").render())

            await pilot.click("#cycle-slot-0")
            await pilot.pause()
            assert app.selected_cycle_id == "2018041500"

            await pilot.click("#next-date")
            await pilot.pause()
            assert app.selected_cycle_id == "2018041600"
            assert "16/04/2018" in str(app.query_one("#date-label").render())

            await pilot.click("#prev-date")
            await pilot.pause()
            assert app.selected_cycle_id == "2018041500"

    asyncio.run(scenario())


def test_filter_and_inspector_logs_action_are_operational(tmp_path: Path) -> None:
    app, _, workdir = _app(tmp_path)
    recorder = RunRecorder(workdir, "interactive_campaign", run_id="ux-test")
    attempt = recorder.begin_attempt("analysis", cycle_id="2018041512")
    attempt.stdout_path.write_text("analysis output\n", encoding="utf-8")
    recorder.write_metadata(
        attempt,
        {
            "status": "running",
            "execution": {"executor": "local"},
        },
    )

    async def scenario() -> None:
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            assert app.selected_task == "analysis"

            await pilot.press("/")
            await pilot.pause()
            field = app.query_one("#task-filter")
            assert field.display
            await pilot.press("a", "n", "a")
            await pilot.pause()
            assert app.task_filter == "ana"
            assert all("analysis" in name for _, name in app.task_nodes)

            await pilot.press("escape")
            await pilot.pause()
            assert not field.display

            button = app.query_one("#open-logs")
            assert not button.disabled
            await pilot.click("#open-logs")
            await pilot.pause()
            assert app.query_one("#views").active == "logs"
            assert "analysis output" in app.current_log_text

    asyncio.run(scenario())


def test_campaign_rows_navigate_back_to_monitor(tmp_path: Path) -> None:
    app, _, _ = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            views = app.query_one("#views")
            views.active = "campaign"
            table = app.query_one("#campaign-table")
            assert table.row_count == 2
            table.focus()
            table.move_cursor(row=1)
            await pilot.press("enter")
            await pilot.pause()
            assert views.active == "monitor"
            assert app.selected_cycle_id == "2018041600"

    asyncio.run(scenario())


def test_log_follow_can_be_paused_and_resumed(tmp_path: Path) -> None:
    app, _, workdir = _app(tmp_path)
    recorder = RunRecorder(workdir, "interactive_campaign", run_id="follow-test")
    attempt = recorder.begin_attempt("analysis", cycle_id="2018041512")
    attempt.stdout_path.write_text("first\n", encoding="utf-8")
    recorder.write_metadata(attempt, {"status": "running", "execution": {"executor": "local"}})

    async def scenario() -> None:
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            app.action_open_logs()
            app._refresh_logs(force=True)
            assert app.follow_logs
            await pilot.press("f")
            await pilot.pause()
            assert not app.follow_logs
            assert "paused" in str(app.query_one("#follow-logs").label).lower()
            await pilot.press("f")
            await pilot.pause()
            assert app.follow_logs

    asyncio.run(scenario())
