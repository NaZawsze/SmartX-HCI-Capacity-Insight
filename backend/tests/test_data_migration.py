import tarfile
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.core.vm_volumes import normalize_vm_volumes
from app.db import init_db
from app.services import data_migration
from app.services.data_migration import _build_migration_manifest, _create_import_backup, _merge_sqlite_database


def test_create_import_backup_includes_database_and_prometheus_blocks(tmp_path, monkeypatch) -> None:
    data_path = tmp_path / "app"
    prometheus_path = tmp_path / "prometheus"
    backup_path = tmp_path / "backups"
    data_path.mkdir()
    prometheus_path.mkdir()
    (data_path / "smartx.db").write_text("db", encoding="utf-8")
    (data_path / "upgrades").mkdir()
    (data_path / "upgrades" / "runtime.txt").write_text("skip", encoding="utf-8")
    block = prometheus_path / "01ABC"
    block.mkdir()
    (block / "meta.json").write_text("{}", encoding="utf-8")
    (prometheus_path / "wal").mkdir()
    (prometheus_path / "wal" / "runtime").write_text("skip", encoding="utf-8")

    monkeypatch.setattr(
        "app.services.data_migration.get_settings",
        lambda: SimpleNamespace(data_path=data_path, prometheus_data_path=prometheus_path, backup_path=backup_path),
    )
    task = {"task_id": "abc", "logs": []}

    backup = _create_import_backup(task)

    assert backup.exists()
    assert task["backup_path"] == str(backup)
    with tarfile.open(backup, mode="r:gz") as archive:
        names = set(archive.getnames())
    assert "manifest.json" in names
    assert "smartx-data/smartx.db" in names
    assert "prometheus-data/01ABC/meta.json" in names
    assert "smartx-data/upgrades/runtime.txt" not in names
    assert "prometheus-data/wal/runtime" not in names


def test_normalize_vm_volumes_drops_unneeded_tower_payload_fields() -> None:
    volumes = normalize_vm_volumes([
        {
            "id": "vol-1",
            "name": "data",
            "path": "iscsi://example",
            "size": "100",
            "used_size": "40",
            "unique_size": "80",
            "elf_storage_policy_replica_num": "2",
            "cluster": {"id": "cluster", "name": "cluster"},
            "lun": {"id": "lun"},
            "vm_disks": [{"id": "disk"}],
            "labels": [{"key": "unused"}],
            "description": "unused tower raw text",
        }
    ])

    assert volumes == [
        {
            "id": "vol-1",
            "name": "data",
            "path": "iscsi://example",
            "size": 100,
            "used_size": 40,
            "unique_size": 80,
            "elf_storage_policy_replica_num": 2,
        }
    ]


def test_merge_old_latest_vm_volumes_payload_compacts_and_creates_items(tmp_path, monkeypatch) -> None:
    target_db = tmp_path / "target.db"
    source_db = tmp_path / "source.db"
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(db_path=target_db, admin_user="admin", admin_password="password"))
    monkeypatch.setattr("app.db.get_settings", lambda: SimpleNamespace(db_path=target_db, admin_user="admin", admin_password="password"))
    monkeypatch.setattr("app.services.data_migration.get_settings", lambda: SimpleNamespace(db_path=target_db, prometheus_data_path=tmp_path / "prometheus"))

    init_db()
    with sqlite3.connect(target_db) as conn:
        conn.execute("INSERT INTO towers (id, name, base_url) VALUES (1, 'Tower', 'https://tower')")
        conn.execute("INSERT INTO clusters (tower_id, cluster_id, name) VALUES (1, 'c1', 'Cluster')")

    with sqlite3.connect(source_db) as conn:
        conn.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE towers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, base_url TEXT NOT NULL, username TEXT, password_encrypted TEXT, api_token_encrypted TEXT, verify_tls INTEGER NOT NULL DEFAULT 1, enabled INTEGER NOT NULL DEFAULT 1, collection_hour INTEGER NOT NULL DEFAULT 2, collection_minute INTEGER NOT NULL DEFAULT 10, last_error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE clusters (id INTEGER PRIMARY KEY AUTOINCREMENT, tower_id INTEGER NOT NULL, cluster_id TEXT NOT NULL, name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(tower_id, cluster_id));
            CREATE TABLE collection_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, finished_at TEXT, status TEXT NOT NULL, message TEXT);
            CREATE TABLE collection_items (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL, tower_id INTEGER, cluster_id TEXT, status TEXT NOT NULL, message TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE reports (id INTEGER PRIMARY KEY AUTOINCREMENT, generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, payload_json TEXT NOT NULL);
            CREATE TABLE metric_samples (id INTEGER PRIMARY KEY AUTOINCREMENT, payload_json TEXT NOT NULL, collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE latest_vm_volumes (tower_id INTEGER NOT NULL, cluster_id TEXT NOT NULL, vm_id TEXT NOT NULL, payload_json TEXT NOT NULL, collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (tower_id, cluster_id, vm_id));
            """
        )
        conn.execute("INSERT INTO users (username, password_hash) VALUES ('incoming', 'hash')")
        conn.execute("INSERT INTO towers (id, name, base_url) VALUES (1, 'Tower', 'https://tower')")
        conn.execute("INSERT INTO clusters (tower_id, cluster_id, name) VALUES (1, 'c1', 'Cluster')")
        payload = [
            {
                "id": "vol-1",
                "name": "os",
                "size": 100,
                "used_size": 40,
                "cluster": {"name": "raw"},
                "lun": {"id": "raw"},
                "vm_disks": [{"id": "raw"}],
            }
        ]
        conn.execute("INSERT INTO latest_vm_volumes (tower_id, cluster_id, vm_id, payload_json) VALUES (1, 'c1', 'vm-1', ?)", (json.dumps(payload),))

    summary = _merge_sqlite_database(source_db, target_db)

    assert summary["status"] == "merged_database"
    with sqlite3.connect(target_db) as conn:
        row = conn.execute("SELECT payload_json FROM latest_vm_volumes WHERE vm_id = 'vm-1'").fetchone()
        compact = json.loads(row[0])
        assert compact == [{"id": "vol-1", "name": "os", "size": 100, "used_size": 40}]
        assert "cluster" not in compact[0]
        item = conn.execute("SELECT volume_id, name, size, used_size FROM latest_vm_volume_items WHERE vm_id = 'vm-1'").fetchone()
        assert item == ("vol-1", "os", 100, 40)


def test_migration_manifest_records_sqlite_and_prometheus_summary(tmp_path) -> None:
    app_path = tmp_path / "app"
    prometheus_path = tmp_path / "prometheus"
    app_path.mkdir()
    prometheus_path.mkdir()
    db_path = app_path / "smartx.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE latest_vm_volumes (payload_json TEXT)")
        conn.execute("CREATE TABLE latest_vm_volume_items (id INTEGER)")
        conn.execute("INSERT INTO latest_vm_volumes VALUES ('[]')")
        conn.execute("INSERT INTO latest_vm_volume_items VALUES (1)")
    block = prometheus_path / "01ABC"
    block.mkdir()
    (block / "meta.json").write_text("{}", encoding="utf-8")
    (prometheus_path / "wal").mkdir()

    manifest = _build_migration_manifest(datetime.now(timezone.utc), app_path, prometheus_path)

    assert manifest["version"] == 2
    assert manifest["sqlite"]["tables"]["latest_vm_volumes"] == 1
    assert manifest["sqlite"]["latest_vm_volume_items"] == 1
    assert manifest["prometheus"]["block_count"] == 1
    assert manifest["prometheus"]["runtime_entries_skipped"] == ["wal"]
