from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from .artifacts import ResolvedArtifacts, resolve_task_artifacts
from .executor import LocalExecutor
from .state import WorkflowState

INVALID_INPUT_EXIT_CODE = 2


def render_template(text: str, context: dict[str, Any]) -> str:
    """Render one string from the workflow context."""
    return text.format(**context)


def render_argv(argv: list[str], context: dict[str, Any]) -> list[str]:
    """Render task arguments while preserving their boundary semantics."""
    return [render_template(argument, context) for argument in argv]


class WorkflowEngine:
    """Small dependency-aware workflow engine for explicit program arguments."""

    def __init__(
        self,
        config: dict[str, Any],
        workdir: str | Path = ".simpleworkflow",
        force: bool = False,
        dry_run: bool = False,
    ):
        self.config = config
        self.workflow_name = config.get("workflow", {}).get("name", "workflow")
        self.context = config.get("context", {})
        self.tasks = config.get("tasks", [])
        self.force = force
        self.dry_run = dry_run
        self.source_dir = Path(
            config.get("__simpleworkflow__", {}).get("source_dir", Path.cwd())
        ).resolve()

        self.workdir = Path(workdir)
        self.log_dir = self.workdir / "logs" / self.workflow_name
        self.state = WorkflowState(self.workdir / "state.sqlite3")
        self.executor = LocalExecutor(self.log_dir)

    def plan(self) -> list[str]:
        """Return a dependency-resolved task order."""
        ordered: list[str] = []
        remaining = {task["name"]: task for task in self.tasks}

        while remaining:
            progressed = False
            for name, task in list(remaining.items()):
                dependencies = task.get("depends_on", []) or []
                if isinstance(dependencies, str):
                    dependencies = [dependencies]

                missing = [dep for dep in dependencies if dep not in remaining and dep not in ordered]
                if missing:
                    raise ValueError(
                        f"Task '{name}' depends on unknown task(s): {', '.join(missing)}"
                    )

                if all(dep in ordered for dep in dependencies):
                    ordered.append(name)
                    del remaining[name]
                    progressed = True

            if not progressed:
                unresolved = ", ".join(sorted(remaining))
                raise ValueError(f"Cyclic or unresolved task dependencies: {unresolved}")

        return ordered

    def _task_cwd(self, task: dict[str, Any]) -> Path | None:
        raw_cwd = task.get("cwd")
        if raw_cwd is None:
            return None
        path = Path(render_template(raw_cwd, self.context))
        return path if path.is_absolute() else self.source_dir / path

    def _task_env(self, task: dict[str, Any]) -> dict[str, str]:
        return {
            key: render_template(value, self.context)
            for key, value in task.get("env", {}).items()
        }

    def _task_artifacts(self, task: dict[str, Any]) -> ResolvedArtifacts:
        return resolve_task_artifacts(task, self.context, self.source_dir)

    @staticmethod
    def _format_missing_inputs(artifacts: ResolvedArtifacts) -> str:
        return ", ".join(str(path) for path in artifacts.missing_required_inputs())

    def run(self) -> int:
        """Execute pending workflow tasks in dependency order."""
        task_map = {task["name"]: task for task in self.tasks}
        exit_code = 0

        for task_name in self.plan():
            task = task_map[task_name]
            if task.get("enabled", True) is False:
                print(f"[SKIP] {task_name}: disabled")
                self.state.set_status(self.workflow_name, task_name, "skipped", 0)
                continue

            artifacts = self._task_artifacts(task)
            missing_inputs = artifacts.missing_required_inputs()
            if missing_inputs:
                message = self._format_missing_inputs(artifacts)
                print(f"[FAIL] {task_name}: missing required input(s): {message}")
                if not self.dry_run:
                    self.state.set_status(
                        self.workflow_name,
                        task_name,
                        "invalid-input",
                        INVALID_INPUT_EXIT_CODE,
                    )
                return INVALID_INPUT_EXIT_CODE

            if not self.force and self.state.get_status(self.workflow_name, task_name) == "success":
                print(f"[SKIP] {task_name}: already successful")
                continue

            argv = render_argv(task["argv"], self.context)
            cwd = self._task_cwd(task)
            env = self._task_env(task)
            rendered = shlex.join(argv)

            if self.dry_run:
                print(f"[PLAN] {task_name}: {rendered}")
                continue

            print(f"[RUN] {task_name}: {rendered}")
            self.state.set_status(self.workflow_name, task_name, "running", None)
            return_code = self.executor.run(task_name, argv, cwd=cwd, env=env)

            if return_code == 0:
                print(f"[OK] {task_name}")
                self.state.set_status(self.workflow_name, task_name, "success", return_code)
            else:
                print(f"[FAIL] {task_name}: return code {return_code}")
                self.state.set_status(self.workflow_name, task_name, "failed", return_code)
                exit_code = return_code
                break

        return exit_code

    def status(self) -> None:
        """Print current task status."""
        for task_name in self.plan():
            status = self.state.get_status(self.workflow_name, task_name) or "pending"
            print(f"{task_name}: {status}")

    def reset(self) -> None:
        """Reset all persisted state for this workflow."""
        self.state.reset(self.workflow_name)
