from __future__ import annotations

from pathlib import Path

from simpleworkflow.cli import main


def _workflow(path: Path) -> Path:
    path.write_text(
        """workflow:
  name: display_test
tasks:
  - name: prepare
    argv: [python, -c, "print('prepare')"]
""",
        encoding="utf-8",
    )
    return path


def test_plan_supports_plain_terminal_output(tmp_path: Path, capsys: object) -> None:
    workflow = _workflow(tmp_path / "workflow.yaml")

    assert main(["plan", str(workflow), "--color", "never", "--plain"]) == 0

    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "\033[" not in output
    assert "Plan · display_test" in output
    assert "Execution plan" in output
    assert "Prepare" in output


def test_status_supports_forced_color(tmp_path: Path, capsys: object) -> None:
    workflow = _workflow(tmp_path / "workflow.yaml")

    assert main(["status", str(workflow), "--color", "always"]) == 0

    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "\033[" in output
    assert "WAITING" in output
    assert "Execution hierarchy" in output
    assert "Cycle status" in output
