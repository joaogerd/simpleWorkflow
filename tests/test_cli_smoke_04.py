from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from simpleworkflow.cli import main
from simpleworkflow.migrations import inspect_state
from simpleworkflow.state import WorkflowState

FIXTURES = Path(__file__).parent / "fixtures"


def test_release_cli_lifecycle_smoke(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        f"""
workflow:
  name: cli_smoke
tasks:
  - name: hello
    cwd: .
    argv:
      - {sys.executable!r}
      - -c
      - "from pathlib import Path; Path('hello.txt').write_text('ok')"
    outputs:
      required: [hello.txt]
""".lstrip(),
        encoding="utf-8",
    )
    state_dir = tmp_path / ".simpleworkflow"

    assert main(["validate", str(workflow), "--color", "never"]) == 0
    assert main(["plan", str(workflow), "--color", "never"]) == 0
    assert main(["status", str(workflow), "--color", "never"]) == 0
    assert main(["explain", str(workflow), "--color", "never"]) == 0
    assert not state_dir.exists()

    assert main(["run", str(workflow), "--color", "never"]) == 0
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "ok"
    assert main(["status", str(workflow), "--color", "never"]) == 0
    assert main(["explain", str(workflow), "--color", "never"]) == 0
    assert main(["reset", str(workflow), "--color", "never"]) == 0

    state = WorkflowState(
        state_dir / "state.sqlite3",
        workflow_name="cli_smoke",
        source_path=workflow,
    )
    assert state.get_status("hello") is None
    state.close()


def test_release_cli_migration_smoke(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: migration_smoke}\ntasks: []\n", encoding="utf-8")
    state_path = tmp_path / ".simpleworkflow" / "state.sqlite3"
    state_path.parent.mkdir()
    connection = sqlite3.connect(state_path)
    connection.executescript(
        (FIXTURES / "state_v0_2.sql").read_text(encoding="utf-8")
    )
    connection.execute(
        """
        INSERT INTO task_state(workflow, task, status, return_code)
        VALUES ('migration_smoke', 'legacy_task', 'failed', 7)
        """
    )
    connection.commit()
    connection.close()

    assert main(["migrate", str(workflow), "--check", "--color", "never"]) == 0
    assert inspect_state(state_path).legacy_version == "0.2.x"
    assert main(["migrate", str(workflow), "--color", "never"]) == 0
    assert inspect_state(state_path).schema_version == 1
    assert main(["status", str(workflow), "--color", "never"]) == 0
