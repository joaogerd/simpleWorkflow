from __future__ import annotations

import subprocess
from pathlib import Path


class LocalExecutor:
    """Run workflow tasks on the local machine using the shell."""

    def __init__(self, log_dir: str | Path):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def run(self, task_name: str, command: str) -> int:
        safe_name = task_name.replace("/", "_").replace(" ", "_")
        stdout_path = self.log_dir / f"{safe_name}.out"
        stderr_path = self.log_dir / f"{safe_name}.err"

        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open(
            "w", encoding="utf-8"
        ) as stderr:
            process = subprocess.run(
                command,
                shell=True,
                stdout=stdout,
                stderr=stderr,
                text=True,
            )

        return process.returncode
