from __future__ import annotations

import hashlib
import json
import multiprocessing
import socket
import sys
import time
from pathlib import Path

import pytest

from simpleworkflow.engine import WorkflowEngine
from simpleworkflow.locking import WorkflowLockedError
from simpleworkflow.runs import RunRecorder


def _run_sleeping_workflow(workdir: str, marker: str) -> None:
    config = {
        "workflow": {"name": "exclusive"},
        "tasks": [{"name": "task", "argv": [sys.executable, "-c", f"import time; time.sleep(1); open({marker!r}, 'a').write('x')"]}],
    }
    engine = WorkflowEngine(config, workdir=workdir)
    try:
        engine.run()
    finally:
        engine.state.close()


def test_second_controller_is_rejected(tmp_path: Path) -> None:
    workdir = tmp_path / ".simpleworkflow"
    marker = tmp_path / "calls.txt"
    process = multiprocessing.Process(
        target=_run_sleeping_workflow, args=(str(workdir), str(marker))
    )
    process.start()
    time.sleep(0.2)
    engine = WorkflowEngine(
        {"workflow": {"name": "exclusive"}, "tasks": []}, workdir=workdir
    )
    try:
        try:
            engine.run()
        except WorkflowLockedError:
            pass
        else:
            raise AssertionError("second controller was not rejected")
    finally:
        engine.state.close()
        process.join()
    assert marker.read_text(encoding="utf-8") == "x"
    assert (workdir / "lock").is_file()


def test_running_attempt_is_recovered_from_final_metadata(tmp_path: Path) -> None:
    workdir = tmp_path / ".simpleworkflow"
    attempt = workdir / "runs" / "run-a" / "tasks" / "task-a" / "attempt-001"
    attempt.mkdir(parents=True)
    (attempt / "metadata.json").write_text(
        json.dumps({"status": "success", "return_code": 0}), encoding="utf-8"
    )
    engine = WorkflowEngine(
        {"workflow": {"name": "recover"}, "tasks": []},
        workdir=workdir,
    )
    engine.state.set_status(
        "task",
        "running",
        None,
        "signature",
        attempt_path=attempt,
    )
    engine.state.reconcile_running()
    assert engine.state.get_status("task") == "success"
    recovered = engine.state.get_task_state("task")
    assert recovered is not None and recovered.attempt_path is not None
    assert not Path(recovered.attempt_path).is_absolute()
    engine.state.close()



def test_running_attempt_with_valid_metadata_checksum_is_recovered(tmp_path: Path) -> None:
    workdir = tmp_path / ".simpleworkflow"
    attempt = workdir / "runs" / "run-checksum" / "tasks" / "task-a" / "attempt-001"
    attempt.mkdir(parents=True)
    metadata = attempt / "metadata.json"
    metadata.write_text(
        json.dumps({"status": "success", "return_code": 0}) + "\n",
        encoding="utf-8",
    )
    (attempt / "metadata.sha256").write_text(
        hashlib.sha256(metadata.read_bytes()).hexdigest() + "\n",
        encoding="utf-8",
    )
    engine = WorkflowEngine(
        {"workflow": {"name": "recover-checksum"}, "tasks": []},
        workdir=workdir,
    )
    engine.state.set_status("task", "running", None, "signature", attempt_path=attempt)

    engine.state.reconcile_running()

    assert engine.state.get_status("task") == "success"
    engine.state.close()


def test_running_attempt_with_mismatched_metadata_checksum_becomes_unknown(
    tmp_path: Path,
) -> None:
    workdir = tmp_path / ".simpleworkflow"
    attempt = workdir / "runs" / "run-corrupt" / "tasks" / "task-a" / "attempt-001"
    attempt.mkdir(parents=True)
    (attempt / "metadata.json").write_text(
        json.dumps({"status": "success", "return_code": 0}) + "\n",
        encoding="utf-8",
    )
    (attempt / "metadata.sha256").write_text("0" * 64 + "\n", encoding="utf-8")
    engine = WorkflowEngine(
        {"workflow": {"name": "recover-corrupt"}, "tasks": []},
        workdir=workdir,
    )
    engine.state.set_status("task", "running", None, "signature", attempt_path=attempt)

    engine.state.reconcile_running()

    recovered = engine.state.get_task_state("task")
    assert recovered is not None
    assert recovered.status == "unknown"
    assert recovered.return_code is None
    assert recovered.reason is not None and "metadata.sha256" in recovered.reason
    engine.state.close()


