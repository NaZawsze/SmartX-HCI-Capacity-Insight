from __future__ import annotations

import sqlite3
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
                    name TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            _ensure_column(conn, "tasks", "links_json", "TEXT")
            _ensure_column(conn, "tasks", "logs_json", "TEXT")
            _ensure_column(conn, "tasks", "steps_json", "TEXT")
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
