from __future__ import annotations

from pathlib import Path

import pytest

from simpleworkflow.config import load_workflow


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_argv_task_and_records_source_location(tmp_path: Path) -> None:
    workflow = write(
        tmp_path / "workflow.yaml",
        """
workflow: {name: test}
tasks:
  - name: task
    argv: [python, -c, "print('ok')"]
""",
    )
    config = load_workflow(workflow)
    assert config["tasks"][0]["argv"][0] == "python"
    assert config["__simpleworkflow__"]["source_dir"] == str(tmp_path)


def test_rejects_shell_run_field(tmp_path: Path) -> None:
    workflow = write(tmp_path / "workflow.yaml", "tasks: [{name: task, run: 'echo no'}]\n")
    with pytest.raises(ValueError, match="unsupported field 'run'"):
        load_workflow(workflow)


def test_rejects_missing_or_invalid_argv(tmp_path: Path) -> None:
    missing = write(tmp_path / "missing.yaml", "tasks: [{name: task}]\n")
    with pytest.raises(ValueError, match="must define 'argv'"):
        load_workflow(missing)
    invalid = write(tmp_path / "invalid.yaml", "tasks: [{name: task, argv: []}]\n")
    with pytest.raises(ValueError, match="non-empty list"):
        load_workflow(invalid)


def test_rejects_unknown_executor(tmp_path: Path) -> None:
    workflow = write(
        tmp_path / "workflow.yaml",
        "tasks: [{name: task, argv: [python], executor: pbs}]\n",
    )
    with pytest.raises(ValueError, match="unsupported executor"):
        load_workflow(workflow)
