from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from .artifacts import ResolvedArtifacts, resolve_task_artifacts
from .executor import LocalExecutor
from .provenance import build_attempt_metadata
from .runs import AttemptPaths, RunRecorder
from .signature import TaskSignature, compute_task_signature
from .state import WorkflowState

INVALID_INPUT_EXIT_CODE = 2
INVALID_OUTPUT_EXIT_CODE = 3


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

    def _workflow_path(self) -> Path | None:
        source_path = self.config.get("__simpleworkflow__", {}).get("source_path")
        return Path(source_path).resolve(strict=False) if source_path else None

    def _task_signature(
        self,
        task_name: str,
        task: dict[str, Any],
        argv: list[str],
        cwd: Path | None,
        env: dict[str, str],
        artifacts: ResolvedArtifacts,
    ) -> TaskSignature:
        return compute_task_signature(
            workflow_path=self._workflow_path(),
            task_name=task_name,
            argv=argv,
            cwd=cwd,
            env=env,
            artifacts=artifacts,
            fingerprint_mode=task.get("input_fingerprint", "metadata"),
        )

    @staticmethod
    def _format_missing_inputs(artifacts: ResolvedArtifacts) -> str:
        return ", ".join(str(path) for path in artifacts.missing_required_inputs())

    @staticmethod
    def _format_missing_outputs(artifacts: ResolvedArtifacts) -> str:
        return ", ".join(str(path) for path in artifacts.missing_required_outputs())

    @staticmethod
    def _output_failure_reason(artifacts: ResolvedArtifacts) -> str:
        return f"missing required output(s): {WorkflowEngine._format_missing_outputs(artifacts)}"

    @staticmethod
    def _process_failure_reason(return_code: int) -> str:
        return f"process exited with return code {return_code}"

    def _record_attempt(
        self,
        recorder: RunRecorder | None,
        attempt: AttemptPaths | None,
        *,
        argv: list[str],
        cwd: Path | None,
        env: dict[str, str],
        artifacts: ResolvedArtifacts,
        signature: TaskSignature,
        status: str,
        return_code: int,
        process_return_code: int | None = None,
        reason: str | None = None,
    ) -> None:
        if recorder is None or attempt is None:
            return
        recorder.write_metadata(
            attempt,
            build_attempt_metadata(
                argv=argv,
                cwd=cwd,
                env=env,
                artifacts=artifacts,
                signature=signature,
                status=status,
                return_code=return_code,
                process_return_code=process_return_code,
                reason=reason,
            ),
        )

    def run(self) -> int:
        """Execute pending workflow tasks in dependency order."""
        recorder: RunRecorder | None = None
        task_map = {task["name"]: task for task in self.tasks}
        planned_outputs_by_task: dict[str, set[Path]] = {}
        exit_code = 0

        for task_name in self.plan():
            task = task_map[task_name]
            if task.get("enabled", True) is False:
                print(f"[SKIP] {task_name}: disabled")
                self.state.set_status(self.workflow_name, task_name, "skipped", 0)
                continue

            artifacts = self._task_artifacts(task)
            dependencies = task.get("depends_on", []) or []
            if isinstance(dependencies, str):
                dependencies = [dependencies]

            planned_dependency_outputs: set[Path] = set()
            for dependency in dependencies:
                planned_dependency_outputs.update(
                    planned_outputs_by_task.get(dependency, set())
                )

            missing_inputs = artifacts.missing_required_inputs()
            if self.dry_run:
                missing_inputs = tuple(
                    path
                    for path in missing_inputs
                    if path not in planned_dependency_outputs
                )

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

            argv = render_argv(task["argv"], self.context)
            cwd = self._task_cwd(task)
            env = self._task_env(task)
            rendered = shlex.join(argv)

            if self.dry_run:
                print(f"[PLAN] {task_name}: {rendered}")
                planned_outputs_by_task[task_name] = (
                    planned_dependency_outputs | set(artifacts.required_outputs)
                )
                continue

            signature = self._task_signature(
                task_name, task, argv, cwd, env, artifacts
            )

            previous = self.state.get_task_state(self.workflow_name, task_name)
            if not self.force and previous and previous.status == "success":
                missing_outputs = artifacts.missing_required_outputs()
                if previous.signature == signature.value and not missing_outputs:
                    print(f"[SKIP] {task_name}: already successful")
                    continue
                if missing_outputs:
                    message = self._format_missing_outputs(artifacts)
                    print(f"[RERUN] {task_name}: required output(s) missing: {message}")
                else:
                    print(f"[RERUN] {task_name}: task signature changed")

            print(f"[RUN] {task_name}: {rendered}")
            if recorder is None:
                recorder = RunRecorder(self.workdir, self.workflow_name)
            attempt = recorder.begin_attempt(task_name)
            self.state.set_status(
                self.workflow_name, task_name, "running", None, signature.value
            )
            return_code = self.executor.run(
                task_name,
                argv,
                cwd=cwd,
                env=env,
                stdout_path=attempt.stdout_path if attempt is not None else None,
                stderr_path=attempt.stderr_path if attempt is not None else None,
            )

            if return_code == 0:
                missing_outputs = artifacts.missing_required_outputs()
                if missing_outputs:
                    reason = self._output_failure_reason(artifacts)
                    print(f"[FAIL] {task_name}: {reason}")
                    self.state.set_status(
                        self.workflow_name,
                        task_name,
                        "invalid-output",
                        INVALID_OUTPUT_EXIT_CODE,
                        signature.value,
                    )
                    self._record_attempt(
                        recorder,
                        attempt,
                        argv=argv,
                        cwd=cwd,
                        env=env,
                        artifacts=artifacts,
                        signature=signature,
                        status="invalid-output",
                        return_code=INVALID_OUTPUT_EXIT_CODE,
                        process_return_code=return_code,
                        reason=reason,
                    )
                    exit_code = INVALID_OUTPUT_EXIT_CODE
                    break
                print(f"[OK] {task_name}")
                self.state.set_status(
                    self.workflow_name, task_name, "success", return_code, signature.value
                )
                self._record_attempt(
                    recorder,
                    attempt,
                    argv=argv,
                    cwd=cwd,
                    env=env,
                    artifacts=artifacts,
                    signature=signature,
                    status="success",
                    return_code=return_code,
                    process_return_code=return_code,
                )
            else:
                reason = self._process_failure_reason(return_code)
                print(f"[FAIL] {task_name}: return code {return_code}")
                self.state.set_status(
                    self.workflow_name, task_name, "failed", return_code, signature.value
                )
                self._record_attempt(
                    recorder,
                    attempt,
                    argv=argv,
                    cwd=cwd,
                    env=env,
                    artifacts=artifacts,
                    signature=signature,
                    status="failed",
                    return_code=return_code,
                    process_return_code=return_code,
                    reason=reason,
                )
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
