from __future__ import annotations

import asyncio
from pathlib import Path

from textual.coordinate import Coordinate
from textual.widgets import DataTable

from simpleworkflow.state import WorkflowState
from simpleworkflow.tui import WorkflowTui


def test_inspector_shows_daily_process_matrix_below_task_details(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: inspector_matrix}\n", encoding="utf-8")
    cycle00 = "2018-04-15T00:00:00Z"
    cycle06 = "2018-04-15T06:00:00Z"
    config: dict[str, object] = {
        "workflow": {"name": "inspector_matrix"},
        "tasks": [
            {"name": "obs00_prepare", "argv": ["tool", "prepare", "--cycle", cycle00]},
            {"name": "jedi00_run", "argv": ["tool", "run", "--cycle", cycle00]},
            {"name": "mpas00_run", "argv": ["tool", "run", "--cycle", cycle00]},
            {"name": "obs06_prepare", "argv": ["tool", "prepare", "--cycle", cycle06]},
            {"name": "jedi06_run", "argv": ["tool", "run", "--cycle", cycle06]},
            {"name": "mpas06_run", "argv": ["tool", "run", "--cycle", cycle06]},
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="inspector_matrix",
        source_path=workflow,
    )
    state.set_status("obs00_prepare", "success", 0)
    state.set_status("jedi00_run", "success", 0)
    state.set_status("mpas00_run", "running", None)
    state.set_status("obs06_prepare", "running", None)
    state.close()

    app = WorkflowTui(
        config=config,
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60,
    )

    async def scenario() -> None:
        async with app.run_test(size=(140, 42)) as pilot:
            await pilot.pause()

            right = app.query_one("#right")
            ids = [getattr(child, "id", None) for child in right.children]
            assert ids.index("inspector") < ids.index("period-matrix")

            title = app.query_one("#period-title")
            assert "PERÍODO / CICLAGEM" in str(title.render())
            assert "15/04/2018" in str(title.render())

            table = app.query_one("#period-matrix", DataTable)
            assert table.column_count == 3
            assert table.row_count == 3

            assert str(table.get_cell_at(Coordinate(0, 0))) == "OBS"
            assert "✓ SUCCESS" in str(table.get_cell_at(Coordinate(0, 1)))
            assert "● RUNNING" in str(table.get_cell_at(Coordinate(0, 2)))

            assert str(table.get_cell_at(Coordinate(1, 0))) == "JEDI"
            assert "✓ SUCCESS" in str(table.get_cell_at(Coordinate(1, 1)))
            assert "○ PENDING" in str(table.get_cell_at(Coordinate(1, 2)))

            assert str(table.get_cell_at(Coordinate(2, 0))) == "MPAS"
            assert "● RUNNING" in str(table.get_cell_at(Coordinate(2, 1)))
            assert "○ PENDING" in str(table.get_cell_at(Coordinate(2, 2)))

    asyncio.run(scenario())
