from __future__ import annotations

import io
import json
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile

from app.core.config import get_settings
from app.db import init_db


ARCHIVE_MEDIA_TYPE = "application/gzip"
MANIFEST_NAME = "manifest.json"
APP_DATA_DIR = "smartx-data"
PROMETHEUS_DATA_DIR = "prometheus-data"
DB_FILENAME = "smartx.db"
MERGE_MODE = "merge"
OVERWRITE_MODE = "overwrite"


PROMETHEUS_RUNTIME_ENTRIES = {"chunks_head", "lock", "queries.active", "wal"}


def build_migration_archive() -> tuple[bytes, str]:
    settings = get_settings()
    app_data_path = settings.data_path
    prometheus_data_path = settings.prometheus_data_path
    generated_at = datetime.now(timezone.utc)
    manifest = {
        "format": "smartx-storage-forecast-migration",
        "version": 1,
        "generated_at": generated_at.isoformat(),
        "contains": {
            APP_DATA_DIR: app_data_path.exists(),
            PROMETHEUS_DATA_DIR: prometheus_data_path.exists(),
        },
    }

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        manifest_info = tarfile.TarInfo(MANIFEST_NAME)
        manifest_info.size = len(manifest_bytes)
        manifest_info.mtime = int(generated_at.timestamp())
        archive.addfile(manifest_info, io.BytesIO(manifest_bytes))
        _add_directory(archive, app_data_path, APP_DATA_DIR)
        _add_directory(archive, prometheus_data_path, PROMETHEUS_DATA_DIR)

    filename = f"smartx-storage-migration-{generated_at.strftime('%Y%m%d%H%M%S')}.tar.gz"
    return buffer.getvalue(), filename


