"""升级任务运行产物自动清理（US-09 / S1-2）。

预检失败/仅上传未预检的任务会留下 `upgrades/<task_id>/`：原始压缩包 + 解包目录 `package/`
（一个失败任务约 800 MiB）。这里按 TTL + 保留最近 N 个，自动删除这两处**包内容**，
保留 `task.json`（预检查结论与历史仍留在任务中心）。

设计：docs/superpowers/specs/2026-09-27-upgrade-artifact-housekeeping-design.md
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from app.upgrade_runner.store import TaskStore
from app.v2.tasks.models import TaskStatus, TaskType
from app.v2.tasks.service import TaskService

from .service.execution import _ACTIVE_UPGRADE_STATUSES
from .service.fs import _now

logger = logging.getLogger(__name__)

DEFAULT_TTL_DAYS = 7
DEFAULT_KEEP_RECENT = 3
DEFAULT_INTERVAL_SECONDS = 6 * 3600
TTL_ENV = "SMARTX_UPGRADE_ARTIFACT_TTL_DAYS"
KEEP_ENV = "SMARTX_UPGRADE_ARTIFACT_KEEP_RECENT"
INTERVAL_ENV = "SMARTX_UPGRADE_HOUSEKEEPING_INTERVAL_SECONDS"

# 只清理「从未执行过」的终态；failed/success/rollback_*/cancelled 跑过，属于取证链，不动。
CLEANUP_STATUSES = frozenset({"precheck_failed", "uploaded"})
CLEANED_MESSAGE = "升级包内容已被自动清理（超过保留期限），如需再次使用请重新上传。"


def _task_timestamp(task: dict[str, Any]) -> str:
    return str(task.get("updated_at") or task.get("created_at") or "")


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def _payload_paths(task_dir: Path, task: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for key in ("package_path", "uploaded_path"):
        raw = task.get(key)
        if not raw:
            continue
        candidate = Path(str(raw))
        if _within(candidate, task_dir) and candidate != task_dir:
            paths.append(candidate)
    filename = task.get("filename")
    if filename:
        archive = task_dir / Path(str(filename)).name
        if _within(archive, task_dir) and archive != task_dir:
            paths.append(archive)
    return paths


class UpgradeArtifactHousekeeper:
    """扫描升级任务目录，按期清理从未执行过任务的包内容。"""

    def __init__(
        self,
        settings: Any,
        tasks: TaskService,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.tasks = tasks
        self._now = now or (lambda: datetime.now(timezone.utc))

    # ---- 扫描 -------------------------------------------------------------
    def _read_task_dirs(self) -> list[tuple[Path, dict[str, Any]]]:
        upgrades_dir = Path(self.settings.upgrades_dir)
        if not upgrades_dir.is_dir():
            return []
        entries: list[tuple[Path, dict[str, Any]]] = []
        for task_dir in sorted(upgrades_dir.iterdir()):
            if not task_dir.is_dir() or not (task_dir / "task.json").is_file():
                continue
            try:
                task = TaskStore(task_dir).load()
            except (OSError, ValueError):
                logger.warning("upgrade housekeeping: cannot read %s", task_dir / "task.json")
                continue
            entries.append((task_dir, task))
        return entries

    def _active_task_ids(self, entries: list[tuple[Path, dict[str, Any]]]) -> list[str]:
        return sorted(
            task_dir.name
            for task_dir, task in entries
            if str(task.get("status") or "") in _ACTIVE_UPGRADE_STATUSES
        )

    def _candidates(
        self, entries: list[tuple[Path, dict[str, Any]]], cutoff: datetime
    ) -> list[tuple[Path, dict[str, Any]]]:
        """超期且从未执行过的任务，按 mtime 从新到旧。"""
        candidates: list[tuple[float, Path, dict[str, Any]]] = []
        for task_dir, task in entries:
            if str(task.get("status") or "") not in CLEANUP_STATUSES:
                continue
            stamp = _parse_timestamp(_task_timestamp(task))
            if stamp is None or stamp >= cutoff:
                continue
            try:
                mtime = task_dir.stat().st_mtime
            except OSError:
                continue
            candidates.append((mtime, task_dir, task))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [(task_dir, task) for _, task_dir, task in candidates]

    # ---- 清理 -------------------------------------------------------------
    def cleanup_stale(self, *, ttl_days: int | None = None, keep_recent: int | None = None) -> dict[str, Any]:
        ttl_days = int(self.settings.upgrade_artifact_ttl_days if ttl_days is None else ttl_days)
        keep_recent = int(self.settings.upgrade_artifact_keep_recent if keep_recent is None else keep_recent)
        if ttl_days <= 0:
            return {"ok": True, "skipped": "disabled", "deleted": [], "reclaimed_bytes": 0, "kept": []}

        entries = self._read_task_dirs()
        active = self._active_task_ids(entries)
        if active:
            logger.info("upgrade housekeeping skipped: active upgrade task(s) %s", ", ".join(active))
            return {
                "ok": True,
                "skipped": "active_upgrade",
                "active_task_ids": active,
                "deleted": [],
                "reclaimed_bytes": 0,
                "kept": [],
            }

        cutoff = self._now() - timedelta(days=ttl_days)
        candidates = self._candidates(entries, cutoff)
        keep = max(0, keep_recent)
        kept = [task_dir.name for task_dir, _ in candidates[:keep]]
        deleted: list[str] = []
        reclaimed = 0
        for task_dir, task in candidates[keep:]:
            paths = _payload_paths(task_dir, task)
            if not paths:
                continue
            size = 0
            for path in paths:
                size += _path_bytes(path)
            try:
                for path in paths:
                    if path.is_dir():
                        shutil.rmtree(path)
                    elif path.exists():
                        path.unlink()
                _mark_cleaned(task_dir)
            except OSError:
                logger.exception("upgrade housekeeping: failed to clean %s", task_dir)
                continue
            reclaimed += size
            deleted.append(task_dir.name)

        if deleted:
            self.tasks.create_task(
                f"upgrade-artifacts-{len(deleted)}-{int(reclaimed)}",
                TaskType.CLEANUP,
                "升级产物清理",
                status=TaskStatus.SUCCESS,
                progress=100,
                message=f"自动清理 {len(deleted)} 个过期升级任务的包内容",
                logs=[
                    f"清理任务：{', '.join(deleted)}",
                    f"保留最近 {len(kept)} 个未执行任务",
                    CLEANED_MESSAGE,
                ],
            )
        return {
            "ok": True,
            "skipped": None,
            "deleted": deleted,
            "kept": kept,
            "reclaimed_bytes": reclaimed,
        }


def _path_bytes(path: Path) -> int:
    try:
        if path.is_file():
            return path.stat().st_size
        total = 0
        for child in path.rglob("*"):
            if child.is_file():
                total += child.stat().st_size
        return total
    except OSError:
        return 0


def _mark_cleaned(task_dir: Path) -> None:
    """复核状态后写回：清空包路径、记录清理时间；状态已变化则放弃。"""
    store = TaskStore(task_dir)
    task = store.load()
    if str(task.get("status") or "") not in CLEANUP_STATUSES:
        return
    task["package_cleaned_at"] = _now().isoformat()
    task["package_path"] = None
    task["uploaded_path"] = None
    store.save(task)


def start_upgrade_housekeeping_daemon(
    settings: Any,
    database: Any,
    *,
    interval_seconds: int | None = None,
    stop_event: threading.Event | None = None,
) -> threading.Event | None:
    if interval_seconds is None:
        interval_seconds = settings.upgrade_housekeeping_interval_seconds
    try:
        interval_seconds = int(interval_seconds)
    except (TypeError, ValueError):
        interval_seconds = DEFAULT_INTERVAL_SECONDS
    if interval_seconds <= 0:
        logger.info("upgrade housekeeping disabled (%s<=%s)", INTERVAL_ENV, interval_seconds)
        return None
    event = stop_event or threading.Event()
    worker = threading.Thread(
        target=_housekeeping_loop,
        name="upgrade-artifact-housekeeping",
        args=(settings, database, event, interval_seconds),
        daemon=True,
    )
    worker.start()
    return event


def _housekeeping_loop(settings: Any, database: Any, stop_event: threading.Event, interval_seconds: int) -> None:
    housekeeper = UpgradeArtifactHousekeeper(settings, TaskService(database))
    logger.info("upgrade housekeeping started (interval=%ss)", interval_seconds)
    while not stop_event.is_set():
        try:
            result = housekeeper.cleanup_stale()
            if result.get("deleted"):
                logger.info("upgrade housekeeping cleaned %s (freed %s bytes)", result["deleted"], result["reclaimed_bytes"])
        except Exception:
            logger.exception("upgrade housekeeping iteration failed")
        stop_event.wait(interval_seconds)


__all__ = [
    "CLEANED_MESSAGE",
    "CLEANUP_STATUSES",
    "DEFAULT_INTERVAL_SECONDS",
    "DEFAULT_KEEP_RECENT",
    "DEFAULT_TTL_DAYS",
    "UpgradeArtifactHousekeeper",
    "start_upgrade_housekeeping_daemon",
]
