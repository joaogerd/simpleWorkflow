from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

from simpleworkflow.engine import WorkflowEngine


def _write_fake_qsub(path: Path) -> Path:
    path.write_text(
        """#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

arguments = sys.argv[1:]
assert arguments[:2] == ["-W", "block=true"]
assert "-V" in arguments
script = Path(arguments[-1])
completed = subprocess.run(["bash", str(script)], check=False)
print("12345.fake")
raise SystemExit(completed.returncode)
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_pbs_executor_waits_for_job_and_records_rendered_script(tmp_path: Path) -> None:
    execution_dir = tmp_path / "execution"
    execution_dir.mkdir()
    workflow_path = tmp_path / "workflow.yaml"
    workflow_path.write_text("workflow: {name: pbs-test}\n", encoding="utf-8")
    qsub = _write_fake_qsub(tmp_path / "fake-qsub")

    config = {
        "workflow": {"name": "pbs-test"},
        "context": {
            "python": sys.executable,
            "cwd": str(execution_dir),
            "qsub": str(qsub),
        },
        "tasks": [
            {
                "name": "analysis",
                "executor": "pbs",
                "argv": [
                    "{python}",
                    "-c",
                    "from pathlib import Path; Path('analysis.nc').write_text('ok')",
                ],
                "cwd": "{cwd}",
                "outputs": {"required": ["{cwd}/analysis.nc"]},
                "pbs": {
                    "qsub": "{qsub}",
                    "queue": "testq",
                    "walltime": "00:05:00",
                    "select": 1,
                    "ncpus": 2,
                    "mpiprocs": 2,
                    "omp_threads": 1,
                    "inherit_environment": True,
                    "block": True,
                },
            }
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow_path),
            "source_dir": str(tmp_path),
        },
    }

    workdir = tmp_path / ".simpleworkflow"
    engine = WorkflowEngine(config, workdir=workdir)

    assert engine.run() == 0
    assert (execution_dir / "analysis.nc").read_text(encoding="utf-8") == "ok"

    attempt = next((workdir / "runs").glob("*/tasks/*/attempt-001"))
    script = attempt / "job.pbs"
    script_content = script.read_text(encoding="utf-8")
    assert "#PBS -q testq" in script_content
    assert "#PBS -l select=1:ncpus=2:mpiprocs=2" in script_content
    assert "export OMP_NUM_THREADS=1" in script_content

    metadata = json.loads((attempt / "metadata.json").read_text(encoding="utf-8"))
    execution = metadata["execution"]
    assert execution["executor"] == "pbs"
    assert execution["wait_mode"] == "block"
    assert execution["job_id"] == "12345.fake"
    assert execution["qsub_argv"][1:3] == ["-W", "block=true"]
