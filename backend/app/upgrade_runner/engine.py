from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.upgrade_runner.actions import _runner_image_from_task, reconcile_project_runner_tag
from app.upgrade_runner.rollback import (
    anchor_rollback_override_images,
    business_count_guard,
    capture_platform_rollback_anchor,
    is_rollback_trigger,
    rollback_on_failure_enabled,
)
from app.upgrade_runner.selfhandoff import is_handoff_final
from app.upgrade_runner.store import TaskStore

logger = logging.getLogger(__name__)

ActionHandler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def _same_file(left: Path, right: Path) -> bool:
    """两个路径是否指向同一个文件（含 bind-mount 双视图：路径不同、inode 相同）。"""
    try:
        first, second = left.stat(), right.stat()
    except OSError:
        return False
    return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)
TaskUpdateCallback = Callable[[dict[str, Any]], None]
SAFE_RESUME_ACTIONS = {
    "backup.create",
    "image.load",
    "filesystem.prepare",
    "files.sync",
    "compose.override",
    "compose.project_migrate",
    "compose.apply",
    "health.http",
    "health.prometheus",
    "task.migrate_runtime_state",
    "task.sync_runtime_state",
    "post_upgrade.schedule_cleanup",
    "post_upgrade.schedule_collection",
    "post_cleanup.precheck_target_health",
    "runner.handoff_target_runtime",
    "runner.schedule_target_runtime_handoff",
    "runner.stop_legacy_runtime",
    "compose.stop_legacy_project",
    "network.remove_legacy",
    "filesystem.cleanup_legacy_paths",
    "filesystem.cleanup_target_app_residuals",
    "post_cleanup.verify",
    "legacy.cleanup",
    "checkpoint.write",
    "rollback.restore",
}


