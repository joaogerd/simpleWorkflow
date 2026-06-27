from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .cycles import validate_cycle_mapping

SUPPORTED_EXECUTORS = {"local", "pbs"}
SUPPORTED_INPUT_FINGERPRINTS = {"metadata", "sha256"}
_GLOB_MARKERS = ("*", "?", "[")
_TASK_FIELDS = {
    "name",
    "argv",
    "depends_on",
    "enabled",
    "cwd",
    "env",
    "executor",
    "pbs",
    "inputs",
    "outputs",
    "input_fingerprint",
}
_PBS_FIELDS = {
    "queue",
    "project",
    "walltime",
    "select",
    "ncpus",
    "mpiprocs",
    "omp_threads",
    "job_name",
    "qsub",
    "block",
    "inherit_environment",
}
_WALLTIME = re.compile(r"^\d{1,3}:\d{2}:\d{2}$")


def _validate_string_list(value: Any, field: str, task_name: str) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError(
            f"Task '{task_name}' field '{field}' must be a non-empty list of strings."
        )
    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError(
            f"Task '{task_name}' field '{field}' must contain only non-empty strings."
        )


def _reject_unknown_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"{label} has unsupported field(s): {names}.")


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


def _validate_positive_integer(value: Any, field: str, task_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"Task '{task_name}' field 'pbs.{field}' must be a positive integer.")


def _validate_pbs(task: dict[str, Any], task_name: str) -> None:
    pbs = task.get("pbs")
    if task.get("executor", "local") == "pbs" and pbs is None:
        raise ValueError(f"Task '{task_name}' executor 'pbs' requires a 'pbs' mapping.")
    if pbs is None:
        return
    if task.get("executor", "local") != "pbs":
        raise ValueError(f"Task '{task_name}' field 'pbs' requires executor 'pbs'.")
    if not isinstance(pbs, dict):
        raise ValueError(f"Task '{task_name}' field 'pbs' must be a mapping.")
    _reject_unknown_keys(pbs, _PBS_FIELDS, f"Task '{task_name}' field 'pbs'")

    for field in ("queue", "project", "job_name", "qsub"):
        if field in pbs and (not isinstance(pbs[field], str) or not pbs[field]):
            raise ValueError(f"Task '{task_name}' field 'pbs.{field}' must be a non-empty string.")
    if "walltime" in pbs and (
        not isinstance(pbs["walltime"], str) or not _WALLTIME.fullmatch(pbs["walltime"])
    ):
        raise ValueError(
            f"Task '{task_name}' field 'pbs.walltime' must use HHH:MM:SS format."
        )
    for field in ("select", "ncpus", "mpiprocs", "omp_threads"):
        if field in pbs:
            _validate_positive_integer(pbs[field], field, task_name)
    for field in ("block", "inherit_environment"):
        if field in pbs and not isinstance(pbs[field], bool):
            raise ValueError(f"Task '{task_name}' field 'pbs.{field}' must be a boolean.")
    if pbs.get("block", True) is not True:
        raise ValueError(
            f"Task '{task_name}' field 'pbs.block' must be true; non-blocking PBS is unsupported."
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
    _reject_unknown_keys(task, _TASK_FIELDS, "Task")

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
    executor = task.get("executor", "local")
    if executor not in SUPPORTED_EXECUTORS:
        supported = ", ".join(sorted(SUPPORTED_EXECUTORS))
        raise ValueError(f"Task '{name}' requests unsupported executor {executor!r}; use: {supported}.")
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
    _validate_pbs(task, name)


def load_workflow(path: str | Path) -> dict[str, Any]:
    """Load and strictly validate one simpleWorkflow YAML configuration."""
    workflow_path = Path(path).resolve()
    if not workflow_path.exists():
        raise FileNotFoundError(f"Workflow file not found: {workflow_path}")

    with workflow_path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    if not isinstance(data, dict):
        raise ValueError("Workflow file must contain a YAML mapping at the top level.")

    _reject_unknown_keys(data, {"workflow", "context", "tasks", "cycle"}, "Workflow")
    data.setdefault("workflow", {})
    data.setdefault("context", {})
    data.setdefault("tasks", [])
    if not isinstance(data["workflow"], dict):
        raise ValueError("'workflow' must be a mapping.")
    _reject_unknown_keys(data["workflow"], {"name"}, "'workflow'")
    if "name" in data["workflow"] and (
        not isinstance(data["workflow"]["name"], str) or not data["workflow"]["name"]
    ):
        raise ValueError("'workflow.name' must be a non-empty string.")
    if not isinstance(data["context"], dict):
        raise ValueError("'context' must be a mapping.")
    if any(not isinstance(key, str) or not key for key in data["context"]):
        raise ValueError("'context' keys must be non-empty strings.")
    if not isinstance(data["tasks"], list):
        raise ValueError("'tasks' must be a list.")

    validate_cycle_mapping(data.get("cycle"))

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
