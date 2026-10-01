from __future__ import annotations

import io
import json
import hashlib
import os
import shutil
import sqlite3
import tarfile
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_hex
from typing import Any, Iterator
from urllib.parse import quote

from fastapi import HTTPException, UploadFile

from app.v2.parsing import int_or_none
from app.v2.config import V2Settings
from app.v2.database import V2Database
from app.v2.tasks.models import TaskStatus, TaskType
from app.v2.tasks.service import TaskService


ARCHIVE_MEDIA_TYPE = "application/gzip"
MANIFEST_NAME = "manifest.json"
APP_DIR = "app"
PROMETHEUS_DIR = "prometheus"
V1_APP_DIR = "smartx-data"
V1_PROMETHEUS_DIR = "prometheus-data"
DB_FILENAME = "smartx.db"
MERGE_MODE = "merge"
OVERWRITE_MODE = "overwrite"
PROMETHEUS_RUNTIME_ENTRIES = {"chunks_head", "lock", "queries.active", "wal"}
CONFIG_SCOPE = "config"
FULL_SCOPE = "full"
DATA_SCOPE = "data"

# 数据包导出时从 SQLite 拷贝里 DROP 掉的表：Tower 配置（towers/clusters）
# 与本机运行状态（users/tasks/升级状态）。其余表（含未来新增的业务表）默认随数据包走；
# 若将来新增「不该离开本机的状态表」，必须显式加进这个清单（test_v2_migration 锁住）。
DATA_EXPORT_DROP_TABLES = ("towers", "clusters", "users", "tasks", "upgrade_runner_state", "upgrade_task_leases")
# 全量迁移包导出的剥离清单：只剥**本机运行状态**（账号/任务历史/升级状态），
# Tower 配置与全部业务数据都随包——「迁移包+恢复密钥=完整恢复」由此成立（#68）。
FULL_EXPORT_DROP_TABLES = ("users", "tasks", "upgrade_runner_state", "upgrade_task_leases")


