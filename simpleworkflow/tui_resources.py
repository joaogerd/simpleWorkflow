"""Read-only discovery of files and resources associated with task attempts.

The TUI consumes these descriptors as presentation metadata. Nothing in this
module mutates workflow state, task provenance, scheduler state, or the files
being inspected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .monitor import AttemptSnapshot, TaskSnapshot


@dataclass(frozen=True)
class InspectableResource:
    """One file-like resource the operator can inspect from the TUI."""

    key: str
    label: str
    path: Path
    kind: str
    origin: str
    follow: bool = False

    @property
    def available(self) -> bool:
        try:
            return self.path.is_file()
        except OSError:
            return False


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalized(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _kind_for_path(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix == ".json":
        return "json"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    if suffix in {".sh", ".bash"}:
        return "shell"
    if suffix == ".py":
        return "python"
    if suffix in {".log", ".out", ".err"}:
        return "log"
    return "text"


def _resource(
    key: str,
    label: str,
    path: str | Path,
    kind: str,
    *,
    origin: str = "structured",
    follow: bool = False,
) -> InspectableResource:
    return InspectableResource(
        key=key,
        label=label,
        path=_normalized(path),
        kind=kind,
        origin=origin,
        follow=follow,
    )


def _append_unique(
    resources: list[InspectableResource],
    seen: set[Path],
    item: InspectableResource,
) -> None:
    if item.path in seen:
        return
    seen.add(item.path)
    resources.append(item)


def _artifact_paths(metadata: dict[str, Any]) -> Iterable[tuple[str, str, Path]]:
    artifacts = _mapping(metadata.get("artifacts"))
    inputs = _mapping(artifacts.get("inputs"))
    outputs = _mapping(artifacts.get("outputs"))

    for category in ("required", "optional"):
        raw = inputs.get(category)
        if isinstance(raw, list):
            for value in raw:
                if isinstance(value, str) and value:
                    yield ("input", f"{category} input", _normalized(value))

    required = outputs.get("required")
    if isinstance(required, list):
        for value in required:
            if isinstance(value, str) and value:
                yield ("output", "required output", _normalized(value))

    checks = outputs.get("checks")
    if isinstance(checks, list):
        for check in checks:
            if not isinstance(check, dict):
                continue
            value = check.get("path")
            if isinstance(value, str) and value:
                yield ("output", "checked output", _normalized(value))


def discover_attempt_resources(
    task: TaskSnapshot,
    attempt: AttemptSnapshot,
    config_task: dict[str, Any],
) -> tuple[InspectableResource, ...]:
    """Return structured, deduplicated resources for one persisted attempt.

    Persisted attempt provenance is authoritative. Configuration is accepted so
    callers have a stable interface for future presentation-only fallbacks, but
    unresolved YAML paths are deliberately not guessed here.
    """

    del task, config_task
    resources: list[InspectableResource] = []
    seen: set[Path] = set()

    for key, label, path in (
        ("stdout", "stdout", attempt.directory / "stdout.log"),
        ("stderr", "stderr", attempt.directory / "stderr.log"),
    ):
        _append_unique(
            resources,
            seen,
            _resource(key, label, path, "log", follow=True),
        )

    execution = attempt.execution
    executor = str(execution.get("executor") or attempt.executor or "")
    is_pbs = executor == "pbs"

    if is_pbs:
        pbs_stdout = execution.get("job_stdout") or attempt.directory / "pbs.stdout.log"
        pbs_stderr = execution.get("job_stderr") or attempt.directory / "pbs.stderr.log"
        _append_unique(
            resources,
            seen,
            _resource("pbs_stdout", "PBS stdout", pbs_stdout, "log", follow=True),
        )
        _append_unique(
            resources,
            seen,
            _resource("pbs_stderr", "PBS stderr", pbs_stderr, "log", follow=True),
        )

    _append_unique(
        resources,
        seen,
        _resource("started", "started.json", attempt.directory / "started.json", "json"),
    )
    _append_unique(
        resources,
        seen,
        _resource("metadata", "metadata.json", attempt.directory / "metadata.json", "json"),
    )

    scheduler_path = attempt.directory / "scheduler.json"
    if is_pbs or scheduler_path.is_file():
        _append_unique(
            resources,
            seen,
            _resource("scheduler", "scheduler.json", scheduler_path, "json"),
        )

    script_value = execution.get("script")
    script_path = _normalized(script_value) if script_value else attempt.directory / "job.pbs"
    if is_pbs or script_path.is_file():
        _append_unique(
            resources,
            seen,
            _resource("pbs_script", "job.pbs", script_path, "pbs-script"),
        )

    metadata = _mapping(attempt.metadata)
    artifact_index = {"input": 0, "output": 0}
    for kind, label, path in _artifact_paths(metadata):
        index = artifact_index[kind]
        artifact_index[kind] += 1
        _append_unique(
            resources,
            seen,
            _resource(
                f"{kind}:{index}",
                f"{label}: {path.name}",
                path,
                kind,
            ),
        )

    return tuple(resources)


_PATH_TOKEN = re.compile(r"""(?P<path>(?:/|\\./|\\.\\./)[^\\s<>"'\\x60]+)""")
_TRAILING_PATH_PUNCTUATION = ".,;:!?)]}"


def discover_related_files(
    text: str,
    *,
    cwd: str | Path | None,
    attempt_dir: str | Path,
    known_paths: Iterable[Path] = (),
) -> tuple[InspectableResource, ...]:
    """Discover only existing regular files from conservative path tokens.

    Absolute paths are accepted directly. Relative paths must explicitly start
    with ./ or ../ and are resolved against the known task cwd (or the attempt
    directory when cwd is unavailable). Bare relative names are not linkified
    because they are too ambiguous in scientific logs.
    """

    attempt_base = _normalized(attempt_dir)
    cwd_base = _normalized(cwd) if cwd is not None else attempt_base
    known = {_normalized(path) for path in known_paths}
    seen = set(known)
    resources: list[InspectableResource] = []

    for match in _PATH_TOKEN.finditer(text):
        raw = match.group("path").rstrip(_TRAILING_PATH_PUNCTUATION)
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if candidate.is_absolute():
            path = candidate.resolve(strict=False)
        elif raw.startswith(("./", "../")):
            path = (cwd_base / candidate).resolve(strict=False)
        else:
            continue
        if path in seen:
            continue
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        seen.add(path)
        resources.append(
            InspectableResource(
                key=f"related:{len(resources)}",
                label=path.name or str(path),
                path=path,
                kind=_kind_for_path(path),
                origin="log",
                follow=False,
            )
        )

    return tuple(resources)


def is_probably_text(path: Path, *, sample_size: int = 8192) -> bool:
    """Return whether a bounded probe looks like UTF-8 text."""

    try:
        with path.open("rb") as stream:
            sample = stream.read(sample_size)
    except OSError:
        return False
    if b"\\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True
