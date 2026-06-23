from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Mapping, Sequence


class LocalExecutor:
    """Run a task locally from an explicit argument vector."""

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
        safe_name = task_name.replace("/", "_").replace(" ", "_")
        stdout_path = self.log_dir / f"{safe_name}.out"
        stderr_path = self.log_dir / f"{safe_name}.err"
        runtime_env = os.environ.copy()
        if env:
            runtime_env.update(env)

        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open(
            "w", encoding="utf-8"
        ) as stderr:
            process = subprocess.run(
                list(argv),
                cwd=cwd,
                env=runtime_env,
                shell=False,
                stdout=stdout,
                stderr=stderr,
                text=True,
                check=False,
            )

        return process.returncode
