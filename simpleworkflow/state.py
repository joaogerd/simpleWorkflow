from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TaskState:
    """Latest persisted result for one workflow task."""

    status: str
    return_code: int | None
    signature: str | None


class WorkflowState:
    """Persistent workflow task state stored in SQLite."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_state (
                    workflow TEXT NOT NULL,
                    task TEXT NOT NULL,
                    status TEXT NOT NULL,
                    return_code INTEGER,
                    signature TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (workflow, task)
                )
                """
            )
            columns = {
                row[1]
                for row in self.connection.execute("PRAGMA table_info(task_state)")
            }
            if "signature" not in columns:
                self.connection.execute("ALTER TABLE task_state ADD COLUMN signature TEXT")
            self.connection.commit()

    def get_task_state(self, workflow: str, task: str) -> TaskState | None:
        with self._lock:
            cursor = self.connection.execute(
                """
                SELECT status, return_code, signature
                FROM task_state
                WHERE workflow = ? AND task = ?
                """,
                (workflow, task),
            )
            row = cursor.fetchone()
        return TaskState(*row) if row else None

    def get_status(self, workflow: str, task: str) -> str | None:
        task_state = self.get_task_state(workflow, task)
        return task_state.status if task_state else None

    def set_status(
        self,
        workflow: str,
        task: str,
        status: str,
        return_code: int | None = None,
        signature: str | None = None,
    ) -> None:
        with self._lock:
            self.connection.execute(
                """
                INSERT INTO task_state (
                    workflow, task, status, return_code, signature, updated_at
                )
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(workflow, task)
                DO UPDATE SET
                    status = excluded.status,
                    return_code = excluded.return_code,
                    signature = excluded.signature,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (workflow, task, status, return_code, signature),
            )
            self.connection.commit()

    def reset(self, workflow: str, tasks: Iterable[str] | None = None) -> None:
        with self._lock:
            if tasks is None:
                self.connection.execute(
                    "DELETE FROM task_state WHERE workflow = ?",
                    (workflow,),
                )
            else:
                self.connection.executemany(
                    "DELETE FROM task_state WHERE workflow = ? AND task = ?",
                    [(workflow, task) for task in tasks],
                )
            self.connection.commit()

    def close(self) -> None:
        with self._lock:
            self.connection.close()
