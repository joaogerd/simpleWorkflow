from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable


class WorkflowState:
    """Persistent workflow task state stored in SQLite."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self._init_schema()

    def _init_schema(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS task_state (
                workflow TEXT NOT NULL,
                task TEXT NOT NULL,
                status TEXT NOT NULL,
                return_code INTEGER,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (workflow, task)
            )
            """
        )
        self.connection.commit()

    def get_status(self, workflow: str, task: str) -> str | None:
        cursor = self.connection.execute(
            "SELECT status FROM task_state WHERE workflow = ? AND task = ?",
            (workflow, task),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def set_status(
        self,
        workflow: str,
        task: str,
        status: str,
        return_code: int | None = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO task_state (workflow, task, status, return_code, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(workflow, task)
            DO UPDATE SET
                status = excluded.status,
                return_code = excluded.return_code,
                updated_at = CURRENT_TIMESTAMP
            """,
            (workflow, task, status, return_code),
        )
        self.connection.commit()

    def reset(self, workflow: str, tasks: Iterable[str] | None = None) -> None:
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
        self.connection.close()
