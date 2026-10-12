from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from .tui import WorkflowTui


def _parse_size(value: str) -> tuple[int, int]:
    normalized = value.lower().replace(" ", "")
    if "x" not in normalized:
        raise ValueError("--size must use COLSxROWS, for example 120x35")
    cols_text, rows_text = normalized.split("x", 1)
    try:
        cols = int(cols_text)
        rows = int(rows_text)
    except ValueError as error:
        raise ValueError("--size must use integer COLSxROWS values") from error
    if cols < 40 or rows < 12:
        raise ValueError("--size is too small; use at least 40x12")
    return cols, rows


async def _capture(
    *,
    config: dict[str, Any],
    workflow_path: Path,
    workdir: Path,
    view: str,
    size: tuple[int, int],
    output: Path,
    color: bool,
) -> Path:
    app = WorkflowTui(
        config=config,
        workflow_path=workflow_path,
        workdir=workdir,
        refresh_seconds=60.0,
        color=color,
    )
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        available = app._available_view_ids()
        if view not in available:
            choices = ", ".join(available)
            raise ValueError(
                f"view '{view}' is not available for this workflow; choose one of: {choices}"
            )
        app.action_select_view(view)
        await pilot.pause()
        svg = app.export_screenshot()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg, encoding="utf-8")
    return output.resolve(strict=False)


def capture_tui(
    *,
    config: dict[str, Any],
    workflow_path: str | Path,
    workdir: str | Path,
    view: str = "monitor",
    size: str = "120x35",
    output: str | Path,
    color: bool = True,
) -> Path:
    return asyncio.run(
        _capture(
            config=config,
            workflow_path=Path(workflow_path).resolve(strict=False),
            workdir=Path(workdir).resolve(strict=False),
            view=view,
            size=_parse_size(size),
            output=Path(output).expanduser(),
            color=color,
        )
    )
