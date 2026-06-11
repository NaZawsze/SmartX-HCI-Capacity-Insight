from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_hex
from typing import Any

try:  # upgrade-runner intentionally avoids the web-api dependency stack.
    from fastapi import HTTPException, UploadFile
except ModuleNotFoundError:  # pragma: no cover - covered by runner image import smoke test.
    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str) -> None:
            self.status_code = status_code
            self.detail = detail
            super().__init__(detail)

    class UploadFile:  # type: ignore[no-redef]
        filename: str | None

from app.v2.config import V2Settings
from app.v2.tasks.models import TaskStatus, TaskType
from app.v2.tasks.service import TaskService
from app.upgrade_protocol.constants import RUNNER_CAPABILITIES, RUNNER_PROTOCOL_VERSION, TASK_SCHEMA_VERSION
from app.upgrade_protocol.validation import ProtocolValidationError, validate_manifest_compatibility
from app.upgrade_runner.store import RevisionConflict, TaskStore
from app.v2.upgrade.compiler import UpgradeCompilationError, compile_execution_plan


MANIFEST_NAME = "manifest.json"
SENSITIVE_NAMES = {".env", "smartx.db"}
SENSITIVE_PARTS = {"backups", "exports", "compose-runtime", "password", "token", "secret"}
PLATFORM_SERVICES = {"web-api", "collector-worker", "frontend"}
OBSERVABILITY_SERVICES = {"prometheus"}
RUNNER_SERVICES = {"upgrade-runner"}


def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    try:
        archive.extractall(destination, filter="data")
    except TypeError:  # Python < 3.12 has no extraction filter argument.
        archive.extractall(destination)


class UpgradeCommandExecutor:
    def run(self, command: list[str], *, cwd: Path | None = None) -> None:
        if os.environ.get("SMARTX_UPGRADE_DRY_RUN") == "1":
            return
        subprocess.run(command, cwd=str(cwd) if cwd else None, check=True)

    def output(self, command: list[str], *, cwd: Path | None = None) -> str:
        if os.environ.get("SMARTX_UPGRADE_DRY_RUN") == "1":
            return ""
        completed = subprocess.run(command, cwd=str(cwd) if cwd else None, check=True, text=True, capture_output=True)
        return completed.stdout


