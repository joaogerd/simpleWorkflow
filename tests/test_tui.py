from __future__ import annotations

import asyncio
from pathlib import Path

from simpleworkflow.state import WorkflowState
from simpleworkflow.tui import WorkflowTui


def _config(workflow: Path) -> dict[str, object]:
    return {
        "workflow": {"name": "MONAN-JEDI M3"},
        "tasks": [
            {"name": "prepare", "argv": ["true"]},
            {"name": "obs2ioda", "argv": ["true"], "depends_on": ["prepare"]},
            {"name": "analysis", "argv": ["true"], "depends_on": ["obs2ioda"]},
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
        workflow_name="MONAN-JEDI M3",
        source_path=workflow,
    )
    for cycle_id, cycle_time in (
        ("2018041500", "2018-04-15T00:00:00Z"),
        ("2018041506", "2018-04-15T06:00:00Z"),
        ("2018041512", "2018-04-15T12:00:00Z"),
        ("2018041518", "2018-04-15T18:00:00Z"),
    ):
        state.ensure_cycle(cycle_id, cycle_time)
    for task in ("prepare", "obs2ioda", "analysis", "forecast"):
        state.set_status(task, "success", 0, cycle_id="2018041500")
    state.set_status("prepare", "success", 0, cycle_id="2018041506")
    state.set_status("obs2ioda", "success", 0, cycle_id="2018041506")
    state.set_status("analysis", "running", None, cycle_id="2018041506")
    state.close()


def test_monitor_mounts_with_approved_five_views_and_inspector(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: MONAN-JEDI M3\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    _persist_campaign(workflow, workdir)
    app = WorkflowTui(
        config=_config(workflow),
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            views = app.query_one("#views")
            assert views.active == "monitor"
            assert app.query_one("#task-tree") is not None
            assert app.query_one("#inspector") is not None
            assert app.query_one("#cycles-table") is not None
            assert app.query_one("#campaign-view") is not None
            assert app.query_one("#problems-table") is not None
            assert app.query_one("#full-log") is not None
            assert app.selected_cycle_id == "2018041506"
            assert app.selected_task == "analysis"

    asyncio.run(scenario())


def test_tab_cycles_through_exactly_five_operational_views(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: MONAN-JEDI M3\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    _persist_campaign(workflow, workdir)
    app = WorkflowTui(
        config=_config(workflow),
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(120, 35)) as pilot:
            views = app.query_one("#views")
            visited = [views.active]
            for _ in range(4):
                await pilot.press("tab")
                await pilot.pause()
                visited.append(views.active)
            assert visited == ["monitor", "cycles", "campaign", "problems", "logs"]

    asyncio.run(scenario())


def test_narrow_terminal_keeps_monitor_usable(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: MONAN-JEDI M3\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    _persist_campaign(workflow, workdir)
    app = WorkflowTui(
        config=_config(workflow),
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(72, 26)) as pilot:
            await pilot.pause()
            assert app.query_one("#task-tree").display
            assert app.selected_task == "analysis"
            assert app.query_one("#shortcut-line") is not None

    asyncio.run(scenario())
