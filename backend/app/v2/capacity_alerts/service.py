from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timezone
from typing import Any

from app.v2.config import V2Settings
from app.v2.database import V2Database
from app.v2.metrics.prometheus import PrometheusService
from app.v2.metrics.series import metric_value
from app.v2.scope import in_enabled_scope
from app.v2.tasks.models import TaskType
from app.v2.tasks.service import TaskService


CLUSTER_USED_METRIC = "smartx_cluster_storage_used_bytes"
CLUSTER_TOTAL_METRIC = "smartx_cluster_storage_total_bytes"


class CapacityAlertService:
    def __init__(
        self,
        database: V2Database,
        settings: V2Settings,
        *,
        prometheus: Any | None = None,
        tasks: TaskService | None = None,
        now_ts: int | None = None,
        warning_ratio: float | None = None,
        critical_ratio: float | None = None,
        min_free_bytes: int | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.prometheus = prometheus or PrometheusService(settings.prometheus_url)
        self.tasks = tasks
        self.now_ts = int(now_ts) if now_ts is not None else int(time.time())
        self.warning_ratio = float(
            warning_ratio if warning_ratio is not None else os.environ.get("SMARTX_CAPACITY_ALERT_WARNING_RATIO", "0.75")
        )
        self.critical_ratio = float(
            critical_ratio if critical_ratio is not None else os.environ.get("SMARTX_CAPACITY_ALERT_CRITICAL_RATIO", "0.80")
        )
        self.min_free_bytes = int(
            min_free_bytes if min_free_bytes is not None else os.environ.get("SMARTX_CAPACITY_ALERT_MIN_FREE_BYTES", "0")
        )

    def evaluate(self) -> dict[str, Any]:
        clusters = self._enabled_clusters()
        enabled_scope = {(cluster["tower_id"], cluster["cluster_id"]) for cluster in clusters}
        used_map = self._cluster_metric_map(CLUSTER_USED_METRIC, enabled_scope=enabled_scope)
        total_map = self._cluster_metric_map(CLUSTER_TOTAL_METRIC, enabled_scope=enabled_scope)
        alerts: list[dict[str, Any]] = []
        for cluster in clusters:
            key = (cluster["tower_id"], cluster["cluster_id"])
            if key not in used_map or key not in total_map:
                continue
            total = float(total_map[key])
            used = float(used_map[key])
            if total <= 0:
                continue
            ratio = used / total
            free = max(0.0, total - used)
            level = None
            if ratio >= self.critical_ratio:
                level = "critical"
            elif ratio >= self.warning_ratio:
                level = "warning"
            if level is None and self.min_free_bytes > 0 and free < self.min_free_bytes:
                level = "warning"
            if level is None:
                continue
            alerts.append(
                {
                    "tower_id": key[0],
                    "cluster_id": key[1],
                    "cluster": cluster.get("cluster") or key[1],
                    "tower": cluster.get("tower") or str(key[0]),
                    "level": level,
                    "used_ratio": ratio,
                    "used_bytes": used,
                    "total_bytes": total,
                    "free_bytes": free,
                }
            )
        alerts.sort(key=lambda item: (-{"critical": 1, "warning": 0}[item["level"]], -item["used_ratio"]))
        return {
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "warning_ratio": self.warning_ratio,
            "critical_ratio": self.critical_ratio,
            "min_free_bytes": self.min_free_bytes,
            "clusters_checked": len(clusters),
            "alerts": alerts,
        }

    def evaluate_and_alert(self) -> dict[str, Any]:
        result = self.evaluate()
        if self.tasks is not None:
            for alert in result["alerts"]:
                self._upsert_alert(alert)
        return result

    def _upsert_alert(self, alert: dict[str, Any]) -> dict[str, Any] | None:
        if self.tasks is None:
            return None
        level = alert["level"]
        suffix = hashlib.sha1(str(alert["cluster_id"]).encode("utf-8")).hexdigest()[:8]
        task_id = f"capacity-alert-{level}-{alert['tower_id']}-{suffix}"
        title = f"集群容量高风险：{alert['cluster']}" if level == "critical" else f"集群容量需关注：{alert['cluster']}"
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
        return [
            f"等级：{'高风险' if alert['level'] == 'critical' else '需关注'}",
            f"集群：{alert['tower']} / {alert['cluster']}",
            f"使用率：{alert['used_ratio'] * 100:.2f}%",
            f"已用容量：{_bytes_label(alert['used_bytes'])}",
            f"总容量：{_bytes_label(alert['total_bytes'])}",
            f"剩余空间：{_bytes_label(alert['free_bytes'])}",
            f"告警阈值：黄色 >= {self.warning_ratio * 100:.2f}%，红色 >= {self.critical_ratio * 100:.2f}%",
            f"评估时间：{datetime.now(timezone.utc).isoformat()}",
        ]

    def _enabled_clusters(self) -> list[dict[str, Any]]:
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT t.id AS tower_id, t.name AS tower, c.cluster_id, c.name AS cluster
                FROM clusters c
                JOIN towers t ON t.id = c.tower_id
                WHERE t.enabled = 1 AND c.enabled = 1
                """
            ).fetchall()
        return [
            {"tower_id": int(row["tower_id"]), "cluster_id": str(row["cluster_id"]), "tower": row["tower"], "cluster": row["cluster"]}
            for row in rows
        ]

    def _cluster_metric_map(self, metric_name: str, *, enabled_scope: set[tuple[int, str]]) -> dict[tuple[int, str], float]:
        values: dict[tuple[int, str], float] = {}
        for row in self.prometheus.instant(metric_name):
            metric = row.get("metric", {})
            key = (int(metric.get("tower_id") or 0), str(metric.get("cluster_id") or ""))
            if not in_enabled_scope(key, enabled_scope):
                continue
            values[key] = metric_value(row)
        return values


def _bytes_label(value: float) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(size) < 1024 or unit == "PiB":
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PiB"
