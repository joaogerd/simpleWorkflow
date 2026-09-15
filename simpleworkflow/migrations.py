from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .locking import WorkflowLock
from .state import STATE_SCHEMA_VERSION, WorkflowState

_HASHED_STATE_KEY = re.compile(r"^(?P<name>.+)@(?P<digest>[0-9a-f]{12})$")
_CYCLE_NAME = re.compile(r"^(?P<base>.+)__(?P<cycle>\d{8}T\d{6}Z)$")


class MigrationError(RuntimeError):
    """Base class for state migration failures."""


class AmbiguousLegacyState(MigrationError):
    """Raised when a legacy database contains more than one logical workflow."""


@dataclass(frozen=True)
class LegacyGroup:
    """One logical workflow instance encoded by legacy workflow keys."""

    selector: str
    base_name: str
    workflow_keys: tuple[str, ...]
    cycle_by_key: dict[str, str | None]


@dataclass(frozen=True)
class StateInspection:
    """Read-only description of one state database."""

    kind: str
    schema_version: int | None = None
    legacy_version: str | None = None
    groups: tuple[LegacyGroup, ...] = ()


@dataclass(frozen=True)
class MigrationResult:
    """Outcome of one migration request."""

    inspection: StateInspection
    migrated: bool
    backup_path: Path | None = None
    selected_group: LegacyGroup | None = None


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _filename_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fsync_file(path: Path) -> None:
    """Force one completed file to stable storage before publishing related metadata."""
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    """Persist directory-entry changes on the POSIX filesystems used by simpleWorkflow."""
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def _split_legacy_key(key: str, *, hashed: bool) -> tuple[str, str | None, str | None]:
    effective = key
    digest: str | None = None
    if hashed:
        match = _HASHED_STATE_KEY.fullmatch(key)
        if match:
            effective = match.group("name")
            digest = match.group("digest")
    cycle_match = _CYCLE_NAME.fullmatch(effective)
    if cycle_match:
        return cycle_match.group("base"), cycle_match.group("cycle"), digest
    return effective, None, digest


def _legacy_groups(keys: list[str], legacy_version: str) -> tuple[LegacyGroup, ...]:
    if legacy_version == "0.2.x":
        return tuple(
            LegacyGroup(
                selector=key,
                base_name=key,
                workflow_keys=(key,),
                cycle_by_key={key: None},
            )
            for key in sorted(keys)
        )

    grouped: dict[tuple[str, str | None], list[tuple[str, str | None]]] = {}
    for key in keys:
        base, cycle_id, digest = _split_legacy_key(key, hashed=True)
        grouped.setdefault((base, digest), []).append((key, cycle_id))

    groups: list[LegacyGroup] = []
    for (base, digest), members in sorted(grouped.items(), key=lambda item: str(item[0])):
        selector = f"{base}@{digest}" if digest else base
        groups.append(
            LegacyGroup(
                selector=selector,
                base_name=base,
                workflow_keys=tuple(sorted(key for key, _ in members)),
                cycle_by_key={key: cycle for key, cycle in members},
            )
        )
    return tuple(groups)


def inspect_state(path: str | Path) -> StateInspection:
    """Inspect a state database without changing it."""
    state_path = Path(path)
    if not state_path.exists():
        return StateInspection(kind="missing")
    uri = state_path.resolve(strict=False).as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        tables = _table_names(connection)
        if not tables:
            return StateInspection(kind="empty")
        if "schema_info" in tables:
            row = connection.execute(
                "SELECT schema_version FROM schema_info WHERE singleton = 1"
            ).fetchone()
            if row is None:
                return StateInspection(kind="invalid")
            return StateInspection(kind="versioned", schema_version=int(row[0]))
        if "task_state" not in tables:
            return StateInspection(kind="unknown")
        columns = _table_columns(connection, "task_state")
        if "workflow" not in columns or "task" not in columns or "status" not in columns:
            return StateInspection(kind="unknown")
        legacy_version = "0.3.x" if {"reason", "attempt_dir"} <= columns else "0.2.x"
        keys = [
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT workflow FROM task_state ORDER BY workflow"
            )
        ]
        return StateInspection(
            kind="legacy",
            legacy_version=legacy_version,
            groups=_legacy_groups(keys, legacy_version),
        )
    finally:
        connection.close()


