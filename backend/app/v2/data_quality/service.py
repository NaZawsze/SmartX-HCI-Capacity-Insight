from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.v2.config import V2Settings
from app.v2.database import V2Database
from app.v2.metrics.prometheus import PrometheusService
from app.v2.tasks.models import TaskStatus, TaskType
from app.v2.tasks.service import TaskService


SECONDS_PER_DAY = 86_400
VM_USED_METRIC = "smartx_vm_storage_used_bytes"
CLUSTER_USED_METRIC = "smartx_cluster_storage_used_bytes"


class DataQualityService:
    def __init__(
        self,
        database: V2Database,
        settings: V2Settings,
        *,
        prometheus: Any | None = None,
        tasks: TaskService | None = None,
        now_ts: int | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.prometheus = prometheus or PrometheusService(settings.prometheus_url)
        self.tasks = tasks
        self.now_ts = int(now_ts) if now_ts is not None else int(time.time())

    def evaluate(self, *, tower_id: int | None = None, cluster_id: str | None = None, period_days: int = 30) -> dict[str, Any]:
        period_days = _normalize_period_days(period_days)
        clusters = self._enabled_clusters(tower_id=tower_id, cluster_id=cluster_id)
        requested_window = _requested_window(self.now_ts, period_days)
        messages: list[str] = []
        if not clusters:
            return self._result(
                status="warning",
                requested_window=requested_window,
                actual_window={},
                sample_sufficient=False,
                clusters=[],
                sqlite_vm_count=0,
                prometheus_vm_count=0,
                prometheus_cluster_count=0,
                latest_collection={},
                latest_prometheus_sample_at=None,
                missing_dates=[],
                incomplete_clusters=[],
                messages=["暂无启用采集目标，无法判断数据质量。"],
            )
        sqlite_vm_count = self._sqlite_vm_count(clusters)
        prometheus_error: str | None = None
        vm_rows: list[dict[str, Any]] = []
        cluster_rows: list[dict[str, Any]] = []
        range_rows: list[dict[str, Any]] = []
        try:
            vm_rows = self.prometheus.instant(VM_USED_METRIC)
            cluster_rows = self.prometheus.instant(CLUSTER_USED_METRIC)
            range_rows = [
                *self.prometheus.range(VM_USED_METRIC, start=self.now_ts - period_days * SECONDS_PER_DAY, end=self.now_ts, step="6h"),
                *self.prometheus.range(CLUSTER_USED_METRIC, start=self.now_ts - period_days * SECONDS_PER_DAY, end=self.now_ts, step="1d"),
            ]
        except Exception as exc:  # noqa: BLE001 - quality result should include SQLite facts.
            prometheus_error = str(exc)
            messages.append(f"Prometheus 查询失败：{exc}")
        cluster_keys = {(cluster["tower_id"], cluster["cluster_id"]) for cluster in clusters}
        vm_rows = [row for row in vm_rows if _cluster_key(row.get("metric", {})) in cluster_keys]
        cluster_rows = [row for row in cluster_rows if _cluster_key(row.get("metric", {})) in cluster_keys]
        prometheus_vm_count = len({_vm_key(row.get("metric", {})) for row in vm_rows if _vm_key(row.get("metric", {}))[2]})
        prometheus_cluster_keys = {_cluster_key(row.get("metric", {})) for row in cluster_rows}
        latest_prometheus_ts = max([_sample_ts(row) for row in [*vm_rows, *cluster_rows]] or [None])
        latest_collection = self._latest_collection()
        missing_dates, failed_cluster_keys = self._missing_collection_dates(period_days=period_days, cluster_keys=cluster_keys)
        range_rows = [row for row in range_rows if _cluster_key(row.get("metric", {})) in cluster_keys]
        actual_window = self._actual_data_window(period_days=period_days, range_rows=range_rows)
        sample_sufficient = int(actual_window.get("days") or 0) >= period_days if actual_window else False
        incomplete_clusters = []
        for cluster in clusters:
            key = (cluster["tower_id"], cluster["cluster_id"])
            reason = None
            if key not in prometheus_cluster_keys:
                reason = "prometheus_cluster_sample_missing"
            elif key in failed_cluster_keys:
                reason = "collection_failed_in_window"
            if reason:
                incomplete_clusters.append({**cluster, "reason": reason})
        difference = abs(sqlite_vm_count - prometheus_vm_count)
        difference_ratio = difference / sqlite_vm_count if sqlite_vm_count else 0.0
        status = "ok"
        if prometheus_error:
            status = "critical"
        if latest_collection.get("status") == "success" and (prometheus_vm_count == 0 or len(prometheus_cluster_keys) == 0):
            status = "critical"
            messages.append("最近一次采集成功但 Prometheus 当前样本为空。")
        if sqlite_vm_count and prometheus_vm_count < sqlite_vm_count * 0.5:
            status = "critical"
            messages.append("Prometheus 当前 VM series 数低于 SQLite 当前 VM 数的 50%。")
        elif sqlite_vm_count and difference > max(10, sqlite_vm_count * 0.1):
            status = _max_status(status, "warning")
            messages.append("SQLite 当前 VM 数与 Prometheus 当前 VM series 数差异超过阈值。")
        if incomplete_clusters:
            status = _max_status(status, "warning")
            messages.append(f"发现 {len(incomplete_clusters)} 个数据不完整集群。")
        if missing_dates:
            status = _max_status(status, "warning")
            messages.append(f"存在 {len(missing_dates)} 天采集异常。")
        if not sample_sufficient:
            status = _max_status(status, "warning")
            messages.append(f"当前实际采集样本约 {actual_window.get('days') or 0} 天，少于本报表选择的 {period_days} 天窗口。")
        if status == "ok":
            messages.append("当前报表范围内未发现明显数据缺口。")
        return self._result(
            status=status,
            requested_window=requested_window,
            actual_window=actual_window,
            sample_sufficient=sample_sufficient,
            clusters=clusters,
            sqlite_vm_count=sqlite_vm_count,
            prometheus_vm_count=prometheus_vm_count,
            prometheus_cluster_count=len(prometheus_cluster_keys),
            latest_collection=latest_collection,
            latest_prometheus_sample_at=datetime.fromtimestamp(latest_prometheus_ts, tz=timezone.utc).isoformat() if latest_prometheus_ts else None,
            missing_dates=missing_dates,
            incomplete_clusters=incomplete_clusters,
            messages=_dedupe(messages),
            prometheus_error=prometheus_error,
            vm_count_difference=difference,
            vm_count_difference_ratio=difference_ratio,
        )

    def evaluate_and_alert(self, *, tower_id: int | None = None, cluster_id: str | None = None, period_days: int = 30) -> dict[str, Any]:
        result = self.evaluate(tower_id=tower_id, cluster_id=cluster_id, period_days=period_days)
        if self.tasks is None or result["status"] == "ok":
            return result
        title = "数据一致性异常" if result["status"] == "critical" else "数据质量需关注"
        task_id = "data-quality-critical" if result["status"] == "critical" else "data-quality-warning"
        detail_lines = [
            f"状态：{result['status']}",
            f"SQLite VM 数：{result['sqlite_vm_count']}",
            f"Prometheus VM series 数：{result['prometheus_vm_series_count']}",
            f"启用集群数：{result['sqlite_cluster_count']}",
            f"Prometheus 集群 series 数：{result['prometheus_cluster_series_count']}",
            f"最近采集状态：{result.get('latest_collection_status') or 'unknown'}",
            f"最近成功采集时间：{result.get('latest_success_at') or '无'}",
            f"最新 Prometheus 样本时间：{result.get('latest_prometheus_sample_at') or '无'}",
            f"不完整集群：{len(result.get('incomplete_clusters') or [])}",
            f"缺采日期：{', '.join(result.get('missing_collection_dates') or []) or '无'}",
            *result.get("messages", []),
        ]
        self.tasks.create_task(
            task_id,
            TaskType.COLLECTION,
            title,
            status=TaskStatus.FAILED,
            progress=100,
            message="\n".join(detail_lines),
            logs=detail_lines,
        )
        return result

    def _result(
        self,
        *,
        status: str,
        requested_window: dict[str, Any],
        actual_window: dict[str, Any],
        sample_sufficient: bool,
        clusters: list[dict[str, Any]],
        sqlite_vm_count: int,
        prometheus_vm_count: int,
        prometheus_cluster_count: int,
        latest_collection: dict[str, Any],
        latest_prometheus_sample_at: str | None,
        missing_dates: list[str],
        incomplete_clusters: list[dict[str, Any]],
        messages: list[str],
        prometheus_error: str | None = None,
        vm_count_difference: int | None = None,
        vm_count_difference_ratio: float | None = None,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "actual_data_window": actual_window,
            "requested_window": requested_window,
            "sample_sufficient": sample_sufficient,
            "missing_collection_dates": missing_dates,
            "incomplete_clusters": incomplete_clusters,
            "sqlite_vm_count": int(sqlite_vm_count),
            "prometheus_vm_series_count": int(prometheus_vm_count),
            "sqlite_cluster_count": len(clusters),
            "prometheus_cluster_series_count": int(prometheus_cluster_count),
            "vm_count_difference": int(vm_count_difference if vm_count_difference is not None else abs(sqlite_vm_count - prometheus_vm_count)),
            "vm_count_difference_ratio": float(vm_count_difference_ratio if vm_count_difference_ratio is not None else 0.0),
            "latest_collection_status": latest_collection.get("status"),
            "latest_success_at": self._latest_success_at(),
            "latest_prometheus_sample_at": latest_prometheus_sample_at,
            "prometheus_error": prometheus_error,
            "messages": messages,
        }

    def _enabled_clusters(self, *, tower_id: int | None, cluster_id: str | None) -> list[dict[str, Any]]:
        filters = ["t.enabled = 1", "c.enabled = 1"]
        params: list[Any] = []
        if tower_id is not None:
            filters.append("t.id = ?")
            params.append(tower_id)
        if cluster_id:
            filters.append("c.cluster_id = ?")
            params.append(cluster_id)
        with self.database.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT t.id AS tower_id, t.name AS tower, c.cluster_id, c.name AS cluster
                FROM clusters c
                JOIN towers t ON t.id = c.tower_id
                WHERE {' AND '.join(filters)}
                ORDER BY t.name, c.name, c.cluster_id
                """,
                params,
            ).fetchall()
        return [
            {"tower_id": int(row["tower_id"]), "tower": str(row["tower"]), "cluster_id": str(row["cluster_id"]), "cluster": str(row["cluster"])}
            for row in rows
        ]

    def _sqlite_vm_count(self, clusters: list[dict[str, Any]]) -> int:
        if not clusters:
            return 0
        clauses = []
        params: list[Any] = []
        for cluster in clusters:
            clauses.append("(tower_id = ? AND cluster_id = ?)")
            params.extend([cluster["tower_id"], cluster["cluster_id"]])
        with self.database.connection() as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM vm_latest WHERE {' OR '.join(clauses)}", params).fetchone()[0] or 0)

    def _latest_collection(self) -> dict[str, Any]:
        with self.database.connection() as conn:
            row = conn.execute("SELECT * FROM collection_runs ORDER BY COALESCE(finished_at, started_at) DESC, id DESC LIMIT 1").fetchone()
        if row is None:
            return {}
        return dict(row)

    def _latest_success_at(self) -> str | None:
        with self.database.connection() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(finished_at, started_at) AS event_at
                FROM collection_runs
                WHERE status = 'success' OR COALESCE(success_targets_json, '[]') != '[]'
                ORDER BY COALESCE(finished_at, started_at) DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        return str(row["event_at"]) if row and row["event_at"] else None

    def _missing_collection_dates(self, *, period_days: int, cluster_keys: set[tuple[int, str]]) -> tuple[list[str], set[tuple[int, str]]]:
        start_ts = self.now_ts - period_days * SECONDS_PER_DAY
        dates: list[str] = []
        failed_keys: set[tuple[int, str]] = set()
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT status, started_at, finished_at, failed_targets_json
                FROM collection_runs
                ORDER BY COALESCE(finished_at, started_at)
                """
            ).fetchall()
        for row in rows:
            event_at = str(row["finished_at"] or row["started_at"] or "")
            event_ts = _parse_ts(event_at)
            failed_targets = _loads(row["failed_targets_json"], [])
            row_failed_keys: set[tuple[int, str]] = set()
            for target in failed_targets if isinstance(failed_targets, list) else []:
                try:
                    key = (int(target.get("tower_id")), str(target.get("cluster_id")))
                except (AttributeError, TypeError, ValueError):
                    continue
                if key in cluster_keys:
                    row_failed_keys.add(key)
            if row["status"] == "failed" and not row_failed_keys and not failed_targets:
                row_failed_keys = set(cluster_keys)
            if row_failed_keys:
                if event_ts is not None and start_ts <= event_ts <= self.now_ts:
                    date_label = _date_label(event_ts, self.settings.timezone)
                    if date_label not in dates:
                        dates.append(date_label)
                failed_keys.update(row_failed_keys)
        return dates, failed_keys

    def _actual_data_window(self, *, period_days: int, range_rows: list[dict[str, Any]]) -> dict[str, Any]:
        start_ts = self.now_ts - period_days * SECONDS_PER_DAY
        timestamps: list[int] = [ts for ts in _range_timestamps(range_rows) if start_ts <= ts <= self.now_ts]
        if timestamps:
            start = min(timestamps)
            end = max(timestamps)
            days = max(1, math.floor((end - start) / SECONDS_PER_DAY) + 1)
            return {"start_at": datetime.fromtimestamp(start, tz=timezone.utc).isoformat(), "end_at": datetime.fromtimestamp(end, tz=timezone.utc).isoformat(), "days": days}
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT status, started_at, finished_at, success_targets_json
                FROM collection_runs
                ORDER BY COALESCE(finished_at, started_at)
                """
            ).fetchall()
        for row in rows:
            if row["status"] != "success" and not _loads(row["success_targets_json"], []):
                continue
            event_ts = _parse_ts(str(row["finished_at"] or row["started_at"] or ""))
            if event_ts is not None and start_ts <= event_ts <= self.now_ts:
                timestamps.append(event_ts)
        if not timestamps:
            return {}
        start = min(timestamps)
        end = max(timestamps)
        days = max(1, math.floor((end - start) / SECONDS_PER_DAY) + 1)
        return {"start_at": datetime.fromtimestamp(start, tz=timezone.utc).isoformat(), "end_at": datetime.fromtimestamp(end, tz=timezone.utc).isoformat(), "days": days}


def _normalize_period_days(period_days: int | None) -> int:
    try:
        value = int(period_days or 30)
    except (TypeError, ValueError):
        return 30
    return value if value in {7, 14, 30, 90, 180, 365} else 30


def _requested_window(now_ts: int, days: int) -> dict[str, Any]:
    start = now_ts - days * SECONDS_PER_DAY
    return {"days": days, "start_at": datetime.fromtimestamp(start, tz=timezone.utc).isoformat(), "end_at": datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat()}


def _cluster_key(metric: dict[str, Any]) -> tuple[int, str]:
    try:
        return int(metric.get("tower_id")), str(metric.get("cluster_id") or "")
    except (TypeError, ValueError):
        return -1, ""


def _vm_key(metric: dict[str, Any]) -> tuple[int, str, str]:
    tower_id, cluster_id = _cluster_key(metric)
    return tower_id, cluster_id, str(metric.get("vm_id") or "")


def _sample_ts(row: dict[str, Any]) -> int | None:
    value = row.get("value")
    if isinstance(value, list) and value:
        try:
            return int(float(value[0]))
        except (TypeError, ValueError):
            return None
    return None


def _range_timestamps(rows: list[dict[str, Any]]) -> list[int]:
    timestamps: list[int] = []
    for row in rows:
        values = row.get("values")
        if not isinstance(values, list):
            continue
        for point in values:
            if isinstance(point, list) and point:
                try:
                    timestamps.append(int(float(point[0])))
                except (TypeError, ValueError):
                    continue
    return timestamps


def _parse_ts(value: str) -> int | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _date_label(ts: int, timezone_name: str) -> str:
    try:
        tz = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = timezone.utc
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(tz).date().isoformat()


def _loads(raw: Any, default: Any) -> Any:
    if not raw:
        return default
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(str(raw))
    except json.JSONDecodeError:
        return default


def _max_status(current: str, candidate: str) -> str:
    rank = {"ok": 0, "warning": 1, "critical": 2}
    return candidate if rank.get(candidate, 0) > rank.get(current, 0) else current


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
