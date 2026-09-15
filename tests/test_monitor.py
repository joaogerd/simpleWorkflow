from __future__ import annotations

from pathlib import Path

from simpleworkflow.monitor import load_monitor_snapshot
from simpleworkflow.state import WorkflowState


def _config(workflow: Path) -> dict[str, object]:
    return {
        "workflow": {"name": "campaign"},
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


def test_snapshot_without_cycles_exposes_pending_config_tasks(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: campaign\n", encoding="utf-8")

    snapshot = load_monitor_snapshot(_config(workflow), workflow, tmp_path / ".simpleworkflow")

    assert snapshot.workflow_name == "campaign"
    assert snapshot.cycles == ()
    assert [task.name for task in snapshot.tasks] == ["prepare", "analysis", "forecast"]
    assert [task.status for task in snapshot.tasks] == ["pending", "pending", "pending"]
    assert snapshot.total_tasks == 3
    assert snapshot.completed_tasks == 0
    assert snapshot.running_tasks == 0
    assert snapshot.failed_tasks == 0


def test_snapshot_uses_persisted_cycles_and_task_states(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: campaign\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="campaign",
        source_path=workflow,
    )
    state.ensure_cycle("2018041500", "2018-04-15T00:00:00Z")
    state.ensure_cycle("2018041506", "2018-04-15T06:00:00Z")
    state.set_status("prepare", "success", 0, cycle_id="2018041500")
    state.set_status("analysis", "success", 0, cycle_id="2018041500")
    state.set_status("forecast", "success", 0, cycle_id="2018041500")
    state.set_status("prepare", "success", 0, cycle_id="2018041506")
    state.set_status("analysis", "running", None, cycle_id="2018041506")
    state.close()

    snapshot = load_monitor_snapshot(_config(workflow), workflow, workdir)

    assert [cycle.cycle_id for cycle in snapshot.cycles] == ["2018041500", "2018041506"]
    assert [cycle.status for cycle in snapshot.cycles] == ["success", "running"]
    assert snapshot.completed_tasks == 4
    assert snapshot.running_tasks == 1
    assert snapshot.failed_tasks == 0
    cycle06 = snapshot.cycles[1]
    assert [(task.name, task.status) for task in cycle06.tasks] == [
        ("prepare", "success"),
        ("analysis", "running"),
        ("forecast", "pending"),
    ]


def test_snapshot_collects_attention_states_as_problems(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: campaign\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="campaign",
        source_path=workflow,
    )
    state.ensure_cycle("2018041506", "2018-04-15T06:00:00Z")
    state.set_status(
        "analysis",
        "failed",
        7,
        reason="process exited with return code 7",
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

    snapshot = load_monitor_snapshot(_config(workflow), workflow, workdir)

    assert snapshot.failed_tasks == 2
    assert [(problem.task_name, problem.status) for problem in snapshot.problems] == [
        ("analysis", "failed"),
        ("forecast", "blocked"),
    ]
    assert snapshot.problems[0].reason == "process exited with return code 7"


def test_snapshot_reads_existing_state_without_modifying_database(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: campaign\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="campaign",
        source_path=workflow,
    )
    state.set_status("prepare", "success", 0)
    before = state.connection.execute("SELECT COUNT(*) FROM state_event").fetchone()[0]
    state.close()

    snapshot = load_monitor_snapshot(_config(workflow), workflow, workdir)

    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="campaign",
        source_path=workflow,
        read_only=True,
    )
    after = state.connection.execute("SELECT COUNT(*) FROM state_event").fetchone()[0]
    state.close()
    assert snapshot.tasks[0].status == "success"
    assert after == before
