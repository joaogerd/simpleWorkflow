from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from .runs import write_durable_json


class _TerminationSignal(Exception):
    def __init__(self, signum: int):
        self.signum = signum


def _raise_termination(signum: int, _frame: object) -> None:
    raise _TerminationSignal(signum)


@dataclass(frozen=True)
class ExecutionResult:
    """Outcome returned by a task execution backend.

    A known outcome requires a confirmed return code. An unknown outcome means
    the backend cannot safely determine whether execution completed and callers
    must not automatically repeat the task.
    """

    return_code: int | None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    outcome: Literal["known", "unknown"] = "known"
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.outcome == "known" and self.return_code is None:
            raise ValueError("known execution results require a return code")
        if self.outcome == "unknown" and self.return_code is not None:
            raise ValueError("unknown execution results must not invent a return code")


@runtime_checkable
class TaskExecutor(Protocol):
    """Protocol implemented by lightweight simpleWorkflow execution backends."""

    def run(
        self,
        task_name: str,
        argv: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        stdout_path: str | Path | None = None,
        stderr_path: str | Path | None = None,
        timeout: float | None = None,
    ) -> ExecutionResult:
        """Execute one rendered task and return its outcome."""
        ...


class LocalExecutor:
    """Run workflow tasks locally from an explicit argument vector."""

    def __init__(self, log_dir: str | Path):
        self.log_dir = Path(log_dir)

    def run(
        self,
        task_name: str,
        argv: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        stdout_path: str | Path | None = None,
        stderr_path: str | Path | None = None,
        timeout: float | None = None,
    ) -> ExecutionResult:
        """Run a task without a shell and return its process outcome."""
        if (stdout_path is None) != (stderr_path is None):
            raise ValueError("stdout_path and stderr_path must be provided together.")

        if stdout_path is None:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            safe_name = task_name.replace("/", "_").replace(" ", "_")
            stdout_file = self.log_dir / f"{safe_name}.out"
            stderr_file = self.log_dir / f"{safe_name}.err"
            log_mode = "w"
        else:
            assert stderr_path is not None
            stdout_file = Path(stdout_path)
            stderr_file = Path(stderr_path)
            stdout_file.parent.mkdir(parents=True, exist_ok=True)
            stderr_file.parent.mkdir(parents=True, exist_ok=True)
            log_mode = "a"

        execution_env = os.environ.copy()
        if env:
            execution_env.update(env)

        with stdout_file.open(log_mode, encoding="utf-8") as stdout, stderr_file.open(
            log_mode, encoding="utf-8"
        ) as stderr:
            try:
                started_at = time.time()
                process = subprocess.Popen(
                    list(argv),
                    shell=False,
                    cwd=str(cwd) if cwd is not None else None,
                    env=execution_env,
                    stdout=stdout,
                    stderr=stderr,
                    text=True,
                    start_new_session=True,
                )
                process_record = stdout_file.parent / "process.json"
                write_durable_json(
                    process_record,
                    {
                        "pid": process.pid,
                        "process_group": process.pid,
                        "host": socket.gethostname(),
                        "started_at_epoch": started_at,
                    },
                )
                timed_out = False
                interrupted_signal: int | None = None
                previous_handlers: dict[signal.Signals, Any] = {}
                try:
                    for signum in (signal.SIGINT, signal.SIGTERM):
                        previous_handlers[signum] = signal.signal(signum, _raise_termination)
                except ValueError:
                    previous_handlers = {}
                try:
                    return_code = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        return_code = process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        return_code = process.wait()
                except _TerminationSignal as interruption:
                    interrupted_signal = interruption.signum
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        return_code = process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        return_code = process.wait()
                finally:
                    for signum, handler in previous_handlers.items():
                        signal.signal(signum, handler)
            except OSError as error:
                stderr.write(f"simpleWorkflow could not start task: {error}\n")
                return ExecutionResult(return_code=127, metadata={"executor": "local"})

        return ExecutionResult(
            return_code=(
                128 + interrupted_signal
                if interrupted_signal is not None
                else 124 if timed_out else return_code
            ),
            metadata={
                "executor": "local",
                "pid": process.pid,
                "process_group": process.pid,
                "started_at_epoch": started_at,
                "finished_at_epoch": time.time(),
                "timed_out": timed_out,
                "interrupted_signal": interrupted_signal,
                "process_return_code": return_code,
            },
        )
