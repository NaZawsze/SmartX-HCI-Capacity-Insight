from __future__ import annotations

import time
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Any

from app.v2.config import V2Settings
from app.v2.data_quality.service import DataQualityService
from app.v2.freshness import parse_db_time
from app.v2.scope import in_enabled_scope
from app.v2.database import V2Database
from app.v2.metrics.prometheus import PrometheusService
from app.v2.metrics.series import cluster_key, labels_match, metric_value, range_values, scoped_query, vm_key
from app.v2.vms.growth import (
    DAY_GROWTH,
    MONTH_GROWTH,
    compute_growth_vms,
    labels_with_latest_name,
    latest_vm_items,
    merge_latest_items,
    points_by_vm,
    series_tail_items,
)
from app.v2.vms.new_vm import collect_vm_first_seen, is_recycled_vm_name, period_bounds, vm_display_name


SECONDS_PER_DAY = 86_400
CLUSTER_USED_METRIC = "smartx_cluster_storage_used_bytes"
CLUSTER_TOTAL_METRIC = "smartx_cluster_storage_total_bytes"
VM_USED_METRIC = "smartx_vm_storage_used_bytes"
# 增长窗口内成功采集的最小覆盖比例（相对窗口长度）：需覆盖两端，避免跨期跳变被当成增长。
GROWTH_WINDOW_COVERAGE_RATIO = 0.5


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
    smoothed_slope_per_day: float | None = None
    exhaustion_days_30d: float | None = None
    recent_day_delta: float | None = None
    spike_detected: bool = False
    # 预测区间半宽线性近似：hw(t) ≈ band_half_width_now + t × band_half_width_per_day
    # None 表示样本不足无法估计；0 表示历史完全共线（区间宽度为零）
    band_half_width_now: float | None = None
    band_half_width_per_day: float | None = None