def _select_group(
    inspection: StateInspection,
    selector: str | None,
    *,
    fallback_name: str | None = None,
) -> LegacyGroup:
    groups = inspection.groups
    if not groups:
        if fallback_name is None:
            raise MigrationError("o banco legado não contém identidade de workflow para migrar")
        if selector is not None and selector != fallback_name:
            raise AmbiguousLegacyState(
                f"--legacy-workflow {selector!r} não corresponde ao workflow vazio "
                f"{fallback_name!r} informado pelo YAML"
            )
        return LegacyGroup(
            selector=fallback_name,
            base_name=fallback_name,
            workflow_keys=(),
            cycle_by_key={},
        )
    if selector is None:
        if len(groups) == 1:
            return groups[0]
        choices = ", ".join(group.selector for group in groups)
        raise AmbiguousLegacyState(
            "o banco legado contém mais de um workflow lógico; nenhuma migração foi feita. "
            f"Instâncias encontradas: {choices}. Copie o .simpleworkflow para o root correto "
            "e execute novamente com --legacy-workflow <instância>."
        )
    matches = [
        group
        for group in groups
        if selector == group.selector or selector in group.workflow_keys
    ]
    if len(matches) != 1:
        choices = ", ".join(group.selector for group in groups)
        raise AmbiguousLegacyState(
            f"--legacy-workflow {selector!r} não identifica uma única instância. "
            f"Use uma destas opções: {choices}"
        )
    return matches[0]


def _effective_name(legacy_key: str) -> str:
    match = _HASHED_STATE_KEY.fullmatch(legacy_key)
    return match.group("name") if match else legacy_key


