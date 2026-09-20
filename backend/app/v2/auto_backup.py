"""数据库自动备份：web-api 侧周期快照，SQLite 与 .env 成对保管。

备份集目录 `backups/auto-backup-<UTC时间戳>/` 含三件：`smartx.db`
（VACUUM INTO 快照，不锁在线库）、`project.env`（0600 副本，与快照
同代配对——Tower 凭据解密依赖它）、`manifest.json`（校验信息）。
删除必须整集删除，不出现"删了库留下孤儿钥匙"。

周期与保留由环境变量控制；间隔 <=0 时整体关闭。异常不抛出守护
线程：失败记任务中心告警后继续下一轮。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.v2.config import V2Settings
from app.v2.database import V2Database
from app.v2.tasks.models import TaskStatus, TaskType
from app.v2.tasks.service import TaskService

logger = logging.getLogger(__name__)

AUTO_BACKUP_FORMAT = "smartx-auto-backup"
DEFAULT_INTERVAL_HOURS = 24
DEFAULT_KEEP = 7
DEFAULT_INITIAL_DELAY_SECONDS = 60
_INTERVAL_ENV = "SMARTX_AUTO_BACKUP_INTERVAL_HOURS"
_KEEP_ENV = "SMARTX_AUTO_BACKUP_KEEP"
_INITIAL_DELAY_ENV = "SMARTX_AUTO_BACKUP_INITIAL_DELAY_SECONDS"
AUTO_BACKUP_DIR_PREFIX = "auto-backup-"
_TS_FORMAT = "%Y%m%dT%H%M%SZ"


def auto_backup_interval_hours() -> int:
    raw = os.environ.get(_INTERVAL_ENV, "").strip()
    try:
        return int(raw) if raw else DEFAULT_INTERVAL_HOURS
    except ValueError:
        return DEFAULT_INTERVAL_HOURS


def auto_backup_keep() -> int:
    raw = os.environ.get(_KEEP_ENV, "").strip()
    try:
        return max(1, int(raw)) if raw else DEFAULT_KEEP
    except ValueError:
        return DEFAULT_KEEP


class AutoBackupService:
    def __init__(
        self,
        database: V2Database,
        settings: V2Settings,
        tasks: TaskService | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.tasks = tasks

    def run_backup(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        db_path = self.settings.sqlite_path
        env_path = self.settings.env_file_path
        db_size = db_path.stat().st_size if db_path.exists() else 0
        env_size = env_path.stat().st_size if env_path.exists() else 0
        result: dict[str, Any] = {
            "status": "success",
            "backup_dir": "",
            "database_included": bool(db_size),
            "env_included": False,
            "pruned": [],
        }
        if not db_size:
            return self._finish(current, result, failed_message="业务数据库不存在，已跳过自动备份。")
        free = shutil.disk_usage(self.settings.data_root).free
        if free < (db_size + env_size) * 2:
            return self._finish(current, result, failed_message=f"磁盘可用空间不足（{free} 字节），已跳过本次自动备份。")

        backup_dir = self.settings.backups_dir / f"{AUTO_BACKUP_DIR_PREFIX}{current.strftime(_TS_FORMAT)}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        result["backup_dir"] = str(backup_dir)
        snapshot = backup_dir / "smartx.db"
        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute("VACUUM INTO ?", (str(snapshot),))
            with sqlite3.connect(snapshot) as conn:
                check = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if str(check) != "ok":
                raise RuntimeError(f"快照完整性校验失败：{check}")
        except Exception as exc:
            shutil.rmtree(backup_dir, ignore_errors=True)
            return self._finish(current, result, failed_message=f"数据库快照失败：{exc}")

        env_lines: list[str] = []
        if env_path.is_file():
            env_copy = backup_dir / "project.env"
            shutil.copy2(env_path, env_copy)
            os.chmod(env_copy, 0o600)
            result["env_included"] = True
        else:
            env_lines.append("警告：project/.env 不存在，本次备份未包含配对密钥文件。")

        manifest = {
            "format": AUTO_BACKUP_FORMAT,
            "version": 1,
            "created_at": current.isoformat(),
            "app_version": self.settings.app_version,
            "database": {"filename": "smartx.db", "size": snapshot.stat().st_size, "sha256": _sha256(snapshot)},
            "env": {"filename": "project.env", "included": result["env_included"], "sha256": _sha256(env_path) if env_path.is_file() else None},
            "source_db_path": str(db_path),
        }
        (backup_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        result["pruned"] = self._prune_old_backups(keep=auto_backup_keep())
        message = f"自动备份完成：{backup_dir.name}" + (f"（含 .env 配对）" if result["env_included"] else "（未含 .env）")
        self._finish(current, result, message=message, extra_logs=env_lines)
        return result

    def _finish(
        self,
        current: datetime,
        result: dict[str, Any],
        *,
        message: str | None = None,
        failed_message: str | None = None,
        extra_logs: list[str] | None = None,
    ) -> dict[str, Any]:
        logs = [line for line in [message or failed_message, *(extra_logs or [])] if line]
        if failed_message:
            result["status"] = "failed"
        if self.tasks is not None:
            links = []
            backup_dir = result.get("backup_dir")
            if result["status"] == "success" and backup_dir:
                directory = Path(backup_dir)
                links = [
                    {"label": "数据库快照", "filename": "smartx.db", "url": "", "path": str(directory / "smartx.db")},
                    {"label": "配对 .env", "filename": "project.env", "url": "", "path": str(directory / "project.env")},
                    {"label": "manifest", "filename": "manifest.json", "url": "", "path": str(directory / "manifest.json")},
                ]
            self.tasks.create_task(
                f"auto-backup-{current.strftime(_TS_FORMAT)}",
                TaskType.BACKUP,
                "自动数据库备份",
                status=TaskStatus.FAILED if failed_message else TaskStatus.SUCCESS,
                progress=100,
                message=failed_message or message or "",
                logs=logs,
                links=links,
            )
        return result

    def _prune_old_backups(self, *, keep: int) -> list[str]:
        sets = sorted(
            (path for path in self.settings.backups_dir.iterdir() if path.is_dir() and path.name.startswith(AUTO_BACKUP_DIR_PREFIX)),
            key=lambda path: path.name,
            reverse=True,
        )
        pruned: list[str] = []
        for stale in sets[keep:]:
            shutil.rmtree(stale, ignore_errors=True)
            pruned.append(stale.name)
        return pruned


def start_auto_backup_daemon(database: V2Database, settings: V2Settings, *, interval_hours: int | None = None) -> threading.Event | None:
    """启动自动备份守护线程，返回停止信号；间隔 <=0 时不启动（关闭开关）。"""
    if interval_hours is None:
        interval_hours = auto_backup_interval_hours()
    if interval_hours <= 0:
        logger.info("auto backup disabled (%s<=%s)", _INTERVAL_ENV, interval_hours)
        return None
    raw = os.environ.get(_INITIAL_DELAY_ENV, "").strip()
    try:
        initial_delay = int(raw) if raw else DEFAULT_INITIAL_DELAY_SECONDS
    except ValueError:
        initial_delay = DEFAULT_INITIAL_DELAY_SECONDS
    stop_event = threading.Event()
    worker = threading.Thread(
        target=_backup_loop,
        name="auto-backup",
        args=(database, settings, stop_event, interval_hours, max(0, initial_delay)),
        daemon=True,
    )
    worker.start()
    return stop_event


def _backup_loop(
    database: V2Database,
    settings: V2Settings,
    stop_event: threading.Event,
    interval_hours: int,
    initial_delay: int,
) -> None:
    tasks = TaskService(database)
    service = AutoBackupService(database, settings, tasks)
    interval_seconds = interval_hours * 3600
    logger.info("auto backup started (interval=%sh, keep=%s)", interval_hours, auto_backup_keep())
    if not stop_event.wait(initial_delay):
        try:
            result = service.run_backup()
            logger.info("auto backup finished: %s", result.get("status"))
        except Exception:
            logger.exception("auto backup iteration failed")
    while not stop_event.is_set():
        if stop_event.wait(interval_seconds):
            break
        try:
            result = service.run_backup()
            logger.info("auto backup finished: %s", result.get("status"))
        except Exception:
            logger.exception("auto backup iteration failed")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
