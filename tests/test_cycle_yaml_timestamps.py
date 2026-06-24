from __future__ import annotations

from pathlib import Path

from simpleworkflow.config import load_workflow
from simpleworkflow.cycles import resolve_cycle_points


def test_unquoted_yaml_timestamps_are_accepted(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        """cycle:
  start: 2018-04-15T00:00:00Z
  end: 2018-04-15T06:00:00Z
  step: PT6H
tasks:
  - name: first
    argv: [printf, first]
""",
        encoding="utf-8",
    )
    points = resolve_cycle_points(load_workflow(workflow)["cycle"])
    assert [point.identifier for point in points] == [
        "20180415T000000Z",
        "20180415T060000Z",
    ]
