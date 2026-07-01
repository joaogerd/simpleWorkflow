from __future__ import annotations

import sys
import time
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


def test_retry_reruns_transient_failure(tmp_path: Path) -> None:
    marker = tmp_path / "attempts.txt"
    result = tmp_path / "result.txt"
    script = (
        "from pathlib import Path\n"
        f"marker = Path({str(marker)!r})\n"
        f"result = Path({str(result)!r})\n"
        "attempts = int(marker.read_text()) if marker.exists() else 0\n"
        "marker.write_text(str(attempts + 1))\n"
        "if attempts == 0:\n"
        "    raise SystemExit(7)\n"
        "result.write_text('ok')\n"
    )
    config = {
        "workflow": {"name": "retry-test"},
        "context": {"python": sys.executable},
        "tasks": [
            {
                "name": "flaky",
                "argv": ["{python}", "-c", script],
                "outputs": {"required": [str(result)]},
                "retry": {"attempts": 2, "delay": "PT0S"},
            }
        ],
        "__simpleworkflow__": {"source_dir": str(tmp_path)},
    }

    engine = WorkflowEngine(config=config, workdir=tmp_path / ".simpleworkflow")
    assert engine.run() == 0
    assert marker.read_text(encoding="utf-8") == "2"
    assert result.read_text(encoding="utf-8") == "ok"


def test_parallel_runs_independent_tasks_before_downstream(tmp_path: Path) -> None:
    start = time.monotonic()
    result = tmp_path / "done.txt"
    sleep_and_write_a = (
        "import time; from pathlib import Path; "
        f"time.sleep(0.3); Path({str(tmp_path / 'a.txt')!r}).write_text('a')"
    )
    sleep_and_write_b = (
        "import time; from pathlib import Path; "
        f"time.sleep(0.3); Path({str(tmp_path / 'b.txt')!r}).write_text('b')"
    )
    combine = (
        "from pathlib import Path; "
        f"Path({str(result)!r}).write_text("
        f"Path({str(tmp_path / 'a.txt')!r}).read_text() + Path({str(tmp_path / 'b.txt')!r}).read_text())"
    )
    config = {
        "workflow": {"name": "parallel-test", "max_parallel_tasks": 2},
        "context": {"python": sys.executable},
        "tasks": [
            {"name": "a", "argv": ["{python}", "-c", sleep_and_write_a]},
            {"name": "b", "argv": ["{python}", "-c", sleep_and_write_b]},
            {
                "name": "combine",
                "argv": ["{python}", "-c", combine],
                "depends_on": ["a", "b"],
                "outputs": {"required": [str(result)]},
            },
        ],
        "__simpleworkflow__": {"source_dir": str(tmp_path)},
    }

    engine = WorkflowEngine(config=config, workdir=tmp_path / ".simpleworkflow")
    assert engine.run() == 0
    assert result.read_text(encoding="utf-8") == "ab"
    assert time.monotonic() - start < 0.55
}
