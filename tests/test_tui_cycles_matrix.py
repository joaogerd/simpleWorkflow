from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import DataTable

from simpleworkflow.state import WorkflowState
from simpleworkflow.tui import WorkflowTui


_CYCLES = (
    ("2018041500", "2018-04-15T00:00:00Z"),
    ("2018041506", "2018-04-15T06:00:00Z"),
    ("2018041512", "2018-04-15T12:00:00Z"),
)


def _config(workflow: Path) -> dict[str, object]:
    tasks: list[dict[str, object]] = []
    for cycle_id, cycle_time in _CYCLES:
        tasks.extend(
            [
                {
                    "name": f"obs{cycle_id}_prepare",
                    "argv": ["obs", "--cycle", cycle_time],
                },
                {
                    "name": f"jedi{cycle_id}_analysis",
                    "argv": ["jedi", "--cycle", cycle_time],
                },
                {
                    "name": f"mpas{cycle_id}_forecast",
                    "argv": ["mpas", "--cycle", cycle_time],
                },
            ]
        )
    return {
        "workflow": {"name": "cycle-matrix"},
        "tasks": tasks,
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }


def _persist(workflow: Path, workdir: Path) -> None:
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="cycle-matrix",
        source_path=workflow,
    )
    statuses = {
        "2018041500": ("success", "success", "success"),
        "2018041506": ("success", "running", "pending"),
        "2018041512": ("failed", "pending", "pending"),
    }
    for cycle_id, _ in _CYCLES:
        for prefix, status in zip(("obs", "jedi", "mpas"), statuses[cycle_id]):
            if status == "pending":
                continue
            state.set_status(
                f"{prefix}{cycle_id}_{'prepare' if prefix == 'obs' else 'analysis' if prefix == 'jedi' else 'forecast'}",
                status,
                7 if status == "failed" else None,
                reason="bad observations" if status == "failed" else None,
            )
    state.close()


def _app(tmp_path: Path) -> WorkflowTui:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: cycle-matrix\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    _persist(workflow, workdir)
    return WorkflowTui(
        config=_config(workflow),
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60,
    )


def test_cycles_view_is_process_by_cycle_matrix(tmp_path: Path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()

            table = app.query_one("#cycles-table", DataTable)
            assert table.cursor_type == "cell"
            assert table.column_count == 4
            assert table.row_count == 3

            rows = [table.get_row_at(index) for index in range(3)]
            assert [str(row[0]) for row in rows] == ["OBS", "JEDI", "MPAS"]
            assert "SUCCESS" in str(rows[0][1])
            assert "RUNNING" in str(rows[1][2])
            assert "FAILED" in str(rows[0][3])

    asyncio.run(scenario())


def test_cycles_matrix_cell_selects_cycle_and_returns_to_monitor(tmp_path: Path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()

            table = app.query_one("#cycles-table", DataTable)
            table.focus()
            table.move_cursor(row=1, column=2)
            table.action_select_cursor()
            await pilot.pause()

            assert app.selected_cycle_id == "2018041506"
            assert app.query_one("#views").active == "monitor"

    asyncio.run(scenario())


def test_cycles_matrix_uses_actual_cycles_not_fixed_synoptic_hours(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: irregular\n", encoding="utf-8")
    config: dict[str, object] = {
        "workflow": {"name": "irregular"},
        "tasks": [
            {
                "name": "jedi2018041503_analysis",
                "argv": ["jedi", "--cycle", "2018-04-15T03:00:00Z"],
            },
            {
                "name": "jedi2018041509_analysis",
                "argv": ["jedi", "--cycle", "2018-04-15T09:00:00Z"],
            },
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }
    state = WorkflowState(
        tmp_path / ".simpleworkflow" / "state.sqlite3",
        workflow_name="irregular",
        source_path=workflow,
    )
    state.set_status("jedi2018041503_analysis", "success", 0)
    state.set_status("jedi2018041509_analysis", "success", 0)
    state.close()
    app = WorkflowTui(
        config=config,
        workflow_path=workflow,
        workdir=tmp_path / ".simpleworkflow",
        refresh_seconds=60,
    )

    async def scenario() -> None:
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            table = app.query_one("#cycles-table", DataTable)
            assert table.column_count == 3
            assert table.row_count == 1
            assert app.cycle_matrix_columns == [
                "2018041503",
                "2018041509",
            ]

    asyncio.run(scenario())
