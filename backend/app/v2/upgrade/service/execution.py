from __future__ import annotations

"""Upgrade execution: start/status/cancel/rollback/recovery and runner sync."""

import json
import shutil
import threading
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

from .constants import RUNNER_NOT_DETECTED
from .runner_presence import RUNNER_PRESENCE_SOURCES, instance_heartbeat_is_fresh, presence_source, task_lease_is_alive


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


# 49-52：升级环境互斥锁。FastAPI 同步 handler 跑在线程池，两个并发 start 可能同时通过
# 扫描再各自写状态；锁内完成「扫描 + 认领落盘」消除竞态窗口（锁不罩长耗时执行本体）。
_UPGRADE_ENV_LOCK = threading.Lock()

# 49-52：这些状态说明升级环境正在被改动或等待恢复，必须与其它升级/清理/回滚互斥。
# precheck_passed 不在集合内：允许多个包同时预检通过待命。
_ACTIVE_UPGRADE_STATUSES = frozenset({
    "pending",
    "running",
    "runner_restarting",
    "recovery_required",
    "rollback_pending",
    "rollback_running",
})


class ExecutionMixin:
    def _ensure_no_active_upgrade(self, exclude_task_id: str) -> None:
        """49-52：单飞守卫——已有升级在执行/待恢复时禁止开始新的升级动作。

        平台升级 /api/admin/upgrade/start 与组件升级 /api/admin/component-upgrade/start
        共用 start()，一处守卫覆盖两个入口；rollback、recovery、post-cleanup retry 复用本守卫。
        直接改 task.json 绕过 API 不属于产品流程，不设防。
        """
        for task_file in sorted(self.settings.upgrades_dir.glob("*/task.json")):
            if task_file.parent.name == exclude_task_id:
                continue
            try:
                other = json.loads(task_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if str(other.get("status") or "") in _ACTIVE_UPGRADE_STATUSES:
                raise HTTPException(
                    status_code=400,
                    detail=f"升级任务 {task_file.parent.name} 正在执行或需要恢复，不能开始新的升级。",
                )

    def _resolve_field_runner_image(self, manifest: dict[str, Any]) -> str:
        """US-26：解析现场正在运行的 runner 镜像，供 handoff 动作使用。

        平台包对 runner 只有「基线声明」（deploy:False），不是部署指令。若直接下发包内
        基线 tag，现场已升级到更高版本的 runner 会被静默降级（实测 v0.3.2 → v0.3.1）。
        这里在编译前把 runner 条目的 image 换成现场实际镜像；取不到时返回空串，由调用方
        保留包内基线（= 现状，不会更坏）。不修改 runner 行为，兼容已发布 runner。
        """
        try:
            inspected = self.executor.output(
                ["docker", "inspect", "--format", "{{.Config.Image}}", f"{self.settings.compose_project_name}-upgrade-runner-1"]
            )
        except Exception:
            return ""
        image = str(inspected or "").strip().splitlines()
        return image[0].strip() if image else ""

    def _inject_field_runner_image(self, manifest: dict[str, Any]) -> dict[str, Any]:
        """把现场 runner 镜像写回 manifest 副本的 runner 条目（不改动原 manifest 语义）。"""
        field_image = self._resolve_field_runner_image(manifest)
        if not field_image:
            return manifest
        updated = dict(manifest)
        components = []
        touched = False
        for component in manifest.get("components") or []:
            images = []
            for image in component.get("images") or []:
                if image.get("service") == "upgrade-runner" and image.get("image") != field_image:
                    images.append({**image, "image": field_image})
                    touched = True
                else:
                    images.append(image)
            components.append({**component, "images": images})
        if touched:
            updated["components"] = components
        return updated

    def start(self, task_id: str, *, submit_to_runner: bool = False) -> dict[str, Any]:
        task_dir = self.settings.upgrades_dir / task_id
        with _UPGRADE_ENV_LOCK:
            task = _read_task_file(task_dir)
            if task.get("status") != "precheck_passed":
                raise HTTPException(status_code=400, detail="预检查通过后才能开始升级。")
            self._ensure_no_active_upgrade(task_id)
            if submit_to_runner:
                try:
                    # US-26：编译前把现场 runner 镜像注入 manifest，使计划里的 handoff
                    # 携带现场版本而非包内基线，避免降级。取不到则沿用包内基线。
                    plan_manifest = self._inject_field_runner_image(task["manifest"])
                    execution_plan = compile_execution_plan(plan_manifest)
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
            task["status"] = "running"
            task["started_at"] = _now().isoformat()
            task["updated_at"] = _now().isoformat()
            _save_task_file(task_dir, task)
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
        # US-29：人工回滚已下线（2026-09-28 用户决定）。保留路由与实现仅为老客户端兼容，
        # 不再作为产品化操作暴露；UI 已隐藏入口。失败自动回滚路径不受影响。
        return self._set_recovery_command(task_id, "rollback", "已请求 upgrade-runner 执行回滚")


    def task_has_live_runner(self, task_id: str) -> bool:
        """US-25：该任务当前是否真的被某个 runner 持有（有未过期/心跳新鲜的租约）。"""
        return task_lease_is_alive(self.tasks.database, task_id)


    def _residual_legacy_paths(self) -> list[str]:
        """US-27：探测被中断升级可能留下的 legacy 路径残留（只读，不做任何清理）。

        放弃人工回滚后，失败任务的唯一出路是「标记失败 → 再跑一次成功升级，由 post-cleanup
        收尾」。本方法只负责告诉管理员"环境现在脏在哪里"，不代替 post-cleanup 执行清理。

        US-31 注意：本方法在 **web-api 容器内**执行。`/data/backups`、`/data/exports`、
        `/data/compose-runtime` 等是 bind mount 的**容器内挂载点**，容器视角下永远存在
        （且必须存在，删掉会拆掉全机挂载，见 UPG-050）。直接 `Path.exists()` 判定会
        **永远误报残留**，把管理员引向无意义的收尾操作（`.12` 实测：7 个 legacy 宿主路径
        全部已清空，探测却报 5 个"残留"）。

        因此必须把容器内路径翻译成**宿主真实路径**再判断：真正的 legacy 残留（如
        `/opt/smartx-storage-forecast`、`/data/upgrades`）在宿主上本来就不该存在，
        而目标布局目录的宿主路径是 `/data/smartx-storage-forecast/*`，与容器内挂载点路径不同。
        """
        candidates = [
            "/opt/smartx-storage-forecast",
            "/data/smartx-capacity-insight-data",
            "/prometheus-data",
            "/data/upgrades",
            "/data/backups",
            "/data/exports",
            "/data/compose-runtime",
        ]
        found: list[str] = []
        for path in candidates:
            try:
                host_path = self._legacy_residual_host_path(path)
                if host_path.is_dir() or host_path.exists():
                    found.append(path)
            except Exception:  # noqa: BLE001 - 探测异常不应让任务视图报错
                continue
        return found

    def _legacy_residual_host_path(self, container_path: str) -> Path:
        """把 legacy 候选路径换算成宿主路径。

        挂载点路径（`/data/backups`、`/prometheus-data` 等）走 `_container_mount_source` 拿真实
        宿主源路径；非挂载点（`/opt/...`、`/data/upgrades` 等）容器与宿主同路径，直接用。
        拿不到映射时**保守返回容器路径**——宁可多报也不漏报（漏报会让管理员误以为环境干净）。
        """
        try:
            source = self._container_mount_source(container_path)
        except Exception:  # noqa: BLE001 - docker inspect 失败不应让探测整体崩掉
            source = None
        if source:
            return Path(source)
        return Path(container_path)

    def recovery_fail(self, task_id: str) -> dict[str, Any]:
        task_dir = self.settings.upgrades_dir / task_id
        task = _read_task_file(task_dir)
        status = str(task.get("status") or "")
        # US-25：卡在 running 且没有任何 runner 持有租约（runner 崩了/被杀了/卡住了）时，
        # 必须给管理员一条产品化出路，否则 US-23 的单飞守卫会把环境永久锁死。
        stuck_running = status == "running" and not self.task_has_live_runner(task_id)
        if status != "recovery_required" and not stuck_running:
            raise HTTPException(status_code=400, detail="只有等待恢复的升级任务，或已无 runner 持有的执行中任务，可以标记失败。")
        # US-27：标记失败不做任何清理/回滚，必须告诉管理员环境可能半迁移、需要重跑一次升级收尾。
        residual_paths = self._residual_legacy_paths()
        cleanup_required = bool(residual_paths)
        task["status"] = "failed"
        task["recovery_status"] = "failed"
        task["recovery_command"] = "fail"
        task["available_recovery_actions"] = []
        task["cleanup_required"] = cleanup_required
        task["residual_paths"] = residual_paths
        base_error = task.get("error") or (
            "管理员已将执行中断的升级任务标记为失败（runner 已不再持有该任务）。"
            if stuck_running
            else "管理员已将恢复任务标记为失败。"
        )
        if cleanup_required:
            # 追加而非覆盖：保留原失败语义，再补收尾指引
            task["error"] = (
                f"{base_error} 环境可能处于半迁移状态，检测到残留路径：{'、'.join(residual_paths)}。"
                "请重新上传并执行一次完整升级，由升级后清理（post-cleanup）收尾；"
                "在此之前不要开始新的升级任务。"
            )
        else:
            task["error"] = base_error
        task["updated_at"] = _now().isoformat()
        _save_task_file(task_dir, task)
        self.tasks.update_task(task_id, status=TaskStatus.FAILED, progress=100, message=task["error"])
        return self._public_task(task)


    def _set_recovery_command(self, task_id: str, command: str, message: str) -> dict[str, Any]:
        task_dir = self.settings.upgrades_dir / task_id
        task = _read_task_file(task_dir)
        if task.get("status") != "recovery_required":
            raise HTTPException(status_code=400, detail="当前升级任务不需要恢复处理。")
        self._ensure_no_active_upgrade(task_id)
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
        source = presence_source(self.tasks.database, runner_state)
        if runner_state and source:
            runner_state["source"] = source
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
        if not runner_state or runner_state.get("source") not in RUNNER_PRESENCE_SOURCES:
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
        # US-29：人工回滚已下线（2026-09-28 用户决定）。保留实现仅为老客户端/历史任务兼容，
        # 不再作为产品化操作暴露；UI 已隐藏入口。**失败自动回滚路径（execute_task 异常分支）不受影响**。
        task_dir = self.settings.upgrades_dir / task_id
        task = _read_task_file(task_dir)
        if not task.get("started_at"):
            raise HTTPException(status_code=400, detail="升级尚未执行，不能回滚。")
        self._ensure_no_active_upgrade(task_id)
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

            if _runner_only(task["manifest"]):
                # US-32：compose 的 runner tag 回写已移到 runner 侧任务收尾
                # （`actions.reconcile_project_runner_tag`）。此处曾长期调用 web-api 侧同名
                # 逻辑，但 web-api 的 project 目录是只读挂载（`docker-compose.yml` 的 `:ro`），
                # 写入必抛 OSError 并被吞掉 —— US-26 的回写自实现起从未生效过。
                # 保留提醒：不要在此再加回写，容器内无写权限。
                runner_image = next(
                    (str(image.get("image")) for image in images if image.get("service") == "upgrade-runner"),
                    "",
                )
                logs.append(
                    f"runner 组件升级已提交（目标镜像 {runner_image or '未知'}）；"
                    "compose tag 由 runner 在任务收尾时对齐"
                )

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
    """实例心跳是否新鲜（保留为薄封装；runner 在场判定统一走 runner_presence.presence_source）。"""
    return instance_heartbeat_is_fresh(state, now=_now())
