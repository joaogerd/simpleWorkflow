from __future__ import annotations

import shlex
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .artifacts import ResolvedArtifacts, resolve_task_artifacts
from .console import TerminalReporter, WorkflowReporter
from .executor import ExecutionResult, LocalExecutor, TaskExecutor
from .locking import WorkflowLock
from .pbs import PbsExecutor
from .provenance import build_attempt_metadata
from .runs import AttemptPaths, RunRecorder
from .signature import (
    SIGNATURE_SCHEMA_VERSION,
    TaskSignature,
    compute_task_signature,
    legacy_signature_compatible,
)
from .state import WorkflowState

INVALID_INPUT_EXIT_CODE = 2
INVALID_OUTPUT_EXIT_CODE = 3
BLOCKED_EXIT_CODE = 4


def render_template(text: str, context: dict[str, Any]) -> str:
    """Render one string from the workflow context with a useful error."""
    try:
        return text.format(**context)
    except KeyError as error:
        missing = error.args[0]
        raise ValueError(f"Unknown context placeholder {{{missing}}} in {text!r}.") from error
    except ValueError as error:
        raise ValueError(f"Invalid context template {text!r}: {error}") from error


def render_argv(argv: list[str], context: dict[str, Any]) -> list[str]:
    """Render task arguments while preserving their boundary semantics."""
    return [render_template(argument, context) for argument in argv]


def _render_value(value: Any, context: dict[str, Any]) -> Any:
    """Render strings recursively in a small executor configuration mapping."""
    if isinstance(value, str):
        return render_template(value, context)
    if isinstance(value, list):
        return [_render_value(item, context) for item in value]
    if isinstance(value, dict):
        return {key: _render_value(item, context) for key, item in value.items()}
    return value