class MigrationService:
    def __init__(self, database: V2Database, settings: V2Settings, tasks: TaskService) -> None:
        self.database = database
        self.settings = settings
        self.tasks = tasks

    def build_export_archive(self, *, record_task: bool = True, task_id: str | None = None, steps: list[dict[str, Any]] | None = None, scope: str = FULL_SCOPE) -> tuple[bytes, str, Path, str]:
        generated_at = _now()
        if scope == DATA_SCOPE:
            filename = f"smartx-data-migration-{generated_at.strftime('%Y%m%d%H%M%S')}-{token_hex(4)}.tar.gz"
        else:
            filename = f"smartx-capacity-insight-migration-{generated_at.strftime('%Y%m%d%H%M%S')}-{token_hex(4)}.tar.gz"
        buffer = io.BytesIO()
        if scope == DATA_SCOPE:
            copy_ctx = tempfile_sqlite_copy_without(self.settings.sqlite_path, DATA_EXPORT_DROP_TABLES)
        elif scope == FULL_SCOPE:
            # #68：全量包名实相符——SQLite 携带全量业务数据（仅剥本机运行状态）
            copy_ctx = tempfile_sqlite_copy_without(self.settings.sqlite_path, FULL_EXPORT_DROP_TABLES)
        else:
            copy_ctx = tempfile_sqlite_copy
        with copy_ctx as config_db:
            candidate_files = _export_candidate_files(config_db, self.settings.prometheus_data_dir)
            total_bytes = sum(path.stat().st_size for path, _ in candidate_files if path.is_file())
            files = {archive_name: _file_manifest(path) for path, archive_name in candidate_files if path.is_file()}
            manifest = {
                "format": "smartx-capacity-insight-v2-migration",
                "version": 1,
                "migration_scope": scope,
                # sqlite_scope 如实反映包内 SQLite 内容（#68：full 包现为全量业务数据）
                "sqlite_scope": scope,
                "generated_at": generated_at.isoformat(),
                "contains": {
                    "sqlite": config_db.is_file(),
                    "prometheus": self.settings.prometheus_data_dir.exists(),
                },
                "files": files,
            }
            with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
                _add_json(archive, MANIFEST_NAME, manifest, generated_at)
                processed_bytes = 0
                logs = []
                for path, archive_name in candidate_files:
                    archive.add(path, arcname=archive_name, recursive=False)
                    processed_bytes += path.stat().st_size
                    logs.append(f"当前文件：{archive_name} ({_size_label(processed_bytes)}/{_size_label(total_bytes)})")
                    if task_id and steps:
                        self.tasks.update_task(
                            task_id,
                            progress=10 + int((processed_bytes / total_bytes) * 70) if total_bytes else 80,
                            message=f"正在打包：{archive_name}",
                            logs=logs[-6:],
                            steps=_replace_step(steps, "archive", "running", f"{_size_label(processed_bytes)}/{_size_label(total_bytes)}"),
                        )
        content = buffer.getvalue()
        self.settings.migrations_dir.mkdir(parents=True, exist_ok=True)
        path = self.settings.migrations_dir / filename
        path.write_bytes(content)
        # 数据包里没有 Tower 凭据，不需要恢复密钥，也不生成 .env 快照；
        # full 包无论是否记录任务都要生成快照（后台任务流程靠 path.with_suffix(".env") 找回它）。
        env_snapshot = None if scope == DATA_SCOPE else self._snapshot_env_for_bundle(path)
        download_url = f"/api/admin/exports/migrations/{quote(filename)}"
        if record_task:
            if scope == DATA_SCOPE:
                links = [{"label": "监测数据包", "filename": filename, "url": download_url, "path": str(path), "scope": DATA_SCOPE}]
                message = "监测数据包已生成（不含 Tower 配置，无需恢复密钥）"
                title = "仅导出存储监测数据"
            else:
                links = [{"label": "迁移包", "filename": filename, "url": download_url, "path": str(path)}]
                if env_snapshot is not None:
                    links.append(self._env_link(env_snapshot))
                message = "迁移包已生成" + ("，已同步生成恢复密钥（任务中心可下载）" if env_snapshot is not None else "（警告：未找到密钥文件，未生成恢复密钥）")
                title = "导出迁移包"
            self.tasks.create_task(
                f"migration-export-{token_hex(8)}",
                TaskType.MIGRATION_EXPORT,
                title,
                status=TaskStatus.SUCCESS,
                progress=100,
                message=message,
                links=links,
            )
        return content, filename, path, download_url

    def _snapshot_env_for_bundle(self, bundle_path: Path) -> Path | None:
        """把当前 .env 快照到导出留档目录，与迁移包同名（.env 后缀），恢复时同代配对使用。"""
        env_path = self.settings.env_file_path
        if not env_path.is_file():
            return None
        target = bundle_path.with_suffix(".env")
        shutil.copy2(env_path, target)
        os.chmod(target, 0o600)
        return target

    @staticmethod
    def _env_link(env_snapshot: Path) -> dict[str, str]:
        return {
            "label": "恢复密钥（与迁移包成对使用）",
            "filename": env_snapshot.name,
            "url": f"/api/admin/exports/migrations/{quote(env_snapshot.name)}",
            "path": str(env_snapshot),
        }

    def build_config_export_archive(self, *, record_task: bool = True) -> tuple[bytes, str, Path, str]:
        generated_at = _now()
        filename = f"smartx-config-migration-{generated_at.strftime('%Y%m%d%H%M%S')}-{token_hex(4)}.tar.gz"
        buffer = io.BytesIO()
        with tempfile_sqlite_copy(self.settings.sqlite_path) as config_db:
            files = {f"{APP_DIR}/{DB_FILENAME}": _file_manifest(config_db)} if config_db.is_file() else {}
            manifest = {
                "format": "smartx-capacity-insight-v2-migration",
                "version": 1,
                "migration_scope": CONFIG_SCOPE,
                "generated_at": generated_at.isoformat(),
                "contains": {
                    "sqlite": config_db.is_file(),
                    "prometheus": False,
                },
                "files": files,
            }
            with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
                _add_json(archive, MANIFEST_NAME, manifest, generated_at)
                if config_db.is_file():
                    archive.add(config_db, arcname=f"{APP_DIR}/{DB_FILENAME}", recursive=False)
        content = buffer.getvalue()
        self.settings.migrations_dir.mkdir(parents=True, exist_ok=True)
        path = self.settings.migrations_dir / filename
        path.write_bytes(content)
        env_snapshot = self._snapshot_env_for_bundle(path)
        download_url = f"/api/admin/exports/migrations/{quote(filename)}"
        if record_task:
            links = [{"label": "Tower 配置", "filename": filename, "url": download_url, "path": str(path), "scope": CONFIG_SCOPE}]
            if env_snapshot is not None:
                links.append(self._env_link(env_snapshot))
            self.tasks.create_task(
                f"migration-config-export-{token_hex(8)}",
                TaskType.MIGRATION_EXPORT,
                "仅导出 Tower 配置",
                status=TaskStatus.SUCCESS,
                progress=100,
                message="Tower 配置已导出（不含历史数据）",
                links=links,
            )
        return content, filename, path, download_url

    def start_export_task(self, *, run_inline: bool = False, scope: str = FULL_SCOPE) -> dict[str, Any]:
        if scope not in {FULL_SCOPE, DATA_SCOPE}:
            raise HTTPException(status_code=400, detail="不支持的导出范围。")
        title = "仅导出存储监测数据" if scope == DATA_SCOPE else "导出迁移包"
        task_id = f"migration-export-{token_hex(8)}"
        steps = [
            _step("scan", "扫描迁移数据", "running"),
            _step("archive", "打包业务库和历史指标", "pending"),
            _step("save", "保存迁移包", "pending"),
            _step("finish", "生成下载链接", "pending"),
        ]
        self.tasks.create_task(
            task_id,
            TaskType.MIGRATION_EXPORT,
            title,
            status=TaskStatus.RUNNING,
            progress=1,
            message="正在扫描迁移数据",
            logs=["开始扫描 SQLite 和 Prometheus 历史指标"],
            steps=steps,
        )
        if not run_inline:
            worker = threading.Thread(target=self._run_export_task_safely, args=(task_id, steps, scope), daemon=True)
            worker.start()
            return _migration_export_task(self.tasks.get_task(task_id) or {})
        try:
            result = self._run_export_task(task_id, steps, scope=scope)
            return result
        except Exception as exc:
            self.tasks.update_task(
                task_id,
                status=TaskStatus.FAILED,
                progress=100,
                message=str(exc),
                logs=["导出失败", str(exc)],
                steps=_replace_step(steps, "scan", "failed", str(exc)),
            )
            raise

    def _run_export_task_safely(self, task_id: str, steps: list[dict[str, Any]], scope: str = FULL_SCOPE) -> None:
        try:
            self.database.initialize()
            self._run_export_task(task_id, steps, scope=scope)
        except Exception as exc:
            self.tasks.update_task(
                task_id,
                status=TaskStatus.FAILED,
                progress=100,
                message=str(exc),
                logs=["导出失败", str(exc)],
                steps=_fail_running_step(steps, str(exc)),
            )

    def export_task_status(self, task_id: str) -> dict[str, Any]:
        task = self.tasks.get_task(task_id)
        if task is None or task["type"] != TaskType.MIGRATION_EXPORT.value:
            raise HTTPException(status_code=404, detail="迁移导出任务不存在。")
        return _migration_export_task(task)

    def import_task_status(self, task_id: str) -> dict[str, Any]:
        task = self.tasks.get_task(task_id)
        if task is None or task["type"] != TaskType.MIGRATION_IMPORT.value:
            raise HTTPException(status_code=404, detail="迁移导入任务不存在。")
        return _migration_import_task(task)

    def _run_export_task(self, task_id: str, steps: list[dict[str, Any]], *, scope: str = FULL_SCOPE) -> dict[str, Any]:
        if scope == DATA_SCOPE:
            copy_ctx = tempfile_sqlite_copy_without(self.settings.sqlite_path, DATA_EXPORT_DROP_TABLES)
        elif scope == FULL_SCOPE:
            copy_ctx = tempfile_sqlite_copy_without(self.settings.sqlite_path, FULL_EXPORT_DROP_TABLES)
        else:
            copy_ctx = tempfile_sqlite_copy
        with copy_ctx as config_db:
            candidate_files = _export_candidate_files(config_db, self.settings.prometheus_data_dir)
            total_bytes = sum(path.stat().st_size for path, _ in candidate_files if path.is_file())
        logs = [f"扫描完成：{len(candidate_files)} 个文件，约 {_size_label(total_bytes)}"]
        steps = _replace_step(steps, "scan", "succeeded", f"{len(candidate_files)} 个文件")
        steps = _replace_step(steps, "archive", "running")
        self.tasks.update_task(task_id, progress=10, message="正在打包迁移包", logs=logs, steps=steps)

        content, filename, path, download_url = self.build_export_archive(record_task=False, task_id=task_id, steps=steps, scope=scope)
        processed_bytes = total_bytes
        if candidate_files:
            logs.append(f"当前文件：{candidate_files[-1][1]} ({_size_label(processed_bytes)}/{_size_label(total_bytes)})")
        logs.append(f"已打包：{Path(filename).name}")
        steps = _replace_step(steps, "archive", "succeeded", f"已处理 {_size_label(processed_bytes)}")
        steps = _replace_step(steps, "save", "succeeded", str(path))
        steps = _replace_step(steps, "finish", "succeeded", download_url)
        links = [{"label": "迁移包", "filename": filename, "url": download_url, "path": str(path), "processed_bytes": processed_bytes, "total_bytes": total_bytes}]
        env_snapshot = path.with_suffix(".env")
        if env_snapshot.is_file():
            links.append(self._env_link(env_snapshot))
        task = self.tasks.update_task(
            task_id,
            status=TaskStatus.SUCCESS,
            progress=100,
            message="迁移包已生成",
            links=links,
            logs=logs + [f"服务器留档：{path}"],
            steps=steps,
        )
        task["processed_bytes"] = processed_bytes
        task["total_bytes"] = total_bytes
        return _migration_export_task(task, processed_bytes=processed_bytes, total_bytes=total_bytes)

    async def restore_upload(self, upload: UploadFile, *, mode: str = MERGE_MODE, confirmed: bool = False) -> dict[str, Any]:
        content = await upload.read()
        return self.restore_archive_bytes(content, filename=upload.filename or "migration.tar.gz", mode=mode, confirmed=confirmed)

    def restore_archive_bytes(self, content: bytes, *, filename: str, mode: str = MERGE_MODE, confirmed: bool = False) -> dict[str, Any]:
        return self.start_import_task(content, filename=filename, mode=mode, confirmed=confirmed, legacy_response=True)

    def start_import_task(self, content: bytes, *, filename: str, mode: str = MERGE_MODE, confirmed: bool = False, legacy_response: bool = False, run_inline: bool = True) -> dict[str, Any]:
        normalized_mode = mode if mode in {MERGE_MODE, OVERWRITE_MODE} else MERGE_MODE
        if normalized_mode == OVERWRITE_MODE and not confirmed:
            raise HTTPException(status_code=400, detail="覆盖导入会清空当前系统数据，请先确认。")
        if not content:
            raise HTTPException(status_code=400, detail="导入文件为空。")

        task_id = f"migration-import-{token_hex(8)}"
        steps = [
            _step("upload", "保存上传包", "running", Path(filename).name),
            _step("extract", "解压并校验迁移包", "pending"),
            _step("backup", "生成导入前备份", "pending"),
            _step("sqlite", "导入业务库", "pending"),
            _step("prometheus", "导入 Prometheus 历史指标", "pending"),
            _step("health", "执行导入后健康检查", "pending"),
        ]
        logs = [f"保存上传包：{Path(filename).name}"]
        self.tasks.create_task(task_id, TaskType.MIGRATION_IMPORT, "导入迁移包", status=TaskStatus.RUNNING, progress=5, message=Path(filename).name, logs=logs, steps=steps)
        package_dir = self.settings.imports_dir / task_id / "package"
        upload_path = self.settings.imports_dir / task_id / Path(filename).name
        upload_path.parent.mkdir(parents=True, exist_ok=True)
        upload_path.write_bytes(content)
        self.tasks.update_task(task_id, links=[{"label": "上传包", "filename": upload_path.name, "url": "", "path": str(upload_path), "saved_path": str(upload_path)}])
        if not run_inline:
            worker = threading.Thread(
                target=self._run_import_task,
                args=(task_id, upload_path, package_dir, normalized_mode, steps, logs),
                daemon=True,
            )
            worker.start()
            return _migration_import_task(self.tasks.get_task(task_id) or {})
        return self._run_import_task(task_id, upload_path, package_dir, normalized_mode, steps, logs, legacy_response=legacy_response)

    def _run_import_task(
        self,
        task_id: str,
        upload_path: Path,
        package_dir: Path,
        normalized_mode: str,
        steps: list[dict[str, Any]],
        logs: list[str],
        *,
        legacy_response: bool = False,
    ) -> dict[str, Any]:
        content = upload_path.read_bytes()
        try:
            steps = _replace_step(steps, "upload", "succeeded", str(upload_path))
            steps = _replace_step(steps, "extract", "running")
            self.tasks.update_task(task_id, progress=15, message="正在解压并校验迁移包", logs=logs, steps=steps)
            package_dir.mkdir(parents=True, exist_ok=True)
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
                _validate_members(archive)
                archive.extractall(package_dir)
            manifest = _read_manifest(package_dir / MANIFEST_NAME)
            if manifest.get("format") not in {"smartx-capacity-insight-v2-migration", "smartx-storage-forecast-migration"}:
                raise HTTPException(status_code=400, detail="导入包格式不正确。")
            migration_scope = str(manifest.get("migration_scope") or FULL_SCOPE)
            logs.append(f"迁移包格式：{manifest.get('format')}")
            if migration_scope == CONFIG_SCOPE:
                logs.append("迁移范围：配置迁移，仅导入 Tower 和集群")
            if migration_scope == DATA_SCOPE:
                logs.append("迁移范围：数据迁移，仅合并监测数据（不动本机 Tower 配置）")
            steps = _replace_step(steps, "extract", "succeeded", "manifest 校验通过")
            steps = _replace_step(steps, "backup", "running")
            self.tasks.update_task(task_id, progress=30, message="正在生成导入前备份", logs=logs, steps=steps)
            backup_path = self._create_import_backup(task_id)
            logs.append(f"导入前备份：{backup_path}")
            steps = _replace_step(steps, "backup", "succeeded", str(backup_path))
            steps = _replace_step(steps, "sqlite", "running")
            self.tasks.update_task(task_id, progress=55, message="正在导入业务库", logs=logs, steps=steps)
            restore_result = self._restore_package(package_dir, normalized_mode, scope=migration_scope)
            logs.extend(restore_result["logs"])
            steps = _replace_step(steps, "sqlite", "succeeded", _summary_label(restore_result["summary"].get("sqlite", {})))
            steps = _replace_step(steps, "prometheus", "succeeded", _summary_label(restore_result["summary"].get("prometheus", {})))
            steps = _replace_step(steps, "health", "running")
            self.tasks.update_task(task_id, progress=85, message="正在执行导入后健康检查", logs=logs[-12:], steps=steps)
            health = self.health_check()
            summary = dict(restore_result["summary"])
            summary["health"] = health
            logs.append(f"健康检查：{health['message']}")
            steps = _replace_step(steps, "health", "succeeded", health["message"])
            links = [
                {"label": "上传包", "filename": upload_path.name, "url": "", "path": str(upload_path), "saved_path": str(upload_path)},
                {"label": "导入前备份", "filename": backup_path.name, "url": "", "path": str(backup_path), "backup_path": str(backup_path)},
                {"label": "导入摘要", "url": "", "path": "", "summary": summary},
            ]
            self.tasks.update_task(task_id, status=TaskStatus.SUCCESS, progress=100, message="数据迁移导入完成", links=links, logs=logs[-20:], steps=steps)
            result = {
                "ok": True,
                "mode": normalized_mode,
                "restored": restore_result["restored"],
                "backup_path": str(backup_path),
                "task_id": task_id,
                "saved_path": str(upload_path),
                "summary": summary,
                "health": health,
            }
            if legacy_response:
                return result
            task = _migration_import_task(self.tasks.get_task(task_id) or {})
            task.update(result)
            return task
        except HTTPException:
            self.tasks.update_task(task_id, status=TaskStatus.FAILED, progress=100, message="数据迁移导入失败", logs=logs, steps=_fail_running_step(steps, "数据迁移导入失败"))
            raise
        except Exception as exc:
            self.tasks.update_task(task_id, status=TaskStatus.FAILED, progress=100, message=str(exc), logs=logs + [str(exc)], steps=_fail_running_step(steps, str(exc)))
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

    def _restore_package(self, package_dir: Path, mode: str, *, scope: str = FULL_SCOPE) -> dict[str, Any]:
        restored: list[str] = []
        logs: list[str] = []
        summary: dict[str, Any] = {"scope": scope, "sqlite": {"inserted": 0}, "prometheus": {"copied": 0, "skipped": 0}}
        source_db = _first_existing(package_dir / APP_DIR / DB_FILENAME, package_dir / V1_APP_DIR / DB_FILENAME)
        source_prometheus = _first_existing(package_dir / PROMETHEUS_DIR, package_dir / V1_PROMETHEUS_DIR)
        if scope == DATA_SCOPE:
            # 数据包的 SQLite 被剥掉了 towers/clusters/users/tasks，整库替换会把
            # 目标机这些表一并清掉——必须在进入任何写动作前挡死。
            if mode == OVERWRITE_MODE:
                raise HTTPException(
                    status_code=400,
                    detail="数据包不支持「整库替换」：替换会把本机 Tower 配置、集群和账号一并清空。监测数据包请用「合并数据」导入。",
                )
            if source_db and source_db.exists():
                summary["sqlite"] = self._merge_data_sqlite(source_db)
                restored.append("smartx_db")
                logs.append(f"SQLite：监测数据合并导入 {summary['sqlite']['inserted']} 条记录（不含 Tower 配置）")
                if summary["sqlite"].get("skipped"):
                    logs.append(f"SQLite：跳过无法归属到本机 Tower 的源行 {summary['sqlite']['skipped']} 条（不照搬源库自增 ID）")
            if source_prometheus and source_prometheus.exists():
                summary["prometheus"] = _copy_missing_tree(source_prometheus, self.settings.prometheus_data_dir, skip_names=PROMETHEUS_RUNTIME_ENTRIES)
                restored.append("prometheus")
                logs.append(f"Prometheus：复制 {summary['prometheus']['copied']} 个 block，跳过 {summary['prometheus']['skipped']} 个 block")
            return {"restored": restored, "summary": summary, "logs": logs}
        if scope == CONFIG_SCOPE:
            if source_db and source_db.exists():
                summary["sqlite"] = self._merge_config_sqlite(source_db)
                restored.append("smartx_db")
                logs.append(f"SQLite：配置合并导入 {summary['sqlite']['inserted']} 条记录")
            logs.append("Prometheus：此导出不包含历史数据，已跳过")
            return {"restored": restored, "summary": summary, "logs": logs}
        if mode == OVERWRITE_MODE:
            if source_db and source_db.exists():
                self.settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_db, self.settings.sqlite_path)
                self.database.initialize()
                restored.append("smartx_db")
                summary["sqlite"]["inserted"] = _count_sqlite_rows(self.settings.sqlite_path)
                logs.append(f"SQLite：覆盖导入 {summary['sqlite']['inserted']} 条记录")
            if source_prometheus and source_prometheus.exists():
                _replace_directory(source_prometheus, self.settings.prometheus_data_dir)
                restored.append("prometheus")
                summary["prometheus"] = _prometheus_summary(source_prometheus)
                logs.append(f"Prometheus：覆盖导入 {summary['prometheus']['copied']} 个 block")
            return {"restored": restored, "summary": summary, "logs": logs}
        if source_db and source_db.exists():
            summary["sqlite"] = self._merge_sqlite(source_db)
            restored.append("smartx_db")
            logs.append(f"SQLite：合并导入 {summary['sqlite']['inserted']} 条记录")
            if summary["sqlite"].get("skipped"):
                logs.append(f"SQLite：跳过无法归属到本机 Tower 的源行 {summary['sqlite']['skipped']} 条（不照搬源库自增 ID）")
        if source_prometheus and source_prometheus.exists():
            summary["prometheus"] = _copy_missing_tree(source_prometheus, self.settings.prometheus_data_dir, skip_names=PROMETHEUS_RUNTIME_ENTRIES)
            restored.append("prometheus")
            logs.append(f"Prometheus：复制 {summary['prometheus']['copied']} 个 block，跳过 {summary['prometheus']['skipped']} 个 block")
        return {"restored": restored, "summary": summary, "logs": logs}

    def _merge_config_sqlite(self, source_db: Path) -> dict[str, Any]:
        self.database.initialize()
        with sqlite3.connect(self.settings.sqlite_path) as target:
            target.row_factory = sqlite3.Row
            target.execute("PRAGMA foreign_keys = ON")
            target.execute("ATTACH DATABASE ? AS incoming", (str(source_db),))
            try:
                tower_map = _merge_towers(target)
                counts = {
                    "towers": len(tower_map),
                    "clusters": _merge_clusters(target, tower_map),
                }
                target.commit()
                return {"inserted": sum(counts.values()), "tables": counts}
            finally:
                target.execute("DETACH DATABASE incoming")

    def _merge_data_sqlite(self, source_db: Path, *, tower_map: dict[int, int] | None = None) -> dict[str, Any]:
        """数据包（DATA_SCOPE）合并导入：只动监测数据表，不碰 towers/clusters。

        tower_id 一律经解析归一（cluster_id 归属优先，其次调用方传入的 tower 映射），
        解析不出的行跳过——**绝不照搬源库自增 ID 产生新孤儿**。
        """
        self.database.initialize()
        with sqlite3.connect(self.settings.sqlite_path) as target:
            target.row_factory = sqlite3.Row
            target.execute("PRAGMA foreign_keys = ON")
            target.execute("ATTACH DATABASE ? AS incoming", (str(source_db),))
            try:
                cluster_tower = _cluster_tower_index(target)
                tower_map = tower_map or {}
                counts: dict[str, int] = {}
                skipped = 0
                counts["vm_latest"], skip = _merge_vm_latest(target, tower_map, cluster_tower)
                skipped += skip
                vol_inserted, skip = _merge_vm_volumes(target, tower_map, cluster_tower)
                v1_inserted, skip1 = _merge_v1_latest_vm_volume_payloads(target, tower_map, cluster_tower)
                counts["vm_volumes"] = vol_inserted + v1_inserted
                skipped += skip + skip1
                counts["collection_runs"], skip = _merge_collection_runs(target)
                skipped += skip
                counts["metric_snapshots"], skip = _merge_metric_snapshot(target)
                skipped += skip
                target.commit()
                return {"inserted": sum(counts.values()), "tables": counts, "skipped": skipped}
            finally:
                target.execute("DETACH DATABASE incoming")

    def _merge_sqlite(self, source_db: Path) -> dict[str, Any]:
        self.database.initialize()
        with sqlite3.connect(self.settings.sqlite_path) as target:
            target.row_factory = sqlite3.Row
            target.execute("PRAGMA foreign_keys = ON")
            target.execute("ATTACH DATABASE ? AS incoming", (str(source_db),))
            try:
                tower_map = _merge_towers(target)
                counts = {
                    "towers": len(tower_map),
                    "clusters": _merge_clusters(target, tower_map),
                }
                cluster_tower = _cluster_tower_index(target)
                skipped = 0
                counts["vm_latest"], skip = _merge_vm_latest(target, tower_map, cluster_tower)
                skipped += skip
                vol_inserted, skip = _merge_vm_volumes(target, tower_map, cluster_tower)
                v1_inserted, skip1 = _merge_v1_latest_vm_volume_payloads(target, tower_map, cluster_tower)
                counts["vm_volumes"] = vol_inserted + v1_inserted
                skipped += skip + skip1
                counts["collection_runs"], skip = _merge_collection_runs(target)
                skipped += skip
                counts["metric_snapshots"], skip = _merge_metric_snapshot(target)
                skipped += skip
                target.commit()
                return {"inserted": sum(counts.values()), "tables": counts, "skipped": skipped}
            finally:
                target.execute("DETACH DATABASE incoming")

    def health_check(self) -> dict[str, Any]:
        sqlite_exists = self.settings.sqlite_path.is_file()
        prometheus_exists = self.settings.prometheus_data_dir.exists()
        prometheus_blocks = [path.name for path in self.settings.prometheus_data_dir.iterdir() if path.is_dir() and (path / "meta.json").is_file()] if prometheus_exists else []
        tables = _sqlite_table_counts(self.settings.sqlite_path) if sqlite_exists else {}
        return {
            "sqlite": {"exists": sqlite_exists, "path": str(self.settings.sqlite_path), "size_bytes": self.settings.sqlite_path.stat().st_size if sqlite_exists else 0, "tables": tables},
            "prometheus": {"exists": prometheus_exists, "path": str(self.settings.prometheus_data_dir), "block_count": len(prometheus_blocks), "blocks": prometheus_blocks[:20]},
            "complete": bool(sqlite_exists and prometheus_blocks),
            "message": "业务库和 Prometheus 历史指标完整" if sqlite_exists and prometheus_blocks else "迁移结果不完整，请确认迁移包是否包含 Prometheus 历史指标。",
        }


