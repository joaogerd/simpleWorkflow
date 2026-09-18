"""Reusable read-only text and log viewer for the Textual frontend."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Static, TextArea

from .tui_resources import InspectableResource, discover_related_files, is_probably_text


@dataclass
class ViewerState:
    """Ephemeral presentation state for one opened resource."""

    resource: InspectableResource | None = None
    follow: bool = False
    query: str = ""
    matches: list[tuple[int, int]] = field(default_factory=list)
    current_match: int = -1
    signature: tuple[int, int] | None = None
    cwd: Path | None = None
    attempt_dir: Path | None = None
    known_paths: tuple[Path, ...] = ()


class TextFileViewer(Vertical):
    """Searchable, copyable, bounded read-only view of one text resource."""

    class OpenRelatedResource(Message):
        def __init__(self, resource: InspectableResource) -> None:
            super().__init__()
            self.resource = resource

    BINDINGS = [
        Binding("slash", "show_search", "Search"),
        Binding("n", "next_match", "Next match"),
        Binding("shift+n", "previous_match", "Previous match"),
        Binding("c", "copy_context", "Copy"),
        Binding("p", "copy_path", "Copy path"),
        Binding("r", "reload_file", "Reload"),
        Binding("f", "toggle_follow", "Follow"),
    ]

    DEFAULT_CSS = """
    TextFileViewer {
        height: 1fr;
        background: #0d0f13;
    }
    #viewer-toolbar {
        height: 2;
        padding: 0 1;
        border-bottom: solid #303744;
        background: #111318;
    }
    #viewer-title {
        width: 1fr;
        height: 1;
        color: #9fb9ff;
        content-align: left middle;
    }
    #viewer-copy-path, #viewer-reload, #viewer-follow {
        width: auto;
        min-width: 9;
        height: 1;
        min-height: 1;
        padding: 0 1;
        margin-left: 1;
        border: none;
        background: #111318;
        color: #8c93a1;
    }
    #viewer-follow.following {
        color: #65a30d;
        text-style: bold;
    }
    #viewer-search {
        display: none;
        height: 1;
        min-height: 1;
        border: none;
        padding: 0 1;
        background: #171a21;
    }
    #viewer-related {
        display: none;
        height: auto;
        max-height: 5;
        min-height: 0;
        margin: 0;
        border-bottom: solid #252b35;
    }
    #viewer-text {
        height: 1fr;
        border: none;
    }
    #viewer-status {
        height: 1;
        padding: 0 1;
        border-top: solid #252b35;
        color: #697180;
        background: #111318;
    }
    """

    def __init__(
        self,
        *,
        max_bytes: int = 2 * 1024 * 1024,
        refresh_seconds: float = 1.0,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.max_bytes = max(64 * 1024, int(max_bytes))
        self.refresh_seconds = max(0.5, float(refresh_seconds))
        self.state = ViewerState()
        self._text = ""
        self.status_message = ""
        self.related_resources: tuple[InspectableResource, ...] = ()
        self._related_paths: list[Path] = []

    @property
    def text(self) -> str:
        return self._text

    @property
    def current_match(self) -> int:
        return self.state.current_match

    def compose(self) -> ComposeResult:
        with Horizontal(id="viewer-toolbar"):
            yield Static("No file selected", id="viewer-title")
            yield Button("Copy path", id="viewer-copy-path")
            yield Button("Reload", id="viewer-reload")
            yield Button("FOLLOW ●", id="viewer-follow")
        yield Input(placeholder="Search…", id="viewer-search")
        yield DataTable(
            id="viewer-related",
            cursor_type="row",
            zebra_stripes=False,
        )
        yield TextArea("", read_only=True, soft_wrap=False, id="viewer-text")
        yield Static("", id="viewer-status")

    def on_mount(self) -> None:
        related = self.query_one("#viewer-related", DataTable)
        related.add_columns("Related file", "Origin")
        self.set_interval(self.refresh_seconds, self.reload)
        self._refresh_controls()
        self._refresh_related()

    def open_resource(
        self,
        resource: InspectableResource | None,
        *,
        cwd: str | Path | None = None,
        attempt_dir: str | Path | None = None,
        known_paths: tuple[Path, ...] = (),
    ) -> None:
        resolved_cwd = Path(cwd).resolve(strict=False) if cwd is not None else None
        resolved_attempt = (
            Path(attempt_dir).resolve(strict=False)
            if attempt_dir is not None
            else (resource.path.parent if resource is not None else None)
        )
        self.state = ViewerState(
            resource=resource,
            follow=bool(resource and resource.follow),
            cwd=resolved_cwd,
            attempt_dir=resolved_attempt,
            known_paths=tuple(Path(path).resolve(strict=False) for path in known_paths),
        )
        self._text = ""
        self.status_message = ""
        self._load_into_widget("")
        self.related_resources = ()
        self._refresh_controls()
        self._refresh_related()
        self.reload(force=True)

    def _load_into_widget(self, text: str) -> None:
        self._text = text
        try:
            self.query_one("#viewer-text", TextArea).load_text(text)
        except Exception:
            # The method can be called before mount by embedding components.
            return

    def _refresh_related(self) -> None:
        try:
            table = self.query_one("#viewer-related", DataTable)
        except Exception:
            return
        resource = self.state.resource
        if (
            resource is None
            or self.state.attempt_dir is None
            or not self._text
        ):
            self.related_resources = ()
        else:
            known = self.state.known_paths
            if resource.path not in known:
                known = (*known, resource.path)
            self.related_resources = discover_related_files(
                self._text,
                cwd=self.state.cwd,
                attempt_dir=self.state.attempt_dir,
                known_paths=known,
            )
        table.clear(columns=False)
        self._related_paths = []
        for related in self.related_resources:
            self._related_paths.append(related.path)
            table.add_row(
                related.label,
                related.origin,
                key=str(related.path),
            )
        table.display = bool(self.related_resources)

    def select_related(self, path: str | Path) -> bool:
        target = Path(path).resolve(strict=False)
        if target not in self._related_paths:
            return False
        table = self.query_one("#viewer-related", DataTable)
        table.move_cursor(row=self._related_paths.index(target))
        return True

    def _selected_related(self) -> InspectableResource | None:
        try:
            table = self.query_one("#viewer-related", DataTable)
        except Exception:
            return None
        row = table.cursor_row
        if row < 0 or row >= len(self.related_resources):
            return None
        return self.related_resources[row]

    def _set_status(self, message: str) -> None:
        self.status_message = message
        try:
            self.query_one("#viewer-status", Static).update(message)
        except Exception:
            return

    def _refresh_controls(self) -> None:
        resource = self.state.resource
        try:
            title = self.query_one("#viewer-title", Static)
            follow = self.query_one("#viewer-follow", Button)
            copy_path = self.query_one("#viewer-copy-path", Button)
            reload_button = self.query_one("#viewer-reload", Button)
        except Exception:
            return
        if resource is None:
            title.update("No file selected")
            follow.display = False
            copy_path.disabled = True
            reload_button.disabled = True
            return
        title.update(f"{resource.label}  {resource.path}")
        copy_path.disabled = False
        reload_button.disabled = False
        follow.display = resource.follow
        follow.label = "FOLLOW ●" if self.state.follow else "FOLLOW ‖"
        follow.set_class(self.state.follow, "following")

    def _read_bounded(self, path: Path, *, tail: bool) -> tuple[str, bool]:
        size = path.stat().st_size
        truncated = size > self.max_bytes
        with path.open("rb") as stream:
            if truncated and tail:
                stream.seek(max(0, size - self.max_bytes))
            raw = stream.read(self.max_bytes)
        return raw.decode("utf-8", errors="replace"), truncated

    def reload(self, *, force: bool = False) -> None:
        resource = self.state.resource
        if resource is None:
            self._set_status("No file selected.")
            return
        if not self.state.follow and not force and self.state.signature is not None:
            return
        path = resource.path
        try:
            stat = path.stat()
        except OSError:
            self.state.signature = None
            self._load_into_widget("")
            self._refresh_related()
            self._set_status(f"File no longer available: {path}")
            return
        if not path.is_file():
            self.state.signature = None
            self._load_into_widget("")
            self._set_status(f"File no longer available: {path}")
            return
        signature = (stat.st_size, stat.st_mtime_ns)
        if not force and signature == self.state.signature:
            return
        self.state.signature = signature
        if not is_probably_text(path):
            self._load_into_widget("")
            self._refresh_related()
            self._set_status(
                "Binary or unsupported text encoding; path can still be copied."
            )
            return
        try:
            text, truncated = self._read_bounded(path, tail=self.state.follow)
        except OSError:
            self._load_into_widget("")
            self._refresh_related()
            self._set_status(f"Unable to read: {path}")
            return
        self._load_into_widget(text)
        self._refresh_related()
        if self.state.query:
            self.search(self.state.query)
        location = "tail" if self.state.follow else "start"
        if truncated:
            self._set_status(
                f"truncated to {location} {self.max_bytes} bytes · {stat.st_size} bytes total"
            )
        else:
            self._set_status(f"{stat.st_size} bytes · {len(text.splitlines())} lines")
        if self.state.follow:
            try:
                area = self.query_one("#viewer-text", TextArea)
                line = max(0, len(text.splitlines()) - 1)
                area.move_cursor((line, 0))
                area.scroll_cursor_visible()
            except Exception:
                pass

    def set_follow(self, enabled: bool) -> None:
        resource = self.state.resource
        self.state.follow = bool(enabled and resource is not None and resource.follow)
        self._refresh_controls()
        if self.state.follow:
            self.state.signature = None
            self.reload(force=True)

    def search(self, query: str) -> int:
        self.state.query = query
        self.state.matches = []
        self.state.current_match = -1
        needle = query.casefold()
        if not needle:
            return 0
        haystack = self._text.casefold()
        start = 0
        while True:
            index = haystack.find(needle, start)
            if index < 0:
                break
            prefix = self._text[:index]
            row = prefix.count("\n")
            column = len(prefix.rsplit("\n", 1)[-1])
            self.state.matches.append((row, column))
            start = index + max(1, len(query))
        if self.state.matches:
            self.state.current_match = 0
            self._move_to_current_match()
        self._update_search_status()
        return len(self.state.matches)

    def _move_to_current_match(self) -> None:
        if not self.state.matches or self.state.current_match < 0:
            return
        location = self.state.matches[self.state.current_match]
        try:
            area = self.query_one("#viewer-text", TextArea)
            area.move_cursor(location)
            area.scroll_cursor_visible()
        except Exception:
            return

    def _update_search_status(self) -> None:
        if not self.state.query:
            return
        count = len(self.state.matches)
        if count:
            position = self.state.current_match + 1
            self._set_status(f"search {position}/{count} · {self.state.query}")
        else:
            self._set_status(f"search 0/0 · {self.state.query}")

    def next_match(self) -> None:
        if not self.state.matches:
            return
        self.state.current_match = (self.state.current_match + 1) % len(self.state.matches)
        self._move_to_current_match()
        self._update_search_status()

    def previous_match(self) -> None:
        if not self.state.matches:
            return
        self.state.current_match = (self.state.current_match - 1) % len(self.state.matches)
        self._move_to_current_match()
        self._update_search_status()

    def _copy(self, value: str) -> None:
        if not value:
            return
        try:
            self.app.copy_to_clipboard(value)
        except Exception:
            self._set_status("Clipboard is unavailable in this terminal.")

    def copy_path(self) -> None:
        if self.state.resource is not None:
            self._copy(str(self.state.resource.path))

    def copy_context(self) -> None:
        try:
            area = self.query_one("#viewer-text", TextArea)
        except Exception:
            return
        selected = area.selected_text
        if selected:
            self._copy(selected)
            return
        row = area.cursor_location[0]
        lines = self._text.splitlines()
        if 0 <= row < len(lines):
            self._copy(lines[row])

    def action_show_search(self) -> None:
        field = self.query_one("#viewer-search", Input)
        field.display = True
        field.focus()

    def action_next_match(self) -> None:
        self.next_match()

    def action_previous_match(self) -> None:
        self.previous_match()

    def action_copy_context(self) -> None:
        self.copy_context()

    def action_copy_path(self) -> None:
        self.copy_path()

    def action_reload_file(self) -> None:
        self.reload(force=True)

    def action_toggle_follow(self) -> None:
        self.set_follow(not self.state.follow)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "viewer-search":
            return
        self.search(event.value)
        event.input.display = False
        self.query_one("#viewer-text", TextArea).focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "viewer-related":
            return
        resource = self._selected_related()
        if resource is not None and resource.available:
            self.post_message(self.OpenRelatedResource(resource))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "viewer-copy-path":
            self.copy_path()
        elif button_id == "viewer-reload":
            self.reload(force=True)
        elif button_id == "viewer-follow":
            self.set_follow(not self.state.follow)


class TextViewerScreen(ModalScreen[None]):
    """Full-screen contextual wrapper around TextFileViewer."""

    BINDINGS = [
        Binding("escape", "close_viewer", "Back", priority=True),
    ]

    DEFAULT_CSS = """
    TextViewerScreen {
        align: center middle;
        background: #0d0f13;
    }
    TextViewerScreen > TextFileViewer {
        width: 100%;
        height: 100%;
    }
    """

    def __init__(
        self,
        resource: InspectableResource,
        *,
        refresh_seconds: float = 1.0,
        cwd: str | Path | None = None,
        attempt_dir: str | Path | None = None,
        known_paths: tuple[Path, ...] = (),
    ) -> None:
        super().__init__()
        self.resource = resource
        self.refresh_seconds = refresh_seconds
        self.cwd = cwd
        self.attempt_dir = attempt_dir
        self.known_paths = known_paths

    def compose(self) -> ComposeResult:
        yield TextFileViewer(
            refresh_seconds=self.refresh_seconds,
            id="context-viewer",
        )

    def on_mount(self) -> None:
        self.query_one(TextFileViewer).open_resource(
            self.resource,
            cwd=self.cwd,
            attempt_dir=self.attempt_dir,
            known_paths=self.known_paths,
        )
        self.query_one("#viewer-text", TextArea).focus()

    def on_text_file_viewer_open_related_resource(
        self,
        event: TextFileViewer.OpenRelatedResource,
    ) -> None:
        event.stop()
        self.query_one(TextFileViewer).open_resource(event.resource)
        self.query_one("#viewer-text", TextArea).focus()

    def action_close_viewer(self) -> None:
        self.dismiss(None)