def test_descendants_become_blocked_after_dependency_failure(tmp_path: Path) -> None:
    config = {
        "workflow": {"name": "blocked"},
        "tasks": [
            {"name": "a", "argv": [sys.executable, "-c", "raise SystemExit(7)"]},
            {"name": "b", "argv": [sys.executable, "-c", "print('b')"], "depends_on": ["a"]},
            {"name": "c", "argv": [sys.executable, "-c", "print('c')"], "depends_on": ["b"]},
        ],
    }
    engine = WorkflowEngine(config, workdir=tmp_path / ".simpleworkflow")
    assert engine.run() == 7
    assert engine.state.get_status("b") == "blocked"
    assert engine.state.get_status("c") == "blocked"
    engine.state.close()



def test_running_attempt_without_terminal_record_becomes_unknown(tmp_path: Path) -> None:
    workdir = tmp_path / ".simpleworkflow"
    attempt = workdir / "runs" / "run-missing" / "tasks" / "task-a" / "attempt-001"
    attempt.mkdir(parents=True)
    engine = WorkflowEngine(
        {"workflow": {"name": "recover-missing"}, "tasks": []},
        workdir=workdir,
    )
    engine.state.set_status("task", "running", None, "signature", attempt_path=attempt)

    engine.state.reconcile_running()

    recovered = engine.state.get_task_state("task")
    assert recovered is not None
    assert recovered.status == "unknown"
    assert recovered.return_code is None
    assert recovered.reason is not None and "não há prova persistente" in recovered.reason
    engine.state.close()


def test_dead_local_process_without_terminal_record_becomes_unknown(tmp_path: Path) -> None:
    workdir = tmp_path / ".simpleworkflow"
    attempt = workdir / "runs" / "run-dead" / "tasks" / "task-a" / "attempt-001"
    attempt.mkdir(parents=True)
    process = multiprocessing.Process(target=lambda: None)
    process.start()
    pid = process.pid
    process.join()
    assert pid is not None
    (attempt / "process.json").write_text(
        json.dumps({"pid": pid, "host": socket.gethostname()}),
        encoding="utf-8",
    )
    engine = WorkflowEngine(
        {"workflow": {"name": "recover-dead"}, "tasks": []},
        workdir=workdir,
    )
    engine.state.set_status("task", "running", None, "signature", attempt_path=attempt)

    engine.state.reconcile_running()

    assert engine.state.get_status("task") == "unknown"
    engine.state.close()


def test_pending_pbs_submission_without_job_id_becomes_unknown(tmp_path: Path) -> None:
    workdir = tmp_path / ".simpleworkflow"
    attempt = workdir / "runs" / "run-pbs" / "tasks" / "task-a" / "attempt-001"
    attempt.mkdir(parents=True)
    (attempt / "scheduler.json").write_text(
        json.dumps({"job_id": None, "submission_pending": True}),
        encoding="utf-8",
    )
    engine = WorkflowEngine(
        {"workflow": {"name": "recover-pbs"}, "tasks": []},
        workdir=workdir,
    )
    engine.state.set_status("task", "running", None, "signature", attempt_path=attempt)

    engine.state.reconcile_running()

    recovered = engine.state.get_task_state("task")
    assert recovered is not None
    assert recovered.status == "unknown"
    assert recovered.reason is not None and "submissão PBS" in recovered.reason
    engine.state.close()


