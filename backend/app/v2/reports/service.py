from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Any

from app.v2.config import V2Settings
from app.v2.database import V2Database
from app.v2.metrics.prometheus import PrometheusService
from app.v2.metrics.series import labels_match, metric_value, range_values, scoped_query


SECONDS_PER_DAY = 86_400
CLUSTER_USED_METRIC = "smartx_cluster_storage_used_bytes"
CLUSTER_TOTAL_METRIC = "smartx_cluster_storage_total_bytes"
VM_USED_METRIC = "smartx_vm_storage_used_bytes"


@dataclass
class ForecastResult:
    status: str
    slope_per_day: float
    current: float
    forecast_30d: float | None
    forecast_60d: float | None
    forecast_90d: float | None
    forecast_180d: float | None
    exhaustion_days: float | None = None
    exhaustion_date: str | None = None


class ReportService:
    def __init__(self, database: V2Database, settings: V2Settings, prometheus=None, now_ts: int | None = None) -> None:
        self.database = database
        self.settings = settings
        self.prometheus = prometheus or PrometheusService(settings.prometheus_url)
        self.now_ts = int(now_ts) if now_ts is not None else int(time.time())

    def latest_report(self, tower_id: int | None = None, cluster_id: str | None = None, period_days: int = 30, chart_days: int = 365) -> dict[str, Any]:
        window_days = _normalize_period_days(period_days)
        chart_window_days = _normalize_chart_days(chart_days)
        enabled_scope = self._enabled_cluster_scope(tower_id=tower_id, cluster_id=cluster_id)
        cluster_series = self._cluster_series(days=window_days, tower_id=tower_id, cluster_id=cluster_id, enabled_scope=enabled_scope)
        chart_series = self._cluster_series(days=chart_window_days, tower_id=tower_id, cluster_id=cluster_id, enabled_scope=enabled_scope)
        growth_series = self._cluster_series(days=7, tower_id=tower_id, cluster_id=cluster_id, enabled_scope=enabled_scope)
        capacity_by_cluster = self._cluster_totals(tower_id=tower_id, cluster_id=cluster_id, enabled_scope=enabled_scope)
        chart_points_by_cluster = _points_by_cluster(chart_series)
        clusters = []
        cluster_names = self._cluster_names()
        for key, points in _points_by_cluster(cluster_series).items():
            labels = {
                "tower_id": str(key[0]),
                "cluster_id": key[1],
                "cluster": cluster_names.get(key, key[1]),
            }
            capacity = capacity_by_cluster.get(key)
            forecast = forecast_series(points, capacity)
            clusters.append(
                {
                    "labels": labels,
                    "forecast": asdict(forecast),
                    "points": chart_points_by_cluster.get(key, points),
                    "total": capacity,
                    "warning": capacity * 0.9 if capacity else None,
                }
            )
        clusters.sort(key=lambda item: (item["labels"].get("cluster", ""), item["labels"].get("cluster_id", "")))
        latest_vms = self._latest_vm_items(tower_id=tower_id, cluster_id=cluster_id, enabled_scope=enabled_scope)
        vm_series = self._vm_series(days=max(window_days, 30), tower_id=tower_id, cluster_id=cluster_id, enabled_scope=enabled_scope)
        day_vm_series = self._vm_series(days=2, tower_id=tower_id, cluster_id=cluster_id, step="1h", enabled_scope=enabled_scope)
        latest_vms = _merge_latest_items(latest_vms, _latest_items_from_series_tail(vm_series))
        latest_label_by_vm = self._latest_vm_labels()
        day_vms = _growth_reports_from_series(latest_vms, day_vm_series, period_days=1, limit=100, latest_label_by_vm=latest_label_by_vm)
        month_vms = _growth_reports_from_series(latest_vms, vm_series, period_days=window_days, limit=100, latest_label_by_vm=latest_label_by_vm, min_sample_days=30)
        day_new_vms = _new_vm_reports_from_series(vm_series, *_period_bounds(self.now_ts, "day"), 100, latest_label_by_vm, _latest_vm_value_map(latest_vms))
        month_new_vms = _new_vm_reports_from_series(vm_series, *_period_bounds(self.now_ts, "month"), 100, latest_label_by_vm, _latest_vm_value_map(latest_vms))
        cluster_growth_rate = _cluster_growth_rate_from_points(_points_by_cluster(growth_series))
        return {
            "scope": {"tower_id": tower_id, "cluster_id": cluster_id},
            "clusters": clusters,
            "fastest_growing_vms": day_vms,
            "day_fastest_growing_vms": day_vms,
            "month_fastest_growing_vms": month_vms,
            "day_new_vms": day_new_vms,
            "month_new_vms": month_new_vms,
            "cluster_growth_rate_per_day": cluster_growth_rate,
            "cluster_growth_rate": {
                "per_day": cluster_growth_rate,
                "per_month": cluster_growth_rate * 30,
                "per_quarter": cluster_growth_rate * 90,
            },
            "window_days": window_days,
            "chart_days": chart_window_days,
            "growth_rate_window_days": 7,
            "forecast_days": 90,
            "period_window": _period_window(self.now_ts, window_days),
            "month_growth_min_sample_days": 30,
        }

    def _cluster_series(self, *, days: int, tower_id: int | None, cluster_id: str | None, enabled_scope: set[tuple[int, str]], step: str = "1d") -> list[dict[str, Any]]:
        start = self.now_ts - days * SECONDS_PER_DAY
        return [
            series
            for series in self.prometheus.range(scoped_query(CLUSTER_USED_METRIC, tower_id=tower_id, cluster_id=cluster_id), start=start, end=self.now_ts, step=step)
            if labels_match(series.get("metric", {}), tower_id=tower_id, cluster_id=cluster_id)
            and _in_enabled_scope(_cluster_key(series.get("metric", {})), enabled_scope)
        ]

    def _vm_series(self, *, days: int, tower_id: int | None, cluster_id: str | None, enabled_scope: set[tuple[int, str]], step: str = "6h") -> list[dict[str, Any]]:
        start = self.now_ts - days * SECONDS_PER_DAY
        return [
            series
            for series in self.prometheus.range(scoped_query(VM_USED_METRIC, tower_id=tower_id, cluster_id=cluster_id), start=start, end=self.now_ts, step=step)
            if labels_match(series.get("metric", {}), tower_id=tower_id, cluster_id=cluster_id)
            and _in_enabled_scope(_cluster_key(series.get("metric", {})), enabled_scope)
        ]

    def _cluster_totals(self, *, tower_id: int | None, cluster_id: str | None, enabled_scope: set[tuple[int, str]]) -> dict[tuple[int, str], float]:
        totals = {}
        for row in self.prometheus.instant(scoped_query(CLUSTER_TOTAL_METRIC, tower_id=tower_id, cluster_id=cluster_id)):
            metric = row.get("metric", {})
            key = _cluster_key(metric)
            if labels_match(metric, tower_id=tower_id, cluster_id=cluster_id) and _in_enabled_scope(key, enabled_scope):
                totals[key] = metric_value(row)
        if totals:
            return totals
        start = self.now_ts - 30 * SECONDS_PER_DAY
        for series in self.prometheus.range(scoped_query(CLUSTER_TOTAL_METRIC, tower_id=tower_id, cluster_id=cluster_id), start=start, end=self.now_ts, step="1d"):
            metric = series.get("metric", {})
            key = _cluster_key(metric)
            points = range_values(series)
            if labels_match(metric, tower_id=tower_id, cluster_id=cluster_id) and _in_enabled_scope(key, enabled_scope) and points:
                totals[key] = points[-1][1]
        return totals

    def _latest_vm_items(self, *, tower_id: int | None, cluster_id: str | None, enabled_scope: set[tuple[int, str]]) -> list[dict[str, Any]]:
        return [
            row
            for row in self.prometheus.instant(scoped_query(VM_USED_METRIC, tower_id=tower_id, cluster_id=cluster_id))
            if labels_match(row.get("metric", {}), tower_id=tower_id, cluster_id=cluster_id)
            and _in_enabled_scope(_cluster_key(row.get("metric", {})), enabled_scope)
        ]

    def _cluster_names(self) -> dict[tuple[int, str], str]:
        with self.database.connection() as conn:
            rows = conn.execute("SELECT tower_id, cluster_id, name FROM clusters").fetchall()
        return {(int(row["tower_id"]), str(row["cluster_id"])): str(row["name"]) for row in rows}

    def _latest_vm_labels(self) -> dict[tuple[int, str, str], dict[str, str]]:
        with self.database.connection() as conn:
            rows = conn.execute("SELECT tower_id, cluster_id, vm_id, name FROM vm_latest").fetchall()
        cluster_names = self._cluster_names()
        return {
            (int(row["tower_id"]), str(row["cluster_id"]), str(row["vm_id"])): {
                "tower_id": str(row["tower_id"]),
                "cluster_id": str(row["cluster_id"]),
                "cluster": cluster_names.get((int(row["tower_id"]), str(row["cluster_id"])), str(row["cluster_id"])),
                "vm_id": str(row["vm_id"]),
                "vm": str(row["name"]),
                "vm_name": str(row["name"]),
            }
            for row in rows
        }

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


