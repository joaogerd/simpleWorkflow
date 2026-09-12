from __future__ import annotations

from io import StringIO

from simpleworkflow.console import TerminalReporter


class InteractiveBuffer(StringIO):
    """Text buffer that behaves like an interactive terminal for tests."""

    def isatty(self) -> bool:
        return True


def test_color_always_emits_ansi_escape_sequences() -> None:
    stream = StringIO()
    reporter = TerminalReporter(color="always", stream=stream, verbose=True)

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


def test_scientific_task_names_are_grouped_by_stage_and_cycle() -> None:
    stream = StringIO()
    reporter = TerminalReporter(color="never", stream=stream)
    reporter.workflow_header(
        command="run",
        workflow_name="corrected-replay",
        workdir=".simpleworkflow",
        task_count=3,
    )

    reporter.event("skip", "jedi06_prepare", "already successful", executor="local")
    reporter.event("run", "jedi06_submit", "monan-jedi-workflow jedi-submit ...")
    reporter.event("ok", "jedi06_submit")
    reporter.event("run", "mpas06_prepare", "monan-jedi-workflow mpas-prepare ...")

    output = stream.getvalue()
    assert "JEDI 06Z" in output
    assert "MPAS 06Z" in output
    assert "REUSED" in output
    assert "Prepare" in output
    assert "Submit" in output
    assert "monan-jedi-workflow" not in output


def test_verbose_mode_keeps_internal_details_available() -> None:
    stream = StringIO()
    reporter = TerminalReporter(color="never", stream=stream, verbose=True)

    reporter.event(
        "run",
        "jedi06_prepare",
        "monan-jedi-workflow jedi-prepare case --cycle 2018-04-15T06:00:00Z",
        executor="local",
    )

    output = stream.getvalue()
    assert "[jedi06_prepare]" in output
    assert "[local]" in output
    assert "monan-jedi-workflow jedi-prepare" in output


def test_run_summary_is_concise_and_actionable() -> None:
    stream = StringIO()
    reporter = TerminalReporter(color="never", stream=stream)
    reporter.workflow_header(
        command="run",
        workflow_name="test",
        workdir=".simpleworkflow",
        task_count=2,
    )
    reporter.event("ok", "prepare")
    reporter.event("skip", "validate", "already successful")

    reporter.run_summary(
        [("prepare", "success"), ("validate", "success")],
        elapsed_seconds=4.2,
        exit_code=0,
    )

    output = stream.getvalue()
    assert "Result · SUCCESS" in output
    assert "1 executed" in output
    assert "1 reused/skipped" in output
    assert "workflow complete" in output
