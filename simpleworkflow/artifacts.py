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

    def missing_required_inputs(self) -> tuple[Path, ...]:
        """Return required inputs that do not exist at preflight time."""
        return tuple(path for path in self.required_inputs if not path.exists())


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
    return ResolvedArtifacts(
        required_inputs=required_inputs,
        optional_inputs=optional_inputs,
        required_outputs=required_outputs,
    )
