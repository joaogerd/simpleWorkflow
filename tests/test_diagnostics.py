from __future__ import annotations

import sys
from pathlib import Path

from simpleworkflow.engine import BLOCKED_EXIT_CODE, WorkflowEngine


def test_selected_task_includes_dependencies(tmp_path: Path) -> None:
    config = {
        "workflow": {"name": "selection"},
        "tasks": [
            {"name": "a", "argv": [sys.executable, "-c", "print('a')"]},
            {"name": "b", "argv": [sys.executable, "-c", "print('b')"], "depends_on": ["a"]},
            {"name": "c", "argv": [sys.executable, "-c", "print('c')"]},
        ],
    }
    engine = WorkflowEngine(config, workdir=tmp_path, selected_tasks={"b"})
    assert engine.plan() == ["a", "b"]


def test_disabled_dependency_blocks_dependent_task(tmp_path: Path) -> None:
    config = {
        "workflow": {"name": "disabled"},
        "tasks": [
            {"name": "a", "argv": [sys.executable, "-c", "print('a')"], "enabled": False},
            {"name": "b", "argv": [sys.executable, "-c", "print('b')"], "depends_on": ["a"]},
        ],
    }
    engine = WorkflowEngine(config, workdir=tmp_path)
    assert engine.run() == BLOCKED_EXIT_CODE
    assert engine.state.get_status("disabled", "b") == "blocked"


def test_validate_reports_missing_input_without_running(tmp_path: Path) -> None:
    missing = tmp_path / "missing.nc"
    config = {
        "workflow": {"name": "validate"},
        "tasks": [
            {
                "name": "a",
                "argv": [sys.executable, "-c", "raise SystemExit('must not run')"],
                "inputs": {"required": [str(missing)]},
            }
        ],
    }
    engine = WorkflowEngine(config, workdir=tmp_path / ".simpleworkflow")
    problems = engine.validate()
    assert len(problems) == 1 and str(missing) in problems[0]