#: 平台健康门参数（与编译器生成的 health.http 动作同一口径）。
#: 回滚后自造健康动作时用它——compose.apply 的 params 里没有 url，不能拿来当健康检查参数。
PLATFORM_HEALTH_PARAMS = {
    "url": "http://web-api:8000/api/system/health",
    "expected_status": 200,
    "attempts": 30,
    "delay_seconds": 2,
    "timeout_seconds": 15,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class UpgradeEngine:
    def __init__(
        self,
        store: TaskStore,
        *,
        handlers: dict[str, ActionHandler],
        context: dict[str, Any] | None = None,
        on_update: TaskUpdateCallback | None = None,
        checkpoint_sink: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.store = store
        self.handlers = handlers
        self.context = context or {}
        self.on_update = on_update
        self.checkpoint_sink = checkpoint_sink
        self._mirror_store: TaskStore | None = None

    def _save(self, task: dict[str, Any]) -> dict[str, Any]:
        saved = self.store.save(task, expected_revision=int(task["revision"]))
        mirror_dir = str(saved.get("task_mirror_dir") or "")
        if self._mirror_store is None and mirror_dir:
            self._mirror_store = TaskStore(Path(mirror_dir))
        # US-24：mirror 与主 store 指向**同一个文件**时绝不能再写一遍。同版本重装（已经在目标布局）时
        # `task.migrate_runtime_state` 返回的 source/mirror 是同一目录的两个路径视图，双写会让同一个
        # task.json 每次保存 revision +2，而内存里的 revision 只 +1 → 下一次保存必然 RevisionConflict
        # →进程崩溃→容器重启→任务永久卡在 running（2026-09-27 `.12` 实测 attempt=17、36 条冲突）。
        if self._mirror_store is not None and not _same_file(self._mirror_store.path, self.store.path):
            self._mirror_store.save(dict(saved))
        if self.on_update is not None:
            self.on_update(saved)
        return saved

    def run(self) -> dict[str, Any]:
        task = self.store.load()
        task["status"] = "running"
        # 注意：不能用 setdefault 兜这些键——键存在且值为 None 时 setdefault 不会替换，
        # 失败任务就会带着 available_recovery_actions=None 定格，前端拿不到任何操作入口
        # （.12 实测）。这里显式判空。
        if not task.get("recovery_status"):
            task["recovery_status"] = "none"
        if task.get("available_recovery_actions") is None:
            task["available_recovery_actions"] = []
        if not task.get("logs"):
            task["logs"] = []
        task = self.store.save(task, expected_revision=int(task.get("revision") or 0))
        if self.on_update is not None:
            self.on_update(task)

        actions = task.get("execution_plan", {}).get("actions") or []
        for index, action in enumerate(actions):
            status = str(action.get("status") or "pending")
            if status in {"succeeded", "skipped"}:
                continue
            if status == "running" and not self._can_resume(action):
                action["status"] = "recovery_required"
                action["finished_at"] = _now()
                task["status"] = "recovery_required"
                task["recovery_status"] = "recovery_required"
                task["recovery_reason"] = f"动作 {action.get('id')} 的执行结果无法自动确认。"
                task["available_recovery_actions"] = ["continue", "rollback", "fail"]
                return self._save(task)

            action["status"] = "running"
            action["attempt"] = int(action.get("attempt") or 0) + 1
            action["started_at"] = _now()
            action["finished_at"] = None
            action.setdefault("checkpoint", {})
            action.setdefault("result", {})
            # W3：自换类动作在**执行前**把「即将调度 handoff」写进 task.json。
            # 必须先落盘再执行——该动作返回后本进程随时会被 docker 替换掉，
            # 新 runner 启动时读到的必须是这个标记，否则它认不出"该收尾了"。
            if str(action.get("type") or "") == "component.schedule_self_handoff":
                handoff = task.get("self_handoff")
                handoff = dict(handoff) if isinstance(handoff, dict) else {}
                handoff["scheduled"] = True
                handoff["scheduled_at"] = _now()
                task["self_handoff"] = handoff
                task["status"] = "running"
                logger.warning(
                    "自换即将调度 handoff：已把 self_handoff.scheduled 落盘，"
                    "本进程在此动作返回后立即停止"
                )
            # A5（设计 v1 §5.0）：首次 `compose.apply` **之前**捕获平台回滚锚点。
            # 顺序是硬要求——apply 之后运行容器就是新镜像，files.sync 还可能已把 project
            # compose 换掉，那时再读"上一版是什么"只会读到新版本，回滚会变成"换回新版本"。
            if str(action.get("type") or "") == "compose.apply" and not task.get("platform_rollback_anchor"):
                anchor = capture_platform_rollback_anchor(
                    self.context.get("action_context"),
                    task,
                    executor=self.context["action_context"].executor,
                    target_version=str(task.get("target_version") or ""),
                    checkpoint_sink=self.checkpoint_sink,
                )
                task["platform_rollback_anchor"] = anchor
                task["logs"] = [
                    *task.get("logs", []),
                    f"已捕获平台回滚锚点：上一版={anchor.get('previous_version') or '未知'}，"
                    f"旧镜像={json.dumps(anchor_rollback_override_images(anchor), ensure_ascii=False)}",
                ]
            task = self._save(task)
            action = task["execution_plan"]["actions"][index]
            handler = self.handlers.get(str(action.get("type")))
            if handler is None:
                message = f"Runner 不支持动作：{action.get('type')}"
                action["status"] = "failed"
                action["error"] = message
                action["finished_at"] = _now()
                task["status"] = "failed"
                task["error"] = message
                task["logs"] = [*task.get("logs", []), message]
                return self._save(task)

            def checkpoint_writer(checkpoint: dict[str, Any]) -> None:
                nonlocal task
                task["execution_plan"]["actions"][index]["checkpoint"] = checkpoint
                task = self._save(task)

            try:
                result = handler(
                    action,
                    {
                        **self.context,
                        "task": task,
                        "task_mirror_dir": task.get("task_mirror_dir"),
                        "checkpoint_writer": checkpoint_writer,
                    },
                ) or {}
            except Exception as exc:
                action = task["execution_plan"]["actions"][index]
                action["status"] = "failed"
                action["error"] = str(exc)
                action["finished_at"] = _now()
                if self._should_auto_rollback(task, action) and int(task.get("rollback_attempts") or 0) < 1:
                    return self._automatic_rollback(task, exc, action)
                task["status"] = "failed"
                task["error"] = str(exc)
                task["logs"] = [*task.get("logs", []), str(exc)]
                return self._save(task)
            # W3：动作返回「到此为止」哨兵（`runner.schedule_target_runtime_handoff`）。
            # 必须在**把动作标记 succeeded 之前**停下。往下走会依次做：标记 succeeded →
            # compose tag 对账 → 任务置 success。这三步在自换窗口内随时会被 docker 替换
            # 容器打断（SIGKILL），留下 revision 与实际状态不一致的 task.json——
            # US-24 的崩溃循环与 attempt=17 正是这么来的。
            # 收尾由新 runner 启动路径的 `_finish_runner_component_steps` 完成。
            if is_handoff_final(result):
                logger.warning(
                    "动作 %s（%s）已调度 handoff，本进程立即停止且不写状态；收尾由新 runner 完成",
                    action.get("id"),
                    action.get("type"),
                )
                return task
            action = task["execution_plan"]["actions"][index]
            action["status"] = "succeeded"
            action["result"] = result
            action["finished_at"] = _now()
            if result.get("checkpoint"):
                action["checkpoint"] = result["checkpoint"]
            mirror_dir = str(result.get("mirror_task_dir") or (result.get("checkpoint") or {}).get("mirror_task_dir") or "")
            if mirror_dir:
                task["task_mirror_dir"] = mirror_dir
                self._mirror_store = TaskStore(Path(mirror_dir))
            task = self._save(task)

        # US-32：所有动作完成、project 文件同步之后，把 compose 里的 runner tag
        # 对齐到计划声明的现场镜像。放在这里是因为再往后没有任何动作会覆盖 compose，
        # 而平台升级的 project 同步会把包内基线写进来（实测 v0.3.1）。
        try:
            action_context = self.context.get("action_context")
            previous_tag = reconcile_project_runner_tag(action_context, task)
            if previous_tag:
                task["logs"] = [
                    *task.get("logs", []),
                    f"compose runner tag 已对齐：{previous_tag} -> {_runner_image_from_task(task)}",
                ]
        except Exception as exc:  # noqa: BLE001 - 对账失败不得让升级任务判失败
            task["logs"] = [*task.get("logs", []), f"runner tag 对账跳过：{exc}"]

        task["status"] = "success"
        task["recovery_status"] = "none"
        task["available_recovery_actions"] = []
        task["finished_at"] = _now()
        return self._save(task)

    def _should_auto_rollback(self, task: dict[str, Any], failed_action: dict[str, Any]) -> bool:
        """这个失败要不要自动回滚。

        两条口径，**刻意不对称**：

        - `health.*` 失败：**无条件**回滚。这是 v0.5.3 起就有的行为，不受新开关影响——
          如果给它加上缺省 false 的开关，等于让所有老 manifest（没有该字段）**丢掉**
          已有的回滚能力，那是行为回退，不是"不受影响"。
        - `compose.apply` / `post_upgrade.*` 失败：需要 manifest 显式
          `rollback_on_failure: true` **且**锚点已捕获。新触发面是 opt-in 的，
          老 manifest 不受影响（设计 v1 §5.1 的触发条件严格化）。
        """
        kind = str(failed_action.get("type") or "")
        if kind.startswith("health."):
            return True
        if not is_rollback_trigger(kind):
            return False
        return rollback_on_failure_enabled(task) and bool(task.get("platform_rollback_anchor"))

    def _automatic_rollback(self, task: dict[str, Any], cause: Exception, failed_health_action: dict[str, Any]) -> dict[str, Any]:
        task["rollback_attempts"] = int(task.get("rollback_attempts") or 0) + 1
        task["status"] = "rollback_running"
        task["recovery_status"] = "rolling_back"
        task["logs"] = [*task.get("logs", []), f"升级步骤失败，开始自动回滚：{cause}"]
        task = self._save(task)
        anchor = task.get("platform_rollback_anchor") or {}
        if str(anchor.get("kind") or "") == "platform" and anchor.get("images"):
            # A5 主路径：场景 A「应用回滚」——只把三件套指回旧 tag，数据不动。
            # 老实现（rollback.restore）会把 SQLite 从备份整份拷回，那是场景 C
            # 「整备回滚」的语义，会吞掉升级窗口内的采集数据；expand-only 迁移纪律
            # 让"保数据回滚应用"成立，所以这里换成锚点驱动。
            return self._anchor_based_rollback(task, anchor, failed_health_action)
        project_backup_path = None
        project_files: list[dict[str, Any]] = []
        override_path = None
        backup_path = None
        backup_scope = None
        services: list[str] = []
        for completed in task.get("execution_plan", {}).get("actions") or []:
            result = completed.get("result") or {}
            if completed.get("type") == "backup.create":
                backup_path = result.get("path")
                backup_scope = result.get("scope")
            elif completed.get("type") == "files.sync":
                project_backup_path = result.get("backup_path")
                project_files = list((result.get("checkpoint") or {}).get("files") or [])
            elif completed.get("type") == "compose.override":
                override_path = result.get("path")
            elif completed.get("type") == "compose.apply":
                services = [str(item) for item in result.get("services") or []]
        rollback_action = {
            "id": "automatic-rollback",
            "type": "rollback.restore",
            "status": "running",
            "attempt": task["rollback_attempts"],
            "params": {
                "backup_path": backup_path,
                "backup_scope": backup_scope,
                "project_backup_path": project_backup_path,
                "project_files": project_files,
                "override_path": override_path,
                "services": services,
            },
            "checkpoint": {},
            "result": {},
        }
        handler = self.handlers.get("rollback.restore")
        if handler is None:
            task["status"] = "rollback_failed"
            task["recovery_status"] = "recovery_required"
            task["error"] = "Runner 不支持 rollback.restore"
            task["available_recovery_actions"] = ["rollback", "fail"]
            return self._save(task)
        try:
            rollback_action["result"] = handler(rollback_action, self.context) or {}
            rollback_action["status"] = "succeeded"
        except Exception as exc:
            rollback_action["status"] = "failed"
            rollback_action["error"] = str(exc)
            task["status"] = "rollback_failed"
            task["recovery_status"] = "recovery_required"
            task["error"] = str(exc)
            task["available_recovery_actions"] = ["rollback", "fail"]
            task["automatic_rollback"] = rollback_action
            return self._save(task)
        health_handler = self.handlers.get(str(failed_health_action.get("type") or ""))
        if health_handler is None:
            task["status"] = "rollback_failed"
            task["recovery_status"] = "recovery_required"
            task["error"] = "回滚后缺少健康检查处理器"
            task["available_recovery_actions"] = ["rollback", "fail"]
            task["automatic_rollback"] = rollback_action
            return self._save(task)
        try:
            rollback_action["post_rollback_health"] = health_handler(failed_health_action, self.context) or {}
        except Exception as exc:
            task["status"] = "rollback_failed"
            task["recovery_status"] = "recovery_required"
            task["error"] = f"回滚后健康检查失败：{exc}"
            task["available_recovery_actions"] = ["rollback", "fail"]
            task["automatic_rollback"] = rollback_action
            return self._save(task)
        task["automatic_rollback"] = rollback_action
        task["status"] = "rolled_back"
        task["recovery_status"] = "rolled_back"
        task["available_recovery_actions"] = []
        task["logs"] = [*task.get("logs", []), "自动回滚完成。"]
        return self._save(task)

    def _can_resume(self, action: dict[str, Any]) -> bool:
        action_type = str(action.get("type") or "")
        if action_type in SAFE_RESUME_ACTIONS:
            return True
        if action_type != "script.run_sandboxed":
            return False
        marker = action.get("params", {}).get("completion_marker")
        return bool(marker and Path(str(marker)).is_file())

    def _anchor_based_rollback(
        self,
        task: dict[str, Any],
        anchor: dict[str, Any],
        failed_action: dict[str, Any],
    ) -> dict[str, Any]:
        """锚点驱动的应用回滚：override 旧 tag → compose.apply → 健康门 → 计数守卫。

        全部**复用现有动作实现**，不新增计划词汇（设计 v1 §5.0 / impl-spec §W5 场景 A）。
        每一步的失败都如实落进 `automatic_rollback.steps`，失败证据不删（US-09 教训：
        宁留记录，不擦痕迹）。
        """
        action_context = self.context.get("action_context")
        database = Path(str(getattr(action_context, "data_path", "") or "")) / "smartx.db"
        rollback_images = anchor_rollback_override_images(anchor)
        services = [str(item.get("service")) for item in rollback_images]
        record: dict[str, Any] = {
            "mode": "anchor_apply",
            "attempt": int(task.get("rollback_attempts") or 0),
            "trigger_action": str(failed_action.get("type") or ""),
            "previous_version": str(anchor.get("previous_version") or ""),
            "images": rollback_images,
            "backup": anchor.get("backup") or {},
            "steps": [],
        }
        task["automatic_rollback"] = record

        def fail(message: str) -> dict[str, Any]:
            record["error"] = message
            task["automatic_rollback"] = record
            task["status"] = "rollback_failed"
            task["recovery_status"] = "recovery_required"
            task["error"] = message
            task["available_recovery_actions"] = ["rollback", "fail"]
            return self._save(task)

        if not rollback_images:
            return fail("回滚锚点里没有旧镜像 tag，无法指回上一版（请走场景 C 整备回滚）")

        # ① 指回旧 tag
        override_handler = self.handlers.get("compose.override")
        if override_handler is None:
            return fail("Runner 不支持 compose.override，无法执行锚点回滚")
        override_action = {
            "id": "rollback-override",
            "type": "compose.override",
            "params": {"images": rollback_images, "services": services},
        }
        try:
            record["steps"].append(
                {
                    "step": "compose.override",
                    "result": override_handler(override_action, {**self.context, "task": task}) or {},
                }
            )
        except Exception as exc:  # noqa: BLE001
            record["steps"].append({"step": "compose.override", "error": str(exc)})
            return fail(f"回滚写回旧镜像失败：{exc}")

        # ② 重建到旧版本（compose.apply 自带差异清单与 runner 不变断言）
        apply_handler = self.handlers.get("compose.apply")
        if apply_handler is None:
            return fail("Runner 不支持 compose.apply，无法执行锚点回滚")
        apply_action = {
            "id": "rollback-apply",
            "type": "compose.apply",
            "params": {"services": services, "images": rollback_images},
        }
        try:
            record["steps"].append(
                {
                    "step": "compose.apply",
                    "result": apply_handler(apply_action, {**self.context, "task": task}) or {},
                }
            )
        except Exception as exc:  # noqa: BLE001
            record["steps"].append({"step": "compose.apply", "error": str(exc)})
            return fail(f"回滚重建旧版本失败：{exc}")

        # ③ 健康门：失败在 health.* 就沿用那一步；失败在 apply 就用**自己造的**平台健康动作。
        # 沙箱 c3-case-a3 实测踩过：早先直接 copy 失败动作再改 type，于是 compose.apply 的
        # params（没有 url）被当成健康检查参数传下去 → `url=None` → 健康门必然失败 →
        # 每次 apply 触发的回滚都以 rollback_failed 收场。参数必须来自健康动作自己。
        failed_type = str(failed_action.get("type") or "")
        if failed_type.startswith("health."):
            health_action = dict(failed_action)
            health_type = failed_type
        else:
            health_action = {
                "id": f"{failed_action.get('id') or 'apply'}-post-rollback-health",
                "type": "health.http",
                "params": dict(PLATFORM_HEALTH_PARAMS),
            }
            health_type = "health.http"
        health_handler = self.handlers.get(health_type)
        if health_handler is None:
            return fail("回滚后缺少健康检查处理器")
        try:
            record["steps"].append(
                {
                    "step": health_action["type"],
                    "result": health_handler(health_action, {**self.context, "task": task}) or {},
                }
            )
        except Exception as exc:  # noqa: BLE001
            record["steps"].append({"step": health_action["type"], "error": str(exc)})
            return fail(f"回滚后健康检查失败：{exc}")

        # ④ 业务计数守卫：数据不得比升级前更少
        guard = business_count_guard(anchor, database)
        record["steps"].append({"step": "business_count_guard", "result": guard})
        if not guard["ok"]:
            return fail(
                "回滚后业务计数守卫未通过（数据变少）："
                + json.dumps(guard["regressions"], ensure_ascii=False)
            )

        task["automatic_rollback"] = record
        task["status"] = "rolled_back"
        task["recovery_status"] = "rolled_back"
        task["error"] = str(failed_action.get("error") or "")
        task["logs"] = [
            *task.get("logs", []),
            f"已回滚到 {anchor.get('previous_version') or '升级前版本'}"
            f"（{'、'.join(services) or '无服务'}），业务计数守卫通过",
        ]
        return self._save(task)
