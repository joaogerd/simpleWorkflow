from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

from simpleworkflow.runs import RunRecorder
from simpleworkflow.state import WorkflowState
from simpleworkflow.tui import WorkflowTui, _latest_attempt, _parse_cycle


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


def _dated_config() -> dict[str, object]:
    return {
        "workflow": {"name": "dated_tui_test"},
        "tasks": [
            {
                "name": "jedi00_prepare",
                "argv": [
                    "monan-jedi-workflow",
                    "jedi-prepare",
                    "case",
                    "--cycle",
                    "2018-04-15T00:00:00Z",
                ],
            },
            {
                "name": "mpas00_prepare",
                "argv": [
                    "monan-jedi-workflow",
                    "mpas-prepare",
                    "case",
                    "--cycle",
                    "2018-04-15T00:00:00Z",
                ],
                "depends_on": ["jedi00_prepare"],
            },
            {
                "name": "obs06_prepare",
                "argv": [
                    "monan-jedi-workflow",
                    "obs2ioda-prepare",
                    "case",
                    "--cycle",
                    "2018-04-15T06:00:00Z",
                ],
                "depends_on": ["mpas00_prepare"],
            },
            {
                "name": "jedi06_prepare",
                "argv": [
                    "monan-jedi-workflow",
                    "jedi-prepare",
                    "case",
                    "--cycle",
                    "2018-04-15T06:00:00Z",
                ],
                "depends_on": ["obs06_prepare"],
            },
            {
                "name": "jedi00_next_prepare",
                "argv": [
                    "monan-jedi-workflow",
                    "jedi-prepare",
                    "case",
                    "--cycle",
                    "2018-04-16T00:00:00Z",
                ],
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


def test_parse_cycle_uses_explicit_cycle_argument() -> None:
    task = {
        "name": "jedi12_prepare",
        "argv": ["cmd", "--cycle", "2018-04-15T12:00:00Z"],
    }

    cycle = _parse_cycle(task)

    assert cycle is not None
    assert cycle.day == date(2018, 4, 15)
    assert cycle.hour == "12"


def test_textual_monitor_mounts_with_minimal_layout(tmp_path: Path) -> None:
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
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            assert app.selected_task == "jedi06_prepare"
            assert app.selected_date is None
            assert set(app.task_nodes) == {"jedi06_prepare", "jedi06_validate"}
            assert app.engine.state.get_status("tui_test", "jedi06_prepare") == "success"
            assert app.query_one("#topbar") is not None
            assert app.query_one("#cycle-line") is not None
            assert app.query_one("#cycle-00") is not None
            assert app.query_one("#cycles-table") is not None
            assert app.query_one("#campaign-view") is not None
            assert app.query_one("#problems-table") is not None
            assert app.query_one("#open-logs") is not None
            assert app.query_one("#log-toolbar") is not None
            assert app.query_one("#shortcut-line") is not None
            assert app.query_one("#task-filter") is not None

    asyncio.run(scenario())


def test_dated_monitor_cycles_are_clickable(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: dated_tui_test\n", encoding="utf-8")

    state = WorkflowState(tmp_path / "state.sqlite3")
    state.set_status("dated_tui_test", "jedi00_prepare", "success", 0)
    state.set_status("dated_tui_test", "mpas00_prepare", "success", 0)
    state.set_status("dated_tui_test", "obs06_prepare", "success", 0)
    state.set_status("dated_tui_test", "jedi06_prepare", "running", None)
    state.close()

    app = WorkflowTui(
        config=_dated_config(),
        workflow_path=workflow,
        workdir=tmp_path,
        refresh_seconds=60.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            assert app.selected_date == date(2018, 4, 15)
            assert app.selected_hour == "06"
            assert set(app.task_nodes) == {"obs06_prepare", "jedi06_prepare"}

            await pilot.click("#cycle-00")
            await pilot.pause()
            assert app.selected_hour == "00"
            assert set(app.task_nodes) == {"jedi00_prepare", "mpas00_prepare"}

            await pilot.click("#cycle-06")
            await pilot.pause()
            assert app.selected_hour == "06"
            assert set(app.task_nodes) == {"obs06_prepare", "jedi06_prepare"}

            await pilot.click("#next-date")
            await pilot.pause()
            assert app.selected_date == date(2018, 4, 16)
            assert app.selected_hour == "00"
            assert set(app.task_nodes) == {"jedi00_next_prepare"}

            await pilot.click("#prev-date")
            await pilot.pause()
            assert app.selected_date == date(2018, 4, 15)

            views = app.query_one("#views")
            assert views.active == "monitor"
            await pilot.press("tab")
            await pilot.pause()
            assert views.active == "cycles"

    asyncio.run(scenario())


def test_logs_can_be_opened_and_selected_by_click(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: tui_test\n", encoding="utf-8")

    state = WorkflowState(tmp_path / "state.sqlite3")
    state.set_status("tui_test", "jedi06_prepare", "success", 0)
    state.close()

    recorder = RunRecorder(tmp_path, "tui_test", run_id="20260912T010000.000000Z-test")
    attempt = recorder.begin_attempt("jedi06_prepare")
    attempt.stdout_path.write_text("launcher output\n", encoding="utf-8")
    attempt.stderr_path.write_text("launcher warning\n", encoding="utf-8")
    recorder.write_metadata(
        attempt,
        {
            "status": "success",
            "return_code": 0,
            "execution": {"executor": "local"},
        },
    )

    app = WorkflowTui(
        config=_config(),
        workflow_path=workflow,
        workdir=tmp_path,
        refresh_seconds=60.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            assert app.selected_task == "jedi06_prepare"
            assert app.selected_log_name == "stdout.log"

            views = app.query_one("#views")
            assert views.active == "monitor"
            await pilot.click("#open-logs")
            await pilot.pause()
            assert views.active == "logs"

            await pilot.click("#log-stderr")
            await pilot.pause()
            assert app.selected_log_name == "stderr.log"

            await pilot.click("#log-stdout")
            await pilot.pause()
            assert app.selected_log_name == "stdout.log"

            views.active = "monitor"
            await pilot.press("v")
            await pilot.pause()
            assert views.active == "logs"

    asyncio.run(scenario())


def test_filter_and_problems_link_to_failure_log(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: dated_tui_test\n", encoding="utf-8")

    state = WorkflowState(tmp_path / "state.sqlite3")
    state.set_status("dated_tui_test", "jedi00_prepare", "success", 0)
    state.set_status("dated_tui_test", "obs06_prepare", "failed", 7)
    state.close()

    recorder = RunRecorder(tmp_path, "dated_tui_test", run_id="failure-run")
    attempt = recorder.begin_attempt("obs06_prepare")
    attempt.stderr_path.write_text("setup detail\nroot cause message\n", encoding="utf-8")
    recorder.write_metadata(
        attempt,
        {
            "status": "failed",
            "return_code": 7,
            "execution": {"executor": "local"},
        },
    )

    app = WorkflowTui(
        config=_dated_config(),
        workflow_path=workflow,
        workdir=tmp_path,
        refresh_seconds=5.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            problems = app.query_one("#problems-table")
            assert problems.row_count == 1
            assert "root cause message" in str(problems.get_row_at(0)[-1])

            await pilot.press("/")
            await pilot.pause()
            field = app.query_one("#task-filter")
            assert field.display
            await pilot.press("o", "b", "s")
            await pilot.pause()
            assert app.task_filter == "obs"
            assert set(app.task_nodes) == {"obs06_prepare"}
            await pilot.press("enter")

            app.query_one("#views").active = "problems"
            problems.focus()
            problems.move_cursor(row=0)
            await pilot.press("enter")
            await pilot.pause()
            assert app.query_one("#views").active == "logs"
            assert app.selected_task == "obs06_prepare"
            assert app.selected_log_name == "stderr.log"

    asyncio.run(scenario())
