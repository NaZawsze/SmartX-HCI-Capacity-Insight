from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.upgrade_runner.store import TaskStore


ActionHandler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
SAFE_RESUME_ACTIONS = {
    "backup.create",
    "image.load",
    "files.sync",
    "compose.override",
    "compose.apply",
    "health.http",
    "health.prometheus",
    "checkpoint.write",
    "rollback.restore",
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
    ) -> None:
        self.store = store
        self.handlers = handlers
        self.context = context or {}

    def run(self) -> dict[str, Any]:
        task = self.store.load()
        task["status"] = "running"
        task.setdefault("recovery_status", "none")
        task.setdefault("logs", [])
        task = self.store.save(task, expected_revision=int(task.get("revision") or 0))

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
                return self.store.save(task, expected_revision=int(task["revision"]))

            action["status"] = "running"
            action["attempt"] = int(action.get("attempt") or 0) + 1
            action["started_at"] = _now()
            action["finished_at"] = None
            action.setdefault("checkpoint", {})
            action.setdefault("result", {})
            task = self.store.save(task, expected_revision=int(task["revision"]))
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
                return self.store.save(task, expected_revision=int(task["revision"]))

            def checkpoint_writer(checkpoint: dict[str, Any]) -> None:
                nonlocal task
                task["execution_plan"]["actions"][index]["checkpoint"] = checkpoint
                task = self.store.save(task, expected_revision=int(task["revision"]))

            try:
                result = handler(action, {**self.context, "checkpoint_writer": checkpoint_writer}) or {}
            except Exception as exc:
                action = task["execution_plan"]["actions"][index]
                action["status"] = "failed"
                action["error"] = str(exc)
                action["finished_at"] = _now()
                if str(action.get("type", "")).startswith("health.") and int(task.get("rollback_attempts") or 0) < 1:
                    return self._automatic_rollback(task, exc, action)
                task["status"] = "failed"
                task["error"] = str(exc)
                task["logs"] = [*task.get("logs", []), str(exc)]
                return self.store.save(task, expected_revision=int(task["revision"]))
            action = task["execution_plan"]["actions"][index]
            action["status"] = "succeeded"
            action["result"] = result
            action["finished_at"] = _now()
            if result.get("checkpoint"):
                action["checkpoint"] = result["checkpoint"]
            task = self.store.save(task, expected_revision=int(task["revision"]))

        task["status"] = "success"
        task["recovery_status"] = "none"
        task["available_recovery_actions"] = []
        return self.store.save(task, expected_revision=int(task["revision"]))

    def _automatic_rollback(self, task: dict[str, Any], cause: Exception, failed_health_action: dict[str, Any]) -> dict[str, Any]:
        task["rollback_attempts"] = int(task.get("rollback_attempts") or 0) + 1
        task["status"] = "rollback_running"
        task["recovery_status"] = "rolling_back"
        task["logs"] = [*task.get("logs", []), f"健康检查失败，开始自动回滚：{cause}"]
        task = self.store.save(task, expected_revision=int(task["revision"]))
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
            return self.store.save(task, expected_revision=int(task["revision"]))
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
            return self.store.save(task, expected_revision=int(task["revision"]))
        health_handler = self.handlers.get(str(failed_health_action.get("type") or ""))
        if health_handler is None:
            task["status"] = "rollback_failed"
            task["recovery_status"] = "recovery_required"
            task["error"] = "回滚后缺少健康检查处理器"
            task["available_recovery_actions"] = ["rollback", "fail"]
            task["automatic_rollback"] = rollback_action
            return self.store.save(task, expected_revision=int(task["revision"]))
        try:
            rollback_action["post_rollback_health"] = health_handler(failed_health_action, self.context) or {}
        except Exception as exc:
            task["status"] = "rollback_failed"
            task["recovery_status"] = "recovery_required"
            task["error"] = f"回滚后健康检查失败：{exc}"
            task["available_recovery_actions"] = ["rollback", "fail"]
            task["automatic_rollback"] = rollback_action
            return self.store.save(task, expected_revision=int(task["revision"]))
        task["automatic_rollback"] = rollback_action
        task["status"] = "rolled_back"
        task["recovery_status"] = "rolled_back"
        task["available_recovery_actions"] = []
        task["logs"] = [*task.get("logs", []), "自动回滚完成。"]
        return self.store.save(task, expected_revision=int(task["revision"]))

    def _can_resume(self, action: dict[str, Any]) -> bool:
        action_type = str(action.get("type") or "")
        if action_type in SAFE_RESUME_ACTIONS:
            return True
        if action_type != "script.run_sandboxed":
            return False
        marker = action.get("params", {}).get("completion_marker")
        return bool(marker and Path(str(marker)).is_file())
