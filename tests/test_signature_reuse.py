from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from simpleworkflow.engine import WorkflowEngine
from simpleworkflow.state import WorkflowState


class WritingExecutor:
    """Test executor that records invocations and materializes one output."""

    def __init__(self, source: Path, destination: Path):
        self.source = source
        self.destination = destination
        self.calls = 0

    def run(
        self,
        task_name: str,
        argv: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        stdout_path: Path | None = None,
        stderr_path: Path | None = None,
    ) -> int:
        del task_name, argv, cwd, env, stdout_path, stderr_path
        self.calls += 1
        self.destination.write_text(self.source.read_text(encoding="utf-8"), encoding="utf-8")
        return 0


def test_successful_task_is_reused_only_when_signature_matches(tmp_path: Path) -> None:
    workflow_path = tmp_path / "workflow.yaml"
    workflow_path.write_text("workflow: {name: signature-reuse}\n", encoding="utf-8")
    source = tmp_path / "background.nc"
    source.write_text("first", encoding="utf-8")
    output = tmp_path / "analysis.nc"

    config = {
        "workflow": {"name": "signature-reuse"},
        "context": {"python": sys.executable, "source": str(source), "output": str(output)},
        "tasks": [
            {
                "name": "analysis",
                "argv": ["{python}", "-c", "print('analysis')"],
                "inputs": {"required": ["{source}"]},
                "outputs": {"required": ["{output}"]},
                "input_fingerprint": "metadata",
            }
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow_path),
            "source_dir": str(tmp_path),
        },
    }
    engine = WorkflowEngine(config, workdir=tmp_path / ".simpleworkflow")
    executor = WritingExecutor(source, output)
    engine.executor = executor

    assert engine.run() == 0
    assert executor.calls == 1
    assert output.read_text(encoding="utf-8") == "first"
    first_state = engine.state.get_task_state("signature-reuse", "analysis")
    assert first_state is not None
    assert first_state.signature

    assert engine.run() == 0
    assert executor.calls == 1

    source.write_text("second-value", encoding="utf-8")
    assert engine.run() == 0
    assert executor.calls == 2
    assert output.read_text(encoding="utf-8") == "second-value"


def test_state_migrates_legacy_database_and_preserves_signatures(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TABLE task_state (
            workflow TEXT NOT NULL,
            task TEXT NOT NULL,
            status TEXT NOT NULL,
            return_code INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (workflow, task)
        )
        """
    )
    connection.execute(
        "INSERT INTO task_state (workflow, task, status, return_code) VALUES (?, ?, ?, ?)",
        ("legacy", "task", "success", 0),
    )
    connection.commit()
    connection.close()

    state = WorkflowState(database)
    legacy = state.get_task_state("legacy", "task")
    assert legacy is not None
    assert legacy.status == "success"
    assert legacy.signature is None

    state.set_status("legacy", "task", "success", 0, "signature-value")
    updated = state.get_task_state("legacy", "task")
    assert updated is not None
    assert updated.signature == "signature-value"