def forecast_series(points: list[tuple[int, float]], capacity: float | None = None) -> ForecastResult:
    cleaned = _clean_points(points)
    if len(cleaned) < 2:
        current = cleaned[-1][1] if cleaned else 0.0
        return ForecastResult("insufficient_data", 0.0, current, None, None, None, None)
    filtered = _drop_outliers(cleaned)
    slope, intercept = _linear_regression(filtered)
    current_ts, current = filtered[-1]
    forecast_30 = max(0.0, intercept + slope * ((current_ts + 30 * SECONDS_PER_DAY) / SECONDS_PER_DAY))
    forecast_60 = max(0.0, intercept + slope * ((current_ts + 60 * SECONDS_PER_DAY) / SECONDS_PER_DAY))
    forecast_90 = max(0.0, intercept + slope * ((current_ts + 90 * SECONDS_PER_DAY) / SECONDS_PER_DAY))
    forecast_180 = max(0.0, intercept + slope * ((current_ts + 180 * SECONDS_PER_DAY) / SECONDS_PER_DAY))
    exhaustion_days = (capacity - current) / slope if capacity and slope > 0 and current < capacity else None
    return ForecastResult("ok", slope, current, forecast_30, forecast_60, forecast_90, forecast_180, exhaustion_days)


def _growth_reports_from_series(
    latest_items: list[dict[str, Any]],
    series_list: list[dict[str, Any]],
    *,
    period_days: int,
    limit: int,
    latest_label_by_vm: dict[tuple[int, str, str], dict[str, str]],
    min_sample_days: int | None = None,
) -> list[dict[str, Any]]:
    baseline_by_vm = {}
    for series in series_list:
        points = range_values(series)
        if not points:
            continue
        baseline_by_vm[_vm_key(series.get("metric", {}))] = points[0]
    mapped = []
    for item in latest_items:
        labels = item.get("metric", {})
        key = _vm_key(labels)
        baseline = baseline_by_vm.get(key)
        if baseline is None:
            continue
        latest_ts = _item_timestamp(item)
        if latest_ts is None:
            continue
        baseline_ts, baseline_value = baseline
        sample_span_days = (latest_ts - baseline_ts) / SECONDS_PER_DAY
        if min_sample_days is not None and sample_span_days < min_sample_days:
            continue
        current = metric_value(item)
        growth_amount = max(0.0, current - baseline_value)
        if growth_amount <= 0:
            continue
        elapsed_days = max(sample_span_days, 1)
        slope_per_day = growth_amount / elapsed_days
        mapped.append(
            {
                "labels": _labels_with_latest_name(labels, latest_label_by_vm),
                "growth_amount": growth_amount,
                "previous_value": baseline_value,
                "growth_ratio": growth_amount / baseline_value if baseline_value > 0 else None,
                "period_days": period_days,
                "sample_span_days": sample_span_days,
                "window_start_at": datetime.fromtimestamp(baseline_ts, tz=timezone.utc).isoformat(),
                "window_end_at": datetime.fromtimestamp(latest_ts, tz=timezone.utc).isoformat(),
                "forecast": asdict(ForecastResult("ok", slope_per_day, current, current + slope_per_day * 30, current + slope_per_day * 60, current + slope_per_day * 90, current + slope_per_day * 180)),
            }
        )
    return sorted(mapped, key=lambda item: (-float(item["growth_amount"]), item["labels"].get("vm", "")))[:limit]


