from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _validate_argv(value: Any, task_name: str) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError(f"Task '{task_name}' must define a non-empty 'argv' list.")
    if not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"Task '{task_name}' field 'argv' must contain non-empty strings.")


def load_workflow(path: str | Path) -> dict[str, Any]:
    """Load and validate a workflow definition."""
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
        if not isinstance(task, dict):
            raise ValueError("Each task must be a mapping.")

        name = task.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("Each task must define a non-empty string 'name'.")
        if name in seen_names:
            raise ValueError(f"Duplicated task name: {name}")
        seen_names.add(name)

        if "run" in task:
            raise ValueError(
                f"Task '{name}' uses unsupported field 'run'; use 'argv' instead."
            )
        _validate_argv(task.get("argv"), name)

        if "cwd" in task and not isinstance(task["cwd"], str):
            raise ValueError(f"Task '{name}' field 'cwd' must be a string.")
        if "env" in task:
            env = task["env"]
            if not isinstance(env, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in env.items()
            ):
                raise ValueError(
                    f"Task '{name}' field 'env' must map strings to strings."
                )

    data["__simpleworkflow__"] = {
        "source_path": str(workflow_path),
        "source_dir": str(workflow_path.parent),
    }
    return data
