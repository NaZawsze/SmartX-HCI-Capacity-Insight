import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.core.config import get_settings
from app.core.security import hash_password


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
            """
        )
        _ensure_admin(conn)


def _ensure_admin(conn: sqlite3.Connection) -> None:
    settings = get_settings()
    existing = conn.execute("SELECT id FROM users WHERE username = ?", (settings.admin_user,)).fetchone()
    if existing:
        return
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
        (settings.admin_user, hash_password(settings.admin_password)),
    )


def insert_report(payload: dict[str, Any]) -> int:
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO reports (payload_json) VALUES (?)", (json.dumps(payload, ensure_ascii=False),))
        return int(cur.lastrowid)