def _new_vm_reports_from_series(
    series_list: list[dict[str, Any]],
    start_ts: int,
    end_ts: int,
    limit: int,
    latest_label_by_vm: dict[tuple[int, str, str], dict[str, str]],
    latest_value_by_vm: dict[tuple[int, str, str], float],
) -> list[dict[str, Any]]:
    mapped = []
    for series in series_list:
        points = sorted(range_values(series))
        if not points:
            continue
        key = _vm_key(series.get("metric", {}))
        first_ts, first_value = points[0]
        if first_ts < start_ts or first_ts > end_ts:
            continue
        current = latest_value_by_vm.get(key, points[-1][1])
        mapped.append(
            {
                "labels": _labels_with_latest_name(series.get("metric", {}), latest_label_by_vm),
                "first_seen_at": datetime.fromtimestamp(first_ts, tz=timezone.utc).isoformat(),
                "age_days": max((end_ts - first_ts) / SECONDS_PER_DAY, 0),
                "growth_amount": max(0.0, current - first_value),
                "previous_value": first_value,
                "growth_ratio": (current - first_value) / first_value if first_value > 0 and current > first_value else None,
                "forecast": asdict(ForecastResult("ok", 0, current, current, current, current, current)),
            }
        )
    return sorted(mapped, key=lambda item: item["first_seen_at"], reverse=True)[:limit]


