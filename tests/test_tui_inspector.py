from __future__ import annotations

import asyncio
import json
from pathlib import Path

from textual.app import App, ComposeResult

from simpleworkflow.monitor import AttemptSnapshot, TaskSnapshot
from simpleworkflow.tui_inspector import TaskInspector
from simpleworkflow.tui_resources import InspectableResource


def _attempt(
    directory: Path,
    *,
    number: int,
    status: str,
    executor: str = "pbs",
    job_id: str | None = None,
    command: tuple[str, ...] = ("mpiexec", "jedi", "analysis.yaml"),
    cwd: str = "/case/work",
) -> AttemptSnapshot:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "stdout.log").write_text(f"stdout attempt {number}\n", encoding="utf-8")
    (directory / "stderr.log").write_text("", encoding="utf-8")
    (directory / "started.json").write_text(
        json.dumps(
            {
                "command": {
                    "argv": list(command),
                    "cwd": cwd,
                    "env": {},
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (directory / "metadata.json").write_text(
        json.dumps(
            {
                "command": {
                    "argv": list(command),
                    "cwd": cwd,
                    "env": {},
                },
                "execution": {
                    "executor": executor,
                    "job_id": job_id,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return AttemptSnapshot(
        run_id=f"run-{number}",
        task_name="analysis",
        cycle_id="2018041506",
        attempt=number,
        status=status,
        return_code=7 if status == "failed" else None,
        reason="boom" if status == "failed" else None,
        directory=directory,
        started_at=f"2018-04-15T06:{number:02d}:00Z",
        finished_at="2018-04-15T06:10:00Z" if status == "failed" else None,
    )


def _task(*attempts: AttemptSnapshot, status: str = "running") -> TaskSnapshot:
    return TaskSnapshot(
        name="analysis",
        status=status,
        cycle_id="2018041506",
        reason="boom" if status == "failed" else None,
        attempts=tuple(attempts),
    )


class InspectorTestApp(App[None]):
    def __init__(self, task: TaskSnapshot, config_task: dict[str, object]) -> None:
        super().__init__()
        self.task = task
        self.config_task = config_task
        self.opened: list[InspectableResource] = []
        self.copied: list[str] = []

    def compose(self) -> ComposeResult:
        yield TaskInspector(id="inspector")

    def on_mount(self) -> None:
        self.query_one(TaskInspector).set_task(self.task, self.config_task)

    def on_task_inspector_open_resource(self, event: TaskInspector.OpenResource) -> None:
        self.opened.append(event.resource)

    def on_task_inspector_copy_value(self, event: TaskInspector.CopyValue) -> None:
        self.copied.append(event.value)


def test_inspector_shows_only_operational_primary_fields_by_default(
    tmp_path: Path,
) -> None:
    attempt = _attempt(
        tmp_path / "attempt-001",
        number=1,
        status="running",
        job_id="363911.pbs-ha",
    )
    app = InspectorTestApp(
        _task(attempt),
        {
            "name": "analysis",
            "executor": "pbs",
            "depends_on": ["obs"],
            "outputs": {"required": ["/case/analysis.nc"]},
        },
    )

    async def scenario() -> None:
        async with app.run_test(size=(70, 24)) as pilot:
            await pilot.pause()
            inspector = app.query_one(TaskInspector)
            rendered = inspector.primary_text
            assert "363911.pbs-ha" in rendered
            assert "RUNNING" in rendered
            assert "analysis" in rendered
            assert "mpiexec jedi analysis.yaml" not in rendered
            assert "/case/work" not in rendered
            assert inspector.region.height < 20

    asyncio.run(scenario())


def test_inspector_switches_attempt_and_resources_together(tmp_path: Path) -> None:
    newest = _attempt(
        tmp_path / "attempt-002",
        number=2,
        status="running",
        job_id="job-2",
    )
    older = _attempt(
        tmp_path / "attempt-001",
        number=1,
        status="failed",
        job_id="job-1",
    )
    task = _task(newest, older)
    app = InspectorTestApp(task, {"name": "analysis", "executor": "pbs"})

    async def scenario() -> None:
        async with app.run_test(size=(80, 28)) as pilot:
            await pilot.pause()
            inspector = app.query_one(TaskInspector)
            assert inspector.selected_attempt is newest
            assert inspector.attempt_label == "Attempt 2 · 1/2"

            await pilot.click("#attempt-prev")
            await pilot.pause()
            assert inspector.selected_attempt is older
            assert inspector.attempt_label == "Attempt 1 · 2/2"
            assert any(
                "attempt-001" in str(resource.path)
                for resource in inspector.resources
            )

    asyncio.run(scenario())


def test_inspector_resource_rows_open_and_copy_paths(tmp_path: Path) -> None:
    attempt = _attempt(
        tmp_path / "attempt-001",
        number=1,
        status="running",
        job_id="job-1",
    )
    app = InspectorTestApp(
        _task(attempt),
        {"name": "analysis", "executor": "pbs"},
    )

    async def scenario() -> None:
        async with app.run_test(size=(80, 28)) as pilot:
            await pilot.pause()
            inspector = app.query_one(TaskInspector)
            assert inspector.focus_resource("stdout")
            table = app.query_one("#inspector-resources")
            table.focus()

            await pilot.press("c")
            await pilot.pause()
            assert app.copied[-1] == str(attempt.directory / "stdout.log")

            await pilot.press("enter")
            await pilot.pause()
            assert app.opened[-1].key == "stdout"

    asyncio.run(scenario())


def test_inspector_secondary_details_are_copyable_without_cluttering_primary(
    tmp_path: Path,
) -> None:
    attempt = _attempt(
        tmp_path / "attempt-001",
        number=1,
        status="running",
        job_id="job-1",
    )
    app = InspectorTestApp(
        _task(attempt),
        {
            "name": "analysis",
            "executor": "pbs",
            "depends_on": ["obs"],
            "outputs": {"required": ["/case/analysis.nc"]},
            "pbs": {"queue": "pesqmini", "ncpus": 64},
        },
    )

    async def scenario() -> None:
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            inspector = app.query_one(TaskInspector)
            assert "command" in inspector.detail_values
            assert inspector.detail_values["command"] == "mpiexec jedi analysis.yaml"
            assert inspector.detail_values["working directory"] == "/case/work"
            assert inspector.detail_values["run id"] == "run-1"

            assert inspector.focus_detail("working directory")
            app.query_one("#inspector-details-table").focus()
            await pilot.press("c")
            await pilot.pause()
            assert app.copied[-1] == "/case/work"

    asyncio.run(scenario())
