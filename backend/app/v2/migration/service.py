from __future__ import annotations

import io
import json
import shutil
import sqlite3
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_hex
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException, UploadFile

from app.v2.config import V2Settings
from app.v2.database import V2Database
from app.v2.tasks.models import TaskStatus, TaskType
from app.v2.tasks.service import TaskService


ARCHIVE_MEDIA_TYPE = "application/gzip"
MANIFEST_NAME = "manifest.json"
APP_DIR = "app"
PROMETHEUS_DIR = "prometheus"
DB_FILENAME = "smartx.db"
MERGE_MODE = "merge"
OVERWRITE_MODE = "overwrite"
PROMETHEUS_RUNTIME_ENTRIES = {"chunks_head", "lock", "queries.active", "wal"}


class MigrationService:
    def __init__(self, database: V2Database, settings: V2Settings, tasks: TaskService) -> None:
        self.database = database
        self.settings = settings
        self.tasks = tasks

    def build_export_archive(self) -> tuple[bytes, str, Path, str]:
        generated_at = _now()
        filename = f"smartx-capacity-insight-migration-{generated_at.strftime('%Y%m%d%H%M%S')}.tar.gz"
        manifest = {
            "format": "smartx-capacity-insight-v2-migration",
            "version": 1,
            "generated_at": generated_at.isoformat(),
            "contains": {
                "sqlite": self.settings.sqlite_path.exists(),
                "prometheus": self.settings.prometheus_data_dir.exists(),
            },
        }
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            _add_json(archive, MANIFEST_NAME, manifest, generated_at)
            if self.settings.sqlite_path.exists():
                archive.add(self.settings.sqlite_path, arcname=f"{APP_DIR}/{DB_FILENAME}", recursive=False)
            _add_directory(archive, self.settings.prometheus_data_dir, PROMETHEUS_DIR, skip_names=PROMETHEUS_RUNTIME_ENTRIES)
        content = buffer.getvalue()
        self.settings.migrations_dir.mkdir(parents=True, exist_ok=True)
        path = self.settings.migrations_dir / filename
        path.write_bytes(content)
        download_url = f"/api/admin/exports/migrations/{quote(filename)}"
        self.tasks.create_task(
            f"migration-export-{token_hex(8)}",
            TaskType.MIGRATION_EXPORT,
            "导出迁移包",
            status=TaskStatus.SUCCESS,
            progress=100,
            message="迁移包已生成",
            links=[{"label": "迁移包", "filename": filename, "url": download_url, "path": str(path)}],
        )
        return content, filename, path, download_url

    async def restore_upload(self, upload: UploadFile, *, mode: str = MERGE_MODE, confirmed: bool = False) -> dict[str, Any]:
        content = await upload.read()
        return self.restore_archive_bytes(content, filename=upload.filename or "migration.tar.gz", mode=mode, confirmed=confirmed)

    def restore_archive_bytes(self, content: bytes, *, filename: str, mode: str = MERGE_MODE, confirmed: bool = False) -> dict[str, Any]:
        normalized_mode = mode if mode in {MERGE_MODE, OVERWRITE_MODE} else MERGE_MODE
        if normalized_mode == OVERWRITE_MODE and not confirmed:
            raise HTTPException(status_code=400, detail="覆盖导入会清空当前系统数据，请先确认。")
        if not content:
            raise HTTPException(status_code=400, detail="导入文件为空。")

        task_id = f"migration-import-{token_hex(8)}"
        self.tasks.create_task(task_id, TaskType.MIGRATION_IMPORT, "导入迁移包", status=TaskStatus.RUNNING, progress=5, message=Path(filename).name)
        package_dir = self.settings.imports_dir / task_id / "package"
        upload_path = self.settings.imports_dir / task_id / Path(filename).name
        upload_path.parent.mkdir(parents=True, exist_ok=True)
        upload_path.write_bytes(content)
        try:
            package_dir.mkdir(parents=True, exist_ok=True)
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
                _validate_members(archive)
                archive.extractall(package_dir)
            manifest = _read_manifest(package_dir / MANIFEST_NAME)
            if manifest.get("format") not in {"smartx-capacity-insight-v2-migration", "smartx-storage-forecast-migration"}:
                raise HTTPException(status_code=400, detail="导入包格式不正确。")
            self.tasks.update_task(task_id, progress=30, message="正在生成导入前备份")
            backup_path = self._create_import_backup(task_id)
            self.tasks.update_task(task_id, progress=55, message="导入前备份已生成", logs=[f"导入前备份：{backup_path}"])
            restored = self._restore_package(package_dir, normalized_mode)
            self.tasks.update_task(task_id, status=TaskStatus.SUCCESS, progress=100, message="数据迁移导入完成")
            return {"ok": True, "mode": normalized_mode, "restored": restored, "backup_path": str(backup_path), "task_id": task_id, "saved_path": str(upload_path)}
        except HTTPException:
            self.tasks.update_task(task_id, status=TaskStatus.FAILED, progress=100, message="数据迁移导入失败")
            raise
        except Exception as exc:
            self.tasks.update_task(task_id, status=TaskStatus.FAILED, progress=100, message=str(exc))
            raise

    def _create_import_backup(self, task_id: str) -> Path:
        generated_at = _now()
        self.settings.backups_dir.mkdir(parents=True, exist_ok=True)
        path = self.settings.backups_dir / f"import-before-{generated_at.strftime('%Y%m%d%H%M%S')}-{task_id[-8:]}.tar.gz"
        manifest = {
            "format": "smartx-capacity-insight-v2-import-backup",
            "version": 1,
            "generated_at": generated_at.isoformat(),
            "source_task_id": task_id,
        }
        with tarfile.open(path, mode="w:gz") as archive:
            _add_json(archive, MANIFEST_NAME, manifest, generated_at)
            if self.settings.sqlite_path.exists():
                archive.add(self.settings.sqlite_path, arcname=f"{APP_DIR}/{DB_FILENAME}", recursive=False)
            _add_directory(archive, self.settings.prometheus_data_dir, PROMETHEUS_DIR, skip_names=PROMETHEUS_RUNTIME_ENTRIES)
        return path

    def _restore_package(self, package_dir: Path, mode: str) -> list[str]:
        restored: list[str] = []
        source_db = package_dir / APP_DIR / DB_FILENAME
        source_prometheus = package_dir / PROMETHEUS_DIR
        if mode == OVERWRITE_MODE:
            if source_db.exists():
                self.settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_db, self.settings.sqlite_path)
                restored.append("smartx_db")
            if source_prometheus.exists():
                _replace_directory(source_prometheus, self.settings.prometheus_data_dir)
                restored.append("prometheus")
            return restored
        if source_db.exists():
            self._merge_sqlite(source_db)
            restored.append("smartx_db")
        if source_prometheus.exists():
            _copy_missing_tree(source_prometheus, self.settings.prometheus_data_dir, skip_names=PROMETHEUS_RUNTIME_ENTRIES)
            restored.append("prometheus")
        return restored

    def _merge_sqlite(self, source_db: Path) -> None:
        self.database.initialize()
        with sqlite3.connect(self.settings.sqlite_path) as target:
            target.row_factory = sqlite3.Row
            target.execute("PRAGMA foreign_keys = ON")
            target.execute("ATTACH DATABASE ? AS incoming", (str(source_db),))
            try:
                _merge_towers(target)
                _merge_clusters(target)
                _merge_vm_latest(target)
                _merge_vm_volumes(target)
                _merge_collection_runs(target)
                _merge_metric_snapshot(target)
                target.commit()
            finally:
                target.execute("DETACH DATABASE incoming")


