from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from app.upgrade_protocol.constants import RUNNER_CAPABILITIES, RUNNER_PROTOCOL_VERSION
from app.upgrade_runner.statefile import RunnerStateStore

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LeaseManager:
    """任务租约 + runner 实例心跳。

    **W1（Phase 68）**：事实源已迁到状态文件 `upgrade-runner-state.json`
    （`RunnerStateStore`），本类保留两张表的写入作为 **DB 兼容镜像**，供仍在支持矩阵内的
    v0.5.3 web-api 读取。镜像语义：**每处 try/except 只记 warning，绝不 raise、绝不重试阻塞**
    （#82 的兜底语义从"重试后再放弃"升级为"镜像失败无害"）。

    之所以留这层镜像：M4 兼容矩阵格（v0.5.3 web-api + v0.3.2 runner）要求 presence 判定正常，
    而 v0.5.3 web-api 只读 DB。收缩（停止 DB 镜像）等 v0.5.3 退出支持矩阵后再做。
    """

    def __init__(
        self,
        database_path: Path,
        owner: str,
        *,
        ttl_seconds: int = 30,
        state_store: RunnerStateStore | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.owner = owner
        self.ttl_seconds = ttl_seconds
        self.state_store = state_store or RunnerStateStore(
            self.database_path,
            owner,
            "unknown",
            RUNNER_PROTOCOL_VERSION,
            RUNNER_CAPABILITIES,
            ttl_seconds=ttl_seconds,
        )
        self._initialize()

    # ── DB 兼容镜像（expand 期） ─────────────────────────────────────────
    def _mirror(self, label: str, action) -> Any:
        """执行一次 DB 镜像写。失败只记 warning——镜像失败无害，绝不影响主流程。"""
        try:
            return action()
        except Exception:  # noqa: BLE001 - 镜像写失败不得让 runner 退出或阻塞升级
            logger.warning("runner DB 心跳镜像失败（%s），已忽略；状态文件为事实源", label)
            return None

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """US-28 治本：每次用完**显式关闭**连接。

        此前 `_connect()` 返回裸连接，调用方写 `with self._connect() as conn`——而
        `with sqlite3.Connection` 只在退出时提交/回滚事务，**不会关闭连接**。心跳每 5 秒
        调一次，长驻进程会持续堆积未关闭连接与未提交写事务，在 WAL 下阻塞 web-api 的写操作
        （`.12` 实测 52 个 fd、约 10 分钟写锁窗口，升级预检查裸 500 `database is locked`）。
        改为真正的上下文管理器，保证异常路径也关闭。
        """
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()
    def _initialize(self) -> None:
        """建两张**镜像**表 + 首次落状态文件。

        建表失败不再阻断 runner 启动：W1 之后状态文件才是事实源，两张表只为 v0.5.3 web-api
        兜底读。为一张兼容镜像表启动失败会让整个升级执行器起不来，代价与收益完全不成比例。
        """
        self._mirror("建镜像表", self._create_mirror_tables)
        try:
            self.state_store.heartbeat()
        except Exception:  # noqa: BLE001 - 状态文件首次落盘失败不阻断（read 时会自愈）
            logger.exception("runner 状态文件首次写入失败（后续心跳会重试）")

    def _create_mirror_tables(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS upgrade_runner_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    instance_id TEXT NOT NULL,
                    runner_version TEXT NOT NULL,
                    protocol_version INTEGER NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS upgrade_task_leases (
                    task_id TEXT PRIMARY KEY,
                    lease_owner TEXT NOT NULL,
                    lease_expires_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0
                );
                """
            )

    def acquire(self, task_id: str, *, revision: int, now: datetime | None = None) -> bool:
        """取得任务租约。事实源 = 状态文件；DB 镜像写失败不影响返回值。"""
        acquired = self.state_store.upsert_lease(
            task_id, self.owner, revision=revision, now=now
        )
        self._mirror("acquire", lambda: self._mirror_acquire(task_id, revision, now))
        return acquired

    def _mirror_acquire(self, task_id: str, revision: int, now: datetime | None) -> None:
        current_time = now or _now()
        expires_at = current_time + timedelta(seconds=self.ttl_seconds)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO upgrade_task_leases (task_id, lease_owner, lease_expires_at, heartbeat_at, revision)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    lease_owner = excluded.lease_owner,
                    lease_expires_at = excluded.lease_expires_at,
                    heartbeat_at = excluded.heartbeat_at,
                    revision = excluded.revision
                """,
                (task_id, self.owner, expires_at.isoformat(), current_time.isoformat(), revision),
            )

    def heartbeat(self, task_id: str, *, revision: int, now: datetime | None = None) -> bool:
        """续租。事实源 = 状态文件；返回值只看状态文件结果，不受镜像失败影响。"""
        renewed = self.state_store.renew_lease(task_id, revision=revision)
        self._mirror("heartbeat", lambda: self._mirror_renew(task_id, revision, now))
        return renewed

    def _mirror_renew(self, task_id: str, revision: int, now: datetime | None) -> None:
        current_time = now or _now()
        expires_at = current_time + timedelta(seconds=self.ttl_seconds)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE upgrade_task_leases
                SET lease_expires_at = ?, heartbeat_at = ?, revision = ?
                WHERE task_id = ? AND lease_owner = ?
                """,
                (expires_at.isoformat(), current_time.isoformat(), revision, task_id, self.owner),
            )

    def release(self, task_id: str) -> None:
        self.state_store.release_lease(task_id)
        self._mirror("release", lambda: self._mirror_release(task_id))

    def _mirror_release(self, task_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM upgrade_task_leases WHERE task_id = ? AND lease_owner = ?",
                (task_id, self.owner),
            )

    def get(self, task_id: str) -> dict[str, Any] | None:
        """读租约。优先状态文件（事实源），回落 DB 镜像（兼容读）。"""
        lease = self.state_store.lease(task_id)
        if lease is not None:
            lease.setdefault("task_id", task_id)
            return lease
        row = self._mirror("get", lambda: self._mirror_get(task_id))
        return dict(row) if row else None

    def _mirror_get(self, task_id: str) -> Any:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM upgrade_task_leases WHERE task_id = ?", (task_id,)
            ).fetchone()

    def save_checkpoint(self, task_id: str, checkpoint: dict[str, Any]) -> None:
        """把执行检查点记进租约（回滚锚点等依赖它，规格 §W5）。"""
        self.state_store.save_checkpoint(task_id, checkpoint)

    def save_rollback_anchor(self, task_id: str, anchor: dict[str, Any]) -> None:
        """回滚锚点写进状态文件的**持久段**（任务结束后仍可读，A5）。"""
        self.state_store.save_rollback_anchor(task_id, anchor)

    def rollback_anchor(self, task_id: str) -> dict[str, Any] | None:
        return self.state_store.rollback_anchor(task_id)

    def update_runner_state(self, runner_version: str, *, now: datetime | None = None) -> None:
        """更新实例身份与心跳。事实源 = 状态文件；DB 镜像失败只记 warning。"""
        self.state_store.update_runner_state(runner_version, now=now)
        self._mirror("update_runner_state", lambda: self._mirror_write_state(runner_version, now))

    def _mirror_write_state(self, runner_version: str, now: datetime | None) -> None:
        # 方法名带 write_ 前缀：读路径另有 `_mirror_read_state`。
        # 两者曾共用 `_mirror_runner_state` 一个名字，后者被覆盖，写路径调用时
        # 变成「传两个参数给零参函数」→ TypeError → 镜像静默失效（US-26 同类：
        # 修好了但从未真正生效）。
        heartbeat_at = (now or _now()).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO upgrade_runner_state (
                    id, instance_id, runner_version, protocol_version, capabilities_json, heartbeat_at, updated_at
                )
                VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    instance_id = excluded.instance_id,
                    runner_version = excluded.runner_version,
                    protocol_version = excluded.protocol_version,
                    capabilities_json = excluded.capabilities_json,
                    heartbeat_at = excluded.heartbeat_at,
                    updated_at = excluded.updated_at
                """,
                (
                    self.owner,
                    runner_version,
                    RUNNER_PROTOCOL_VERSION,
                    json.dumps(sorted(RUNNER_CAPABILITIES)),
                    heartbeat_at,
                    heartbeat_at,
                ),
            )

    def runner_state(self) -> dict[str, Any] | None:
        """读实例状态。优先状态文件（事实源），回落 DB 镜像（兼容读）。"""
        payload = self.state_store.read()
        if payload.get("heartbeat_at"):
            return payload
        row = self._mirror("runner_state", self._mirror_read_state)
        if not row:
            return None
        state = dict(row)
        state["capabilities"] = json.loads(state.pop("capabilities_json"))
        return state

    def _mirror_read_state(self) -> Any:
        with self._connect() as connection:
            return connection.execute("SELECT * FROM upgrade_runner_state WHERE id = 1").fetchone()
