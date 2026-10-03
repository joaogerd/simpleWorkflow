from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from simpleworkflow.engine import WorkflowEngine
from simpleworkflow.state import StateBindingError


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
    engine.state.close()


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
    assert engine.state.get_status("write-result") == "success"
    engine.state.close()


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
    assert engine.state.get_status("write-result") == "invalid-input"
    engine.state.close()


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
    engine.state.close()


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
    engine.state.set_status("task", "success", 0)

    assert engine.run() == 2
    assert engine.state.get_status("task") == "invalid-input"
    engine.state.close()


def test_local_timeout_terminates_process_group(tmp_path: Path) -> None:
    config = {
        "workflow": {"name": "timeout"},
        "tasks": [
            {
                "name": "slow",
                "argv": [sys.executable, "-c", "import time; time.sleep(30)"],
                "timeout": 0.05,
            }
        ],
    }
    engine = WorkflowEngine(config, workdir=tmp_path / ".simpleworkflow")
    assert engine.run() == 124
    state = engine.state.get_task_state("slow")
    assert state is not None and state.status == "failed"
    attempt = next((tmp_path / ".simpleworkflow" / "runs").glob("*/tasks/*/attempt-001"))
    assert (attempt / "process.json").is_file()
    engine.state.close()


def test_same_state_directory_rejects_a_different_workflow_file(tmp_path: Path) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    first.write_text("workflow: {name: repeated}\n", encoding="utf-8")
    second.write_text("workflow: {name: repeated}\n", encoding="utf-8")
    base = {"workflow": {"name": "repeated"}, "tasks": []}
    workdir = tmp_path / ".simpleworkflow"
    first_engine = WorkflowEngine(
        {**base, "__simpleworkflow__": {"source_path": str(first), "source_dir": str(tmp_path)}},
        workdir=workdir,
    )
    first_id = first_engine.state.instance_id
    first_engine.state.close()

    second_engine = WorkflowEngine(
        {
            **base,
            "__simpleworkflow__": {
                "source_path": str(second),
                "source_dir": str(tmp_path),
            },
        },
        workdir=workdir,
    )
    with pytest.raises(StateBindingError):
        _ = second_engine.state.instance_id
    second_engine.state.close()

    reopened = WorkflowEngine(
        {**base, "__simpleworkflow__": {"source_path": str(first), "source_dir": str(tmp_path)}},
        workdir=workdir,
    )
    assert reopened.state.instance_id == first_id
    reopened.state.close()


def test_omitted_cwd_tracks_effective_launch_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: cwd-portable}\n", encoding="utf-8")
    first_cwd = tmp_path / "first"
    second_cwd = tmp_path / "second"
    first_cwd.mkdir()
    second_cwd.mkdir()
    marker = tmp_path / "calls.txt"
    script = f"open({str(marker)!r}, 'a', encoding='utf-8').write('x')"
    config = {
        "workflow": {"name": "cwd-portable"},
        "tasks": [
            {"name": "task", "argv": [sys.executable, "-c", script]},
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(tmp_path),
        },
    }
    workdir = tmp_path / ".simpleworkflow"

    monkeypatch.chdir(first_cwd)
    first = WorkflowEngine(config=config, workdir=workdir)
    assert first.run() == 0
    first_state = first.state.get_task_state("task")
    assert first_state is not None
    assert first_state.signature_payload is not None
    assert first_state.signature_payload["task"]["cwd"] == "$WORKFLOW/first"
    first_signature = first_state.signature
    first.state.close()

    monkeypatch.chdir(second_cwd)
    second = WorkflowEngine(config=config, workdir=workdir)
    assert second.run() == 0
    second_state = second.state.get_task_state("task")
    assert second_state is not None
    assert second_state.signature != first_signature
    assert second_state.signature_payload is not None
    assert second_state.signature_payload["task"]["cwd"] == "$WORKFLOW/second"
    attempt_dir = second.state.resolve_path(second_state.attempt_path)
    assert attempt_dir is not None
    metadata = json.loads((attempt_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["command"]["cwd"] == str(second_cwd.resolve())
    assert marker.read_text(encoding="utf-8") == "xx"
    second.state.close()


def test_validate_reports_invalid_explicit_cwd(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: cwd-validation}\n", encoding="utf-8")
    not_directory = tmp_path / "not-directory"
    not_directory.write_text("file", encoding="utf-8")
    config = {
        "workflow": {"name": "cwd-validation"},
        "tasks": [
            {"name": "missing", "argv": ["true"], "cwd": "missing-dir"},
            {"name": "file", "argv": ["true"], "cwd": "not-directory"},
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(tmp_path),
        },
    }
    engine = WorkflowEngine(config=config, workdir=tmp_path / ".simpleworkflow")

    problems = engine.validate()

    assert any("missing: diretório de trabalho ausente" in problem for problem in problems)
    assert any("file: cwd não é um diretório" in problem for problem in problems)
    engine.state.close()