async def restore_migration_archive(upload: UploadFile, confirmed: bool, mode: str = MERGE_MODE) -> dict[str, Any]:
    normalized_mode = mode if mode in {MERGE_MODE, OVERWRITE_MODE} else MERGE_MODE
    if normalized_mode == OVERWRITE_MODE and not confirmed:
        raise HTTPException(status_code=400, detail="覆盖导入会清空当前系统数据，请先勾选确认。")
    content = await upload.read()
    if not content:
        raise HTTPException(status_code=400, detail="导入文件为空。")

    settings = get_settings()
    with tempfile.TemporaryDirectory(prefix="smartx-migration-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        try:
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
                _validate_archive_members(archive)
                archive.extractall(temp_dir)
        except (tarfile.TarError, OSError) as exc:
            raise HTTPException(status_code=400, detail=f"无法读取导入包：{exc}") from exc

        manifest = _read_manifest(temp_dir / MANIFEST_NAME)
        if manifest.get("format") != "smartx-storage-forecast-migration":
            raise HTTPException(status_code=400, detail="导入包格式不正确。")

        if normalized_mode == OVERWRITE_MODE:
            result = _restore_overwrite(temp_dir, settings.data_path, settings.prometheus_data_path)
            message = "数据覆盖导入完成，请重启 web-api、collector-worker 和 prometheus 使数据完全生效。"
        else:
            result = _restore_merge(temp_dir, settings.data_path, settings.prometheus_data_path)
            message = "数据补全导入完成，已保留当前系统已有数据；请重启 web-api、collector-worker 和 prometheus 使数据完全生效。"

    return {
        "ok": True,
        "mode": normalized_mode,
        "restored": result["restored"],
        "summary": result["summary"],
        "message": message,
    }


def _restore_overwrite(temp_dir: Path, app_target: Path, prometheus_target: Path) -> dict[str, Any]:
    restored: list[str] = []
    app_source = temp_dir / APP_DATA_DIR
    prometheus_source = temp_dir / PROMETHEUS_DATA_DIR
    if app_source.exists():
        _replace_directory(app_source, app_target)
        restored.append(APP_DATA_DIR)
    if prometheus_source.exists():
        _replace_directory(prometheus_source, prometheus_target)
        restored.append(PROMETHEUS_DATA_DIR)
    return {"restored": restored, "summary": {"mode": OVERWRITE_MODE}}


def _restore_merge(temp_dir: Path, app_target: Path, prometheus_target: Path) -> dict[str, Any]:
    restored: list[str] = []
    summary: dict[str, Any] = {"mode": MERGE_MODE}
    app_source = temp_dir / APP_DATA_DIR
    prometheus_source = temp_dir / PROMETHEUS_DATA_DIR
    if app_source.exists():
        app_summary = _merge_app_data(app_source, app_target)
        summary[APP_DATA_DIR] = app_summary
        restored.append(APP_DATA_DIR)
    if prometheus_source.exists():
        prometheus_summary = _merge_prometheus_data(prometheus_source, prometheus_target)
        summary[PROMETHEUS_DATA_DIR] = prometheus_summary
        restored.append(PROMETHEUS_DATA_DIR)
    return {"restored": restored, "summary": summary}


def _merge_app_data(source: Path, target: Path) -> dict[str, Any]:
    target.mkdir(parents=True, exist_ok=True)
    copied_files = _copy_missing_files(source, target, skip_names={DB_FILENAME})
    db_summary: dict[str, Any] = {"status": "missing_source_db"}
    source_db = source / DB_FILENAME
    target_db = target / DB_FILENAME
    if source_db.exists():
        target_db.parent.mkdir(parents=True, exist_ok=True)
        if not target_db.exists():
            shutil.copy2(source_db, target_db)
            db_summary = {"status": "copied_database"}
        else:
            db_summary = _merge_sqlite_database(source_db, target_db)
    return {"copied_files": copied_files, "database": db_summary}


def _merge_sqlite_database(source_db: Path, target_db: Path) -> dict[str, Any]:
    init_db()
    tower_id_map: dict[int, int] = {}
    run_id_map: dict[int, int] = {}
    inserted: dict[str, int] = {}
    skipped: dict[str, int] = {}

    with sqlite3.connect(target_db) as target_conn:
        target_conn.row_factory = sqlite3.Row
        target_conn.execute("PRAGMA foreign_keys = ON")
        target_conn.execute("ATTACH DATABASE ? AS incoming", (str(source_db),))

        _merge_users(target_conn, inserted, skipped)
        _merge_towers(target_conn, tower_id_map, inserted, skipped)
        _merge_clusters(target_conn, tower_id_map, inserted, skipped)
        _merge_collection_runs(target_conn, run_id_map, inserted, skipped)
        _merge_collection_items(target_conn, tower_id_map, run_id_map, inserted, skipped)
        _merge_json_table(target_conn, "reports", ["generated_at", "payload_json"], inserted, skipped)
        _merge_json_table(target_conn, "metric_samples", ["collected_at", "payload_json"], inserted, skipped)
        _merge_latest_vm_volumes(target_conn, tower_id_map, inserted, skipped)
        target_conn.commit()
        target_conn.execute("DETACH DATABASE incoming")

    return {"status": "merged_database", "inserted": inserted, "skipped_existing": skipped}


def _merge_users(conn: sqlite3.Connection, inserted: dict[str, int], skipped: dict[str, int]) -> None:
    rows = conn.execute("SELECT username, password_hash, is_admin, created_at FROM incoming.users ORDER BY id").fetchall()
    for row in rows:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO users (username, password_hash, is_admin, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (row["username"], row["password_hash"], row["is_admin"], row["created_at"]),
        )
        _count_result("users", cur.rowcount, inserted, skipped)


def _merge_towers(conn: sqlite3.Connection, tower_id_map: dict[int, int], inserted: dict[str, int], skipped: dict[str, int]) -> None:
    rows = conn.execute("SELECT * FROM incoming.towers ORDER BY id").fetchall()
    for row in rows:
        source_id = int(row["id"])
        existing = conn.execute("SELECT * FROM towers WHERE id = ?", (source_id,)).fetchone()
        if existing and _same_tower(existing, row):
            tower_id_map[source_id] = int(existing["id"])
            _inc(skipped, "towers")
            continue
        matching = conn.execute("SELECT * FROM towers WHERE base_url = ? OR name = ? ORDER BY id LIMIT 1", (row["base_url"], row["name"])).fetchone()
        if matching:
            tower_id_map[source_id] = int(matching["id"])
            _inc(skipped, "towers")
            continue

        columns = [
            "name",
            "base_url",
            "username",
            "password_encrypted",
            "api_token_encrypted",
            "verify_tls",
            "enabled",
            "collection_hour",
            "collection_minute",
            "last_error",
            "created_at",
            "updated_at",
        ]
        if existing is None:
            conn.execute(
                f"INSERT INTO towers (id, {', '.join(columns)}) VALUES ({', '.join(['?'] * (len(columns) + 1))})",
                [source_id] + [row[column] for column in columns],
            )
            tower_id_map[source_id] = source_id
        else:
            conn.execute(
                f"INSERT INTO towers ({', '.join(columns)}) VALUES ({', '.join(['?'] * len(columns))})",
                [row[column] for column in columns],
            )
            tower_id_map[source_id] = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        _inc(inserted, "towers")


def _merge_clusters(conn: sqlite3.Connection, tower_id_map: dict[int, int], inserted: dict[str, int], skipped: dict[str, int]) -> None:
    rows = conn.execute("SELECT * FROM incoming.clusters ORDER BY id").fetchall()
    for row in rows:
        target_tower_id = tower_id_map.get(int(row["tower_id"]))
        if target_tower_id is None:
            _inc(skipped, "clusters")
            continue
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO clusters (tower_id, cluster_id, name, enabled, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (target_tower_id, row["cluster_id"], row["name"], row["enabled"], row["updated_at"]),
        )
        _count_result("clusters", cur.rowcount, inserted, skipped)


def _merge_collection_runs(conn: sqlite3.Connection, run_id_map: dict[int, int], inserted: dict[str, int], skipped: dict[str, int]) -> None:
    rows = conn.execute("SELECT * FROM incoming.collection_runs ORDER BY id").fetchall()
    for row in rows:
        source_id = int(row["id"])
        existing = conn.execute("SELECT id FROM collection_runs WHERE id = ?", (source_id,)).fetchone()
        duplicate = conn.execute(
            "SELECT id FROM collection_runs WHERE started_at = ? AND COALESCE(finished_at, '') = COALESCE(?, '') AND status = ? AND COALESCE(message, '') = COALESCE(?, '')",
            (row["started_at"], row["finished_at"], row["status"], row["message"]),
        ).fetchone()
        if duplicate:
            run_id_map[source_id] = int(duplicate["id"])
            _inc(skipped, "collection_runs")
            continue
        if existing is None:
            conn.execute(
                "INSERT INTO collection_runs (id, started_at, finished_at, status, message) VALUES (?, ?, ?, ?, ?)",
                (source_id, row["started_at"], row["finished_at"], row["status"], row["message"]),
            )
            run_id_map[source_id] = source_id
        else:
            conn.execute(
                "INSERT INTO collection_runs (started_at, finished_at, status, message) VALUES (?, ?, ?, ?)",
                (row["started_at"], row["finished_at"], row["status"], row["message"]),
            )
            run_id_map[source_id] = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        _inc(inserted, "collection_runs")


def _merge_collection_items(
    conn: sqlite3.Connection,
    tower_id_map: dict[int, int],
    run_id_map: dict[int, int],
    inserted: dict[str, int],
    skipped: dict[str, int],
) -> None:
    rows = conn.execute("SELECT * FROM incoming.collection_items ORDER BY id").fetchall()
    for row in rows:
        target_run_id = run_id_map.get(int(row["run_id"]))
        target_tower_id = tower_id_map.get(int(row["tower_id"])) if row["tower_id"] is not None else None
        if target_run_id is None:
            _inc(skipped, "collection_items")
            continue
        duplicate = conn.execute(
            """
            SELECT id FROM collection_items
            WHERE run_id = ? AND COALESCE(tower_id, -1) = COALESCE(?, -1)
              AND COALESCE(cluster_id, '') = COALESCE(?, '') AND status = ?
              AND COALESCE(message, '') = COALESCE(?, '') AND created_at = ?
            """,
            (target_run_id, target_tower_id, row["cluster_id"], row["status"], row["message"], row["created_at"]),
        ).fetchone()
        if duplicate:
            _inc(skipped, "collection_items")
            continue
        conn.execute(
            "INSERT INTO collection_items (run_id, tower_id, cluster_id, status, message, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (target_run_id, target_tower_id, row["cluster_id"], row["status"], row["message"], row["created_at"]),
        )
        _inc(inserted, "collection_items")


def _merge_json_table(conn: sqlite3.Connection, table: str, unique_columns: list[str], inserted: dict[str, int], skipped: dict[str, int]) -> None:
    rows = conn.execute(f"SELECT * FROM incoming.{table} ORDER BY id").fetchall()
    for row in rows:
        where = " AND ".join([f"{column} = ?" for column in unique_columns])
        duplicate = conn.execute(f"SELECT id FROM {table} WHERE {where}", [row[column] for column in unique_columns]).fetchone()
        if duplicate:
            _inc(skipped, table)
            continue
        target_id_exists = conn.execute(f"SELECT id FROM {table} WHERE id = ?", (row["id"],)).fetchone()
        if target_id_exists:
            conn.execute(
                f"INSERT INTO {table} ({', '.join(unique_columns)}) VALUES ({', '.join(['?'] * len(unique_columns))})",
                [row[column] for column in unique_columns],
            )
        else:
            conn.execute(
                f"INSERT INTO {table} (id, {', '.join(unique_columns)}) VALUES ({', '.join(['?'] * (len(unique_columns) + 1))})",
                [row["id"]] + [row[column] for column in unique_columns],
            )
        _inc(inserted, table)


def _merge_latest_vm_volumes(conn: sqlite3.Connection, tower_id_map: dict[int, int], inserted: dict[str, int], skipped: dict[str, int]) -> None:
    rows = conn.execute("SELECT * FROM incoming.latest_vm_volumes ORDER BY tower_id, cluster_id, vm_id").fetchall()
    for row in rows:
        target_tower_id = tower_id_map.get(int(row["tower_id"]))
        if target_tower_id is None:
            _inc(skipped, "latest_vm_volumes")
            continue
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO latest_vm_volumes (tower_id, cluster_id, vm_id, payload_json, collected_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (target_tower_id, row["cluster_id"], row["vm_id"], row["payload_json"], row["collected_at"]),
        )
        _count_result("latest_vm_volumes", cur.rowcount, inserted, skipped)


def _same_tower(target_row: sqlite3.Row, source_row: sqlite3.Row) -> bool:
    return str(target_row["base_url"]) == str(source_row["base_url"]) or str(target_row["name"]) == str(source_row["name"])


def _merge_prometheus_data(source: Path, target: Path) -> dict[str, Any]:
    target.mkdir(parents=True, exist_ok=True)
    source_blocks = _prometheus_blocks(source)
    target_blocks = _prometheus_blocks(target)

    if source_blocks and not target_blocks:
        _replace_directory(source, target)
        return {
            "mode": "full_copy_empty_target",
            "copied_blocks": len(source_blocks),
            "copied_runtime_entries": _count_existing_entries(source, PROMETHEUS_RUNTIME_ENTRIES),
            "skipped_existing_blocks": 0,
            "skipped_runtime_entries": 0,
        }

    copied_blocks = 0
    skipped_blocks = 0
    copied_files = 0
    skipped_runtime = 0
    for child in source.iterdir():
        if child.name in PROMETHEUS_RUNTIME_ENTRIES:
            skipped_runtime += 1
            continue
        destination = target / child.name
        if child.is_dir():
            if not _looks_like_prometheus_block(child):
                skipped_runtime += 1
                continue
            if destination.exists():
                skipped_blocks += 1
                continue
            shutil.copytree(child, destination)
            copied_blocks += 1
        elif not destination.exists():
            shutil.copy2(child, destination)
            copied_files += 1
    return {
        "mode": "merge_blocks",
        "copied_blocks": copied_blocks,
        "skipped_existing_blocks": skipped_blocks,
        "copied_files": copied_files,
        "skipped_runtime_entries": skipped_runtime,
    }


def _prometheus_blocks(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return [child for child in path.iterdir() if child.is_dir() and _looks_like_prometheus_block(child)]


def _count_existing_entries(path: Path, names: set[str]) -> int:
    return sum(1 for name in names if (path / name).exists())


def _looks_like_prometheus_block(path: Path) -> bool:
    return (path / "meta.json").exists()


def _copy_missing_files(source: Path, target: Path, skip_names: set[str] | None = None) -> int:
    skip = skip_names or set()
    copied = 0
    for child in source.iterdir():
        if child.name in skip:
            continue
        destination = target / child.name
        if destination.exists():
            continue
        if child.is_dir():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)
        copied += 1
    return copied


def _add_directory(archive: tarfile.TarFile, source: Path, arcname: str) -> None:
    if not source.exists():
        return
    archive.add(source, arcname=arcname, recursive=True, filter=_tar_filter)


def _tar_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    name = Path(info.name).name
    if name in {".DS_Store"} or name.startswith("._"):
        return None
    return info


def _validate_archive_members(archive: tarfile.TarFile) -> None:
    for member in archive.getmembers():
        path = Path(member.name)
        if member.islnk() or member.issym():
            raise HTTPException(status_code=400, detail="导入包不能包含符号链接。")
        if path.is_absolute() or ".." in path.parts:
            raise HTTPException(status_code=400, detail="导入包包含非法路径。")
        if path.parts and path.parts[0] not in {MANIFEST_NAME, APP_DATA_DIR, PROMETHEUS_DATA_DIR}:
            raise HTTPException(status_code=400, detail="导入包包含未知目录。")


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="导入包缺少有效 manifest。") from exc


def _replace_directory(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for child in target.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in source.iterdir():
        destination = target / child.name
        if child.is_dir():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)


def _count_result(table: str, rowcount: int, inserted: dict[str, int], skipped: dict[str, int]) -> None:
    if rowcount:
        _inc(inserted, table)
    else:
        _inc(skipped, table)


def _inc(mapping: dict[str, int], key: str) -> None:
    mapping[key] = mapping.get(key, 0) + 1
