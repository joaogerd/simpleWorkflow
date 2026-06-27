from __future__ import annotations

from io import StringIO

from simpleworkflow.console import TerminalReporter


class InteractiveBuffer(StringIO):
    """Text buffer that behaves like an interactive terminal for tests."""

    def isatty(self) -> bool:
        return True


def test_color_always_emits_ansi_escape_sequences() -> None:
    stream = StringIO()
    reporter = TerminalReporter(color="always", stream=stream)

    reporter.event("ok", "analysis", executor="pbs")

    output = stream.getvalue()
    assert "\033[" in output
    assert "analysis" in output
    assert "[pbs]" in output


def test_color_never_emits_plain_text() -> None:
    stream = InteractiveBuffer()
    reporter = TerminalReporter(color="never", stream=stream)

    reporter.event("fail", "analysis", "return code 7", executor="local")

    output = stream.getvalue()
    assert "\033[" not in output
    assert "✘ FAIL" in output
    assert "return code 7" in output


def test_auto_color_uses_interactive_stream() -> None:
    stream = InteractiveBuffer()
    reporter = TerminalReporter(color="auto", stream=stream)

    reporter.status_table([("prepare", "success"), ("analysis", "pending")])

    output = stream.getvalue()
    assert "\033[" in output
    assert "prepare" in output
    assert "analysis" in output


def test_status_table_renders_all_lifecycle_states_without_color() -> None:
    stream = StringIO()
    reporter = TerminalReporter(color="never", stream=stream)

    reporter.status_table(
        [
            ("prepare", "pending"),
            ("analysis", "running"),
            ("verify", "invalid-output"),
        ]
    )

    output = stream.getvalue()
    assert "PENDING" in output
    assert "RUNNING" in output
    assert "BAD OUTPUT" in output