def _cluster_growth_rate_from_series(series_list: list[dict[str, Any]]) -> float:
    total = 0.0
    for series in series_list:
        points = range_values(series)
        if len(points) < 2:
            continue
        elapsed_days = max((points[-1][0] - points[0][0]) / SECONDS_PER_DAY, 1)
        total += max(0.0, (points[-1][1] - points[0][1]) / elapsed_days)
    return total


def _points_by_cluster(series_list: list[dict[str, Any]]) -> dict[tuple[int, str], list[tuple[int, float]]]:
    grouped: dict[tuple[int, str], dict[int, float]] = {}
    for series in series_list:
        key = _cluster_key(series.get("metric", {}))
        if not key[1]:
            continue
        points = grouped.setdefault(key, {})
        for timestamp, value in range_values(series):
            points[int(timestamp)] = float(value)
    return {key: sorted(points.items()) for key, points in grouped.items()}


def _cluster_growth_rate_from_points(points_by_cluster: dict[tuple[int, str], list[tuple[int, float]]]) -> float:
    total = 0.0
    for points in points_by_cluster.values():
        if len(points) < 2:
            continue
        elapsed_days = max((points[-1][0] - points[0][0]) / SECONDS_PER_DAY, 1)
        total += max(0.0, (points[-1][1] - points[0][1]) / elapsed_days)
    return total


def _latest_vm_value_map(items: list[dict[str, Any]]) -> dict[tuple[int, str, str], float]:
    return {_vm_key(item.get("metric", {})): metric_value(item) for item in items}