def _merge_towers(conn: sqlite3.Connection) -> dict[int, int]:
    """按身份 (name, base_url) 合并源 towers，返回 {源 tower_id: 目标 tower_id} 映射。

    身份匹配到目标现役 Tower → 直接复用其 ID（不产生重复 Tower）；
    未匹配 → 作为新 Tower 插入（AUTOINCREMENT 分配新 ID）。
    绝不按源库自增 ID 照搬——那是跨系统导入产生三代冗余/错挂的根因（#63）。
    """
    mapping: dict[int, int] = {}
    for row in conn.execute("SELECT * FROM incoming.towers ORDER BY id").fetchall():
        name = row["name"]
        base_url = row["base_url"]
        existing = conn.execute(
            "SELECT id FROM towers WHERE name = ? AND base_url = ? ORDER BY enabled DESC, id LIMIT 1",
            (name, base_url),
        ).fetchone()
        if existing is not None:
            mapping[int(row["id"])] = int(existing["id"])
            continue
        cursor = conn.execute(
            """
            INSERT INTO towers (name, base_url, username, password_encrypted, api_token_encrypted, verify_tls, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), COALESCE(?, CURRENT_TIMESTAMP))
            """,
            (
                name,
                base_url,
                row["username"] if "username" in row.keys() else None,
                row["password_encrypted"] if "password_encrypted" in row.keys() else None,
                row["api_token_encrypted"] if "api_token_encrypted" in row.keys() else None,
                row["verify_tls"] if "verify_tls" in row.keys() else 1,
                row["enabled"] if "enabled" in row.keys() else 1,
                row["created_at"] if "created_at" in row.keys() else None,
                row["updated_at"] if "updated_at" in row.keys() else None,
            ),
        )
        mapping[int(row["id"])] = int(cursor.lastrowid)
    return mapping


