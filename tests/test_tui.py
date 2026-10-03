from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Static

from simpleworkflow.cli import main
from simpleworkflow.state import WorkflowState
from simpleworkflow.tui import WorkflowTui


def _config(workflow: Path) -> dict[str, object]:
    return {
        "workflow": {"name": "MONAN-JEDI M3"},
        "tasks": [
            {"name": "prepare", "argv": ["true"]},
            {"name": "obs2ioda", "argv": ["true"], "depends_on": ["prepare"]},
            {"name": "analysis", "argv": ["true"], "depends_on": ["obs2ioda"]},
            {"name": "forecast", "argv": ["true"], "depends_on": ["analysis"]},
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }


def _persist_campaign(workflow: Path, workdir: Path) -> None:
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="MONAN-JEDI M3",
        source_path=workflow,
    )
    for cycle_id, cycle_time in (
        ("2018041500", "2018-04-15T00:00:00Z"),
        ("2018041506", "2018-04-15T06:00:00Z"),
        ("2018041512", "2018-04-15T12:00:00Z"),
        ("2018041518", "2018-04-15T18:00:00Z"),
    ):
        state.ensure_cycle(cycle_id, cycle_time)
    for task in ("prepare", "obs2ioda", "analysis", "forecast"):
        state.set_status(task, "success", 0, cycle_id="2018041500")
    state.set_status("prepare", "success", 0, cycle_id="2018041506")
    state.set_status("obs2ioda", "success", 0, cycle_id="2018041506")
    state.set_status("analysis", "running", None, cycle_id="2018041506")
    state.close()


