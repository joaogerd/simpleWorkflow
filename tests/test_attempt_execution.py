from __future__ import annotations

import json
import sys
from pathlib import Path

from simpleworkflow.engine import WorkflowEngine


def _attempt_directory(workdir: Path) -> Path:
    run_directories = [path for path in (workdir / "runs").iterdir() if path.is_dir()]
    assert len(run_directories) == 1
    attempts = list(run_directories[0].glob("tasks/*/attempt-001"))
    assert len(attempts) == 1
    return attempts[0]


def test_engine_records_successful_attempt_logs_and_metadata(tmp_path: Path) -> None:
    workflow_path = tmp_path / "workflow.yaml"
    workflow_path.write_text("workflow: {name: attempt-success}\n", encoding="utf-8")
    execution_dir = tmp_path / "execution"
    execution_dir.mkdir()
    workdir = tmp_path / ".simpleworkflow"
    command = "import sys; print('stdout marker'); print('stderr marker', file=sys.stderr)"
    config = {
        "workflow": {"name": "attempt-success"},
        "context": {"python": sys.executable, "cwd": str(execution_dir)},
        "tasks": [
            {
                "name": "diagnostics",
                "argv": ["{python}", "-c", command],
                "cwd": "{cwd}",
                "env": {"OMP_NUM_THREADS": "1"},
            }
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow_path),
            "source_dir": str(tmp_path),
        },
    }

    engine = WorkflowEngine(config, workdir=workdir)

    assert engine.run() == 0

    attempt = _attempt_directory(workdir)
    assert attempt.joinpath("stdout.log").read_text(encoding="utf-8") == "stdout marker\n"
    assert attempt.joinpath("stderr.log").read_text(encoding="utf-8").endswith("stderr marker\n")

    metadata = json.loads(attempt.joinpath("metadata.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "success"
    assert metadata["return_code"] == 0
    assert metadata["process_return_code"] == 0
    assert metadata["command"]["argv"] == [sys.executable, "-c", command]
    assert metadata["command"]["env"] == {"OMP_NUM_THREADS": "1"}
    assert metadata["signature"]["value"]


def test_engine_records_failed_process_attempt(tmp_path: Path) -> None:
    workflow_path = tmp_path / "workflow.yaml"
    workflow_path.write_text("workflow: {name: attempt-failure}\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    command = "import sys; print('failure marker', file=sys.stderr); sys.exit(7)"
    config = {
        "workflow": {"name": "attempt-failure"},
        "context": {"python": sys.executable},
        "tasks": [{"name": "analysis", "argv": ["{python}", "-c", command]}],
        "__simpleworkflow__": {
            "source_path": str(workflow_path),
            "source_dir": str(tmp_path),
        },
    }

    engine = WorkflowEngine(config, workdir=workdir)

    assert engine.run() == 7

    attempt = _attempt_directory(workdir)
    metadata = json.loads(attempt.joinpath("metadata.json").read_text(encoding="utf-8"))
    assert attempt.joinpath("stderr.log").read_text(encoding="utf-8").endswith("failure marker\n")
    assert metadata["status"] == "failed"
    assert metadata["return_code"] == 7
    assert metadata["process_return_code"] == 7
    assert metadata["reason"] == "process exited with return code 7"
