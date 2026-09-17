from __future__ import annotations

import asyncio
from pathlib import Path

from simpleworkflow.state import WorkflowState
from simpleworkflow.tui import WorkflowTui


def _plain(node: object) -> str:
    label = getattr(node, "label")
    return str(getattr(label, "plain", label))


def _styles(node: object) -> set[str]:
    label = getattr(node, "label")
    return {str(span.style) for span in getattr(label, "spans", ())}


def test_selected_cycle_tree_groups_processes_and_colors_status_symbols(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: process_tree}\n", encoding="utf-8")
    cycle = "2018-04-15T06:00:00Z"
    config: dict[str, object] = {
        "workflow": {"name": "process_tree"},
        "tasks": [
            {"name": "global_setup", "argv": ["true"]},
            {"name": "obs06_doctor", "argv": ["tool", "doctor", "--cycle", cycle]},
            {"name": "obs06_prepare", "argv": ["tool", "prepare", "--cycle", cycle]},
            {"name": "jedi06_prepare", "argv": ["tool", "prepare", "--cycle", cycle]},
            {"name": "jedi06_submit", "argv": ["tool", "submit", "--cycle", cycle]},
            {"name": "mpas06_prepare", "argv": ["tool", "prepare", "--cycle", cycle]},
            {"name": "qc06_check", "argv": ["tool", "check", "--cycle", cycle]},
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="process_tree",
        source_path=workflow,
    )
    state.set_status("global_setup", "success", 0)
    state.set_status("obs06_doctor", "success", 0)
    state.set_status("obs06_prepare", "success", 0)
    state.set_status("jedi06_prepare", "success", 0)
    state.set_status("jedi06_submit", "running", None)
    state.set_status("qc06_check", "failed", 1, reason="quality check failed")
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
            tree = app.query_one("#task-tree")
            groups = {_plain(node): node for node in tree.root.children}

            assert "✓ OBS" in groups
            assert "● JEDI" in groups
            assert "○ MPAS" in groups
            assert "✕ QC" in groups
            assert "✓ Workflow" in groups

            assert "green" in _styles(groups["✓ OBS"])
            assert "cyan" in _styles(groups["● JEDI"])
            assert "dim" in _styles(groups["○ MPAS"])
            assert "red" in _styles(groups["✕ QC"])

            obs_steps = [_plain(node) for node in groups["✓ OBS"].children]
            jedi_steps = [_plain(node) for node in groups["● JEDI"].children]
            mpas_steps = [_plain(node) for node in groups["○ MPAS"].children]
            qc_steps = [_plain(node) for node in groups["✕ QC"].children]

            assert obs_steps == ["✓ doctor", "✓ prepare"]
            assert jedi_steps == ["✓ prepare", "● submit"]
            assert mpas_steps == ["○ prepare"]
            assert qc_steps == ["✕ check"]
            assert "red" in _styles(groups["✕ QC"].children[0])

    asyncio.run(scenario())
