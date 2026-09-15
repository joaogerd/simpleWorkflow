from __future__ import annotations

import shutil
import sys
from pathlib import Path

from simpleworkflow.cli import main
from simpleworkflow.state import WorkflowState


def test_moved_workflow_reuses_state_until_semantic_input_changes(tmp_path: Path) -> None:
    first_root = tmp_path / "case-A"
    first_root.mkdir()
    workflow = first_root / "workflow.yaml"
    source = first_root / "input.txt"
    source.write_text("first", encoding="utf-8")
    workflow.write_text(
        f"""
workflow:
  name: portable_change
tasks:
  - name: analysis
    cwd: .
    argv:
      - {sys.executable!r}
      - -c
      - "from pathlib import Path; Path('output.txt').write_text(Path('input.txt').read_text())"
    inputs:
      required: [input.txt]
    outputs:
      required: [output.txt]
    input_fingerprint: metadata
""".lstrip(),
        encoding="utf-8",
    )

    assert main(["run", str(workflow), "--color", "never"]) == 0
    state_path = first_root / ".simpleworkflow" / "state.sqlite3"
    state = WorkflowState(state_path, workflow_name="portable_change", source_path=workflow)
    instance_id = state.instance_id
    first_signature = state.get_task_state("analysis").signature  # type: ignore[union-attr]
    first_runs = state.connection.execute("SELECT COUNT(*) FROM run_history").fetchone()[0]
    state.close()

    second_root = tmp_path / "case-B"
    shutil.move(str(first_root), second_root)
    moved_workflow = second_root / "workflow.yaml"
    moved_state_path = second_root / ".simpleworkflow" / "state.sqlite3"

    assert main(["run", str(moved_workflow), "--color", "never"]) == 0
    moved = WorkflowState(
        moved_state_path,
        workflow_name="portable_change",
        source_path=moved_workflow,
    )
    assert moved.instance_id == instance_id
    assert moved.get_task_state("analysis").signature == first_signature  # type: ignore[union-attr]
    assert moved.connection.execute("SELECT COUNT(*) FROM run_history").fetchone()[0] == first_runs
    moved.close()

    (second_root / "input.txt").write_text("second-value", encoding="utf-8")
    assert main(["run", str(moved_workflow), "--color", "never"]) == 0
    assert (second_root / "output.txt").read_text(encoding="utf-8") == "second-value"
    changed = WorkflowState(
        moved_state_path,
        workflow_name="portable_change",
        source_path=moved_workflow,
    )
    assert changed.instance_id == instance_id
    assert changed.get_task_state("analysis").signature != first_signature  # type: ignore[union-attr]
    assert changed.connection.execute("SELECT COUNT(*) FROM run_history").fetchone()[0] == (
        first_runs + 1
    )
    changed.close()