def test_unknown_recovery_blocks_automatic_reexecution(tmp_path: Path) -> None:
    workdir = tmp_path / ".simpleworkflow"
    attempt = workdir / "runs" / "run-block" / "tasks" / "task-a" / "attempt-001"
    attempt.mkdir(parents=True)
    config = {
        "workflow": {"name": "recover-block"},
        "tasks": [{"name": "task", "argv": [sys.executable, "-c", "print('must not run')"]}],
    }
    engine = WorkflowEngine(config, workdir=workdir)
    engine.state.set_status("task", "running", None, "signature", attempt_path=attempt)

    with pytest.raises(RuntimeError, match="não é seguro continuar"):
        engine.run()

    assert engine.state.get_status("task") == "unknown"
    run_directories = [path.name for path in (workdir / "runs").iterdir() if path.is_dir()]
    assert run_directories == ["run-block"]
    assert not (attempt / "metadata.json").exists()
    engine.state.close()



@pytest.mark.parametrize("payload", ["null", "[]", '"not-an-object"'])
def test_malformed_scheduler_json_falls_back_to_unknown(
    tmp_path: Path, payload: str
) -> None:
    workdir = tmp_path / ".simpleworkflow"
    attempt = workdir / "runs" / "run-malformed" / "tasks" / "task-a" / "attempt-001"
    attempt.mkdir(parents=True)
    (attempt / "scheduler.json").write_text(payload, encoding="utf-8")
    engine = WorkflowEngine(
        {"workflow": {"name": "recover-malformed"}, "tasks": []},
        workdir=workdir,
    )
    engine.state.set_status("task", "running", None, "signature", attempt_path=attempt)

    engine.state.reconcile_running()

    recovered = engine.state.get_task_state("task")
    assert recovered is not None
    assert recovered.status == "unknown"
    engine.state.close()


def test_unrelated_unknown_task_does_not_block_selected_task(tmp_path: Path) -> None:
    workdir = tmp_path / ".simpleworkflow"
    config = {
        "workflow": {"name": "selected-safe"},
        "tasks": [
            {"name": "wanted", "argv": [sys.executable, "-c", "print('wanted')"]},
            {"name": "other", "argv": [sys.executable, "-c", "print('other')"]},
        ],
    }
    engine = WorkflowEngine(config, workdir=workdir, selected_tasks={"wanted"})
    engine.state.set_status("other", "unknown", None, reason="unrelated uncertain work")

    assert engine.run() == 0
    assert engine.state.get_status("wanted") == "success"
    assert engine.state.get_status("other") == "unknown"
    engine.state.close()


def test_removed_unknown_task_does_not_block_current_workflow(tmp_path: Path) -> None:
    workdir = tmp_path / ".simpleworkflow"
    config = {
        "workflow": {"name": "removed-safe"},
        "tasks": [{"name": "current", "argv": [sys.executable, "-c", "print('current')"]}],
    }
    engine = WorkflowEngine(config, workdir=workdir)
    engine.state.set_status("removed-task", "unknown", None, reason="old workflow definition")

    assert engine.run() == 0
    assert engine.state.get_status("current") == "success"
    assert engine.state.get_status("removed-task") == "unknown"
    engine.state.close()



