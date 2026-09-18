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


def _write_scoped_workflow(path: Path, output_dir: Path) -> Path:
    init_code = (
        "from pathlib import Path; "
        "root = Path(r'{output_dir}'); "
        "root.mkdir(parents=True, exist_ok=True); "
        "(root / 'init.txt').write_text('initialized'); "
        "(root / 'order.log').open('a').write('INIT\\n')"
    )

    def scope_code(scope: str) -> str:
        return (
            "from pathlib import Path; "
            "root = Path(r'{output_dir}'); "
            "root.mkdir(parents=True, exist_ok=True); "
            f"(root / '{scope}_{{cycle_id}}.txt').write_text('{{cycle_time}}'); "
            f"(root / 'order.log').open('a').write('{scope}:{{cycle_id}}\\n')"
        )

    path.write_text(
        f"""
workflow:
  name: scoped_cycle_test
initialization:
  tasks:
    - name: initialize
      argv:
        - "{{python}}"
        - -c
        - {json.dumps(init_code)}
      outputs:
        required:
          - "{{output_dir}}/init.txt"
cycle:
  start: "2018-04-15T00:00:00Z"
  end: "2018-04-15T12:00:00Z"
  step: PT6H
context:
  python: {json.dumps(sys.executable)}
  output_dir: {json.dumps(str(output_dir))}
tasks:
  - name: all_task
    cycle_scope: all
    argv: ["{{python}}", -c, {json.dumps(scope_code("all"))}]
    outputs:
      required: ["{{output_dir}}/all_{{cycle_id}}.txt"]
  - name: first_task
    cycle_scope: first
    depends_on: [all_task]
    argv: ["{{python}}", -c, {json.dumps(scope_code("first"))}]
    outputs:
      required: ["{{output_dir}}/first_{{cycle_id}}.txt"]
  - name: not_first_task
    cycle_scope: not_first
    depends_on: [all_task]
    argv: ["{{python}}", -c, {json.dumps(scope_code("not_first"))}]
    outputs:
      required: ["{{output_dir}}/not_first_{{cycle_id}}.txt"]
  - name: not_last_task
    cycle_scope: not_last
    depends_on: [all_task]
    argv: ["{{python}}", -c, {json.dumps(scope_code("not_last"))}]
    outputs:
      required: ["{{output_dir}}/not_last_{{cycle_id}}.txt"]
  - name: last_task
    cycle_scope: last
    depends_on: [all_task]
    argv: ["{{python}}", -c, {json.dumps(scope_code("last"))}]
    outputs:
      required: ["{{output_dir}}/last_{{cycle_id}}.txt"]
""".lstrip(),
        encoding="utf-8",
    )
    return path


def _write_initialization_restart_workflow(path: Path, output_dir: Path) -> Path:
    prepare_code = (
        "from pathlib import Path; "
        "root=Path(r'{output_dir}'); root.mkdir(parents=True, exist_ok=True); "
        "(root/'init_prepare.txt').write_text('ready'); "
        "(root/'init_prepare.log').open('a').write('run\\n')"
    )
    finish_code = (
        "from pathlib import Path; import sys; "
        "root=Path(r'{output_dir}'); marker=root/'init_fail_once'; "
        "(root/'init_finish.log').open('a').write('run\\n'); "
        "first=not marker.exists(); marker.touch(); "
        "sys.exit(9) if first else (root/'init_done.txt').write_text('done')"
    )
    cycle_code = (
        "from pathlib import Path; "
        "root=Path(r'{output_dir}'); "
        "(root/'cycle_{cycle_id}.txt').write_text('{cycle_time}')"
    )
    path.write_text(
        f"""
workflow:
  name: initialization_restart_test
initialization:
  tasks:
    - name: init_prepare
      argv: ["{{python}}", -c, {json.dumps(prepare_code)}]
      outputs:
        required: ["{{output_dir}}/init_prepare.txt"]
    - name: init_finish
      depends_on: [init_prepare]
      argv: ["{{python}}", -c, {json.dumps(finish_code)}]
      outputs:
        required: ["{{output_dir}}/init_done.txt"]
cycle:
  start: "2018-04-15T00:00:00Z"
  end: "2018-04-15T06:00:00Z"
  step: PT6H
context:
  python: {json.dumps(sys.executable)}
  output_dir: {json.dumps(str(output_dir))}
tasks:
  - name: cycle_task
    argv: ["{{python}}", -c, {json.dumps(cycle_code)}]
    inputs:
      required: ["{{output_dir}}/init_done.txt"]
    outputs:
      required: ["{{output_dir}}/cycle_{{cycle_id}}.txt"]
""".lstrip(),
        encoding="utf-8",
    )
    return path