def _merge_towers(conn: sqlite3.Connection) -> None:
    if not _incoming_table_exists(conn, "towers"):
        return
    for row in conn.execute("SELECT * FROM incoming.towers ORDER BY id").fetchall():
        conn.execute(
            """
            INSERT OR IGNORE INTO towers (id, name, base_url, username, password_encrypted, api_token_encrypted, verify_tls, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), COALESCE(?, CURRENT_TIMESTAMP))
            """,
            (
                row["id"],
                row["name"],
                row["base_url"],
                row["username"] if "username" in row.keys() else None,
                row["password_encrypted"] if "password_encrypted" in row.keys() else None,
                row["api_token_encrypted"] if "api_token_encrypted" in row.keys() else None,
                row["verify_tls"] if "verify_tls" in row.keys() else 1,
                row["enabled"] if "enabled" in row.keys() else 1,
                row["created_at"] if "created_at" in row.keys() else None,
                row["updated_at"] if "updated_at" in row.keys() else None,
            ),
        )


def _merge_clusters(conn: sqlite3.Connection) -> None:
    if not _incoming_table_exists(conn, "clusters"):
        return
    for row in conn.execute("SELECT * FROM incoming.clusters ORDER BY id").fetchall():
        conn.execute(
            """
            INSERT OR IGNORE INTO clusters (tower_id, cluster_id, name, enabled, updated_at)
            VALUES (?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
            """,
            (row["tower_id"], row["cluster_id"], row["name"], row["enabled"] if "enabled" in row.keys() else 1, row["updated_at"] if "updated_at" in row.keys() else None),
        )


