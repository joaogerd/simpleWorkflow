"""Runtime wrapper for the optional Textual monitor."""

from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from typing import Any

from .tui import WorkflowTui


def run_monitor(
    config: dict[str, Any],
    workflow_path: str | Path,
    workdir: str | Path,
    *,
    refresh_seconds: float = 1.0,
    color: bool = True,
    completion_future: Future[int] | None = None,
) -> None:
    """Run Textual and optionally close it when an attached execution finishes."""
    app = WorkflowTui(
        config=config,
        workflow_path=workflow_path,
        workdir=workdir,
        refresh_seconds=refresh_seconds,
        color=color,
    )

    if completion_future is not None:
        def execution_finished(_: Future[int]) -> None:
            try:
                app.call_from_thread(app.exit)
            except RuntimeError:
                # The UI may already have been closed with q. That is expected;
                # the workflow thread continues and the caller waits for it.
                pass

        completion_future.add_done_callback(execution_finished)

    app.run()