def _cluster_tower_index(conn: sqlite3.Connection) -> dict[str, int]:
    """cluster_id → 目标 tower_id 索引（同 cluster 多条时优先 enabled、其次最新一代）。"""
    index: dict[str, int] = {}
    for row in conn.execute("SELECT tower_id, cluster_id FROM clusters ORDER BY enabled DESC, tower_id DESC"):
        index.setdefault(str(row["cluster_id"]), int(row["tower_id"]))
    return index


def _resolve_row_tower(row: sqlite3.Row, tower_map: dict[int, int], cluster_tower: dict[str, int]) -> int | None:
    """数据行的目标 tower_id：cluster_id 归属优先，其次 tower 映射；都解析不出 → None（跳过，不留孤儿）。"""
    resolved = cluster_tower.get(str(row["cluster_id"]))
    if resolved is not None:
        return resolved
    return tower_map.get(int(row["tower_id"]))


def _merge_clusters(conn: sqlite3.Connection, tower_map: dict[int, int]) -> int:
    if not _incoming_table_exists(conn, "clusters"):
        return 0
    inserted = 0
    for row in conn.execute("SELECT * FROM incoming.clusters ORDER BY id").fetchall():
        tower_id = tower_map.get(int(row["tower_id"]))
        if tower_id is None:
            continue  # 源集群引用的 Tower 不存在（孤儿集群）——不搬，避免制造新孤儿
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO clusters (tower_id, cluster_id, name, enabled, updated_at)
            VALUES (?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
            """,
            (tower_id, row["cluster_id"], row["name"], row["enabled"] if "enabled" in row.keys() else 1, row["updated_at"] if "updated_at" in row.keys() else None),
        )
        inserted += int(cursor.rowcount or 0)
    return inserted


def _merge_vm_latest(conn: sqlite3.Connection, tower_map: dict[int, int], cluster_tower: dict[str, int]) -> tuple[int, int]:
    if not _incoming_table_exists(conn, "vm_latest"):
        return 0, 0
    inserted = 0
    skipped = 0
    for row in conn.execute("SELECT * FROM incoming.vm_latest").fetchall():
        tower_id = _resolve_row_tower(row, tower_map, cluster_tower)
        if tower_id is None:
            skipped += 1
            continue
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes, updated_at)
            VALUES (?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
            """,
            (tower_id, row["cluster_id"], row["vm_id"], row["name"], row["used_bytes"], row["updated_at"] if "updated_at" in row.keys() else None),
        )
        inserted += int(cursor.rowcount or 0)
    return inserted, skipped


