from __future__ import annotations

import json
from pathlib import Path

from simpleworkflow.monitor import load_monitor_snapshot
from simpleworkflow.runs import RunRecorder
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


def test_snapshot_loads_latest_attempt_command_logs_and_pbs_metadata(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: campaign\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="campaign",
        source_path=workflow,
    )
    state.ensure_cycle("2018041506", "2018-04-15T06:00:00Z")
    recorder = RunRecorder(
        workdir,
        "campaign",
        instance_id=state.instance_id,
        cycle_id="2018041506",
        cycle_time="2018-04-15T06:00:00Z",
        run_id="run-1",
    )
    state.record_run(
        recorder.run_id,
        recorder.directory,
        cycle_id="2018041506",
        cycle_time="2018-04-15T06:00:00Z",
    )
    attempt = recorder.begin_attempt("analysis")
    recorder.write_started(
        attempt,
        {
            "status": "running",
            "command": {
                "argv": ["mpiexec", "jedi", "analysis.yaml"],
                "cwd": "/case/work",
                "env": {},
            },
            "signature": "sig",
        },
    )
    attempt.stdout_path.write_text("qsub output\n", encoding="utf-8")
    attempt.stderr_path.write_text("", encoding="utf-8")
    (attempt.directory / "pbs.stdout.log").write_text("JEDI output\n", encoding="utf-8")
    (attempt.directory / "pbs.stderr.log").write_text("JEDI warning\n", encoding="utf-8")
    (attempt.directory / "scheduler.json").write_text(
        json.dumps({"executor": "pbs", "job_id": "381922.pbs-ha"}) + "\n",
        encoding="utf-8",
    )
    state.record_attempt_started(
        run_id=attempt.run_id,
        task="analysis",
        attempt=attempt.attempt,
        attempt_path=attempt.directory,
        signature="sig",
        cycle_id="2018041506",
        started_at="2018-04-15T06:01:04Z",
    )
    state.set_status(
        "analysis",
        "running",
        None,
        "sig",
        "tarefa iniciada",
        attempt.directory,
        cycle_id="2018041506",
    )
    state.close()

    snapshot = load_monitor_snapshot(_config(workflow), workflow, workdir)
    task = next(task for task in snapshot.cycles[0].tasks if task.name == "analysis")

    assert task.attempt is not None
    assert task.attempt.attempt == 1
    assert task.attempt.executor == "pbs"
    assert task.attempt.job_id == "381922.pbs-ha"
    assert task.attempt.command == ("mpiexec", "jedi", "analysis.yaml")
    assert task.attempt.cwd == "/case/work"
    assert task.attempt.started_at == "2018-04-15T06:01:04Z"
    assert task.attempt.finished_at is None
    assert task.attempt.log_paths["stdout"].name == "stdout.log"
    assert task.attempt.log_paths["pbs_stdout"].read_text(encoding="utf-8") == "JEDI output\n"


def test_snapshot_prefers_newest_retry_and_tolerates_missing_files(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: campaign\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="campaign",
        source_path=workflow,
    )
    state.ensure_cycle("2018041506", "2018-04-15T06:00:00Z")
    recorder = RunRecorder(
        workdir,
        "campaign",
        instance_id=state.instance_id,
        cycle_id="2018041506",
        cycle_time="2018-04-15T06:00:00Z",
        run_id="run-retry",
    )
    state.record_run(
        recorder.run_id,
        recorder.directory,
        cycle_id="2018041506",
        cycle_time="2018-04-15T06:00:00Z",
    )
    first = recorder.begin_attempt("analysis")
    state.record_attempt_started(
        run_id=first.run_id,
        task="analysis",
        attempt=first.attempt,
        attempt_path=first.directory,
        signature="sig-1",
        cycle_id="2018041506",
        started_at="2018-04-15T06:00:00Z",
    )
    state.record_attempt_finished(
        run_id=first.run_id,
        task="analysis",
        attempt=first.attempt,
        status="failed",
        return_code=7,
        reason="first failure",
    )
    second = recorder.begin_attempt("analysis")
    state.record_attempt_started(
        run_id=second.run_id,
        task="analysis",
        attempt=second.attempt,
        attempt_path=second.directory,
        signature="sig-2",
        cycle_id="2018041506",
        started_at="2018-04-15T06:05:00Z",
    )
    # Simulate incomplete filesystem provenance. SQLite remains the source of truth.
    (second.directory / "started.json").unlink(missing_ok=True)
    second.stdout_path.unlink(missing_ok=True)
    state.set_status(
        "analysis",
        "running",
        None,
        "sig-2",
        "retry in progress",
        second.directory,
        cycle_id="2018041506",
    )
    state.close()

    snapshot = load_monitor_snapshot(_config(workflow), workflow, workdir)
    task = next(task for task in snapshot.cycles[0].tasks if task.name == "analysis")

    assert task.attempt is not None
    assert task.attempt.attempt == 2
    assert task.attempt.status == "running"
    assert task.attempt.command is None
    assert task.attempt.log_paths["stdout"].exists() is False


def test_snapshot_exposes_all_attempts_newest_first(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: campaign\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="campaign",
        source_path=workflow,
    )
    state.ensure_cycle("2018041506", "2018-04-15T06:00:00Z")
    recorder = RunRecorder(
        workdir,
        "campaign",
        instance_id=state.instance_id,
        cycle_id="2018041506",
        cycle_time="2018-04-15T06:00:00Z",
        run_id="run-retry-history",
    )
    state.record_run(
        recorder.run_id,
        recorder.directory,
        cycle_id="2018041506",
        cycle_time="2018-04-15T06:00:00Z",
    )

    first = recorder.begin_attempt("analysis")
    state.record_attempt_started(
        run_id=first.run_id,
        task="analysis",
        attempt=first.attempt,
        attempt_path=first.directory,
        signature="sig-1",
        cycle_id="2018041506",
        started_at="2018-04-15T06:00:00Z",
    )
    state.record_attempt_finished(
        run_id=first.run_id,
        task="analysis",
        attempt=first.attempt,
        status="failed",
        return_code=7,
        reason="first failure",
    )

    second = recorder.begin_attempt("analysis")
    state.record_attempt_started(
        run_id=second.run_id,
        task="analysis",
        attempt=second.attempt,
        attempt_path=second.directory,
        signature="sig-2",
        cycle_id="2018041506",
        started_at="2018-04-15T06:10:00Z",
    )
    state.set_status(
        "analysis",
        "running",
        None,
        "sig-2",
        "tarefa iniciada",
        second.directory,
        cycle_id="2018041506",
    )
    state.close()

    snapshot = load_monitor_snapshot(_config(workflow), workflow, workdir)
    task = next(task for task in snapshot.cycles[0].tasks if task.name == "analysis")

    assert [attempt.attempt for attempt in task.attempts] == [2, 1]
    assert [attempt.status for attempt in task.attempts] == ["running", "failed"]
    assert task.attempt is task.attempts[0]
