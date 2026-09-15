from __future__ import annotations

from pathlib import Path

from simpleworkflow.monitor import load_monitor_snapshot
from simpleworkflow.state import WorkflowState


def _unrolled_config(workflow: Path) -> dict[str, object]:
    return {
        "workflow": {"name": "monan_unrolled"},
        "tasks": [
            {
                "name": "jedi00_prepare",
                "argv": ["tool", "jedi-prepare", "--cycle", "2018-04-15T00:00:00Z"],
            },
            {
                "name": "jedi00_gate",
                "depends_on": ["jedi00_prepare"],
                "argv": ["tool", "validation-gate", "jedi00-validation.json"],
            },
            {
                "name": "obs06_prepare",
                "depends_on": ["jedi00_gate"],
                "argv": ["tool", "obs-prepare", "--cycle", "2018-04-15T06:00:00Z"],
            },
            {
                "name": "jedi06_prepare",
                "depends_on": ["obs06_prepare"],
                "argv": ["tool", "jedi-prepare", "--cycle", "2018-04-15T06:00:00Z"],
            },
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }


def test_unrolled_workflow_uses_config_cycles_for_presentation(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: monan_unrolled}\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="monan_unrolled",
        source_path=workflow,
    )
    state.set_status("jedi00_prepare", "success", 0)
    state.set_status("jedi00_gate", "success", 0)
    state.set_status("obs06_prepare", "success", 0)
    state.set_status("jedi06_prepare", "running", None)
    state.close()

    snapshot = load_monitor_snapshot(_unrolled_config(workflow), workflow, workdir)

    assert [cycle.cycle_id for cycle in snapshot.cycles] == ["2018041500", "2018041506"]
    assert [task.name for task in snapshot.cycles[0].tasks] == [
        "jedi00_prepare",
        "jedi00_gate",
    ]
    assert [task.name for task in snapshot.cycles[1].tasks] == [
        "obs06_prepare",
        "jedi06_prepare",
    ]
    assert snapshot.cycles[0].status == "success"
    assert snapshot.cycles[1].status == "running"
    assert snapshot.total_tasks == 4
    assert snapshot.completed_tasks == 3
    assert snapshot.running_tasks == 1


def test_unrolled_noncyclic_setup_task_remains_visible_once(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: monan_unrolled}\n", encoding="utf-8")
    config = _unrolled_config(workflow)
    config["tasks"] = [
        {"name": "setup", "argv": ["true"]},
        *config["tasks"],
    ]
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="monan_unrolled",
        source_path=workflow,
    )
    state.set_status("setup", "success", 0)
    state.close()

    snapshot = load_monitor_snapshot(config, workflow, workdir)

    assert [task.name for task in snapshot.tasks] == ["setup"]
    assert snapshot.total_tasks == 5
    assert len({task.name for task in snapshot.all_tasks}) == 5
