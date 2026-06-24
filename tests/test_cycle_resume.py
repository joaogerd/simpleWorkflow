from __future__ import annotations

import sys
from pathlib import Path

from simpleworkflow.cli import main


def test_cycle_run_keeps_independent_restart_state(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        f"""workflow:
  name: restart-test
context:
  python: {sys.executable}
  output_dir: {output_dir}
cycle:
  start: 2018-04-15T00:00:00Z
  end: 2018-04-15T06:00:00Z
  step: PT6H
tasks:
  - name: write
    argv:
      - '{{python}}'
      - -c
      - "from pathlib import Path; Path(r'{{output_dir}}/{{cycle_id}}.txt').write_text('{{cycle_time}}')"
    outputs:
      required: ['{{output_dir}}/{{cycle_id}}.txt']
""",
        encoding="utf-8",
    )
    workdir = tmp_path / ".simpleworkflow"

    assert main(["run", str(workflow), "--workdir", str(workdir)]) == 0
    assert (output_dir / "20180415T000000Z.txt").exists()
    assert (output_dir / "20180415T060000Z.txt").exists()
    assert (workdir / "cycles" / "20180415T000000Z" / "state.sqlite3").exists()
    assert (workdir / "cycles" / "20180415T060000Z" / "state.sqlite3").exists()

    assert main(["run", str(workflow), "--workdir", str(workdir)]) == 0
