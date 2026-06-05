from __future__ import annotations

import io
import json
import shutil
import sqlite3
import tarfile
import uuid
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
APP_RUNTIME_ENTRIES = {"backups", "upgrades", "exports", "compose-runtime"}
EXPORT_TASK_DIR = "migration-tasks"
IMPORT_TASK_DIR = "imports"
TASK_FILE = "task.json"
IMPORT_UPLOAD_FILENAME = "upload.tar.gz"
IMPORT_PACKAGE_DIR = "package"


def build_migration_archive(save_export: bool = True) -> tuple[bytes, str]:
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
        _add_directory(archive, app_data_path, APP_DATA_DIR, skip_names=APP_RUNTIME_ENTRIES)
        _add_directory(archive, prometheus_data_path, PROMETHEUS_DATA_DIR)

    filename = f"smartx-storage-migration-{generated_at.strftime('%Y%m%d%H%M%S')}.tar.gz"
    content = buffer.getvalue()
    if save_export:
        _save_migration_export(content, filename)
    return content, filename


def _save_migration_export(content: bytes, filename: str) -> Path:
    settings = get_settings()
    export_dir = settings.export_path / "migrations"
    export_dir.mkdir(parents=True, exist_ok=True)
    target = export_dir / Path(filename).name
    target.write_bytes(content)
    return target


