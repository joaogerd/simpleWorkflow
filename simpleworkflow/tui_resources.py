"""Read-only discovery of files and resources associated with task attempts.

The TUI consumes these descriptors as presentation metadata. Nothing in this
module mutates workflow state, task provenance, scheduler state, or the files
being inspected.
"""

from __future__ import annotations

import json
import re
import shlex
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


def _attempt_provenance(attempt: AttemptSnapshot) -> dict[str, Any]:
    """Prefer final metadata, falling back to running-attempt provenance."""
    return _mapping(attempt.metadata) or _mapping(attempt.started_record)


def _read_json_mapping(path: Path, *, max_bytes: int = 1024 * 1024) -> dict[str, Any]:
    """Read one small JSON object without making the monitor fragile."""
    try:
        if not path.is_file() or path.stat().st_size > max_bytes:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
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



_OPERATIONAL_DETAIL_FIELDS = (
    ("job_id", "job id"),
    ("state", "submission state"),
    ("scheduler_last_state", "scheduler state"),
    ("submitted_at", "submitted"),
    ("scheduler_finished_at", "scheduler finished"),
    ("pbs_file", "PBS script"),
    ("run_dir", "run directory"),
)


def _looks_operational_manifest(value: dict[str, Any]) -> bool:
    return any(
        key in value
        for key in ("job_id", "pbs_file", "scheduler_last_state")
    )


def _resolved_manifest_path(value: Any, *, base: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve(strict=False)


def _pbs_redirect_paths(script: Path, *, run_dir: Path) -> tuple[Path | None, Path | None]:
    """Conservatively extract simple stdout/stderr redirections from a PBS script."""
    try:
        lines = script.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None, None

    stdout: Path | None = None
    stderr: Path | None = None
    for line in lines:
        try:
            tokens = shlex.split(line, posix=True)
        except ValueError:
            continue
        for marker, target_name in ((">", "stdout"), ("2>", "stderr")):
            try:
                index = tokens.index(marker)
            except ValueError:
                continue
            if index + 1 >= len(tokens):
                continue
            path = _resolved_manifest_path(tokens[index + 1], base=run_dir)
            if target_name == "stdout":
                stdout = path
            else:
                stderr = path
    return stdout, stderr


def _structured_output_resources(
    output: Path,
) -> tuple[InspectableResource, ...]:
    """Discover resources described by one declared operational JSON output."""
    if output.suffix.casefold() != ".json":
        return ()
    manifest = _read_json_mapping(output)
    if not _looks_operational_manifest(manifest):
        return ()

    run_dir = _resolved_manifest_path(manifest.get("run_dir"), base=output.parent)
    base = run_dir or output.parent
    resources: list[InspectableResource] = []
    seen: set[Path] = set()

    pbs_file = _resolved_manifest_path(manifest.get("pbs_file"), base=base)
    if pbs_file is not None:
        _append_unique(
            resources,
            seen,
            _resource(
                "pbs_script",
                "PBS script",
                pbs_file,
                "pbs-script",
                origin="artifact",
            ),
        )

    for key, label, resource_key in (
        ("job_stdout", "PBS stdout", "pbs_stdout"),
        ("stdout", "PBS stdout", "pbs_stdout"),
        ("job_stderr", "PBS stderr", "pbs_stderr"),
        ("stderr", "PBS stderr", "pbs_stderr"),
    ):
        path = _resolved_manifest_path(manifest.get(key), base=base)
        if path is not None:
            _append_unique(
                resources,
                seen,
                _resource(
                    resource_key,
                    label,
                    path,
                    "log",
                    origin="artifact",
                    follow=True,
                ),
            )

    if pbs_file is not None:
        stdout, stderr = _pbs_redirect_paths(pbs_file, run_dir=base)
        if stdout is not None:
            _append_unique(
                resources,
                seen,
                _resource(
                    "pbs_stdout",
                    "PBS stdout",
                    stdout,
                    "log",
                    origin="artifact",
                    follow=True,
                ),
            )
        if stderr is not None:
            _append_unique(
                resources,
                seen,
                _resource(
                    "pbs_stderr",
                    "PBS stderr",
                    stderr,
                    "log",
                    origin="artifact",
                    follow=True,
                ),
            )

    return tuple(resources)


def discover_structured_artifact_details(
    attempt: AttemptSnapshot,
) -> dict[str, str]:
    """Promote small scheduler/submission facts from declared JSON outputs."""
    provenance = _attempt_provenance(attempt)
    details: dict[str, str] = {}
    for kind, _label, output in _artifact_paths(provenance):
        if kind != "output" or output.suffix.casefold() != ".json":
            continue
        manifest = _read_json_mapping(output)
        if not _looks_operational_manifest(manifest):
            continue
        for key, label in _OPERATIONAL_DETAIL_FIELDS:
            value = manifest.get(key)
            if value is not None and label not in details:
                details[label] = str(value)
    return details


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

    provenance = _attempt_provenance(attempt)
    artifact_index = {"input": 0, "output": 0}
    output_paths: list[Path] = []
    for kind, label, path in _artifact_paths(provenance):
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
        if kind == "output":
            output_paths.append(path)

    for output in output_paths:
        for resource in _structured_output_resources(output):
            _append_unique(resources, seen, resource)

    return tuple(resources)


_PATH_TOKEN = re.compile(r"""(?P<path>(?:/|\./|\.\./)[^\s<>"'\x60]+)""")
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
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True
