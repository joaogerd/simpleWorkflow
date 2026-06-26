from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

RUN_SCHEMA_VERSION = 1


def _utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp suitable for provenance records."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_run_id() -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{now}-{uuid.uuid4().hex[:12]}"


def _task_directory_name(task_name: str) -> str:
    """Produce a filesystem-safe, collision-resistant task directory name."""
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", task_name).strip("._-") or "task"
    digest = hashlib.sha256(task_name.encode("utf-8")).hexdigest()[:10]
    return f"{normalized}-{digest}"


@dataclass(frozen=True)
class AttemptPaths:
    """Filesystem locations belonging to one immutable task attempt."""

    run_id: str
    task_name: str
    attempt: int
    directory: Path
    stdout_path: Path
    stderr_path: Path
    metadata_path: Path


class RunRecorder:
    """Create immutable, filesystem-backed records for workflow task attempts."""

    def __init__(
        self,
        workdir: str | Path,
        workflow_name: str,
        *,
        run_id: str | None = None,
    ) -> None:
        self.workflow_name = workflow_name
        self.run_id = run_id or _default_run_id()
        self.root = Path(workdir) / "runs"
        self.directory = self.root / self.run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self._attempt_numbers: dict[str, int] = {}

        self._write_exclusive_json(
            self.directory / "run.json",
            {
                "schema_version": RUN_SCHEMA_VERSION,
                "run_id": self.run_id,
                "workflow": workflow_name,
                "created_at": _utc_timestamp(),
            },
        )

    def begin_attempt(self, task_name: str) -> AttemptPaths:
        """Allocate an empty, non-reusable directory for the next task attempt."""
        attempt = self._attempt_numbers.get(task_name, 0) + 1
        self._attempt_numbers[task_name] = attempt

        directory = (
            self.directory
            / "tasks"
            / _task_directory_name(task_name)
            / f"attempt-{attempt:03d}"
        )
        directory.mkdir(parents=True, exist_ok=False)
        stdout_path = directory / "stdout.log"
        stderr_path = directory / "stderr.log"
        stdout_path.touch(exist_ok=False)
        stderr_path.touch(exist_ok=False)
        return AttemptPaths(
            run_id=self.run_id,
            task_name=task_name,
            attempt=attempt,
            directory=directory,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            metadata_path=directory / "metadata.json",
        )

    def write_metadata(
        self, attempt: AttemptPaths, payload: Mapping[str, Any]
    ) -> None:
        """Write one final metadata record; a second write is deliberately rejected."""
        record = {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": attempt.run_id,
            "workflow": self.workflow_name,
            "task": attempt.task_name,
            "attempt": attempt.attempt,
            "recorded_at": _utc_timestamp(),
            "logs": {
                "stdout": attempt.stdout_path.name,
                "stderr": attempt.stderr_path.name,
            },
            **dict(payload),
        }
        self._write_exclusive_json(attempt.metadata_path, record)

    @staticmethod
    def _write_exclusive_json(path: Path, payload: Mapping[str, Any]) -> None:
        serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        with path.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
