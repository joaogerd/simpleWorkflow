from __future__ import annotations

import sys
from pathlib import Path

from simpleworkflow.engine import INVALID_OUTPUT_EXIT_CODE, WorkflowEngine


def test_run_marks_task_invalid_when_required_output_is_missing(tmp_path: Path) -> None:
    execution_dir = tmp_path / "execution"
    execution_dir.mkdir()
    config = {
        "workflow": {"name": "missing-output"},
        "context": {"python": sys.executable, "cwd": str(execution_dir)},
        "tasks": [
            {
                "name": "run",
                "argv": ["{python}", "-c", "print('completed without output')"],
                "cwd": "{cwd}",
                "outputs": {"required": ["{cwd}/analysis.nc"]},
            }
        ],
        "__simpleworkflow__": {"source_dir": str(tmp_path)},
    }
    engine = WorkflowEngine(config=config, workdir=tmp_path / ".simpleworkflow")

    assert engine.run() == INVALID_OUTPUT_EXIT_CODE
    assert engine.state.get_status("missing-output", "run") == "invalid-output"


def test_successful_task_reruns_when_required_output_disappears(tmp_path: Path) -> None:
    execution_dir = tmp_path / "execution"
    execution_dir.mkdir()
    output = execution_dir / "analysis.nc"
    config = {
        "workflow": {"name": "rerun-output"},
        "context": {"python": sys.executable, "cwd": str(execution_dir)},
        "tasks": [
            {
                "name": "run",
                "argv": [
                    "{python}",
                    "-c",
                    "from pathlib import Path; Path('analysis.nc').write_text('analysis')",
                ],
                "cwd": "{cwd}",
                "outputs": {"required": ["{cwd}/analysis.nc"]},
            }
        ],
        "__simpleworkflow__": {"source_dir": str(tmp_path)},
    }
    engine = WorkflowEngine(config=config, workdir=tmp_path / ".simpleworkflow")
    engine.state.set_status("rerun-output", "run", "success", 0)

    assert not output.exists()
    assert engine.run() == 0
    assert output.read_text(encoding="utf-8") == "analysis"
    assert engine.state.get_status("rerun-output", "run") == "success"
