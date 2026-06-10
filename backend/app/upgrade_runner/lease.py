from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.upgrade_protocol.constants import RUNNER_CAPABILITIES, RUNNER_PROTOCOL_VERSION


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LeaseManager:
    def __init__(self, database_path: Path, owner: str, *, ttl_seconds: int = 30) -> None:
        self.database_path = Path(database_path)
        self.owner = owner
        self.ttl_seconds = ttl_seconds
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS upgrade_runner_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    instance_id TEXT NOT NULL,
                    runner_version TEXT NOT NULL,
                    protocol_version INTEGER NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS upgrade_task_leases (
                    task_id TEXT PRIMARY KEY,
                    lease_owner TEXT NOT NULL,
                    lease_expires_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0
                );
                """
            )

    def acquire(self, task_id: str, *, revision: int, now: datetime | None = None) -> bool:
        current_time = now or _now()
        expires_at = current_time + timedelta(seconds=self.ttl_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT lease_owner, lease_expires_at FROM upgrade_task_leases WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row and row["lease_owner"] != self.owner:
                existing_expiry = datetime.fromisoformat(row["lease_expires_at"])
                if existing_expiry > current_time:
                    connection.rollback()
                    return False
            connection.execute(
                """
                INSERT INTO upgrade_task_leases (task_id, lease_owner, lease_expires_at, heartbeat_at, revision)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    lease_owner = excluded.lease_owner,
                    lease_expires_at = excluded.lease_expires_at,
                    heartbeat_at = excluded.heartbeat_at,
                    revision = excluded.revision
                """,
                (task_id, self.owner, expires_at.isoformat(), current_time.isoformat(), revision),
            )
            connection.commit()
            return True

    def heartbeat(self, task_id: str, *, revision: int, now: datetime | None = None) -> bool:
        current_time = now or _now()
        expires_at = current_time + timedelta(seconds=self.ttl_seconds)
        with self._connect() as connection:
            result = connection.execute(
                """
                UPDATE upgrade_task_leases
                SET lease_expires_at = ?, heartbeat_at = ?, revision = ?
                WHERE task_id = ? AND lease_owner = ?
                """,
                (expires_at.isoformat(), current_time.isoformat(), revision, task_id, self.owner),
            )
            return result.rowcount == 1

    def release(self, task_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM upgrade_task_leases WHERE task_id = ? AND lease_owner = ?",
                (task_id, self.owner),
            )

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM upgrade_task_leases WHERE task_id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def update_runner_state(self, runner_version: str, *, now: datetime | None = None) -> None:
        heartbeat_at = (now or _now()).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO upgrade_runner_state (
                    id, instance_id, runner_version, protocol_version, capabilities_json, heartbeat_at, updated_at
                ) VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    instance_id = excluded.instance_id,
                    runner_version = excluded.runner_version,
                    protocol_version = excluded.protocol_version,
                    capabilities_json = excluded.capabilities_json,
                    heartbeat_at = excluded.heartbeat_at,
                    updated_at = excluded.updated_at
                """,
                (
                    self.owner,
                    runner_version,
                    RUNNER_PROTOCOL_VERSION,
                    json.dumps(sorted(RUNNER_CAPABILITIES)),
                    heartbeat_at,
                    heartbeat_at,
                ),
            )

    def runner_state(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM upgrade_runner_state WHERE id = 1").fetchone()
        if not row:
            return None
        payload = dict(row)
        payload["capabilities"] = json.loads(payload.pop("capabilities_json"))
        return payload
