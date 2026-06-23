from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .artifacts import ResolvedArtifacts

SIGNATURE_SCHEMA_VERSION = 1
SUPPORTED_FINGERPRINT_MODES = {"metadata", "sha256"}


@dataclass(frozen=True)
class TaskSignature:
    """Canonical payload and SHA-256 digest for a rendered task invocation."""

    value: str
    payload: dict[str, Any]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path_kind(path: Path) -> str:
    if path.is_file():
        return "file"
    if path.is_dir():
        return "directory"
    return "other"


def fingerprint_artifact(path: Path, mode: str) -> dict[str, Any]:
    """Fingerprint one existing input artifact using metadata or SHA-256."""
    if mode not in SUPPORTED_FINGERPRINT_MODES:
        supported = ", ".join(sorted(SUPPORTED_FINGERPRINT_MODES))
        raise ValueError(f"Unsupported fingerprint mode {mode!r}; expected one of: {supported}.")

    resolved = path.resolve(strict=False)
    if not resolved.exists():
        raise FileNotFoundError(f"Cannot fingerprint missing artifact: {resolved}")

    stat = resolved.stat()
    kind = _path_kind(resolved)
    fingerprint: dict[str, Any] = {
        "path": str(resolved),
        "kind": kind,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    if mode == "sha256":
        if kind != "file":
            raise ValueError(
                f"SHA-256 fingerprinting currently requires a regular file: {resolved}"
            )
        fingerprint["sha256"] = _sha256_file(resolved)
    return fingerprint


def _fingerprint_paths(paths: tuple[Path, ...], mode: str) -> list[dict[str, Any]]:
    return [fingerprint_artifact(path, mode) for path in paths]


def _workflow_digest(workflow_path: Path | None) -> str | None:
    """Return the workflow file digest, or None for an in-memory configuration."""
    if workflow_path is None:
        return None
    resolved = workflow_path.resolve(strict=False)
    if not resolved.is_file():
        raise FileNotFoundError(f"Workflow file not found for signature: {resolved}")
    return _sha256_file(resolved)


def compute_task_signature(
    *,
    workflow_path: Path | None,
    task_name: str,
    argv: list[str],
    cwd: Path | None,
    env: dict[str, str],
    artifacts: ResolvedArtifacts,
    fingerprint_mode: str = "metadata",
) -> TaskSignature:
    """Compute a deterministic signature for a fully rendered task invocation.

    The signature deliberately includes only declared task environment values, never the
    inherited process environment. Optional input globs are represented by their resolved
    matches, so newly appearing files change the signature.
    """
    payload: dict[str, Any] = {
        "signature_schema": SIGNATURE_SCHEMA_VERSION,
        "simpleworkflow_version": __version__,
        "workflow_sha256": _workflow_digest(workflow_path),
        "task": {
            "name": task_name,
            "argv": list(argv),
            "cwd": str(cwd.resolve(strict=False)) if cwd is not None else None,
            "env": dict(sorted(env.items())),
            "input_fingerprint": fingerprint_mode,
            "inputs": {
                "required": _fingerprint_paths(artifacts.required_inputs, fingerprint_mode),
                "optional": _fingerprint_paths(artifacts.optional_inputs, fingerprint_mode),
            },
            "outputs": [
                str(path.resolve(strict=False)) for path in artifacts.required_outputs
            ],
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return TaskSignature(
        value=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        payload=payload,
    )
