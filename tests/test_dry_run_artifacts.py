from __future__ import annotations

import sys
from pathlib import Path

from simpleworkflow.engine import WorkflowEngine


def test_dry_run_accepts_transitive_planned_dependency_outputs(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    rendered_yaml = tmp_path / "rendered" / "experiment.yaml"

    config = {
        "workflow": {"name": "dry-run-planned-outputs"},
        "context": {
            "python": sys.executable,
            "runtime_dir": str(runtime_dir),
            "rendered_yaml": str(rendered_yaml),
        },
        "tasks": [
            {
                "name": "prepare",
                "argv": ["{python}", "-c", "print('prepare')"],
                "outputs": {"required": ["{runtime_dir}"]},
            },
            {
                "name": "render",
                "argv": ["{python}", "-c", "print('render')"],
                "depends_on": ["prepare"],
                "inputs": {"required": ["{runtime_dir}"]},
                "outputs": {"required": ["{rendered_yaml}"]},
            },
            {
                "name": "execute",
                "argv": ["{python}", "-c", "print('execute')"],
                "depends_on": ["render"],
                "inputs": {
                    "required": ["{runtime_dir}", "{rendered_yaml}"],
                },
            },
        ],
        "__simpleworkflow__": {"source_dir": str(tmp_path)},
    }

    engine = WorkflowEngine(
        config=config,
        workdir=tmp_path / ".simpleworkflow",
        dry_run=True,
    )

    assert engine.run() == 0
    assert not runtime_dir.exists()
    assert not rendered_yaml.exists()
    assert not (tmp_path / ".simpleworkflow" / "runs").exists()


def test_dry_run_does_not_accept_output_from_unrelated_task(tmp_path: Path) -> None:
    shared_path = tmp_path / "shared.nc"

    config = {
        "workflow": {"name": "dry-run-unrelated-output"},
        "context": {
            "python": sys.executable,
            "shared_path": str(shared_path),
        },
        "tasks": [
            {
                "name": "unrelated_producer",
                "argv": ["{python}", "-c", "print('producer')"],
                "outputs": {"required": ["{shared_path}"]},
            },
            {
                "name": "consumer",
                "argv": ["{python}", "-c", "print('consumer')"],
                "inputs": {"required": ["{shared_path}"]},
            },
        ],
        "__simpleworkflow__": {"source_dir": str(tmp_path)},
    }

    engine = WorkflowEngine(
        config=config,
        workdir=tmp_path / ".simpleworkflow",
        dry_run=True,
    )

    assert engine.run() == 2
    assert not (tmp_path / ".simpleworkflow" / "runs").exists()
