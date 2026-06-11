from __future__ import annotations

import sqlite3
import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from app.v2.config import V2Settings
from app.v2.security import hash_password


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


@dataclass
class V2Database:
    settings: V2Settings

    def connect(self) -> sqlite3.Connection:
        self.settings.sqlite_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.settings.sqlite_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        self.settings.ensure_directories()
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    message TEXT,
                    links_json TEXT,
                    logs_json TEXT,
                    steps_json TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS towers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    username TEXT,
                    password_encrypted TEXT,
                    api_token_encrypted TEXT,
                    verify_tls INTEGER NOT NULL DEFAULT 1,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS clusters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tower_id INTEGER NOT NULL REFERENCES towers(id) ON DELETE CASCADE,
                    cluster_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(tower_id, cluster_id)
                );

                CREATE TABLE IF NOT EXISTS vm_latest (
                    tower_id INTEGER NOT NULL,
                    cluster_id TEXT NOT NULL,
                    vm_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    used_bytes INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (tower_id, cluster_id, vm_id)
                );

                CREATE TABLE IF NOT EXISTS vm_volumes (
                    tower_id INTEGER NOT NULL,
                    cluster_id TEXT NOT NULL,
                    vm_id TEXT NOT NULL,
                    volume_id TEXT NOT NULL,
                    name TEXT,
                    path TEXT,
                    size_bytes INTEGER,
                    used_bytes INTEGER,
                    storage_policy TEXT,
                    replica_num INTEGER,
                    thin_provision INTEGER,
                    ec_k INTEGER,
                    ec_m INTEGER,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (tower_id, cluster_id, vm_id, volume_id)
                );

                CREATE TABLE IF NOT EXISTS collection_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL,
                    message TEXT,
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS metric_snapshots (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    metrics_text TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    description TEXT NOT NULL,
                    script_sha256 TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

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
            _ensure_column(conn, "users", "updated_at", "TEXT")
            conn.execute("UPDATE users SET updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)")
            _ensure_column(conn, "tasks", "links_json", "TEXT")
            _ensure_column(conn, "tasks", "logs_json", "TEXT")
            _ensure_column(conn, "tasks", "steps_json", "TEXT")
            _ensure_column(conn, "tasks", "severity", "TEXT")
            _ensure_column(conn, "tasks", "seen_at", "TEXT")
            _ensure_column(conn, "tasks", "acknowledged_at", "TEXT")
            _ensure_schema_migrations_table(conn)
            _backfill_v1_latest_vm_payloads(conn)
            _backfill_legacy_volume_items(conn)
            self._ensure_admin(conn)

    def _ensure_admin(self, conn: sqlite3.Connection) -> None:
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (self.settings.admin_user,)).fetchone()
        if existing:
            return
        conn.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
            (self.settings.admin_user, hash_password(self.settings.admin_password)),
        )


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(schema_migrations)").fetchall()}
    if {"id", "version", "description", "script_sha256", "applied_at"}.issubset(columns):
        return
    legacy_rows = []
    if "name" in columns:
        legacy_rows = conn.execute("SELECT name, applied_at FROM schema_migrations").fetchall()
        conn.execute("ALTER TABLE schema_migrations RENAME TO schema_migrations_legacy")
    else:
        conn.execute("DROP TABLE IF EXISTS schema_migrations")
    conn.execute(
        """
        CREATE TABLE schema_migrations (
            id TEXT PRIMARY KEY,
            version TEXT NOT NULL,
            description TEXT NOT NULL,
            script_sha256 TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    for row in legacy_rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO schema_migrations (id, version, description, script_sha256, applied_at)
            VALUES (?, 'legacy', ?, '', COALESCE(?, CURRENT_TIMESTAMP))
            """,
            (row["name"], row["name"], row["applied_at"]),
        )
    conn.execute("DROP TABLE IF EXISTS schema_migrations_legacy")


def _backfill_v1_latest_vm_payloads(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "latest_vm_volumes"):
        return
    rows = conn.execute("SELECT tower_id, cluster_id, vm_id, payload_json, collected_at FROM latest_vm_volumes").fetchall()
    for row in rows:
        volumes = _loads_volume_payload(row["payload_json"])
        used_bytes = sum(_int_or_none(volume.get("used_bytes"), volume.get("used_size")) or 0 for volume in volumes)
        conn.execute(
            """
            INSERT OR IGNORE INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes, updated_at)
            VALUES (?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
            """,
            (row["tower_id"], row["cluster_id"], row["vm_id"], row["vm_id"], used_bytes, row["collected_at"]),
        )
        for index, volume in enumerate(volumes):
            conn.execute(
                """
                INSERT OR IGNORE INTO vm_volumes (
                    tower_id, cluster_id, vm_id, volume_id, name, path, size_bytes, used_bytes,
                    storage_policy, replica_num, thin_provision, ec_k, ec_m, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
                """,
                (
                    row["tower_id"],
                    row["cluster_id"],
                    row["vm_id"],
                    str(volume.get("volume_id") or volume.get("id") or f"volume-{index}"),
                    volume.get("name"),
                    volume.get("path"),
                    _int_or_none(volume.get("size_bytes"), volume.get("size")),
                    _int_or_none(volume.get("used_bytes"), volume.get("used_size")),
                    volume.get("storage_policy") or volume.get("elf_storage_policy"),
                    _int_or_none(volume.get("replica_num"), volume.get("elf_storage_policy_replica_num")),
                    _bool_to_int(volume.get("thin_provision", volume.get("elf_storage_policy_thin_provision"))),
                    _int_or_none(volume.get("ec_k"), volume.get("elf_storage_policy_ec_k")),
                    _int_or_none(volume.get("ec_m"), volume.get("elf_storage_policy_ec_m")),
                    row["collected_at"],
                ),
            )
    conn.execute("DROP TABLE latest_vm_volumes")
    conn.execute(
        """
        INSERT OR IGNORE INTO schema_migrations (id, version, description, script_sha256)
        VALUES ('drop_legacy_latest_vm_volumes', 'legacy', 'drop_legacy_latest_vm_volumes', '')
        """
    )


def _backfill_legacy_volume_items(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "latest_vm_volume_items"):
        return
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(latest_vm_volume_items)").fetchall()}
    required = {"tower_id", "cluster_id", "vm_id", "volume_id"}
    if required.issubset(columns):
        conn.execute(
            """
            INSERT OR IGNORE INTO vm_volumes (
                tower_id, cluster_id, vm_id, volume_id, name, path, size_bytes, used_bytes,
                storage_policy, replica_num, thin_provision, ec_k, ec_m, updated_at
            )
            SELECT
                tower_id,
                cluster_id,
                vm_id,
                volume_id,
                name,
                path,
                size,
                used_size,
                storage_policy,
                replica_num,
                thin_provision,
                ec_k,
                ec_m,
                COALESCE(collected_at, CURRENT_TIMESTAMP)
            FROM latest_vm_volume_items
            """
        )
    conn.execute("DROP TABLE latest_vm_volume_items")
    conn.execute(
        """
        INSERT OR IGNORE INTO schema_migrations (id, version, description, script_sha256)
        VALUES ('drop_legacy_latest_vm_volume_items', 'legacy', 'drop_legacy_latest_vm_volume_items', '')
        """
    )


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None


def _loads_volume_payload(payload_json: Any) -> list[dict[str, Any]]:
    try:
        payload = json.loads(payload_json)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _int_or_none(*values: object) -> int | None:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
    return None


def _bool_to_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if value else 0
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return 1
    if text in {"false", "0", "no", "n"}:
        return 0
    return None
