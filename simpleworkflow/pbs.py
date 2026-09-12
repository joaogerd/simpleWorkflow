"""Small foreground-wait PBS execution backend for simpleWorkflow."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .executor import ExecutionResult

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_JOB_ID = re.compile(r"(?m)^\s*([0-9]+(?:\.[A-Za-z0-9_.-]+)?)\s*$")
_WALLTIME = re.compile(r"^\d{1,3}:\d{2}:\d{2}$")
_DIRECTIVE_VALUE = re.compile(r"^[A-Za-z0-9_.@/+:-]+$")
_JOB_STATE = re.compile(r"(?m)^\s*job_state\s*=\s*([A-Za-z])\s*$")
_EXIT_STATUS = re.compile(r"(?m)^\s*Exit_status\s*=\s*(-?\d+)\s*$")


class PbsExecutor:
    """Submit one task to PBS and wait for the final job result.

    Submission returns a job identifier immediately; this foreground process
    then consults PBS until completion. Success means that the job completed
    successfully, not merely that it entered a queue.
    """

    def __init__(self, options: Mapping[str, Any]):
        self.options = dict(options)
        self._validate_options()

    @staticmethod
    def _directive_value(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value or not _DIRECTIVE_VALUE.fullmatch(value):
            raise ValueError(
                f"PBS field '{field}' contains characters that are not safe in a directive."
            )
        return value

    def _validate_options(self) -> None:
        for field in ("queue", "project"):
            if field in self.options:
                self._directive_value(self.options[field], field)
        if "qsub" in self.options:
            value = self.options["qsub"]
            if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
                raise ValueError("PBS field 'qsub' must be a safe non-empty command.")
            if not shlex.split(value):
                raise ValueError("PBS field 'qsub' must resolve to a command.")
        for field in ("qstat", "qdel"):
            if field in self.options:
                value = self.options[field]
                if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
                    raise ValueError(f"PBS field '{field}' must be a safe non-empty command.")
                if not shlex.split(value):
                    raise ValueError(f"PBS field '{field}' must resolve to a command.")
        if "walltime" in self.options:
            self._walltime(self.options["walltime"])
        for field in ("select", "ncpus", "mpiprocs", "omp_threads"):
            if field in self.options:
                self._positive_integer(self.options[field], field)
        if self.options.get("block", True) is not True:
            raise ValueError("PBS non-blocking submission is intentionally unsupported.")
        interval = self.options.get("poll_interval", 5)
        try:
            interval = float(interval)
        except (TypeError, ValueError) as error:
            raise ValueError("PBS field 'poll_interval' must be a positive number.") from error
        if interval <= 0:
            raise ValueError("PBS field 'poll_interval' must be a positive number.")
        self.options["poll_interval"] = interval

    @staticmethod
    def _write_scheduler_record(path: Path, payload: Mapping[str, Any]) -> None:
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(dict(payload), sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _pbs_result(output: str) -> int | None:
        state = _JOB_STATE.search(output)
        if not state or state.group(1).upper() not in {"F", "X"}:
            return None
        status = _EXIT_STATUS.search(output)
        return int(status.group(1)) if status else 75

    @staticmethod
    def _scheduler_status_line(job_id: str, output: str) -> str:
        """Return a compact scheduler status without persisting qstat payloads."""
        state_match = _JOB_STATE.search(output)
        exit_match = _EXIT_STATUS.search(output)

        state = state_match.group(1).upper() if state_match else "?"
        fields = [f"job_id={job_id}", f"state={state}"]

        if exit_match:
            fields.append(f"exit_status={exit_match.group(1)}")

        return "[simpleworkflow] qstat: " + " ".join(fields) + "\n"

    @staticmethod
    def _safe_job_name(value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._-")
        return normalized[:80] or "simpleworkflow"

    @staticmethod
    def _write(path: Path, content: str, *, mode: str = "a") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open(mode, encoding="utf-8") as stream:
            stream.write(content)

    @staticmethod
    def _positive_integer(value: Any, field: str) -> int:
        """Normalize a rendered PBS count and reject invalid resource values."""
        if isinstance(value, bool):
            raise ValueError(f"PBS field '{field}' must be a positive integer.")
        try:
            normalized = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"PBS field '{field}' must be a positive integer.") from error
        if normalized <= 0 or str(normalized) != str(value).strip():
            raise ValueError(f"PBS field '{field}' must be a positive integer.")
        return normalized

    @staticmethod
    def _walltime(value: Any) -> str:
        """Validate a rendered PBS walltime value."""
        if not isinstance(value, str) or not _WALLTIME.fullmatch(value):
            raise ValueError("PBS field 'walltime' must use HHH:MM:SS format.")
        return value

    def _build_script(
        self,
        *,
        task_name: str,
        argv: Sequence[str],
        cwd: str | Path | None,
        env: Mapping[str, str] | None,
        worker_stdout: Path,
        worker_stderr: Path,
    ) -> str:
        job_name = self._safe_job_name(str(self.options.get("job_name", task_name)))
        lines = ["#!/bin/bash", f"#PBS -N {job_name}"]

        queue = self.options.get("queue")
        if queue:
            lines.append(f"#PBS -q {self._directive_value(queue, 'queue')}")

        project = self.options.get("project")
        if project:
            lines.append(f"#PBS -A {self._directive_value(project, 'project')}")

        if "walltime" in self.options:
            lines.append(f"#PBS -l walltime={self._walltime(self.options['walltime'])}")

        has_select = any(
            key in self.options for key in ("select", "ncpus", "mpiprocs")
        )
        if has_select:
            select = self._positive_integer(self.options.get("select", 1), "select")
            resources = [f"select={select}"]
            for key in ("ncpus", "mpiprocs"):
                if key in self.options:
                    resources.append(
                        f"{key}={self._positive_integer(self.options[key], key)}"
                    )
            lines.append(f"#PBS -l {':'.join(resources)}")

        lines.extend(
            [
                f"#PBS -o {worker_stdout.resolve(strict=False)}",
                f"#PBS -e {worker_stderr.resolve(strict=False)}",
                "set -euo pipefail",
            ]
        )

        resolved_cwd = Path(cwd).resolve(strict=False) if cwd is not None else Path.cwd()
        lines.append(f"cd {shlex.quote(str(resolved_cwd))}")

        task_env = dict(env or {})
        if "omp_threads" in self.options:
            omp_threads = self._positive_integer(
                self.options["omp_threads"], "omp_threads"
            )
            task_env.setdefault("OMP_NUM_THREADS", str(omp_threads))
        for key, value in sorted(task_env.items()):
            if not _ENV_NAME.fullmatch(key):
                raise ValueError(f"Invalid PBS environment variable name: {key!r}")
            lines.append(f"export {key}={shlex.quote(value)}")

        lines.append(f"exec {shlex.join(list(argv))}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _job_id(output: str) -> str | None:
        match = _JOB_ID.search(output)
        return match.group(1) if match else None

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
        """Submit one PBS job, persist its ID and wait in the foreground."""
        del timeout
        if stdout_path is None or stderr_path is None:
            raise ValueError("PBS execution requires attempt stdout and stderr paths.")
        if self.options.get("block", True) is not True:
            raise ValueError("PBS non-blocking submission is intentionally unsupported.")

        submit_stdout = Path(stdout_path)
        submit_stderr = Path(stderr_path)
        attempt_dir = submit_stdout.parent
        script_path = attempt_dir / "job.pbs"
        worker_stdout = attempt_dir / "pbs.stdout.log"
        worker_stderr = attempt_dir / "pbs.stderr.log"
        script_path.write_text(
            self._build_script(
                task_name=task_name,
                argv=argv,
                cwd=cwd,
                env=env,
                worker_stdout=worker_stdout,
                worker_stderr=worker_stderr,
            ),
            encoding="utf-8",
        )

        qsub = shlex.split(str(self.options.get("qsub", "qsub")))
        if not qsub:
            raise ValueError("PBS field 'qsub' must resolve to a command.")
        command = [*qsub]
        if self.options.get("inherit_environment", True):
            command.append("-V")
        command.append(str(script_path.resolve(strict=False)))

        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd) if cwd is not None else None,
                text=True,
                capture_output=True,
                check=False,
            )
        except OSError as error:
            self._write(submit_stderr, f"simpleWorkflow could not start qsub: {error}\n")
            return ExecutionResult(
                return_code=127,
                metadata={
                    "executor": "pbs",
                    "wait_mode": "foreground-poll",
                    "qsub_argv": command,
                    "script": str(script_path.resolve(strict=False)),
                    "job_stdout": str(worker_stdout.resolve(strict=False)),
                    "job_stderr": str(worker_stderr.resolve(strict=False)),
                },
            )

        self._write(submit_stdout, f"[simpleworkflow] qsub: {shlex.join(command)}\n")
        self._write(submit_stdout, completed.stdout)
        self._write(submit_stderr, completed.stderr)
        combined_output = f"{completed.stdout}\n{completed.stderr}"
        job_id = self._job_id(combined_output)
        base_metadata = {
            "executor": "pbs",
            "wait_mode": "foreground-poll",
            "qsub_argv": command,
            "script": str(script_path.resolve(strict=False)),
            "job_id": job_id,
            "job_stdout": str(worker_stdout.resolve(strict=False)),
            "job_stderr": str(worker_stderr.resolve(strict=False)),
        }
        if completed.returncode != 0 or job_id is None:
            return ExecutionResult(
                return_code=completed.returncode or 75,
                metadata=base_metadata,
            )

        scheduler_record = attempt_dir / "scheduler.json"
        self._write_scheduler_record(scheduler_record, base_metadata)
        qstat = shlex.split(str(self.options.get("qstat", "qstat")))
        qdel = shlex.split(str(self.options.get("qdel", "qdel")))
        interval = float(self.options["poll_interval"])
        while True:
            try:
                status = subprocess.run(
                    [*qstat, "-xf", job_id], text=True, capture_output=True, check=False
                )
            except OSError as error:
                self._write(submit_stderr, f"simpleWorkflow could not run qstat: {error}\n")
                return ExecutionResult(return_code=75, metadata=base_metadata)
            status_output = f"{status.stdout}\n{status.stderr}"
            self._write(
                submit_stdout,
                self._scheduler_status_line(job_id, status_output),
            )
            result = self._pbs_result(status_output)
            if result is not None:
                return ExecutionResult(return_code=result, metadata=base_metadata)
            if status.returncode != 0:
                if status.stderr:
                    self._write(submit_stderr, status.stderr)
                return ExecutionResult(return_code=75, metadata=base_metadata)
            try:
                time.sleep(interval)
            except KeyboardInterrupt:
                subprocess.run([*qdel, job_id], text=True, capture_output=True, check=False)
                raise
