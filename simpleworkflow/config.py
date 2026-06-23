from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _validate_string_list(value: Any, field: str, task_name: str) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError(
            f"Task '{task_name}' field '{field}' must be a non-empty list of strings."
        )

    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError(
            f"Task '{task_name}' field '{field}' must contain only non-empty strings."
        )


def _validate_dependencies(value: Any, task_name: str) -> None:
    if isinstance(value, str):
        if not value:
            raise ValueError(f"Task '{task_name}' dependency names cannot be empty.")
        return

    _validate_string_list(value, "depends_on", task_name)


def _validate_task(task: Any) -> None:
    if not isinstance(task, dict):
        raise ValueError("Each task must be a mapping.")

    name = task.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("Each task must define a non-empty string 'name'.")

    if "run" in task:
        raise ValueError(
            f"Task '{name}' uses unsupported field 'run'. "
            "Define 'argv' as a list of program arguments; tasks never run through a shell."
        )

    if "argv" not in task:
        raise ValueError(f"Task '{name}' must define 'argv'.")
    _validate_string_list(task["argv"], "argv", name)

    if "depends_on" in task:
        _validate_dependencies(task["depends_on"], name)

    if "enabled" in task and not isinstance(task["enabled"], bool):
        raise ValueError(f"Task '{name}' field 'enabled' must be a boolean.")

    if "cwd" in task and not isinstance(task["cwd"], str):
        raise ValueError(f"Task '{name}' field 'cwd' must be a string.")

    if "env" in task:
        env = task["env"]
        if not isinstance(env, dict):
            raise ValueError(f"Task '{name}' field 'env' must be a mapping.")
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in env.items()):
            raise ValueError(
                f"Task '{name}' field 'env' must map string names to string values."
            )

    if "executor" in task and not isinstance(task["executor"], str):
        raise ValueError(f"Task '{name}' field 'executor' must be a string.")


def load_workflow(path: str | Path) -> dict[str, Any]:
    """Load and validate a simpleWorkflow YAML file."""
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