class WorkflowEngine:
    """Small dependency-aware workflow engine for one logical workflow instance."""

    def __init__(
        self,
        config: dict[str, Any],
        workdir: str | Path | None = None,
        force: bool = False,
        dry_run: bool = False,
        reporter: WorkflowReporter | None = None,
        selected_tasks: set[str] | None = None,
        cycle_id: str | None = None,
        cycle_time: str | None = None,
    ) -> None:
        self.config = config
        self.workflow_name = config.get("workflow", {}).get("name", "workflow")
        self.context = config.get("context", {})
        self.tasks = config.get("tasks", [])
        self.force = force
        self.dry_run = dry_run
        self.reporter = reporter or TerminalReporter()
        self.selected_tasks = selected_tasks
        self.cycle_id = cycle_id
        self.cycle_time = cycle_time
        self.source_dir = Path(
            config.get("__simpleworkflow__", {}).get("source_dir", Path.cwd())
        ).resolve()
        source_path = config.get("__simpleworkflow__", {}).get("source_path")
        self.workdir = (
            Path(workdir).resolve(strict=False)
            if workdir is not None
            else (self.source_dir / ".simpleworkflow").resolve(strict=False)
        )
        self.log_dir = self.workdir / "logs"
        self.state = WorkflowState(
            self.workdir / "state.sqlite3",
            workflow_name=self.workflow_name,
            source_path=source_path,
        )
        self.state.ensure_cycle(self.cycle_id, self.cycle_time)
        self.executor: TaskExecutor = LocalExecutor(self.log_dir)

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

        if not self.selected_tasks:
            return ordered
        unknown = self.selected_tasks - set(ordered)
        if unknown:
            raise ValueError("Unknown selected task(s): " + ", ".join(sorted(unknown)))
        task_map = {task["name"]: task for task in self.tasks}
        required = set(self.selected_tasks)
        pending = list(self.selected_tasks)
        while pending:
            name = pending.pop()
            dependencies = task_map[name].get("depends_on", []) or []
            if isinstance(dependencies, str):
                dependencies = [dependencies]
            for dependency in dependencies:
                if dependency not in required:
                    required.add(dependency)
                    pending.append(dependency)
        return [name for name in ordered if name in required]

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

    def _task_timeout(self, task: dict[str, Any]) -> float | None:
        value = task.get("timeout")
        if value is None:
            return None
        rendered = render_template(value, self.context) if isinstance(value, str) else value
        try:
            timeout = float(rendered)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Task '{task['name']}' timeout must be a positive number.") from error
        if timeout <= 0:
            raise ValueError(f"Task '{task['name']}' timeout must be a positive number.")
        return timeout

    def _task_executor(self, task: dict[str, Any]) -> TaskExecutor:
        executor = task.get("executor", "local")
        if executor == "local":
            return self.executor
        if executor == "pbs":
            options = _render_value(task["pbs"], self.context)
            if not isinstance(options, Mapping):
                raise ValueError("Rendered PBS options must be a mapping.")
            return PbsExecutor(options)
        raise ValueError(f"Unsupported executor {executor!r}.")

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
            executor=(
                {"name": "pbs", "options": _render_value(task["pbs"], self.context)}
                if task.get("executor", "local") == "pbs"
                else {"name": "local", "timeout": self._task_timeout(task)}
            ),
            format_version=int(self.config.get("format_version", 1)),
        )

    @staticmethod
    def _format_missing_inputs(artifacts: ResolvedArtifacts) -> str:
        return ", ".join(str(path) for path in artifacts.missing_required_inputs())

    @staticmethod
    def _format_missing_outputs(artifacts: ResolvedArtifacts) -> str:
        return ", ".join(str(path) for path in artifacts.missing_required_outputs())

    @staticmethod
    def _output_failure_reason(artifacts: ResolvedArtifacts) -> str:
        if artifacts.missing_required_outputs():
            return f"missing required output(s): {WorkflowEngine._format_missing_outputs(artifacts)}"
        return "invalid output(s): " + "; ".join(artifacts.invalid_outputs())

    @staticmethod
    def _process_failure_reason(return_code: int) -> str:
        return f"process exited with return code {return_code}"

    @staticmethod
    def _normalize_execution_result(result: ExecutionResult | int) -> ExecutionResult:
        """Accept legacy integer test doubles while enforcing the backend contract."""
        if isinstance(result, ExecutionResult):
            return result
        if isinstance(result, int):
            return ExecutionResult(return_code=result)
        raise TypeError("Task executor must return ExecutionResult or an integer return code.")

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
        execution: Mapping[str, Any] | None = None,
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
                execution=execution,
                process_return_code=process_return_code,
                reason=reason,
            ),
        )
        self.state.record_attempt_finished(
            run_id=attempt.run_id,
            task=attempt.task_name,
            attempt=attempt.attempt,
            status=status,
            return_code=return_code,
            reason=reason,
        )

    def run(self) -> int:
        """Execute pending workflow tasks in dependency order."""
        with WorkflowLock(self.workdir, self.workflow_name):
            self.state.reconcile_running(cycle_id=self.cycle_id)
            uncertain = self.state.tasks_with_status("unknown", cycle_id=self.cycle_id)
            if uncertain:
                raise RuntimeError(
                    "não é seguro continuar; a atividade ainda não pôde ser confirmada para: "
                    + ", ".join(uncertain)
                    + ". Verifique o processo ou job antes de usar reset."
                )
            return self._run_locked()

    def _descendants(self, task_name: str) -> list[str]:
        descendants: list[str] = []
        pending = [task_name]
        while pending:
            parent = pending.pop(0)
            for task in self.tasks:
                dependencies = task.get("depends_on", []) or []
                if isinstance(dependencies, str):
                    dependencies = [dependencies]
                name = task["name"]
                if parent in dependencies and name not in descendants:
                    descendants.append(name)
                    pending.append(name)
        return descendants

    def _adopt_legacy_signature(
        self,
        task_name: str,
        previous: Any,
        current: TaskSignature,
    ) -> bool:
        if previous.signature == current.value:
            return True
        if not legacy_signature_compatible(
            previous.signature_payload,
            current.payload,
            workflow_path=self._workflow_path(),
        ):
            return False
        self.state.set_status(
            task_name,
            "success",
            previous.return_code,
            current.value,
            previous.reason or "assinatura legada validada e atualizada",
            previous.attempt_path,
            cycle_id=self.cycle_id,
            signature_schema=SIGNATURE_SCHEMA_VERSION,
            signature_payload=current.payload,
        )
        return True

    def _run_locked(self) -> int:
        """Run after acquiring the workflow lock and reconciling interrupted work."""
        recorder: RunRecorder | None = None
        task_map = {task["name"]: task for task in self.tasks}
        planned_outputs_by_task: dict[str, set[Path]] = {}
        executed_tasks: set[str] = set()
        exit_code = 0

        for task_name in self.plan():
            task = task_map[task_name]
            executor_name = str(task.get("executor", "local"))
            dependencies = task.get("depends_on", []) or []
            if isinstance(dependencies, str):
                dependencies = [dependencies]
            unavailable = [
                dependency
                for dependency in dependencies
                if self.state.get_status(dependency, cycle_id=self.cycle_id)
                in {
                    "skipped",
                    "blocked",
                    "failed",
                    "invalid-input",
                    "invalid-output",
                    "interrupted",
                    "unknown",
                }
            ]
            if unavailable:
                reason = "dependência indisponível: " + ", ".join(unavailable)
                self.reporter.event("fail", task_name, reason, executor=executor_name)
                self.state.set_status(
                    task_name,
                    "blocked",
                    BLOCKED_EXIT_CODE,
                    reason=reason,
                    cycle_id=self.cycle_id,
                )
                return BLOCKED_EXIT_CODE
            if task.get("enabled", True) is False:
                self.reporter.event("skip", task_name, "disabled", executor=executor_name)
                self.state.set_status(
                    task_name,
                    "skipped",
                    0,
                    cycle_id=self.cycle_id,
                )
                continue

            artifacts = self._task_artifacts(task)
            dependency_executed = any(
                dependency in executed_tasks for dependency in dependencies
            )

            planned_dependency_outputs: set[Path] = set()
            for dependency in dependencies:
                planned_dependency_outputs.update(
                    planned_outputs_by_task.get(dependency, set())
                )

            missing_inputs = artifacts.missing_required_inputs()
            if self.dry_run:
                missing_inputs = tuple(
                    path for path in missing_inputs if path not in planned_dependency_outputs
                )

            if missing_inputs:
                message = f"missing required input(s): {self._format_missing_inputs(artifacts)}"
                self.reporter.event("fail", task_name, message, executor=executor_name)
                if not self.dry_run:
                    self.state.set_status(
                        task_name,
                        "invalid-input",
                        INVALID_INPUT_EXIT_CODE,
                        cycle_id=self.cycle_id,
                    )
                return INVALID_INPUT_EXIT_CODE

            argv = render_argv(task["argv"], self.context)
            cwd = self._task_cwd(task)
            env = self._task_env(task)
            timeout = self._task_timeout(task)
            rendered = shlex.join(argv)

            if self.dry_run:
                self.reporter.event("plan", task_name, rendered, executor=executor_name)
                planned_outputs_by_task[task_name] = (
                    planned_dependency_outputs | set(artifacts.required_outputs)
                )
                continue

            signature = self._task_signature(task_name, task, argv, cwd, env, artifacts)
            task_executor = self._task_executor(task)

            previous = self.state.get_task_state(task_name, cycle_id=self.cycle_id)
            if not self.force and previous and previous.status == "success":
                missing_outputs = artifacts.missing_required_outputs()
                invalid_outputs = artifacts.invalid_outputs()
                signature_matches = self._adopt_legacy_signature(
                    task_name, previous, signature
                )
                if (
                    not dependency_executed
                    and signature_matches
                    and not missing_outputs
                    and not invalid_outputs
                ):
                    self.reporter.event(
                        "skip",
                        task_name,
                        "already successful",
                        executor=executor_name,
                    )
                    continue
                if dependency_executed:
                    self.reporter.event(
                        "rerun",
                        task_name,
                        "dependency executed again",
                        executor=executor_name,
                    )
                elif missing_outputs or invalid_outputs:
                    message = self._output_failure_reason(artifacts)
                    self.reporter.event("rerun", task_name, message, executor=executor_name)
                else:
                    self.reporter.event(
                        "rerun",
                        task_name,
                        "task signature changed",
                        executor=executor_name,
                    )

            descendants = self._descendants(task_name)
            if descendants:
                self.state.mark_tasks(
                    descendants,
                    "stale",
                    f"a dependência '{task_name}' será executada novamente",
                    cycle_id=self.cycle_id,
                )

            run_message = rendered
            if executor_name == "pbs":
                run_message = f"waiting for scheduler completion · {rendered}"
            self.reporter.event("run", task_name, run_message, executor=executor_name)
            if recorder is None:
                recorder = RunRecorder(
                    self.workdir,
                    self.workflow_name,
                    instance_id=self.state.instance_id,
                    cycle_id=self.cycle_id,
                    cycle_time=self.cycle_time,
                )
                recorder.write_workflow_snapshot(self.config)
                self.state.record_run(
                    recorder.run_id,
                    recorder.directory,
                    cycle_id=self.cycle_id,
                    cycle_time=self.cycle_time,
                )
            attempt = recorder.begin_attempt(task_name)
            recorder.write_started(
                attempt,
                {
                    "status": "running",
                    "command": {"argv": argv, "cwd": str(cwd) if cwd else None, "env": env},
                    "signature": signature.value,
                },
            )
            self.state.record_attempt_started(
                run_id=attempt.run_id,
                task=task_name,
                attempt=attempt.attempt,
                attempt_path=attempt.directory,
                signature=signature.value,
                cycle_id=self.cycle_id,
            )
            self.state.set_status(
                task_name,
                "running",
                None,
                signature.value,
                "tarefa iniciada",
                attempt.directory,
                cycle_id=self.cycle_id,
                signature_schema=SIGNATURE_SCHEMA_VERSION,
                signature_payload=signature.payload,
            )
            execution_options: dict[str, Any] = {
                "cwd": cwd,
                "env": env,
                "stdout_path": attempt.stdout_path,
                "stderr_path": attempt.stderr_path,
            }
            if timeout is not None:
                execution_options["timeout"] = timeout
            execution_result = self._normalize_execution_result(
                task_executor.run(task_name, argv, **execution_options)
            )
            return_code = execution_result.return_code
            execution = execution_result.metadata

            if return_code == 0:
                missing_outputs = artifacts.missing_required_outputs()
                invalid_outputs = artifacts.invalid_outputs()
                if missing_outputs or invalid_outputs:
                    reason = self._output_failure_reason(artifacts)
                    self.reporter.event("fail", task_name, reason, executor=executor_name)
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
                        execution=execution,
                        process_return_code=return_code,
                        reason=reason,
                    )
                    self.state.set_status(
                        task_name,
                        "invalid-output",
                        INVALID_OUTPUT_EXIT_CODE,
                        signature.value,
                        reason,
                        attempt.directory,
                        cycle_id=self.cycle_id,
                        signature_schema=SIGNATURE_SCHEMA_VERSION,
                        signature_payload=signature.payload,
                    )
                    if descendants:
                        self.state.mark_tasks(
                            descendants,
                            "blocked",
                            reason,
                            cycle_id=self.cycle_id,
                        )
                    exit_code = INVALID_OUTPUT_EXIT_CODE
                    break
                self.reporter.event("ok", task_name, executor=executor_name)
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
                    execution=execution,
                    process_return_code=return_code,
                )
                self.state.set_status(
                    task_name,
                    "success",
                    return_code,
                    signature.value,
                    "concluída com sucesso",
                    attempt.directory,
                    cycle_id=self.cycle_id,
                    signature_schema=SIGNATURE_SCHEMA_VERSION,
                    signature_payload=signature.payload,
                )
                executed_tasks.add(task_name)
            else:
                reason = self._process_failure_reason(return_code)
                self.reporter.event(
                    "fail",
                    task_name,
                    f"return code {return_code}",
                    executor=executor_name,
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
                    execution=execution,
                    process_return_code=return_code,
                    reason=reason,
                )
                self.state.set_status(
                    task_name,
                    "failed",
                    return_code,
                    signature.value,
                    reason,
                    attempt.directory,
                    cycle_id=self.cycle_id,
                    signature_schema=SIGNATURE_SCHEMA_VERSION,
                    signature_payload=signature.payload,
                )
                if descendants:
                    self.state.mark_tasks(
                        descendants,
                        "blocked",
                        reason,
                        cycle_id=self.cycle_id,
                    )
                exit_code = return_code
                break

        if recorder is not None:
            self.state.finish_run(recorder.run_id, "success" if exit_code == 0 else "failed")
        return exit_code

    def status(self) -> None:
        """Render current task states in dependency order."""
        entries = [
            (
                task_name,
                self.state.get_status(task_name, cycle_id=self.cycle_id) or "pending",
            )
            for task_name in self.plan()
        ]
        self.reporter.status_table(entries)

    def reset(self) -> None:
        """Reset current task state while preserving run and attempt history."""
        self.state.reset(cycle_id=self.cycle_id)

    def validate(self) -> list[str]:
        """Validate dependency order and every rendered task field without execution."""
        problems: list[str] = []
        task_map = {task["name"]: task for task in self.tasks}
        planned_outputs_by_task: dict[str, set[Path]] = {}
        for task_name in self.plan():
            task = task_map[task_name]
            render_argv(task["argv"], self.context)
            self._task_cwd(task)
            self._task_env(task)
            self._task_timeout(task)
            self._task_executor(task)
            artifacts = self._task_artifacts(task)

            dependencies = task.get("depends_on", []) or []
            if isinstance(dependencies, str):
                dependencies = [dependencies]
            planned_dependency_outputs: set[Path] = set()
            for dependency in dependencies:
                planned_dependency_outputs.update(
                    planned_outputs_by_task.get(dependency, set())
                )

            for path in artifacts.missing_required_inputs():
                if path not in planned_dependency_outputs:
                    problems.append(f"{task_name}: entrada obrigatória ausente: {path}")

            if task.get("enabled", True) is not False:
                planned_outputs_by_task[task_name] = (
                    planned_dependency_outputs | set(artifacts.required_outputs)
                )
        return problems

    def explain(self) -> None:
        """Explain current state and the next safe action in researcher-facing terms."""
        task_map = {task["name"]: task for task in self.tasks}
        for task_name in self.plan():
            task = task_map[task_name]
            state = self.state.get_task_state(task_name, cycle_id=self.cycle_id)
            status = state.status if state else "pending"
            reason = state.reason if state and state.reason else "a tarefa ainda não foi executada"
            self.reporter.event(
                status,
                task_name,
                reason,
                executor=str(task.get("executor", "local")),
            )
            artifacts = self._task_artifacts(task)
            missing_inputs = artifacts.missing_required_inputs()
            missing_outputs = artifacts.missing_required_outputs()
            if missing_inputs:
                self.reporter.note("  Entradas ausentes: " + ", ".join(map(str, missing_inputs)))
            if missing_outputs:
                self.reporter.note("  Produtos ausentes: " + ", ".join(map(str, missing_outputs)))
            if state and state.attempt_path:
                resolved = self.state.resolve_path(state.attempt_path)
                self.reporter.note(f"  Registros da tentativa: {resolved}")