def _merge_vm_volumes(conn: sqlite3.Connection, tower_map: dict[int, int], cluster_tower: dict[str, int]) -> tuple[int, int]:
    if not _incoming_table_exists(conn, "vm_volumes"):
        return 0, 0
    inserted = 0
    skipped = 0
    for row in conn.execute("SELECT * FROM incoming.vm_volumes").fetchall():
        tower_id = _resolve_row_tower(row, tower_map, cluster_tower)
        if tower_id is None:
            skipped += 1
            continue
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO vm_volumes (
                tower_id, cluster_id, vm_id, volume_id, name, path, size_bytes, used_bytes,
                storage_policy, replica_num, thin_provision, ec_k, ec_m, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
            """,
            (
                tower_id,
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
        inserted += int(cursor.rowcount or 0)
    return inserted, skipped


def _merge_v1_latest_vm_volume_payloads(conn: sqlite3.Connection, tower_map: dict[int, int], cluster_tower: dict[str, int]) -> tuple[int, int]:
    if not _incoming_table_exists(conn, "latest_vm_volumes"):
        return 0, 0
    inserted = 0
    skipped = 0
    for row in conn.execute("SELECT * FROM incoming.latest_vm_volumes").fetchall():
        tower_id = _resolve_row_tower(row, tower_map, cluster_tower)
        if tower_id is None:
            skipped += 1
            continue
        volumes = _loads_json_list(row["payload_json"])
        for index, volume in enumerate(volumes):
            normalized = _v1_volume_to_v2(volume, index)
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO vm_volumes (
                    tower_id, cluster_id, vm_id, volume_id, name, path, size_bytes, used_bytes,
                    storage_policy, replica_num, thin_provision, ec_k, ec_m, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
                """,
                (
                    tower_id,
                    row["cluster_id"],
                    row["vm_id"],
                    normalized["volume_id"],
                    normalized["name"],
                    normalized["path"],
                    normalized["size_bytes"],
                    normalized["used_bytes"],
                    normalized["storage_policy"],
                    normalized["replica_num"],
                    normalized["thin_provision"],
                    normalized["ec_k"],
                    normalized["ec_m"],
                    row["collected_at"] if "collected_at" in row.keys() else None,
                ),
            )
            inserted += int(cursor.rowcount or 0)
    return inserted, skipped


