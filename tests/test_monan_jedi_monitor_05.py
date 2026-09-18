from __future__ import annotations

from pathlib import Path
from typing import Any

from simpleworkflow.monitor import load_monitor_snapshot

_CYCLES = {
    "00": "2018-04-15T00:00:00Z",
    "06": "2018-04-15T06:00:00Z",
    "12": "2018-04-15T12:00:00Z",
    "18": "2018-04-15T18:00:00Z",
}


def _stage_tasks(
    prefix: str,
    cycle: str,
    *,
    first_dependencies: list[str] | None = None,
    obs: bool = False,
) -> list[dict[str, Any]]:
    """Mirror one five-task stage from the published MONAN-JEDI replay."""
    first = "doctor" if obs else "prepare"
    middle = ["prepare", "run", "validate"] if obs else ["submit", "wait", "validate"]
    names = [first, *middle, "gate"]
    tasks: list[dict[str, Any]] = []
    previous: str | None = None
    for index, suffix in enumerate(names):
        name = f"{prefix}_{suffix}"
        dependencies = (
            list(first_dependencies or [])
            if index == 0
            else [previous] if previous is not None else []
        )
        argv = ["monan-jedi-workflow", suffix]
        if suffix != "gate":
            argv.extend(["--cycle", _CYCLES[cycle]])
        task: dict[str, Any] = {"name": name, "argv": argv}
        if dependencies:
            task["depends_on"] = dependencies
        tasks.append(task)
        previous = name
    return tasks


def _published_replay_shape(workflow: Path) -> dict[str, Any]:
    """Represent the 50-task 00Z→18Z corrected replay published by MONAN-JEDI.

    The source workflow is deliberately unrolled. The fixture keeps the same
    stage ordering and cross-cycle joins while replacing scientific arguments
    with harmless placeholders because this is a presentation/read-model test.
    """
    tasks: list[dict[str, Any]] = []
    tasks += _stage_tasks("jedi00", "00")
    tasks += _stage_tasks("mpas00", "00", first_dependencies=["jedi00_gate"])
    tasks += _stage_tasks("obs06", "06", first_dependencies=["jedi00_gate"], obs=True)
    tasks += _stage_tasks(
        "jedi06",
        "06",
        first_dependencies=["mpas00_gate", "obs06_gate"],
    )
    tasks += _stage_tasks("mpas06", "06", first_dependencies=["jedi06_gate"])
    tasks += _stage_tasks("obs12", "12", first_dependencies=["jedi06_gate"], obs=True)
    tasks += _stage_tasks(
        "jedi12",
        "12",
        first_dependencies=["mpas06_gate", "obs12_gate"],
    )
    tasks += _stage_tasks("mpas12", "12", first_dependencies=["jedi12_gate"])
    tasks += _stage_tasks("obs18", "18", first_dependencies=["jedi12_gate"], obs=True)
    tasks += _stage_tasks(
        "jedi18",
        "18",
        first_dependencies=["mpas12_gate", "obs18_gate"],
    )
    return {
        "workflow": {"name": "monan_jedi_corrected_replay_20180415_00z_18z"},
        "tasks": tasks,
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }


def test_published_monan_jedi_50_task_shape_groups_into_four_synoptic_cycles(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        "workflow: {name: monan_jedi_corrected_replay_20180415_00z_18z}\n",
        encoding="utf-8",
    )
    config = _published_replay_shape(workflow)

    snapshot = load_monitor_snapshot(config, workflow, tmp_path / ".simpleworkflow")

    assert snapshot.total_tasks == 50
    assert [cycle.cycle_id for cycle in snapshot.cycles] == [
        "2018041500",
        "2018041506",
        "2018041512",
        "2018041518",
    ]
    assert [len(cycle.tasks) for cycle in snapshot.cycles] == [10, 15, 15, 10]
    assert snapshot.cycles[0].tasks[0].name == "jedi00_prepare"
    assert snapshot.cycles[-1].tasks[-1].name == "jedi18_gate"
    assert snapshot.tasks == ()

    grouped = {
        cycle.cycle_id: {task.name for task in cycle.tasks}
        for cycle in snapshot.cycles
    }
    assert {"jedi00_gate", "mpas00_gate"} <= grouped["2018041500"]
    assert {"obs06_gate", "jedi06_gate", "mpas06_gate"} <= grouped["2018041506"]
    assert {"obs12_gate", "jedi12_gate", "mpas12_gate"} <= grouped["2018041512"]
    assert {"obs18_gate", "jedi18_gate"} <= grouped["2018041518"]

    # The cross-cycle joins remain the workflow's real dependencies; the
    # monitor does not rewrite them to manufacture the visual timeline.
    task_map = {task["name"]: task for task in config["tasks"]}
    assert task_map["jedi06_prepare"]["depends_on"] == ["mpas00_gate", "obs06_gate"]
    assert task_map["jedi12_prepare"]["depends_on"] == ["mpas06_gate", "obs12_gate"]
    assert task_map["jedi18_prepare"]["depends_on"] == ["mpas12_gate", "obs18_gate"]
