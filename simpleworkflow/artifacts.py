from __future__ import annotations

import glob
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResolvedArtifacts:
    """Rendered, absolute artifact paths for one task."""

    required_inputs: tuple[Path, ...] = ()
    optional_inputs: tuple[Path, ...] = ()
    required_outputs: tuple[Path, ...] = ()
    output_checks: tuple[OutputCheck, ...] = ()

    def missing_required_inputs(self) -> tuple[Path, ...]:
        """Return required inputs that do not exist at preflight time."""
        return tuple(path for path in self.required_inputs if not path.exists())

    def missing_required_outputs(self) -> tuple[Path, ...]:
        """Return required outputs that do not exist after a task completes."""
        return tuple(path for path in self.required_outputs if not path.exists())

    def invalid_outputs(self) -> tuple[str, ...]:
        problems: list[str] = []
        for check in self.output_checks:
            path = check.path
            if not path.exists():
                problems.append(f"{path}: does not exist")
                continue
            if check.kind == "file" and not path.is_file():
                problems.append(f"{path}: expected a file")
            elif check.kind == "directory" and not path.is_dir():
                problems.append(f"{path}: expected a directory")
            if check.nonempty:
                if path.is_file() and path.stat().st_size == 0:
                    problems.append(f"{path}: file is empty")
                elif path.is_dir() and not any(path.iterdir()):
                    problems.append(f"{path}: directory is empty")
            if check.min_size is not None and path.is_file() and path.stat().st_size < check.min_size:
                problems.append(f"{path}: size is below {check.min_size} bytes")
        return tuple(problems)


@dataclass(frozen=True)
class OutputCheck:
    path: Path
    kind: str = "any"
    nonempty: bool = False
    min_size: int | None = None


def _render_path(value: str, context: dict[str, Any], source_dir: Path) -> Path:
    rendered = Path(value.format(**context))
    path = rendered if rendered.is_absolute() else source_dir / rendered
    return path.resolve(strict=False)


def _deduplicate(paths: list[Path]) -> tuple[Path, ...]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return tuple(unique)


def _resolve_optional_paths(
    patterns: list[str], context: dict[str, Any], source_dir: Path
) -> tuple[Path, ...]:
    matches: list[Path] = []
    for pattern in patterns:
        rendered = pattern.format(**context)
        candidate = Path(rendered)
        full_pattern = candidate if candidate.is_absolute() else source_dir / candidate
        matches.extend(
            Path(match).resolve(strict=False)
            for match in sorted(glob.glob(str(full_pattern)))
        )
    return _deduplicate(matches)


def resolve_task_artifacts(
    task: dict[str, Any], context: dict[str, Any], source_dir: Path
) -> ResolvedArtifacts:
    """Render task artifacts and resolve relative paths from the workflow file."""
    inputs = task.get("inputs", {})
    outputs = task.get("outputs", {})

    required_inputs = tuple(
        _render_path(value, context, source_dir)
        for value in inputs.get("required", [])
    )
    optional_inputs = _resolve_optional_paths(
        inputs.get("optional", []), context, source_dir
    )
    required_outputs = tuple(
        _render_path(value, context, source_dir)
        for value in outputs.get("required", [])
    )
    output_checks = tuple(
        OutputCheck(
            path=_render_path(check["path"], context, source_dir),
            kind=check.get("kind", "any"),
            nonempty=check.get("nonempty", False),
            min_size=check.get("min_size"),
        )
        for check in outputs.get("checks", [])
    )
    return ResolvedArtifacts(
        required_inputs=required_inputs,
        optional_inputs=optional_inputs,
        required_outputs=required_outputs,
        output_checks=output_checks,
    )
