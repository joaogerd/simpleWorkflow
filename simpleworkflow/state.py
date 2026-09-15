from __future__ import annotations

import json
import os
import socket
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_SCHEMA_VERSION = 1
_NO_CYCLE = ""


class StateMigrationRequired(RuntimeError):
    """Raised when an unversioned pre-0.4 state database is opened."""


class StateSchemaError(RuntimeError):
    """Raised when a state database uses an unsupported schema."""


class StateBindingError(RuntimeError):
    """Raised when one state directory is used for a different workflow file."""


@dataclass(frozen=True)
class WorkflowInstance:
    """Persistent identity of the single logical workflow stored in this database."""

    instance_id: str
    workflow_name: str
    source_filename: str | None
    last_source_path: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TaskState:
    """Latest persisted result for one task in one optional cycle."""

    status: str
    return_code: int | None
    signature: str | None
    signature_schema: int | None = None
    signature_payload: dict[str, Any] | None = None
    reason: str | None = None
    attempt_path: str | None = None
    updated_at: str | None = None


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _cycle_key(cycle_id: str | None) -> str:
    return cycle_id or _NO_CYCLE


def _decode_payload(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


class WorkflowState:
    """Persistent state for exactly one logical workflow instance."""

    def __init__(
        self,
        path: str | Path,
        *,
        workflow_name: str,
        source_path: str | Path | None = None,
    ) -> None:
        self.path = Path(path)
        self.workdir = self.path.parent.resolve(strict=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        try:
            self._open_or_initialize(workflow_name, source_path)
        except Exception:
            self.connection.close()
            raise

    def _table_exists(self, name: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone()
        return row is not None

    def _has_user_tables(self) -> bool:
        row = self.connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            LIMIT 1
            """
        ).fetchone()
        return row is not None

    def _open_or_initialize(
        self,
        workflow_name: str,
        source_path: str | Path | None,
    ) -> None:
        if not self._has_user_tables():
            self._create_schema()
            self._create_instance(workflow_name, source_path)
            return
        if not self._table_exists("schema_info"):
            raise StateMigrationRequired(
                f"o banco {self.path} foi criado por uma versão anterior do simpleWorkflow; "
                "execute 'swf migrate <workflow.yaml>' antes de continuar"
            )
        row = self.connection.execute(
            "SELECT schema_version FROM schema_info WHERE singleton = 1"
        ).fetchone()
        if row is None:
            raise StateSchemaError("state database has schema_info but no schema version record")
        version = int(row[0])
        if version != STATE_SCHEMA_VERSION:
            raise StateSchemaError(
                f"state schema {version} is unsupported by this simpleWorkflow; "
                f"expected schema {STATE_SCHEMA_VERSION}"
            )
        self._bind_instance(workflow_name, source_path)

    def _create_schema(self) -> None:
        now = _utc_timestamp()
        self.connection.executescript(
            """
            CREATE TABLE schema_info (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                schema_version INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE workflow_instance (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                instance_id TEXT NOT NULL UNIQUE,
                workflow_name TEXT NOT NULL,
                source_filename TEXT,
                last_source_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE cycle_state (
                cycle_id TEXT PRIMARY KEY,
                cycle_time TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE task_state (
                cycle_id TEXT NOT NULL DEFAULT '',
                task TEXT NOT NULL,
                status TEXT NOT NULL,
                return_code INTEGER,
                signature TEXT,
                signature_schema INTEGER,
                signature_payload TEXT,
                reason TEXT,
                attempt_path TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (cycle_id, task)
            );

            CREATE TABLE state_event (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cycle_id TEXT NOT NULL DEFAULT '',
                task TEXT NOT NULL,
                status TEXT NOT NULL,
                return_code INTEGER,
                reason TEXT,
                attempt_path TEXT,
                recorded_at TEXT NOT NULL
            );

            CREATE TABLE run_history (
                run_id TEXT PRIMARY KEY,
                cycle_id TEXT NOT NULL DEFAULT '',
                run_path TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                finished_at TEXT
            );

            CREATE TABLE attempt_history (
                run_id TEXT NOT NULL,
                cycle_id TEXT NOT NULL DEFAULT '',
                task TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                status TEXT NOT NULL,
                return_code INTEGER,
                signature TEXT,
                reason TEXT,
                attempt_path TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                PRIMARY KEY (run_id, task, attempt),
                FOREIGN KEY (run_id) REFERENCES run_history(run_id) ON DELETE CASCADE
            );

            CREATE TABLE migration_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_version TEXT NOT NULL,
                source_selector TEXT,
                source_workflow_keys TEXT,
                backup_path TEXT NOT NULL,
                migrated_at TEXT NOT NULL
            );

            CREATE INDEX idx_task_state_status
                ON task_state(cycle_id, status);
            CREATE INDEX idx_attempt_history_task
                ON attempt_history(cycle_id, task, started_at);
            """
        )
        self.connection.execute(
            "INSERT INTO schema_info(singleton, schema_version, created_at) VALUES (1, ?, ?)",
            (STATE_SCHEMA_VERSION, now),
        )
        self.connection.commit()

    def _create_instance(
        self,
        workflow_name: str,
        source_path: str | Path | None,
        *,
        instance_id: str | None = None,
        created_at: str | None = None,
    ) -> None:
        now = _utc_timestamp()
        source = Path(source_path).resolve(strict=False) if source_path is not None else None
        self.connection.execute(
            """
            INSERT INTO workflow_instance(
                singleton, instance_id, workflow_name, source_filename,
                last_source_path, created_at, updated_at
            ) VALUES (1, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id or str(uuid.uuid4()),
                workflow_name,
                source.name if source is not None else None,
                str(source) if source is not None else None,
                created_at or now,
                now,
            ),
        )
        self.connection.commit()

    def _bind_instance(
        self,
        workflow_name: str,
        source_path: str | Path | None,
    ) -> None:
        row = self.connection.execute(
            """
            SELECT source_filename
            FROM workflow_instance
            WHERE singleton = 1
            """
        ).fetchone()
        if row is None:
            raise StateSchemaError("state database has no workflow_instance record")
        stored_filename = row[0]
        source = Path(source_path).resolve(strict=False) if source_path is not None else None
        if source is not None and stored_filename and source.name != stored_filename:
            raise StateBindingError(
                f"{self.workdir} pertence ao workflow '{stored_filename}', mas o arquivo atual "
                f"é '{source.name}'. Use um .simpleworkflow separado ou --workdir explícito."
            )
        now = _utc_timestamp()
        self.connection.execute(
            """
            UPDATE workflow_instance
            SET workflow_name = ?,
                last_source_path = COALESCE(?, last_source_path),
                updated_at = ?
            WHERE singleton = 1
            """,
            (workflow_name, str(source) if source is not None else None, now),
        )
        self.connection.commit()

    @property
    def instance(self) -> WorkflowInstance:
        row = self.connection.execute(
            """
            SELECT instance_id, workflow_name, source_filename, last_source_path,
                   created_at, updated_at
            FROM workflow_instance
            WHERE singleton = 1
            """
        ).fetchone()
        if row is None:
            raise StateSchemaError("state database has no workflow_instance record")
        return WorkflowInstance(*row)

    @property
    def instance_id(self) -> str:
        return self.instance.instance_id

    def ensure_cycle(self, cycle_id: str | None, cycle_time: str | None) -> None:
        if not cycle_id:
            return
        if not cycle_time:
            raise ValueError("cycle_time is required when cycle_id is set")
        now = _utc_timestamp()
        self.connection.execute(
            """
            INSERT INTO cycle_state(cycle_id, cycle_time, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(cycle_id) DO UPDATE SET
                cycle_time = excluded.cycle_time,
                updated_at = excluded.updated_at
            """,
            (cycle_id, cycle_time, now, now),
        )
        self.connection.commit()

    def get_task_state(self, task: str, *, cycle_id: str | None = None) -> TaskState | None:
        row = self.connection.execute(
            """
            SELECT status, return_code, signature, signature_schema,
                   signature_payload, reason, attempt_path, updated_at
            FROM task_state
            WHERE cycle_id = ? AND task = ?
            """,
            (_cycle_key(cycle_id), task),
        ).fetchone()
        if row is None:
            return None
        return TaskState(
            status=row[0],
            return_code=row[1],
            signature=row[2],
            signature_schema=row[3],
            signature_payload=_decode_payload(row[4]),
            reason=row[5],
            attempt_path=row[6],
            updated_at=row[7],
        )

    def get_status(self, task: str, *, cycle_id: str | None = None) -> str | None:
        state = self.get_task_state(task, cycle_id=cycle_id)
        return state.status if state else None

    def set_status(
        self,
        task: str,
        status: str,
        return_code: int | None = None,
        signature: str | None = None,
        reason: str | None = None,
        attempt_path: str | Path | None = None,
        *,
        cycle_id: str | None = None,
        signature_schema: int | None = None,
        signature_payload: Mapping[str, Any] | None = None,
        updated_at: str | None = None,
    ) -> None:
        timestamp = updated_at or _utc_timestamp()
        portable_attempt = self.portable_path(attempt_path) if attempt_path is not None else None
        encoded_payload = (
            json.dumps(dict(signature_payload), sort_keys=True, separators=(",", ":"))
            if signature_payload is not None
            else None
        )
        key = _cycle_key(cycle_id)
        self.connection.execute(
            """
            INSERT INTO task_state(
                cycle_id, task, status, return_code, signature, signature_schema,
                signature_payload, reason, attempt_path, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cycle_id, task) DO UPDATE SET
                status = excluded.status,
                return_code = excluded.return_code,
                signature = excluded.signature,
                signature_schema = excluded.signature_schema,
                signature_payload = excluded.signature_payload,
                reason = excluded.reason,
                attempt_path = excluded.attempt_path,
                updated_at = excluded.updated_at
            """,
            (
                key,
                task,
                status,
                return_code,
                signature,
                signature_schema,
                encoded_payload,
                reason,
                portable_attempt,
                timestamp,
            ),
        )
        self.connection.execute(
            """
            INSERT INTO state_event(
                cycle_id, task, status, return_code, reason, attempt_path, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (key, task, status, return_code, reason, portable_attempt, timestamp),
        )
        self.connection.commit()

    def mark_tasks(
        self,
        tasks: Iterable[str],
        status: str,
        reason: str,
        *,
        cycle_id: str | None = None,
    ) -> None:
        for task in tasks:
            previous = self.get_task_state(task, cycle_id=cycle_id)
            self.set_status(
                task,
                status,
                None,
                previous.signature if previous else None,
                reason,
                previous.attempt_path if previous else None,
                cycle_id=cycle_id,
                signature_schema=previous.signature_schema if previous else None,
                signature_payload=previous.signature_payload if previous else None,
            )

    def portable_path(self, value: str | Path) -> str:
        path = Path(value)
        if not path.is_absolute():
            parts = path.parts
            if parts and parts[0] == self.workdir.name:
                path = Path(*parts[1:])
            return str(path)
        resolved = path.resolve(strict=False)
        try:
            return str(resolved.relative_to(self.workdir))
        except ValueError:
            if "runs" in resolved.parts:
                index = resolved.parts.index("runs")
                return str(Path(*resolved.parts[index:]))
            return str(resolved)

    def resolve_path(self, value: str | None) -> Path | None:
        if not value:
            return None
        path = Path(value)
        return path if path.is_absolute() else self.workdir / path

    def reconcile_running(self, *, cycle_id: str | None = None) -> None:
        rows = self.connection.execute(
            """
            SELECT task, signature, signature_schema, signature_payload, attempt_path
            FROM task_state
            WHERE cycle_id = ? AND status = 'running'
            """,
            (_cycle_key(cycle_id),),
        ).fetchall()
        for task, signature, schema, payload_json, attempt_path in rows:
            payload = _decode_payload(payload_json)
            attempt = self.resolve_path(attempt_path)
            metadata = attempt / "metadata.json" if attempt else None
            if metadata and metadata.is_file():
                try:
                    record = json.loads(metadata.read_text(encoding="utf-8"))
                    status = str(record["status"])
                    return_code = record.get("return_code")
                    reason = record.get("reason") or "resultado recuperado do registro da tentativa"
                    self.set_status(
                        task,
                        status,
                        return_code,
                        signature,
                        reason,
                        attempt_path,
                        cycle_id=cycle_id,
                        signature_schema=schema,
                        signature_payload=payload,
                    )
                    continue
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            process_record = attempt / "process.json" if attempt else None
            if process_record and process_record.is_file():
                try:
                    process = json.loads(process_record.read_text(encoding="utf-8"))
                    pid = int(process["pid"])
                    if process.get("host") == socket.gethostname():
                        os.kill(pid, 0)
                        self.set_status(
                            task,
                            "unknown",
                            None,
                            signature,
                            f"processo {pid} ainda pode estar ativo neste computador",
                            attempt_path,
                            cycle_id=cycle_id,
                            signature_schema=schema,
                            signature_payload=payload,
                        )
                        continue
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            scheduler_record = attempt / "scheduler.json" if attempt else None
            if scheduler_record and scheduler_record.is_file():
                try:
                    scheduler = json.loads(scheduler_record.read_text(encoding="utf-8"))
                    job_id = str(scheduler["job_id"])
                    self.set_status(
                        task,
                        "unknown",
                        None,
                        signature,
                        f"job PBS {job_id} precisa ser reconciliado com o escalonador",
                        attempt_path,
                        cycle_id=cycle_id,
                        signature_schema=schema,
                        signature_payload=payload,
                    )
                    continue
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            self.set_status(
                task,
                "interrupted",
                None,
                signature,
                "o controlador anterior terminou antes de registrar o resultado",
                attempt_path,
                cycle_id=cycle_id,
                signature_schema=schema,
                signature_payload=payload,
            )

    def tasks_with_status(self, status: str, *, cycle_id: str | None = None) -> list[str]:
        return [
            row[0]
            for row in self.connection.execute(
                """
                SELECT task FROM task_state
                WHERE cycle_id = ? AND status = ?
                ORDER BY task
                """,
                (_cycle_key(cycle_id), status),
            )
        ]

    def reset(
        self,
        tasks: Iterable[str] | None = None,
        *,
        cycle_id: str | None = None,
    ) -> None:
        key = _cycle_key(cycle_id)
        if tasks is None:
            self.connection.execute("DELETE FROM task_state WHERE cycle_id = ?", (key,))
        else:
            self.connection.executemany(
                "DELETE FROM task_state WHERE cycle_id = ? AND task = ?",
                [(key, task) for task in tasks],
            )
        self.connection.commit()

    def record_run(
        self,
        run_id: str,
        run_path: str | Path,
        *,
        cycle_id: str | None = None,
        cycle_time: str | None = None,
        created_at: str | None = None,
    ) -> None:
        self.ensure_cycle(cycle_id, cycle_time)
        self.connection.execute(
            """
            INSERT OR IGNORE INTO run_history(
                run_id, cycle_id, run_path, status, created_at
            ) VALUES (?, ?, ?, 'running', ?)
            """,
            (
                run_id,
                _cycle_key(cycle_id),
                self.portable_path(run_path),
                created_at or _utc_timestamp(),
            ),
        )
        self.connection.commit()

    def finish_run(self, run_id: str, status: str) -> None:
        self.connection.execute(
            "UPDATE run_history SET status = ?, finished_at = ? WHERE run_id = ?",
            (status, _utc_timestamp(), run_id),
        )
        self.connection.commit()

    def record_attempt_started(
        self,
        *,
        run_id: str,
        task: str,
        attempt: int,
        attempt_path: str | Path,
        signature: str | None,
        cycle_id: str | None = None,
        started_at: str | None = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO attempt_history(
                run_id, cycle_id, task, attempt, status, signature,
                attempt_path, started_at, finished_at
            ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, NULL)
            """,
            (
                run_id,
                _cycle_key(cycle_id),
                task,
                attempt,
                signature,
                self.portable_path(attempt_path),
                started_at or _utc_timestamp(),
            ),
        )
        self.connection.commit()

    def record_attempt_finished(
        self,
        *,
        run_id: str,
        task: str,
        attempt: int,
        status: str,
        return_code: int | None,
        reason: str | None,
    ) -> None:
        self.connection.execute(
            """
            UPDATE attempt_history
            SET status = ?, return_code = ?, reason = ?, finished_at = ?
            WHERE run_id = ? AND task = ? AND attempt = ?
            """,
            (status, return_code, reason, _utc_timestamp(), run_id, task, attempt),
        )
        self.connection.commit()

    def record_migration(
        self,
        *,
        source_version: str,
        source_selector: str | None,
        source_workflow_keys: Iterable[str],
        backup_path: str | Path,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO migration_history(
                source_version, source_selector, source_workflow_keys,
                backup_path, migrated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                source_version,
                source_selector,
                json.dumps(sorted(source_workflow_keys)),
                str(backup_path),
                _utc_timestamp(),
            ),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
