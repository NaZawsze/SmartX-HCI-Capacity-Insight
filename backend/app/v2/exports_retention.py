"""报表导出 / 迁移包 / 导入留档的自动保留（2026-10-04，pending #78）。

## 缺口

`upgrade/housekeeping.py` 的 TTL 自动清理**只管 `upgrades/`**（升级包与备份）。
`exports/` 下的四个目录——

| 目录 | 内容 |
| --- | --- |
| `reports_dir` | 报表导出物（Excel/Word 客户报表） |
| `migrations_dir` | 数据迁出包（SQLite+Prometheus 成对） |
| `imports_dir` | 数据迁入留档 |
| `migration_tasks_dir` | 迁移任务工作目录 |

——**没有任何自动清理**。`.12` 实测磁盘事故追查中，约 450 MiB 正是由此堆积：
客户不会主动去点「空间清理」，磁盘就一直涨。

## 另一个方向的问题：手动清理会**全删**

`CleanupService.cleanup_artifacts` 的 `keep_recent` **只对 `upgrades/` 生效**；
其余三类走 `elif child.is_dir(): rmtree`，即**一次清空**。这对 `imports`/`migrations`
尤其危险——**迁移包可能是客户唯一的重导入凭据**（源库已随迁移被替换），
清掉就再也导不回去。本模块保证自动清理**始终保留最近 N 个**，
不会因为跑了一次后台任务就把客户的迁移凭据清空。

## 口径（与既有配置一致，不新增概念）

- TTL：复用 `SMARTX_UPGRADE_ARTIFACT_TTL_DAYS`（默认 7 天），不另设环境变量
- 保留数：复用 `SMARTX_UPGRADE_ARTIFACT_KEEP_RECENT`（默认 3）
- 默认**保留最近 3 个**且 TTL 作用下的删除有下限保护，绝不清空

## 边界

- 只删**目录内的产物**，不动 `exports/` 本身，也不碰 `upgrades/`（那是 housekeeping 的职责）
- 单个任务正在写入时不应被删：以 mtime 排序 + 只删超过 TTL 且超出保留数的项；
  正在写入的文件 mtime 是最新的，天然落在保留窗口内
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.v2.config import V2Settings

logger = logging.getLogger(__name__)

DEFAULT_TTL_DAYS = 7
#: 自动清理的**保留下限**：无论 TTL 多严，导入/迁出至少留这么多个。
#: 迁移包可能是客户唯一的重导入凭据，清空即不可逆。
MIN_KEEP = 3
DEFAULT_INTERVAL_SECONDS = 6 * 3600
INTERVAL_ENV = "SMARTX_UPGRADE_HOUSEKEEPING_INTERVAL_SECONDS"


def _path_bytes(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    if not path.is_dir():
        return 0
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                continue
    return total


def _mtime(path: Path) -> datetime:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return datetime.now(timezone.utc)


class ExportRetentionService:
    """按 TTL + 保留数清理报表导出 / 迁移包 / 导入留档。"""

    def __init__(
        self,
        settings: V2Settings,
        *,
        now_fn=None,
    ) -> None:
        self.settings = settings
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    # ── 目标目录：reports / migrations / imports / migration-tasks ──────────
    def _targets(self) -> list[tuple[str, Path]]:
        s = self.settings
        return [
            ("报表导出", s.reports_dir),
            ("数据迁出包", s.migrations_dir),
            ("数据迁入留档", s.imports_dir),
            ("迁移任务工作目录", s.migration_tasks_dir),
        ]

    def scan(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for label, path in self._targets():
            if not path.is_dir():
                continue
            children = [c for c in path.iterdir()]
            size = sum(_path_bytes(c) for c in children)
            out.append(
                {
                    "label": label,
                    "path": str(path),
                    "count": len(children),
                    "size": size,
                }
            )
        return out

    def cleanup(self, *, ttl_days: int | None = None, keep_recent: int | None = None) -> dict[str, Any]:
        """删除「超过 TTL 且超出保留数」的产物。返回统计。"""
        ttl_days = int(self.settings.upgrade_artifact_ttl_days if ttl_days is None else ttl_days)
        keep_recent = int(self.settings.upgrade_artifact_keep_recent if keep_recent is None else keep_recent)
        keep = max(MIN_KEEP, keep_recent)

        deleted = 0
        reclaimed = 0
        logs: list[str] = []
        details: list[dict[str, Any]] = []

        for label, path in self._targets():
            if not path.is_dir():
                continue
            try:
                children = sorted(path.iterdir(), key=_mtime, reverse=True)
            except OSError as exc:
                logs.append(f"{label}：读取失败 {exc}")
                continue

            if ttl_days <= 0:
                # TTL 关闭 → 只做保留数裁剪，不按时间删
                victims = children[keep:]
                reason = "超出保留数"
            else:
                cutoff = self._now_fn() - timedelta(days=ttl_days)
                expired = [c for c in children[keep:] if _mtime(c) < cutoff]
                victims = expired
                reason = f"超过 {ttl_days} 天且超出保留数 {keep}"

            removed_here = 0
            freed = 0
            for victim in victims:
                size = _path_bytes(victim)
                try:
                    if victim.is_dir() and not victim.is_symlink():
                        shutil.rmtree(victim)
                    else:
                        victim.unlink()
                except OSError as exc:
                    logs.append(f"{label}：删除 {victim.name} 失败 {exc}")
                    continue
                removed_here += 1
                freed += size
            deleted += removed_here
            reclaimed += freed
            if removed_here:
                logs.append(f"{label}：按「{reason}」清理 {removed_here} 项，释放 {_size(freed)}")
            details.append(
                {
                    "label": label,
                    "kept": max(0, len(children) - removed_here),
                    "deleted": removed_here,
                    "reclaimed": freed,
                }
            )

        return {
            "ok": True,
            "deleted_count": deleted,
            "space_reclaimed": reclaimed,
            "logs": logs,
            "details": details,
            "ttl_days": ttl_days,
            "keep_recent": keep,
        }


def _size(value: float) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(size) < 1024 or unit == "TiB":
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TiB"


def start_export_retention_daemon(
    settings: V2Settings,
    *,
    interval_seconds: int | None = None,
) -> threading.Event | None:
    """后台守护：周期性清理报表/迁移/导入留档。

    返回 `threading.Event` 作为停止信号，与 `start_backup_cleanup_daemon`（US-31）
    保持同一契约，便于 `main.py` 的 shutdown 统一 `set()`；参数 <=0 时返回 None
    表示未启动。调度参数同为 `SMARTX_UPGRADE_HOUSEKEEPING_INTERVAL_SECONDS`（默认 6h）。
    """
    if interval_seconds is None:
        interval_seconds = settings.upgrade_housekeeping_interval_seconds
    # 与 backup_retention 同语义：**0 是合法的「关闭」值**，不能用 `or`——
    # `int(x or 0) or DEFAULT` 会把 0 吞成默认值，导致显式传 0 关不掉守护。
    try:
        interval_seconds = int(interval_seconds)
    except (TypeError, ValueError):
        interval_seconds = DEFAULT_INTERVAL_SECONDS
    if interval_seconds <= 0:
        logger.info("export retention disabled (%s<=%s)", INTERVAL_ENV, interval_seconds)
        return None

    service = ExportRetentionService(settings)
    stop_event = threading.Event()

    def _loop() -> None:
        while not stop_event.is_set():
            try:
                result = service.cleanup()
                if result["deleted_count"]:
                    for line in result["logs"]:
                        logger.info("export retention: %s", line)
            except Exception:  # noqa: BLE001 - 守护线程不得因单次失败退出
                logger.exception("export retention 清理失败")
            stop_event.wait(interval_seconds)

    thread = threading.Thread(target=_loop, name="export-retention", daemon=True)
    thread.start()
    logger.info("export retention daemon started (interval=%ss)", interval_seconds)
    return stop_event
