from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from .artifacts import ResolvedArtifacts
from .signature import TaskSignature

PROVENANCE_SCHEMA_VERSION = 1


def _rendered_paths(paths: tuple[Path, ...]) -> list[str]:
    return [str(path.resolve(strict=False)) for path in paths]


def build_attempt_metadata(
    *,
    argv: Sequence[str],
    cwd: Path | None,
    env: Mapping[str, str],
    artifacts: ResolvedArtifacts,
    signature: TaskSignature,
    status: str,
    return_code: int,
    process_return_code: int | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Build the stable provenance payload for one completed task attempt.

    The returned mapping includes only task-declared environment variables. It never
    captures the inherited process environment, which may contain credentials or
    machine-specific transient values.
    """
    metadata: dict[str, Any] = {
        "provenance_schema_version": PROVENANCE_SCHEMA_VERSION,
        "status": status,
        "return_code": return_code,
        "command": {
            "argv": list(argv),
            "cwd": str(cwd.resolve(strict=False)) if cwd is not None else None,
            "env": dict(sorted(env.items())),
        },
        "signature": {
            "value": signature.value,
            "payload": signature.payload,
        },
        "artifacts": {
            "inputs": {
                "required": _rendered_paths(artifacts.required_inputs),
                "optional": _rendered_paths(artifacts.optional_inputs),
            },
            "outputs": {
                "required": _rendered_paths(artifacts.required_outputs),
            },
        },
    }
    if process_return_code is not None:
        metadata["process_return_code"] = process_return_code
    if reason is not None:
        metadata["reason"] = reason
    return metadata
