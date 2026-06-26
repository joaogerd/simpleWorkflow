from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from simpleworkflow.cli import main
from simpleworkflow.config import load_workflow
from simpleworkflow.cycles import CycleConfigurationError, resolve_cycle_contexts


def _write_cycle_workflow(path: Path, output_dir: Path) -> Path:
    code = (
        "from pathlib import Path; "
        "root = Path(r'{output_dir}'); "
        "root.mkdir(parents=True, exist_ok=True); "
        "(root / 'cycle_{cycle_yyyymmddhh}.txt').write_text('{cycle_time}')"
    )
    path.write_text(
        f"""
workflow:
  name: cycle_test
cycle:
  start: "2018-04-15T00:00:00Z"
  end: "2018-04-15T12:00:00Z"
  step: PT6H
context:
  python: {json.dumps(sys.executable)}
  output_dir: {json.dumps(str(output_dir))}
tasks:
  - name: write_cycle
    argv:
      - "{{python}}"
      - -c
      - {json.dumps(code)}
    outputs:
      required:
        - "{{output_dir}}/cycle_{{cycle_yyyymmddhh}}.txt"
""".lstrip(),
        encoding="utf-8",
    )
    return path


def test_cycle_expansion_renders_per_cycle_context_and_state(tmp_path: Path) -> None:
    workflow = _write_cycle_workflow(tmp_path / "workflow.yaml", tmp_path / "products")
    workdir = tmp_path / "state"

    assert main(["run", str(workflow), "--workdir", str(workdir)]) == 0

    assert (tmp_path / "products" / "cycle_2018041500.txt").read_text() == "2018-04-15T00:00:00Z"
    assert (tmp_path / "products" / "cycle_2018041506.txt").read_text() == "2018-04-15T06:00:00Z"
    assert (tmp_path / "products" / "cycle_2018041512.txt").read_text() == "2018-04-15T12:00:00Z"

    connection = sqlite3.connect(workdir / "state.sqlite3")
    rows = connection.execute("SELECT workflow, task, status FROM task_state ORDER BY workflow").fetchall()
    connection.close()
    assert rows == [
        ("cycle_test__20180415T000000Z", "write_cycle", "success"),
        ("cycle_test__20180415T060000Z", "write_cycle", "success"),
        ("cycle_test__20180415T120000Z", "write_cycle", "success"),
    ]


def test_cycle_time_selects_one_cycle(tmp_path: Path) -> None:
    workflow = _write_cycle_workflow(tmp_path / "workflow.yaml", tmp_path / "products")

    assert (
        main(
            [
                "run",
                str(workflow),
                "--cycle-time",
                "2018-04-15T06:00:00Z",
                "--workdir",
                str(tmp_path / "state"),
            ]
        )
        == 0
    )

    assert not (tmp_path / "products" / "cycle_2018041500.txt").exists()
    assert (tmp_path / "products" / "cycle_2018041506.txt").exists()
    assert not (tmp_path / "products" / "cycle_2018041512.txt").exists()


def test_range_options_override_yaml_cycle_fields() -> None:
    cycles = resolve_cycle_contexts(
        {
            "start": "2018-04-15T00:00:00Z",
            "end": "2018-04-15T12:00:00Z",
            "step": "PT6H",
        },
        start="2018-04-16T00:00:00Z",
        end="2018-04-16T12:00:00Z",
        step="PT12H",
    )
    assert [cycle.cycle_id for cycle in cycles] == ["20180416T000000Z", "20180416T120000Z"]


def test_cycle_config_requires_complete_mapping(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        'cycle: {start: "2018-04-15T00:00:00Z", step: PT6H}\ntasks: []\n',
        encoding="utf-8",
    )
    with pytest.raises(CycleConfigurationError, match="missing required field"):
        load_workflow(workflow)


def test_cycle_time_cannot_be_combined_with_range_options() -> None:
    with pytest.raises(CycleConfigurationError, match="cannot be combined"):
        resolve_cycle_contexts(
            None,
            cycle_times=["2018-04-15T00:00:00Z"],
            start="2018-04-15T00:00:00Z",
        )
