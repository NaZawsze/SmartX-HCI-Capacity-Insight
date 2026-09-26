from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.v2.metrics.series import cluster_key, labels_match, metric_value, range_values, scoped_query, vm_key
from app.v2.scope import in_enabled_scope
from app.v2.vms.new_vm import is_recycled_vm_name, vm_display_name

VM_USED_METRIC = "smartx_vm_storage_used_bytes"
SECONDS_PER_DAY = 86_400


@dataclass(frozen=True)
class GrowthWindow:
    """增长最快 VM 的查询窗口（49-45）：概览与报表必须共用同一定义。"""

    days: int
    step: str


# 日：2 天回看 + 1 小时粒度（基线至少落在 1 天外由前端 sample_span_days >= 1 把关）
DAY_GROWTH = GrowthWindow(days=2, step="1h")
# 月：固定 30 天 + 6 小时粒度（不随报表 period_days 放大，保证与概览一致）
MONTH_GROWTH = GrowthWindow(days=30, step="6h")


def latest_vm_items(
    prometheus: Any,
    *,
    tower_id: int | None = None,
    cluster_id: str | None = None,
    enabled_scope: set[tuple[int, str]],
) -> list[dict[str, Any]]:
    """当前值来源之一：Prometheus instant 查询（过滤启用范围与回收站 VM）。"""
    items: list[dict[str, Any]] = []
    for row in prometheus.instant(scoped_query(VM_USED_METRIC, tower_id=tower_id, cluster_id=cluster_id)):
        metric = row.get("metric", {})
        if not labels_match(metric, tower_id=tower_id, cluster_id=cluster_id):
            continue
        if not in_enabled_scope(cluster_key(metric), enabled_scope):
            continue
        if is_recycled_vm_name(vm_display_name(metric)):
            continue
        items.append(row)
    return items


def series_tail_items(series_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """当前值来源之二：序列最新点兜底（instant 为空时使用），同样排除回收站 VM。"""
    items: list[dict[str, Any]] = []
    for series in series_list:
        metric = series.get("metric", {})
        if is_recycled_vm_name(vm_display_name(metric)):
            continue
        points = sorted(range_values(series))
        if not points:
            continue
        latest_ts, latest_value = points[-1]
        items.append({"metric": dict(metric), "value": [latest_ts, str(latest_value)]})
    return items


def merge_latest_items(primary: list[dict[str, Any]], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """primary（instant）优先覆盖 fallback（序列尾部），按 vm_key 去重。"""
    merged: dict[tuple[int, str, str], dict[str, Any]] = {}
    for item in fallback:
        merged[vm_key(item.get("metric", {}))] = item
    for item in primary:
        merged[vm_key(item.get("metric", {}))] = item
    return list(merged.values())


def points_by_vm(series_list: list[dict[str, Any]]) -> dict[tuple[int, str, str], list[tuple[int, float]]]:
    grouped: dict[tuple[int, str, str], dict[int, float]] = {}
    for series in series_list:
        key = vm_key(series.get("metric", {}))
        if not key[2]:
            continue
        points = grouped.setdefault(key, {})
        for timestamp, value in range_values(series):
            points[int(timestamp)] = float(value)
    return {key: sorted(points.items()) for key, points in grouped.items()}


def labels_with_latest_name(labels: dict[str, Any], latest_label_by_vm: dict[tuple[int, str, str], dict[str, str]]) -> dict[str, str]:
    normalized = {str(key): str(value) for key, value in labels.items()}
    latest = latest_label_by_vm.get(vm_key(labels))
    if latest:
        normalized.update(latest)
    normalized.setdefault("vm", normalized.get("vm_name") or normalized.get("vm_id", ""))
    normalized.setdefault("vm_name", normalized.get("vm") or normalized.get("vm_id", ""))
    return normalized


def item_timestamp(item: dict[str, Any]) -> int | None:
    value = item.get("value")
    if isinstance(value, (list, tuple)) and value:
        try:
            return int(float(value[0]))
        except (TypeError, ValueError):
            return None
    return None


def compute_growth_vms(
    *,
    series_list: list[dict[str, Any]],
    latest_items: list[dict[str, Any]],
    latest_label_by_vm: dict[tuple[int, str, str], dict[str, str]],
) -> list[dict[str, Any]]:
    """增长最快 VM 的唯一计算口径（49-45），概览与报表共用。

    - 基线 = 窗口内最早样本；当前值 = latest_items（instant ∪ 序列尾部）；
    - growth = current - baseline，仅保留 > 0；
    - sample_span_days = (latest_ts - baseline_ts) / 86400，供前端样本跨度过滤；
    - 回收站 VM 全程排除；排序 growth 降序、次键 vm_name。
    """
    points_by_key = points_by_vm(series_list)
    mapped: list[dict[str, Any]] = []
    for item in latest_items:
        labels = item.get("metric", {})
        key = vm_key(labels)
        points = points_by_key.get(key) or []
        if not points:
            continue
        baseline_ts, baseline_value = points[0]
        latest_ts = item_timestamp(item)
        if latest_ts is None:
            continue
        labels_latest = labels_with_latest_name(labels, latest_label_by_vm)
        if is_recycled_vm_name(vm_display_name(labels_latest)):
            continue
        current = metric_value(item)
        growth_amount = max(0.0, current - baseline_value)
        if growth_amount <= 0:
            continue
        sample_span_days = (latest_ts - baseline_ts) / SECONDS_PER_DAY
        slope_per_day = growth_amount / max(sample_span_days, 1)
        mapped.append(
            {
                "vm_id": str(labels.get("vm_id") or ""),
                "vm_name": str(labels_latest.get("vm") or labels_latest.get("vm_name") or ""),
                "tower_id": key[0],
                "cluster_id": key[1],
                "metric": {str(name): str(value) for name, value in labels_latest.items()},
                "current_bytes": current,
                "value": current,
                "previous_value": baseline_value,
                "growth_amount": growth_amount,
                "growth_ratio": growth_amount / baseline_value if baseline_value > 0 else None,
                "sample_span_days": sample_span_days,
                "slope_per_day": slope_per_day,
                "window_start_at": baseline_ts,
                "window_end_at": latest_ts,
            }
        )
    return sorted(mapped, key=lambda entry: (-float(entry["growth_amount"]), entry["vm_name"]))