def _merge_vm_latest(conn: sqlite3.Connection) -> None:
    if not _incoming_table_exists(conn, "vm_latest"):
        return
    for row in conn.execute("SELECT * FROM incoming.vm_latest").fetchall():
        conn.execute(
            """
            INSERT OR IGNORE INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes, updated_at)
            VALUES (?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
            """,
            (row["tower_id"], row["cluster_id"], row["vm_id"], row["name"], row["used_bytes"], row["updated_at"] if "updated_at" in row.keys() else None),
        )


def _merge_vm_volumes(conn: sqlite3.Connection) -> None:
    if not _incoming_table_exists(conn, "vm_volumes"):
        return
    for row in conn.execute("SELECT * FROM incoming.vm_volumes").fetchall():
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
                row["volume_id"],
                row["name"],
                row["path"],
                row["size_bytes"],
                row["used_bytes"],
                row["storage_policy"],
                row["replica_num"],
                row["thin_provision"],
                row["ec_k"],
                row["ec_m"],
                row["updated_at"] if "updated_at" in row.keys() else None,
            ),
        )


def _merge_collection_runs(conn: sqlite3.Connection) -> None:
    if not _incoming_table_exists(conn, "collection_runs"):
        return
    for row in conn.execute("SELECT * FROM incoming.collection_runs").fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO collection_runs (id, status, message, started_at, finished_at) VALUES (?, ?, ?, ?, ?)",
            (row["id"], row["status"], row["message"], row["started_at"], row["finished_at"]),
        )


def _merge_metric_snapshot(conn: sqlite3.Connection) -> None:
    if not _incoming_table_exists(conn, "metric_snapshots"):
        return
    for row in conn.execute("SELECT * FROM incoming.metric_snapshots").fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO metric_snapshots (id, metrics_text, updated_at) VALUES (?, ?, ?)",
            (row["id"], row["metrics_text"], row["updated_at"]),
        )


def _incoming_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM incoming.sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    return row is not None


def _add_json(archive: tarfile.TarFile, arcname: str, payload: dict[str, Any], generated_at: datetime) -> None:
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    info = tarfile.TarInfo(arcname)
    info.size = len(content)
    info.mtime = int(generated_at.timestamp())
    archive.addfile(info, io.BytesIO(content))


def _add_directory(archive: tarfile.TarFile, source: Path, arcname: str, *, skip_names: set[str]) -> None:
    if not source.exists():
        return
    for path in sorted(source.rglob("*")):
        if any(part in skip_names for part in path.relative_to(source).parts):
            continue
        archive.add(path, arcname=str(Path(arcname) / path.relative_to(source)), recursive=False)


def _validate_members(archive: tarfile.TarFile) -> None:
    for member in archive.getmembers():
        target = Path(member.name)
        if target.is_absolute() or ".." in target.parts:
            raise HTTPException(status_code=400, detail="导入包包含非法路径。")


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise HTTPException(status_code=400, detail="导入包缺少 manifest.json。")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="manifest.json 格式不正确。") from exc


def _copy_missing_tree(source: Path, target: Path, *, skip_names: set[str]) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if any(part in skip_names for part in relative.parts):
            continue
        destination = target / relative
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)


def _replace_directory(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def _now() -> datetime:
    return datetime.now(timezone.utc)
