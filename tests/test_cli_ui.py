from __future__ import annotations

import os
from pathlib import Path

import pytest

import simpleworkflow.cli as cli
from simpleworkflow.ui import select_ui_mode


class _Stream:
    def __init__(self, tty: bool) -> None:
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


def test_auto_selects_tui_only_for_real_interactive_terminal() -> None:
    assert (
        select_ui_mode(
            "auto",
            stdin=_Stream(True),
            stdout=_Stream(True),
            term="xterm-256color",
            tui_available=True,
        )
        == "tui"
    )
    assert (
        select_ui_mode(
            "auto",
            stdin=_Stream(True),
            stdout=_Stream(False),
            term="xterm-256color",
            tui_available=True,
        )
        == "plain"
    )
    assert (
        select_ui_mode(
            "auto",
            stdin=_Stream(False),
            stdout=_Stream(True),
            term="xterm-256color",
            tui_available=True,
        )
        == "plain"
    )
    assert (
        select_ui_mode(
            "auto",
            stdin=_Stream(True),
            stdout=_Stream(True),
            term="dumb",
            tui_available=True,
        )
        == "plain"
    )
    assert (
        select_ui_mode(
            "auto",
            stdin=_Stream(True),
            stdout=_Stream(True),
            term="xterm",
            tui_available=False,
        )
        == "plain"
    )


def test_auto_in_ci_non_tty_uses_plain_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    assert (
        select_ui_mode(
            "auto",
            stdin=_Stream(False),
            stdout=_Stream(False),
            term="xterm",
            tui_available=True,
        )
        == "plain"
    )


def test_explicit_ui_modes_are_predictable() -> None:
    assert (
        select_ui_mode(
            "plain",
            stdin=_Stream(True),
            stdout=_Stream(True),
            term="xterm",
            tui_available=True,
        )
        == "plain"
    )
    assert (
        select_ui_mode(
            "tui",
            stdin=_Stream(False),
            stdout=_Stream(False),
            term="dumb",
            tui_available=True,
        )
        == "tui"
    )
    with pytest.raises(RuntimeError, match=r"simpleworkflow\[tui\]"):
        select_ui_mode(
            "tui",
            stdin=_Stream(True),
            stdout=_Stream(True),
            term="xterm",
            tui_available=False,
        )


def test_monitor_command_is_read_only_and_uses_default_state_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: monitor_cli}\ntasks: []\n", encoding="utf-8")
    launched: dict[str, object] = {}

    def fake_launch(
        config: dict[str, object], workflow_path: Path, workdir: Path, **kwargs: object
    ) -> None:
        launched["workflow"] = workflow_path
        launched["workdir"] = workdir
        launched["refresh_seconds"] = kwargs["refresh_seconds"]

    monkeypatch.setattr(cli, "_launch_monitor", fake_launch)

    assert cli.main(["monitor", str(workflow), "--refresh-seconds", "2"]) == 0
    assert launched["workflow"] == workflow.resolve()
    assert launched["workdir"] == (tmp_path / ".simpleworkflow").resolve()
    assert launched["refresh_seconds"] == 2.0
    assert not (tmp_path / ".simpleworkflow").exists()


def test_monitor_reports_optional_dependency_requirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: monitor_cli}\ntasks: []\n", encoding="utf-8")

    def unavailable(*args: object, **kwargs: object) -> None:
        raise RuntimeError('interactive monitor requires pip install "simpleworkflow[tui]"')

    monkeypatch.setattr(cli, "_launch_monitor", unavailable)
    assert cli.main(["monitor", str(workflow)]) == 2
    error = capsys.readouterr().err
    assert "simpleworkflow[tui]" in error
    assert "Traceback" not in error


def test_explicit_tui_without_extra_reports_short_install_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: missing_tui}\ntasks: []\n", encoding="utf-8")
    monkeypatch.setattr(cli, "tui_available", lambda: False)

    assert cli.main(["run", str(workflow), "--ui", "tui"]) == 2
    error = capsys.readouterr().err
    assert 'pip install "simpleworkflow[tui]"' in error
    assert "Traceback" not in error


def test_auto_without_tui_extra_falls_back_to_terminal_reporter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        "workflow: {name: auto_plain}\n"
        "tasks:\n"
        "  - name: hello\n"
        "    argv: ['python', '-c', 'print(123)']\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "tui_available", lambda: False)

    assert cli.main(["run", str(workflow), "--ui", "auto", "--color", "never"]) == 0
    output = capsys.readouterr().out
    assert "▶ RUN" in output
    assert "✔ OK" in output


def test_run_plain_preserves_terminal_reporter_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        "workflow: {name: plain_ui}\n"
        "tasks:\n"
        "  - name: hello\n"
        "    argv: ['python', '-c', 'print(123)']\n",
        encoding="utf-8",
    )

    assert cli.main(["run", str(workflow), "--ui", "plain", "--color", "never"]) == 0
    output = capsys.readouterr().out
    assert "▶ RUN" in output
    assert "✔ OK" in output


def test_no_color_does_not_change_ui_mode_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    assert os.environ["NO_COLOR"] == "1"
    assert (
        select_ui_mode(
            "auto",
            stdin=_Stream(True),
            stdout=_Stream(True),
            term="xterm",
            tui_available=True,
        )
        == "tui"
    )