class UpgradeService:
    def __init__(self, settings: V2Settings, tasks: TaskService, *, executor: UpgradeCommandExecutor | None = None, project_path: Path | None = None) -> None:
        self.settings = settings
        self.tasks = tasks
        self.executor = executor or UpgradeCommandExecutor()
        self.project_path = project_path or Path("/opt/smartx-storage-forecast")

    async def upload_package(self, upload: UploadFile) -> dict[str, Any]:
        return self.upload_package_bytes(await upload.read(), filename=upload.filename or "upgrade.tar.gz")

    def upload_package_bytes(self, content: bytes, *, filename: str) -> dict[str, Any]:
        if not content:
            raise HTTPException(status_code=400, detail="升级包为空。")
        task_id = f"upgrade-{token_hex(8)}"
        task_dir = self.settings.upgrades_dir / task_id
        package_path = task_dir / "package"
        package_path.mkdir(parents=True, exist_ok=True)
        upload_path = task_dir / Path(filename).name
        upload_path.write_bytes(content)
        try:
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
                _validate_members(archive)
                _safe_extract(archive, package_path)
        except (tarfile.TarError, OSError) as exc:
            shutil.rmtree(task_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"无法读取升级包：{exc}") from exc
        manifest = _read_manifest(package_path / MANIFEST_NAME)
        components = _component_types(manifest)
        task = {
            "task_id": task_id,
            "status": "uploaded",
            "target_version": str(manifest.get("version") or ""),
            "components": components,
            "manifest": manifest,
            "filename": Path(filename).name,
            "package_path": str(package_path),
            "uploaded_path": str(upload_path),
            "created_at": _now().isoformat(),
            "checks": [],
        }
        _save_task_file(task_dir, task)
        self.tasks.create_task(task_id, TaskType.UPGRADE, "上传升级包", status=TaskStatus.SUCCESS, progress=100, message=f"升级包已上传：{task['target_version']}")
        return self._public_task(task)

    def precheck(self, task_id: str) -> dict[str, Any]:
        task_dir = self.settings.upgrades_dir / task_id
        task = _read_task_file(task_dir)
        package_path = Path(task["package_path"])
        manifest = task["manifest"]
        checks = [
            _check_manifest(manifest),
            {"name": "paths", "ok": True, "message": "包内路径安全"},
        ]
        if manifest.get("schema_version") == "3":
            checks.extend([_check_protocol(manifest), _check_package_checksums(package_path)])
        checks.extend([_check_images(package_path, manifest), _check_project_files(package_path, manifest)])
        if _observability_services(manifest):
            checks.append(_check_prometheus_permissions(self.settings.prometheus_data_dir))
        task["checks"] = checks
        task["status"] = "precheck_passed" if all(check["ok"] for check in checks) else "precheck_failed"
        task["updated_at"] = _now().isoformat()
        _save_task_file(task_dir, task)
        self.tasks.create_task(
            task_id,
            TaskType.UPGRADE,
            "升级预检查",
            status=TaskStatus.SUCCESS if task["status"] == "precheck_passed" else TaskStatus.FAILED,
            progress=100,
            message="预检查通过" if task["status"] == "precheck_passed" else "预检查失败",
            logs=[check["message"] for check in checks],
        )
        return self._public_task(task)

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
        return self._public_task(_read_task_file(self.settings.upgrades_dir / task_id))

    def history(self, *, component_type: str | None = None) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for task_file in sorted(self.settings.upgrades_dir.glob("*/task.json"), key=lambda path: path.stat().st_mtime, reverse=True):
            task = _read_task_file(task_file.parent)
            if component_type and component_type not in set(task.get("components") or []):
                continue
            tasks.append(self._public_task(task))
        return tasks

    def delete_package(self, task_id: str) -> dict[str, Any]:
        task_dir = self.settings.upgrades_dir / task_id
        task = _read_task_file(task_dir)
        if task.get("started_at") or task.get("status") in {"running", "pending", "runner_restarting", "success", "failed"}:
            raise HTTPException(status_code=400, detail="已开始执行的升级包不能删除。")
        shutil.rmtree(task_dir, ignore_errors=True)
        return {"ok": True, "task_id": task_id}

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

    def version(self) -> dict[str, str]:
        return {"version": self.settings.app_version}

    def component_version(self) -> dict[str, str]:
        return {"component": "upgrade-runner", "version": self.settings.runner_version}

    def component_catalog(self) -> dict[str, Any]:
        prometheus_status = self._inspect_service_by_name("prometheus")
        prometheus_version = _version_from_service_status(prometheus_status) or "-"
        runner_state = self._runner_state()
        runner_capabilities = runner_state.get("capabilities", []) if runner_state else []
        compatible = bool(
            runner_state
            and int(runner_state.get("protocol_version") or 0) >= RUNNER_PROTOCOL_VERSION
            and RUNNER_CAPABILITIES <= set(runner_capabilities)
        )
        return {
            "components": [
                {
                    "type": "runner",
                    "display_name": "升级中心组件",
                    "service": "upgrade-runner",
                    "version": self.settings.runner_version,
                    "protocol_version": runner_state.get("protocol_version") if runner_state else None,
                    "capabilities": runner_capabilities,
                    "heartbeat_at": runner_state.get("heartbeat_at") if runner_state else None,
                    "compatible": compatible,
                    "executor": "web-api",
                    "upgradeable": True,
                    "status_message": "由 web-api 执行自升级，不修改业务库和历史指标。",
                },
                {
                    "type": "observability",
                    "display_name": "观测组件",
                    "service": "prometheus",
                    "version": prometheus_version,
                    "executor": "upgrade-runner",
                    "upgradeable": True,
                    "status_message": prometheus_status.get("error") or "由 upgrade-runner 执行升级，保留 Prometheus 历史指标。",
                },
            ]
        }

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

    def verification(self) -> dict[str, Any]:
        success_packages = [task for task in self.history() if task.get("status") == "succeeded"]
        latest_package = success_packages[0] if success_packages else None
        services, service_status_error = self._runtime_services()
        prometheus_version = next((_version_from_service_status(service) for service in services if service.get("service") == "prometheus"), None)
        if not prometheus_version:
            prometheus_version = _version_from_service_status(self._inspect_service_by_name("prometheus")) or "-"
        return {
            "app_version": self.settings.app_version,
            "runner_version": self.settings.runner_version,
            "prometheus_version": prometheus_version,
            "compose_project": self.settings.compose_project_name,
            "compose_file": self.settings.compose_file,
            "package": {
                "task_id": latest_package.get("task_id"),
                "version": latest_package.get("target_version"),
                "filename": latest_package.get("package_filename"),
                "uploaded_at": latest_package.get("uploaded_at"),
                "finished_at": latest_package.get("finished_at"),
            }
            if latest_package
            else None,
            "service_status_error": service_status_error,
            "services": services,
        }

    def _runtime_services(self) -> tuple[list[dict[str, Any]], str | None]:
        try:
            output = self.executor.output(["docker", "compose", "-f", self.settings.compose_file, "--project-name", self.settings.compose_project_name, "ps", "--format", "json"], cwd=self.project_path)
        except Exception as exc:
            return [], f"Docker 状态读取失败：{exc}"
        services: list[dict[str, Any]] = []
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            service = str(item.get("Service") or item.get("Name") or "")
            container = str(item.get("Name") or item.get("Container") or service)
            if not service:
                continue
            services.append(self._inspect_container(service, container, fallback_status=str(item.get("State") or item.get("Status") or "")))
        return services, None

    def _inspect_service_by_name(self, service: str) -> dict[str, Any]:
        container = f"{self.settings.compose_project_name}-{service}-1"
        return self._inspect_container(service, container)

    def _inspect_container(self, service: str, container: str, *, fallback_status: str = "") -> dict[str, Any]:
        result = {
            "service": service,
            "container": container,
            "status": fallback_status,
            "running": fallback_status == "running",
            "image": "",
            "image_id": "",
            "app_version": None,
            "started_at": None,
            "error": None,
        }
        try:
            output = self.executor.output(["docker", "inspect", container], cwd=self.project_path)
            payload = json.loads(output or "[]")
            inspected = payload[0] if payload else {}
        except Exception as exc:
            result["error"] = str(exc)
            return result
        config = inspected.get("Config") or {}
        state = inspected.get("State") or {}
        env = config.get("Env") or []
        image = str(config.get("Image") or "")
        status = str(state.get("Status") or fallback_status)
        result.update(
            {
                "status": status,
                "running": bool(state.get("Running")) or status == "running",
                "image": image,
                "image_id": str(inspected.get("Image") or ""),
                "app_version": _version_from_env(env) or _version_from_image(image),
                "started_at": state.get("StartedAt"),
            }
        )
        return result

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
            try:
                self.executor.run(["docker", "compose", "-f", self.settings.compose_file, "-f", str(override_path), "--project-name", self.settings.compose_project_name, "up", "-d", "--no-deps", *sorted(_task_services(task["manifest"]))], cwd=self.project_path)
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
            _save_task_file(task_dir, task)
            self.tasks.update_task(task_id, status=TaskStatus.SUCCESS, progress=100, message="升级执行完成", logs=logs, steps=steps)
        except Exception as exc:
            task["status"] = "failed"
            task["error"] = str(exc)
            task["steps"] = steps
            task["logs"] = logs + [str(exc)]
            task["updated_at"] = _now().isoformat()
            _save_task_file(task_dir, task)
            self.tasks.update_task(task_id, status=TaskStatus.FAILED, progress=100, message=str(exc), logs=task["logs"], steps=steps)
            raise
        return self._public_task(task)

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
        _save_task_file(task_dir, task)
        self.tasks.update_task(task_id, status=TaskStatus.SUCCESS, progress=100, message="组件升级执行完成", logs=logs, steps=steps)
        return self._public_task(task)

    def _public_task(self, task: dict[str, Any]) -> dict[str, Any]:
        public = dict(task)
        public["task_id"] = str(task.get("task_id") or "")
        public["status"] = _public_status(str(task.get("status") or ""))
        if task.get("status") == "recovery_required" and task.get("recovery_command") in {"continue", "rollback"}:
            public["status"] = "running"
        public["package_filename"] = task.get("filename") or task.get("package_filename")
        public["uploaded_at"] = task.get("created_at") or task.get("uploaded_at")
        checks = task.get("checks") or []
        public["precheck_ok"] = task.get("status") == "precheck_passed" or (bool(checks) and all(check.get("ok") for check in checks))
        public["checks"] = task.get("checks") or []
        public["steps"] = task.get("steps") or []
        public["logs"] = task.get("logs") or []
        components = set(task.get("components") or [])
        if components <= {"runner"}:
            public["kind"] = "component"
            public["component"] = "upgrade-runner"
        elif components <= {"observability"}:
            public["kind"] = "component"
            public["component"] = "prometheus"
        else:
            public["kind"] = "platform"
            public["component"] = None
        public["ok"] = bool(public["precheck_ok"] or public["status"] in {"succeeded", "running", "pending", "rolled_back"})
        if task.get("status") == "success":
            public.setdefault("finished_at", task.get("updated_at"))
        return public

    def _read_task_or_pending_record(self, task_id: str, task_dir: Path) -> dict[str, Any]:
        try:
            return _read_task_file(task_dir)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
        record = self.tasks.get_task(task_id)
        if not record or record.get("status") != TaskStatus.PENDING.value:
            raise HTTPException(status_code=404, detail="升级任务不存在。")
        return {
            "task_id": task_id,
            "status": "pending",
            "target_version": record.get("message") or "",
            "components": ["platform"],
            "checks": [],
            "steps": [],
            "logs": [],
        }

    def _create_upgrade_backup(self, task: dict[str, Any]) -> Path:
        generated_at = _now()
        version = str(task.get("target_version") or "unknown").replace("/", "-")
        self.settings.backups_dir.mkdir(parents=True, exist_ok=True)
        path = self.settings.backups_dir / f"upgrade-{version}-before-{generated_at.strftime('%Y%m%d%H%M%S')}.tar.gz"
        manifest = {
            "format": "smartx-capacity-insight-v2-upgrade-backup",
            "version": 1,
            "generated_at": generated_at.isoformat(),
            "source_task_id": task.get("task_id"),
            "target_version": task.get("target_version"),
            "components": task.get("components", []),
        }
        with tarfile.open(path, mode="w:gz") as archive:
            _add_json(archive, MANIFEST_NAME, manifest, generated_at)
            if self.settings.sqlite_path.exists():
                archive.add(self.settings.sqlite_path, arcname="app/smartx.db", recursive=False)
            _add_directory(archive, self.settings.prometheus_data_dir, "prometheus", skip_names={"chunks_head", "lock", "queries.active", "wal"})
        return path

    def _sync_project_files(self, task: dict[str, Any]) -> Path | None:
        if not task.get("manifest", {}).get("project_files"):
            return None
        package_project = Path(task["package_path"]) / "project"
        if not package_project.is_dir():
            return None
        version = str(task.get("target_version") or "unknown").replace("/", "-")
        backup_dir = self.settings.backups_dir / f"project-files-before-{version}-{_now().strftime('%Y%m%d%H%M%S')}"
        for source in sorted(package_project.rglob("*")):
            if source.is_dir():
                continue
            relative = source.relative_to(package_project)
            target = self.project_path / relative
            backup = backup_dir / relative
            if target.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        return backup_dir

    def _write_upgrade_override(self, images: list[dict[str, Any]]) -> Path:
        self.settings.compose_runtime_dir.mkdir(parents=True, exist_ok=True)
        path = self.settings.compose_runtime_dir / "docker-compose.upgrade.yml"
        return self._write_override(path, images)

    def _write_runner_override(self, images: list[dict[str, Any]]) -> Path:
        self.settings.compose_runtime_dir.mkdir(parents=True, exist_ok=True)
        path = self.settings.compose_runtime_dir / "docker-compose.runner-upgrade.yml"
        return self._write_override(path, images)

    def _write_task_override(self, manifest: dict[str, Any], images: list[dict[str, Any]]) -> Path:
        if _runner_only(manifest):
            return self._write_runner_override(images)
        return self._write_upgrade_override(images)

    def _write_override(self, path: Path, images: list[dict[str, Any]]) -> Path:
        lines = ["services:"]
        for image in images:
            service = str(image["service"])
            lines.extend([f"  {service}:", f"    image: {image['image']}"])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path


