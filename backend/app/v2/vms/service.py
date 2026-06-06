from __future__ import annotations

from typing import Any

from app.v2.config import V2Settings
from app.v2.database import V2Database
from app.v2.metrics.prometheus import PrometheusService
from app.v2.metrics.series import labels_match, metric_value, range_values, scoped_query


VM_USED_METRIC = "smartx_vm_storage_used_bytes"


class VmService:
    def __init__(self, database: V2Database, settings: V2Settings, prometheus=None, now_ts: int | None = None) -> None:
        self.database = database
        self.settings = settings
        self.prometheus = prometheus or PrometheusService(settings.prometheus_url)
        self.now_ts = now_ts

    def list_vms(self, tower_id: int | None = None, cluster_id: str | None = None) -> list[dict[str, Any]]:
        latest_names = self._latest_vm_names()
        rows = self.prometheus.instant(scoped_query(VM_USED_METRIC, tower_id=tower_id, cluster_id=cluster_id))
        vms: list[dict[str, Any]] = []
        for row in rows:
            metric = row.get("metric", {})
            if not labels_match(metric, tower_id=tower_id, cluster_id=cluster_id):
                continue
            key = _vm_key(metric)
            name = latest_names.get(key) or str(metric.get("vm_name") or metric.get("vm_id") or "")
            vms.append(
                {
                    "tower_id": int(metric.get("tower_id") or 0),
                    "cluster_id": str(metric.get("cluster_id") or ""),
                    "vm_id": str(metric.get("vm_id") or ""),
                    "vm_name": name,
                    "used_bytes": metric_value(row),
                }
            )
        return sorted(vms, key=lambda item: (-float(item["used_bytes"]), item["vm_name"]))

    def trend(self, *, vm_id: str, tower_id: int, cluster_id: str, days: int) -> dict[str, Any]:
        end = self.now_ts or __import__("time").time()
        start = int(end - days * 86400)
        end = int(end)
        query = scoped_query(VM_USED_METRIC, tower_id=tower_id, cluster_id=cluster_id, vm_id=vm_id)
        result = self.prometheus.range(query, start=start, end=end, step=_step_for_days(days))
        points: list[dict[str, float | int]] = []
        for series in result:
            for timestamp, value in range_values(series):
                points.append({"timestamp": timestamp, "used_bytes": value})
        latest_names = self._latest_vm_names()
        return {
            "tower_id": tower_id,
            "cluster_id": cluster_id,
            "vm_id": vm_id,
            "vm_name": latest_names.get((tower_id, cluster_id, vm_id), vm_id),
            "points": points,
        }

    def detail(self, *, vm_id: str, tower_id: int, cluster_id: str) -> dict[str, Any]:
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT tower_id, cluster_id, vm_id, name, used_bytes, updated_at FROM vm_latest WHERE tower_id = ? AND cluster_id = ? AND vm_id = ?",
                (tower_id, cluster_id, vm_id),
            ).fetchone()
        if row is None:
            return {"tower_id": tower_id, "cluster_id": cluster_id, "vm_id": vm_id, "vm_name": vm_id, "used_bytes": 0, "updated_at": None}
        return {
            "tower_id": int(row["tower_id"]),
            "cluster_id": str(row["cluster_id"]),
            "vm_id": str(row["vm_id"]),
            "vm_name": str(row["name"]),
            "used_bytes": int(row["used_bytes"]),
            "updated_at": row["updated_at"],
        }

    def volumes(self, *, vm_id: str, tower_id: int, cluster_id: str) -> list[dict[str, Any]]:
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT volume_id, name, path, size_bytes, used_bytes, storage_policy,
                       replica_num, thin_provision, ec_k, ec_m, updated_at
                FROM vm_volumes
                WHERE tower_id = ? AND cluster_id = ? AND vm_id = ?
                ORDER BY name, volume_id
                """,
                (tower_id, cluster_id, vm_id),
            ).fetchall()
        return [
            {
                "volume_id": str(row["volume_id"]),
                "name": row["name"],
                "path": row["path"],
                "size_bytes": row["size_bytes"],
                "used_bytes": row["used_bytes"],
                "storage_policy": row["storage_policy"],
                "replica_num": row["replica_num"],
                "thin_provision": bool(row["thin_provision"]) if row["thin_provision"] is not None else None,
                "ec_k": row["ec_k"],
                "ec_m": row["ec_m"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def _latest_vm_names(self) -> dict[tuple[int, str, str], str]:
        with self.database.connection() as conn:
            rows = conn.execute("SELECT tower_id, cluster_id, vm_id, name FROM vm_latest").fetchall()
        return {(int(row["tower_id"]), str(row["cluster_id"]), str(row["vm_id"])): str(row["name"]) for row in rows}


def _vm_key(metric: dict[str, Any]) -> tuple[int, str, str]:
    return (int(metric.get("tower_id") or 0), str(metric.get("cluster_id") or ""), str(metric.get("vm_id") or ""))


def _step_for_days(days: int) -> str:
    if days <= 7:
        return "1h"
    if days <= 30:
        return "6h"
    return "1d"
