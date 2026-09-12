from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

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
    started_path: Path


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
            started_path=directory / "started.json",
        )

    def write_workflow_snapshot(self, config: Mapping[str, Any]) -> None:
        public_config = {
            key: value for key, value in config.items() if not key.startswith("__")
        }
        self._write_exclusive_text(
            self.directory / "workflow.yaml",
            yaml.safe_dump(public_config, sort_keys=False, allow_unicode=True),
        )

    def write_started(self, attempt: AttemptPaths, payload: Mapping[str, Any]) -> None:
        self._write_exclusive_json(
            attempt.started_path,
            {
                "schema_version": RUN_SCHEMA_VERSION,
                "run_id": attempt.run_id,
                "workflow": self.workflow_name,
                "task": attempt.task_name,
                "attempt": attempt.attempt,
                "started_at": _utc_timestamp(),
                "controller": {"pid": os.getpid(), "host": socket.gethostname()},
                **dict(payload),
            },
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
        digest = hashlib.sha256(attempt.metadata_path.read_bytes()).hexdigest()
        self._write_exclusive_text(attempt.directory / "metadata.sha256", digest + "\n")

    @staticmethod
    def _write_exclusive_text(path: Path, text: str) -> None:
        RunRecorder._atomic_exclusive_write(path, text)

    @staticmethod
    def _write_exclusive_json(path: Path, payload: Mapping[str, Any]) -> None:
        serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        RunRecorder._atomic_exclusive_write(path, serialized)

    @staticmethod
    def _atomic_exclusive_write(path: Path, serialized: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            if path.exists():
                raise FileExistsError(path)
            os.link(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
