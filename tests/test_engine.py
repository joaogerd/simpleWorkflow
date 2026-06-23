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
