from __future__ import annotations

import sqlite3
import json
import os
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TaskState:
    """Latest persisted result for one workflow task."""

    status: str
    return_code: int | None
    signature: str | None
    reason: str | None = None
    attempt_dir: str | None = None


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
                signature TEXT,
                reason TEXT,
                attempt_dir TEXT,
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
        if "reason" not in columns:
            self.connection.execute("ALTER TABLE task_state ADD COLUMN reason TEXT")
        if "attempt_dir" not in columns:
            self.connection.execute("ALTER TABLE task_state ADD COLUMN attempt_dir TEXT")
        self.connection.commit()

    def get_task_state(self, workflow: str, task: str) -> TaskState | None:
        cursor = self.connection.execute(
            """
            SELECT status, return_code, signature, reason, attempt_dir
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
        reason: str | None = None,
        attempt_dir: str | None = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO task_state (
                workflow, task, status, return_code, signature, reason, attempt_dir, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(workflow, task)
            DO UPDATE SET
                status = excluded.status,
                return_code = excluded.return_code,
                signature = excluded.signature,
                reason = excluded.reason,
                attempt_dir = excluded.attempt_dir,
                updated_at = CURRENT_TIMESTAMP
            """,
            (workflow, task, status, return_code, signature, reason, attempt_dir),
        )
        self.connection.commit()

    def mark_tasks(self, workflow: str, tasks: Iterable[str], status: str, reason: str) -> None:
        self.connection.executemany(
            """
            INSERT INTO task_state (workflow, task, status, reason, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(workflow, task) DO UPDATE SET
                status = excluded.status,
                return_code = NULL,
                reason = excluded.reason,
                updated_at = CURRENT_TIMESTAMP
            """,
            [(workflow, task, status, reason) for task in tasks],
        )
        self.connection.commit()

    def reconcile_running(self, workflow: str) -> None:
        rows = self.connection.execute(
            "SELECT task, signature, attempt_dir FROM task_state WHERE workflow = ? AND status = 'running'",
            (workflow,),
        ).fetchall()
        for task, signature, attempt_dir in rows:
            metadata = Path(attempt_dir) / "metadata.json" if attempt_dir else None
            if metadata and metadata.is_file():
                try:
                    record = json.loads(metadata.read_text(encoding="utf-8"))
                    status = str(record["status"])
                    return_code = record.get("return_code")
                    reason = record.get("reason") or "resultado recuperado do registro da tentativa"
                    self.set_status(
                        workflow, task, status, return_code, signature, reason, attempt_dir
                    )
                    continue
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            process_record = Path(attempt_dir) / "process.json" if attempt_dir else None
            if process_record and process_record.is_file():
                try:
                    process = json.loads(process_record.read_text(encoding="utf-8"))
                    pid = int(process["pid"])
                    if process.get("host") == socket.gethostname():
                        os.kill(pid, 0)
                        self.set_status(
                            workflow,
                            task,
                            "unknown",
                            None,
                            signature,
                            f"processo {pid} ainda pode estar ativo neste computador",
                            attempt_dir,
                        )
                        continue
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            scheduler_record = Path(attempt_dir) / "scheduler.json" if attempt_dir else None
            if scheduler_record and scheduler_record.is_file():
                try:
                    scheduler = json.loads(scheduler_record.read_text(encoding="utf-8"))
                    job_id = str(scheduler["job_id"])
                    self.set_status(
                        workflow,
                        task,
                        "unknown",
                        None,
                        signature,
                        f"job PBS {job_id} precisa ser reconciliado com o escalonador",
                        attempt_dir,
                    )
                    continue
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            self.set_status(
                workflow,
                task,
                "interrupted",
                None,
                signature,
                "o controlador anterior terminou antes de registrar o resultado",
                attempt_dir,
            )

    def tasks_with_status(self, workflow: str, status: str) -> list[str]:
        return [
            row[0]
            for row in self.connection.execute(
                "SELECT task FROM task_state WHERE workflow = ? AND status = ? ORDER BY task",
                (workflow, status),
            )
        ]

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
