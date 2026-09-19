from __future__ import annotations

import json
from typing import Any

from app.v2.config import V2Settings
from app.v2.scope import in_enabled_scope
from app.v2.database import V2Database
from app.v2.metrics.prometheus import PrometheusService
from app.v2.metrics.series import labels_match, metric_value, range_values, scoped_query, vm_key


VM_USED_METRIC = "smartx_vm_storage_used_bytes"

# occupied（实际占用集群空间）排序键：复刻前端 getOccupiedSize 口径（副本数 / EC 比率放大）。
_VOLUME_OCCUPIED_SQL = (
    "v.used_bytes * CASE "
    "WHEN COALESCE(v.replica_num, 0) > 0 THEN v.replica_num "
    "WHEN COALESCE(v.ec_k, 0) > 0 AND COALESCE(v.ec_m, 0) > 0 THEN (v.ec_k + v.ec_m) * 1.0 / v.ec_k "
    "ELSE 1 END"
)


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
            key = vm_key(metric)
            if not in_enabled_scope((key[0], key[1]), enabled_scope):
                continue
            name = latest_names.get(key) or str(metric.get("vm_name") or metric.get("vm_id") or "")
            used_bytes = metric_value(row)
            vms.append(
                {
                    "tower_id": int(metric.get("tower_id") or 0),
                    "cluster_id": str(metric.get("cluster_id") or ""),
                    "cluster_name": cluster_names.get((key[0], key[1]), str(metric.get("cluster") or "")),
                    "vm_id": str(metric.get("vm_id") or ""),
                    "vm_name": name,
                    "used_bytes": used_bytes,
                    "metric": {
                        "tower_id": str(metric.get("tower_id") or 0),
                        "cluster_id": str(metric.get("cluster_id") or ""),
                        "cluster": cluster_names.get((key[0], key[1]), str(metric.get("cluster") or "")),
                        "cluster_name": cluster_names.get((key[0], key[1]), str(metric.get("cluster") or "")),
                        "vm_id": str(metric.get("vm_id") or ""),
                        "vm": str(name),
                        "vm_name": str(name),
                    },
                    "value": used_bytes,
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
        freshness = self._collection_freshness(tower_id=tower_id, cluster_id=cluster_id, start_ts=start, end_ts=end)
        return {
            "tower_id": tower_id,
            "cluster_id": cluster_id,
            "vm_id": vm_id,
            "vm_name": latest_names.get((tower_id, cluster_id, vm_id), vm_id),
            "points": points,
            **freshness,
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

    def all_volumes(
        self,
        *,
        tower_id: int | None = None,
        cluster_id: str | None = None,
        page: int | None = None,
        page_size: int = 200,
        sort: str | None = None,
        order: str | None = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        if page is None:
            return self._all_volumes_grouped(tower_id=tower_id, cluster_id=cluster_id)
        return self._all_volumes_page(
            tower_id=tower_id, cluster_id=cluster_id, page=page, page_size=page_size, sort=sort, order=order
        )

    def _all_volumes_grouped(self, *, tower_id: int | None, cluster_id: str | None) -> list[dict[str, Any]]:
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
            if not in_enabled_scope((key[0], key[1]), enabled_scope):
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

    def _all_volumes_page(
        self,
        *,
        tower_id: int | None,
        cluster_id: str | None,
        page: int,
        page_size: int,
        sort: str | None,
        order: str | None,
    ) -> dict[str, Any]:
        page = max(int(page), 1)
        page_size = min(max(int(page_size), 1), 1000)
        sort_field = sort if sort in {"vm", "used", "occupied"} else "used"
        direction = "ASC" if str(order or "desc").lower() == "asc" else "DESC"
        filters: list[str] = []
        params: list[object] = []
        if tower_id is not None:
            filters.append("v.tower_id = ?")
            params.append(tower_id)
        if cluster_id:
            filters.append("v.cluster_id = ?")
            params.append(cluster_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        join_vm_latest = ""
        if sort_field == "vm":
            join_vm_latest = "LEFT JOIN vm_latest vm ON vm.tower_id = v.tower_id AND vm.cluster_id = v.cluster_id AND vm.vm_id = v.vm_id"
            order_sql = f"COALESCE(vm.name, v.vm_id) {direction}, v.name {direction}, v.volume_id {direction}"
        elif sort_field == "occupied":
            order_sql = f"{_VOLUME_OCCUPIED_SQL} {direction}, v.used_bytes {direction}, v.name {direction}"
        else:
            order_sql = f"v.used_bytes {direction}, v.name {direction}, v.volume_id {direction}"
        with self.database.connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM vm_volumes v {where}",
                params,
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT v.tower_id, v.cluster_id, v.vm_id, v.volume_id, v.name, v.path,
                       v.size_bytes, v.used_bytes, v.storage_policy, v.replica_num,
                       v.thin_provision, v.ec_k, v.ec_m, v.updated_at,
                       COALESCE(vm.name, v.vm_id) AS vm_name,
                       COALESCE(cl.name, '') AS cluster_name
                FROM vm_volumes v
                {join_vm_latest}
                LEFT JOIN clusters cl ON cl.tower_id = v.tower_id AND cl.cluster_id = v.cluster_id
                {where}
                ORDER BY {order_sql}
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
        volumes = [
            {
                "tower_id": int(row["tower_id"]),
                "cluster_id": str(row["cluster_id"]),
                "cluster_name": str(row["cluster_name"] or row["cluster_id"]),
                "vm_id": str(row["vm_id"]),
                "vm_name": str(row["vm_name"]),
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
        return {"volumes": volumes, "total": int(total), "page": page, "page_size": page_size}

    def usage_summary(self, *, tower_id: int | None = None, cluster_id: str | None = None) -> list[dict[str, Any]]:
        filters: list[str] = []
        params: list[object] = []
        if tower_id is not None:
            filters.append("tower_id = ?")
            params.append(tower_id)
        if cluster_id:
            filters.append("cluster_id = ?")
            params.append(cluster_id)
        # 与前端逐卷口径一致：used >= 0 且 size > 0 的卷才计入求和。
        filters.append("used_bytes IS NOT NULL AND used_bytes >= 0")
        filters.append("size_bytes IS NOT NULL AND size_bytes > 0")
        where = f"WHERE {' AND '.join(filters)}"
        with self.database.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT tower_id, cluster_id, vm_id,
                       SUM(used_bytes) AS used_bytes,
                       SUM(size_bytes) AS provisioned_bytes
                FROM vm_volumes
                {where}
                GROUP BY tower_id, cluster_id, vm_id
                """,
                params,
            ).fetchall()
        return [
            {
                "tower_id": int(row["tower_id"]),
                "cluster_id": str(row["cluster_id"]),
                "vm_id": str(row["vm_id"]),
                "used_bytes": float(row["used_bytes"] or 0),
                "provisioned_bytes": float(row["provisioned_bytes"] or 0),
            }
            for row in rows
        ]

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
        items = []
        for row in rows:
            if not in_enabled_scope((int(row["tower_id"]), str(row["cluster_id"])), enabled_scope):
                continue
            tower_id = int(row["tower_id"])
            cluster_id = str(row["cluster_id"])
            vm_id = str(row["vm_id"])
            vm_name = str(row["name"])
            cluster_name = cluster_names.get((tower_id, cluster_id), "")
            used_bytes = int(row["used_bytes"] or 0)
            items.append(
                {
                    "tower_id": tower_id,
                    "cluster_id": cluster_id,
                    "cluster_name": cluster_name,
                    "vm_id": vm_id,
                    "vm_name": vm_name,
                    "used_bytes": used_bytes,
                    "metric": {
                        "tower_id": str(tower_id),
                        "cluster_id": cluster_id,
                        "cluster": cluster_name,
                        "cluster_name": cluster_name,
                        "vm_id": vm_id,
                        "vm": vm_name,
                        "vm_name": vm_name,
                    },
                    "value": used_bytes,
                }
            )
        return items

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

    def _collection_freshness(self, *, tower_id: int, cluster_id: str, start_ts: int, end_ts: int) -> dict[str, Any]:
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT status, finished_at, started_at, success_targets_json, failed_targets_json
                FROM collection_runs
                WHERE COALESCE(finished_at, started_at) IS NOT NULL
                ORDER BY COALESCE(finished_at, started_at) ASC, id ASC
                """
            ).fetchall()
        latest_success_at: str | None = None
        latest_status = "unknown"
        gap_dates: list[str] = []
        for row in rows:
            event_at = row["finished_at"] or row["started_at"]
            if _target_in_json(row["success_targets_json"], tower_id=tower_id, cluster_id=cluster_id):
                latest_success_at = event_at
                latest_status = "success"
            if _target_in_json(row["failed_targets_json"], tower_id=tower_id, cluster_id=cluster_id):
                latest_status = "failed"
                date_label = _date_part(event_at)
                if _timestamp_in_window(event_at, start_ts=start_ts, end_ts=end_ts) and date_label and date_label not in gap_dates:
                    gap_dates.append(date_label)
        if latest_status == "success":
            freshness = "fresh"
        elif latest_status == "failed":
            freshness = "stale" if latest_success_at else "partial"
        else:
            freshness = "fresh"
        return {
            "latest_success_at": latest_success_at,
            "latest_collection_status": latest_status,
            "has_collection_gap": bool(gap_dates),
            "gap_dates": gap_dates,
            "data_freshness": freshness,
        }


def _step_for_days(days: int) -> str:
    if days <= 7:
        return "1h"
    if days <= 30:
        return "6h"
    return "1d"


def _target_in_json(value: str | None, *, tower_id: int, cluster_id: str) -> bool:
    targets = _load_json(value)
    return any(str(item.get("tower_id")) == str(tower_id) and str(item.get("cluster_id")) == cluster_id for item in targets)


def _load_json(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _date_part(value: str | None) -> str | None:
    if not value:
        return None
    return str(value).split("T", 1)[0].split(" ", 1)[0]


def _timestamp_in_window(value: str | None, *, start_ts: int, end_ts: int) -> bool:
    if not value:
        return False
    from datetime import datetime, timezone

    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(str(value).split(".")[0], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    start_date = datetime.fromtimestamp(start_ts, tz=timezone.utc).date()
    end_date = datetime.fromtimestamp(end_ts, tz=timezone.utc).date()
    return start_date <= parsed.date() <= end_date
