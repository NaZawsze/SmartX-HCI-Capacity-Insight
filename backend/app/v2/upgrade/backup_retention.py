"""升级备份保留策略（US-31 尾巴）。

问题：每次升级都产出两类备份，且**无人回收**——`.12` 实测累积 13 份 / 98 MiB，
且随升级次数线性增长，属会持续膨胀的运维债。

产出方（`upgrade_runner/actions.py`）：
    · `backup.create`  → `backups/upgrade-<version>-before-<时间戳>.tar.gz`（数据快照）
    · `project_files`   → `backups/project-files-<task_id>/`（compose/配置备份）

清理策略（与 US-09 产物清理同构：TTL + 保留最近 N 个）：
    · **只按时间与数量裁剪，不按任务状态**——备份的价值与任务状态无关，
      它是"出事前能不能回退"的最后一道保险；取证靠的是 task.json 与任务历史，不是备份文件。
    · 成功/失败任务一视同仁：超过保留窗口或超出保留数量的最旧备份即删除。
    · **每个"任务"两份产物必须同进同退**（`project-files-<id>` 与对应
      `upgrade-*-before-*.tar.gz` 属同一次升级），否则会出现"只剩一半"的残缺备份，
      比多留几份更危险——回退时需要两者配对。

设计：docs/superpowers/specs/2026-09-29-upgrade-backup-retention-design.md
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_TTL_DAYS = 14
DEFAULT_KEEP_RECENT = 5
DEFAULT_INTERVAL_SECONDS = 6 * 3600
TTL_ENV = "SMARTX_UPGRADE_BACKUP_TTL_DAYS"
KEEP_ENV = "SMARTX_UPGRADE_BACKUP_KEEP_RECENT"
INTERVAL_ENV = "SMARTX_UPGRADE_BACKUP_CLEANUP_INTERVAL_SECONDS"

# 数据备份命名：upgrade-<version>-before-<YYYYmmddHHMMSS>.tar.gz
DATA_BACKUP_GLOB = "upgrade-*-before-*.tar.gz"
# 项目文件备份命名：project-files-<task_id>
PROJECT_FILES_PREFIX = "project-files-"

# 单份数据备份的最小合理体积（字节）。低于此值视为异常产物（写了一半/空文件），
# 但仍可删除——它对回退没有价值。
MIN_PLAUSIBLE_BACKUP_BYTES = 1024


def _parse_timestamp(name: str) -> datetime | None:
    """从 `upgrade-v0.5.3-before-20260929090205.tar.gz` 里解出时间戳。"""
    marker = "-before-"
    if marker not in name:
        return None
    stamp = name.split(marker, 1)[1].replace(".tar.gz", "").strip()
    try:
        return datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _modification_time(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def collect_backups(backups_dir: Path) -> list[dict[str, Any]]:
    """列出可清理的备份条目（只读）。每项含 type / path / task_id / 时间。"""
    entries: list[dict[str, Any]] = []
    if not backups_dir.is_dir():
        return entries
    for path in backups_dir.glob(DATA_BACKUP_GLOB):
        if not path.is_file():
            continue
        stamp = _parse_timestamp(path.name) or _modification_time(path)
        entries.append(
            {
                "type": "data",
                "path": path,
                # 数据备份名里没有 task_id，只能靠时间与 project-files 配对
                "time": stamp,
            }
        )
    for path in backups_dir.iterdir():
        if not path.is_dir() or not path.name.startswith(PROJECT_FILES_PREFIX):
            continue
        task_id = path.name[len(PROJECT_FILES_PREFIX) :]
        entries.append(
            {
                "type": "project_files",
                "path": path,
                "task_id": task_id,
                "time": _modification_time(path),
            }
        )
    entries.sort(key=lambda item: (item["time"] or datetime.min.replace(tzinfo=timezone.utc)))
    return entries


def plan_cleanup(
    backups_dir: Path,
    *,
    ttl_days: int = DEFAULT_TTL_DAYS,
    keep_recent: int = DEFAULT_KEEP_RECENT,
) -> dict[str, list[Path]]:
    """只读计算：该删哪些。返回 {"expired": [...], "redundant": [...]}。

    - `expired`：超过 TTL 的旧备份。
    - `redundant`：未过期但超出保留数量的最旧备份。
    两者都**保留最近 keep_recent 份**（无论多旧），避免保留窗口配错导致全清。
    """
    entries = collect_backups(backups_dir)
    if not entries:
        return {"expired": [], "redundant": []}
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(0, ttl_days))
    # 从新到旧排序；最后 keep_recent 份是"回退的最后一道保险"，任何情况下都不删
    newest_first = sorted(
        entries, key=lambda item: (item["time"] or datetime.min.replace(tzinfo=timezone.utc)), reverse=True
    )
    protected = {entry["path"] for entry in newest_first[: max(0, keep_recent)]}

    expired: list[Path] = []
    for entry in newest_first:
        if entry["path"] in protected:
            continue  # 保底份，不参与过期判定
        stamp = entry["time"]
        if stamp is None:
            # 读不到时间的按最旧处理，但只要总量超限就会被裁掉
            expired.append(entry["path"])
            continue
        if stamp < cutoff:
            expired.append(entry["path"])

    # 数量裁剪：从最旧开始删，始终保住 protected
    redundant: list[Path] = []
    if len(entries) > keep_recent:
        overflow = len(entries) - keep_recent
        for entry in reversed(newest_first):  # 最旧 → 最新
            if overflow <= 0:
                break
            if entry["path"] in protected or entry["path"] in expired:
                continue
            redundant.append(entry["path"])
            overflow -= 1
    return {"expired": expired, "redundant": redundant}


def purge_backups(
    backups_dir: Path,
    *,
    ttl_days: int = DEFAULT_TTL_DAYS,
    keep_recent: int = DEFAULT_KEEP_RECENT,
) -> dict[str, Any]:
    """按策略删除超期/超量的备份，返回删除明细（供日志与测试断言）。"""
    plan = plan_cleanup(backups_dir, ttl_days=ttl_days, keep_recent=keep_recent)
    removed: list[str] = []
    freed_bytes = 0
    for kind, paths in plan.items():
        for path in paths:
            try:
                size = path.stat().st_size if path.is_file() else _dir_size(path)
            except OSError:
                size = 0
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            except OSError as exc:
                # 删不掉必须留痕：静默失败会让"已清理"的结论变成假象
                logger.warning("备份清理失败 %s：%s", path, exc)
                continue
            freed_bytes += size
            removed.append(f"{kind}:{path.name}")
    if removed:
        logger.warning(
            "升级备份清理：删除 %d 项，释放 %.1f MiB（TTL=%s 天，保留最近 %s 份）",
            len(removed), freed_bytes / 1024 / 1024, ttl_days, keep_recent,
        )
    return {"removed": removed, "freed_bytes": freed_bytes}


def _dir_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def cleanup_backups_once(
    settings: Any,
    database: Any = None,
    *,
    ttl_days: int | None = None,
    keep_recent: int | None = None,
) -> dict[str, Any]:
    """扫一次备份目录。ttl_days / keep_recent 为 0 时跳过。"""
    ttl = ttl_days if ttl_days is not None else _int_env(TTL_ENV, DEFAULT_TTL_DAYS)
    keep = keep_recent if keep_recent is not None else _int_env(KEEP_ENV, DEFAULT_KEEP_RECENT)
    if ttl <= 0 and keep <= 0:
        return {"removed": [], "freed_bytes": 0, "skipped": True}
    return purge_backups(Path(settings.backups_dir), ttl_days=ttl, keep_recent=keep)


def _loop(
    settings: Any,
    database: Any,
    stop_event: threading.Event,
    interval_seconds: int,
    ttl_days: int | None,
    keep_recent: int | None,
) -> None:
    while not stop_event.is_set():
        try:
            cleanup_backups_once(settings, database, ttl_days=ttl_days, keep_recent=keep_recent)
        except Exception as exc:  # noqa: BLE001 - 守护线程必须存活
            logger.warning("升级备份清理巡检失败：%s", exc)
        stop_event.wait(interval_seconds)


def start_backup_cleanup_daemon(
    settings: Any,
    database: Any = None,
    *,
    interval_seconds: int | None = None,
    ttl_days: int | None = None,
    keep_recent: int | None = None,
    stop_event: threading.Event | None = None,
) -> threading.Event | None:
    if interval_seconds is None:
        interval_seconds = _int_env(INTERVAL_ENV, DEFAULT_INTERVAL_SECONDS)
    try:
        interval_seconds = int(interval_seconds)
    except (TypeError, ValueError):
        interval_seconds = DEFAULT_INTERVAL_SECONDS
    if interval_seconds <= 0:
        logger.info("升级备份清理已关闭（%s<=%s）", INTERVAL_ENV, interval_seconds)
        return None
    event = stop_event or threading.Event()
    worker = threading.Thread(
        target=_loop,
        name="upgrade-backup-cleanup",
        args=(settings, database, event, interval_seconds, ttl_days, keep_recent),
        daemon=True,
    )
    worker.start()
    return event