def _cycle_time(cycle_id: str) -> str:
    parsed = datetime.strptime(cycle_id, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _signature_parts(
    record: dict[str, Any] | None,
) -> tuple[str | None, int | None, dict[str, Any] | None]:
    if not record:
        return None, None, None
    signature = record.get("signature")
    if isinstance(signature, dict):
        value = signature.get("value")
        payload = signature.get("payload")
        schema = payload.get("signature_schema") if isinstance(payload, dict) else None
        return (
            str(value) if value is not None else None,
            int(schema) if isinstance(schema, int) else None,
            payload if isinstance(payload, dict) else None,
        )
    if isinstance(signature, str):
        return signature, None, None
    return None, None, None


def _scan_legacy_runs(
    workdir: Path,
    group: LegacyGroup,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[tuple[str, str, str], dict[str, Any]],
]:
    run_rows: list[dict[str, Any]] = []
    attempt_rows: list[dict[str, Any]] = []
    signature_records: dict[tuple[str, str, str], dict[str, Any]] = {}
    allowed_effective = {_effective_name(key): key for key in group.workflow_keys}
    runs_root = workdir / "runs"
    if not runs_root.is_dir():
        return run_rows, attempt_rows, signature_records

    for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
        run_record = _load_json(run_dir / "run.json")
        if not run_record:
            continue
        run_workflow = str(run_record.get("workflow", ""))
        legacy_key = allowed_effective.get(run_workflow)
        if legacy_key is None:
            continue
        cycle_id = group.cycle_by_key.get(legacy_key)
        attempts_for_run: list[dict[str, Any]] = []
        tasks_dir = run_dir / "tasks"
        if tasks_dir.is_dir():
            for attempt_dir in sorted(tasks_dir.glob("*/attempt-*")):
                if not attempt_dir.is_dir():
                    continue
                metadata = _load_json(attempt_dir / "metadata.json")
                started = _load_json(attempt_dir / "started.json")
                record = metadata or started or {}
                task = record.get("task")
                if not isinstance(task, str) or not task:
                    continue
                attempt_value = record.get("attempt")
                if not isinstance(attempt_value, int):
                    try:
                        attempt_value = int(attempt_dir.name.split("-")[-1])
                    except ValueError:
                        attempt_value = 1
                sig_value, sig_schema, sig_payload = _signature_parts(metadata or started)
                status = (
                    str(metadata.get("status"))
                    if metadata and metadata.get("status")
                    else "running"
                )
                return_code = metadata.get("return_code") if metadata else None
                reason = metadata.get("reason") if metadata else None
                started_at = started.get("started_at") if started else None
                finished_at = metadata.get("recorded_at") if metadata else None
                row = {
                    "run_id": str(run_record.get("run_id") or run_dir.name),
                    "cycle_id": cycle_id or "",
                    "task": task,
                    "attempt": attempt_value,
                    "status": status,
                    "return_code": return_code if isinstance(return_code, int) else None,
                    "signature": sig_value,
                    "signature_schema": sig_schema,
                    "signature_payload": sig_payload,
                    "reason": str(reason) if reason is not None else None,
                    "attempt_path": str(attempt_dir.relative_to(workdir)),
                    "started_at": str(started_at) if started_at else None,
                    "finished_at": str(finished_at) if finished_at else None,
                    "legacy_workflow": legacy_key,
                }
                attempts_for_run.append(row)
                if sig_value and sig_payload:
                    signature_records[(legacy_key, task, sig_value)] = row
        run_status = (
            "completed"
            if attempts_for_run
            and all(row["status"] != "running" for row in attempts_for_run)
            else "incomplete"
        )
        run_rows.append(
            {
                "run_id": str(run_record.get("run_id") or run_dir.name),
                "cycle_id": cycle_id or "",
                "run_path": str(run_dir.relative_to(workdir)),
                "status": run_status,
                "created_at": str(run_record.get("created_at") or _utc_timestamp()),
                "finished_at": max(
                    (
                        row["finished_at"]
                        for row in attempts_for_run
                        if row["finished_at"]
                    ),
                    default=None,
                ),
            }
        )
        attempt_rows.extend(attempts_for_run)
    return run_rows, attempt_rows, signature_records


def _legacy_rows(
    connection: sqlite3.Connection,
    inspection: StateInspection,
    group: LegacyGroup,
) -> list[dict[str, Any]]:
    if not group.workflow_keys:
        return []
    columns = _table_columns(connection, "task_state")
    selected = ["workflow", "task", "status", "return_code", "signature", "updated_at"]
    if "reason" in columns:
        selected.append("reason")
    if "attempt_dir" in columns:
        selected.append("attempt_dir")
    placeholders = ",".join("?" for _ in group.workflow_keys)
    query = (
        f"SELECT {', '.join(selected)} FROM task_state "
        f"WHERE workflow IN ({placeholders}) ORDER BY workflow, task"
    )
    rows: list[dict[str, Any]] = []
    for values in connection.execute(query, group.workflow_keys):
        rows.append(dict(zip(selected, values)))
    return rows


def _backup_database(source: Path, legacy_version: str) -> Path:
    backups = source.parent / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stem = legacy_version.replace(".", "-")
    timestamp = _filename_timestamp()
    candidate = backups / f"state-v{stem}-before-migration-{timestamp}.sqlite3"
    suffix = 1
    while candidate.exists():
        candidate = backups / f"state-v{stem}-before-migration-{timestamp}-{suffix}.sqlite3"
        suffix += 1
    source_connection = sqlite3.connect(source)
    backup_connection = sqlite3.connect(candidate)
    try:
        source_connection.backup(backup_connection)
        backup_connection.commit()
    finally:
        backup_connection.close()
        source_connection.close()
    _fsync_file(candidate)
    _fsync_directory(backups)
    return candidate


def _portable_legacy_attempt(
    state: WorkflowState,
    raw: str | None,
    fallback: str | None,
) -> str | None:
    if fallback:
        return fallback
    if not raw:
        return None
    path = Path(raw)
    if path.is_absolute():
        if "runs" in path.parts:
            index = path.parts.index("runs")
            return str(Path(*path.parts[index:]))
        return str(path)
    parts = path.parts
    if parts and parts[0] == state.workdir.name:
        return str(Path(*parts[1:]))
    if "runs" in parts:
        index = parts.index("runs")
        return str(Path(*parts[index:]))
    return str(path)


def _validate_migratable(inspection: StateInspection, state_file: Path) -> None:
    if inspection.kind == "missing":
        raise MigrationError(f"não existe banco de estado em {state_file}")
    if inspection.kind != "legacy" or not inspection.legacy_version:
        raise MigrationError(f"o formato do banco {state_file} não é reconhecido")


def _migrate_state_locked(
    *,
    state_file: Path,
    workflow_name: str,
    source_path: str | Path,
    legacy_selector: str | None,
) -> MigrationResult:
    """Perform migration while the workflow lock is already held."""
    inspection = inspect_state(state_file)
    if inspection.kind == "versioned":
        if inspection.schema_version == STATE_SCHEMA_VERSION:
            return MigrationResult(inspection=inspection, migrated=False)
        raise MigrationError(
            f"schema {inspection.schema_version} não pode ser migrado por esta versão "
            f"(schema atual: {STATE_SCHEMA_VERSION})"
        )
    _validate_migratable(inspection, state_file)
    assert inspection.legacy_version is not None

    group = _select_group(
        inspection,
        legacy_selector,
        fallback_name=workflow_name,
    )
    legacy_connection = sqlite3.connect(state_file)
    try:
        task_rows = _legacy_rows(legacy_connection, inspection, group)
    finally:
        legacy_connection.close()
    run_rows, attempt_rows, signature_records = _scan_legacy_runs(state_file.parent, group)
    backup_path = _backup_database(state_file, inspection.legacy_version)

    temporary = state_file.with_name(f".{state_file.name}.migrating-{uuid.uuid4().hex}")
    new_state: WorkflowState | None = None
    try:
        new_state = WorkflowState(
            temporary,
            workflow_name=workflow_name,
            source_path=source_path,
        )
        connection = new_state.connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            for cycle_id in group.cycle_by_key.values():
                if cycle_id:
                    now = _utc_timestamp()
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO cycle_state(
                            cycle_id, cycle_time, created_at, updated_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (cycle_id, _cycle_time(cycle_id), now, now),
                    )

            latest_attempt_by_task: dict[tuple[str, str], dict[str, Any]] = {}
            for attempt in attempt_rows:
                latest_attempt_by_task[(attempt["legacy_workflow"], attempt["task"])] = attempt

            for row in task_rows:
                legacy_key = str(row["workflow"])
                task = str(row["task"])
                cycle_id = group.cycle_by_key.get(legacy_key) or ""
                signature = str(row["signature"]) if row.get("signature") else None
                signature_record = (
                    signature_records.get((legacy_key, task, signature)) if signature else None
                )
                fallback_attempt = latest_attempt_by_task.get((legacy_key, task))
                payload = signature_record.get("signature_payload") if signature_record else None
                schema = signature_record.get("signature_schema") if signature_record else None
                attempt_path = _portable_legacy_attempt(
                    new_state,
                    str(row.get("attempt_dir")) if row.get("attempt_dir") else None,
                    fallback_attempt.get("attempt_path") if fallback_attempt else None,
                )
                status = str(row["status"])
                reason = str(row.get("reason")) if row.get("reason") else None
                if inspection.legacy_version == "0.2.x" and status == "running":
                    status = "unknown"
                    reason = (
                        "tarefa estava marcada como running no estado 0.2.x; "
                        "verifique o processo/produtos antes de resetar"
                    )
                payload_json = (
                    json.dumps(payload, sort_keys=True, separators=(",", ":"))
                    if isinstance(payload, dict)
                    else None
                )
                timestamp = str(row.get("updated_at") or _utc_timestamp())
                connection.execute(
                    """
                    INSERT INTO task_state(
                        cycle_id, task, status, return_code, signature, signature_schema,
                        signature_payload, reason, attempt_path, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cycle_id,
                        task,
                        status,
                        row.get("return_code"),
                        signature,
                        schema,
                        payload_json,
                        reason,
                        attempt_path,
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO state_event(
                        cycle_id, task, status, return_code, reason, attempt_path, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cycle_id,
                        task,
                        status,
                        row.get("return_code"),
                        reason,
                        attempt_path,
                        timestamp,
                    ),
                )

            for run in run_rows:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO run_history(
                        run_id, cycle_id, run_path, status, created_at, finished_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run["run_id"],
                        run["cycle_id"],
                        run["run_path"],
                        run["status"],
                        run["created_at"],
                        run["finished_at"],
                    ),
                )
            for attempt in attempt_rows:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO attempt_history(
                        run_id, cycle_id, task, attempt, status, return_code,
                        signature, reason, attempt_path, started_at, finished_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        attempt["run_id"],
                        attempt["cycle_id"],
                        attempt["task"],
                        attempt["attempt"],
                        attempt["status"],
                        attempt["return_code"],
                        attempt["signature"],
                        attempt["reason"],
                        attempt["attempt_path"],
                        attempt["started_at"],
                        attempt["finished_at"],
                    ),
                )
            connection.execute(
                """
                INSERT INTO migration_history(
                    source_version, source_selector, source_workflow_keys,
                    backup_path, migrated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    inspection.legacy_version,
                    group.selector,
                    json.dumps(sorted(group.workflow_keys)),
                    new_state.portable_path(backup_path),
                    _utc_timestamp(),
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        new_state.close()
        new_state = None
        _fsync_file(temporary)
    except Exception:
        if new_state is not None:
            new_state.close()
        temporary.unlink(missing_ok=True)
        raise

    try:
        os.replace(temporary, state_file)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise MigrationError(
            "não foi possível instalar o banco migrado; o state.sqlite3 legado foi "
            f"preservado e o backup permanece em {backup_path}"
        ) from error

    _fsync_directory(state_file.parent)
    return MigrationResult(
        inspection=inspection,
        migrated=True,
        backup_path=backup_path,
        selected_group=group,
    )


def migrate_state(
    *,
    state_path: str | Path,
    workflow_name: str,
    source_path: str | Path,
    legacy_selector: str | None = None,
) -> MigrationResult:
    """Migrate one legacy database safely under the workflow's local lock."""
    state_file = Path(state_path)
    inspection = inspect_state(state_file)
    if inspection.kind == "versioned":
        if inspection.schema_version == STATE_SCHEMA_VERSION:
            return MigrationResult(inspection=inspection, migrated=False)
        raise MigrationError(
            f"schema {inspection.schema_version} não pode ser migrado por esta versão "
            f"(schema atual: {STATE_SCHEMA_VERSION})"
        )
    _validate_migratable(inspection, state_file)

    with WorkflowLock(state_file.parent, workflow_name):
        return _migrate_state_locked(
            state_file=state_file,
            workflow_name=workflow_name,
            source_path=source_path,
            legacy_selector=legacy_selector,
        )