def _validate_members(archive: tarfile.TarFile) -> None:
    for member in archive.getmembers():
        path = Path(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise HTTPException(status_code=400, detail="升级包包含非法路径。")
        lower_parts = {part.lower() for part in path.parts}
        if path.name in SENSITIVE_NAMES or any(part in SENSITIVE_PARTS for part in lower_parts):
            raise HTTPException(status_code=400, detail=f"升级包包含敏感路径：{member.name}")


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise HTTPException(status_code=400, detail="升级包缺少 manifest.json。")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="manifest.json 格式不正确。") from exc
    if manifest.get("schema_version") not in {"2", "3"}:
        raise HTTPException(status_code=400, detail="升级包 schema_version 必须为 2 或 3。")
    return manifest


def _component_types(manifest: dict[str, Any]) -> list[str]:
    return [str(component.get("type")) for component in manifest.get("components") or [] if component.get("type")]


def _check_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    ok = bool(manifest.get("version")) and isinstance(manifest.get("components"), list)
    return {"name": "manifest", "ok": ok, "message": "manifest 格式正确" if ok else "manifest 缺少 version 或 components"}


def _check_protocol(manifest: dict[str, Any]) -> dict[str, Any]:
    try:
        validate_manifest_compatibility(manifest, RUNNER_PROTOCOL_VERSION, RUNNER_CAPABILITIES)
    except (ProtocolValidationError, TypeError, ValueError) as exc:
        return {"name": "runner_protocol", "ok": False, "message": str(exc)}
    return {"name": "runner_protocol", "ok": True, "message": "Runner 协议与能力满足升级包要求"}


