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
        cluster_names = self._cluster_names()
        enabled_scope = self._enabled_cluster_scope(tower_id=tower_id, cluster_id=cluster_id)
        rows = self.prometheus.instant(scoped_query(VM_USED_METRIC, tower_id=tower_id, cluster_id=cluster_id))
        vms: list[dict[str, Any]] = []
        for row in rows:
            metric = row.get("metric", {})
            if not labels_match(metric, tower_id=tower_id, cluster_id=cluster_id):
                continue
            key = _vm_key(metric)
            if not _in_enabled_scope((key[0], key[1]), enabled_scope):
                continue
            name = latest_names.get(key) or str(metric.get("vm_name") or metric.get("vm_id") or "")
            vms.append(
                {
                    "tower_id": int(metric.get("tower_id") or 0),
                    "cluster_id": str(metric.get("cluster_id") or ""),
                    "cluster_name": cluster_names.get((key[0], key[1]), str(metric.get("cluster") or "")),
                    "vm_id": str(metric.get("vm_id") or ""),
                    "vm_name": name,
                    "used_bytes": metric_value(row),
                }
            )
        if not vms:
            vms = self._latest_vms_from_database(tower_id=tower_id, cluster_id=cluster_id, enabled_scope=enabled_scope, cluster_names=cluster_names)
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

    def all_volumes(self, *, tower_id: int | None = None, cluster_id: str | None = None) -> list[dict[str, Any]]:
        enabled_scope = self._enabled_cluster_scope(tower_id=tower_id, cluster_id=cluster_id)
        cluster_names = self._cluster_names()
        latest_names = self._latest_vm_names()
        filters: list[str] = []
        params: list[object] = []
        if tower_id is not None:
            filters.append("v.tower_id = ?")
            params.append(tower_id)
        if cluster_id:
            filters.append("v.cluster_id = ?")
            params.append(cluster_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.database.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT v.tower_id, v.cluster_id, v.vm_id, v.volume_id, v.name, v.path,
                       v.size_bytes, v.used_bytes, v.storage_policy, v.replica_num,
                       v.thin_provision, v.ec_k, v.ec_m, v.updated_at
                FROM vm_volumes v
                {where}
                ORDER BY v.tower_id, v.cluster_id, v.vm_id, v.name, v.volume_id
                """,
                params,
            ).fetchall()

        grouped: dict[tuple[int, str, str], dict[str, Any]] = {}
        for row in rows:
            key = (int(row["tower_id"]), str(row["cluster_id"]), str(row["vm_id"]))
            if not _in_enabled_scope((key[0], key[1]), enabled_scope):
                continue
            item = grouped.setdefault(
                key,
                {
                    "tower_id": key[0],
                    "cluster_id": key[1],
                    "cluster_name": cluster_names.get((key[0], key[1]), key[1]),
                    "vm_id": key[2],
                    "vm_name": latest_names.get(key, key[2]),
                    "volumes": [],
                },
            )
            item["volumes"].append(
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
            )
        return list(grouped.values())

    def _latest_vm_names(self) -> dict[tuple[int, str, str], str]:
        with self.database.connection() as conn:
            rows = conn.execute("SELECT tower_id, cluster_id, vm_id, name FROM vm_latest").fetchall()
        return {(int(row["tower_id"]), str(row["cluster_id"]), str(row["vm_id"])): str(row["name"]) for row in rows}

    def _cluster_names(self) -> dict[tuple[int, str], str]:
        with self.database.connection() as conn:
            rows = conn.execute("SELECT tower_id, cluster_id, name FROM clusters").fetchall()
        return {(int(row["tower_id"]), str(row["cluster_id"])): str(row["name"]) for row in rows}

    def _latest_vms_from_database(
        self,
        *,
        tower_id: int | None,
        cluster_id: str | None,
        enabled_scope: set[tuple[int, str]],
        cluster_names: dict[tuple[int, str], str],
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        params: list[object] = []
        if tower_id is not None:
            filters.append("tower_id = ?")
            params.append(tower_id)
        if cluster_id:
            filters.append("cluster_id = ?")
            params.append(cluster_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.database.connection() as conn:
            rows = conn.execute(
                f"SELECT tower_id, cluster_id, vm_id, name, used_bytes FROM vm_latest {where}",
                params,
            ).fetchall()
        return [
            {
                "tower_id": int(row["tower_id"]),
                "cluster_id": str(row["cluster_id"]),
                "cluster_name": cluster_names.get((int(row["tower_id"]), str(row["cluster_id"])), ""),
                "vm_id": str(row["vm_id"]),
                "vm_name": str(row["name"]),
                "used_bytes": int(row["used_bytes"] or 0),
            }
            for row in rows
            if _in_enabled_scope((int(row["tower_id"]), str(row["cluster_id"])), enabled_scope)
        ]

    def _enabled_cluster_scope(self, *, tower_id: int | None, cluster_id: str | None) -> set[tuple[int, str]]:
        filters = ["enabled = 1"]
        params: list[object] = []
        if tower_id is not None:
            filters.append("tower_id = ?")
            params.append(tower_id)
        if cluster_id:
            filters.append("cluster_id = ?")
            params.append(cluster_id)
        with self.database.connection() as conn:
            rows = conn.execute(f"SELECT tower_id, cluster_id FROM clusters WHERE {' AND '.join(filters)}", params).fetchall()
        return {(int(row["tower_id"]), str(row["cluster_id"])) for row in rows}


def _vm_key(metric: dict[str, Any]) -> tuple[int, str, str]:
    return (int(metric.get("tower_id") or 0), str(metric.get("cluster_id") or ""), str(metric.get("vm_id") or ""))


def _in_enabled_scope(key: tuple[int, str], enabled_scope: set[tuple[int, str]]) -> bool:
    return key in enabled_scope if enabled_scope else True


def _step_for_days(days: int) -> str:
    if days <= 7:
        return "1h"
    if days <= 30:
        return "6h"
    return "1d"
