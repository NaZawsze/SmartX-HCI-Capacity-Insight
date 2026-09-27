from __future__ import annotations

"""Upgrade execution: start/status/cancel/rollback/recovery and runner sync."""

import json
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any
from app.v2.tasks.models import TaskStatus, TaskType
from app.upgrade_protocol.constants import TASK_SCHEMA_VERSION
from app.upgrade_protocol.validation import ProtocolValidationError, validate_manifest_compatibility
from app.upgrade_runner.main import _action_steps as _runner_action_steps
from app.v2.upgrade.compiler import UpgradeCompilationError, compile_execution_plan

from ._compat import HTTPException, UploadFile

from .fs import _now
from .precheck import _runner_bootstrap, _runner_compose_project_name, _runner_only, _task_images, _task_services, _version_from_image
from .taskfile import _completed_runner_task_view, _parse_datetime, _read_task_file, _replace_step, _save_task_file, _step

from .constants import RUNNER_HEARTBEAT_STALE_SECONDS, RUNNER_NOT_DETECTED


def _should_stop_previous_runner(bootstrap: Any, current_project: str) -> bool:
    """49-50：是否需要停止「旧 project 的 upgrade-runner」。

    只有 bootstrap 目标 project 与当前 compose project **不同**时才停——此时旧 runner 属于旧 project。
    两者相同（目标布局机器上原地做 runner 组件升级）时必须跳过，否则 `docker compose stop upgrade-runner`
    停掉的是**刚 `up -d` 启动的新 runner**（2026-09-27 在 10.20.11.12 两轮实测：启动后 10 秒 SIGKILL、
    `exit=137`、心跳过期导致后续升级预检查失败；旧链路因源端 project 不同而从未触发）。
    """
    if not bootstrap:
        return False
    target_project = str(bootstrap.get("target_project") or "").strip()
    if not target_project:
        # 未声明目标 project：保持旧行为（停止），避免旧 runner 心跳覆盖
        return True
    return target_project != str(current_project or "")

