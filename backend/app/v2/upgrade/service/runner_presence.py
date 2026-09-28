"""runner 在场判定（US-08）。

runner 有**两条**心跳通道：

| 通道 | 表 | 刷新时机 |
| --- | --- | --- |
| 实例心跳 | `upgrade_runner_state.heartbeat_at` | 任务之间，每个轮询周期（约 3s，`main.py::update_runner_state`） |
| 任务租约心跳 | `upgrade_task_leases.lease_expires_at`/`heartbeat_at` | **执行期间**，runner 的心跳线程每 5s（`main.py::_heartbeat_until_done`） |

执行期间实例心跳不再刷新（`update_runner_state` 只在 `run_pending_once` 开头调用）。`.3` 实测
（2026-09-27 真实同版本升级，task `upgrade-c921c5bc0aad72e5`）：整段执行约 75s 内实例心跳冻结在
开始时刻，而 `RUNNER_HEARTBEAT_STALE_SECONDS = 30` —— 只看实例心跳就会把"正在执行升级的 runner"
判成不在场，导致升级页组件目录显示"不满足平台要求"、并发预检查报"未检测到 upgrade-runner 心跳"。

因此这里把"存在有效任务租约"也当作 runner 在场的证据；两条通道都不成立时才算不在场。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .constants import RUNNER_HEARTBEAT_STALE_SECONDS

HEARTBEAT_SOURCE = "heartbeat"
TASK_LEASE_SOURCE = "task_lease"
# 判定"runner 在场"可接受的来源（协议/兼容性判定用同一集合，避免各处写死 "heartbeat"）
RUNNER_PRESENCE_SOURCES = frozenset({HEARTBEAT_SOURCE, TASK_LEASE_SOURCE})


def parse_heartbeat(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def instance_heartbeat_is_fresh(state: dict[str, Any], *, now: datetime | None = None) -> bool:
    heartbeat = parse_heartbeat(state.get("heartbeat_at") or state.get("updated_at"))
    if heartbeat is None:
        return False
    reference = now or datetime.now(timezone.utc)
    return reference - heartbeat <= timedelta(seconds=RUNNER_HEARTBEAT_STALE_SECONDS)


def task_lease_is_alive(database: Any, task_id: str, *, now: datetime | None = None) -> bool:
    """该任务当前是否真的被某个 runner 持有（US-25：判断"卡在 running"的逃生门是否可用）。"""
    reference = now or datetime.now(timezone.utc)
    try:
        with database.connection() as conn:
            row = conn.execute(
                "SELECT lease_expires_at, heartbeat_at FROM upgrade_task_leases WHERE task_id = ?",
                (task_id,),
            ).fetchone()
    except Exception:  # noqa: BLE001 - 判定失败按"没有活租约"处理
        return False
    if not row:
        return False
    if hasattr(row, "keys"):
        expires_raw, heartbeat_raw = row["lease_expires_at"], row["heartbeat_at"]
    else:
        expires_raw, heartbeat_raw = row[0], row[1]
    expires = parse_heartbeat(expires_raw)
    if expires is not None and expires > reference:
        return True
    heartbeat = parse_heartbeat(heartbeat_raw)
    return bool(heartbeat is not None and reference - heartbeat <= timedelta(seconds=RUNNER_HEARTBEAT_STALE_SECONDS))


def active_task_lease_is_fresh(database: Any, *, now: datetime | None = None) -> bool:
    """执行期间 runner 用心跳线程续租；任一租约仍有效即证明 runner 在场。"""
    reference = now or datetime.now(timezone.utc)
    try:
        with database.connection() as conn:
            rows = conn.execute("SELECT lease_expires_at, heartbeat_at FROM upgrade_task_leases").fetchall()
    except Exception:  # noqa: BLE001 - 判定失败按"不在场"处理，与旧行为一致
        return False
    for row in rows:
        if hasattr(row, "keys"):
            expires_raw, heartbeat_raw = row["lease_expires_at"], row["heartbeat_at"]
        else:
            expires_raw, heartbeat_raw = row[0], row[1]
        expires = parse_heartbeat(expires_raw)
        if expires is not None and expires > reference:
            return True
        heartbeat = parse_heartbeat(heartbeat_raw)
        if heartbeat is not None and reference - heartbeat <= timedelta(seconds=RUNNER_HEARTBEAT_STALE_SECONDS):
            return True
    return False


def presence_source(database: Any, state: dict[str, Any] | None, *, now: datetime | None = None) -> str | None:
    """返回 runner 在场的证据来源：`heartbeat` / `task_lease`；都不成立返回 None。"""
    if not state:
        return None
    if instance_heartbeat_is_fresh(state, now=now):
        return HEARTBEAT_SOURCE
    if active_task_lease_is_fresh(database, now=now):
        return TASK_LEASE_SOURCE
    return None
