import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.core.config import get_settings
from app.core.security import hash_password
from app.core.vm_volumes import compact_vm_volumes_json, normalize_vm_volumes


def _connect() -> sqlite3.Connection:
    db_path = get_settings().db_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
                collection_hour INTEGER NOT NULL DEFAULT 2,
                collection_minute INTEGER NOT NULL DEFAULT 10,
                last_error TEXT,
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

            CREATE TABLE IF NOT EXISTS collection_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT,
                status TEXT NOT NULL,
                message TEXT
            );

            CREATE TABLE IF NOT EXISTS collection_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES collection_runs(id) ON DELETE CASCADE,
                tower_id INTEGER,
                cluster_id TEXT,
                status TEXT NOT NULL,
                message TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS metric_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload_json TEXT NOT NULL,
                collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS latest_vm_volumes (
                tower_id INTEGER NOT NULL,
                cluster_id TEXT NOT NULL,
                vm_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tower_id, cluster_id, vm_id)
            );

            CREATE TABLE IF NOT EXISTS latest_vm_volume_items (
                tower_id INTEGER NOT NULL,
                cluster_id TEXT NOT NULL,
                vm_id TEXT NOT NULL,
                volume_id TEXT NOT NULL,
                name TEXT,
                path TEXT,
                type TEXT,
                size INTEGER,
                used_size INTEGER,
                unique_size INTEGER,
                unique_logical_size INTEGER,
                guest_used_size INTEGER,
                used_size_usage REAL,
                guest_size_usage REAL,
                storage_policy TEXT,
                replica_num INTEGER,
                thin_provision INTEGER,
                ec_k INTEGER,
                ec_m INTEGER,
                collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tower_id, cluster_id, vm_id, volume_id)
            );

            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        _ensure_admin(conn)
        _migrate_latest_vm_volume_storage(conn)


def _ensure_admin(conn: sqlite3.Connection) -> None:
    settings = get_settings()
    existing = conn.execute("SELECT id FROM users WHERE username = ?", (settings.admin_user,)).fetchone()
    if existing:
        return
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
        (settings.admin_user, hash_password(settings.admin_password)),
    )


def _migrate_latest_vm_volume_storage(conn: sqlite3.Connection) -> None:
    migration_name = "latest_vm_volume_items_v1"
    if conn.execute("SELECT 1 FROM schema_migrations WHERE name = ?", (migration_name,)).fetchone():
        return
    existing_items = int(conn.execute("SELECT COUNT(*) FROM latest_vm_volume_items").fetchone()[0])
    if existing_items:
        conn.execute("INSERT OR IGNORE INTO schema_migrations (name) VALUES (?)", (migration_name,))
        return
    rows = conn.execute("SELECT tower_id, cluster_id, vm_id, payload_json, collected_at FROM latest_vm_volumes").fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            payload = []
        normalized = normalize_vm_volumes(payload)
        compact_json = compact_vm_volumes_json(normalized)
        if compact_json != row["payload_json"]:
            conn.execute(
                """
                UPDATE latest_vm_volumes
                SET payload_json = ?
                WHERE tower_id = ? AND cluster_id = ? AND vm_id = ?
                """,
                (compact_json, row["tower_id"], row["cluster_id"], row["vm_id"]),
            )
        conn.execute("DELETE FROM latest_vm_volume_items WHERE tower_id = ? AND cluster_id = ? AND vm_id = ?", (row["tower_id"], row["cluster_id"], row["vm_id"]))
        for index, volume in enumerate(normalized):
            volume_id = str(volume.get("id") or f"volume-{index}")
            conn.execute(
                """
                INSERT OR REPLACE INTO latest_vm_volume_items (
                    tower_id, cluster_id, vm_id, volume_id, name, path, type, size, used_size,
                    unique_size, unique_logical_size, guest_used_size, used_size_usage,
                    guest_size_usage, storage_policy, replica_num, thin_provision, ec_k, ec_m,
                    collected_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["tower_id"],
                    row["cluster_id"],
                    row["vm_id"],
                    volume_id,
                    volume.get("name"),
                    volume.get("path"),
                    volume.get("type"),
                    volume.get("size"),
                    volume.get("used_size"),
                    volume.get("unique_size"),
                    volume.get("unique_logical_size"),
                    volume.get("guest_used_size"),
                    volume.get("used_size_usage"),
                    volume.get("guest_size_usage"),
                    volume.get("elf_storage_policy"),
                    volume.get("elf_storage_policy_replica_num"),
                    int(volume["elf_storage_policy_thin_provision"]) if "elf_storage_policy_thin_provision" in volume else None,
                    volume.get("elf_storage_policy_ec_k"),
                    volume.get("elf_storage_policy_ec_m"),
                    row["collected_at"],
                ),
            )
    conn.execute("INSERT OR IGNORE INTO schema_migrations (name) VALUES (?)", (migration_name,))


def insert_report(payload: dict[str, Any]) -> int:
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO reports (payload_json) VALUES (?)", (json.dumps(payload, ensure_ascii=False),))
        return int(cur.lastrowid)
