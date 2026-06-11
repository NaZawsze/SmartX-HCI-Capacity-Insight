from __future__ import annotations

import json
import os
import signal
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.upgrade_runner.actions import ActionContext, CommandExecutor, default_handlers
from app.upgrade_runner.engine import UpgradeEngine
from app.upgrade_runner.lease import LeaseManager
from app.upgrade_runner.store import TaskStore


@dataclass
class RunnerSettings:
    database_path: Path
    upgrades_path: Path
    data_path: Path
    backups_path: Path
    compose_runtime_path: Path
    prometheus_path: Path
    project_path: Path
    compose_file: str
    compose_project: str
    runner_version: str = "v0.3.0"
    host_data_path: Path | None = None
    host_backups_path: Path | None = None
    host_compose_runtime_path: Path | None = None
    host_prometheus_path: Path | None = None
    host_project_path: Path | None = None

    @classmethod
    def from_environment(cls) -> "RunnerSettings":
        database_path = Path(os.environ.get("SMARTX_DB_PATH", "/data/smartx.db"))
        project_path = Path(os.environ.get("SMARTX_PROJECT_PATH", "/opt/smartx-storage-forecast"))
        return cls(
            database_path=database_path,
            upgrades_path=Path(os.environ.get("SMARTX_UPGRADES_PATH", "/data/upgrades")),
            data_path=database_path.parent,
            backups_path=Path(os.environ.get("SMARTX_BACKUPS_PATH", "/data/backups")),
            compose_runtime_path=Path(os.environ.get("SMARTX_COMPOSE_RUNTIME_PATH", "/data/compose-runtime")),
            prometheus_path=Path(os.environ.get("SMARTX_PROMETHEUS_DATA_PATH", "/prometheus-data")),
            project_path=project_path,
            compose_file=os.environ.get("SMARTX_COMPOSE_FILE", "docker-compose.offline.yml"),
            compose_project=os.environ.get("SMARTX_COMPOSE_PROJECT_NAME", "smartx-storage-forecast"),
            runner_version=os.environ.get("SMARTX_RUNNER_VERSION", "v0.3.0"),
            host_data_path=Path(os.environ.get("SMARTX_HOST_DATA_PATH", str(database_path.parent))),
            host_backups_path=Path(os.environ.get("SMARTX_HOST_BACKUPS_PATH", "/data/backups")),
            host_compose_runtime_path=Path(os.environ.get("SMARTX_HOST_COMPOSE_RUNTIME_PATH", "/data/compose-runtime")),
            host_prometheus_path=Path(
                os.environ.get("SMARTX_HOST_PROMETHEUS_DATA_PATH", os.environ.get("SMARTX_PROMETHEUS_DATA_PATH", "/prometheus-data"))
            ),
            host_project_path=Path(os.environ.get("SMARTX_HOST_PROJECT_PATH", str(project_path))),
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _replace_step(steps: list[dict[str, Any]], key: str, status: str, message: str = "") -> list[dict[str, Any]]:
    replaced = False
    next_steps: list[dict[str, Any]] = []
    for step in steps:
        if step.get("key") == key:
            copied = dict(step)
            copied["status"] = status
            copied["message"] = message
            next_steps.append(copied)
            replaced = True
        else:
            next_steps.append(dict(step))
    if not replaced:
        next_steps.append({"key": key, "title": key, "status": status, "message": message})
    return next_steps


def _has_unfinished_steps(task: dict[str, Any]) -> bool:
    return any(step.get("status") in {"pending", "running"} for step in task.get("steps") or [])


def _is_runner_component_task(task: dict[str, Any]) -> bool:
    components = {str(component) for component in task.get("components") or []}
    if components:
        return components <= {"runner"}
    manifest_components = {str(component.get("type")) for component in (task.get("manifest") or {}).get("components") or []}
    return bool(manifest_components) and manifest_components <= {"runner"}


def _finish_runner_component_steps(task: dict[str, Any], message: str) -> dict[str, Any]:
    steps = list(task.get("steps") or [])
    steps = _replace_step(steps, "restart", "succeeded", "upgrade-runner 已重新启动")
    steps = _replace_step(steps, "healthcheck", "succeeded", "组件升级健康检查通过")
    updated_at = _now()
    task["status"] = "success"
    task["runner_resume_pending"] = False
    task["updated_at"] = updated_at
    task["finished_at"] = task.get("finished_at") or updated_at
    task["steps"] = steps
    logs = list(task.get("logs") or [])
    if message not in logs:
        logs.append(message)
    task["logs"] = logs
    return task


def _project_task(database_path: Path, task: dict[str, Any]) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    status_map = {
        "success": "success",
        "rolled_back": "success",
        "failed": "failed",
        "rollback_failed": "failed",
        "recovery_required": "failed",
        "running": "running",
        "pending": "pending",
    }
    status = status_map.get(str(task.get("status")), str(task.get("status")))
    progress = 100 if status in {"success", "failed", "cancelled"} else 50 if status == "running" else 1
    message = {
        "success": "升级执行完成",
        "rolled_back": "升级失败，已自动回滚",
        "recovery_required": "升级需要人工恢复处理",
        "rollback_failed": "升级自动回滚失败",
        "failed": str(task.get("error") or "升级执行失败"),
    }.get(str(task.get("status")), "正在执行升级任务")
    actions = task.get("execution_plan", {}).get("actions") or []
    if actions:
        steps = [
            {
                "key": action.get("id"),
                "title": action.get("type"),
                "status": action.get("status"),
                "message": action.get("error") or "",
            }
            for action in actions
        ]
    else:
        steps = list(task.get("steps") or [])
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO tasks (id, type, status, title, progress, message, logs_json, steps_json, severity, created_at, updated_at, finished_at)
            VALUES (?, 'upgrade', ?, '执行系统升级', ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                progress = excluded.progress,
                message = excluded.message,
                logs_json = excluded.logs_json,
                steps_json = excluded.steps_json,
                severity = excluded.severity,
                updated_at = excluded.updated_at,
                finished_at = excluded.finished_at
            """,
            (
                task["task_id"],
                status,
                progress,
                message,
                json.dumps(task.get("logs") or [], ensure_ascii=False),
                json.dumps(steps, ensure_ascii=False),
                "critical" if status == "failed" else "info" if status == "success" else None,
                task.get("created_at") or _now(),
                _now(),
                _now() if status in {"success", "failed"} else None,
            ),
        )


def _heartbeat_until_done(lease: LeaseManager, task_id: str, store: TaskStore, stop: threading.Event) -> None:
    while not stop.wait(5):
        try:
            lease.heartbeat(task_id, revision=int(store.load().get("revision") or 0))
        except Exception:
            return


def run_pending_once(
    settings: RunnerSettings,
    *,
    executor: CommandExecutor | None = None,
    owner: str | None = None,
    handlers: dict[str, Any] | None = None,
) -> int:
    owner_id = owner or f"runner-{uuid.uuid4().hex}"
    lease = LeaseManager(settings.database_path, owner_id)
    lease.update_runner_state(settings.runner_version)
    executed = 0
    settings.upgrades_path.mkdir(parents=True, exist_ok=True)
    for task_file in sorted(settings.upgrades_path.glob("*/task.json"), key=lambda path: path.stat().st_mtime):
        store = TaskStore(task_file.parent)
        task = store.load()
        status = str(task.get("status") or "")
        if status == "success" and _is_runner_component_task(task) and _has_unfinished_steps(task):
            task = _finish_runner_component_steps(task, "upgrade-runner v0.3.0 已重新启动，组件升级完成。")
            result = store.save(task, expected_revision=int(task.get("revision") or 0))
            _project_task(settings.database_path, result)
            executed += 1
            continue
        if status not in {"pending", "running", "runner_restarting", "recovery_required"}:
            continue
        if status == "runner_restarting" and task.get("runner_resume_pending") and not task.get("execution_plan"):
            task = _finish_runner_component_steps(task, "upgrade-runner 已重新启动，组件升级完成。")
            result = store.save(task, expected_revision=int(task.get("revision") or 0))
            _project_task(settings.database_path, result)
            executed += 1
            continue
        recovery_command = task.get("recovery_command")
        if status == "recovery_required" and recovery_command not in {"continue", "rollback"}:
            continue
        if not task.get("execution_plan"):
            continue
        if not lease.acquire(task["task_id"], revision=int(task.get("revision") or 0)):
            continue
        if status == "recovery_required" and recovery_command == "rollback":
            selected_handlers = handlers or default_handlers()
            rollback_handler = selected_handlers.get("rollback.restore")
            if rollback_handler is None:
                task["status"] = "rollback_failed"
                task["error"] = "Runner 不支持 rollback.restore"
            else:
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
                recovery_context = ActionContext(
                    package_path=Path(task["package_path"]),
                    project_path=settings.project_path,
                    data_path=settings.data_path,
                    backups_path=settings.backups_path,
                    compose_runtime_path=settings.compose_runtime_path,
                    prometheus_path=settings.prometheus_path,
                    compose_file=settings.compose_file,
                    compose_project=settings.compose_project,
                    executor=executor or CommandExecutor(),
                    task_id=task["task_id"],
                    target_version=str(task.get("target_version") or "unknown"),
                    host_data_path=settings.host_data_path,
                    host_backups_path=settings.host_backups_path,
                    host_compose_runtime_path=settings.host_compose_runtime_path,
                    host_prometheus_path=settings.host_prometheus_path,
                    host_project_path=settings.host_project_path,
                )
                rollback_action = {
                    "id": "operator-rollback",
                    "type": "rollback.restore",
                    "params": {
                        "backup_path": backup_path,
                        "backup_scope": backup_scope,
                        "project_backup_path": project_backup_path,
                        "project_files": project_files,
                        "override_path": override_path,
                        "services": services,
                    },
                    "checkpoint": {},
                }
                try:
                    task["recovery_result"] = rollback_handler(rollback_action, recovery_context.as_dict())
                    task["status"] = "rolled_back"
                    task["recovery_status"] = "rolled_back"
                    task["available_recovery_actions"] = []
                except Exception as exc:
                    task["status"] = "rollback_failed"
                    task["recovery_status"] = "recovery_required"
                    task["error"] = str(exc)
                    task["available_recovery_actions"] = ["rollback", "fail"]
            task["recovery_command"] = None
            result = store.save(task, expected_revision=int(task.get("revision") or 0))
            _project_task(settings.database_path, result)
            lease.release(task["task_id"])
            executed += 1
            continue
        if status == "recovery_required":
            for action in task["execution_plan"]["actions"]:
                if action.get("status") == "recovery_required":
                    action["status"] = "pending"
            task["status"] = "pending"
            task["recovery_command"] = None
            task = store.save(task, expected_revision=int(task.get("revision") or 0))
        action_context = ActionContext(
            package_path=Path(task["package_path"]),
            project_path=settings.project_path,
            data_path=settings.data_path,
            backups_path=settings.backups_path,
            compose_runtime_path=settings.compose_runtime_path,
            prometheus_path=settings.prometheus_path,
            compose_file=settings.compose_file,
            compose_project=settings.compose_project,
            executor=executor or CommandExecutor(),
            task_id=task["task_id"],
            target_version=str(task.get("target_version") or "unknown"),
            host_data_path=settings.host_data_path,
            host_backups_path=settings.host_backups_path,
            host_compose_runtime_path=settings.host_compose_runtime_path,
            host_prometheus_path=settings.host_prometheus_path,
            host_project_path=settings.host_project_path,
        )
        stop_heartbeat = threading.Event()
        heartbeat = threading.Thread(
            target=_heartbeat_until_done,
            args=(lease, task["task_id"], store, stop_heartbeat),
            daemon=True,
        )
        heartbeat.start()
        try:
            result = UpgradeEngine(
                store,
                handlers=handlers or default_handlers(),
                context=action_context.as_dict(),
            ).run()
            _project_task(settings.database_path, result)
            executed += 1
        finally:
            stop_heartbeat.set()
            heartbeat.join(timeout=1)
            lease.release(task["task_id"])
    return executed


def main() -> None:
    settings = RunnerSettings.from_environment()
    owner = f"runner-{uuid.uuid4().hex}"
    stop = False

    def request_stop(*_: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    while not stop:
        run_pending_once(settings, owner=owner)
        time.sleep(3)


if __name__ == "__main__":
    main()