def _merge_collection_runs(conn: sqlite3.Connection) -> tuple[int, int]:
    if not _incoming_table_exists(conn, "collection_runs"):
        return 0, 0
    inserted = 0
    skipped = 0
    for row in conn.execute("SELECT * FROM incoming.collection_runs").fetchall():
        cursor = conn.execute(
            "INSERT OR IGNORE INTO collection_runs (id, status, message, started_at, finished_at) VALUES (?, ?, ?, ?, ?)",
            (row["id"], row["status"], row["message"], row["started_at"], row["finished_at"]),
        )
        inserted += int(cursor.rowcount or 0)
    return inserted, skipped


def _merge_metric_snapshot(conn: sqlite3.Connection) -> tuple[int, int]:
    if not _incoming_table_exists(conn, "metric_snapshots"):
        return 0, 0
    inserted = 0
    skipped = 0
    for row in conn.execute("SELECT * FROM incoming.metric_snapshots").fetchall():
        cursor = conn.execute(
            "INSERT OR IGNORE INTO metric_snapshots (id, metrics_text, updated_at) VALUES (?, ?, ?)",
            (row["id"], row["metrics_text"], row["updated_at"]),
        )
        inserted += int(cursor.rowcount or 0)
    return inserted, skipped


@contextmanager
def tempfile_sqlite_copy(source_db: Path) -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as tmpdir:
        target_db = Path(tmpdir) / DB_FILENAME
        with sqlite3.connect(target_db) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(
                """
                CREATE TABLE towers (
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

                CREATE TABLE clusters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tower_id INTEGER NOT NULL REFERENCES towers(id) ON DELETE CASCADE,
                    cluster_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(tower_id, cluster_id)
                );
                """
            )
            if source_db.is_file():
                conn.execute("ATTACH DATABASE ? AS incoming", (str(source_db),))
                try:
                    _copy_config_table(conn, "towers")
                    _copy_config_table(conn, "clusters")
                    conn.commit()
                finally:
                    conn.execute("DETACH DATABASE incoming")
        yield target_db


