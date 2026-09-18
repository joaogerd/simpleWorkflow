"""Terminal UI selection without importing optional presentation dependencies."""

from __future__ import annotations

import importlib.util
from typing import Literal, Protocol

UiRequest = Literal["auto", "tui", "plain"]
ResolvedUi = Literal["tui", "plain"]


class TtyStream(Protocol):
    def isatty(self) -> bool: ...


def tui_available() -> bool:
    """Return whether the optional interactive dependencies can be imported."""
    return (
        importlib.util.find_spec("textual") is not None
        and importlib.util.find_spec("rich") is not None
    )


def select_ui_mode(
    requested: UiRequest,
    *,
    stdin: TtyStream,
    stdout: TtyStream,
    term: str | None,
    tui_available: bool,
) -> ResolvedUi:
    """Resolve ``auto`` without changing workflow execution semantics."""
    if requested == "plain":
        return "plain"
    if requested == "tui":
        if not tui_available:
            raise RuntimeError(
                'interactive TUI is not installed; run pip install "simpleworkflow[tui]"'
            )
        return "tui"
    if requested != "auto":
        raise ValueError(f"Unsupported UI mode: {requested!r}")

    interactive = bool(stdin.isatty()) and bool(stdout.isatty())
    capable_term = (term or "").lower() != "dumb"
    return "tui" if interactive and capable_term and tui_available else "plain"
