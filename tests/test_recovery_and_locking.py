from __future__ import annotations

import json
import multiprocessing
import sys
import time
from pathlib import Path

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
