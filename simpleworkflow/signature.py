from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import ResolvedArtifacts

SIGNATURE_SCHEMA_VERSION = 4
SUPPORTED_FINGERPRINT_MODES = {"metadata", "sha256"}
_WORKFLOW_TOKEN = "$WORKFLOW"


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


def _portable_path(path: Path, workflow_root: Path | None) -> str:
    resolved = path.resolve(strict=False)
    if workflow_root is not None:
        root = workflow_root.resolve(strict=False)
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            pass
        else:
            return _WORKFLOW_TOKEN if not relative.parts else f"{_WORKFLOW_TOKEN}/{relative.as_posix()}"
    return str(resolved)


def _portable_text(value: str, workflow_root: Path | None) -> str:
    if workflow_root is None:
        return value
    root = str(workflow_root.resolve(strict=False))
    return value.replace(root, _WORKFLOW_TOKEN)


def _portable_value(value: Any, workflow_root: Path | None) -> Any:
    if isinstance(value, str):
        return _portable_text(value, workflow_root)
    if isinstance(value, list):
        return [_portable_value(item, workflow_root) for item in value]
    if isinstance(value, dict):
        return {key: _portable_value(item, workflow_root) for key, item in value.items()}
    return value


def fingerprint_artifact(
    path: Path,
    mode: str,
    *,
    workflow_root: Path | None = None,
) -> dict[str, Any]:
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
        "path": _portable_path(resolved, workflow_root),
        "kind": kind,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    if kind == "directory":
        children = []
        for child in sorted(item for item in resolved.rglob("*") if item.is_file()):
            child_stat = child.stat()
            entry: dict[str, Any] = {
                "path": str(child.relative_to(resolved)),
                "size": child_stat.st_size,
                "mtime_ns": child_stat.st_mtime_ns,
            }
            if mode == "sha256":
                entry["sha256"] = _sha256_file(child)
            children.append(entry)
        fingerprint["children"] = children
    elif mode == "sha256":
        if kind != "file":
            raise ValueError(f"Cannot calculate SHA-256 for input: {resolved}")
        fingerprint["sha256"] = _sha256_file(resolved)
    return fingerprint


def _fingerprint_paths(
    paths: tuple[Path, ...],
    mode: str,
    workflow_root: Path | None,
) -> list[dict[str, Any]]:
    return [
        fingerprint_artifact(path, mode, workflow_root=workflow_root)
        for path in paths
    ]


_SAFE_ENVIRONMENT = (
    "PATH",
    "LD_LIBRARY_PATH",
    "PYTHONPATH",
    "MODULEPATH",
    "LOADEDMODULES",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "MPI_HOME",
    "CONDA_PREFIX",
)


def _effective_environment(env: Mapping[str, str]) -> dict[str, str]:
    effective = os.environ.copy()
    effective.update(env)
    return effective


def _resolve_executable(
    requested: str,
    *,
    cwd: Path | None,
    environment: Mapping[str, str],
) -> str | None:
    if os.path.dirname(requested):
        candidate = Path(requested)
        if not candidate.is_absolute():
            candidate = (cwd if cwd is not None else Path.cwd()) / candidate
        resolved = candidate.resolve(strict=False)
        return str(resolved) if resolved.is_file() else None
    return shutil.which(requested, path=environment.get("PATH"))