def _check_package_checksums(package_path: Path) -> dict[str, Any]:
    checksum_file = package_path / "checksums.sha256"
    if not checksum_file.is_file():
        return {"name": "checksums", "ok": False, "message": "schema 3 升级包缺少 checksums.sha256"}
    try:
        entries = [line.strip().split(maxsplit=1) for line in checksum_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        for digest, relative_value in entries:
            relative = Path(relative_value.strip())
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"校验路径不安全：{relative_value}")
            target = package_path / relative
            if not target.is_file():
                raise ValueError(f"校验文件不存在：{relative_value}")
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual != digest:
                raise ValueError(f"文件校验失败：{relative_value}")
    except (OSError, ValueError) as exc:
        return {"name": "checksums", "ok": False, "message": str(exc)}
    return {"name": "checksums", "ok": True, "message": f"升级包文件校验通过，共 {len(entries)} 项"}


def _check_images(package_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    for component in manifest.get("components") or []:
        for image in component.get("images") or []:
            archive_name = image.get("archive")
            sha256 = image.get("sha256")
            if not image.get("image"):
                return {"name": "images", "ok": False, "message": "镜像声明缺少 image"}
            if not archive_name and not sha256:
                continue
            if not archive_name or not sha256:
                return {"name": "images", "ok": False, "message": "离线镜像声明缺少 archive 或 sha256"}
            image_path = package_path / str(archive_name)
            if not image_path.is_file():
                return {"name": "images", "ok": False, "message": f"镜像文件不存在：{archive_name}"}
            actual = hashlib.sha256(image_path.read_bytes()).hexdigest()
            if actual != sha256:
                return {"name": "images", "ok": False, "message": f"镜像 sha256 不匹配：{archive_name}"}
    return {"name": "images", "ok": True, "message": "镜像声明校验通过；无 archive 的镜像使用仓库引用"}


def _check_project_files(package_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    if not manifest.get("project_files"):
        return {"name": "project_files", "ok": True, "message": "升级包不包含项目文件同步"}
    project_dir = package_path / "project"
    ok = project_dir.is_dir() and (project_dir / "docker-compose.offline.yml").is_file()
    return {"name": "project_files", "ok": ok, "message": "项目文件同步包完整" if ok else "project 文件包缺少 docker-compose.offline.yml"}


def _platform_images(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    for component in manifest.get("components") or []:
        if component.get("type") != "platform":
            continue
        for image in component.get("images") or []:
            if image.get("service") in PLATFORM_SERVICES:
                images.append(dict(image))
    return images


def _platform_services(manifest: dict[str, Any]) -> set[str]:
    services: set[str] = set()
    for component in manifest.get("components") or []:
        if component.get("type") != "platform":
            continue
        for service in component.get("services") or []:
            if service in PLATFORM_SERVICES:
                services.add(str(service))
    if services:
        return services
    return {str(image.get("service")) for image in _platform_images(manifest) if image.get("service") in PLATFORM_SERVICES}


def _observability_images(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    for component in manifest.get("components") or []:
        if component.get("type") != "observability":
            continue
        for image in component.get("images") or []:
            if image.get("service") in OBSERVABILITY_SERVICES:
                images.append(dict(image))
    return images


def _observability_services(manifest: dict[str, Any]) -> set[str]:
    services: set[str] = set()
    for component in manifest.get("components") or []:
        if component.get("type") != "observability":
            continue
        for service in component.get("services") or []:
            if service in OBSERVABILITY_SERVICES:
                services.add(str(service))
    if services:
        return services
    return {str(image.get("service")) for image in _observability_images(manifest) if image.get("service") in OBSERVABILITY_SERVICES}


def _runner_images(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    for component in manifest.get("components") or []:
        if component.get("type") != "runner":
            continue
        for image in component.get("images") or []:
            if image.get("service") in RUNNER_SERVICES:
                images.append(dict(image))
    return images


def _runner_services(manifest: dict[str, Any]) -> set[str]:
    services: set[str] = set()
    for component in manifest.get("components") or []:
        if component.get("type") != "runner":
            continue
        for service in component.get("services") or []:
            if service in RUNNER_SERVICES:
                services.add(str(service))
    if services:
        return services
    return {str(image.get("service")) for image in _runner_images(manifest) if image.get("service") in RUNNER_SERVICES}


def _runner_only(manifest: dict[str, Any]) -> bool:
    components = set(_component_types(manifest))
    return bool(components) and components <= {"runner"}


def _upgrade_images(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return _platform_images(manifest) + _observability_images(manifest)


def _upgrade_services(manifest: dict[str, Any]) -> set[str]:
    return _platform_services(manifest) | _observability_services(manifest)


def _task_images(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if _runner_only(manifest):
        return _runner_images(manifest)
    return _upgrade_images(manifest)


def _task_services(manifest: dict[str, Any]) -> set[str]:
    if _runner_only(manifest):
        return _runner_services(manifest)
    return _upgrade_services(manifest)


def _check_prometheus_permissions(prometheus_dir: Path) -> dict[str, Any]:
    if not prometheus_dir.exists() or not prometheus_dir.is_dir():
        return {"name": "prometheus_permissions", "ok": False, "message": "Prometheus 数据目录不存在。"}
    marker = prometheus_dir / ".smartx-upgrade-precheck"
    try:
        marker.write_text("ok", encoding="utf-8")
        marker.unlink()
    except Exception as exc:
        return {"name": "prometheus_permissions", "ok": False, "message": f"Prometheus 数据目录不可写：{exc}"}
    blocks = [path.name for path in prometheus_dir.iterdir() if path.is_dir() and (path / "meta.json").is_file()]
    return {"name": "prometheus_permissions", "ok": True, "message": f"Prometheus 数据目录可写，历史 block {len(blocks)} 个。"}


def _version_from_env(env: list[Any]) -> str | None:
    for item in env:
        text = str(item)
        if text.startswith("SMARTX_APP_VERSION=") or text.startswith("SMARTX_RUNNER_VERSION="):
            version = text.split("=", 1)[1].strip()
            if version:
                return version
    return None


def _version_from_image(image: str) -> str | None:
    if ":" not in image:
        return None
    tag = image.rsplit(":", 1)[1].strip()
    if not tag or tag == "latest":
        return None
    return tag


def _version_from_service_status(service: dict[str, Any]) -> str | None:
    version = service.get("app_version")
    if isinstance(version, str) and version.strip():
        return version.strip()
    image = service.get("image")
    if isinstance(image, str):
        return _version_from_image(image)
    return None


def _step(key: str, title: str, status: str, message: str = "") -> dict[str, str]:
    return {"key": key, "title": title, "status": status, "message": message}


def _replace_step(steps: list[dict[str, Any]], key: str, status: str, message: str = "") -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for step in steps:
        if step.get("key") == key:
            next_step = dict(step)
            next_step["status"] = status
            if message:
                next_step["message"] = message
            result.append(next_step)
        else:
            result.append(step)
    return result


def _add_json(archive: tarfile.TarFile, arcname: str, payload: dict[str, Any], generated_at: datetime) -> None:
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    info = tarfile.TarInfo(arcname)
    info.size = len(content)
    info.mtime = int(generated_at.timestamp())
    archive.addfile(info, io.BytesIO(content))


def _add_directory(archive: tarfile.TarFile, source: Path, arcname: str, *, skip_names: set[str]) -> None:
    if not source.exists():
        return
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if any(part in skip_names for part in relative.parts):
            continue
        archive.add(path, arcname=str(Path(arcname) / relative), recursive=False)


def _save_task_file(task_dir: Path, task: dict[str, Any]) -> None:
    expected_revision = int(task.get("revision") or 0) if (task_dir / "task.json").is_file() else None
    try:
        saved = TaskStore(task_dir).save(task, expected_revision=expected_revision)
        task["revision"] = saved["revision"]
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail="升级任务状态已变化，请刷新后重试。") from exc


def _read_task_file(task_dir: Path) -> dict[str, Any]:
    path = task_dir / "task.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="升级任务不存在。")
    return TaskStore(task_dir).load()


def _public_status(status: str) -> str:
    return {
        "uploaded": "uploaded",
        "precheck_passed": "prechecked",
        "precheck_failed": "failed",
        "pending": "pending",
        "running": "running",
        "runner_restarting": "running",
        "recovery_required": "recovery_required",
        "rollback_running": "running",
        "rollback_failed": "failed",
        "success": "succeeded",
        "failed": "failed",
        "cancelled": "cancelled",
    }.get(status, status)


def _now() -> datetime:
    return datetime.now(timezone.utc)
