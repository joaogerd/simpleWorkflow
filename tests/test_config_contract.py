from __future__ import annotations

from pathlib import Path

import pytest

from simpleworkflow.config import load_workflow
from simpleworkflow.engine import render_template


def test_workflow_rejects_unknown_top_level_field(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("tasks: []\nworklfow: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported field"):
        load_workflow(workflow)


def test_task_rejects_unknown_field(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        "tasks:\n  - name: run\n    argv: [echo, ok]\n    depend_on: setup\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported field"):
        load_workflow(workflow)


def test_pbs_requires_blocking_submission(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        """tasks:
  - name: run
    executor: pbs
    argv: [echo, ok]
    pbs:
      block: false
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be true"):
        load_workflow(workflow)


def test_pbs_accepts_context_rendered_resources(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        """context:
  ncpus: "128"
  walltime: "00:30:00"
tasks:
  - name: run
    executor: pbs
    argv: [echo, ok]
    pbs:
      ncpus: "{ncpus}"
      walltime: "{walltime}"
""",
        encoding="utf-8",
    )

    config = load_workflow(workflow)
    assert config["tasks"][0]["pbs"]["ncpus"] == "{ncpus}"


def test_rejects_invalid_environment_variable_name(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        """tasks:
  - name: run
    argv: [echo, ok]
    env:
      BAD-NAME: value
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid environment variable"):
        load_workflow(workflow)


def test_template_error_names_the_missing_placeholder() -> None:
    with pytest.raises(ValueError, match=r"\{missing_value\}"):
        render_template("{missing_value}", {})
