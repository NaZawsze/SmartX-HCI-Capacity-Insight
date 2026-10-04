"""磁盘占用告警（2026-10-04 新增）。

为什么需要（`.12` 实测事故链）：

    2026-07起有两个 `running` 僵尸任务永久锁死空间清理
      → 磁盘堆到 94%（`upgrades/` 14G 历史升级包）
      → `/tmp`（tmpfs 3.7G）也 100% 满，连 scp 都传不进包
      → 客户全程**收不到任何通知**，只有升级失败时才发现

`capacity_alerts` 原先只管**集群容量**（使用率/剩余空间），磁盘完全无人看管。
本模块补上这一层，复用同一套 severity 体系与 `tasks.upsert_alert` 去重机制。

口径：
- 用 `shutil.disk_usage(data_root)` 取**平台数据目录所在文件系统**的使用率——
  这就是客户升级会写满的那块盘（不是 `/`，也不是任意分区）。
- 阈值默认 **80% 需关注 / 90% 高风险**，与集群容量告警同一套 warning/critical 语义；
  可用环境变量覆盖。
- 另设**绝对下限** `min_free_bytes`（默认 2 GiB）：小盘客户 90% 还没到，
  但 2 GiB 已经不够写一个升级包了，此时也应预警。
"""

from __future__ import annotations

import hashlib
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.v2.tasks.models import TaskType
from app.v2.tasks.service import TaskService


def _bytes_label(value: float) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(size) < 1024 or unit == "PiB":
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PiB"


class DiskAlertService:
    """按数据目录所在文件系统的占用率产出告警。"""

    def __init__(
        self,
        settings: Any,
        tasks: TaskService | None = None,
        *,
        warning_ratio: float | None = None,
        critical_ratio: float | None = None,
        min_free_bytes: int | None = None,
        usage: Any = None,
    ) -> None:
        self.settings = settings
        self.tasks = tasks
        self.usage = usage or shutil.disk_usage
        self.warning_ratio = float(
            warning_ratio
            if warning_ratio is not None
            else os.environ.get("SMARTX_DISK_ALERT_WARNING_RATIO", "0.80")
        )
        self.critical_ratio = float(
            critical_ratio
            if critical_ratio is not None
            else os.environ.get("SMARTX_DISK_ALERT_CRITICAL_RATIO", "0.90")
        )
        # 绝对下限：占用率没到阈值，但剩余空间已不够写一个升级包时也要预警
        self.min_free_bytes = int(
            min_free_bytes
            if min_free_bytes is not None
            else os.environ.get("SMARTX_DISK_ALERT_MIN_FREE_BYTES", str(2 * 1024**3))
        )

    def _watched_path(self) -> Path:
        """被监控的目录：平台数据根（客户升级会写满的那块盘）。"""
        return Path(self.settings.data_root)

    def evaluate(self) -> dict[str, Any]:
        path = self._watched_path()
        try:
            path.mkdir(parents=True, exist_ok=True)
            stat = self.usage(path)
            total = int(stat.total)
            free = int(stat.free)
        except OSError as exc:
            return {
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
                "error": f"无法读取磁盘占用：{exc}",
                "alerts": [],
            }
        used = max(0, total - free)
        ratio = (used / total) if total > 0 else 0.0

        level: str | None = None
        if ratio >= self.critical_ratio:
            level = "critical"
        elif ratio >= self.warning_ratio:
            level = "warning"
        elif self.min_free_bytes > 0 and free < self.min_free_bytes:
            # 剩余空间已不足以容纳一个升级包（默认盘 60G 时约 3% 就会命中）
            level = "warning"

        alerts: list[dict[str, Any]] = []
        if level is not None:
            alerts.append(
                {
                    "level": level,
                    "path": str(path),
                    "used_ratio": ratio,
                    "used_bytes": used,
                    "total_bytes": total,
                    "free_bytes": free,
                }
            )

        return {
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "warning_ratio": self.warning_ratio,
            "critical_ratio": self.critical_ratio,
            "min_free_bytes": self.min_free_bytes,
            "alerts": alerts,
        }

    def evaluate_and_alert(self) -> dict[str, Any]:
        result = self.evaluate()
        for alert in result.get("alerts") or []:
            self._upsert_alert(alert)
        return result

    def _upsert_alert(self, alert: dict[str, Any]) -> dict[str, Any] | None:
        if self.tasks is None:
            return None
        level = alert["level"]
        # 路径参与 task_id：多挂载点场景下各发一条，互不覆盖
        suffix = hashlib.sha1(str(alert["path"]).encode("utf-8")).hexdigest()[:8]
        task_id = f"disk-alert-{level}-{suffix}"
        title = (
            f"磁盘空间高风险：{alert['path']}"
            if level == "critical"
            else f"磁盘空间需关注：{alert['path']}"
        )
        message = "\n".join(self._message_lines(alert))
        return self.tasks.upsert_alert(
            task_id,
            TaskType.COLLECTION,
            title,
            severity=level,
            message=message,
            logs=message.splitlines(),
        )

    def _message_lines(self, alert: dict[str, Any]) -> list[str]:
        lines = [
            f"等级：{'高风险' if alert['level'] == 'critical' else '需关注'}",
            f"路径：{alert['path']}",
            f"占用率：{alert['used_ratio'] * 100:.2f}%",
            f"已用：{_bytes_label(alert['used_bytes'])}",
            f"总容量：{_bytes_label(alert['total_bytes'])}",
            f"剩余空间：{_bytes_label(alert['free_bytes'])}",
            f"告警阈值：黄色 >= {self.warning_ratio * 100:.2f}%，红色 >= {self.critical_ratio * 100:.2f}%，"
            f"或剩余 < {_bytes_label(self.min_free_bytes)}",
        ]
        if alert["level"] != "critical" and alert["used_ratio"] < self.warning_ratio:
            lines.append("提示：占用率未达百分比阈值，但剩余空间已不足以写入升级包")
        lines.append(
            "处置：系统 → 空间清理，扫描并清理历史升级包/报表/迁入留档"
            "（会保留最近一次升级的完整包与全部升级记录）。"
        )
        lines.append(f"评估时间：{datetime.now(timezone.utc).isoformat()}")
        return lines
