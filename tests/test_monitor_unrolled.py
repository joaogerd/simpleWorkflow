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


def test_unrolled_gate_inherits_only_when_every_dependency_is_same_cycle(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: conservative}\n", encoding="utf-8")
    config: dict[str, object] = {
        "workflow": {"name": "conservative"},
        "tasks": [
            {"name": "global_setup", "argv": ["true"]},
            {
                "name": "analysis00",
                "argv": ["tool", "analysis", "--cycle", "2018-04-15T00:00:00Z"],
            },
            {
                "name": "obs00",
                "argv": ["tool", "obs", "--cycle", "2018-04-15T00:00:00Z"],
            },
            {
                "name": "same_cycle_gate",
                "depends_on": ["analysis00", "obs00"],
                "argv": ["tool", "gate"],
            },
            {
                "name": "analysis06",
                "argv": ["tool", "analysis", "--cycle", "2018-04-15T06:00:00Z"],
            },
            {
                "name": "mixed_cycle_gate",
                "depends_on": ["analysis00", "analysis06"],
                "argv": ["tool", "gate"],
            },
            {
                "name": "cycle_and_global_gate",
                "depends_on": ["analysis00", "global_setup"],
                "argv": ["tool", "gate"],
            },
            {"name": "global_cleanup", "depends_on": ["mixed_cycle_gate"], "argv": ["true"]},
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }

    snapshot = load_monitor_snapshot(config, workflow, tmp_path / ".simpleworkflow")

    groups = {
        cycle.cycle_id: [task.name for task in cycle.tasks]
        for cycle in snapshot.cycles
    }
    assert groups["2018041500"] == ["analysis00", "obs00", "same_cycle_gate"]
    assert groups["2018041506"] == ["analysis06"]
    assert [task.name for task in snapshot.tasks] == [
        "global_setup",
        "mixed_cycle_gate",
        "cycle_and_global_gate",
        "global_cleanup",
    ]


def test_unrolled_waits_for_all_dependency_cycles_before_inheriting(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: ordering}\n", encoding="utf-8")
    config: dict[str, object] = {
        "workflow": {"name": "ordering"},
        "tasks": [
            {
                "name": "cycle00",
                "argv": ["tool", "run", "--cycle", "2018-04-15T00:00:00Z"],
            },
            {"name": "bridge00", "depends_on": ["cycle00"], "argv": ["tool", "gate"]},
            {
                "name": "ambiguous_join",
                "depends_on": ["bridge00", "late06"],
                "argv": ["tool", "join"],
            },
            {
                "name": "cycle06",
                "argv": ["tool", "run", "--cycle", "2018-04-15T06:00:00Z"],
            },
            {"name": "late06", "depends_on": ["cycle06"], "argv": ["tool", "gate"]},
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }

    snapshot = load_monitor_snapshot(config, workflow, tmp_path / ".simpleworkflow")

    assert [task.name for task in snapshot.tasks] == ["ambiguous_join"]
    assert [task.name for task in snapshot.cycles[0].tasks] == ["cycle00", "bridge00"]
    assert [task.name for task in snapshot.cycles[1].tasks] == ["cycle06", "late06"]


def test_unrolled_shared_global_task_is_not_forced_into_either_cycle(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: shared}\n", encoding="utf-8")
    config: dict[str, object] = {
        "workflow": {"name": "shared"},
        "tasks": [
            {"name": "shared_input", "argv": ["tool", "prepare"]},
            {
                "name": "cycle00",
                "depends_on": ["shared_input"],
                "argv": ["tool", "run", "--cycle", "2018-04-15T00:00:00Z"],
            },
            {
                "name": "cycle06",
                "depends_on": ["shared_input"],
                "argv": ["tool", "run", "--cycle", "2018-04-15T06:00:00Z"],
            },
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }

    snapshot = load_monitor_snapshot(config, workflow, tmp_path / ".simpleworkflow")

    assert [task.name for task in snapshot.tasks] == ["shared_input"]
    assert [[task.name for task in cycle.tasks] for cycle in snapshot.cycles] == [
        ["cycle00"],
        ["cycle06"],
    ]


def test_native_cycle_state_takes_priority_over_unrolled_presentation_groups(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: native_first}\n", encoding="utf-8")
    config: dict[str, object] = {
        "workflow": {"name": "native_first"},
        "tasks": [
            {
                "name": "task",
                "argv": ["tool", "run", "--cycle", "1999-01-01T00:00:00Z"],
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
        workflow_name="native_first",
        source_path=workflow,
    )
    state.ensure_cycle("2018041500", "2018-04-15T00:00:00Z")
    state.set_status("task", "success", 0, cycle_id="2018041500")
    state.close()

    snapshot = load_monitor_snapshot(config, workflow, workdir)

    assert [cycle.cycle_id for cycle in snapshot.cycles] == ["2018041500"]
    assert snapshot.cycles[0].persisted is True
    assert snapshot.cycles[0].tasks[0].status == "success"
