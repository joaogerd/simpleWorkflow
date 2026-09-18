from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import TextArea
from textual.widgets.text_area import Selection

from simpleworkflow.tui_resources import InspectableResource
from simpleworkflow.tui_viewer import TextFileViewer


def _resource(path: Path, *, follow: bool = False) -> InspectableResource:
    return InspectableResource(
        key="stdout",
        label="stdout",
        path=path,
        kind="log",
        origin="structured",
        follow=follow,
    )


class ViewerTestApp(App[None]):
    def __init__(self, resource: InspectableResource) -> None:
        super().__init__()
        self.resource = resource
        self.copied: list[str] = []

    def compose(self) -> ComposeResult:
        yield TextFileViewer(id="viewer")

    def on_mount(self) -> None:
        self.query_one(TextFileViewer).open_resource(self.resource)

    def copy_to_clipboard(self, text: str) -> None:
        self.copied.append(text)


def test_viewer_loads_text_and_survives_file_disappearance(tmp_path: Path) -> None:
    path = tmp_path / "stdout.log"
    path.write_text("one\ntwo\nthree\n", encoding="utf-8")
    app = ViewerTestApp(_resource(path, follow=True))

    async def scenario() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            viewer = app.query_one(TextFileViewer)
            assert "two" in viewer.text
            path.unlink()
            viewer.reload(force=True)
            assert "no longer available" in viewer.status_message.lower()

    asyncio.run(scenario())


def test_viewer_search_moves_between_matches(tmp_path: Path) -> None:
    path = tmp_path / "log.txt"
    path.write_text("alpha\nneedle one\nbeta\nneedle two\n", encoding="utf-8")
    app = ViewerTestApp(_resource(path))

    async def scenario() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            viewer = app.query_one(TextFileViewer)
            assert viewer.search("needle") == 2
            assert viewer.current_match == 0
            assert app.query_one("#viewer-text", TextArea).cursor_location == (1, 0)
            viewer.next_match()
            assert viewer.current_match == 1
            assert app.query_one("#viewer-text", TextArea).cursor_location == (3, 0)
            viewer.previous_match()
            assert viewer.current_match == 0

    asyncio.run(scenario())


def test_viewer_follow_pause_and_resume_reads_growth(tmp_path: Path) -> None:
    path = tmp_path / "stdout.log"
    path.write_text("first\n", encoding="utf-8")
    app = ViewerTestApp(_resource(path, follow=True))

    async def scenario() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            viewer = app.query_one(TextFileViewer)
            viewer.set_follow(False)
            path.write_text("first\nsecond\n", encoding="utf-8")
            viewer.reload()
            assert "second" not in viewer.text
            viewer.set_follow(True)
            assert "second" in viewer.text

    asyncio.run(scenario())


def test_viewer_copies_path_current_line_and_selected_text(tmp_path: Path) -> None:
    path = tmp_path / "stdout.log"
    path.write_text("first line\nsecond line\n", encoding="utf-8")
    app = ViewerTestApp(_resource(path))

    async def scenario() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            viewer = app.query_one(TextFileViewer)
            area = app.query_one("#viewer-text", TextArea)

            viewer.copy_path()
            assert app.copied[-1] == str(path)

            area.move_cursor((1, 0))
            viewer.copy_context()
            assert app.copied[-1] == "second line"

            area.selection = Selection((0, 0), (0, 5))
            viewer.copy_context()
            assert app.copied[-1] == "first"

    asyncio.run(scenario())


def test_viewer_rejects_binary_content_without_crashing(tmp_path: Path) -> None:
    path = tmp_path / "field.nc"
    path.write_bytes(b"CDF\x00\x01\x02")
    app = ViewerTestApp(_resource(path))

    async def scenario() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            viewer = app.query_one(TextFileViewer)
            assert viewer.text == ""
            assert "binary" in viewer.status_message.lower()
            viewer.copy_path()
            assert app.copied[-1] == str(path)

    asyncio.run(scenario())


def test_viewer_bounds_large_files(tmp_path: Path) -> None:
    path = tmp_path / "large.log"
    path.write_text("A" * (3 * 1024 * 1024), encoding="utf-8")
    app = ViewerTestApp(_resource(path))

    async def scenario() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            viewer = app.query_one(TextFileViewer)
            assert len(viewer.text.encode("utf-8")) <= viewer.max_bytes + 256
            assert "truncated" in viewer.status_message.lower()

    asyncio.run(scenario())


def test_viewer_discovers_existing_related_files_from_visible_log(tmp_path: Path) -> None:
    attempt_dir = tmp_path / "attempt-001"
    attempt_dir.mkdir()
    cwd = tmp_path / "case"
    cwd.mkdir()
    manifest = cwd / "manifest.json"
    manifest.write_text('{"accepted": true}\n', encoding="utf-8")
    log = attempt_dir / "stdout.log"
    log.write_text(
        f"[OK] validation manifest accepted: {manifest}\n",
        encoding="utf-8",
    )
    app = ViewerTestApp(_resource(log, follow=True))

    async def scenario() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            viewer = app.query_one(TextFileViewer)
            viewer.open_resource(
                _resource(log, follow=True),
                cwd=cwd,
                attempt_dir=attempt_dir,
                known_paths=(log,),
            )
            await pilot.pause()

            assert [resource.path for resource in viewer.related_resources] == [manifest]
            assert viewer.select_related(manifest)
            table = app.query_one("#viewer-related")
            assert table.display
            assert table.cursor_row == 0

    asyncio.run(scenario())
