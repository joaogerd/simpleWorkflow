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


def test_loads_declarative_artifact_contract(tmp_path: Path) -> None:
    workflow = write(
        tmp_path / "workflow.yaml",
        """
workflow: {name: test}
tasks:
  - name: run_3dvar
    argv: [bash, wrappers/jaci/run_mpas_jedi.sh]
    inputs:
      required:
        - wrappers/jaci/run_mpas_jedi.sh
        - "{case_dir}/background.nc"
      optional:
        - "{case_dir}/obs/*.nc4"
    outputs:
      required:
        - "{case_dir}/analysis.nc"
    input_fingerprint: metadata
""",
    )
    config = load_workflow(workflow)
    task = config["tasks"][0]
    assert task["inputs"]["required"][0] == "wrappers/jaci/run_mpas_jedi.sh"
    assert task["outputs"]["required"] == ["{case_dir}/analysis.nc"]
    assert task["input_fingerprint"] == "metadata"


@pytest.mark.parametrize(
    "field_snippet, message",
    [
        ("inputs: []", "field 'inputs' must be a mapping"),
        ("outputs: []", "field 'outputs' must be a mapping"),
        ("inputs: {required: ['obs/*.nc4']}", "must contain explicit paths"),
        ("outputs: {optional: ['x']}", "unsupported keys"),
        ("input_fingerprint: md5", "input_fingerprint"),
    ],
)
def test_rejects_invalid_artifact_contract(
    tmp_path: Path, field_snippet: str, message: str
) -> None:
    workflow = write(
        tmp_path / "workflow.yaml",
        f"""
tasks:
  - name: task
    argv: [python]
    {field_snippet}
""",
    )
    with pytest.raises(ValueError, match=message):
        load_workflow(workflow)