def test_recovery_from_terminal_metadata_reconciles_attempt_and_run_history(
    tmp_path: Path,
) -> None:
    workdir = tmp_path / ".simpleworkflow"
    engine = WorkflowEngine(
        {"workflow": {"name": "recover-history"}, "tasks": []},
        workdir=workdir,
    )
    recorder = RunRecorder(
        workdir,
        "recover-history",
        instance_id=engine.state.instance_id,
        run_id="run-recover-history",
    )
    engine.state.record_run(recorder.run_id, recorder.directory)
    attempt = recorder.begin_attempt("task")
    recorder.write_started(
        attempt,
        {"status": "running", "command": {"argv": ["true"], "cwd": None, "env": {}}, "signature": "sig"},
    )
    engine.state.record_attempt_started(
        run_id=attempt.run_id,
        task="task",
        attempt=attempt.attempt,
        attempt_path=attempt.directory,
        signature="sig",
    )
    engine.state.set_status(
        "task",
        "running",
        None,
        "sig",
        "tarefa iniciada",
        attempt.directory,
    )
    recorder.write_metadata(
        attempt,
        {"status": "success", "return_code": 0, "reason": "completed before controller loss"},
    )

    engine.state.reconcile_running()

    task = engine.state.get_task_state("task")
    assert task is not None and task.status == "success"
    attempt_row = engine.state.connection.execute(
        """
        SELECT status, return_code, reason, finished_at
        FROM attempt_history
        WHERE run_id = ? AND task = ? AND attempt = ?
        """,
        (attempt.run_id, "task", attempt.attempt),
    ).fetchone()
    assert attempt_row is not None
    assert attempt_row[0] == "success"
    assert attempt_row[1] == 0
    assert attempt_row[2] == "completed before controller loss"
    assert attempt_row[3] is not None

    run_row = engine.state.connection.execute(
        "SELECT status, finished_at FROM run_history WHERE run_id = ?",
        (attempt.run_id,),
    ).fetchone()
    assert run_row is not None
    assert run_row[0] == "interrupted"
    assert run_row[1] is not None
    engine.state.close()


def test_finalize_attempt_rolls_back_if_task_state_update_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workdir = tmp_path / ".simpleworkflow"
    engine = WorkflowEngine(
        {"workflow": {"name": "atomic-finalize"}, "tasks": []},
        workdir=workdir,
    )
    recorder = RunRecorder(
        workdir,
        "atomic-finalize",
        instance_id=engine.state.instance_id,
        run_id="run-atomic-finalize",
    )
    engine.state.record_run(recorder.run_id, recorder.directory)
    attempt = recorder.begin_attempt("task")
    engine.state.record_attempt_started(
        run_id=attempt.run_id,
        task="task",
        attempt=attempt.attempt,
        attempt_path=attempt.directory,
        signature="sig",
    )
    engine.state.set_status(
        "task",
        "running",
        None,
        "sig",
        "tarefa iniciada",
        attempt.directory,
    )

    def fail_task_state(*_args: object, **_kwargs: object) -> None:
        raise sqlite3.OperationalError("injected task-state failure")

    import sqlite3

    monkeypatch.setattr(engine.state, "_write_task_state_event", fail_task_state)
    with pytest.raises(sqlite3.OperationalError, match="injected"):
        engine.state.finalize_attempt(
            run_id=attempt.run_id,
            task="task",
            attempt=attempt.attempt,
            status="success",
            return_code=0,
            signature="sig",
            reason="done",
            attempt_path=attempt.directory,
        )

    attempt_status = engine.state.connection.execute(
        """
        SELECT status, return_code, finished_at
        FROM attempt_history
        WHERE run_id = ? AND task = ? AND attempt = ?
        """,
        (attempt.run_id, "task", attempt.attempt),
    ).fetchone()
    assert attempt_status == ("running", None, None)
    current = engine.state.get_task_state("task")
    assert current is not None and current.status == "running"
    engine.state.close()


def test_unexpected_executor_exception_finishes_run_as_interrupted(tmp_path: Path) -> None:
    class ExplodingExecutor:
        def run(self, *_args: object, **_kwargs: object) -> object:
            raise RuntimeError("controller-side failure")

    config = {
        "workflow": {"name": "run-finally"},
        "tasks": [{"name": "task", "argv": [sys.executable, "-c", "print('unused')"]}],
    }
    engine = WorkflowEngine(config, workdir=tmp_path / ".simpleworkflow")
    engine.executor = ExplodingExecutor()  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="controller-side failure"):
        engine.run()

    row = engine.state.connection.execute(
        "SELECT status, finished_at FROM run_history"
    ).fetchone()
    assert row is not None
    assert row[0] == "interrupted"
    assert row[1] is not None
    assert engine.state.get_status("task") == "running"
    engine.state.close()
