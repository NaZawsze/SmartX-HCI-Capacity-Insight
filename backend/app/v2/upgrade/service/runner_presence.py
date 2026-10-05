"""runner 在场判定（US-08 + W1 状态文件优先）。

runner 有**两条**心跳通道：

| 通道 | 载体 | 刷新时机 |
| --- | --- | --- |
| 实例心跳 | 状态文件 `heartbeat_at`（v0.3.1：DB `upgrade_runner_state.heartbeat_at`） | 任务之间，每个轮询周期（约 3s） |
| 任务租约心跳 | 状态文件 `leases.<id>.lease_expires_at`/`heartbeat_at`（v0.3.1：DB `upgrade_task_leases`） | **执行期间**，心跳线程每 5s |

执行期间实例心跳不再刷新（只在 `run_pending_once` 开头调一次）。`.3` 实测
（2026-09-27 真实同版本升级，task `upgrade-c921c5bc0aad72e5`）：整段执行约 75s 内实例心跳冻结在
开始时刻，而 `RUNNER_HEARTBEAT_STALE_SECONDS = 30` —— 只看实例心跳就会把"正在执行升级的 runner"
判成不在场，导致升级页组件目录显示"不满足平台要求"、并发预检查报"未检测到 upgrade-runner 心跳"。

因此这里把"存在有效任务租约"也当作 runner 在场的证据；两条通道都不成立时才算不在场。

## W1：为什么判定顺序是「文件 → DB」（2026-10-05，Phase 68）

runner v0.3.2 起把心跳与租约写进状态文件 `upgrade-runner-state.json`，DB 只剩兼容镜像。
判定因此改为**文件优先、DB 兜底**：

| 现场组合 | 文件 | DB | 判定走哪条 | 与升级前的行为 |
| --- | --- | --- | --- | --- |
| v0.5.4 + v0.3.2 | 有（新鲜） | 镜像 | 文件 | 新机制 |
| v0.5.4 + v0.3.1（M5） | 无 | **有** | DB | **与今天完全一致** |
| v0.5.3 + v0.3.2（M4） | 有 | 镜像 | 文件 | 新机制（v0.5.3 web-api 仍只读 DB，见下） |
| v0.5.3 + v0.3.1 | 无 | 有 | DB | 与今天一致 |

M5 这一格是本函数存在的理由：v0.3.1 runner 只写 DB、不写文件，文件读不到必须**干净地**
回落到 DB，不能把「文件缺失」当成「runner 不在场」——那会让 v0.5.4 + v0.3.1 的组合
（矩阵 M5 格）直接不可用。

M4 那一格的方向是反的：v0.5.3 web-api 只认 DB。所以 runner v0.3.2 **必须继续镜像写 DB**
（`lease.py::_mirror`），否则 v0.5.3 + v0.3.2 的 presence 会误判为不在场。镜像失败只记
warning——镜像失败无害，presence 判定由 v0.5.4 web-api 的文件通道兜住。

来源名 `heartbeat` / `task_lease` 沿用不变：协议与兼容性判定共用
`RUNNER_PRESENCE_SOURCES`，改名字会连带改判定语义。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .constants import RUNNER_HEARTBEAT_STALE_SECONDS

logger = logging.getLogger(__name__)

HEARTBEAT_SOURCE = "heartbeat"
TASK_LEASE_SOURCE = "task_lease"
# 判定"runner 在场"可接受的来源（协议/兼容性判定用同一集合，避免各处写死 "heartbeat"）
RUNNER_PRESENCE_SOURCES = frozenset({HEARTBEAT_SOURCE, TASK_LEASE_SOURCE})

STATE_FILENAME = "upgrade-runner-state.json"


def state_file_path(settings: Any) -> Path:
    """状态文件路径：**从业务库路径推导**，不硬编码容器路径。

    与 runner 侧 `statefile.state_file_path` 同一条推导规则（`Path(db).parent / 文件名`）：
    两侧各算各的会漂移（US-26 的"三处 compose 三个 tag"同源），故口径写在两处但规则一致，
    并由 `test_runner_state_file_path_matches_runner` 断言两侧结果相同。
    """
    database = getattr(settings, "database_path", None) or getattr(settings, "sqlite_path", None)
    if database is None:
        data_root = getattr(settings, "data_root", None) or getattr(settings, "sqlite_dir", None)
        if data_root is None:
            raise ValueError("settings 未提供数据库路径，无法推导 runner 状态文件位置")
        return Path(str(data_root)) / STATE_FILENAME
    return Path(str(database)).parent / STATE_FILENAME


def read_state_file(settings: Any) -> dict[str, Any] | None:
    """读 runner 状态文件。缺失 / 损坏 / 不可读一律返回 None（调用方回落 DB）。

    容错是硬要求：状态文件由 runner 单写者原子替换，正常不会半截；真出现损坏时，
    web-api 侧的表现必须是「按没有文件处理」而不是抛错——否则一个坏文件会让升级中心整体 500。
    """
    try:
        path = state_file_path(settings)
    except ValueError:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("runner 状态文件不可读（%s：%s），按无文件处理", path, exc)
        return None
    if not isinstance(payload, dict):
        logger.warning("runner 状态文件顶层不是对象（%s），按无文件处理", path)
        return None
    return payload


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


def _lease_pair_is_alive(expires_raw: Any, heartbeat_raw: Any, *, now: datetime) -> bool:
    """租约是否仍然有效：未过期，或心跳仍在 30s 阈值内。

    文件与 DB 两条通道用**同一份判定**——两处各写一套阈值逻辑，迟早漂移，
    而漂移的表现是「文件说在场、DB 说不在场」，排查成本极高。
    """
    expires = parse_heartbeat(expires_raw)
    if expires is not None and expires > now:
        return True
    heartbeat = parse_heartbeat(heartbeat_raw)
    return bool(heartbeat is not None and now - heartbeat <= timedelta(seconds=RUNNER_HEARTBEAT_STALE_SECONDS))


def task_lease_is_alive(
    database: Any,
    task_id: str,
    *,
    now: datetime | None = None,
    state_file: dict[str, Any] | None = None,
) -> bool:
    """该任务当前是否真的被某个 runner 持有（US-25：判断"卡在 running"的逃生门是否可用）。

    W1：**先查状态文件**，文件里没有这条租约再查 DB 镜像。
    """
    reference = now or datetime.now(timezone.utc)
    if state_file is not None:
        leases = state_file.get("leases")
        if isinstance(leases, dict):
            lease = leases.get(task_id)
            if isinstance(lease, dict):
                return _lease_pair_is_alive(
                    lease.get("lease_expires_at"), lease.get("heartbeat_at"), now=reference
                )
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
    return _lease_pair_is_alive(expires_raw, heartbeat_raw, now=reference)


def file_task_lease_is_fresh(state_file: dict[str, Any] | None, *, now: datetime | None = None) -> bool:
    """状态文件里是否存在仍有效的任务租约（执行期在场的证据）。"""
    if not state_file:
        return False
    leases = state_file.get("leases")
    if not isinstance(leases, dict):
        return False
    reference = now or datetime.now(timezone.utc)
    for lease in leases.values():
        if not isinstance(lease, dict):
            continue
        if _lease_pair_is_alive(lease.get("lease_expires_at"), lease.get("heartbeat_at"), now=reference):
            return True
    return False


def active_task_lease_is_fresh(
    database: Any, *, now: datetime | None = None, state_file: dict[str, Any] | None = None
) -> bool:
    """执行期间 runner 用心跳线程续租；任一租约仍有效即证明 runner 在场。"""
    reference = now or datetime.now(timezone.utc)
    if file_task_lease_is_fresh(state_file, now=reference):
        return True
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
        if _lease_pair_is_alive(expires_raw, heartbeat_raw, now=reference):
            return True
    return False


def state_file_instance_state(state_file: dict[str, Any] | None) -> dict[str, Any] | None:
    """从状态文件取实例状态，形状对齐 DB 的 `upgrade_runner_state` 行。

    对齐的意义：调用方（`execution._active_runner_state` 等）不必分叉两套字段名，
    否则「文件优先」会在每个消费点各写一遍字段映射，很快漂移。
    """
    if not state_file:
        return None
    return {
        "instance_id": state_file.get("instance_id"),
        "runner_version": state_file.get("runner_version"),
        "protocol_version": state_file.get("protocol_version"),
        "capabilities": list(state_file.get("capabilities") or []),
        "heartbeat_at": state_file.get("heartbeat_at"),
        "updated_at": state_file.get("updated_at"),
        "source": STATE_FILE_SOURCE,
    }


#: 状态文件来源标记。只在**内部**用于排障与日志，不参与 RUNNER_PRESENCE_SOURCES
#: —— 来源名对外只有 heartbeat / task_lease 两个语义（改名字会改判定语义）。
STATE_FILE_SOURCE = "state_file"


def presence_source(
    database: Any,
    state: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    state_file: dict[str, Any] | None = None,
) -> str | None:
    """返回 runner 在场的证据来源：`heartbeat` / `task_lease`；都不成立返回 None。

    W1 判定顺序：**文件实例心跳 → 文件租约 → DB 实例心跳 → DB 租约**。
    前两条是 v0.3.2 通道，后两条是 v0.3.1 通道（M5 格走的就是后两条）。
    """
    file_state = state_file_instance_state(state_file)
    if file_state and instance_heartbeat_is_fresh(file_state, now=now):
        return HEARTBEAT_SOURCE
    if file_task_lease_is_fresh(state_file, now=now):
        return TASK_LEASE_SOURCE
    if not state:
        return None
    if instance_heartbeat_is_fresh(state, now=now):
        return HEARTBEAT_SOURCE
    if active_task_lease_is_fresh(database, now=now, state_file=state_file):
        return TASK_LEASE_SOURCE
    return None
