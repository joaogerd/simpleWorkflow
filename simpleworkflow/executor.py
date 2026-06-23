from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path


class LocalExecutor:
    """Run workflow tasks locally from an explicit argument vector."""

    def __init__(self, log_dir: str | Path):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        task_name: str,
        argv: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        stdout_path: str | Path | None = None,
        stderr_path: str | Path | None = None,
    ) -> int:
        """Run a task without a shell and return its process exit status."""
        if (stdout_path is None) != (stderr_path is None):
            raise ValueError("stdout_path and stderr_path must be provided together.")

        if stdout_path is None:
            safe_name = task_name.replace("/", "_").replace(" ", "_")
            stdout_file = self.log_dir / f"{safe_name}.out"
            stderr_file = self.log_dir / f"{safe_name}.err"
            log_mode = "w"
        else:
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
                process = subprocess.run(
                    list(argv),
                    shell=False,
                    cwd=str(cwd) if cwd is not None else None,
                    env=execution_env,
                    stdout=stdout,
                    stderr=stderr,
                    text=True,
                    check=False,
                )
            except OSError as error:
                stderr.write(f"simpleWorkflow could not start task: {error}\n")
                return 127

        return process.returncode
