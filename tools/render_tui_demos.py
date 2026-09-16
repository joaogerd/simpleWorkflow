#!/usr/bin/env python3
"""Render deterministic headless TUI demonstrations for release review.

These screenshots exercise persisted local fixtures only. They are UI evidence,
not scientific or JACI execution evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
from pathlib import Path
from typing import Any

from simpleworkflow.runs import RunRecorder
from simpleworkflow.state import WorkflowState
from simpleworkflow.tui import WorkflowTui


def _simple_config(workflow: Path, name: str) -> dict[str, Any]:
    return {
        "workflow": {"name": name},
        "tasks": [
            {"name": "prepare", "argv": ["true"]},
            {"name": "analysis", "argv": ["true"], "depends_on": ["prepare"]},
            {"name": "forecast", "argv": ["true"], "depends_on": ["analysis"]},
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }


def _unrolled_config(workflow: Path) -> dict[str, Any]:
    return {
        "workflow": {"name": "MONAN-JEDI-style unrolled demo"},
        "tasks": [
            {"name": "global_setup", "argv": ["true"]},
            {
                "name": "jedi00_prepare",
                "depends_on": ["global_setup"],
                "argv": ["tool", "jedi", "--cycle", "2018-04-15T00:00:00Z"],
            },
            {
                "name": "jedi00_gate",
                "depends_on": ["jedi00_prepare"],
                "argv": ["tool", "gate"],
            },
            {
                "name": "obs06_prepare",
                "depends_on": ["jedi00_gate"],
                "argv": ["tool", "obs", "--cycle", "2018-04-15T06:00:00Z"],
            },
            {
                "name": "mpas00_prepare",
                "depends_on": ["jedi00_gate"],
                "argv": ["tool", "mpas", "--cycle", "2018-04-15T00:00:00Z"],
            },
            {
                "name": "jedi06_prepare",
                "depends_on": ["mpas00_prepare", "obs06_prepare"],
                "argv": ["tool", "jedi", "--cycle", "2018-04-15T06:00:00Z"],
            },
            {
                "name": "global_summary",
                "depends_on": ["jedi00_prepare", "jedi06_prepare"],
                "argv": ["true"],
            },
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }


def _scenario_root(output: Path, name: str) -> tuple[Path, Path]:
    root = output / "state" / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    workflow = root / "workflow.yaml"
    workdir = root / ".simpleworkflow"
    return workflow, workdir


def _simple_scenario(output: Path, scenario: str) -> tuple[dict[str, Any], Path, Path]:
    workflow, workdir = _scenario_root(output, scenario)
    workflow.write_text(f"workflow: {{name: {scenario}}}\n", encoding="utf-8")
    config = _simple_config(workflow, scenario)
    if scenario == "starting":
        return config, workflow, workdir

    state = WorkflowState(workdir / "state.sqlite3", workflow_name=scenario, source_path=workflow)
    if scenario == "running":
        state.set_status("prepare", "running", None)
    elif scenario == "partial":
        state.set_status("prepare", "success", 0)
        state.set_status("analysis", "running", None)
    elif scenario == "failure":
        state.set_status("prepare", "success", 0)
        state.set_status("analysis", "failed", 7, reason="demonstration failure")
        state.set_status("forecast", "blocked", 4, reason="analysis is unavailable")
    elif scenario == "completed":
        for task in ("prepare", "analysis", "forecast"):
            state.set_status(task, "success", 0)
    else:
        raise ValueError(scenario)
    state.close()
    return config, workflow, workdir


def _unrolled_scenario(output: Path) -> tuple[dict[str, Any], Path, Path]:
    workflow, workdir = _scenario_root(output, "unrolled")
    workflow.write_text("workflow: {name: unrolled}\n", encoding="utf-8")
    config = _unrolled_config(workflow)
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="MONAN-JEDI-style unrolled demo",
        source_path=workflow,
    )
    state.set_status("global_setup", "success", 0)
    state.set_status("jedi00_prepare", "success", 0)
    state.set_status("jedi00_gate", "success", 0)
    state.set_status("mpas00_prepare", "success", 0)
    state.set_status("obs06_prepare", "success", 0)

    recorder = RunRecorder(
        workdir,
        "MONAN-JEDI-style unrolled demo",
        instance_id=state.instance_id,
        run_id="demo-run",
    )
    state.record_run(recorder.run_id, recorder.directory)
    attempt = recorder.begin_attempt("jedi06_prepare")
    recorder.write_started(
        attempt,
        {
            "status": "running",
            "command": {
                "argv": ["monan-jedi-workflow", "jedi-prepare", "--cycle", "2018-04-15T06:00:00Z"],
                "cwd": str(workflow.parent),
                "env": {},
            },
            "signature": "demo",
        },
    )
    attempt.stdout_path.write_text("preparing 06Z analysis\n", encoding="utf-8")
    attempt.stderr_path.write_text("demonstration failure: missing input\n", encoding="utf-8")
    state.record_attempt_started(
        run_id=attempt.run_id,
        task="jedi06_prepare",
        attempt=attempt.attempt,
        attempt_path=attempt.directory,
        signature="demo",
        started_at="2018-04-15T06:01:00Z",
    )
    state.record_attempt_finished(
        run_id=attempt.run_id,
        task="jedi06_prepare",
        attempt=attempt.attempt,
        status="failed",
        return_code=7,
        reason="demonstration failure: missing input",
    )
    state.set_status(
        "jedi06_prepare",
        "failed",
        7,
        signature="demo",
        reason="demonstration failure: missing input",
        attempt_path=attempt.directory,
    )
    state.finish_run(recorder.run_id, "failed")
    state.close()
    return config, workflow, workdir


async def _capture(
    config: dict[str, Any],
    workflow: Path,
    workdir: Path,
    destination: Path,
    *,
    view: str = "monitor",
    error_log: bool = False,
    size: tuple[int, int] = (140, 42),
) -> None:
    app = WorkflowTui(
        config=config,
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60,
    )
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        app.query_one("#views").active = view
        if view == "logs" and error_log:
            app.action_select_error()
        await pilot.pause()
        destination.write_text(app.export_screenshot(), encoding="utf-8")


async def _render(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for scenario in ("starting", "running", "partial", "failure", "completed"):
        config, workflow, workdir = _simple_scenario(output, scenario)
        await _capture(
            config,
            workflow,
            workdir,
            output / f"scenario-{scenario}.svg",
        )

    config, workflow, workdir = _unrolled_scenario(output)
    await _capture(config, workflow, workdir, output / "scenario-unrolled.svg")
    for view in ("monitor", "cycles", "campaign", "problems", "logs"):
        await _capture(
            config,
            workflow,
            workdir,
            output / f"unrolled-{view}.svg",
            view=view,
            error_log=view == "logs",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(_render(args.output_dir.resolve()))
    screenshots = sorted(args.output_dir.glob("*.svg"))
    if len(screenshots) != 11:
        raise RuntimeError(f"expected 11 screenshots, produced {len(screenshots)}")
    for path in screenshots:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
