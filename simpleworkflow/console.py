"""Small, dependency-free terminal rendering for simpleWorkflow."""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol, TextIO

ColorMode = Literal["auto", "always", "never"]

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_COLORS = {
    "blue": "\033[34m",
    "cyan": "\033[36m",
    "green": "\033[32m",
    "red": "\033[31m",
    "yellow": "\033[33m",
}


@dataclass(frozen=True)
class EventStyle:
    """Visual representation for one workflow lifecycle event."""

    symbol: str
    label: str
    color: str | None


_EVENT_STYLES = {
    "plan": EventStyle("•", "PLAN", "cyan"),
    "run": EventStyle("▶", "RUN", "blue"),
    "ok": EventStyle("✔", "OK", "green"),
    "fail": EventStyle("✘", "FAIL", "red"),
    "skip": EventStyle("↷", "SKIP", "yellow"),
    "retry": EventStyle("↻", "RETRY", "yellow"),
    "rerun": EventStyle("↻", "RERUN", "yellow"),
    "pending": EventStyle("○", "PENDING", None),
    "running": EventStyle("▶", "RUNNING", "blue"),
    "success": EventStyle("✔", "SUCCESS", "green"),
    "failed": EventStyle("✘", "FAILED", "red"),
    "invalid-input": EventStyle("!", "BAD INPUT", "red"),
    "invalid-output": EventStyle("!", "BAD OUTPUT", "red"),
    "skipped": EventStyle("↷", "SKIPPED", "yellow"),
}


class WorkflowReporter(Protocol):
    """Minimal presentation interface consumed by the workflow engine."""

    def event(
        self,
        kind: str,
        task_name: str,
        message: str | None = None,
        *,
        executor: str | None = None,
    ) -> None:
        """Render one task lifecycle event."""
        ...

    def status_table(self, entries: Iterable[tuple[str, str]]) -> None:
        """Render task states in a compact terminal table."""
        ...


class TerminalReporter:
    """Render friendly workflow progress without a third-party dependency.

    Color is enabled automatically only for interactive terminals. The ``always``
    and ``never`` modes support demonstrations, CI logs and machine-readable
    output without requiring environment-specific configuration.
    """

    def __init__(self, color: ColorMode = "auto", stream: TextIO | None = None) -> None:
        if color not in {"auto", "always", "never"}:
            raise ValueError(f"Unsupported color mode: {color!r}")
        self.stream = stream or sys.stdout
        self.color = color
        self._use_color = self._resolve_color()
        self._lock = threading.Lock()

    def _resolve_color(self) -> bool:
        if self.color == "always":
            return True
        if self.color == "never":
            return False
        return bool(self.stream.isatty()) and not bool(os.environ.get("NO_COLOR"))

    def _paint(self, text: str, color: str | None, *, bold: bool = False) -> str:
        if not self._use_color:
            return text
        codes = ""
        if bold:
            codes += _BOLD
        if color is not None:
            codes += _COLORS[color]
        return f"{codes}{text}{_RESET}"

    def _dim(self, text: str) -> str:
        if not self._use_color:
            return text
        return f"{_DIM}{text}{_RESET}"

    def _write(self, text: str = "") -> None:
        with self._lock:
            print(text, file=self.stream, flush=True)

    def heading(self, title: str) -> None:
        """Render a compact section heading."""
        self._write(self._paint(f"━━ {title} ━━", "cyan", bold=True))

    def event(
        self,
        kind: str,
        task_name: str,
        message: str | None = None,
        *,
        executor: str | None = None,
    ) -> None:
        """Render one task lifecycle event."""
        style = _EVENT_STYLES.get(kind, EventStyle("•", kind.upper(), None))
        prefix = self._paint(
            f"{style.symbol} {style.label:<9}", style.color, bold=True
        )
        line = f"{prefix} {task_name}"
        if executor:
            line += f" {self._dim(f'[{executor}]')}"
        if message:
            line += f" {self._dim('—')} {message}"
        self._write(line)

    def plan_item(self, index: int, task_name: str) -> None:
        """Render one dependency-resolved plan entry."""
        index_text = self._paint(f"{index:02d}", "cyan", bold=True)
        self._write(f"{index_text} {task_name}")

    def status_table(self, entries: Iterable[tuple[str, str]]) -> None:
        """Render task states in a compact, color-aware table."""
        rows = list(entries)
        if not rows:
            self._write(self._dim("No tasks declared."))
            return

        width = max(len(task_name) for task_name, _ in rows)
        self._write(self._dim(f"{'TASK'.ljust(width)}  STATE"))
        for task_name, status in rows:
            style = _EVENT_STYLES.get(status, EventStyle("•", status.upper(), None))
            state = self._paint(
                f"{style.symbol} {style.label}", style.color, bold=True
            )
            self._write(f"{task_name.ljust(width)}  {state}")

    def note(self, message: str) -> None:
        """Render a neutral informational message."""
        self._write(self._dim(message))