class ExecutionMixin:
    def start(self, task_id: str, *, submit_to_runner: bool = False) -> dict[str, Any]:
        task_dir = self.settings.upgrades_dir / task_id
        task = _read_task_file(task_dir)
        if task.get("status") != "precheck_passed":
            raise HTTPException(status_code=400, detail="预检查通过后才能开始升级。")
        if submit_to_runner:
            try:
                execution_plan = compile_execution_plan(task["manifest"])
            except (UpgradeCompilationError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            task["status"] = "pending"
            task["runner_requested"] = True
            task["task_schema_version"] = TASK_SCHEMA_VERSION
            task["execution_plan"] = execution_plan.to_dict()
            task["updated_at"] = _now().isoformat()
            _save_task_file(task_dir, task)
            self.tasks.create_task(task_id, TaskType.UPGRADE, "执行系统升级", status=TaskStatus.PENDING, progress=1, message="升级任务已提交，等待 upgrade-runner 执行")
            return self._public_task(task)
        return self.execute_task(task)


    def status(self, task_id: str) -> dict[str, Any]:
        task_dir = self.settings.upgrades_dir / task_id
        task = self._normalize_completed_runner_task(task_dir, _read_task_file(task_dir))
        return self._public_task(task)


    def cancel(self, task_id: str) -> dict[str, Any]:
        task_dir = self.settings.upgrades_dir / task_id
        task = self._read_task_or_pending_record(task_id, task_dir)
        if task.get("started_at") or task.get("status") != "pending":
            raise HTTPException(status_code=400, detail="只能取消等待执行的升级任务。")
        task["status"] = "cancelled"
        task["runner_requested"] = False
        task["runner_resume_pending"] = False
        task["cancelled_at"] = _now().isoformat()
        task["updated_at"] = task["cancelled_at"]
        logs = list(task.get("logs") or [])
        logs.append("管理员已取消等待中的升级任务")
        task["logs"] = logs
        _save_task_file(task_dir, task)
        self.tasks.update_task(task_id, status=TaskStatus.CANCELLED, progress=100, message="升级任务已取消", logs=logs)
        return self._public_task(task)


    def recovery_continue(self, task_id: str) -> dict[str, Any]:
        return self._set_recovery_command(task_id, "continue", "已请求 upgrade-runner 继续执行")


    def recovery_rollback(self, task_id: str) -> dict[str, Any]:
        return self._set_recovery_command(task_id, "rollback", "已请求 upgrade-runner 执行回滚")


    def recovery_fail(self, task_id: str) -> dict[str, Any]:
        task_dir = self.settings.upgrades_dir / task_id
        task = _read_task_file(task_dir)
        if task.get("status") != "recovery_required":
            raise HTTPException(status_code=400, detail="只有等待恢复的升级任务可以标记失败。")
        task["status"] = "failed"
        task["recovery_status"] = "failed"
        task["recovery_command"] = "fail"
        task["available_recovery_actions"] = []
        task["error"] = task.get("error") or "管理员已将恢复任务标记为失败。"
        task["updated_at"] = _now().isoformat()
        _save_task_file(task_dir, task)
        self.tasks.update_task(task_id, status=TaskStatus.FAILED, progress=100, message=task["error"])
        return self._public_task(task)


    def _set_recovery_command(self, task_id: str, command: str, message: str) -> dict[str, Any]:
        task_dir = self.settings.upgrades_dir / task_id
        task = _read_task_file(task_dir)
        if task.get("status") != "recovery_required":
            raise HTTPException(status_code=400, detail="当前升级任务不需要恢复处理。")
        if command not in set(task.get("available_recovery_actions") or []):
            raise HTTPException(status_code=400, detail="当前恢复操作不可用。")
        task["recovery_command"] = command
        task["runner_requested"] = True
        task["updated_at"] = _now().isoformat()
        _save_task_file(task_dir, task)
        self.tasks.update_task(task_id, status=TaskStatus.RUNNING, progress=50, message=message)
        return self._public_task(task)


    def _runner_state(self) -> dict[str, Any] | None:
        with self.tasks.database.connection() as conn:
            row = conn.execute("SELECT * FROM upgrade_runner_state WHERE id = 1").fetchone()
        if not row:
            return None
        payload = dict(row)
        try:
            payload["capabilities"] = json.loads(payload.pop("capabilities_json"))
        except (json.JSONDecodeError, TypeError):
            payload["capabilities"] = []
        return payload


    def _active_runner_state(self) -> dict[str, Any] | None:
        runner_state = self._runner_state()
        if runner_state and _runner_state_is_fresh(runner_state):
            runner_state["source"] = "heartbeat"
            return runner_state
        return self._active_runner_state_from_docker()


    def _active_runner_state_from_docker(self) -> dict[str, Any] | None:
        try:
            output = self.executor.output(
                [
                    "docker",
                    "ps",
                    "--filter",
                    "name=upgrade-runner",
                    "--filter",
                    "status=running",
                    "--format",
                    "{{json .}}",
                ],
                cwd=self.project_path,
            )
        except Exception:
            return None
        candidates: list[dict[str, Any]] = []
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            container = str(item.get("Names") or item.get("Name") or item.get("Container") or "").strip()
            image = str(item.get("Image") or "").strip()
            if not container or "upgrade-runner" not in container:
                continue
            candidates.append({"container": container, "image": image})
        if not candidates:
            return None
        candidates.sort(key=lambda item: ("smartx-hci-capacity-insight" not in item["container"], item["container"]))
        for candidate in candidates:
            container = candidate["container"]
            version = ""
            try:
                version = self.executor.output(["docker", "exec", container, "sh", "-lc", "cat /app/RUNNER_VERSION 2>/dev/null || true"], cwd=self.project_path).strip()
            except Exception:
                version = ""
            if not version:
                version = _version_from_image(candidate["image"]) or ""
            if version:
                return {
                    "runner_version": version,
                    "protocol_version": 0,
                    "capabilities": [],
                    "heartbeat_at": None,
                    "container": container,
                    "image": candidate["image"],
                    "source": "docker",
                }
        return None


    def _active_runner_version(self, runner_state: dict[str, Any] | None = None) -> str:
        state = runner_state if runner_state is not None else self._active_runner_state()
        version = str(state.get("runner_version") or "").strip() if state else ""
        return version or RUNNER_NOT_DETECTED


    def _check_runner_protocol(self, manifest: dict[str, Any]) -> dict[str, Any]:
        runner_state = self._active_runner_state()
        minimum_runner_version = str(manifest.get("minimum_runner_version") or "").strip()
        if not runner_state or runner_state.get("source") != "heartbeat":
            return {
                "name": "runner_protocol",
                "ok": False,
                "message": (
                    f"未检测到 upgrade-runner 心跳，无法确认升级执行器能力。请先升级 upgrade-runner 到 {minimum_runner_version}。"
                    if minimum_runner_version
                    else "未检测到 upgrade-runner 心跳，无法确认升级执行器能力。"
                ),
                "detail": {
                    "required_capabilities": list(manifest.get("required_capabilities") or []),
                    "minimum_runner_version": minimum_runner_version or None,
                    "runner_version": runner_state.get("runner_version") if runner_state else None,
                    "capabilities": runner_state.get("capabilities", []) if runner_state else [],
                    "source": runner_state.get("source") if runner_state else None,
                },
            }
        capabilities = [str(item) for item in runner_state.get("capabilities") or []]
        protocol_version = int(runner_state.get("protocol_version") or 0)
        try:
            validate_manifest_compatibility(manifest, protocol_version, capabilities)
        except (ProtocolValidationError, TypeError, ValueError) as exc:
            message = str(exc)
            if minimum_runner_version:
                message = f"{message}。请先升级 upgrade-runner 到 {minimum_runner_version}。"
            return {
                "name": "runner_protocol",
                "ok": False,
                "message": message,
                "detail": {
                    "runner_version": runner_state.get("runner_version"),
                    "minimum_runner_version": minimum_runner_version,
                    "protocol_version": protocol_version,
                    "required_capabilities": list(manifest.get("required_capabilities") or []),
                    "capabilities": capabilities,
                    "heartbeat_at": runner_state.get("heartbeat_at"),
                },
            }
        return {
            "name": "runner_protocol",
            "ok": True,
            "message": "Runner 协议与能力满足升级包要求",
            "detail": {
                "runner_version": runner_state.get("runner_version"),
                "minimum_runner_version": minimum_runner_version or None,
                "protocol_version": protocol_version,
                "required_capabilities": list(manifest.get("required_capabilities") or []),
                "capabilities": capabilities,
                "heartbeat_at": runner_state.get("heartbeat_at"),
            },
        }


    def rollback(self, task_id: str) -> dict[str, Any]:
        task_dir = self.settings.upgrades_dir / task_id
        task = _read_task_file(task_dir)
        if not task.get("started_at"):
            raise HTTPException(status_code=400, detail="升级尚未执行，不能回滚。")
        services = sorted(_task_services(task["manifest"]))
        logs = list(task.get("logs") or [])
        steps = [
            _step("rollback_config", "恢复升级前镜像配置", "running"),
            _step("rollback_restart", "重启回滚服务", "pending"),
            _step("rollback_healthcheck", "执行回滚健康检查", "pending"),
        ]
        task["status"] = "rollback_running"
        task["rollback_started_at"] = _now().isoformat()
        task["steps"] = steps
        _save_task_file(task_dir, task)
        self.tasks.update_task(task_id, status=TaskStatus.RUNNING, progress=10, message="正在执行手动回滚", logs=logs, steps=steps)
        try:
            project_backup = Path(task["project_backup_path"]) if task.get("project_backup_path") else None
            if project_backup and project_backup.is_dir():
                for source in sorted(project_backup.rglob("*")):
                    if source.is_dir():
                        continue
                    relative = source.relative_to(project_backup)
                    target = self.project_path / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                logs.append(f"已恢复项目文件：{project_backup}")
            override_path = Path(task["override_path"]) if task.get("override_path") else None
            if override_path and override_path.exists():
                override_path.unlink()
                logs.append(f"已移除运行时覆盖配置：{override_path}")
            steps = _replace_step(steps, "rollback_config", "succeeded")
            steps = _replace_step(steps, "rollback_restart", "running")
            self.tasks.update_task(task_id, progress=60, message="正在重启回滚服务", logs=logs, steps=steps)
            self.executor.run(["docker", "compose", "-f", self.settings.compose_file, "--project-name", self.settings.compose_project_name, "up", "-d", "--no-deps", *services], cwd=self.project_path)
            steps = _replace_step(steps, "rollback_restart", "succeeded")
            steps = _replace_step(steps, "rollback_healthcheck", "succeeded", "回滚健康检查占位通过")
            task["status"] = "rolled_back"
            task["rollback_finished_at"] = _now().isoformat()
            task["steps"] = steps
            task["logs"] = logs
            task["updated_at"] = _now().isoformat()
            _save_task_file(task_dir, task)
            self.tasks.update_task(task_id, status=TaskStatus.SUCCESS, progress=100, message="回滚完成", logs=logs, steps=steps)
            return self._public_task(task)
        except Exception as exc:
            task["status"] = "rollback_failed"
            task["error"] = str(exc)
            task["steps"] = steps
            task["logs"] = logs + [str(exc)]
            task["updated_at"] = _now().isoformat()
            _save_task_file(task_dir, task)
            self.tasks.update_task(task_id, status=TaskStatus.FAILED, progress=100, message=str(exc), logs=task["logs"], steps=steps)
            raise


    def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        task_id = task["task_id"]
        task_dir = self.settings.upgrades_dir / task_id
        if task.get("status") == "runner_restarting" and task.get("runner_resume_pending"):
            return self._resume_runner_upgrade(task)
        steps = [
            _step("backup", "生成升级前数据备份", "running"),
            _step("load_images", "加载升级镜像", "pending"),
            _step("project_files", "同步项目文件", "pending"),
            _step("write_override", "写入服务镜像覆盖配置", "pending"),
            _step("restart", "重启升级服务", "pending"),
            _step("healthcheck", "执行服务健康检查", "pending"),
        ]
        logs: list[str] = []
        task["status"] = "running"
        task["started_at"] = _now().isoformat()
        task["steps"] = steps
        task["logs"] = logs
        _save_task_file(task_dir, task)
        self.tasks.create_task(task_id, TaskType.UPGRADE, "执行系统升级", status=TaskStatus.RUNNING, progress=5, message="正在生成升级前备份", logs=logs, steps=steps)
        try:
            backup_path = self._create_upgrade_backup(task)
            logs.append(f"升级前备份：{backup_path}")
            steps = _replace_step(steps, "backup", "succeeded", str(backup_path))
            self.tasks.update_task(task_id, progress=20, message="升级前备份已完成", logs=logs, steps=steps)

            package_path = Path(task["package_path"])
            images = _task_images(task["manifest"])
            image_archives = [image for image in images if image.get("archive")]
            steps = _replace_step(steps, "load_images", "running", f"{len(images)} 个镜像")
            self.tasks.update_task(task_id, progress=35, message="正在加载升级镜像", logs=logs, steps=steps)
            for image in image_archives:
                archive_path = package_path / str(image["archive"])
                self.executor.run(["docker", "load", "-i", str(archive_path)])
                logs.append(f"已加载镜像：{image['image']}")
            steps = _replace_step(steps, "load_images", "succeeded", f"已加载 {len(image_archives)} 个镜像；其余镜像使用仓库引用")

            steps = _replace_step(steps, "project_files", "running")
            self.tasks.update_task(task_id, progress=55, message="正在同步项目文件", logs=logs[-8:], steps=steps)
            project_backup = self._sync_project_files(task)
            if project_backup:
                logs.append(f"项目文件备份：{project_backup}")
                steps = _replace_step(steps, "project_files", "succeeded", str(project_backup))
            else:
                steps = _replace_step(steps, "project_files", "succeeded", "升级包未包含项目文件")

            steps = _replace_step(steps, "write_override", "running")
            self.tasks.update_task(task_id, progress=70, message="正在写入运行时覆盖配置", logs=logs[-8:], steps=steps)
            override_path = self._write_task_override(task["manifest"], images)
            logs.append(f"运行时覆盖配置：{override_path}")
            steps = _replace_step(steps, "write_override", "succeeded", str(override_path))

            steps = _replace_step(steps, "restart", "running")
            self.tasks.update_task(task_id, progress=82, message="正在重启升级服务", logs=logs[-8:], steps=steps)
            if _runner_only(task["manifest"]):
                task["status"] = "runner_restarting"
                task["runner_resume_pending"] = True
                task["steps"] = steps
                task["logs"] = logs
                task["updated_at"] = _now().isoformat()
                _save_task_file(task_dir, task)
            compose_command = ["docker", "compose"]
            if _runner_only(task["manifest"]):
                compose_command.extend(["-f", str(override_path)])
            else:
                compose_command.extend(["-f", self.settings.compose_file, "-f", str(override_path)])
            compose_project_name = _runner_compose_project_name(task["manifest"], self.settings.compose_project_name)
            compose_command.extend(["--project-name", compose_project_name, "up", "-d", "--no-deps", *sorted(_task_services(task["manifest"]))])
            try:
                self.executor.run(compose_command, cwd=self.project_path)
                bootstrap = _runner_bootstrap(task["manifest"])
                if bootstrap and _should_stop_previous_runner(bootstrap, self.settings.compose_project_name):
                    self.executor.run(
                        ["docker", "compose", "-f", self.settings.compose_file, "--project-name", self.settings.compose_project_name, "stop", "upgrade-runner"],
                        cwd=self.project_path,
                    )
                    logs.append("已停止旧 project upgrade-runner，避免旧 runner 心跳覆盖新版本。")
                elif bootstrap:
                    logs.append("新旧 runner 同属当前 compose project，跳过停止旧 runner（否则会停掉刚启动的新 runner）。")
            except SystemExit:
                if _runner_only(task["manifest"]):
                    self.tasks.update_task(task_id, status=TaskStatus.RUNNING, progress=86, message="upgrade-runner 正在重启，等待新进程接续", logs=logs, steps=steps)
                    return self._public_task(task)
                raise
            logs.append("升级服务已提交重启")
            steps = _replace_step(steps, "restart", "succeeded")

            steps = _replace_step(steps, "healthcheck", "succeeded", "健康检查占位通过")
            task["status"] = "success"
            task["runner_resume_pending"] = False
            task["backup_path"] = str(backup_path)
            task["project_backup_path"] = str(project_backup) if project_backup else None
            task["override_path"] = str(override_path)
            task["steps"] = steps
            task["logs"] = logs
            task["updated_at"] = _now().isoformat()
            task["finished_at"] = task["updated_at"]
            task["logs"] = logs
            try:
                _save_task_file(task_dir, task)
            except HTTPException as exc:
                recovered = self._recover_runner_only_success_after_save_conflict(task_dir, task, exc)
                if recovered is not None:
                    return self._public_task(recovered)
                raise
            self.tasks.update_task(task_id, status=TaskStatus.SUCCESS, progress=100, message="升级执行完成", logs=logs, steps=steps)
        except Exception as exc:
            task["status"] = "failed"
            task["error"] = str(exc)
            task["steps"] = steps
            task["logs"] = logs + [str(exc)]
            task["updated_at"] = _now().isoformat()
            _save_task_file(task_dir, task)
            self.tasks.update_task(task_id, status=TaskStatus.FAILED, progress=100, message=str(exc), logs=task["logs"], steps=steps)
            return self._public_task(task)
        return self._public_task(task)


    def _recover_runner_only_success_after_save_conflict(self, task_dir: Path, attempted_task: dict[str, Any], exc: HTTPException) -> dict[str, Any] | None:
        if getattr(exc, "status_code", None) != 409:
            return None
        if not _runner_only(attempted_task.get("manifest") or {}):
            return None
        current = _read_task_file(task_dir)
        if str(current.get("status") or "") not in {"success", "succeeded"}:
            return None
        self._project_runner_task(current)
        return current


    def _resume_runner_upgrade(self, task: dict[str, Any]) -> dict[str, Any]:
        task_id = task["task_id"]
        task_dir = self.settings.upgrades_dir / task_id
        logs = list(task.get("logs") or [])
        steps = list(task.get("steps") or [])
        logs.append("upgrade-runner 已重新启动，继续完成组件升级任务")
        steps = _replace_step(steps, "restart", "succeeded", "upgrade-runner 已重新启动")
        steps = _replace_step(steps, "healthcheck", "succeeded", "组件升级健康检查占位通过")
        task["status"] = "success"
        task["runner_resume_pending"] = False
        task["steps"] = steps
        task["logs"] = logs
        task["updated_at"] = _now().isoformat()
        task["finished_at"] = task["updated_at"]
        task["logs"] = logs
        _save_task_file(task_dir, task)
        self.tasks.update_task(task_id, status=TaskStatus.SUCCESS, progress=100, message="组件升级执行完成", logs=logs, steps=steps)
        return self._public_task(task)


    def _normalize_completed_runner_task(self, task_dir: Path, task: dict[str, Any]) -> dict[str, Any]:
        actions = task.get("execution_plan", {}).get("actions") or []
        if not actions:
            return task
        if str(task.get("status") or "") in {"success", "failed", "rollback_failed", "rolled_back", "recovery_required", "cancelled"}:
            if str(task.get("status") or "") == "success":
                self._project_runner_task(task)
                self._maybe_schedule_post_upgrade_cleanup(task)
            return task
        completed = _completed_runner_task_view(task)
        if completed is task:
            return task
        task = completed
        updated_at = _now().isoformat()
        task["updated_at"] = updated_at
        task["finished_at"] = task.get("finished_at") or updated_at
        _save_task_file(task_dir, task)
        self._project_runner_task(task)
        self._maybe_schedule_post_upgrade_cleanup(task)
        return task


    def _maybe_schedule_post_upgrade_cleanup(self, task: dict[str, Any]) -> None:
        manifest = task.get("manifest") or {}
        post_upgrade = manifest.get("post_upgrade") if isinstance(manifest, dict) else None
        legacy_cleanup = manifest.get("legacy_cleanup") if isinstance(manifest, dict) else None
        if not (
            isinstance(post_upgrade, dict)
            and post_upgrade.get("create_cleanup_task")
            and isinstance(legacy_cleanup, dict)
            and legacy_cleanup
        ):
            return
        task_id = str(task.get("task_id") or "")
        if not task_id:
            return
        cleanup_id = f"post-cleanup-{task_id}"
        if (self.settings.upgrades_dir / cleanup_id / "task.json").is_file():
            return
        try:
            self.create_post_upgrade_cleanup_task(task_id, legacy_cleanup)
        except Exception as exc:
            logs = list(task.get("logs") or [])
            logs.append(f"升级后清理任务创建失败：{exc}")
            task["logs"] = logs
            task["post_upgrade_cleanup_status"] = "failed"
            task["post_upgrade_cleanup_error"] = str(exc)
            task["updated_at"] = _now().isoformat()
            _save_task_file(self.settings.upgrades_dir / task_id, task)
            try:
                self.tasks.create_task(
                    f"post-cleanup-{task_id}-warning",
                    TaskType.CLEANUP,
                    "升级后清理",
                    status=TaskStatus.FAILED,
                    progress=100,
                    message=f"升级后清理任务创建失败：{exc}",
                    logs=logs,
                )
            except Exception:
                return


    def _project_runner_task(self, task: dict[str, Any]) -> None:
        steps = _runner_action_steps(task)
        task_id = str(task["task_id"])
        logs = list(task.get("logs") or [])
        existing = self.tasks.get_task(task_id)
        if (
            existing
            and existing.get("type") == TaskType.UPGRADE.value
            and existing.get("status") == TaskStatus.SUCCESS.value
            and existing.get("title") == "执行系统升级"
            and existing.get("progress") == 100
            and existing.get("message") == "升级执行完成"
            and existing.get("logs") == logs
            and existing.get("steps") == steps
        ):
            return
        self.tasks.create_task(
            task_id,
            TaskType.UPGRADE,
            "执行系统升级",
            status=TaskStatus.SUCCESS,
            progress=100,
            message="升级执行完成",
            logs=logs,
            steps=steps,
        )

def _runner_state_is_fresh(state: dict[str, Any]) -> bool:
    heartbeat_at = _parse_datetime(state.get("heartbeat_at") or state.get("updated_at"))
    if heartbeat_at is None:
        return False
    return _now() - heartbeat_at <= timedelta(seconds=RUNNER_HEARTBEAT_STALE_SECONDS)
