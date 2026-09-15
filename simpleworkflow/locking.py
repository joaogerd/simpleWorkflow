from __future__ import annotations

import fcntl
import json
import os
import socket
from pathlib import Path
from typing import TextIO


class WorkflowLockedError(RuntimeError):
    """Raised when another controller owns the workflow execution lock."""


class WorkflowLock:
    """Advisory process lock for the single workflow represented by a work directory."""

    def __init__(self, workdir: str | Path, workflow: str) -> None:
        self.path = Path(workdir) / "lock"
        self.workflow = workflow
        self._stream: TextIO | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            stream.seek(0)
            details = stream.read().strip() or "controlador não identificado"
            stream.close()
            raise WorkflowLockedError(
                f"Workflow '{self.workflow}' já está em execução ({details})."
            ) from error
        stream.seek(0)
        stream.truncate()
        json.dump(
            {"pid": os.getpid(), "host": socket.gethostname(), "workflow": self.workflow},
            stream,
            sort_keys=True,
        )
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
        self._stream = stream

    def release(self) -> None:
        if self._stream is None:
            return
        fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        self._stream.close()
        self._stream = None

    def __enter__(self) -> WorkflowLock:
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()
