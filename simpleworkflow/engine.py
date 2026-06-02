from __future__ import annotations

from pathlib import Path
from typing import Any

from .executor import LocalExecutor
from .state import WorkflowState


def render_template(text: str, context: dict[str, Any]) -> str:
    """Render a command string using Python format placeholders."""
    return text.format(**context)


class WorkflowEngine:
    """Small dependency-aware workflow engine."""

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

    def run(self) -> int:
        """Execute pending workflow tasks in dependency order."""
        task_map = {task["name"]: task for task in self.tasks}
        exit_code = 0

        for task_name in self.plan():
            task = task_map[task_name]
            enabled = task.get("enabled", True)

            if enabled is False:
                print(f"[SKIP] {task_name}: disabled")
                self.state.set_status(self.workflow_name, task_name, "skipped", 0)
                continue

            if not self.force and self.state.get_status(self.workflow_name, task_name) == "success":
                print(f"[SKIP] {task_name}: already successful")
                continue

            command = render_template(task["run"], self.context)

            if self.dry_run:
                print(f"[PLAN] {task_name}: {command}")
                continue

            print(f"[RUN] {task_name}: {command}")
            self.state.set_status(self.workflow_name, task_name, "running", None)
            return_code = self.executor.run(task_name, command)

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
