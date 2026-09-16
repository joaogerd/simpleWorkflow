from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import Future
from pathlib import Path

import pytest

import simpleworkflow.cli as cli
from simpleworkflow.state import WorkflowState
from simpleworkflow.tui import WorkflowTui


def test_explicit_tui_run_keeps_workflow_alive_when_monitor_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow = tmp_path / "workflow.yaml"
    marker = tmp_path / "finished.txt"
    workflow.write_text(
        "workflow: {name: interactive_run}\n"
        "tasks:\n"
        "  - name: slow\n"
        "    argv:\n"
        "      - python\n"
        "      - -c\n"
        f"      - \"import time; from pathlib import Path; time.sleep(0.15); Path({str(marker)!r}).write_text('done')\"\n",
        encoding="utf-8",
    )
    launch_calls: list[dict[str, object]] = []

    def close_immediately(*args: object, **kwargs: object) -> None:
        # This simulates the user pressing q immediately. The monitor closes, but
        # it must never be interpreted as a request to cancel the workflow.
        launch_calls.append(kwargs)

    monkeypatch.setattr(cli, "tui_available", lambda: True)
    monkeypatch.setattr(cli, "_launch_monitor", close_immediately)

    started = time.monotonic()
    assert cli.main(["run", str(workflow), "--ui", "tui", "--color", "never"]) == 0
    elapsed = time.monotonic() - started

    assert launch_calls
    assert marker.read_text(encoding="utf-8") == "done"
    assert elapsed >= 0.10

    state = WorkflowState(
        tmp_path / ".simpleworkflow" / "state.sqlite3",
        workflow_name="interactive_run",
        source_path=workflow,
        read_only=True,
    )
    assert state.get_status("slow") == "success"
    state.close()

    assert not any(
        thread.name.startswith("simpleworkflow-engine")
        for thread in threading.enumerate()
    )

    # A second state-changing command must acquire the workflow lock normally.
    assert (
        cli.main(
            [
                "run",
                str(workflow),
                "--ui",
                "plain",
                "--force",
                "--color",
                "never",
            ]
        )
        == 0
    )


def test_tui_run_passes_completion_future_to_monitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        "workflow: {name: interactive_run}\n"
        "tasks:\n"
        "  - name: quick\n"
        "    argv: ['python', '-c', 'print(123)']\n",
        encoding="utf-8",
    )
    seen_future = None

    def inspect_launch(*args: object, **kwargs: object) -> None:
        nonlocal seen_future
        seen_future = kwargs.get("completion_future")

    monkeypatch.setattr(cli, "tui_available", lambda: True)
    monkeypatch.setattr(cli, "_launch_monitor", inspect_launch)

    assert cli.main(["run", str(workflow), "--ui", "tui", "--color", "never"]) == 0
    assert seen_future is not None
    assert seen_future.done()
    assert seen_future.result() == 0


def test_monitor_q_does_not_cancel_attached_completion_future(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: q_semantics}\ntasks: []\n", encoding="utf-8")
    completion: Future[int] = Future()
    app = WorkflowTui(
        config={
            "workflow": {"name": "q_semantics"},
            "tasks": [],
            "__simpleworkflow__": {
                "source_path": str(workflow),
                "source_dir": str(workflow.parent),
            },
        },
        workflow_path=workflow,
        workdir=tmp_path / ".simpleworkflow",
        refresh_seconds=60,
        completion_future=completion,
    )

    async def scenario() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()

    asyncio.run(scenario())
    assert not completion.cancelled()
    assert not completion.done()
    completion.set_result(0)


def test_tui_dry_run_is_rejected_without_creating_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: dry}\ntasks: []\n", encoding="utf-8")
    monkeypatch.setattr(cli, "tui_available", lambda: True)

    assert cli.main(["run", str(workflow), "--ui", "tui", "--dry-run"]) == 2
    assert "--ui tui" in capsys.readouterr().err
    assert not (tmp_path / ".simpleworkflow").exists()
