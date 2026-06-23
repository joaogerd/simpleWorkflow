from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

SUPPORTED_INPUT_FINGERPRINTS = {"metadata", "sha256"}
_GLOB_MARKERS = ("*", "?", "[")


def _validate_string_list(value: Any, field: str, task_name: str) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError(
            f"Task '{task_name}' field '{field}' must be a non-empty list of strings."
        )
    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError(
            f"Task '{task_name}' field '{field}' must contain only non-empty strings."
        )


def _validate_artifact_paths(
    value: Any, field: str, task_name: str, *, allow_globs: bool
) -> None:
    if not isinstance(value, list):
        raise ValueError(f"Task '{task_name}' field '{field}' must be a list of strings.")
    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError(
            f"Task '{task_name}' field '{field}' must contain only non-empty strings."
        )
    if not allow_globs and any(marker in item for item in value for marker in _GLOB_MARKERS):
        raise ValueError(
            f"Task '{task_name}' field '{field}' must contain explicit paths, not glob patterns."
        )


def _validate_artifact_group(value: Any, field: str, task_name: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"Task '{task_name}' field '{field}' must be a mapping.")

    allowed_keys = {"required", "optional"} if field == "inputs" else {"required"}
    unknown_keys = set(value) - allowed_keys
    if unknown_keys:
        unknown = ", ".join(sorted(unknown_keys))
        raise ValueError(f"Task '{task_name}' field '{field}' has unsupported keys: {unknown}.")

    if "required" in value:
        _validate_artifact_paths(
            value["required"], f"{field}.required", task_name, allow_globs=False
        )
    if field == "inputs" and "optional" in value:
        _validate_artifact_paths(
            value["optional"], f"{field}.optional", task_name, allow_globs=True
        )


def _validate_task(task: Any) -> None:
    if not isinstance(task, dict):
        raise ValueError("Each task must be a mapping.")

    name = task.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("Each task must define a non-empty string 'name'.")

    if "run" in task:
        raise ValueError(
            f"Task '{name}' uses unsupported field 'run'. "
            "Define 'argv' as a list of program arguments."
        )
    if "argv" not in task:
        raise ValueError(f"Task '{name}' must define 'argv'.")
    _validate_string_list(task["argv"], "argv", name)

    dependencies = task.get("depends_on")
    if dependencies is not None:
        if isinstance(dependencies, str):
            if not dependencies:
                raise ValueError(f"Task '{name}' dependency names cannot be empty.")
        else:
            _validate_string_list(dependencies, "depends_on", name)

    if "enabled" in task and not isinstance(task["enabled"], bool):
        raise ValueError(f"Task '{name}' field 'enabled' must be a boolean.")
    if "executor" in task and task["executor"] != "local":
        raise ValueError(f"Task '{name}' requests unsupported executor {task['executor']!r}.")
    if "cwd" in task and not isinstance(task["cwd"], str):
        raise ValueError(f"Task '{name}' field 'cwd' must be a string.")
    if "env" in task:
        environment = task["env"]
        if not isinstance(environment, dict):
            raise ValueError(f"Task '{name}' field 'env' must be a mapping.")
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in environment.items()
        ):
            raise ValueError(
                f"Task '{name}' field 'env' must map string names to string values."
            )

    if "inputs" in task:
        _validate_artifact_group(task["inputs"], "inputs", name)
    if "outputs" in task:
        _validate_artifact_group(task["outputs"], "outputs", name)

    fingerprint = task.get("input_fingerprint")
    if fingerprint is not None and fingerprint not in SUPPORTED_INPUT_FINGERPRINTS:
        supported = ", ".join(sorted(SUPPORTED_INPUT_FINGERPRINTS))
        raise ValueError(
            f"Task '{name}' field 'input_fingerprint' must be one of: {supported}."
        )


def load_workflow(path: str | Path) -> dict[str, Any]:
    """Load and validate a Python-only simpleWorkflow YAML file."""
    workflow_path = Path(path).resolve()
    if not workflow_path.exists():
        raise FileNotFoundError(f"Workflow file not found: {workflow_path}")

    with workflow_path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    if not isinstance(data, dict):
        raise ValueError("Workflow file must contain a YAML mapping at the top level.")

    data.setdefault("workflow", {})
    data.setdefault("context", {})
    data.setdefault("tasks", [])
    if not isinstance(data["workflow"], dict):
        raise ValueError("'workflow' must be a mapping.")
    if not isinstance(data["context"], dict):
        raise ValueError("'context' must be a mapping.")
    if not isinstance(data["tasks"], list):
        raise ValueError("'tasks' must be a list.")

    seen_names: set[str] = set()
    for task in data["tasks"]:
        _validate_task(task)
        name = task["name"]
        if name in seen_names:
            raise ValueError(f"Duplicated task name: {name}")
        seen_names.add(name)

    data["__simpleworkflow__"] = {
        "source_path": str(workflow_path),
        "source_dir": str(workflow_path.parent),
    }
    return data
