from __future__ import annotations

from pathlib import Path

from simpleworkflow.monitor import load_monitor_snapshot
from simpleworkflow.runs import RunRecorder
from simpleworkflow.state import WorkflowState


def _config(workflow: Path) -> dict[str, object]:
    return {
        "workflow": {"name": "release05"},
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


def test_native_cycle_snapshot_distinguishes_partial_and_completed_workflow(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: release05}\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="release05",
        source_path=workflow,
    )
    state.ensure_cycle("2018041500", "2018-04-15T00:00:00Z")
    state.set_status("prepare", "success", 0, cycle_id="2018041500")
    state.close()

    partial = load_monitor_snapshot(_config(workflow), workflow, workdir)
    assert partial.cycles[0].status == "partial"
    assert partial.completed_tasks == 1
    assert partial.running_tasks == 0
    assert partial.failed_tasks == 0

    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="release05",
        source_path=workflow,
    )
    state.set_status("analysis", "success", 0, cycle_id="2018041500")
    state.set_status("forecast", "success", 0, cycle_id="2018041500")
    state.close()

    completed = load_monitor_snapshot(_config(workflow), workflow, workdir)
    assert completed.cycles[0].status == "success"
    assert completed.completed_tasks == 3
    assert completed.running_tasks == 0
    assert completed.failed_tasks == 0


def test_root_workflow_snapshot_reconstructs_completed_state_without_cycles(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: release05}\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="release05",
        source_path=workflow,
    )
    for task in ("prepare", "analysis", "forecast"):
        state.set_status(task, "success", 0)
    state.close()

    snapshot = load_monitor_snapshot(_config(workflow), workflow, workdir)

    assert snapshot.cycles == ()
    assert [task.status for task in snapshot.tasks] == ["success", "success", "success"]
    assert snapshot.completed_tasks == 3


def test_attempt_files_are_optional_and_sqlite_state_remains_usable(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: release05}\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="release05",
        source_path=workflow,
    )
    recorder = RunRecorder(
        workdir,
        "release05",
        instance_id=state.instance_id,
        run_id="run-incomplete-files",
    )
    state.record_run(recorder.run_id, recorder.directory)
    attempt = recorder.begin_attempt("analysis")
    state.record_attempt_started(
        run_id=attempt.run_id,
        task="analysis",
        attempt=attempt.attempt,
        attempt_path=attempt.directory,
        signature="sig",
        started_at="2018-04-15T06:00:00Z",
    )
    state.set_status(
        "analysis",
        "running",
        None,
        "sig",
        "running from persisted state",
        attempt.directory,
    )
    state.close()

    # Simulate an interrupted/incomplete provenance directory. None of these
    # complementary files is required to reconstruct the operational state.
    (attempt.directory / "started.json").unlink(missing_ok=True)
    attempt.stdout_path.unlink(missing_ok=True)
    attempt.stderr_path.unlink(missing_ok=True)
    (attempt.directory / "metadata.json").unlink(missing_ok=True)
    (attempt.directory / "scheduler.json").unlink(missing_ok=True)
    (attempt.directory / "pbs.stdout.log").unlink(missing_ok=True)
    (attempt.directory / "pbs.stderr.log").unlink(missing_ok=True)

    snapshot = load_monitor_snapshot(_config(workflow), workflow, workdir)
    task = next(task for task in snapshot.tasks if task.name == "analysis")

    assert task.status == "running"
    assert task.reason == "running from persisted state"
    assert task.attempt is not None
    assert task.attempt.command is None
    assert task.attempt.executor is None
    assert task.attempt.job_id is None
    assert task.attempt.metadata is None
    assert task.attempt.scheduler is None
    assert task.attempt.available_logs == {}