def _write_cycle_restart_workflow(path: Path, output_dir: Path) -> Path:
    init_code = (
        "from pathlib import Path; root=Path(r'{output_dir}'); "
        "root.mkdir(parents=True, exist_ok=True); "
        "(root/'init.txt').write_text('ready'); "
        "(root/'init.log').open('a').write('run\\n')"
    )
    prepare_code = (
        "from pathlib import Path; root=Path(r'{output_dir}'); "
        "(root/'prepare.log').open('a').write('{cycle_id}\\n'); "
        "(root/'prepare_{cycle_id}.txt').write_text('ready')"
    )
    run_code = (
        "from pathlib import Path; import sys; root=Path(r'{output_dir}'); "
        "cid='{cycle_id}'; (root/'run.log').open('a').write(cid+'\\n'); "
        "marker=root/('failed_'+cid); "
        "should_fail=(cid=='20180415T060000Z' and not marker.exists()); "
        "marker.touch() if should_fail else None; "
        "sys.exit(7) if should_fail else (root/('done_'+cid+'.txt')).write_text('done')"
    )
    path.write_text(
        f"""
workflow:
  name: cycle_restart_test
initialization:
  tasks:
    - name: initialize
      argv: ["{{python}}", -c, {json.dumps(init_code)}]
      outputs:
        required: ["{{output_dir}}/init.txt"]
cycle:
  start: "2018-04-15T00:00:00Z"
  end: "2018-04-15T12:00:00Z"
  step: PT6H
context:
  python: {json.dumps(sys.executable)}
  output_dir: {json.dumps(str(output_dir))}
tasks:
  - name: prepare
    argv: ["{{python}}", -c, {json.dumps(prepare_code)}]
    outputs:
      required: ["{{output_dir}}/prepare_{{cycle_id}}.txt"]
  - name: run
    depends_on: [prepare]
    argv: ["{{python}}", -c, {json.dumps(run_code)}]
    outputs:
      required: ["{{output_dir}}/done_{{cycle_id}}.txt"]
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
    rows = connection.execute(
        "SELECT cycle_id, task, status FROM task_state ORDER BY cycle_id"
    ).fetchall()
    cycles = connection.execute(
        "SELECT cycle_id, cycle_time FROM cycle_state ORDER BY cycle_id"
    ).fetchall()
    instance_count = connection.execute("SELECT COUNT(*) FROM workflow_instance").fetchone()[0]
    workflow_name = connection.execute(
        "SELECT workflow_name FROM workflow_instance WHERE singleton = 1"
    ).fetchone()[0]
    connection.close()

    assert rows == [
        ("20180415T000000Z", "write_cycle", "success"),
        ("20180415T060000Z", "write_cycle", "success"),
        ("20180415T120000Z", "write_cycle", "success"),
    ]
    assert cycles == [
        ("20180415T000000Z", "2018-04-15T00:00:00Z"),
        ("20180415T060000Z", "2018-04-15T06:00:00Z"),
        ("20180415T120000Z", "2018-04-15T12:00:00Z"),
    ]
    assert instance_count == 1
    assert workflow_name == "cycle_test"


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
        'workflow: {name: cycle_test}\ncycle: {start: "2018-04-15T00:00:00Z", step: PT6H}\ntasks: []\n',
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


def test_72_hour_cycle_range_is_inclusive_and_contains_13_cycles() -> None:
    cycles = resolve_cycle_contexts(
        {
            "start": "2018-04-15T00:00:00Z",
            "end": "2018-04-18T00:00:00Z",
            "step": "PT6H",
        }
    )

    assert len(cycles) == 13
    assert cycles[0].cycle_id == "20180415T000000Z"
    assert cycles[-1].cycle_id == "20180418T000000Z"


def test_cycle_context_exposes_position_and_neighbors() -> None:
    cycles = resolve_cycle_contexts(
        {
            "start": "2018-04-15T00:00:00Z",
            "end": "2018-04-15T12:00:00Z",
            "step": "PT6H",
        }
    )

    first = cycles[0].render_context()
    middle = cycles[1].render_context()
    last = cycles[2].render_context()

    assert first["cycle_index"] == "0"
    assert first["cycle_count"] == "3"
    assert first["cycle_is_first"] == "true"
    assert first["cycle_is_last"] == "false"
    assert first["previous_cycle_time"] == ""
    assert first["previous_cycle_id"] == ""
    assert first["next_cycle_time"] == "2018-04-15T06:00:00Z"
    assert first["next_cycle_id"] == "20180415T060000Z"

    assert middle["cycle_index"] == "1"
    assert middle["cycle_count"] == "3"
    assert middle["cycle_is_first"] == "false"
    assert middle["cycle_is_last"] == "false"
    assert middle["previous_cycle_time"] == "2018-04-15T00:00:00Z"
    assert middle["previous_cycle_id"] == "20180415T000000Z"
    assert middle["next_cycle_time"] == "2018-04-15T12:00:00Z"
    assert middle["next_cycle_id"] == "20180415T120000Z"

    assert last["cycle_index"] == "2"
    assert last["cycle_count"] == "3"
    assert last["cycle_is_first"] == "false"
    assert last["cycle_is_last"] == "true"
    assert last["previous_cycle_time"] == "2018-04-15T06:00:00Z"
    assert last["previous_cycle_id"] == "20180415T060000Z"
    assert last["next_cycle_time"] == ""
    assert last["next_cycle_id"] == ""


def test_explicit_cycle_selection_preserves_declared_campaign_position() -> None:
    cycles = resolve_cycle_contexts(
        {
            "start": "2018-04-15T00:00:00Z",
            "end": "2018-04-15T12:00:00Z",
            "step": "PT6H",
        },
        cycle_times=["2018-04-15T06:00:00Z"],
    )

    assert len(cycles) == 1
    context = cycles[0].render_context()
    assert context["cycle_index"] == "1"
    assert context["cycle_count"] == "3"
    assert context["cycle_is_first"] == "false"
    assert context["cycle_is_last"] == "false"
    assert context["previous_cycle_id"] == "20180415T000000Z"
    assert context["next_cycle_id"] == "20180415T120000Z"


def test_initialization_and_cycle_scopes_execute_in_expected_positions(tmp_path: Path) -> None:
    products = tmp_path / "products"
    workflow = _write_scoped_workflow(tmp_path / "workflow.yaml", products)
    workdir = tmp_path / "state"

    assert main(["run", str(workflow), "--workdir", str(workdir)]) == 0

    assert (products / "init.txt").exists()
    assert len(list(products.glob("all_*.txt"))) == 3
    assert len(list(products.glob("first_*.txt"))) == 1
    assert len(list(products.glob("not_first_*.txt"))) == 2
    assert len(list(products.glob("not_last_*.txt"))) == 2
    assert len(list(products.glob("last_*.txt"))) == 1

    connection = sqlite3.connect(workdir / "state.sqlite3")
    counts = dict(
        connection.execute(
            "SELECT task, COUNT(*) FROM task_state GROUP BY task ORDER BY task"
        ).fetchall()
    )
    init_row = connection.execute(
        "SELECT cycle_id, status FROM task_state WHERE task = 'initialize'"
    ).fetchone()
    connection.close()

    assert init_row == ("", "success")
    assert counts == {
        "all_task": 3,
        "first_task": 1,
        "initialize": 1,
        "last_task": 1,
        "not_first_task": 2,
        "not_last_task": 2,
    }

    order = (products / "order.log").read_text().splitlines()
    assert order[0] == "INIT"
    assert [line for line in order if line.startswith("all:")] == [
        "all:20180415T000000Z",
        "all:20180415T060000Z",
        "all:20180415T120000Z",
    ]


def test_not_last_runs_exactly_12_times_for_13_cycles(tmp_path: Path) -> None:
    products = tmp_path / "products"
    products.mkdir()
    code = (
        "from pathlib import Path; root=Path(r'{output_dir}'); "
        "(root/'not_last_{cycle_id}.txt').write_text('{cycle_time}')"
    )
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        f"""
workflow:
  name: thirteen_cycle_scope_test
cycle:
  start: "2018-04-15T00:00:00Z"
  end: "2018-04-18T00:00:00Z"
  step: PT6H
context:
  python: {json.dumps(sys.executable)}
  output_dir: {json.dumps(str(products))}
tasks:
  - name: next_cycle_product
    cycle_scope: not_last
    argv: ["{{python}}", -c, {json.dumps(code)}]
    outputs:
      required: ["{{output_dir}}/not_last_{{cycle_id}}.txt"]
""".lstrip(),
        encoding="utf-8",
    )
    workdir = tmp_path / "state"

    assert main(["run", str(workflow), "--workdir", str(workdir)]) == 0
    assert len(list(products.glob("not_last_*.txt"))) == 12

    connection = sqlite3.connect(workdir / "state.sqlite3")
    count = connection.execute(
        "SELECT COUNT(*) FROM task_state WHERE task = 'next_cycle_product'"
    ).fetchone()[0]
    connection.close()
    assert count == 12


def test_initialization_restart_resumes_only_incomplete_initialization(tmp_path: Path) -> None:
    products = tmp_path / "products"
    workflow = _write_initialization_restart_workflow(
        tmp_path / "workflow.yaml", products
    )
    workdir = tmp_path / "state"

    assert main(["run", str(workflow), "--workdir", str(workdir)]) == 9
    assert (products / "init_prepare.txt").exists()
    assert not (products / "init_done.txt").exists()
    assert not list(products.glob("cycle_*.txt"))

    assert main(["run", str(workflow), "--workdir", str(workdir)]) == 0
    assert (products / "init_done.txt").exists()
    assert len(list(products.glob("cycle_*.txt"))) == 2
    assert (products / "init_prepare.log").read_text().splitlines() == ["run"]
    assert (products / "init_finish.log").read_text().splitlines() == ["run", "run"]


def test_cycle_restart_is_fail_fast_and_resume_does_not_repeat_completed_work(tmp_path: Path) -> None:
    products = tmp_path / "products"
    workflow = _write_cycle_restart_workflow(tmp_path / "workflow.yaml", products)
    workdir = tmp_path / "state"

    assert main(["run", str(workflow), "--workdir", str(workdir)]) == 7
    assert (products / "done_20180415T000000Z.txt").exists()
    assert not (products / "done_20180415T060000Z.txt").exists()
    assert not (products / "done_20180415T120000Z.txt").exists()

    assert main(["run", str(workflow), "--workdir", str(workdir)]) == 0
    assert (products / "done_20180415T060000Z.txt").exists()
    assert (products / "done_20180415T120000Z.txt").exists()

    assert (products / "init.log").read_text().splitlines() == ["run"]
    assert (products / "prepare.log").read_text().splitlines() == [
        "20180415T000000Z",
        "20180415T060000Z",
        "20180415T120000Z",
    ]
    assert (products / "run.log").read_text().splitlines() == [
        "20180415T000000Z",
        "20180415T060000Z",
        "20180415T060000Z",
        "20180415T120000Z",
    ]

    before = (products / "run.log").read_text()
    assert main(["run", str(workflow), "--workdir", str(workdir)]) == 0
    assert (products / "run.log").read_text() == before
    assert (products / "init.log").read_text().splitlines() == ["run"]


def test_resuming_after_one_selected_cycle_preserves_initialization_and_cycle_state(
    tmp_path: Path,
) -> None:
    products = tmp_path / "products"
    workflow = _write_scoped_workflow(tmp_path / "workflow.yaml", products)
    workdir = tmp_path / "state"

    assert (
        main(
            [
                "run",
                str(workflow),
                "--cycle-time",
                "2018-04-15T00:00:00Z",
                "--workdir",
                str(workdir),
            ]
        )
        == 0
    )
    assert (products / "init.txt").exists()
    assert (products / "all_20180415T000000Z.txt").exists()

    assert main(["run", str(workflow), "--workdir", str(workdir)]) == 0
    order = (products / "order.log").read_text().splitlines()
    assert order.count("INIT") == 1
    assert order.count("all:20180415T000000Z") == 1
    assert order.count("all:20180415T060000Z") == 1
    assert order.count("all:20180415T120000Z") == 1


def test_cycle_scope_is_strictly_validated(tmp_path: Path) -> None:
    accepted = tmp_path / "accepted.yaml"
    accepted.write_text(
        """
workflow: {name: selector_validation}
cycle:
  start: "2018-04-15T00:00:00Z"
  end: "2018-04-15T06:00:00Z"
  step: PT6H
tasks:
  - name: valid
    cycle_scope: not_last
    argv: [python, -c, "print('ok')"]
""".lstrip(),
        encoding="utf-8",
    )
    assert load_workflow(accepted)["tasks"][0]["cycle_scope"] == "not_last"

    rejected = tmp_path / "rejected.yaml"
    rejected.write_text(
        """
workflow: {name: selector_validation}
cycle:
  start: "2018-04-15T00:00:00Z"
  end: "2018-04-15T06:00:00Z"
  step: PT6H
tasks:
  - name: invalid
    cycle_scope: arbitrary_expression
    argv: [python, -c, "print('no')"]
""".lstrip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="cycle_scope"):
        load_workflow(rejected)


def test_workflow_without_initialization_or_scope_remains_compatible(tmp_path: Path) -> None:
    workflow = _write_cycle_workflow(tmp_path / "workflow.yaml", tmp_path / "products")
    loaded = load_workflow(workflow)

    assert "initialization" not in loaded
    assert loaded["tasks"][0].get("cycle_scope") is None
    assert main(["run", str(workflow), "--workdir", str(tmp_path / "state")]) == 0