def test_monitor_mounts_with_approved_five_views_and_inspector(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: MONAN-JEDI M3\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    _persist_campaign(workflow, workdir)
    app = WorkflowTui(
        config=_config(workflow),
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            views = app.query_one("#views")
            assert views.active == "monitor"
            assert app.query_one("#task-tree") is not None
            assert app.query_one("#inspector") is not None
            assert app.query_one("#cycles-table") is not None
            assert app.query_one("#campaign-view") is not None
            assert app.query_one("#problems-table") is not None
            assert app.query_one("#log-viewer") is not None
            assert app.selected_cycle_id == "2018041506"
            assert app.selected_task == "analysis"

    asyncio.run(scenario())


def test_tab_cycles_through_exactly_five_operational_views(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: MONAN-JEDI M3\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    _persist_campaign(workflow, workdir)
    app = WorkflowTui(
        config=_config(workflow),
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(120, 35)) as pilot:
            views = app.query_one("#views")
            visited = [views.active]
            for _ in range(4):
                await pilot.press("ctrl+tab")
                await pilot.pause()
                visited.append(views.active)
            assert visited == ["monitor", "cycles", "campaign", "problems", "logs"]

    asyncio.run(scenario())


def test_narrow_terminal_keeps_monitor_usable(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: MONAN-JEDI M3\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    _persist_campaign(workflow, workdir)
    app = WorkflowTui(
        config=_config(workflow),
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(72, 26)) as pilot:
            await pilot.pause()
            assert app.query_one("#task-tree").display
            assert app.selected_task == "analysis"
            assert app.query_one("#shortcut-line") is not None

    asyncio.run(scenario())


def test_mixed_unrolled_workflow_shows_noncycle_tasks_in_workflow_section(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: mixed}\n", encoding="utf-8")
    config: dict[str, object] = {
        "workflow": {"name": "mixed"},
        "tasks": [
            {"name": "global_setup", "argv": ["true"]},
            {
                "name": "analysis00",
                "depends_on": ["global_setup"],
                "argv": ["tool", "run", "--cycle", "2018-04-15T00:00:00Z"],
            },
            {"name": "gate00", "depends_on": ["analysis00"], "argv": ["tool", "gate"]},
            {
                "name": "analysis06",
                "depends_on": ["gate00"],
                "argv": ["tool", "run", "--cycle", "2018-04-15T06:00:00Z"],
            },
            {
                "name": "global_finish",
                "depends_on": ["analysis00", "analysis06"],
                "argv": ["true"],
            },
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="mixed",
        source_path=workflow,
    )
    state.set_status("global_setup", "success", 0)
    state.set_status("analysis00", "success", 0)
    state.set_status("gate00", "success", 0)
    state.set_status("analysis06", "running", None)
    state.close()

    app = WorkflowTui(
        config=config,
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            assert (None, "global_setup") in app.task_nodes
            assert (None, "global_finish") in app.task_nodes
            global_node = app.task_nodes[(None, "global_setup")].parent
            assert global_node is not None
            assert "Workflow" in str(global_node.label)

            app.selected_cycle_id = None
            app.selected_task = "global_setup"
            app._refresh_inspector()
            inspector = app.query_one("#inspector")
            assert "workflow" in inspector.primary_text.lower()

    asyncio.run(scenario())


def test_representative_terminal_sizes_keep_all_views_operational(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: MONAN-JEDI M3\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    _persist_campaign(workflow, workdir)

    async def scenario(size: tuple[int, int]) -> None:
        app = WorkflowTui(
            config=_config(workflow),
            workflow_path=workflow,
            workdir=workdir,
            refresh_seconds=60.0,
        )
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            views = app.query_one("#views")
            assert views.active == "monitor"
            for expected in ("cycles", "campaign", "problems", "logs"):
                await pilot.press("ctrl+tab")
                await pilot.pause()
                assert views.active == expected
            await pilot.press("1")
            await pilot.pause()
            assert views.active == "monitor"
            assert app.query_one("#cycle-line") is not None
            assert app.query_one("#task-tree") is not None
            assert app.query_one("#inspector") is not None
            if size[0] < 86:
                # The interactive header added in 0.5.1 introduces additional
                # focusable controls. Exercise the responsive action directly so
                # this test validates the narrow layout independently of whichever
                # widget currently owns keyboard focus.
                app.action_inspect()
                await pilot.pause()
                assert app.query_one("#monitor-main").has_class("inspecting")
                app.action_escape_context()
                await pilot.pause()
                assert not app.query_one("#monitor-main").has_class("inspecting")

    for size in ((140, 45), (100, 32), (72, 26)):
        asyncio.run(scenario(size))


def test_representative_terminal_sizes_keep_monitor_reachable(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: MONAN-JEDI M3\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    _persist_campaign(workflow, workdir)

    async def scenario(size: tuple[int, int]) -> None:
        app = WorkflowTui(
            config=_config(workflow),
            workflow_path=workflow,
            workdir=workdir,
            refresh_seconds=60.0,
        )
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            tree = app.query_one("#task-tree")
            assert tree.display
            assert tree.region.height > 0
            assert app.selected_task == "analysis"

            body = app.query_one("#monitor-main")
            shortcut = str(app.query_one("#shortcut-line").render())
            if size[0] < 86:
                assert body.has_class("narrow")
                assert "↑↓ task" not in shortcut
                app.set_focus(tree)
                await pilot.pause()
                assert tree.has_focus
                await pilot.press("enter")
                await pilot.pause()
                inspector = app.query_one("#inspector")
                assert body.has_class("inspecting")
                assert inspector.display
                assert inspector.region.height > 0
                await pilot.press("escape")
                await pilot.pause()
                assert not body.has_class("inspecting")
            else:
                assert not body.has_class("narrow")
                matrix = app.query_one("#period-matrix")
                assert matrix.display
                assert matrix.region.height > 0

            views = app.query_one("#views")
            for key, expected in zip(("1", "2", "3", "4", "5"), (
                "monitor", "cycles", "campaign", "problems", "logs"
            )):
                await pilot.press(key)
                await pilot.pause()
                assert views.active == expected

    for size in ((140, 45), (100, 32), (80, 24), (72, 26)):
        asyncio.run(scenario(size))


def test_noncyclic_workflow_hides_cycle_specific_ui(tmp_path: Path) -> None:
    workflow = tmp_path / "hello.yaml"
    workflow.write_text("workflow: {name: hello_world}\n", encoding="utf-8")
    config: dict[str, object] = {
        "workflow": {"name": "hello_world"},
        "tasks": [
            {"name": "hello", "argv": ["echo", "hello"]},
            {"name": "finish", "argv": ["echo", "done"], "depends_on": ["hello"]},
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="hello_world",
        source_path=workflow,
    )
    state.set_status("hello", "success", 0)
    state.set_status("finish", "success", 0)
    state.close()

    app = WorkflowTui(
        config=config,
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(100, 28)) as pilot:
            await pilot.pause()
            assert app.cycle_mode is False
            assert list(app.query("#date-nav")) == []
            assert list(app.query("#cycle-line")) == []
            assert list(app.query("#cycles")) == []
            assert list(app.query("#campaign")) == []
            assert list(app.query("#period-title")) == []
            assert list(app.query("#period-matrix")) == []

            views = app.query_one("#views")
            visited = [views.active]
            await pilot.press("ctrl+tab")
            await pilot.pause()
            visited.append(views.active)
            await pilot.press("ctrl+tab")
            await pilot.pause()
            visited.append(views.active)
            assert visited == ["monitor", "problems", "logs"]

            app.action_select_view("cycles")
            assert views.active == "logs"
            app.action_select_view("monitor")
            assert views.active == "monitor"

    asyncio.run(scenario())


def test_low_height_terminal_uses_compact_layout_without_losing_core_panels(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: MONAN-JEDI M3\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    _persist_campaign(workflow, workdir)
    app = WorkflowTui(
        config=_config(workflow),
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(156, 30)) as pilot:
            await pilot.pause()
            body = app.query_one("#monitor-main")
            assert not body.has_class("narrow")
            assert app.query_one("#topbar").has_class("compact")
            assert app.query_one("#summary").has_class("compact")
            assert app.query_one("#inspector").has_class("compact")
            assert not app.query_one("#period-title").display
            assert not app.query_one("#period-matrix").display
            assert app.query_one("#task-tree").region.height > 0
            assert app.query_one("#inspector").region.height > 0

    asyncio.run(scenario())


def test_interactive_save_key_writes_svg_to_workdir(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: screenshot_demo}\ntasks: []\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    app = WorkflowTui(
        config={
            "workflow": {"name": "screenshot_demo"},
            "tasks": [],
            "__simpleworkflow__": {
                "source_path": str(workflow),
                "source_dir": str(workflow.parent),
            },
        },
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(100, 28)) as pilot:
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()

    asyncio.run(scenario())
    screenshots = list((workdir / "screenshots").glob("*-monitor.svg"))
    assert len(screenshots) == 1
    assert "<svg" in screenshots[0].read_text(encoding="utf-8")


def test_shortcut_footer_is_docked_to_bottom_on_low_height_terminal(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        "workflow: {name: footer_demo}\ntasks: []\n",
        encoding="utf-8",
    )
    app = WorkflowTui(
        config={
            "workflow": {"name": "footer_demo"},
            "tasks": [],
            "__simpleworkflow__": {
                "source_path": str(workflow),
                "source_dir": str(workflow.parent),
            },
        },
        workflow_path=workflow,
        workdir=tmp_path / ".simpleworkflow",
        refresh_seconds=60.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(100, 24)) as pilot:
            await pilot.pause()
            footer = app.query_one("#shortcut-line", Static)
            assert footer.display
            assert footer.region.height == 1
            assert footer.region.width == app.size.width
            assert footer.region.y + footer.region.height == app.size.height
            assert footer.content_region.height == 1
            assert footer.content_region.width > 0
            rendered = str(footer.render())
            assert "r Refresh" in rendered
            assert "q Exit" in rendered

    asyncio.run(scenario())



def test_wide_monitor_prioritizes_inspector_and_cycle_selector_is_local(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow:\n  name: MONAN-JEDI M3\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    _persist_campaign(workflow, workdir)
    app = WorkflowTui(
        config=_config(workflow),
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            left = app.query_one("#left")
            right = app.query_one("#right")
            assert left.region.width < right.region.width
            ratio = left.region.width / (left.region.width + right.region.width)
            assert 0.30 <= ratio <= 0.40
            cycle_line = app.query_one("#cycle-line")
            assert cycle_line.parent is not None
            assert cycle_line.parent.id == "monitor"

    asyncio.run(scenario())


def test_single_cycle_does_not_waste_space_on_period_matrix(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: one_cycle}\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="one_cycle",
        source_path=workflow,
    )
    state.ensure_cycle("2026100300", "2026-10-03T00:00:00Z")
    state.set_status("hello", "success", 0, cycle_id="2026100300")
    state.close()
    config: dict[str, object] = {
        "workflow": {"name": "one_cycle"},
        "tasks": [{"name": "hello", "argv": ["true"]}],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }
    app = WorkflowTui(
        config=config,
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            assert app.cycle_mode
            assert not app.query_one("#period-title").display
            assert not app.query_one("#period-matrix").display

    asyncio.run(scenario())


def test_problem_filter_searches_real_problem_fields(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: problems}\n", encoding="utf-8")
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="problems",
        source_path=workflow,
    )
    state.set_status("download", "failed", 7, reason="network unavailable")
    state.set_status("validate", "invalid-output", 0, reason="missing report")
    state.close()
    config: dict[str, object] = {
        "workflow": {"name": "problems"},
        "tasks": [
            {"name": "download", "argv": ["false"]},
            {"name": "validate", "argv": ["true"]},
        ],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }
    app = WorkflowTui(
        config=config,
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app.action_select_view("problems")
            app.action_show_filter()
            field = app.query_one("#problem-filter")
            assert field.display
            field.value = "invalid-output"
            await pilot.pause()
            assert app.problem_filter == "invalid-output"
            table = app.query_one("#problems-table")
            assert table.row_count == 1
            field.value = "does-not-exist"
            await pilot.pause()
            assert table.row_count == 1
            app.action_escape_context()
            await pilot.pause()
            assert app.problem_filter == ""
            assert table.row_count == 2

    asyncio.run(scenario())


def test_inspector_stdout_opens_logs_view_directly(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        """
format_version: 1
workflow:
  name: logs_direct
tasks:
  - name: hello
    argv: [python, -c, "print('hello from stdout')"]
""".lstrip(),
        encoding="utf-8",
    )
    assert main(["run", str(workflow), "--ui", "plain", "--color", "never"]) == 0

    config = {
        "workflow": {"name": "logs_direct"},
        "tasks": [{"name": "hello", "argv": ["python", "-c", "print('hello from stdout')"]}],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }
    app = WorkflowTui(
        config=config,
        workflow_path=workflow,
        workdir=tmp_path / ".simpleworkflow",
        refresh_seconds=60.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            inspector = app.query_one("#inspector")
            assert inspector.focus_resource("stdout")
            resources = inspector.query_one("#inspector-resources")
            resources.focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.query_one("#views").active == "logs"
            assert app.selected_log_key == "stdout"
            viewer = app.query_one("#log-viewer")
            assert viewer.state.resource is not None
            assert viewer.state.resource.key == "stdout"

    asyncio.run(scenario())



def test_tui_focuses_primary_content_on_open_and_view_change(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("workflow: {name: focus_demo}\n", encoding="utf-8")
    config: dict[str, object] = {
        "workflow": {"name": "focus_demo"},
        "tasks": [{"name": "hello", "argv": ["true"]}],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }
    workdir = tmp_path / ".simpleworkflow"
    state = WorkflowState(
        workdir / "state.sqlite3",
        workflow_name="focus_demo",
        source_path=workflow,
    )
    state.set_status("hello", "success", 0)
    state.close()

    app = WorkflowTui(
        config=config,
        workflow_path=workflow,
        workdir=workdir,
        refresh_seconds=60.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            assert app.focused is app.query_one("#task-tree")

            await pilot.press("ctrl+tab")
            await pilot.pause()
            assert app.query_one("#views").active == "problems"
            assert app.focused is app.query_one("#problems-table")

            await pilot.press("ctrl+tab")
            await pilot.pause()
            assert app.query_one("#views").active == "logs"
            assert app.focused is app.query_one("#log-viewer")

    asyncio.run(scenario())


def test_tab_switches_monitor_panels_without_mouse_click(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        """
format_version: 1
workflow:
  name: panel_demo
tasks:
  - name: hello
    argv: [python, -c, "print('hello')"]
""".lstrip(),
        encoding="utf-8",
    )
    assert main(["run", str(workflow), "--ui", "plain", "--color", "never"]) == 0

    config = {
        "workflow": {"name": "panel_demo"},
        "tasks": [{"name": "hello", "argv": ["python", "-c", "print('hello')"]}],
        "__simpleworkflow__": {
            "source_path": str(workflow),
            "source_dir": str(workflow.parent),
        },
    }
    app = WorkflowTui(
        config=config,
        workflow_path=workflow,
        workdir=tmp_path / ".simpleworkflow",
        refresh_seconds=60.0,
    )

    async def scenario() -> None:
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            tree = app.query_one("#task-tree")
            resources = app.query_one("#inspector-resources")
            assert app.focused is tree

            await pilot.press("tab")
            await pilot.pause()
            assert app.focused is resources

            await pilot.press("shift+tab")
            await pilot.pause()
            assert app.focused is tree

    asyncio.run(scenario())
