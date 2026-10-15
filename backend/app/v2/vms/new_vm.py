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


def parse_iso_timestamp(value: Any) -> int | None:
    """ISO-8601 时间串 → epoch 秒（支持 Tower 的 `2026-10-07T13:05:20.000Z`）。

    解析不了返回 None（调用方回落首见口径，**不猜、不填假值**）。
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def tower_created_at_map(database: Any) -> dict[VmKey, int]:
    """`vm_latest.local_created_at`（Tower 真实创建时间）→ epoch 秒（#36/#37 ①）。

    为空/不可解析的行跳过；DB 探测失败返回空字典（此时判定整体回落首见口径，行为与旧版一致）。
    """
    try:
        with database.connection() as conn:
            rows = conn.execute(
                "SELECT tower_id, cluster_id, vm_id, local_created_at FROM vm_latest"
                " WHERE COALESCE(local_created_at, '') <> ''"
            ).fetchall()
    except Exception:  # noqa: BLE001 - 探测失败不应让「新建 VM」整体报错
        return {}
    created: dict[VmKey, int] = {}
    for row in rows:
        timestamp = parse_iso_timestamp(row["local_created_at"])
        if timestamp is None:
            continue
        created[(int(row["tower_id"]), str(row["cluster_id"]), str(row["vm_id"]))] = timestamp
    return created


def merge_tower_created_at(first_seen: VmFirstSeen, created_by_vm: dict[VmKey, int]) -> VmFirstSeen:
    """把 Tower 真实创建时间并入「首见」表：**Tower 值优先**，缺失的 VM 保留首见值（#36/#37 ①）。

    只替换时间戳，保留该 VM 原 `first_value`（首见样本值）——概览/报表的「新建」列表用它算
    `previous_value`/`growth_amount`，语义不变。效果：采集断档期创建的 VM 不再被整批判成新建，
    而真正在窗口内创建的 VM 能按 Tower 真实创建日归位。
    """
    if not created_by_vm:
        return first_seen
    merged = dict(first_seen)
    for key, timestamp in created_by_vm.items():
        previous = merged.get(key)
        merged[key] = (int(timestamp), previous[1] if previous else 0.0)
    return merged