async def restore_migration_archive(upload: UploadFile, confirmed: bool, mode: str = MERGE_MODE) -> dict[str, Any]:
    normalized_mode = mode if mode in {MERGE_MODE, OVERWRITE_MODE} else MERGE_MODE
    if normalized_mode == OVERWRITE_MODE and not confirmed:
        raise HTTPException(status_code=400, detail="覆盖导入会清空当前系统数据，请先勾选确认。")

    settings = get_settings()
    task = _create_migration_import_task(upload.filename, normalized_mode)
    task_dir = _migration_import_task_dir(str(task["task_id"]))
    upload_path = task_dir / IMPORT_UPLOAD_FILENAME
    package_dir = task_dir / IMPORT_PACKAGE_DIR
    try:
        saved_bytes = await _save_import_upload(upload, upload_path)
        if saved_bytes <= 0:
            _update_migration_import_task(
                task,
                status="failed",
                progress=100,
                detail="导入文件为空。",
                logs=["导入文件为空"],
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            raise HTTPException(status_code=400, detail="导入文件为空。")

        package_dir.mkdir(parents=True, exist_ok=True)
        _update_migration_import_task(
            task,
            status="running",
            progress=20,
            detail="正在解压并校验导入包",
            logs=[f"上传文件已保存：{upload_path}", f"文件大小：{saved_bytes} bytes"],
        )
        try:
            with tarfile.open(upload_path, mode="r:gz") as archive:
                _validate_archive_members(archive)
                archive.extractall(package_dir)
        except (tarfile.TarError, OSError) as exc:
            _update_migration_import_task(
                task,
                status="failed",
                progress=100,
                detail=str(exc),
                logs=["无法读取导入包", str(exc)],
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            raise HTTPException(status_code=400, detail=f"无法读取导入包：{exc}") from exc

        manifest = _read_manifest(package_dir / MANIFEST_NAME)
        if manifest.get("format") != "smartx-storage-forecast-migration":
            _update_migration_import_task(
                task,
                status="failed",
                progress=100,
                detail="导入包格式不正确。",
                logs=["导入包格式不正确"],
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            raise HTTPException(status_code=400, detail="导入包格式不正确。")

        _update_migration_import_task(task, progress=55, detail="正在导入业务库和历史指标", logs=[f"导入模式：{normalized_mode}"])
        if normalized_mode == OVERWRITE_MODE:
            result = _restore_overwrite(package_dir, settings.data_path, settings.prometheus_data_path)
            message = "数据覆盖导入完成，请重启 web-api、collector-worker 和 prometheus 使数据完全生效。"
        else:
            result = _restore_merge(package_dir, settings.data_path, settings.prometheus_data_path)
            message = "数据补全导入完成，已保留当前系统已有数据；请重启 web-api、collector-worker 和 prometheus 使数据完全生效。"

        _update_migration_import_task(
            task,
            status="succeeded",
            progress=100,
            detail="数据迁移导入完成",
            logs=[message],
            restored=result["restored"],
            summary=result["summary"],
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        return {
            "ok": True,
            "mode": normalized_mode,
            "restored": result["restored"],
            "summary": result["summary"],
            "message": message,
            "task_id": task["task_id"],
            "saved_path": str(upload_path),
        }
    except HTTPException:
        raise
    except Exception as exc:
        _update_migration_import_task(
            task,
            status="failed",
            progress=100,
            detail=str(exc),
            logs=["导入失败", str(exc)],
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        raise


async def _save_import_upload(upload: UploadFile, target: Path) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with target.open("wb") as output:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            total += len(chunk)
    return total


def _migration_import_root() -> Path:
    settings = get_settings()
    root = settings.export_path / IMPORT_TASK_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _migration_import_task_dir(task_id: str) -> Path:
    if not task_id or any(ch not in "0123456789abcdef" for ch in task_id):
        raise HTTPException(status_code=404, detail="迁移导入任务不存在。")
    return _migration_import_root() / task_id


def _migration_import_task_path(task_id: str) -> Path:
    return _migration_import_task_dir(task_id) / TASK_FILE


def _create_migration_import_task(filename: str | None, mode: str) -> dict[str, Any]:
    task_id = uuid.uuid4().hex
    task_dir = _migration_import_task_dir(task_id)
    task_dir.mkdir(parents=True, exist_ok=False)
    task = {
        "task_id": task_id,
        "status": "pending",
        "progress": 0,
        "mode": mode,
        "filename": Path(filename or IMPORT_UPLOAD_FILENAME).name,
        "saved_path": str(task_dir / IMPORT_UPLOAD_FILENAME),
        "package_path": str(task_dir / IMPORT_PACKAGE_DIR),
        "detail": "等待开始导入",
        "logs": ["导入任务已创建"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_migration_import_task(task)
    return task


def _save_migration_import_task(task: dict[str, Any]) -> None:
    task["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = _migration_import_task_path(str(task["task_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _update_migration_import_task(task: dict[str, Any], **patch: Any) -> None:
    logs = patch.pop("logs", None)
    task.update({key: value for key, value in patch.items() if value is not None})
    if logs:
        current_logs = list(task.get("logs") or [])
        current_logs.extend(str(item) for item in logs if item)
        task["logs"] = current_logs[-20:]
    _save_migration_import_task(task)


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


def _add_directory(archive: tarfile.TarFile, source: Path, arcname: str, skip_names: set[str] | None = None) -> None:
    if not source.exists():
        return
    skip = skip_names or set()
    archive.add(source, arcname=arcname, recursive=True, filter=lambda info: _tar_filter(info, skip))


def _tar_filter(info: tarfile.TarInfo, skip_names: set[str] | None = None) -> tarfile.TarInfo | None:
    name = Path(info.name).name
    if name in {".DS_Store"} or name.startswith("._") or name in (skip_names or set()):
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



def create_migration_export_task() -> dict[str, Any]:
    task_id = uuid.uuid4().hex
    task_dir = _migration_export_task_dir(task_id)
    task_dir.mkdir(parents=True, exist_ok=False)
    task = {
        "task_id": task_id,
        "status": "pending",
        "progress": 0,
        "processed_bytes": 0,
        "total_bytes": 0,
        "detail": "等待开始导出",
        "logs": ["导出任务已创建"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_migration_export_task(task)
    return _public_migration_export_task(task)


def run_migration_export_task(task_id: str) -> None:
    task = _load_migration_export_task(task_id)
    target: Path | None = None
    try:
        settings = get_settings()
        _update_migration_export_task(task, status="running", progress=1, detail="正在扫描导出数据", logs=["正在统计业务库和历史指标大小"])
        generated_at = datetime.now(timezone.utc)
        manifest = {
            "format": "smartx-storage-forecast-migration",
            "version": 1,
            "generated_at": generated_at.isoformat(),
            "contains": {
                APP_DATA_DIR: settings.data_path.exists(),
                PROMETHEUS_DATA_DIR: settings.prometheus_data_path.exists(),
            },
        }
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        entries = _collect_migration_export_entries(settings.data_path, APP_DATA_DIR, APP_RUNTIME_ENTRIES)
        entries += _collect_migration_export_entries(settings.prometheus_data_path, PROMETHEUS_DATA_DIR, PROMETHEUS_RUNTIME_ENTRIES)
        total_bytes = len(manifest_bytes) + sum(size for _, _, size in entries)
        if total_bytes <= 0:
            total_bytes = 1
        filename = f"smartx-storage-migration-{generated_at.strftime('%Y%m%d%H%M%S')}.tar.gz"
        export_dir = settings.export_path / "migrations"
        export_dir.mkdir(parents=True, exist_ok=True)
        target = export_dir / filename
        task.update({
            "filename": filename,
            "saved_path": str(target),
            "download_url": f"/api/admin/exports/migrations/{filename}",
            "total_bytes": total_bytes,
        })
        _update_migration_export_task(task, progress=3, detail="正在创建迁移包", logs=[f"待处理文件 {len(entries)} 个", _format_bytes(total_bytes)])

        processed = 0
        last_saved_percent = -1

        def advance(amount: int, message: str | None = None) -> None:
            nonlocal processed, last_saved_percent
            processed += max(0, amount)
            percent = min(98, max(3, int(processed / total_bytes * 98)))
            if percent != last_saved_percent or message:
                last_saved_percent = percent
                logs = [message] if message else None
                _update_migration_export_task(task, progress=percent, processed_bytes=processed, detail="正在打包迁移数据", logs=logs)

        with tarfile.open(target, mode="w:gz") as archive:
            manifest_info = tarfile.TarInfo(MANIFEST_NAME)
            manifest_info.size = len(manifest_bytes)
            manifest_info.mtime = int(generated_at.timestamp())
            archive.addfile(manifest_info, io.BytesIO(manifest_bytes))
            advance(len(manifest_bytes), "manifest 已写入")
            for source, arcname, size in entries:
                _add_file_with_progress(archive, source, arcname, lambda count, name=arcname: advance(count, f"正在打包 {name}" if count else None))
                if size == 0:
                    advance(0, f"已处理空文件 {arcname}")
        _update_migration_export_task(
            task,
            status="succeeded",
            progress=100,
            processed_bytes=total_bytes,
            detail="迁移包已生成",
            logs=["迁移包已生成", f"服务器留档：{target}"],
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:
        if target and target.exists():
            target.unlink(missing_ok=True)
        _update_migration_export_task(
            task,
            status="failed",
            progress=100,
            detail=str(exc),
            logs=["导出失败", str(exc)],
            finished_at=datetime.now(timezone.utc).isoformat(),
        )


def get_migration_export_task(task_id: str) -> dict[str, Any]:
    return _public_migration_export_task(_load_migration_export_task(task_id))


def _collect_migration_export_entries(source: Path, arcname: str, skip_names: set[str]) -> list[tuple[Path, str, int]]:
    if not source.exists():
        return []
    entries: list[tuple[Path, str, int]] = []
    for child in source.rglob("*"):
        try:
            relative = child.relative_to(source)
        except ValueError:
            continue
        if _skip_export_path(relative, skip_names):
            continue
        if not child.is_file() or child.is_symlink():
            continue
        entries.append((child, str(Path(arcname) / relative), child.stat().st_size))
    return entries


def _skip_export_path(relative: Path, skip_names: set[str]) -> bool:
    for part in relative.parts:
        if part in {".DS_Store"} or part.startswith("._") or part in skip_names:
            return True
    return False


def _add_file_with_progress(archive: tarfile.TarFile, source: Path, arcname: str, on_progress: Any) -> None:
    info = archive.gettarinfo(str(source), arcname=arcname)
    with source.open("rb") as file_obj:
        archive.addfile(info, _ProgressReader(file_obj, on_progress))


class _ProgressReader:
    def __init__(self, file_obj: Any, on_progress: Any) -> None:
        self._file_obj = file_obj
        self._on_progress = on_progress

    def read(self, size: int = -1) -> bytes:
        data = self._file_obj.read(size)
        if data:
            self._on_progress(len(data))
        return data


def _migration_export_root() -> Path:
    root = get_settings().export_path / EXPORT_TASK_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _migration_export_task_dir(task_id: str) -> Path:
    if not task_id or any(ch not in "0123456789abcdef" for ch in task_id):
        raise HTTPException(status_code=404, detail="迁移导出任务不存在。")
    return _migration_export_root() / task_id


def _migration_export_task_path(task_id: str) -> Path:
    return _migration_export_task_dir(task_id) / TASK_FILE


def _load_migration_export_task(task_id: str) -> dict[str, Any]:
    path = _migration_export_task_path(task_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="迁移导出任务不存在。")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_migration_export_task(task: dict[str, Any]) -> None:
    task["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = _migration_export_task_path(str(task["task_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _update_migration_export_task(task: dict[str, Any], **patch: Any) -> None:
    logs = patch.pop("logs", None)
    task.update({key: value for key, value in patch.items() if value is not None})
    if logs:
        current_logs = list(task.get("logs") or [])
        current_logs.extend(str(item) for item in logs if item)
        task["logs"] = current_logs[-20:]
    _save_migration_export_task(task)


def _public_migration_export_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task.get("task_id"),
        "status": task.get("status"),
        "progress": int(task.get("progress") or 0),
        "processed_bytes": int(task.get("processed_bytes") or 0),
        "total_bytes": int(task.get("total_bytes") or 0),
        "detail": task.get("detail") or "",
        "logs": list(task.get("logs") or []),
        "filename": task.get("filename"),
        "saved_path": task.get("saved_path"),
        "download_url": task.get("download_url"),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "finished_at": task.get("finished_at"),
    }


def _format_bytes(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(value)
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    return f"总数据量 {size:.1f} {units[index]}"
