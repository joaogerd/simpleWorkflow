"""Small, dependency-free terminal rendering for simpleWorkflow."""

from __future__ import annotations

import os
import re
import shutil
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol, TextIO

from . import __version__

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

_TASK_PATTERN = re.compile(
    r"^(?P<component>[A-Za-z][A-Za-z0-9]*?)(?P<hour>\d{2})_(?P<action>.+)$"
)


@dataclass(frozen=True)
class EventStyle:
    """Visual representation for one workflow lifecycle event."""

    symbol: str
    label: str
    color: str | None


@dataclass(frozen=True)
class TaskDisplay:
    """Human-facing grouping derived from a stable internal task name."""

    raw_name: str
    stage: str | None
    label: str


_EVENT_STYLES = {
    "plan": EventStyle("•", "PLAN", "cyan"),
    "run": EventStyle("▶", "RUN", "blue"),
    "ok": EventStyle("✔", "OK", "green"),
    "fail": EventStyle("✘", "FAIL", "red"),
    "skip": EventStyle("↷", "SKIPPED", "yellow"),
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
    """Render concise workflow progress for scientific and operational users.

    The default view emphasizes workflow stages, progress and actionable failures.
    ``verbose=True`` adds internal task names, executor names and rendered commands
    for debugging. Color is enabled automatically only for interactive terminals.
    """

    def __init__(
        self,
        color: ColorMode = "auto",
        stream: TextIO | None = None,
        *,
        verbose: bool = False,
    ) -> None:
        if color not in {"auto", "always", "never"}:
            raise ValueError(f"Unsupported color mode: {color!r}")
        self.stream = stream or sys.stdout
        self.color = color
        self.verbose = verbose
        self._use_color = self._resolve_color()
        self._current_stage: str | None = None
        self._task_total: int | None = None
        self._completed = 0
        self._event_counts: Counter[str] = Counter()
        self._commands: dict[str, str] = {}

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
        print(text, file=self.stream, flush=True)

    def _terminal_width(self) -> int:
        return max(60, min(shutil.get_terminal_size((100, 24)).columns, 140))

    def _fit(self, text: str, *, indent: int = 0) -> str:
        available = max(20, self._terminal_width() - indent)
        if len(text) <= available:
            return text
        return text[: max(1, available - 1)] + "…"

    @staticmethod
    def _humanize_task(task_name: str) -> TaskDisplay:
        match = _TASK_PATTERN.fullmatch(task_name)
        if match is None:
            return TaskDisplay(task_name, None, task_name.replace("_", " "))

        component = match.group("component").upper()
        hour = match.group("hour")
        action = match.group("action").replace("_", " ").replace("-", " ").title()
        return TaskDisplay(task_name, f"{component} {hour}Z", action)

    def _reset_view(self, *, task_count: int | None = None) -> None:
        self._current_stage = None
        self._task_total = task_count
        self._completed = 0
        self._event_counts.clear()
        self._commands.clear()

    def heading(self, title: str) -> None:
        """Render a compact section heading."""
        self._write(self._paint(f"━━ {title} ━━", "cyan", bold=True))

    def workflow_header(
        self,
        *,
        command: str,
        workflow_name: str,
        workdir: str,
        cycle_time: str | None = None,
        mode: str = "normal",
        task_count: int | None = None,
    ) -> None:
        """Render a stable high-level header before plan/run/status output."""
        self._reset_view(task_count=task_count)
        self.heading(f"{command.title()} · {workflow_name}")
        self._write(self._dim(f"simpleWorkflow {__version__}"))
        details = [
            ("Workflow", workflow_name),
            ("Action", command.upper()),
            ("Workdir", workdir),
            ("Mode", mode),
        ]
        if cycle_time is not None:
            details.insert(2, ("Cycle", cycle_time))
        if task_count is not None:
            details.append(("Tasks", str(task_count)))
        label_width = max(len(label) for label, _ in details)
        for label, value in details:
            self._write(self._fit(f"{label.ljust(label_width)} : {value}"))

    def _stage_heading(self, stage: str | None) -> None:
        if stage is None or stage == self._current_stage:
            return
        if self._current_stage is not None:
            self._write()
        self._write(self._paint(stage, "cyan", bold=True))
        self._current_stage = stage

    def _progress_prefix(self, kind: str) -> str:
        if kind in {"ok", "skip"}:
            self._completed += 1
        if self._task_total is None or kind not in {"ok", "skip"}:
            return ""
        return self._dim(f"[{self._completed:02d}/{self._task_total:02d}] ")

    @staticmethod
    def _event_style(kind: str, message: str | None) -> EventStyle:
        if kind == "skip" and message == "already successful":
            return EventStyle("↷", "REUSED", "green")
        return _EVENT_STYLES.get(kind, EventStyle("•", kind.upper(), None))

    @staticmethod
    def _friendly_message(kind: str, message: str | None) -> str | None:
        if message is None:
            return None
        if kind == "skip" and message == "already successful":
            return None
        if kind == "rerun" and message == "dependency executed again":
            return "upstream step ran again"
        if kind == "rerun" and message == "task signature changed":
            return "inputs or configuration changed"
        return message

    def event(
        self,
        kind: str,
        task_name: str,
        message: str | None = None,
        *,
        executor: str | None = None,
    ) -> None:
        """Render one task lifecycle event with scientific-stage grouping."""
        self._event_counts[kind] += 1
        display = self._humanize_task(task_name)
        self._stage_heading(display.stage)

        if kind == "run" and message:
            self._commands[task_name] = message

        style = self._event_style(kind, message)
        prefix = self._paint(f"{style.symbol} {style.label:<8}", style.color, bold=True)
        progress = self._progress_prefix(kind)
        indent = "  " if display.stage is not None else ""
        line = f"{indent}{progress}{prefix} {display.label}"

        if self.verbose:
            if display.label != task_name:
                line += f" {self._dim(f'[{task_name}]')}"
            if executor:
                line += f" {self._dim(f'[{executor}]')}"

        friendly_message = self._friendly_message(kind, message)
        if kind in {"run", "plan"} and not self.verbose:
            friendly_message = None
        if friendly_message:
            line += f" {self._dim('—')} {friendly_message}"
        self._write(self._fit(line))

        if kind == "fail" and not self.verbose:
            command = self._commands.get(task_name)
            if command:
                self._write(self._dim(self._fit(f"{indent}  command: {command}", indent=4)))

    def plan_item(self, index: int, task_name: str) -> None:
        """Render one dependency-resolved plan entry grouped by scientific stage."""
        display = self._humanize_task(task_name)
        self._stage_heading(display.stage)
        index_text = self._paint(f"{index:02d}", "cyan", bold=True)
        indent = "  " if display.stage is not None else ""
        line = f"{indent}{index_text} {display.label}"
        if self.verbose and display.label != task_name:
            line += f" {self._dim(f'[{task_name}]')}"
        self._write(line)

    def status_table(self, entries: Iterable[tuple[str, str]]) -> None:
        """Render grouped task states plus an aggregate progress summary."""
        rows = list(entries)
        if not rows:
            self._write(self._dim("No tasks declared."))
            return

        self._current_stage = None
        counts: Counter[str] = Counter(status for _, status in rows)
        completed = counts["success"] + counts["skipped"]
        self._write()
        self._write(
            self._paint(
                f"Progress {completed}/{len(rows)} completed",
                "green" if completed == len(rows) else "cyan",
                bold=True,
            )
        )

        display_rows = [(self._humanize_task(name), status) for name, status in rows]
        label_width = max(len(display.label) for display, _ in display_rows)
        for display, status in display_rows:
            self._stage_heading(display.stage)
            style = _EVENT_STYLES.get(status, EventStyle("•", status.upper(), None))
            state = self._paint(f"{style.symbol} {style.label}", style.color, bold=True)
            indent = "  " if display.stage is not None else ""
            label = display.label.ljust(label_width)
            line = f"{indent}{label}  {state}"
            if self.verbose and display.label != display.raw_name:
                line += f" {self._dim(f'[{display.raw_name}]')}"
            self._write(line)

        self._write()
        summary = (
            f"success={counts['success']}  failed={counts['failed'] + counts['invalid-input'] + counts['invalid-output']}  "
            f"running={counts['running']}  pending={counts['pending']}  skipped={counts['skipped']}"
        )
        self._write(self._dim(summary))

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        total = max(0, int(round(seconds)))
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def run_summary(
        self,
        entries: Iterable[tuple[str, str]],
        *,
        elapsed_seconds: float,
        exit_code: int,
    ) -> None:
        """Render a concise end-of-run result and the next useful action."""
        rows = list(entries)
        counts: Counter[str] = Counter(status for _, status in rows)
        failed = counts["failed"] + counts["invalid-input"] + counts["invalid-output"]
        result = "SUCCESS" if exit_code == 0 and failed == 0 else "FAILED"
        color = "green" if result == "SUCCESS" else "red"

        self._write()
        self._write(self._paint(f"━━ Result · {result} ━━", color, bold=True))
        self._write(
            f"Tasks   : {counts['success']} success · {failed} failed · "
            f"{counts['pending']} pending · {counts['skipped']} skipped"
        )
        self._write(
            f"Run     : {self._event_counts['ok']} executed · "
            f"{self._event_counts['skip']} reused/skipped · "
            f"{self._event_counts['rerun']} rerun"
        )
        self._write(f"Elapsed : {self._format_elapsed(elapsed_seconds)}")
        if result == "SUCCESS":
            self._write(self._paint("Next    : workflow complete.", "green"))
        else:
            self._write(
                self._paint(
                    "Next    : fix the failing step and rerun the same workflow; "
                    "validated steps will be reused.",
                    "yellow",
                )
            )

    def note(self, message: str) -> None:
        """Render a neutral informational message."""
        self._write(self._dim(message))