class _MemoPrometheus:
    """请求内 Prometheus 查询去重包装。

    latest_report 单次请求内会以相同 (query, start, end, step) 重复查询同一指标
    （如 VM 30 天序列被窗口统计/日新建/月新建三处共用）。此包装把首次结果按 key
    缓存，命中后不再打底层；其余属性透传给内部实例。返回的序列不被调用方原地
    修改，可安全共享。
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self._range_cache: dict[tuple[str, int, int, str], Any] = {}
        self._instant_cache: dict[str, Any] = {}

    def range(self, query: str, *, start: int, end: int, step: str):
        key = (query, int(start), int(end), step)
        if key not in self._range_cache:
            self._range_cache[key] = self._inner.range(query, start=start, end=end, step=step)
        return self._range_cache[key]

    def instant(self, query: str):
        if query not in self._instant_cache:
            self._instant_cache[query] = self._inner.instant(query)
        return self._instant_cache[query]

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


class ReportService:
    def __init__(self, database: V2Database, settings: V2Settings, prometheus=None, now_ts: int | None = None) -> None:
        self.database = database
        self.settings = settings
        self.prometheus = prometheus or PrometheusService(settings.prometheus_url)
        self.now_ts = int(now_ts) if now_ts is not None else int(time.time())

    def latest_report(self, tower_id: int | None = None, cluster_id: str | None = None, period_days: int = 30, chart_days: int = 365) -> dict[str, Any]:
        # ReportService 为请求级实例；包一层请求内去重，DataQualityService 通过
        # prometheus=self.prometheus 共享同一 memo。
        original_prometheus = self.prometheus
        self.prometheus = _MemoPrometheus(original_prometheus)
        try:
            return self._latest_report(tower_id=tower_id, cluster_id=cluster_id, period_days=period_days, chart_days=chart_days)
        finally:
            self.prometheus = original_prometheus

    def _latest_report(self, tower_id: int | None = None, cluster_id: str | None = None, period_days: int = 30, chart_days: int = 365) -> dict[str, Any]:
        window_days = _normalize_period_days(period_days)
        chart_window_days = _normalize_chart_days(chart_days)
        # 增长速率：窗口长度固定 日 1 / 月 30 / 季度 90 天，锚定在最后一次成功采集上
        # （窗口 = [last_success - N 天, last_success]），且窗口内成功采集要覆盖两端
        # （最早一次采集距窗口末尾 >= 窗口一半），否则：
        #   - 日：暂停期"旧值→新值"的刷新跳变会被当成单日增长（49-39）；
        #   - 月/季度：窗口内只有窗口末尾一小段采集，同样算不出该窗口的增长率。
        # 图表序列（clusters[].points）同样只取到最后一次成功采集，避免把回填/暂停期
        # 的假点画进趋势图（49-41）。
        successes = self._success_timestamps()
        last_success_ts = successes[0] if successes else None
        enabled_scope = self._enabled_cluster_scope(tower_id=tower_id, cluster_id=cluster_id)
        cluster_series = self._cluster_series(days=window_days, tower_id=tower_id, cluster_id=cluster_id, enabled_scope=enabled_scope)
        chart_series = (
            self._cluster_series(days=chart_window_days, tower_id=tower_id, cluster_id=cluster_id, enabled_scope=enabled_scope, end_ts=last_success_ts)
            if last_success_ts is not None
            else []
        )
        if last_success_ts is None:
            day_growth_series: list[dict[str, Any]] = []
            month_growth_series: list[dict[str, Any]] = []
            quarter_growth_series: list[dict[str, Any]] = []
        else:
            day_growth_series = (
                self._cluster_series(days=1, tower_id=tower_id, cluster_id=cluster_id, enabled_scope=enabled_scope, step="1h", end_ts=last_success_ts)
                if _window_success_coverage(successes, last_success_ts, 1)
                else []
            )
            month_growth_series = (
                self._cluster_series(days=30, tower_id=tower_id, cluster_id=cluster_id, enabled_scope=enabled_scope, end_ts=last_success_ts)
                if _window_success_coverage(successes, last_success_ts, 30)
                else []
            )
            quarter_growth_series = (
                self._cluster_series(days=90, tower_id=tower_id, cluster_id=cluster_id, enabled_scope=enabled_scope, end_ts=last_success_ts)
                if _window_success_coverage(successes, last_success_ts, 90)
                else []
            )
        capacity_by_cluster = self._cluster_totals(tower_id=tower_id, cluster_id=cluster_id, enabled_scope=enabled_scope)
        chart_points_by_cluster = _points_by_cluster(chart_series)
        clusters = []
        tower_names = self._tower_names()
        cluster_names = self._cluster_names()
        for key, points in _points_by_cluster(cluster_series).items():
            labels = {
                "tower_id": str(key[0]),
                "tower": tower_names.get(key[0], str(key[0])),
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
        window_vm_series = self._vm_series(days=window_days, tower_id=tower_id, cluster_id=cluster_id, enabled_scope=enabled_scope)
        # 日/月增长窗口与概览共用同一定义（49-45），保证两页结果一致
        day_vm_series = self._vm_series(days=DAY_GROWTH.days, tower_id=tower_id, cluster_id=cluster_id, step=DAY_GROWTH.step, enabled_scope=enabled_scope)
        vm_month_series = self._vm_series(days=MONTH_GROWTH.days, tower_id=tower_id, cluster_id=cluster_id, step=MONTH_GROWTH.step, enabled_scope=enabled_scope)
        latest_vms = merge_latest_items(latest_vms, series_tail_items(vm_series))
        latest_label_by_vm = self._latest_vm_labels()
        window_vms = _growth_reports_from_series(latest_vms, window_vm_series, period_days=window_days, limit=None, latest_label_by_vm=latest_label_by_vm)
        day_vms = _growth_reports_from_series(latest_vms, day_vm_series, period_days=1, limit=None, latest_label_by_vm=latest_label_by_vm)
        month_vms = _growth_reports_from_series(
            latest_vms,
            vm_month_series,
            period_days=window_days,
            limit=None,
            latest_label_by_vm=latest_label_by_vm,
            min_sample_days=0,
            max_sample_days=window_days,
        )
        vm_first_seen = collect_vm_first_seen(self.prometheus, now_ts=self.now_ts, tower_id=tower_id, cluster_id=cluster_id, enabled_scope=enabled_scope)
        day_new_vms = _new_vm_reports_from_series(vm_series, *period_bounds(self.now_ts, "day", self.settings.timezone), None, latest_label_by_vm, _latest_vm_value_map(latest_vms), first_seen_by_vm=vm_first_seen)
        month_new_vms = _new_vm_reports_from_series(vm_series, *period_bounds(self.now_ts, "month", self.settings.timezone), None, latest_label_by_vm, _latest_vm_value_map(latest_vms), first_seen_by_vm=vm_first_seen)
        cluster_growth_rate = _cluster_growth_rates(
            day=_points_by_cluster(day_growth_series),
            month=_points_by_cluster(month_growth_series),
            quarter=_points_by_cluster(quarter_growth_series),
        )
        return {
            "scope": {"tower_id": tower_id, "cluster_id": cluster_id},
            "clusters": clusters,
            "window_fastest_growing_vms": window_vms,
            "fastest_growing_vms": day_vms,
            "day_fastest_growing_vms": day_vms,
            "month_fastest_growing_vms": month_vms,
            "day_new_vms": day_new_vms,
            "month_new_vms": month_new_vms,
            "cluster_growth_rate_per_day": cluster_growth_rate["per_day"],
            "cluster_growth_rate": cluster_growth_rate,
            "window_days": window_days,
            "chart_days": chart_window_days,
            "growth_rate_window_days": 1,
            "forecast_days": 90,
            "period_window": _period_window(self.now_ts, window_days),
            "data_window": _data_window_from_series(vm_series, cluster_series),
            "data_quality": DataQualityService(self.database, self.settings, prometheus=self.prometheus, now_ts=self.now_ts).evaluate(tower_id=tower_id, cluster_id=cluster_id, period_days=window_days),
            "timezone": self.settings.timezone,
            "vm_growth_sample_bucket": {"min_days": 0, "max_days": window_days},
            "month_growth_min_sample_days": 0,
        }

    def _cluster_series(self, *, days: int, tower_id: int | None, cluster_id: str | None, enabled_scope: set[tuple[int, str]], step: str = "1d", end_ts: int | None = None) -> list[dict[str, Any]]:
        # end_ts 为 None 时窗口从"现在"回算（图表/预测用）；给定 end_ts 时窗口锚定在
        # end_ts 上（[end - days, end]，增长速率的"最后一次成功采集"口径，49-39）。
        if end_ts is None:
            end = self.now_ts
            start = self.now_ts - days * SECONDS_PER_DAY
        else:
            end = min(int(end_ts), self.now_ts)
            start = end - days * SECONDS_PER_DAY
        if end < start:
            return []
        series_list = [
            series
            for series in self.prometheus.range(scoped_query(CLUSTER_USED_METRIC, tower_id=tower_id, cluster_id=cluster_id), start=start, end=end, step=step)
            if labels_match(series.get("metric", {}), tower_id=tower_id, cluster_id=cluster_id)
            and in_enabled_scope(cluster_key(series.get("metric", {})), enabled_scope)
        ]
        if end_ts is None:
            return series_list
        # 双保险：按窗口裁剪（部分 Prometheus 实现/测试替身可能返回越界点）。
        trimmed: list[dict[str, Any]] = []
        for series in series_list:
            values = [item for item in series.get("values", []) if start <= int(item[0]) <= end]
            if values:
                trimmed.append({**series, "values": values})
        return trimmed

    def _success_timestamps(self, limit: int = 500) -> list[int]:
        """最近的成功采集时间戳（口径同看板：success/partial_failed 且有成功目标），新→旧。"""
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT finished_at FROM collection_runs
                WHERE status IN ('success', 'partial_failed') AND finished_at IS NOT NULL
                  AND COALESCE(success_targets_json, '[]') != '[]'
                ORDER BY finished_at DESC, id DESC LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        stamps: list[int] = []
        for row in rows:
            parsed = parse_db_time(str(row["finished_at"]))
            if parsed:
                stamps.append(int(parsed.timestamp()))
        return stamps

    def _vm_series(self, *, days: int, tower_id: int | None, cluster_id: str | None, enabled_scope: set[tuple[int, str]], step: str = "6h") -> list[dict[str, Any]]:
        start = self.now_ts - days * SECONDS_PER_DAY
        return [
            series
            for series in self.prometheus.range(scoped_query(VM_USED_METRIC, tower_id=tower_id, cluster_id=cluster_id), start=start, end=self.now_ts, step=step)
            if labels_match(series.get("metric", {}), tower_id=tower_id, cluster_id=cluster_id)
            and in_enabled_scope(cluster_key(series.get("metric", {})), enabled_scope)
        ]

    def _cluster_totals(self, *, tower_id: int | None, cluster_id: str | None, enabled_scope: set[tuple[int, str]]) -> dict[tuple[int, str], float]:
        totals = {}
        for row in self.prometheus.instant(scoped_query(CLUSTER_TOTAL_METRIC, tower_id=tower_id, cluster_id=cluster_id)):
            metric = row.get("metric", {})
            key = cluster_key(metric)
            if labels_match(metric, tower_id=tower_id, cluster_id=cluster_id) and in_enabled_scope(key, enabled_scope):
                totals[key] = metric_value(row)
        if totals:
            return totals
        start = self.now_ts - 30 * SECONDS_PER_DAY
        for series in self.prometheus.range(scoped_query(CLUSTER_TOTAL_METRIC, tower_id=tower_id, cluster_id=cluster_id), start=start, end=self.now_ts, step="1d"):
            metric = series.get("metric", {})
            key = cluster_key(metric)
            points = range_values(series)
            if labels_match(metric, tower_id=tower_id, cluster_id=cluster_id) and in_enabled_scope(key, enabled_scope) and points:
                totals[key] = points[-1][1]
        return totals

    def _latest_vm_items(self, *, tower_id: int | None, cluster_id: str | None, enabled_scope: set[tuple[int, str]]) -> list[dict[str, Any]]:
        return latest_vm_items(self.prometheus, tower_id=tower_id, cluster_id=cluster_id, enabled_scope=enabled_scope)

    def _cluster_names(self) -> dict[tuple[int, str], str]:
        with self.database.connection() as conn:
            rows = conn.execute("SELECT tower_id, cluster_id, name FROM clusters").fetchall()
        return {(int(row["tower_id"]), str(row["cluster_id"])): str(row["name"]) for row in rows}

    def _tower_names(self) -> dict[int, str]:
        with self.database.connection() as conn:
            rows = conn.execute("SELECT id, name FROM towers").fetchall()
        return {int(row["id"]): str(row["name"]) for row in rows}

    def _latest_vm_labels(self) -> dict[tuple[int, str, str], dict[str, str]]:
        with self.database.connection() as conn:
            rows = conn.execute("SELECT tower_id, cluster_id, vm_id, name FROM vm_latest").fetchall()
        tower_names = self._tower_names()
        cluster_names = self._cluster_names()
        return {
            (int(row["tower_id"]), str(row["cluster_id"]), str(row["vm_id"])): {
                "tower_id": str(row["tower_id"]),
                "tower": tower_names.get(int(row["tower_id"]), str(row["tower_id"])),
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


SPIKE_MULTIPLIER = 3
SPIKE_FLOOR_BYTES = 1024 ** 3


def forecast_series(points: list[tuple[int, float]], capacity: float | None = None) -> ForecastResult:
    cleaned = _clean_points(points)
    if len(cleaned) < 2:
        current = cleaned[-1][1] if cleaned else 0.0
        return ForecastResult("insufficient_data", 0.0, current, None, None, None, None)
    filtered = _drop_outliers(cleaned)
    slope, intercept = _linear_regression(filtered)
    band_now, band_per_day = _forecast_band(filtered, slope, intercept, cleaned[-1][0])
    _, current = cleaned[-1]
    raw_elapsed_days = max((cleaned[-1][0] - cleaned[0][0]) / SECONDS_PER_DAY, 1)
    raw_slope = max(0.0, (cleaned[-1][1] - cleaned[0][1]) / raw_elapsed_days)
    if slope <= 0 and raw_slope > 0:
        slope = raw_slope
    forecast_30 = max(0.0, current + slope * 30)
    forecast_60 = max(0.0, current + slope * 60)
    forecast_90 = max(0.0, current + slope * 90)
    forecast_180 = max(0.0, current + slope * 180)
    exhaustion_days = (capacity - current) / slope if capacity and slope > 0 and current < capacity else None

    # 稳健口径：近 30 天平滑趋势，避免单日大迁入把耗尽预测拉陡
    recent_30 = cleaned[-30:]
    smoothed_slope = _trend_slope_per_day(recent_30) if len(recent_30) >= 2 else None
    exhaustion_30d = (capacity - current) / smoothed_slope if capacity and smoothed_slope and smoothed_slope > 0 and current < capacity else None
    recent_day_delta = cleaned[-1][1] - cleaned[-2][1] if len(cleaned) >= 2 else None
    baseline = max(smoothed_slope or 0.0, 0.0)
    spike = bool(
        recent_day_delta is not None
        and recent_day_delta > 0
        and recent_day_delta > SPIKE_MULTIPLIER * max(baseline, SPIKE_FLOOR_BYTES)
    )
    return ForecastResult(
        "ok",
        slope,
        current,
        forecast_30,
        forecast_60,
        forecast_90,
        forecast_180,
        exhaustion_days,
        smoothed_slope_per_day=smoothed_slope,
        exhaustion_days_30d=exhaustion_30d,
        recent_day_delta=recent_day_delta,
        spike_detected=spike,
        band_half_width_now=band_now,
        band_half_width_per_day=band_per_day,
    )


# t(0.975, df) 单侧 95% 分位数；df>=30 近似 1.96。避免为此引入 scipy 依赖。
_T_CRITICAL_975 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
    9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074,
    23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045,
}


def _forecast_band(points: list[tuple[int, float]], slope: float, intercept: float, last_ts: int) -> tuple[float | None, float | None]:
    """OLS 预测区间的线性近似参数（半宽，字节）。

    hw(t) = z·s·sqrt(1 + 1/n + ((x_now + t − x̄)² / Sxx))，x 单位为天。
    对外暴露 hw(0) 与每增量一天的近似增长率 z·s/sqrt(Sxx)；该线性近似对
    远期 hw 略偏宽（保守方向）。样本 <3 或 Sxx=0 时无法估计，返回 None。
    """
    n = len(points)
    if n < 3:
        return None, None
    xs = [ts / SECONDS_PER_DAY for ts, _ in points]
    x_bar = sum(xs) / n
    sxx = sum((x - x_bar) ** 2 for x in xs)
    if sxx <= 0:
        return None, None
    residuals = [value - (intercept + slope * x) for x, (_, value) in zip(xs, points)]
    residual_std = math.sqrt(sum(residual ** 2 for residual in residuals) / (n - 2))
    z = _T_CRITICAL_975.get(n - 2, 1.96)
    x_now = last_ts / SECONDS_PER_DAY
    half_width_now = z * residual_std * math.sqrt(1 + 1 / n + (x_now - x_bar) ** 2 / sxx)
    half_width_per_day = z * residual_std / math.sqrt(sxx)
    return half_width_now, half_width_per_day


def _growth_reports_from_series(
    latest_items: list[dict[str, Any]],
    series_list: list[dict[str, Any]],
    *,
    period_days: int,
    limit: int | None,
    latest_label_by_vm: dict[tuple[int, str, str], dict[str, str]],
    min_sample_days: int | None = None,
    max_sample_days: int | None = None,
) -> list[dict[str, Any]]:
    """报表增长列表 = 共享口径 `compute_growth_vms`（49-45）+ 报表侧字段（forecast/period_days 等）。

    min/max_sample_days 是报表侧的样本跨度过滤（月列表按所选周期截断），概览无此参数。
    """
    records = compute_growth_vms(series_list=series_list, latest_items=latest_items, latest_label_by_vm=latest_label_by_vm)
    mapped = []
    for record in records:
        sample_span_days = float(record["sample_span_days"])
        if min_sample_days is not None and sample_span_days < min_sample_days:
            continue
        if max_sample_days is not None and sample_span_days > max_sample_days:
            continue
        current = float(record["current_bytes"])
        slope_per_day = float(record["slope_per_day"])
        labels_latest = dict(record["metric"])
        mapped.append(
            {
                "vm_id": record["vm_id"],
                "vm_name": record["vm_name"],
                "labels": labels_latest,
                "metric": dict(labels_latest),
                "value": record["value"],
                "growth_amount": record["growth_amount"],
                "previous_value": record["previous_value"],
                "growth_ratio": record["growth_ratio"],
                "period_days": period_days,
                "sample_span_days": sample_span_days,
                "window_start_at": datetime.fromtimestamp(int(record["window_start_at"]), tz=timezone.utc).isoformat(),
                "window_end_at": datetime.fromtimestamp(int(record["window_end_at"]), tz=timezone.utc).isoformat(),
                "forecast": asdict(ForecastResult("ok", slope_per_day, current, current + slope_per_day * 30, current + slope_per_day * 60, current + slope_per_day * 90, current + slope_per_day * 180)),
            }
        )
    return mapped[:limit] if limit is not None else mapped


def _new_vm_reports_from_series(
    series_list: list[dict[str, Any]],
    start_ts: int,
    end_ts: int,
    limit: int | None,
    latest_label_by_vm: dict[tuple[int, str, str], dict[str, str]],
    latest_value_by_vm: dict[tuple[int, str, str], float],
    first_seen_by_vm: dict[tuple[int, str, str], tuple[int, float]] | None = None,
) -> list[dict[str, Any]]:
    mapped = []
    latest_labels_by_key = {vm_key(series.get("metric", {})): series.get("metric", {}) for series in series_list}
    for key, points in points_by_vm(series_list).items():
        if not points:
            continue
        first_ts, first_value = points[0]
        if first_seen_by_vm is not None:
            seen = first_seen_by_vm.get(key)
            if seen is None:
                continue
            first_ts, first_value = seen
        if first_ts < start_ts or first_ts > end_ts:
            continue
        current = latest_value_by_vm.get(key, points[-1][1])
        labels_latest = labels_with_latest_name(latest_labels_by_key.get(key, {}), latest_label_by_vm)
        if is_recycled_vm_name(vm_display_name(labels_latest)):
            continue
        mapped.append(
            {
                "vm_id": str(labels_latest.get("vm_id") or ""),
                "vm_name": str(labels_latest.get("vm") or labels_latest.get("vm_name") or ""),
                "labels": labels_latest,
                "metric": {key: str(value) for key, value in labels_latest.items()},
                "value": current,
                "first_seen_at": datetime.fromtimestamp(first_ts, tz=timezone.utc).isoformat(),
                "age_days": max((end_ts - first_ts) / SECONDS_PER_DAY, 0),
                "growth_amount": max(0.0, current - first_value),
                "previous_value": first_value,
                "growth_ratio": (current - first_value) / first_value if first_value > 0 and current > first_value else None,
                "forecast": asdict(ForecastResult("ok", 0, current, current, current, current, current)),
            }
        )
    sorted_items = sorted(mapped, key=lambda item: item["first_seen_at"], reverse=True)
    return sorted_items[:limit] if limit is not None else sorted_items



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
        key = cluster_key(series.get("metric", {}))
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


def _cluster_growth_rates(
    *,
    day: dict[tuple[int, str], list[tuple[int, float]]],
    month: dict[tuple[int, str], list[tuple[int, float]]],
    quarter: dict[tuple[int, str], list[tuple[int, float]]],
) -> dict[str, Any]:
    day_value, day_sufficient = _summed_window_rate(day, multiplier=1, use_trend=False)
    month_value, month_sufficient = _summed_window_rate(month, multiplier=30, use_trend=True)
    quarter_value, quarter_sufficient = _summed_window_rate(quarter, multiplier=90, use_trend=True)
    return {
        "per_day": day_value,
        "per_month": month_value,
        "per_quarter": quarter_value,
        "day_sample_sufficient": day_sufficient,
        "month_sample_sufficient": month_sufficient,
        "quarter_sample_sufficient": quarter_sufficient,
        "day_window_days": 1,
        "month_window_days": 30,
        "quarter_window_days": 90,
    }


def _window_success_coverage(successes: list[int], last_success_ts: int, days: int) -> bool:
    """窗口 [last - days, last] 内成功采集是否覆盖两端。

    要求窗口内至少有两次成功采集，且最早一次距窗口末尾至少半个窗口（默认 50%）。
    否则两次采集间隔远大于窗口（如断档三周后恢复），算出来的是跨期跳变，
    或只有窗口末尾一小段采集，都不能当作该窗口的增长率（49-39）。
    """
    window_start = last_success_ts - days * SECONDS_PER_DAY
    in_window = [ts for ts in successes if window_start <= ts <= last_success_ts]
    if len(in_window) < 2:
        return False
    return (last_success_ts - min(in_window)) >= days * SECONDS_PER_DAY * GROWTH_WINDOW_COVERAGE_RATIO


def _summed_window_rate(points_by_cluster: dict[tuple[int, str], list[tuple[int, float]]], *, multiplier: int, use_trend: bool) -> tuple[float | None, bool]:
    total = 0.0
    sufficient_count = 0
    insufficient_count = 0
    for points in points_by_cluster.values():
        if len(points) < 2:
            insufficient_count += 1
            continue
        if use_trend:
            slope = _trend_slope_per_day(points)
        else:
            elapsed_days = max((points[-1][0] - points[0][0]) / SECONDS_PER_DAY, 1)
            slope = (points[-1][1] - points[0][1]) / elapsed_days
        total += slope * multiplier
        sufficient_count += 1
    if sufficient_count == 0:
        return None, False
    return total, insufficient_count == 0


def _trend_slope_per_day(points: list[tuple[int, float]]) -> float:
    cleaned = _clean_points(points)
    if len(cleaned) < 2:
        return 0.0
    filtered = _drop_outliers(cleaned)
    slope, _ = _linear_regression(filtered)
    return slope


def _latest_vm_value_map(items: list[dict[str, Any]]) -> dict[tuple[int, str, str], float]:
    return {vm_key(item.get("metric", {})): metric_value(item) for item in items}

def _period_window(now_ts: int, days: int) -> dict[str, Any]:
    start_ts = now_ts - days * SECONDS_PER_DAY
    return {
        "days": days,
        "start_at": datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat(),
        "end_at": datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat(),
    }


def _data_window_from_series(*series_groups: list[dict[str, Any]]) -> dict[str, Any]:
    timestamps: list[int] = []
    for series_list in series_groups:
        for series in series_list:
            points = range_values(series)
            if points:
                timestamps.append(int(points[0][0]))
                timestamps.append(int(points[-1][0]))
    if not timestamps:
        return {}
    return {
        "start_at": datetime.fromtimestamp(min(timestamps), tz=timezone.utc).isoformat(),
        "end_at": datetime.fromtimestamp(max(timestamps), tz=timezone.utc).isoformat(),
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
    return value if value in {7, 30, 90, 365} else 365

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
