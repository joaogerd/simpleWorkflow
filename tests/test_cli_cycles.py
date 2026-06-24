from __future__ import annotations

from pathlib import Path

from simpleworkflow.cli import main


def test_plan_expands_yaml_cycle_and_cli_range(tmp_path: Path, capsys) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        """cycle:
  start: 2018-04-15T00:00:00Z
  end: 2018-04-15T12:00:00Z
  step: PT6H
tasks:
  - name: first
    argv: [printf, first]
""",
        encoding="utf-8",
    )

    assert main([
        "plan", str(workflow),
        "--from", "2018-04-15T06:00:00Z",
        "--to", "2018-04-15T12:00:00Z",
    ]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "20180415T060000Z/01. first",
        "20180415T120000Z/01. first",
    ]
