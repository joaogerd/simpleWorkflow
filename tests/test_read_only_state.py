from __future__ import annotations

import sys
from pathlib import Path

from simpleworkflow.cli import main


def _workflow(path: Path) -> Path:
    path.write_text(
        f"""
workflow:
  name: read_only_case
tasks:
  - name: make_output
    cwd: .
    argv:
      - {sys.executable!r}
      - -c
      - "from pathlib import Path; Path('result.txt').write_text('ok')"
    outputs:
      required:
        - result.txt
""".lstrip(),
        encoding="utf-8",
    )
    return path


def test_status_explain_and_reset_do_not_create_missing_state(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path / "workflow.yaml")
    state_dir = tmp_path / ".simpleworkflow"

    assert main(["status", str(workflow), "--color", "never"]) == 0
    assert main(["explain", str(workflow), "--color", "never"]) == 0
    assert main(["reset", str(workflow), "--color", "never"]) == 0

    assert not state_dir.exists()


def test_dry_run_has_no_persistent_side_effects(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path / "workflow.yaml")
    state_dir = tmp_path / ".simpleworkflow"

    assert main(["run", str(workflow), "--dry-run", "--color", "never"]) == 0

    assert not state_dir.exists()
    assert not (tmp_path / "result.txt").exists()


def test_status_and_explain_do_not_modify_existing_database(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path / "workflow.yaml")
    state_path = tmp_path / ".simpleworkflow" / "state.sqlite3"

    assert main(["run", str(workflow), "--color", "never"]) == 0
    before = state_path.read_bytes()

    assert main(["status", str(workflow), "--color", "never"]) == 0
    assert state_path.read_bytes() == before
    assert main(["explain", str(workflow), "--color", "never"]) == 0
    assert state_path.read_bytes() == before
