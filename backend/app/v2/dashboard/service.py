from __future__ import annotations

from typing import Any

from app.v2.config import V2Settings
from app.v2.database import V2Database, row_to_dict
from app.v2.metrics.prometheus import PrometheusService
from app.v2.metrics.series import labels_match, metric_value, range_values, scoped_query


CLUSTER_USED_METRIC = "smartx_cluster_storage_used_bytes"
CLUSTER_TOTAL_METRIC = "smartx_cluster_storage_total_bytes"
VM_USED_METRIC = "smartx_vm_storage_used_bytes"
NORMAL_RISK_MESSAGE = "当前所有集群暂无明显容量风险"


class DashboardService:
    def __init__(self, database: V2Database, settings: V2Settings, prometheus=None, now_ts: int | None = None) -> None:
        self.database = database
        self.settings = settings
        self.prometheus = prometheus or PrometheusService(settings.prometheus_url)
        self.now_ts = int(now_ts) if now_ts is not None else int(__import__("time").time())

    def summary(self, tower_id: int | None = None, cluster_id: str | None = None) -> dict[str, Any]:
        clusters = self._cluster_capacity(tower_id=tower_id, cluster_id=cluster_id)
        vms = self._latest_vms(tower_id=tower_id, cluster_id=cluster_id)
        return {
            "scope": {"tower_id": tower_id, "cluster_id": cluster_id},
            "capacity_risk": self._capacity_risk(clusters),
            "totals": self._totals(tower_id=tower_id, cluster_id=cluster_id),
            "storage": self._storage(clusters),
            "collection": self._latest_collection(),
            "day_fastest_growing_vms": self._day_fastest_growing_vms(tower_id=tower_id, cluster_id=cluster_id),
            "day_new_vms": self._day_new_vms(vms, tower_id=tower_id, cluster_id=cluster_id),
            "clusters": clusters,
        }

    def _cluster_capacity(self, *, tower_id: int | None, cluster_id: str | None) -> list[dict[str, Any]]:
        used_by_key = self._cluster_metric_map(CLUSTER_USED_METRIC, tower_id=tower_id, cluster_id=cluster_id)
        total_by_key = self._cluster_metric_map(CLUSTER_TOTAL_METRIC, tower_id=tower_id, cluster_id=cluster_id)
        names = self._cluster_names()
        clusters: list[dict[str, Any]] = []
        for key in sorted(set(used_by_key) | set(total_by_key)):
            used = used_by_key.get(key, 0.0)
            total = total_by_key.get(key, 0.0)
            ratio = used / total if total > 0 else 0.0
            clusters.append(
                {
                    "tower_id": key[0],
                    "cluster_id": key[1],
                    "name": names.get(key, key[1]),
                    "used_bytes": used,
                    "total_bytes": total,
                    "used_ratio": ratio,
                }
            )
        return clusters

    def _cluster_metric_map(self, metric_name: str, *, tower_id: int | None, cluster_id: str | None) -> dict[tuple[int, str], float]:
        values: dict[tuple[int, str], float] = {}
        for row in self.prometheus.instant(scoped_query(metric_name, tower_id=tower_id, cluster_id=cluster_id)):
            metric = row.get("metric", {})
            if not labels_match(metric, tower_id=tower_id, cluster_id=cluster_id):
                continue
            key = (int(metric.get("tower_id") or 0), str(metric.get("cluster_id") or ""))
            values[key] = metric_value(row)
        return values

    def _capacity_risk(self, clusters: list[dict[str, Any]]) -> dict[str, str]:
        if not clusters:
            return {"level": "normal", "message": NORMAL_RISK_MESSAGE}
        high = [cluster for cluster in clusters if float(cluster["used_ratio"]) >= 0.8]
        if high:
            names = "、".join(cluster["name"] for cluster in high[:3])
            return {"level": "high", "message": f"{names} 使用率超过 80%，容量风险较高。"}
        warning = [cluster for cluster in clusters if float(cluster["used_ratio"]) >= 0.75]
        if warning:
            names = "、".join(cluster["name"] for cluster in warning[:3])
            return {"level": "warning", "message": f"{names} 使用率超过 75%，需要关注容量增长。"}
        return {"level": "normal", "message": NORMAL_RISK_MESSAGE}

    def _totals(self, *, tower_id: int | None, cluster_id: str | None) -> dict[str, int]:
        with self.database.connection() as conn:
            tower_count = conn.execute("SELECT COUNT(*) AS count FROM towers WHERE enabled = 1").fetchone()["count"]
            cluster_filters = ["enabled = 1"]
            cluster_params: list[object] = []
            if tower_id is not None:
                cluster_filters.append("tower_id = ?")
                cluster_params.append(tower_id)
            if cluster_id:
                cluster_filters.append("cluster_id = ?")
                cluster_params.append(cluster_id)
            cluster_count = conn.execute(f"SELECT COUNT(*) AS count FROM clusters WHERE {' AND '.join(cluster_filters)}", cluster_params).fetchone()["count"]
            vm_filters = []
            vm_params: list[object] = []
            if tower_id is not None:
                vm_filters.append("tower_id = ?")
                vm_params.append(tower_id)
            if cluster_id:
                vm_filters.append("cluster_id = ?")
                vm_params.append(cluster_id)
            where = f"WHERE {' AND '.join(vm_filters)}" if vm_filters else ""
            vm_count = conn.execute(f"SELECT COUNT(*) AS count FROM vm_latest {where}", vm_params).fetchone()["count"]
        return {"towers": int(tower_count), "clusters": int(cluster_count), "vms": int(vm_count)}

    def _storage(self, clusters: list[dict[str, Any]]) -> dict[str, float]:
        used = sum(float(cluster["used_bytes"]) for cluster in clusters)
        total = sum(float(cluster["total_bytes"]) for cluster in clusters)
        return {"used_bytes": used, "total_bytes": total, "used_ratio": used / total if total > 0 else 0.0}

    def _latest_collection(self) -> dict[str, Any] | None:
        with self.database.connection() as conn:
            row = row_to_dict(conn.execute("SELECT status, message, finished_at FROM collection_runs ORDER BY id DESC LIMIT 1").fetchone())
        if row is None:
            return None
        return {"status": row["status"], "message": row["message"], "last_success_at": row["finished_at"] if row["status"] == "success" else None}

    def _latest_vms(self, *, tower_id: int | None, cluster_id: str | None) -> list[dict[str, Any]]:
        names = self._latest_vm_names()
        vms: list[dict[str, Any]] = []
        for row in self.prometheus.instant(scoped_query(VM_USED_METRIC, tower_id=tower_id, cluster_id=cluster_id)):
            metric = row.get("metric", {})
            if not labels_match(metric, tower_id=tower_id, cluster_id=cluster_id):
                continue
            key = (int(metric.get("tower_id") or 0), str(metric.get("cluster_id") or ""), str(metric.get("vm_id") or ""))
            vms.append(
                {
                    "tower_id": key[0],
                    "cluster_id": key[1],
                    "vm_id": key[2],
                    "vm_name": names.get(key, str(metric.get("vm_name") or key[2])),
                    "current_bytes": metric_value(row),
                }
            )
        return vms

    def _day_fastest_growing_vms(self, *, tower_id: int | None, cluster_id: str | None) -> list[dict[str, Any]]:
        names = self._latest_vm_names()
        result: list[dict[str, Any]] = []
        start = self.now_ts - 86400
        for series in self.prometheus.range(scoped_query(VM_USED_METRIC, tower_id=tower_id, cluster_id=cluster_id), start=start, end=self.now_ts, step="1h"):
            points = range_values(series)
            if len(points) < 2:
                continue
            metric = series.get("metric", {})
            key = (int(metric.get("tower_id") or 0), str(metric.get("cluster_id") or ""), str(metric.get("vm_id") or ""))
            growth = points[-1][1] - points[0][1]
            if growth <= 0:
                continue
            result.append(
                {
                    "tower_id": key[0],
                    "cluster_id": key[1],
                    "vm_id": key[2],
                    "vm_name": names.get(key, str(metric.get("vm_name") or key[2])),
                    "current_bytes": points[-1][1],
                    "previous_bytes": points[0][1],
                    "growth_amount": growth,
                    "growth_ratio": growth / points[0][1] if points[0][1] > 0 else None,
                }
            )
        return sorted(result, key=lambda item: (-float(item["growth_amount"]), item["vm_name"]))[:100]

    def _day_new_vms(self, vms: list[dict[str, Any]], *, tower_id: int | None, cluster_id: str | None) -> list[dict[str, Any]]:
        existing_keys = set()
        start = self.now_ts - 86400
        for series in self.prometheus.range(scoped_query(VM_USED_METRIC, tower_id=tower_id, cluster_id=cluster_id), start=start, end=self.now_ts, step="1h"):
            points = range_values(series)
            if len(points) >= 2:
                metric = series.get("metric", {})
                existing_keys.add((int(metric.get("tower_id") or 0), str(metric.get("cluster_id") or ""), str(metric.get("vm_id") or "")))
        new_vms = []
        for vm in vms:
            key = (int(vm["tower_id"]), str(vm["cluster_id"]), str(vm["vm_id"]))
            if key not in existing_keys:
                new_vms.append(vm)
        return sorted(new_vms, key=lambda item: item["vm_name"])[:100]

    def _cluster_names(self) -> dict[tuple[int, str], str]:
        with self.database.connection() as conn:
            rows = conn.execute("SELECT tower_id, cluster_id, name FROM clusters").fetchall()
        return {(int(row["tower_id"]), str(row["cluster_id"])): str(row["name"]) for row in rows}

    def _latest_vm_names(self) -> dict[tuple[int, str, str], str]:
        with self.database.connection() as conn:
            rows = conn.execute("SELECT tower_id, cluster_id, vm_id, name FROM vm_latest").fetchall()
        return {(int(row["tower_id"]), str(row["cluster_id"]), str(row["vm_id"])): str(row["name"]) for row in rows}
