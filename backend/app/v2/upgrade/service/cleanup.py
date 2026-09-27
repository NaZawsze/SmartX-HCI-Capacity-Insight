from __future__ import annotations

"""Post-upgrade cleanup task lifecycle."""

import shutil
from typing import Any
from app.v2.tasks.models import TaskStatus, TaskType
from app.upgrade_protocol.constants import TASK_SCHEMA_VERSION
from app.upgrade_runner.main import _action_steps as _runner_action_steps
from app.v2.upgrade.compiler import compile_post_upgrade_cleanup_plan

from ._compat import HTTPException, UploadFile

from .fs import _now
from .taskfile import _read_task_file, _save_task_file

class CleanupMixin:
    def create_post_upgrade_cleanup_task(self, parent_task_id: str, legacy_cleanup: dict[str, Any] | None = None) -> dict[str, Any]:
        parent_dir = self.settings.upgrades_dir / parent_task_id
        parent = _read_task_file(parent_dir)
        cleanup_config = dict(legacy_cleanup or (parent.get("manifest") or {}).get("legacy_cleanup") or {})
        if not cleanup_config:
            raise HTTPException(status_code=400, detail="当前升级任务没有旧环境清理配置。")
        cleanup_id = f"post-cleanup-{parent_task_id}"
        cleanup_dir = self.settings.upgrades_dir / cleanup_id
        if (cleanup_dir / "task.json").is_file():
            return self._public_task(_read_task_file(cleanup_dir))
        target_version = str(parent.get("target_version") or (parent.get("manifest") or {}).get("version") or self.settings.app_version)
        target_project = self.settings.compose_project_name
        plan = compile_post_upgrade_cleanup_plan(
            cleanup_config,
            parent_task_id=parent_task_id,
            target_version=target_version,
            target_project=target_project,
        )
        now = _now().isoformat()
        cleanup_task = {
            "task_id": cleanup_id,
            "status": "pending",
            "target_version": target_version,
            "components": ["platform"],
            "task_type": "post_upgrade_cleanup",
            "parent_task_id": parent_task_id,
            "manifest": {
                "version": target_version,
                "package_type": "post_upgrade_cleanup",
                "components": [{"type": "platform", "services": []}],
                "legacy_cleanup": cleanup_config,
            },
            "runner_requested": True,
            "task_schema_version": TASK_SCHEMA_VERSION,
            "execution_plan": plan.to_dict(),
            "created_at": now,
            "updated_at": now,
            "checks": [{"name": "post_upgrade_cleanup", "ok": True, "message": "旧环境清理任务已创建"}],
            "logs": [f"由平台升级任务 {parent_task_id} 创建升级后清理任务"],
        }
        _save_task_file(cleanup_dir, cleanup_task)
        parent["post_upgrade_cleanup_task_id"] = cleanup_id
        parent["post_upgrade_cleanup_status"] = "pending"
        parent["updated_at"] = now
        _save_task_file(parent_dir, parent)
        self.tasks.create_task(
            cleanup_id,
            TaskType.CLEANUP,
            "升级后清理",
            status=TaskStatus.PENDING,
            progress=1,
            message="等待 upgrade-runner 清理旧环境残留",
            logs=list(cleanup_task["logs"]),
            steps=_runner_action_steps(cleanup_task),
        )
        return self._public_task(cleanup_task)


    def retry_post_upgrade_cleanup(self, parent_task_id: str) -> dict[str, Any]:
        cleanup_id = f"post-cleanup-{parent_task_id}"
        self._ensure_no_active_upgrade(cleanup_id)
        cleanup_dir = self.settings.upgrades_dir / cleanup_id
        if cleanup_dir.exists():
            task = _read_task_file(cleanup_dir)
            if task.get("status") in {"pending", "running", "runner_restarting", "recovery_required"}:
                raise HTTPException(status_code=400, detail="升级后清理任务正在执行或等待恢复。")
            shutil.rmtree(cleanup_dir, ignore_errors=True)
        return self.create_post_upgrade_cleanup_task(parent_task_id)


    def post_upgrade_cleanup_status(self, parent_task_id: str) -> dict[str, Any]:
        parent = _read_task_file(self.settings.upgrades_dir / parent_task_id)
        manifest = parent.get("manifest") or {}
        post_upgrade = manifest.get("post_upgrade") if isinstance(manifest, dict) else None
        legacy_cleanup = manifest.get("legacy_cleanup") if isinstance(manifest, dict) else None
        if not (
            isinstance(post_upgrade, dict)
            and post_upgrade.get("create_cleanup_task")
            and isinstance(legacy_cleanup, dict)
            and legacy_cleanup
        ):
            return {"parent_task_id": parent_task_id, "status": "not_required", "task": None}
        cleanup_id = str(parent.get("post_upgrade_cleanup_task_id") or f"post-cleanup-{parent_task_id}")
        cleanup_file = self.settings.upgrades_dir / cleanup_id / "task.json"
        if not cleanup_file.is_file():
            return {"parent_task_id": parent_task_id, "status": "pending", "task_id": cleanup_id, "task": None}
        task = self._normalize_completed_runner_task(cleanup_file.parent, _read_task_file(cleanup_file.parent))
        public = self._public_task(task)
        cleanup_status = str(task.get("status") or "pending")
        if cleanup_status in {"success", "failed", "cancelled", "rolled_back", "rollback_failed", "recovery_required"}:
            parent_dir = self.settings.upgrades_dir / parent_task_id
            parent["post_upgrade_cleanup_status"] = cleanup_status
            if cleanup_status != "success":
                first_error = task.get("error")
                if not first_error:
                    for act in task.get("execution_plan", {}).get("actions") or []:
                        if act.get("error"):
                            first_error = act.get("error")
                            break
                if not first_error:
                    for log in task.get("logs") or []:
                        if "错误" in str(log) or "error" in str(log).lower():
                            first_error = log
                            break
                if first_error:
                    parent["post_upgrade_cleanup_error"] = first_error
            _save_task_file(parent_dir, parent)
        return {
            "parent_task_id": parent_task_id,
            "status": public["status"],
            "task_id": cleanup_id,
            "task": public,
        }
