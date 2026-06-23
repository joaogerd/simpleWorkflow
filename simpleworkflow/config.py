from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


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
        if not isinstance(task, dict):
            raise ValueError("Each task must be a mapping.")
        if "name" not in task:
            raise ValueError("Each task must define 'name'.")
        if "run" not in task:
            raise ValueError(f"Task '{task['name']}' must define 'run'.")
        if task["name"] in seen_names:
            raise ValueError(f"Duplicated task name: {task['name']}")
        seen_names.add(task["name"])

    return data
