from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from simpleworkflow.state import WorkflowState
from simpleworkflow.tui import WorkflowTui


def _config(workflow: Path) -> dict[str, object]:
    return {
        "workflow": {"name": "restart_tui"},
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


def _unrolled_config(workflow: Path) -> dict[str, object]:
    return {
        "workflow": {"name": "restart_unrolled"},
        "tasks": [
            {"name": "setup", "argv": ["true"]},
            {
                "name": "analysis00",
                "depends_on": ["setup"],
                "argv": ["tool", "analysis", "--cycle", "2018-04-15T00:00:00Z"],
            },
            {"name": "gate00", "depends_on": ["analysis00"], "argv": ["tool", "gate"]},
            {
                "name": "analysis06",
                "depends_on": ["gate00"],
                "argv": ["tool", "analysis", "--cycle", "2018-04-15T06:00:00Z"],
            },
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }


def _write_partial_state(workflow: Path, workdir: Path) -> None:
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="restart_tui",
        source_path=workflow,
    )
    state.ensure_cycle("2018041500", "2018-04-15T00:00:00Z")
    state.ensure_cycle("2018041506", "2018-04-15T06:00:00Z")
    for task in ("prepare", "analysis", "forecast"):
        state.set_status(task, "success", 0, cycle_id="2018041500")
    state.set_status("prepare", "success", 0, cycle_id="2018041506")
    state.set_status("analysis", "running", None, cycle_id="2018041506")
    state.close()


def test_monitor_reopens_to_same_persisted_running_state(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: restart_tui}\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    _write_partial_state(workflow, workdir)

    async def inspect(app: WorkflowTui) -> tuple[str | None, str | None, int, int]:
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            return (
                app.selected_cycle_id,
                app.selected_task,
                app.snapshot.completed_tasks,
                app.snapshot.running_tasks,
            )

    first = asyncio.run(
        inspect(
            WorkflowTui(
                config=_config(workflow),
                workflow_path=workflow,
                workdir=workdir,
                refresh_seconds=60,
            )
        )
    )
    second = asyncio.run(
        inspect(
            WorkflowTui(
                config=_config(workflow),
                workflow_path=workflow,
                workdir=workdir,
                refresh_seconds=60,
            )
        )
    )

    assert first == second == ("2018041506", "analysis", 4, 1)


def test_monitor_reopens_failure_from_sqlite_only(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: restart_tui}\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="restart_tui",
        source_path=workflow,
    )
    state.ensure_cycle("2018041506", "2018-04-15T06:00:00Z")
    state.set_status("prepare", "success", 0, cycle_id="2018041506")
    state.set_status(
        "analysis",
        "failed",
        9,
        reason="process exited with return code 9",
        cycle_id="2018041506",
    )
    state.set_status(
        "forecast",
        "blocked",
        4,
        reason="dependência indisponível: analysis",
        cycle_id="2018041506",
    )
    state.close()

    app = WorkflowTui(
        config=_config(workflow),
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60,
    )

    async def scenario() -> None:
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            assert app.selected_cycle_id == "2018041506"
            assert app.selected_task == "analysis"
            assert app.snapshot.failed_tasks == 2
            assert [problem.task_name for problem in app.snapshot.problems] == [
                "analysis",
                "forecast",
            ]

    asyncio.run(scenario())


def test_monitor_reopens_completed_workflow_from_persisted_state(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: restart_tui}\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="restart_tui",
        source_path=workflow,
    )
    state.ensure_cycle("2018041500", "2018-04-15T00:00:00Z")
    for task in ("prepare", "analysis", "forecast"):
        state.set_status(task, "success", 0, cycle_id="2018041500")
    state.close()

    async def inspect() -> tuple[int, int, int, str]:
        app = WorkflowTui(
            config=_config(workflow),
            workflow_path=workflow,
            workdir=workdir,
            refresh_seconds=60,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            return (
                app.snapshot.completed_tasks,
                app.snapshot.running_tasks,
                app.snapshot.failed_tasks,
                app.snapshot.cycles[0].status,
            )

    assert asyncio.run(inspect()) == (3, 0, 0, "success")
    assert asyncio.run(inspect()) == (3, 0, 0, "success")


def test_unrolled_monitor_reopens_after_events_were_missed(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: restart_unrolled}\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    config = _unrolled_config(workflow)
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="restart_unrolled",
        source_path=workflow,
    )
    state.set_status("setup", "success", 0)
    state.set_status("analysis00", "success", 0)
    state.set_status("gate00", "success", 0)
    state.set_status("analysis06", "running", None)
    state.close()

    first = WorkflowTui(
        config=config,
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60,
    )

    async def inspect(app: WorkflowTui) -> tuple[int, int, list[str], list[str]]:
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            return (
                app.snapshot.completed_tasks,
                app.snapshot.running_tasks,
                [cycle.status for cycle in app.snapshot.cycles],
                [task.name for task in app.snapshot.tasks],
            )

    assert asyncio.run(inspect(first)) == (3, 1, ["success", "running"], ["setup"])

    # The monitor is now closed. Persist a transition it never observed.
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="restart_unrolled",
        source_path=workflow,
    )
    state.set_status("analysis06", "success", 0)
    state.close()

    reopened = WorkflowTui(
        config=config,
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60,
    )
    assert asyncio.run(inspect(reopened)) == (4, 0, ["success", "success"], ["setup"])


def test_no_color_disables_semantic_color_without_changing_symbols(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: restart_tui}\n", encoding="utf-8")
    monkeypatch.setenv("NO_COLOR", "1")

    app = WorkflowTui(
        config=_config(workflow),
        workflow_path=workflow,
        workdir=tmp_path / ".simpleworkflow",
        refresh_seconds=60,
        color=True,
    )

    assert app.color_enabled is False
