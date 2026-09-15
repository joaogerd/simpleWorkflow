from __future__ import annotations

import os
from pathlib import Path

from simpleworkflow.cli import main


def _write_workflow(path: Path) -> None:
    path.write_text(
        """
workflow:
  name: cli_state_root
tasks:
  - name: hello
    cwd: .
    argv:
      - python
      - -c
      - "from pathlib import Path; Path('hello.txt').write_text('ok')"
    outputs:
      required:
        - hello.txt
""".lstrip(),
        encoding="utf-8",
    )


def test_default_workdir_is_beside_workflow_not_current_directory(
    tmp_path: Path, monkeypatch: object
) -> None:
    case = tmp_path / "case"
    caller = tmp_path / "caller"
    case.mkdir()
    caller.mkdir()
    workflow = case / "workflow.yaml"
    _write_workflow(workflow)
    monkeypatch.chdir(caller)  # type: ignore[attr-defined]

    assert main(["run", str(workflow), "--color", "never"]) == 0
    assert (case / ".simpleworkflow" / "state.sqlite3").is_file()
    assert not (caller / ".simpleworkflow").exists()

    assert main(["status", str(workflow), "--color", "never"]) == 0
    assert main(["reset", str(workflow), "--color", "never"]) == 0
    assert (case / ".simpleworkflow" / "state.sqlite3").is_file()


def test_explicit_relative_workdir_remains_relative_to_current_directory(
    tmp_path: Path, monkeypatch: object
) -> None:
    case = tmp_path / "case"
    caller = tmp_path / "caller"
    case.mkdir()
    caller.mkdir()
    workflow = case / "workflow.yaml"
    _write_workflow(workflow)
    monkeypatch.chdir(caller)  # type: ignore[attr-defined]

    assert main(["run", str(workflow), "--workdir", "state-here", "--color", "never"]) == 0
    assert (caller / "state-here" / "state.sqlite3").is_file()
    assert not (case / ".simpleworkflow").exists()


def test_plan_and_validate_share_same_default_resolution_without_using_cwd_state(
    tmp_path: Path, monkeypatch: object
) -> None:
    case = tmp_path / "case"
    caller = tmp_path / "caller"
    case.mkdir()
    caller.mkdir()
    workflow = case / "workflow.yaml"
    _write_workflow(workflow)
    monkeypatch.chdir(caller)  # type: ignore[attr-defined]

    assert main(["plan", str(workflow), "--color", "never"]) == 0
    assert main(["validate", str(workflow), "--color", "never"]) == 0
    assert (case / ".simpleworkflow" / "state.sqlite3").is_file()
    assert not (caller / ".simpleworkflow").exists()


def test_absolute_explicit_workdir_is_preserved(tmp_path: Path, monkeypatch: object) -> None:
    case = tmp_path / "case"
    caller = tmp_path / "caller"
    state = tmp_path / "external-state"
    case.mkdir()
    caller.mkdir()
    workflow = case / "workflow.yaml"
    _write_workflow(workflow)
    monkeypatch.chdir(caller)  # type: ignore[attr-defined]

    assert main(["status", str(workflow), "--workdir", str(state), "--color", "never"]) == 0
    assert (state / "state.sqlite3").is_file()
    assert os.path.samefile(state, state.resolve())
