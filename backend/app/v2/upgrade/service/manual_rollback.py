"""场景 B：升级成功后用户手动「回滚到上一版本」（应用回滚，保数据）。

设计 v1 §5.2 / impl-spec §W5 场景 B。US-17 的第二个场景。

## 与 A5 自动回滚的关系

A5 已经把「失败自动回滚」改成锚点驱动的应用回滚（只指回旧 tag，数据不动）。
B8 是**同一套锚点的第二个消费者**：升级成功之后，由用户主动发起。
两者共用锚点、共用"指回旧 tag + 健康门 + 计数守卫"的语义，只差触发方式与编排方。

## 锚点从哪读（为什么不写 app/rollback-anchor.json）

impl-spec §W5 原写"web-api 在任务创建时写 `app/rollback-anchor.json`"。实测那条路会造出
**第三份锚点**：A5 已经把锚点写在 ①task.json ②状态文件持久段 `rollback_anchors`
（`e594432` 修掉了"任务结束锚点随租约消失"）。三份锚点一旦不同步，回滚会按过期值执行——
比没有锚点更危险。所以 B8 **不新建文件**，而是读状态文件持久段（事实源），
并回退扫 task.json（覆盖未升级 runner 的现场）。

## 三条判定（缺一不可）

1. **旧镜像在本地**：tag 被清理过就回滚不了（compose 会去拉，��线环境直接失败）。
2. **未执行 contract 迁移**：应用回滚的前提是旧代码能在新 schema 上跑（expand-only）。
   一旦执行过 contract（删列/改类型），保数据回滚就不成立，只能走场景 C。
3. **无进行中任务**：复用既有单飞守卫（US-23），回滚同样是升级任务。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.upgrade_protocol.constants import RUNNER_PROTOCOL_VERSION
from app.upgrade_protocol.models import ExecutionAction, ExecutionPlan
from app.v2.tasks.models import TaskStatus, TaskType

from ._compat import HTTPException
from .fs import _now
from .runner_presence import read_state_file
from .taskfile import _save_task_file, _step
from ..projection import project_if_newer

logger = logging.getLogger(__name__)

#: 只支持回滚到**紧邻上一版本**（N-1）。跨两个版本需要跨版本数据兼容，明确不支持。
ROLLBACK_STEP_DEFS = (
    ("rollback_config", "指回上一版本镜像"),
    ("rollback_apply", "重建到上一版本"),
    ("rollback_healthcheck", "检查回滚后健康状态"),
)


def latest_rollback_anchor(settings: Any) -> dict[str, Any] | None:
    """最近一次平台回滚锚点（状态文件持久段优先，task.json 兜底）。"""
    state = read_state_file(settings)
    anchors = state.get("rollback_anchors") if isinstance(state, dict) else None
    if isinstance(anchors, dict) and anchors:
        newest = max(
            anchors.items(),
            key=lambda item: str((item[1] or {}).get("captured_at") or ""),
        )
        payload = newest[1]
        if isinstance(payload, dict) and payload.get("kind") == "platform":
            return {**payload, "anchor_source": "state_file", "anchor_task_id": newest[0]}

    upgrades_dir = Path(settings.upgrades_dir)
    best: dict[str, Any] | None = None
    for task_file in sorted(upgrades_dir.glob("*/task.json")):
        try:
            task = json.loads(task_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        anchor = task.get("platform_rollback_anchor")
        if not isinstance(anchor, dict) or anchor.get("kind") != "platform":
            continue
        if best is None or str(anchor.get("captured_at") or "") > str(best.get("captured_at") or ""):
            best = {**anchor, "anchor_source": "task_file", "anchor_task_id": task_file.parent.name}
    return best


#: 迁移登记表（与 build_upgrade_package.py 的 W7.2 expand-only 门禁同一份）。
MIGRATION_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "migrations" / "registry.json"


def _contract_migration_blockers(anchor: dict[str, Any], registry_path: Path) -> list[str]:
    """锚点之后是否执行过 contract 迁移（registry 里 `contract: true` 的条目）。"""
    try:
        registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(registry, list):
        return []
    baseline = set(str(item) for item in (anchor.get("pre_upgrade") or {}).get("applied_migrations") or [])
    blockers = []
    for entry in registry:
        if not isinstance(entry, dict) or not entry.get("contract"):
            continue
        identifier = str(entry.get("id") or entry.get("version") or entry.get("name") or "")
        if not identifier or identifier in baseline:
            continue
        blockers.append(f"已执行 contract 迁移 {identifier}，旧版本可能无法在新 schema 上运行")
    return blockers


#: 平台回滚**永远不重建 upgrade-runner**（A4 第 1 层：执行者自杀）。
#: 判定与计划都跳过它——否则回滚会被"runner 镜像不在本地"这种无关原因挡住。
ROLLBACK_EXCLUDED_SERVICES = frozenset({"upgrade-runner"})


def _missing_images(anchor: dict[str, Any], executor: Any) -> list[str]:
    """锚点里的旧镜像是否还在本地。tag 被清理过就不能回滚。"""
    missing = []
    for service, facts in sorted((anchor.get("images") or {}).items()):
        if service in ROLLBACK_EXCLUDED_SERVICES:
            continue
        tag = str((facts or {}).get("tag") or "")
        if not tag:
            missing.append(f"{service}（锚点未记录旧镜像引用）")
            continue
        try:
            executor.output(["docker", "image", "inspect", tag])
        except Exception:  # noqa: BLE001 - inspect 失败即视为本地没有
            missing.append(f"{service}（{tag}）")
    return missing


def _backup_facts(anchor: dict[str, Any], backups_dir: Path) -> dict[str, Any]:
    """锚点引用的备份是否还在、SHA 是否对得上、丢失窗口有多长。"""
    raw_path = str((anchor.get("backup") or {}).get("path") or "")
    expected_sha = str((anchor.get("backup") or {}).get("sha256") or "")
    if not raw_path:
        return {"present": False, "reason": "锚点未记录升级前备份路径"}
    path = Path(raw_path)
    if not backups_dir or not path.is_file():
        return {"present": False, "path": raw_path, "reason": f"升级前备份不存在：{path.name or raw_path}"}
    actual_sha = _sha256(path)
    if expected_sha and actual_sha != expected_sha:
        return {
            "present": False,
            "path": raw_path,
            "sha256_ok": False,
            "reason": "备份 SHA256 与锚点记录不一致，拒绝用它恢复",
        }
    captured = str(anchor.get("captured_at") or "")
    return {
        "present": True,
        "path": raw_path,
        "sha256_ok": True,
        "sha256": actual_sha,
        "size_bytes": path.stat().st_size,
        "captured_at": captured,
        "data_loss_window": _data_loss_window(captured),
    }


def _data_loss_window(captured_at: str) -> str:
    """升级时刻 → 现在，采集数据丢失窗口的人话描述。"""
    from datetime import datetime, timezone

    try:
        start = datetime.fromisoformat(str(captured_at or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "无法确定（锚点缺少捕获时间）"
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - start
    hours = max(0.0, delta.total_seconds() / 3600)
    return f"{hours:.1f} 小时（自 {start.astimezone().strftime('%Y-%m-%d %H:%M')} 起）"


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ManualRollbackMixin:
    """场景 B 的产品入口：判定 + 执行（都走既有任务状态机，单飞与审计天然适用）。"""

    def rollback_availability(self) -> dict[str, Any]:
        anchor = latest_rollback_anchor(self.settings)
        blockers: list[str] = []
        previous_version = ""
        images: list[str] = []
        if not anchor:
            blockers.append("没有平台回滚锚点（需先完成一次 v0.5.4+ 平台升级）")
        else:
            previous_version = str(anchor.get("previous_version") or "")
            images = [
                str(facts.get("tag") or "")
                for service, facts in (anchor.get("images") or {}).items()
                if str(facts.get("tag") or "") and service not in ROLLBACK_EXCLUDED_SERVICES
            ]
            if not images:
                blockers.append("锚点未记录旧镜像引用，无法指回上一版本")
            missing = _missing_images(anchor, self.executor)
            if missing:
                blockers.append("旧镜像已不在本地：" + "、".join(missing))
            blockers.extend(
                _contract_migration_blockers(anchor, MIGRATION_REGISTRY_PATH)
            )
        if previous_version and previous_version == self.settings.app_version:
            blockers.append(f"当前已是 {previous_version}，没有可回滚的上一版本")
        active = self._active_upgrade_task_id()
        if active:
            blockers.append(f"升级任务 {active} 正在进行或需要恢复，请先处理")
        return {
            "available": not blockers,
            "blockers": blockers,
            "target_version": previous_version,
            "current_version": self.settings.app_version,
            "images": images,
            "anchor_source": (anchor or {}).get("anchor_source", ""),
            "anchor_task_id": (anchor or {}).get("anchor_task_id", ""),
            "captured_at": (anchor or {}).get("captured_at", ""),
            "scope": "application_only",
            "note": "仅回滚应用、不动数据；数据回到升级前请使用整备回滚",
        }

    def _active_upgrade_task_id(self) -> str:
        from .execution import _ACTIVE_UPGRADE_STATUSES

        for task_file in sorted(self.settings.upgrades_dir.glob("*/task.json")):
            try:
                task = json.loads(task_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if str(task.get("status") or "") in _ACTIVE_UPGRADE_STATUSES:
                return task_file.parent.name
        return ""

    def full_rollback_availability(self) -> dict[str, Any]:
        """场景 C：整备回滚（应用 + 数据一起回到升级前）。

        判定与场景 B 同源（同一锚点），但**多一条硬要求**：备份必须存在且 SHA 对得上——
        整备回滚会把 SQLite/Prometheus 整份换回，读错备份的代价远高于回滚失败。
        """
        anchor = latest_rollback_anchor(self.settings)
        blockers: list[str] = []
        previous_version = ""
        backup: dict[str, Any] = {}
        if not anchor:
            blockers.append("没有平台回滚锚点（需先完成一次 v0.5.4+ 平台升级）")
        else:
            previous_version = str(anchor.get("previous_version") or "")
            backup = _backup_facts(anchor, Path(self.settings.backups_dir))
            if not backup.get("present"):
                blockers.append(str(backup.get("reason") or "升级前备份不可用"))
        if previous_version and previous_version == self.settings.app_version:
            blockers.append(f"当前已是 {previous_version}，没有可回滚的上一版本")
        active = self._active_upgrade_task_id()
        if active:
            blockers.append(f"升级任务 {active} 正在进行或需要恢复，请先处理")
        return {
            "available": not blockers,
            "blockers": blockers,
            "target_version": previous_version,
            "current_version": self.settings.app_version,
            "backup": backup,
            "scope": "application_and_data",
            "data_loss_window": backup.get("data_loss_window", ""),
            "requires_confirmation": True,
            "note": "整备回滚会用升级前备份覆盖 SQLite/Prometheus，丢失升级时刻至今的采集数据",
        }

    def start_full_rollback(self, *, confirm_data_loss: bool = False) -> dict[str, Any]:
        """场景 C 执行入口。`confirm_data_loss` 必须显式为真——没有默认的"是"。"""
        availability = self.full_rollback_availability()
        if not availability["available"]:
            raise HTTPException(
                status_code=400,
                detail="当前不可整备回滚：" + "；".join(availability["blockers"]),
            )
        if not confirm_data_loss:
            # 拒绝必须带出路：告诉用户要确认什么、数据会丢多少
            raise HTTPException(
                status_code=400,
                detail=(
                    "整备回滚会丢失升级时刻至今的采集数据"
                    f"（{availability['data_loss_window'] or '窗口未知'}）。"
                    "确认请显式传 confirm_data_loss=true。"
                ),
            )
        anchor = latest_rollback_anchor(self.settings) or {}
        self._ensure_no_active_upgrade("")
        target_version = str(anchor.get("previous_version") or "")
        backup = availability["backup"]
        project_backup = None
        project_files: list[dict[str, Any]] = []
        # 项目文件备份：取最近一次完成过 files.sync 的任务（它的 checkpoint.files 里带配对信息）
        for task_file in sorted(Path(self.settings.upgrades_dir).glob("*/task.json"), reverse=True):
            try:
                other = json.loads(task_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for action in other.get("execution_plan", {}).get("actions") or []:
                if str(action.get("type") or "") != "files.sync":
                    continue
                result = action.get("result") or {}
                backup_path = result.get("backup_path")
                if not backup_path:
                    continue
                project_backup = str(backup_path)
                project_files = list((action.get("checkpoint") or {}).get("files") or [])
                break
            if project_backup:
                break
        task_id = f"manual-full-rollback-{_now().strftime('%Y%m%d%H%M%S')}"
        task_dir = Path(self.settings.upgrades_dir) / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        plan = _full_rollback_plan(
            backup_path=str(backup.get("path") or ""),
            project_backup_path=project_backup,
            project_files=project_files,
            services=sorted(
                service
                for service, facts in (anchor.get("images") or {}).items()
                if str(facts.get("tag") or "") and service not in ROLLBACK_EXCLUDED_SERVICES
            ),
        )
        task = {
            "task_id": task_id,
            "status": "pending",
            "kind": "manual_full_rollback",
            "package_type": "manual_rollback",
            "target_version": target_version,
            "components": ["platform"],
            "manifest": {
                "version": target_version,
                "package_type": "manual_rollback",
                "source_compatibility": {
                    "min_version": target_version,
                    "max_version_inclusive": self.settings.app_version,
                    "target_version": target_version,
                    "allow_same_version": False,
                    "supported_versions": [target_version, self.settings.app_version],
                },
            },
            "rollback_anchor": anchor,
            "data_loss_window": backup.get("data_loss_window", ""),
            "execution_plan": plan,
            "steps": [
                _step("rollback_stop_writers", "停止平台写入方", "pending"),
                _step("rollback_restore_backup", "恢复升级前数据与配置", "pending"),
                _step("rollback_start", "启动并检查上一版本", "pending"),
            ],
            "logs": [
                f"整备回滚：{self.settings.app_version} → {target_version}；"
                f"已确认数据丢失窗口 {backup.get('data_loss_window', '')}"
            ],
        }
        _save_task_file(task_dir, task)
        self.tasks.create_task(
            task_id,
            TaskType.UPGRADE,
            "整备回滚（数据回到升级前）",
            status=TaskStatus.PENDING,
            progress=0,
            message="整备回滚任务已提交，等待 upgrade-runner 执行",
            steps=task["steps"],
            logs=list(task["logs"]),
        )
        project_if_newer(self.tasks.database, task)
        return task

    def start_manual_rollback(self) -> dict[str, Any]:
        availability = self.rollback_availability()
        if not availability["available"]:
            raise HTTPException(
                status_code=400,
                detail="当前不可回滚：" + "；".join(availability["blockers"]),
            )
        anchor = latest_rollback_anchor(self.settings) or {}
        self._ensure_no_active_upgrade("")
        target_version = str(anchor.get("previous_version") or "")
        services = sorted(
            service
            for service, facts in (anchor.get("images") or {}).items()
            if str((facts or {}).get("tag") or "") and service not in ROLLBACK_EXCLUDED_SERVICES
        )
        task_id = f"manual-rollback-{_now().strftime('%Y%m%d%H%M%S')}"
        task_dir = self.settings.upgrades_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        plan = _manual_rollback_plan(anchor, services=services)
        task = {
            "task_id": task_id,
            "status": "pending",
            "kind": "manual_rollback",
            "package_type": "manual_rollback",
            "target_version": target_version,
            "components": ["platform"],
            "manifest": {
                "version": target_version,
                "package_type": "manual_rollback",
                "source_compatibility": {
                    "min_version": target_version,
                    "max_version_inclusive": self.settings.app_version,
                    "target_version": target_version,
                    "allow_same_version": False,
                    "supported_versions": [target_version, self.settings.app_version],
                },
            },
            "rollback_anchor": anchor,
            "execution_plan": plan,
            "steps": [_step(key, title, "pending") for key, title in ROLLBACK_STEP_DEFS],
            "logs": [f"手动应用回滚：{self.settings.app_version} → {target_version}"],
        }
        _save_task_file(task_dir, task)
        self.tasks.create_task(
            task_id,
            TaskType.UPGRADE,
            "手动回滚到上一版本",
            status=TaskStatus.PENDING,
            progress=0,
            message="手动回滚任务已提交，等待 upgrade-runner 执行",
            steps=task["steps"],
            logs=list(task["logs"]),
        )
        project_if_newer(self.tasks.database, task)
        return task


def _manual_rollback_plan(anchor: dict[str, Any], *, services: list[str]) -> dict[str, Any]:
    """回滚计划：指回旧 tag → compose.apply → 健康门。**全部是既有动作**，不新增计划词汇。"""
    images = [
        {"service": service, "image": str((facts or {}).get("tag"))}
        for service, facts in sorted((anchor.get("images") or {}).items())
        if str((facts or {}).get("tag") or "") and service not in ROLLBACK_EXCLUDED_SERVICES
    ]
    actions = [
        ExecutionAction(
            id="rollback-override",
            type="compose.override",
            params={"images": images, "services": services},
        ),
        ExecutionAction(
            id="rollback-apply",
            type="compose.apply",
            params={"services": services, "images": images},
        ),
        ExecutionAction(
            id="rollback-healthcheck",
            type="health.http",
            params={
                "url": "http://web-api:8000/api/system/health",
                "expected_status": 200,
                "attempts": 30,
                "delay_seconds": 2,
                "timeout_seconds": 15,
            },
        ),
    ]
    plan = ExecutionPlan(protocol_version=RUNNER_PROTOCOL_VERSION, required_capabilities=[], actions=actions)
    return plan.to_dict()

def _full_rollback_plan(
    *,
    backup_path: str,
    project_backup_path: str | None,
    project_files: list[dict[str, Any]],
    services: list[str],
) -> dict[str, Any]:
    """整备回滚计划：`rollback.restore`（恢复五步）→ `health.http`。

    ## 为什么复用 rollback.restore 而不是新写一份沙箱恢复脚本

    impl-spec §W5 场景 C 原写"走 script.run_sandboxed + 包内恢复脚本"。实测那条路要**再实现一遍**
    `rollback.restore` 已经做全的五步（停写方 → 恢复 SQLite/Prometheus/.env → 指回旧 tag → 起服务），
    两份恢复逻辑各自演化就会出现"手动回滚恢复得对、整备回滚恢复得不对"的难查差异。
    `rollback.restore` 已在**已发布 runner 词汇**内（不新增计划词汇），改用它更安全也更少代码。

    参数与 runner 侧 `rollback_restore` 一一对应；restore 内部的 `up -d --force-recreate`
    是**故意**的：整备回滚的目标配置可能与当前 config-hash 不同，必须重建。
    """
    actions = [
        ExecutionAction(
            id="full-restore",
            type="rollback.restore",
            params={
                "services": services,
                "backup_path": backup_path,
                "backup_scope": "bundle",
                "project_backup_path": project_backup_path,
                "project_files": project_files,
            },
        ),
        ExecutionAction(
            id="full-rollback-healthcheck",
            type="health.http",
            params={
                "url": "http://web-api:8000/api/system/health",
                "expected_status": 200,
                "attempts": 30,
                "delay_seconds": 2,
                "timeout_seconds": 15,
            },
        ),
    ]
    plan = ExecutionPlan(protocol_version=RUNNER_PROTOCOL_VERSION, required_capabilities=[], actions=actions)
    return plan.to_dict()
