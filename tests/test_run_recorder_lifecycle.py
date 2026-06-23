from __future__ import annotations

import sys
from pathlib import Path

from simpleworkflow.engine import WorkflowEngine


def test_all_reused_tasks_do_not_create_an_empty_run_record(tmp_path: Path) -> None:
    workdir = tmp_path / ".simpleworkflow"
    config = {
        "workflow": {"name": "reuse-only"},
        "context": {"python": sys.executable},
        "tasks": [
            {
                "name": "task",
                "argv": ["{python}", "-c", "print('ok')"],
            }
        ],
        "__simpleworkflow__": {"source_dir": str(tmp_path)},
    }
    engine = WorkflowEngine(config, workdir=workdir)

    assert engine.run() == 0
    first_runs = [path for path in (workdir / "runs").iterdir() if path.is_dir()]
    assert len(first_runs) == 1

    assert engine.run() == 0
    second_runs = [path for path in (workdir / "runs").iterdir() if path.is_dir()]
    assert second_runs == first_runs


def test_preflight_failure_does_not_create_a_run_record(tmp_path: Path) -> None:
    workdir = tmp_path / ".simpleworkflow"
    config = {
        "workflow": {"name": "invalid-input"},
        "context": {"python": sys.executable, "case_dir": str(tmp_path / "case")},
        "tasks": [
            {
                "name": "task",
                "argv": ["{python}", "-c", "print('should not run')"],
                "inputs": {"required": ["{case_dir}/background.nc"]},
            }
        ],
        "__simpleworkflow__": {"source_dir": str(tmp_path)},
    }
    engine = WorkflowEngine(config, workdir=workdir)

    assert engine.run() == 2
    assert not (workdir / "runs").exists()
