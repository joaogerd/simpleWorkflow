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
    assert "Analysis" in output
    assert "pbs" in output


def test_color_never_emits_plain_text() -> None:
    stream = InteractiveBuffer()
    reporter = TerminalReporter(color="never", stream=stream)

    reporter.event("fail", "analysis", "return code 7", executor="local")

    output = stream.getvalue()
    assert "\033[" not in output
    assert "✘ FAILED" in output
    assert "return code 7" in output


def test_auto_color_uses_interactive_stream() -> None:
    stream = InteractiveBuffer()
    reporter = TerminalReporter(color="auto", stream=stream)

    reporter.workflow_header(
        command="status",
        workflow_name="test",
        workdir=".simpleworkflow",
        task_names=["prepare", "analysis"],
    )
    reporter.status_table([("prepare", "success"), ("analysis", "pending")])

    output = stream.getvalue()
    assert "\033[" in output
    assert "Execution hierarchy" in output
    assert "Cycle status" in output
    assert "Prepare" in output
    assert "Analysis" in output


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
    assert "WAITING" in output
    assert "RUNNING" in output
    assert "BAD OUTPUT" in output


def test_scientific_task_names_are_grouped_by_stage_and_cycle() -> None:
    stream = StringIO()
    reporter = TerminalReporter(color="never", stream=stream)
    reporter.workflow_header(
        command="run",
        workflow_name="corrected-replay",
        workdir=".simpleworkflow",
        task_names=["jedi06_prepare", "jedi06_submit", "mpas06_prepare"],
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
    assert "jedi06_prepare" in output
    assert "local" in output
    assert "monan-jedi-workflow jedi-prepare" in output


def test_run_summary_is_concise_and_actionable() -> None:
    stream = StringIO()
    reporter = TerminalReporter(color="never", stream=stream)
    reporter.workflow_header(
        command="run",
        workflow_name="test",
        workdir=".simpleworkflow",
        task_names=["prepare", "validate"],
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
    assert "Workflow complete" in output


def test_interactive_dashboard_contains_tree_and_cycle_matrix() -> None:
    stream = InteractiveBuffer()
    reporter = TerminalReporter(color="never", stream=stream)
    reporter.workflow_header(
        command="status",
        workflow_name="monan-jedi",
        workdir=".simpleworkflow",
        task_names=[
            "jedi00_prepare",
            "jedi00_validate",
            "mpas00_prepare",
            "obs06_run",
            "jedi06_prepare",
        ],
    )

    reporter.status_table(
        [
            ("jedi00_prepare", "success"),
            ("jedi00_validate", "success"),
            ("mpas00_prepare", "success"),
            ("obs06_run", "success"),
            ("jedi06_prepare", "running"),
        ]
    )

    output = stream.getvalue()
    assert "Execution hierarchy" in output
    assert "Cycle status" in output
    assert "JEDI 00Z" in output
    assert "JEDI 06Z" in output
    assert "MPAS" in output
    assert "OBS" in output
    assert "RUNNING" in output


def test_plain_mode_disables_live_dashboard() -> None:
    stream = InteractiveBuffer()
    reporter = TerminalReporter(color="never", stream=stream, plain=True)
    reporter.workflow_header(
        command="run",
        workflow_name="plain-test",
        workdir=".simpleworkflow",
        task_names=["jedi00_prepare"],
    )
    reporter.event("run", "jedi00_prepare", "command --flag", executor="local")

    output = stream.getvalue()
    assert "Run · plain-test" in output
    assert "RUNNING" in output
    assert "Execution hierarchy" not in output
