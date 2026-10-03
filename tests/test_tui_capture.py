from __future__ import annotations

from pathlib import Path

from simpleworkflow.cli import main


def _workflow(path: Path) -> None:
    path.write_text(
        """
format_version: 1
workflow:
  name: capture_demo
tasks:
  - name: hello
    argv: [python, -c, "print('hello')"]
""".lstrip(),
        encoding="utf-8",
    )


def test_capture_tui_writes_svg_with_virtual_size(
    tmp_path: Path,
    capsys,
) -> None:
    workflow = tmp_path / "workflow.yaml"
    _workflow(workflow)

    assert main(["run", str(workflow), "--ui", "plain", "--color", "never"]) == 0
    output = tmp_path / "capture.svg"
    assert (
        main(
            [
                "capture-tui",
                str(workflow),
                "--view",
                "monitor",
                "--size",
                "100x28",
                "--output",
                str(output),
                "--color",
                "never",
            ]
        )
        == 0
    )
    assert output.is_file()
    assert "<svg" in output.read_text(encoding="utf-8")
    assert str(output.resolve()) in capsys.readouterr().out


def test_capture_rejects_cycle_view_for_noncyclic_workflow(
    tmp_path: Path,
    capsys,
) -> None:
    workflow = tmp_path / "workflow.yaml"
    _workflow(workflow)

    output = tmp_path / "cycles.svg"
    assert (
        main(
            [
                "capture-tui",
                str(workflow),
                "--view",
                "cycles",
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert not output.exists()
    assert "not available" in capsys.readouterr().err


def test_capture_rejects_invalid_virtual_size(tmp_path: Path, capsys) -> None:
    workflow = tmp_path / "workflow.yaml"
    _workflow(workflow)

    assert (
        main(
            [
                "capture-tui",
                str(workflow),
                "--size",
                "tiny",
                "--output",
                str(tmp_path / "bad.svg"),
            ]
        )
        == 2
    )
    assert "--size" in capsys.readouterr().err
