from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.v2.cloudtower.client import RECYCLE_BIN_VM_PREFIX
from app.v2.metrics.series import cluster_key, labels_match, range_values, scoped_query, vm_key
from app.v2.scope import in_enabled_scope

VM_USED_METRIC = "smartx_vm_storage_used_bytes"
# "新建 VM" 的首次纳管时间查询窗口（天）：取该 vm_id 在全历史内的最早样本，
# 而不是当前报表/看板查询窗口内的首个样本，避免采集断档后把老 VM 判成新建（49-42/49-43）。
VM_FIRST_SEEN_WINDOW_DAYS = 400
SECONDS_PER_DAY = 86_400

VmKey = tuple[int, str, str]
VmFirstSeen = dict[VmKey, tuple[int, float]]


def is_recycled_vm_name(name: str) -> bool:
    """回收站 VM（`in-recycle-bin-<uuid>`）不计入新建/增长统计（49-40）。"""
    return name.startswith(RECYCLE_BIN_VM_PREFIX)


def vm_display_name(labels: dict[str, Any]) -> str:
    return str(labels.get("vm") or labels.get("vm_name") or labels.get("vm_id") or "")


def period_bounds(now_ts: int, kind: str, tz_name: str | None = None) -> tuple[int, int]:
    """「新建 VM」周期窗口 `[当日/当月 0 点, now]`，按业务时区计算（49-44）。

    概览与报表共用：此前报表用进程本地时区、概览用 `settings.timezone`，
    生产环境虽然都是 Asia/Shanghai 结果相同，但实现不同属隐患，故统一。
    """
    tz = _resolve_tz(tz_name)
    now = datetime.fromtimestamp(now_ts, tz=tz)
    if kind == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp()), now_ts


def _resolve_tz(tz_name: str | None):
    if not tz_name:
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tz_name)
    except Exception:
        return timezone.utc


def collect_vm_first_seen(
    prometheus: Any,
    *,
    now_ts: int,
    tower_id: int | None = None,
    cluster_id: str | None = None,
    enabled_scope: set[tuple[int, str]],
) -> VmFirstSeen:
    """每个 VM（按 vm_id 聚合）在全历史窗口内的最早样本：近似「平台首次纳管该 VM」。

    概览（DashboardService）与报表（ReportService）的「新建 VM」共用本口径（49-43）：
    - 全历史（400 天）而不是当前查询窗口内的首个样本——采集断档后恢复采集时，
      窗口内每个 VM 的首个样本都会落在恢复当天，会把老 VM 全判成新建（49-42）；
    - 按 vm_id 聚合——VM 改名/换 label 产生的新序列不会被当成新 VM。
    """
    first: VmFirstSeen = {}
    start = now_ts - VM_FIRST_SEEN_WINDOW_DAYS * SECONDS_PER_DAY
    query = scoped_query(VM_USED_METRIC, tower_id=tower_id, cluster_id=cluster_id)
    for series in prometheus.range(query, start=start, end=now_ts, step="1d"):
        metric = series.get("metric", {})
        key = vm_key(metric)
        if not key[2] or not labels_match(metric, tower_id=tower_id, cluster_id=cluster_id):
            continue
        if not in_enabled_scope(cluster_key(metric), enabled_scope):
            continue
        points = sorted(range_values(series))
        if not points:
            continue
        timestamp, value = points[0]
        previous = first.get(key)
        if previous is None or timestamp < previous[0]:
            first[key] = (int(timestamp), float(value))
    return first
