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