def _latest_items_from_series_tail(series_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for series in series_list:
        points = sorted(range_values(series))
        if not points:
            continue
        latest_ts, latest_value = points[-1]
        items.append({"metric": dict(series.get("metric", {})), "value": [latest_ts, str(latest_value)]})
    return items


def _merge_latest_items(primary: list[dict[str, Any]], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[int, str, str], dict[str, Any]] = {}
    for item in fallback:
        merged[_vm_key(item.get("metric", {}))] = item
    for item in primary:
        merged[_vm_key(item.get("metric", {}))] = item
    return list(merged.values())


def _labels_with_latest_name(labels: dict[str, Any], latest_label_by_vm: dict[tuple[int, str, str], dict[str, str]]) -> dict[str, str]:
    normalized = {str(key): str(value) for key, value in labels.items()}
    latest = latest_label_by_vm.get(_vm_key(labels))
    if latest:
        normalized.update(latest)
    normalized.setdefault("vm", normalized.get("vm_name") or normalized.get("vm_id", ""))
    normalized.setdefault("vm_name", normalized.get("vm") or normalized.get("vm_id", ""))
    return normalized


def _period_bounds(now_ts: int, kind: str) -> tuple[int, int]:
    now = datetime.fromtimestamp(now_ts)
    if kind == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp()), now_ts


def _period_window(now_ts: int, days: int) -> dict[str, Any]:
    start_ts = now_ts - days * SECONDS_PER_DAY
    return {
        "days": days,
        "start_at": datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat(),
        "end_at": datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat(),
    }


def _normalize_period_days(period_days: int | None) -> int:
    try:
        value = int(period_days or 30)
    except (TypeError, ValueError):
        return 30
    return value if value in {7, 14, 30, 90, 180, 365} else 30


def _normalize_chart_days(chart_days: int | None) -> int:
    try:
        value = int(chart_days or 365)
    except (TypeError, ValueError):
        return 365
    return value if value in {7, 30, 90, 365, 720} else 365


def _cluster_key(labels: dict[str, Any]) -> tuple[int, str]:
    return (int(labels.get("tower_id") or 0), str(labels.get("cluster_id") or ""))


def _vm_key(labels: dict[str, Any]) -> tuple[int, str, str]:
    return (int(labels.get("tower_id") or 0), str(labels.get("cluster_id") or ""), str(labels.get("vm_id") or ""))


def _in_enabled_scope(key: tuple[int, str], enabled_scope: set[tuple[int, str]]) -> bool:
    return key in enabled_scope if enabled_scope else True


def _item_timestamp(item: dict[str, Any]) -> int | None:
    value = item.get("value")
    if isinstance(value, (list, tuple)) and value:
        try:
            return int(float(value[0]))
        except (TypeError, ValueError):
            return None
    return None


def _clean_points(points: list[tuple[int, float]]) -> list[tuple[int, float]]:
    dedup = {int(ts): float(value) for ts, value in points if value is not None}
    return sorted(dedup.items())


def _drop_outliers(points: list[tuple[int, float]]) -> list[tuple[int, float]]:
    if len(points) < 10:
        return points
    deltas = [abs(points[index][1] - points[index - 1][1]) for index in range(1, len(points))]
    med = median(deltas)
    if med == 0:
        return points
    filtered = [points[0]]
    for point in points[1:]:
        if abs(point[1] - filtered[-1][1]) <= med * 8:
            filtered.append(point)
    return filtered if len(filtered) >= 2 else points


def _linear_regression(points: list[tuple[int, float]]) -> tuple[float, float]:
    xs = [ts / SECONDS_PER_DAY for ts, _ in points]
    ys = [value for _, value in points]
    x_bar = sum(xs) / len(xs)
    y_bar = sum(ys) / len(ys)
    denominator = sum((value - x_bar) ** 2 for value in xs)
    if denominator == 0:
        return 0.0, y_bar
    numerator = sum((x - x_bar) * (y - y_bar) for x, y in zip(xs, ys))
    slope = numerator / denominator
    return slope, y_bar - slope * x_bar
