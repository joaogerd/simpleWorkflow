from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

from simpleworkflow.engine import (
    BLOCKED_EXIT_CODE,
    INVALID_INPUT_EXIT_CODE,
    WorkflowEngine,
)
from simpleworkflow.state import WorkflowState


def test_mark_tasks_rolls_back_entire_batch_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = WorkflowState(
        tmp_path / "state.sqlite3",
        workflow_name="batch-state",
    )
    for name in ("a", "b", "c"):
        state.set_status(name, "success", 0, signature=f"sig-{name}")

    before_events = state.connection.execute("SELECT COUNT(*) FROM state_event").fetchone()[0]
    original = WorkflowState._write_task_state_event
    calls = 0

    def fail_on_second(
        self: WorkflowState,
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.OperationalError("injected batch failure")
        original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(WorkflowState, "_write_task_state_event", fail_on_second)

    with pytest.raises(sqlite3.OperationalError, match="injected batch failure"):
        state.mark_tasks(["a", "b", "c"], "stale", "upstream rerun")

    assert [state.get_status(name) for name in ("a", "b", "c")] == [
        "success",
        "success",
        "success",
    ]
    after_events = state.connection.execute("SELECT COUNT(*) FROM state_event").fetchone()[0]
    assert after_events == before_events
    state.close()


def test_invalid_input_blocks_all_descendants(tmp_path: Path) -> None:
    missing = tmp_path / "missing.dat"
    config = {
        "workflow": {"name": "invalid-input-cascade"},
        "tasks": [
            {
                "name": "prepare",
                "argv": [sys.executable, "-c", "print('prepare')"],
                "inputs": {"required": [str(missing)]},
            },
            {
                "name": "analysis",
                "depends_on": ["prepare"],
                "argv": [sys.executable, "-c", "print('analysis')"],
            },
            {
                "name": "forecast",
                "depends_on": ["analysis"],
                "argv": [sys.executable, "-c", "print('forecast')"],
            },
        ],
        "__simpleworkflow__": {"source_dir": str(tmp_path)},
    }
    engine = WorkflowEngine(config, workdir=tmp_path / ".simpleworkflow")

    assert engine.run() == INVALID_INPUT_EXIT_CODE
    assert engine.state.get_status("prepare") == "invalid-input"
    assert engine.state.get_status("analysis") == "blocked"
    assert engine.state.get_status("forecast") == "blocked"
    assert engine.state.get_task_state("analysis").return_code == BLOCKED_EXIT_CODE
    assert engine.state.get_task_state("forecast").return_code == BLOCKED_EXIT_CODE
    engine.state.close()


def test_disabled_upstream_blocks_descendants_immediately(tmp_path: Path) -> None:
    config = {
        "workflow": {"name": "disabled-cascade"},
        "tasks": [
            {
                "name": "prepare",
                "enabled": False,
                "argv": [sys.executable, "-c", "print('prepare')"],
            },
            {
                "name": "analysis",
                "depends_on": ["prepare"],
                "argv": [sys.executable, "-c", "print('analysis')"],
            },
            {
                "name": "forecast",
                "depends_on": ["analysis"],
                "argv": [sys.executable, "-c", "print('forecast')"],
            },
        ],
    }
    engine = WorkflowEngine(config, workdir=tmp_path / ".simpleworkflow")

    assert engine.run() == BLOCKED_EXIT_CODE
    assert engine.state.get_status("prepare") == "skipped"
    assert engine.state.get_status("analysis") == "blocked"
    assert engine.state.get_status("forecast") == "blocked"
    engine.state.close()


def test_process_failure_blocks_every_descendant(tmp_path: Path) -> None:
    config = {
        "workflow": {"name": "failure-cascade"},
        "tasks": [
            {
                "name": "analysis",
                "argv": [sys.executable, "-c", "import sys; sys.exit(7)"],
            },
            {
                "name": "post",
                "depends_on": ["analysis"],
                "argv": [sys.executable, "-c", "print('post')"],
            },
            {
                "name": "publish",
                "depends_on": ["post"],
                "argv": [sys.executable, "-c", "print('publish')"],
            },
        ],
    }
    engine = WorkflowEngine(config, workdir=tmp_path / ".simpleworkflow")

    assert engine.run() == 7
    assert engine.state.get_status("analysis") == "failed"
    assert engine.state.get_status("post") == "blocked"
    assert engine.state.get_status("publish") == "blocked"
    engine.state.close()