@contextmanager
def tempfile_sqlite_copy_without(source_db: Path, drop_tables: tuple[str, ...]) -> Iterator[Path]:
    """导出用的 SQLite 拷贝：整库拷贝后 DROP 指定表再 VACUUM。

    用「拷贝后 DROP」而不是「新建空库拷数据」：schema 与源库版本天然一致，
    未来新增业务表默认随包走（drop 清单由调用方按导出语义给定）。
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        target_db = Path(tmpdir) / DB_FILENAME
        if source_db.is_file():
            shutil.copy2(source_db, target_db)
            # 源库是 WAL 模式：DROP 会先落在 -wal 旁文件里，必须显式 close 让
            # SQLite checkpoint 回写主文件——tar 只读主文件，不 close 就会把
            # 没剥的表原样打进包里（.14/.3 实测踩坑：with connect 只 commit 不 close）。
            conn = sqlite3.connect(target_db)
            try:
                for table in drop_tables:
                    conn.execute(f"DROP TABLE IF EXISTS {table}")
                conn.commit()
                conn.execute("VACUUM")
            finally:
                conn.close()
        else:
            # 源库不存在（异常安装）：产出空库文件，导入侧按「表不存在 → 0 行」处理。
            sqlite3.connect(target_db).close()
        yield target_db


def _copy_config_table(conn: sqlite3.Connection, table: str) -> None:
    if not _incoming_table_exists(conn, table):
        return
    target_columns = [str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    incoming_columns = {str(row["name"]) for row in conn.execute(f"PRAGMA incoming.table_info({table})").fetchall()}
    columns = [column for column in target_columns if column in incoming_columns]
    if not columns:
        return
    column_sql = ", ".join(f'"{column}"' for column in columns)
    conn.execute(f"INSERT OR IGNORE INTO {table} ({column_sql}) SELECT {column_sql} FROM incoming.{table}")


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


def _collect_manifest_files(files: list[tuple[Path, str]], directory: Path, arcname: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path, archive_name in files:
        if path.is_file():
            result[archive_name] = _file_manifest(path)
    if directory.exists():
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or any(part in PROMETHEUS_RUNTIME_ENTRIES for part in path.relative_to(directory).parts):
                continue
            result[str(Path(arcname) / path.relative_to(directory))] = _file_manifest(path)
    return result


def _file_manifest(path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    return {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}


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


def _copy_missing_tree(source: Path, target: Path, *, skip_names: set[str]) -> dict[str, int]:
    target.mkdir(parents=True, exist_ok=True)
    copied_blocks = 0
    skipped_blocks = 0
    seen_blocks: set[str] = set()
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
            if relative.parts:
                block = relative.parts[0]
                if block not in seen_blocks and (source / block / "meta.json").is_file():
                    copied_blocks += 1
                    seen_blocks.add(block)
        elif relative.parts and relative.parts[0] not in seen_blocks and (source / relative.parts[0] / "meta.json").is_file():
            skipped_blocks += 1
            seen_blocks.add(relative.parts[0])
    return {"copied": copied_blocks, "skipped": skipped_blocks}


def _replace_directory(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def _prometheus_summary(source: Path) -> dict[str, int]:
    blocks = [path for path in source.iterdir() if path.is_dir() and (path / "meta.json").is_file()] if source.exists() else []
    return {"copied": len(blocks), "skipped": 0}


def _count_sqlite_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with sqlite3.connect(path) as conn:
        total = 0
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
            name = row[0]
            if name.startswith("sqlite_"):
                continue
            try:
                total += int(conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
            except sqlite3.Error:
                continue
        return total


def _sqlite_table_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    with sqlite3.connect(path) as conn:
        tables: dict[str, int] = {}
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall():
            name = str(row[0])
            if name.startswith("sqlite_"):
                continue
            try:
                tables[name] = int(conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
            except sqlite3.Error:
                tables[name] = 0
        return tables


def _summary_label(summary: dict[str, Any]) -> str:
    if not summary:
        return "无数据"
    parts = []
    if "inserted" in summary:
        parts.append(f"写入 {summary['inserted']} 条")
    if "copied" in summary:
        parts.append(f"复制 {summary['copied']} 个")
    if "skipped" in summary:
        parts.append(f"跳过 {summary['skipped']} 个")
    return "，".join(parts) or "完成"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _first_existing(*paths: Path) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _loads_json_list(payload_json: Any) -> list[dict[str, Any]]:
    try:
        payload = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _v1_volume_to_v2(volume: dict[str, Any], index: int) -> dict[str, Any]:
    volume_id = _text(volume.get("id"), volume.get("volume_id"), volume.get("local_id"), volume.get("path"), volume.get("name")) or f"volume-{index}"
    return {
        "volume_id": volume_id,
        "name": _text(volume.get("name"), volume.get("volume_name"), volume.get("path"), volume_id),
        "path": _text(volume.get("path")),
        "size_bytes": int_or_none(volume.get("size"), volume.get("size_bytes"), volume.get("capacity"), volume.get("capacity_bytes"), volume.get("provisioned_size"), volume.get("provisioned_size_bytes")),
        "used_bytes": int_or_none(volume.get("used_size"), volume.get("used_size_bytes"), volume.get("used_bytes")),
        "storage_policy": _text(volume.get("elf_storage_policy"), volume.get("storage_policy"), volume.get("storagePolicy"), volume.get("policy_name"), volume.get("policyName"), volume.get("policy")),
        "replica_num": int_or_none(volume.get("elf_storage_policy_replica_num"), volume.get("replica_num"), volume.get("replicaNum"), volume.get("replica_count"), volume.get("replicaCount")),
        "thin_provision": _bool_to_int(volume.get("elf_storage_policy_thin_provision", volume.get("thin_provision", volume.get("thinProvision")))),
        "ec_k": int_or_none(volume.get("elf_storage_policy_ec_k"), volume.get("ec_data"), volume.get("ecData"), volume.get("ec_k"), volume.get("ecDataUnits")),
        "ec_m": int_or_none(volume.get("elf_storage_policy_ec_m"), volume.get("ec_parity"), volume.get("ecParity"), volume.get("ec_m"), volume.get("ecParityUnits")),
    }


def _text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _bool_to_int(value: Any) -> int | None:
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


def _step(key: str, title: str, status: str, message: str = "") -> dict[str, str]:
    return {"key": key, "title": title, "status": status, "message": message}


def _replace_step(steps: list[dict[str, Any]], key: str, status: str, message: str = "") -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for step in steps:
        if step.get("key") == key:
            next_step = dict(step)
            next_step["status"] = status
            if message:
                next_step["message"] = message
            result.append(next_step)
        else:
            result.append(step)
    return result


def _export_candidate_files(sqlite_path: Path, prometheus_dir: Path) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    if sqlite_path.is_file():
        files.append((sqlite_path, f"{APP_DIR}/{DB_FILENAME}"))
    if prometheus_dir.exists():
        for path in sorted(prometheus_dir.rglob("*")):
            if not path.is_file() or any(part in PROMETHEUS_RUNTIME_ENTRIES for part in path.relative_to(prometheus_dir).parts):
                continue
            files.append((path, str(Path(PROMETHEUS_DIR) / path.relative_to(prometheus_dir))))
    return files


def _migration_export_task(task: dict[str, Any], *, processed_bytes: int | None = None, total_bytes: int | None = None) -> dict[str, Any]:
    link = (task.get("links") or [{}])[0] if task.get("links") else {}
    logs = task.get("logs") or []
    return {
        "task_id": task["id"],
        "status": "succeeded" if task["status"] == TaskStatus.SUCCESS.value else "failed" if task["status"] == TaskStatus.FAILED.value else task["status"],
        "progress": task["progress"],
        "processed_bytes": int(processed_bytes if processed_bytes is not None else link.get("processed_bytes") or 0),
        "total_bytes": int(total_bytes if total_bytes is not None else link.get("total_bytes") or 0),
        "detail": task.get("message") or "",
        "logs": logs,
        "steps": task.get("steps") or [],
        "filename": link.get("filename"),
        "saved_path": link.get("path"),
        "download_url": link.get("url"),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "finished_at": task.get("finished_at"),
    }


def _migration_import_task(task: dict[str, Any]) -> dict[str, Any]:
    links = task.get("links") or []
    upload_link = next((link for link in links if link.get("saved_path") or link.get("label") == "上传包"), {})
    backup_link = next((link for link in links if link.get("backup_path") or link.get("label") == "导入前备份"), {})
    summary_link = next((link for link in links if isinstance(link.get("summary"), dict)), {})
    return {
        "task_id": task["id"],
        "status": "succeeded" if task["status"] == TaskStatus.SUCCESS.value else "failed" if task["status"] == TaskStatus.FAILED.value else task["status"],
        "progress": task.get("progress", 0),
        "detail": task.get("message") or "",
        "logs": task.get("logs") or [],
        "steps": task.get("steps") or [],
        "backup_path": backup_link.get("backup_path") or backup_link.get("path"),
        "saved_path": upload_link.get("saved_path") or upload_link.get("path"),
        "summary": summary_link.get("summary") or {},
        "links": links,
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "finished_at": task.get("finished_at"),
    }


def _fail_running_step(steps: list[dict[str, Any]], message: str) -> list[dict[str, Any]]:
    failed_key = None
    for step in steps:
        if step.get("status") == "running":
            failed_key = step.get("key")
            break
    if failed_key is None:
        running_candidates = [step.get("key") for step in steps if step.get("status") != "succeeded"]
        failed_key = running_candidates[0] if running_candidates else (steps[-1].get("key") if steps else "")
    return _replace_step(steps, str(failed_key), "failed", message) if failed_key else steps


def _size_label(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
