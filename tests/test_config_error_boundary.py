"""Regression tests for consistent user-facing configuration errors."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from simpleworkflow.artifacts import resolve_task_artifacts
from simpleworkflow.cli import main
from simpleworkflow.config import load_workflow
from simpleworkflow.engine import render_template
from simpleworkflow.templates import render_template as shared_renderer


@pytest.mark.parametrize("value", ["true", "1.0", "'1'"])
def test_format_version_does_not_accept_python_equality_aliases(
    tmp_path: Path, value: str
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        f"format_version: {value}\nworkflow: {{name: example}}\ntasks: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="format_version"):
        load_workflow(workflow)


def test_integer_format_version_remains_supported(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        "format_version: 1\nworkflow: {name: example}\ntasks: []\n",
        encoding="utf-8",
    )
    assert load_workflow(workflow)["format_version"] == 1


def test_public_engine_renderer_remains_compatible() -> None:
    assert render_template is shared_renderer
    assert render_template("{value}", {"value": 3}) == "3"


@pytest.mark.parametrize(
    "task",
    [
        {"name": "science", "inputs": {"required": ["{missing}/background.nc"]}},
        {"name": "science", "inputs": {"optional": ["{missing}/*.nc4"]}},
        {"name": "science", "outputs": {"required": ["{missing}/analysis.nc"]}},
        {"name": "science", "outputs": {"checks": [{"path": "{missing}/analysis.nc"}]}},
    ],
)
def test_artifact_fields_report_missing_placeholder_as_configuration_error(
    task: dict[str, object], tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match=r"Unknown context placeholder \{missing\}"):
        resolve_task_artifacts(task, {}, tmp_path)


def test_malformed_yaml_has_source_location_and_normal_cli_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workflow = tmp_path / "invalid.yaml"
    workflow.write_text("workflow: [not closed\n", encoding="utf-8")
    assert main(["plan", str(workflow), "--color", "never"]) == 2
    error = capsys.readouterr().err
    assert "Invalid YAML" in error
    assert str(workflow) in error
    assert "line" in error and "column" in error
    assert "Traceback" not in error


def test_debug_retains_yaml_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workflow = tmp_path / "invalid.yaml"
    workflow.write_text("workflow: [not closed\n", encoding="utf-8")
    assert main(["plan", str(workflow), "--color", "never", "--debug"]) == 2
    assert "Traceback" in capsys.readouterr().err


def test_expected_sqlite_failure_is_concise(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_open(_: str) -> None:
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr("simpleworkflow.cli.load_workflow", fail_open)
    assert main(["plan", "unused.yaml"]) == 2
    error = capsys.readouterr().err
    assert "unable to open database file" in error
    assert "Traceback" not in error


def test_unexpected_programming_error_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_bug(_: str) -> None:
        raise TypeError("unexpected programming error")

    monkeypatch.setattr("simpleworkflow.cli.load_workflow", fail_bug)
    with pytest.raises(TypeError, match="unexpected programming error"):
        main(["plan", "unused.yaml"])
