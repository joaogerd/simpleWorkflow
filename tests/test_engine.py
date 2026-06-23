from __future__ import annotations

import sys
from pathlib import Path

from simpleworkflow.engine import WorkflowEngine


def test_plan_orders_dependencies(tmp_path: Path) -> None:
    config = {
        "workflow": {"name": "test"},
        "context": {},
        "tasks": [
            {
                "name": "second",
                "argv": [sys.executable, "-c", "print('second')"],
                "depends_on": ["first"],
            },
            {"name": "first", "argv": [sys.executable, "-c", "print('first')"]},
        ],
    }
    engine = WorkflowEngine(config=config, workdir=tmp_path / ".simpleworkflow")
    assert engine.plan() == ["first", "second"]


def test_run_executes_argv_with_cwd_and_environment(tmp_path: Path) -> None:
    execution_dir = tmp_path / "execution"
    execution_dir.mkdir()
    config = {
        "workflow": {"name": "run-test"},
        "context": {
            "python": sys.executable,
            "cwd": str(execution_dir),
            "value": "expected",
        },
        "tasks": [
            {
                "name": "write-result",
                "argv": [
                    "{python}",
                    "-c",
                    "import os; from pathlib import Path; Path('result.txt').write_text(os.environ['VALUE'])",
                ],
                "cwd": "{cwd}",
                "env": {"VALUE": "{value}"},
            }
        ],
    }
    engine = WorkflowEngine(config=config, workdir=tmp_path / ".simpleworkflow")
    assert engine.run() == 0
    assert (execution_dir / "result.txt").read_text(encoding="utf-8") == "expected"
    assert engine.state.get_status("run-test", "write-result") == "success"


def test_run_rejects_missing_required_input(tmp_path: Path) -> None:
    execution_dir = tmp_path / "execution"
    execution_dir.mkdir()
    result = execution_dir / "result.txt"
    config = {
        "workflow": {"name": "missing-input"},
        "context": {
            "python": sys.executable,
            "cwd": str(execution_dir),
            "case_dir": str(tmp_path / "case"),
        },
        "tasks": [
            {
                "name": "write-result",
                "argv": [
                    "{python}",
                    "-c",
                    "from pathlib import Path; Path('result.txt').write_text('ran')",
                ],
                "cwd": "{cwd}",
                "inputs": {"required": ["{case_dir}/background.nc"]},
            }
        ],
        "__simpleworkflow__": {"source_dir": str(tmp_path)},
    }

    engine = WorkflowEngine(config=config, workdir=tmp_path / ".simpleworkflow")
    assert engine.run() == 2
    assert not result.exists()
    assert engine.state.get_status("missing-input", "write-result") == "invalid-input"


def test_run_allows_unmatched_optional_input_glob(tmp_path: Path) -> None:
    execution_dir = tmp_path / "execution"
    execution_dir.mkdir()
    config = {
        "workflow": {"name": "optional-input"},
        "context": {"python": sys.executable, "cwd": str(execution_dir)},
        "tasks": [
            {
                "name": "write-result",
                "argv": [
                    "{python}",
                    "-c",
                    "from pathlib import Path; Path('result.txt').write_text('ok')",
                ],
                "cwd": "{cwd}",
                "inputs": {"optional": ["missing/*.nc4"]},
            }
        ],
        "__simpleworkflow__": {"source_dir": str(tmp_path)},
    }

    engine = WorkflowEngine(config=config, workdir=tmp_path / ".simpleworkflow")
    assert engine.run() == 0
    assert (execution_dir / "result.txt").read_text(encoding="utf-8") == "ok"


def test_success_state_is_invalidated_when_required_input_disappears(tmp_path: Path) -> None:
    config = {
        "workflow": {"name": "stale-input"},
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

    engine = WorkflowEngine(config=config, workdir=tmp_path / ".simpleworkflow")
    engine.state.set_status("stale-input", "task", "success", 0)

    assert engine.run() == 2
    assert engine.state.get_status("stale-input", "task") == "invalid-input"
