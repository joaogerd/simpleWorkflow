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
    ) -> int:
        """Run a task without a shell and return its process exit status."""
        safe_name = task_name.replace("/", "_").replace(" ", "_")
        stdout_path = self.log_dir / f"{safe_name}.out"
        stderr_path = self.log_dir / f"{safe_name}.err"
        execution_env = os.environ.copy()
        if env:
            execution_env.update(env)

        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open(
            "w", encoding="utf-8"
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
