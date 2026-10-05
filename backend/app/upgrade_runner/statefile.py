"""W1：runner 状态文件（US-28 / #82 根治）。

工程规格：docs/superpowers/specs/2026-10-05-upgrade-architecture-v054-impl-spec.md §W1

## 为什么要出库

`LeaseManager` 原先把实例心跳与任务租约直接写进**业务 SQLite**（`upgrade_runner_state` /
`upgrade_task_leases`）。这让 runner 在升级执行期间每 5 秒对全平台共享的库开一次写事务，
在 WAL 下阻塞 web-api 的所有写操作——`.12` 实测 52 个 fd、约 10 分钟写锁窗口，
预检查裸 500 `database is locked`。US-28 修了连接泄漏（治标），#82 修了心跳遇锁即退出
（治标），**根因是"执行者与被升级对象共用一份可变资源"**（US-28 三类结构性根因之三）。

状态出库后：runner 写自己的 JSON 文件，web-api 读文件优先、读不到才回落 DB。
执行期 runner 对业务库的写只剩 `_project_task` 的低频兼容镜像（W2）。

## 为什么路径从 DB 路径推导、而不是硬编码

runner 与 web-api 共享同一个 `/data` bind 挂载，两者看到的 `smartx.db` 在各自命名空间里
路径可能不同（bootstrap 过渡期还会出现 bind 双视图，见 engine.py `_same_file`）。
从 `Path(database_path).parent` 推导能保证"runner 写的位置 web-api 一定看得到同一个文件"，
比约定一个魔法路径可靠——这与 US-24（同一文件两个路径视图双写）是同一类教训。

## 写协议

同目录临时文件 → 写 → `flush` + `fsync` → `os.replace` 原子替换。单写者 = runner 进程。
`os.replace` 在同一文件系统内是原子的，读者要么看到旧完整文件、要么看到新完整文件，
**不存在半截 JSON**。文件 < 64KB（规格 §W1），开销可忽略。

## 自愈

启动读取时 JSON 损坏 → 坏文件改名 `.corrupt-<ts>` 留证 → 视为无状态重建。
理由：状态文件只承载"在场判定"与租约这类**可重新推导**的信息，损坏时保留现场
比直接删掉更能事后定位；而保留一份坏文件又不至于让每次启动都失败。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 状态文件 schema 版本。字段**只允许增补**（老 reader 忽略未知键、新 reader 容忍缺字段），
#: 因此破坏性变更必须 bump 此值并在 reader 侧显式处理。
STATE_SCHEMA_VERSION = 1

STATE_FILENAME = "upgrade-runner-state.json"


def state_file_path(database_path: Path | str) -> Path:
    """状态文件路径：从业务库路径推导（容器内 `/data/upgrade-runner-state.json`）。"""
    return Path(database_path).parent / STATE_FILENAME


def _now() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: Any) -> datetime | None:
    """解析 ISO 时间串；naive 视为 UTC。统一走这里，不各处新写时区逻辑（规格 §14.1.7）。"""
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


class RunnerStateStore:
    """runner 心跳与任务租约的**事实源**（JSON 文件）。

    公共 API 刻意与 `LeaseManager` 现有调用面一致（heartbeat / upsert_lease /
    renew_lease / release_lease / save_checkpoint / read），使调用方只换存储、不改语义。
    """

    def __init__(
        self,
        database_path: Path | str,
        instance_id: str,
        runner_version: str,
        protocol_version: int,
        capabilities: Any = None,
        *,
        path: Path | None = None,
        ttl_seconds: int = 30,
    ) -> None:
        self.database_path = Path(database_path)
        self.path = Path(path) if path is not None else state_file_path(self.database_path)
        self.instance_id = instance_id
        self.runner_version = runner_version
        self.protocol_version = int(protocol_version)
        self.capabilities = sorted(str(item) for item in (capabilities or []))
        self.ttl_seconds = int(ttl_seconds)
        self._lock_path = self.path.with_suffix(".lock")
        # 单写者 = runner 进程；同一进程内的租约与心跳线程并发访问，用进程内锁串行化。
        import threading

        self._mutex = threading.RLock()

    # ── 读 ────────────────────────────────────────────────────────────────
    def read(self) -> dict[str, Any]:
        """读状态文件。缺失或损坏 → 视为无状态（调用方据此按"不在场/无租约"处理）。"""
        with self._mutex:
            return self._read_locked()

    def _read_locked(self) -> dict[str, Any]:
        if not self.path.is_file():
            return self._empty()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self._quarantine(str(exc))
            return self._empty()
        if not isinstance(payload, dict):
            self._quarantine("顶层不是对象")
            return self._empty()
        # schema 演进容错：只取认识的字段，未知键保留原样透传（便于排障），缺字段补默认。
        payload.setdefault("schema", STATE_SCHEMA_VERSION)
        payload.setdefault("instance_id", self.instance_id)
        payload.setdefault("runner_version", self.runner_version)
        payload.setdefault("protocol_version", self.protocol_version)
        payload.setdefault("capabilities", list(self.capabilities))
        payload.setdefault("started_at", _now().isoformat())
        payload.setdefault("heartbeat_at", _now().isoformat())
        payload.setdefault("updated_at", _now().isoformat())
        leases = payload.get("leases")
        payload["leases"] = leases if isinstance(leases, dict) else {}
        return payload

    def _empty(self) -> dict[str, Any]:
        now = _now().isoformat()
        return {
            "schema": STATE_SCHEMA_VERSION,
            "instance_id": self.instance_id,
            "runner_version": self.runner_version,
            "protocol_version": self.protocol_version,
            "capabilities": list(self.capabilities),
            "started_at": now,
            "heartbeat_at": now,
            "updated_at": now,
            "leases": {},
        }

    def _quarantine(self, reason: str) -> None:
        """坏文件改名留证，不删（保留现场才能事后定位），随后按无状态重建。"""
        stamp = _now().strftime("%Y%m%d%H%M%S")
        target = self.path.with_name(f"{self.path.name}.corrupt-{stamp}-{uuid.uuid4().hex[:6]}")
        try:
            self.path.replace(target)
        except OSError:
            return
        logger.warning(
            "runner 状态文件损坏（%s），已改名留证 %s；按无状态重建。", reason, target.name
        )

    # ── 写 ────────────────────────────────────────────────────────────────
    def _write_locked(self, payload: dict[str, Any]) -> None:
        """同目录临时文件 → flush+fsync → os.replace 原子替换。"""
        payload["schema"] = STATE_SCHEMA_VERSION
        payload["instance_id"] = self.instance_id
        payload["runner_version"] = self.runner_version
        payload["protocol_version"] = self.protocol_version
        payload["capabilities"] = list(self.capabilities)
        payload["updated_at"] = _now().isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=f".{self.path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            # 失败绝不能冒泡到心跳/租约调用方（心跳丢一次不该让 runner 退出，#82 教训）。
            try:
                os.unlink(temporary)
            except OSError:
                pass
            logger.exception("runner 状态文件写入失败，本轮跳过")
            raise

    def _mutate(self, mutator) -> dict[str, Any]:
        """读-改-写。`mutator` 抛异常时**不落盘**，避免半成品。"""
        with self._mutex:
            payload = self._read_locked()
            mutator(payload)
            self._write_locked(payload)
            return payload

    # ── 实例心跳 ──────────────────────────────────────────────────────────
    def heartbeat(self, *, now: datetime | None = None) -> bool:
        """刷新实例心跳。返回是否成功落盘（失败返回 False，绝不抛）。"""
        stamp = (now or _now()).isoformat()
        try:
            self._mutate(lambda payload: payload.__setitem__("heartbeat_at", stamp))
            return True
        except Exception:  # noqa: BLE001 - 心跳失败不得让 runner 退出
            logger.exception("runner 状态心跳失败（跳过本轮）")
            return False

    def update_runner_state(self, runner_version: str, *, now: datetime | None = None) -> None:
        """兼容 `LeaseManager.update_runner_state` 调用面；同时更新实例身份字段。

        版本号存在 store 实例上：`_write_locked` 每次落盘都会重写 `runner_version` 字段，
        若不更新实例属性，新版本号会被构造时的初值（`LeaseManager` 传的是 `unknown`）覆盖回去。
        """
        stamp = (now or _now()).isoformat()
        self.runner_version = runner_version

        def apply(payload: dict[str, Any]) -> None:
            payload["heartbeat_at"] = stamp

        try:
            self._mutate(apply)
        except Exception:  # noqa: BLE001
            logger.exception("runner 状态更新失败（跳过本轮）")

    # ── 任务租约 ──────────────────────────────────────────────────────────
    def upsert_lease(
        self, task_id: str, owner: str, *, revision: int = 0, now: datetime | None = None
    ) -> bool:
        """取得/续租。别人持有且未过期 → False（与 `LeaseManager.acquire` 同语义）。"""
        current = now or _now()
        expires_at = (current + timedelta(seconds=self.ttl_seconds)).isoformat()
        outcome: dict[str, bool] = {"acquired": False}

        def apply(payload: dict[str, Any]) -> None:
            leases = payload.setdefault("leases", {})
            existing = leases.get(task_id)
            if isinstance(existing, dict):
                existing_owner = str(existing.get("lease_owner") or "")
                existing_expiry = parse_timestamp(existing.get("lease_expires_at"))
                if existing_owner != owner and existing_expiry is not None and existing_expiry > current:
                    outcome["acquired"] = False
                    return
            leases[task_id] = {
                "lease_owner": owner,
                "lease_expires_at": expires_at,
                "heartbeat_at": current.isoformat(),
                "revision": int(revision),
                "checkpoint": (existing.get("checkpoint") if isinstance(existing, dict) else {}) or {},
            }
            outcome["acquired"] = True

        try:
            self._mutate(apply)
        except Exception:  # noqa: BLE001
            logger.exception("runner 租约写入失败（跳过本轮）")
            return False
        return outcome["acquired"]

    def renew_lease(self, task_id: str, *, revision: int | None = None) -> bool:
        """续租。租约不属于本实例 → False（与 `LeaseManager.heartbeat` 同语义）。"""
        current = _now()
        expires_at = (current + timedelta(seconds=self.ttl_seconds)).isoformat()
        outcome: dict[str, bool] = {"renewed": False}

        def apply(payload: dict[str, Any]) -> None:
            leases = payload.setdefault("leases", {})
            existing = leases.get(task_id)
            if not isinstance(existing, dict):
                return
            if str(existing.get("lease_owner") or "") != self.instance_id:
                return
            existing["lease_expires_at"] = expires_at
            existing["heartbeat_at"] = current.isoformat()
            if revision is not None:
                existing["revision"] = int(revision)
            outcome["renewed"] = True

        try:
            self._mutate(apply)
        except Exception:  # noqa: BLE001
            logger.exception("runner 租约续租失败（跳过本轮）")
            return False
        return outcome["renewed"]

    def release_lease(self, task_id: str) -> None:
        def apply(payload: dict[str, Any]) -> None:
            leases = payload.setdefault("leases", {})
            existing = leases.get(task_id)
            if isinstance(existing, dict) and str(existing.get("lease_owner") or "") not in {
                "",
                self.instance_id,
            }:
                # 不是本实例的租约，别人的执行权不能被自己清掉
                return
            leases.pop(task_id, None)

        try:
            self._mutate(apply)
        except Exception:  # noqa: BLE001
            logger.exception("runner 租约释放失败（忽略）")

    def lease(self, task_id: str) -> dict[str, Any] | None:
        leases = self.read().get("leases") or {}
        value = leases.get(task_id)
        return dict(value) if isinstance(value, dict) else None

    def save_checkpoint(self, task_id: str, checkpoint: dict[str, Any]) -> None:
        def apply(payload: dict[str, Any]) -> None:
            leases = payload.setdefault("leases", {})
            existing = leases.get(task_id)
            if not isinstance(existing, dict):
                existing = {
                    "lease_owner": self.instance_id,
                    "lease_expires_at": (
                        _now() + timedelta(seconds=self.ttl_seconds)
                    ).isoformat(),
                    "heartbeat_at": _now().isoformat(),
                    "revision": 0,
                }
                leases[task_id] = existing
            existing["checkpoint"] = checkpoint

        try:
            self._mutate(apply)
        except Exception:  # noqa: BLE001
            logger.exception("runner 租约 checkpoint 写入失败（忽略）")

    # ── 自换窗口的状态快照（规格 §14.1.3） ────────────────────────────────
    def snapshot_identity(self) -> dict[str, Any]:
        payload = self.read()
        return {
            "instance_id": payload.get("instance_id"),
            "runner_version": payload.get("runner_version"),
            "protocol_version": payload.get("protocol_version"),
            "heartbeat_at": payload.get("heartbeat_at"),
        }