def _runtime_identity(
    argv: list[str],
    *,
    cwd: Path | None,
    env: Mapping[str, str],
    workflow_root: Path | None,
) -> dict[str, Any]:
    environment = _effective_environment(env)
    executable = _resolve_executable(argv[0], cwd=cwd, environment=environment)
    identity: dict[str, Any] = {
        "requested": _portable_text(argv[0], workflow_root),
        "resolved": (
            _portable_path(Path(executable), workflow_root) if executable else None
        ),
    }
    if executable:
        path = Path(executable).resolve(strict=False)
        if path.is_file():
            stat = path.stat()
            identity.update({"size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    identity["effective_environment_sha256"] = {
        name: hashlib.sha256(
            _portable_text(environment[name], workflow_root).encode("utf-8")
        ).hexdigest()
        for name in _SAFE_ENVIRONMENT
        if name in environment
    }
    return identity


def compute_task_signature(
    *,
    workflow_path: Path | None,
    task_name: str,
    argv: list[str],
    cwd: Path | None,
    env: dict[str, str],
    artifacts: ResolvedArtifacts,
    fingerprint_mode: str = "metadata",
    executor: Mapping[str, Any] | None = None,
    format_version: int = 1,
) -> TaskSignature:
    """Compute a location-independent signature for a rendered task invocation.

    Paths inside the workflow root are represented with ``$WORKFLOW`` so moving the
    complete workflow root together with ``.simpleworkflow`` does not invalidate a
    successful task. The simpleWorkflow package version is deliberately excluded.
    """
    workflow_root = workflow_path.parent if workflow_path is not None else None
    payload: dict[str, Any] = {
        "signature_schema": SIGNATURE_SCHEMA_VERSION,
        "format_version": format_version,
        "task": {
            "name": task_name,
            "argv": [_portable_text(value, workflow_root) for value in argv],
            "cwd": _portable_path(cwd, workflow_root) if cwd is not None else None,
            "env": {
                key: _portable_text(value, workflow_root)
                for key, value in sorted(env.items())
            },
            "input_fingerprint": fingerprint_mode,
            "inputs": {
                "required": _fingerprint_paths(
                    artifacts.required_inputs, fingerprint_mode, workflow_root
                ),
                "optional": _fingerprint_paths(
                    artifacts.optional_inputs, fingerprint_mode, workflow_root
                ),
            },
            "outputs": [
                _portable_path(path, workflow_root) for path in artifacts.required_outputs
            ],
            "output_checks": [
                {
                    "path": _portable_path(check.path, workflow_root),
                    "kind": check.kind,
                    "nonempty": check.nonempty,
                    "min_size": check.min_size,
                }
                for check in artifacts.output_checks
            ],
            "executor": _portable_value(dict(executor or {"name": "local"}), workflow_root),
            "runtime": _runtime_identity(
                argv,
                cwd=cwd,
                env=env,
                workflow_root=workflow_root,
            ),
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return TaskSignature(
        value=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        payload=payload,
    )


def _legacy_root(payload: Mapping[str, Any]) -> Path | None:
    source = payload.get("workflow_source")
    return Path(source).parent if isinstance(source, str) and source else None


def _normalize_legacy_value(value: Any, root: Path | None) -> Any:
    if isinstance(value, str):
        return _portable_text(value, root)
    if isinstance(value, list):
        return [_normalize_legacy_value(item, root) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_legacy_value(item, root) for key, item in value.items()}
    return value


def _fingerprints_without_paths(value: Any) -> Any:
    if isinstance(value, list):
        return [_fingerprints_without_paths(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _fingerprints_without_paths(item)
            for key, item in value.items()
            if key != "path"
        }
    return value


def _schema_one_compatible(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    workflow_path: Path | None,
) -> bool:
    expected_workflow = previous.get("workflow_sha256")
    if not isinstance(expected_workflow, str) or workflow_path is None or not workflow_path.is_file():
        return False
    if _sha256_file(workflow_path) != expected_workflow:
        return False
    previous_task = previous.get("task")
    current_task = current.get("task")
    if not isinstance(previous_task, dict) or not isinstance(current_task, dict):
        return False
    if previous_task.get("name") != current_task.get("name"):
        return False
    if previous_task.get("env", {}) != current_task.get("env", {}):
        return False
    if previous_task.get("input_fingerprint", "metadata") != current_task.get(
        "input_fingerprint", "metadata"
    ):
        return False
    return _fingerprints_without_paths(previous_task.get("inputs", {})) == _fingerprints_without_paths(
        current_task.get("inputs", {})
    )


def _runtime_without_environment_hashes(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    return {
        key: item
        for key, item in value.items()
        if key not in {"effective_environment_sha256", "inherited_environment_sha256"}
    }


def legacy_signature_compatible(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any],
    *,
    workflow_path: Path | None,
) -> bool:
    """Return whether a legacy signature can be safely adopted by schema 4.

    Schema 1 (simpleWorkflow 0.2.x) is accepted only when the original complete
    workflow-file digest still matches and input fingerprints still match. Later
    schemas are compared structurally after making paths relative to the old workflow
    root. Runtime environment hashes are intentionally not used for legacy adoption.
    """
    if not isinstance(previous, Mapping):
        return False
    schema = previous.get("signature_schema")
    if schema == 1:
        return _schema_one_compatible(previous, current, workflow_path)
    if schema not in {2, 3}:
        return False

    previous_task = previous.get("task")
    current_task = current.get("task")
    if not isinstance(previous_task, dict) or not isinstance(current_task, dict):
        return False
    root = _legacy_root(previous)
    old = _normalize_legacy_value(previous_task, root)
    new = dict(current_task)

    keys = {
        "name",
        "argv",
        "cwd",
        "env",
        "input_fingerprint",
        "inputs",
        "outputs",
    }
    for key in keys:
        if old.get(key) != new.get(key):
            return False
    for optional_key in ("output_checks", "executor"):
        if optional_key in old and old.get(optional_key) != new.get(optional_key):
            return False
    if "runtime" in old:
        if _runtime_without_environment_hashes(old.get("runtime")) != _runtime_without_environment_hashes(
            new.get("runtime")
        ):
            return False
    return True
