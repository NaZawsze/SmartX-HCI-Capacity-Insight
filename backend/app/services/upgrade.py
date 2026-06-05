from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import quote
from urllib.request import Request, urlopen

from fastapi import HTTPException, UploadFile

from app.core.config import get_settings
from app.services.data_migration import APP_DATA_DIR, MANIFEST_NAME as MIGRATION_MANIFEST_NAME, PROMETHEUS_DATA_DIR
from app.services.system_control import _docker_request

PRODUCT_NAME = "smartx-storage-forecast"
COMPONENT_PRODUCT_NAME = "smartx-upgrade-runner"
RUNNER_SERVICE = "upgrade-runner"
TASK_FILE = "task.json"
MANIFEST_NAME = "manifest.json"
ALLOWED_SERVICES = {"web-api", "frontend", "collector-worker", "prometheus", "upgrade-runner"}
PLATFORM_PACKAGE_SERVICES = {"web-api", "frontend", "collector-worker"}
CORE_VOLUME_MARKERS = (
    "/data/smartx-capacity-insight-data/app:/data",
    "/data/smartx-capacity-insight-data/prometheus:/prometheus",
)
EXPECTED_NETWORK_SUBNET = "10.249.249.0/24"
RUNNING_STATUSES = {"pending", "running", "rollback_pending", "rollback_running"}
APP_BACKUP_SKIP_NAMES = {"backups", "upgrades", "exports", "compose-runtime", "migration-tasks", "__pycache__"}
PROMETHEUS_BACKUP_SKIP_NAMES = {"chunks_head", "lock", "queries.active", "wal"}
PLATFORM_RESTART_SERVICES = {"web-api", "collector-worker", "frontend"}
UPGRADE_STEPS = (
    ("backup", "生成升级前数据备份"),
    ("load_images", "加载升级镜像"),
    ("project_files", "同步项目文件"),
    ("write_override", "写入服务镜像覆盖配置"),
    ("migration", "执行数据库迁移脚本"),
    ("restart", "重启升级服务"),
    ("healthcheck", "执行服务健康检查"),
)
ROLLBACK_STEPS = (
    ("rollback_project_files", "恢复升级前项目文件"),
    ("rollback_config", "恢复升级前镜像配置"),
    ("rollback_restart", "重启回滚服务"),
    ("rollback_healthcheck", "执行回滚健康检查"),
)
COMPONENT_STEPS = (
    ("load_images", "加载组件镜像"),
    ("write_override", "写入组件镜像覆盖配置"),
    ("restart", "重启升级中心组件"),
    ("healthcheck", "检查组件运行状态"),
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def upload_upgrade_package(upload: UploadFile) -> dict[str, Any]:
    filename = upload.filename or "upgrade.tar.gz"
    if not (filename.endswith(".tar.gz") or filename.endswith(".tgz")):
        raise HTTPException(status_code=400, detail="请上传 .tar.gz 升级包。")

    task_id = uuid.uuid4().hex
    task_dir = _task_dir(task_id)
    package_dir = task_dir / "package"
    package_path = task_dir / "upload.tar.gz"
    task_dir.mkdir(parents=True, exist_ok=False)
    package_dir.mkdir(parents=True, exist_ok=True)

    try:
        with package_path.open("wb") as target:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
        if package_path.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="升级包为空。")
        _extract_safe(package_path, package_dir)
        manifest = _read_manifest(package_dir / MANIFEST_NAME)
        _validate_manifest_shape(manifest)
    except HTTPException:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"无法解析升级包：{exc}") from exc

    task = {
        "task_id": task_id,
        "status": "uploaded",
        "uploaded_at": now_iso(),
        "updated_at": now_iso(),
        "package_filename": filename,
        "package_path": str(package_path),
        "package_dir": str(package_dir),
        "manifest": manifest,
        "checks": [],
        "steps": [],
        "logs": [f"升级包已上传：{filename}"],
    }
    _save_task(task)
    return _public_task(task)


async def upload_component_package(upload: UploadFile) -> dict[str, Any]:
    filename = upload.filename or "component-upgrade.tar.gz"
    if not (filename.endswith(".tar.gz") or filename.endswith(".tgz")):
        raise HTTPException(status_code=400, detail="请上传 .tar.gz 组件升级包。")

    task_id = uuid.uuid4().hex
    task_dir = _component_task_dir(task_id)
    package_dir = task_dir / "package"
    package_path = task_dir / "upload.tar.gz"
    task_dir.mkdir(parents=True, exist_ok=False)
    package_dir.mkdir(parents=True, exist_ok=True)

    try:
        with package_path.open("wb") as target:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
        if package_path.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="组件升级包为空。")
        _extract_safe(package_path, package_dir)
        manifest = _read_manifest(package_dir / MANIFEST_NAME)
        _validate_component_manifest_shape(manifest)
    except HTTPException:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"无法解析组件升级包：{exc}") from exc

    task = {
        "task_id": task_id,
        "kind": "component",
        "component": RUNNER_SERVICE,
        "status": "uploaded",
        "uploaded_at": now_iso(),
        "updated_at": now_iso(),
        "package_filename": filename,
        "package_path": str(package_path),
        "package_dir": str(package_dir),
        "manifest": manifest,
        "checks": [],
        "steps": [],
        "logs": [f"组件升级包已上传：{filename}"],
    }
    _save_component_task(task)
    return _public_component_task(task)


def precheck_upgrade(task_id: str) -> dict[str, Any]:
    task = _load_task_or_404(task_id)
    if task.get("status") in RUNNING_STATUSES:
        raise HTTPException(status_code=409, detail="升级任务正在执行，不能重复预检查。")
    manifest = task.get("manifest") or {}
    package_dir = Path(task["package_dir"])
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, message: str, detail: Any | None = None) -> None:
        item: dict[str, Any] = {"name": name, "ok": ok, "message": message}
        if detail is not None:
            item["detail"] = detail
        checks.append(item)

    try:
        _validate_manifest_shape(manifest)
        check("manifest", True, "manifest.json 格式正确。")
    except HTTPException as exc:
        check("manifest", False, str(exc.detail))

    current_version = get_settings().app_version
    target_version = str(manifest.get("version") or "")
    min_version = str(manifest.get("min_version") or "0.0.0")
    check("version", bool(target_version) and _version_gte(current_version, min_version), f"当前版本 {current_version}，目标版本 {target_version or '-'}，最低兼容版本 {min_version}。")

    service_names = _manifest_services(manifest)
    check("services", bool(service_names) and service_names.issubset(PLATFORM_PACKAGE_SERVICES), f"影响服务：{', '.join(sorted(service_names)) or '-'}。平台升级包只允许 web-api、collector-worker、frontend。")

    hash_ok = True
    hash_details: list[str] = []
    for image in manifest.get("images") or []:
        rel_file = str(image.get("file") or "")
        expected = str(image.get("sha256") or "").lower()
        image_path = _safe_child(package_dir, rel_file)
        if not image_path.exists() or not image_path.is_file():
            hash_ok = False
            hash_details.append(f"缺少镜像文件 {rel_file}")
            continue
        actual = _sha256_file(image_path)
        if expected and actual != expected:
            hash_ok = False
            hash_details.append(f"{rel_file} sha256 不匹配")
        else:
            hash_details.append(f"{rel_file} 校验通过")
    check("sha256", hash_ok, "镜像文件 sha256 校验完成。" if hash_ok else "镜像文件 sha256 校验失败。", hash_details)

    try:
        status, body = _docker_request("GET", "/_ping")
        docker_ok = status < 300 and body.strip() == b"OK"
        check("docker", docker_ok, "Docker 控制接口可用。" if docker_ok else "Docker 控制接口不可用。")
    except OSError as exc:
        check("docker", False, "当前环境未挂载 Docker 控制接口。", str(exc))

    check("upgrade-runner", True, "升级执行器镜像包含 Docker CLI，并会负责加载镜像和重启服务。")

    compose_ok, compose_message = _compose_volume_safe()
    check("volumes", compose_ok, compose_message)

    network_ok, network_message, network_detail = _compose_network_safe(package_dir)
    check("network", network_ok, network_message, network_detail)

    image_names_ok, image_names_message, image_names_detail = _image_names_check(manifest)
    check("image-names", image_names_ok, image_names_message, image_names_detail)

    project_ok, project_message, project_detail = _project_files_check(package_dir, manifest)
    check("project-files", project_ok, project_message, project_detail)

    tag_ok, tag_message, tag_detail = _project_compose_tag_check(package_dir, manifest)
    check("compose-tag", tag_ok, tag_message, tag_detail)

    free_ok, free_message = _disk_space_ok(package_dir, manifest)
    check("disk", free_ok, free_message)

    migrate_flag = bool(manifest.get("database_migration"))
    migrate_script = package_dir / "scripts" / "migrate.sh"
    check("migration", not migrate_flag or migrate_script.is_file(), "需要执行迁移脚本。" if migrate_flag else "不需要数据库迁移。")

    ok = all(item["ok"] for item in checks)
    task["checks"] = checks
    task["precheck_ok"] = ok
    task["status"] = "prechecked" if ok else "uploaded"
    task["updated_at"] = now_iso()
    _append_log(task, "预检查通过。" if ok else "预检查未通过，请查看失败项。")
    _save_task(task)
    return _public_task(task)


def precheck_component_upgrade(task_id: str) -> dict[str, Any]:
    task = _load_component_task_or_404(task_id)
    if task.get("status") in RUNNING_STATUSES:
        raise HTTPException(status_code=409, detail="组件升级任务正在执行，不能重复预检查。")
    manifest = task.get("manifest") or {}
    package_dir = Path(task["package_dir"])
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, message: str, detail: Any | None = None) -> None:
        item: dict[str, Any] = {"name": name, "ok": ok, "message": message}
        if detail is not None:
            item["detail"] = detail
        checks.append(item)

    try:
        _validate_component_manifest_shape(manifest)
        check("manifest", True, "组件 manifest.json 格式正确。")
    except HTTPException as exc:
        check("manifest", False, str(exc.detail))

    current_version = runner_version()
    target_version = str(manifest.get("version") or "")
    min_version = str(manifest.get("min_version") or "0.0.0")
    check("version", bool(target_version) and _version_gte(current_version, min_version), f"当前版本 {current_version}，目标版本 {target_version or '-'}，最低兼容版本 {min_version}。")

    platform_running = _has_running_platform_upgrade()
    check("platform-upgrade", not platform_running, "当前没有正在执行的平台升级任务。" if not platform_running else "平台升级任务正在执行，请完成后再升级组件。")

    hash_ok = True
    hash_details: list[str] = []
    for image in manifest.get("images") or []:
        rel_file = str(image.get("file") or "")
        expected = str(image.get("sha256") or "").lower()
        image_path = _safe_child(package_dir, rel_file)
        if not image_path.exists() or not image_path.is_file():
            hash_ok = False
            hash_details.append(f"缺少镜像文件 {rel_file}")
            continue
        actual = _sha256_file(image_path)
        if expected and actual != expected:
            hash_ok = False
            hash_details.append(f"{rel_file} sha256 不匹配")
        else:
            hash_details.append(f"{rel_file} 校验通过")
    check("sha256", hash_ok, "组件镜像文件 sha256 校验完成。" if hash_ok else "组件镜像文件 sha256 校验失败。", hash_details)

    try:
        status, body = _docker_request("GET", "/_ping")
        docker_ok = status < 300 and body.strip() == b"OK"
        check("docker", docker_ok, "Docker 控制接口可用。" if docker_ok else "Docker 控制接口不可用。")
    except OSError as exc:
        check("docker", False, "当前环境未挂载 Docker 控制接口。", str(exc))

    cli_ok, cli_message = _docker_cli_available()
    check("docker-cli", cli_ok, cli_message)

    free_ok, free_message = _disk_space_ok(package_dir, manifest)
    check("disk", free_ok, free_message)

    ok = all(item["ok"] for item in checks)
    task["checks"] = checks
    task["precheck_ok"] = ok
    task["status"] = "prechecked" if ok else "uploaded"
    task["updated_at"] = now_iso()
    _append_log(task, "组件预检查通过。" if ok else "组件预检查未通过，请查看失败项。")
    _save_component_task(task)
    return _public_component_task(task)


def start_upgrade(task_id: str) -> dict[str, Any]:
    task = _load_task_or_404(task_id)
    if not task.get("precheck_ok"):
        raise HTTPException(status_code=400, detail="请先完成并通过预检查。")
    if task.get("status") in RUNNING_STATUSES:
        raise HTTPException(status_code=409, detail="升级任务已经在执行。")
    task["status"] = "pending"
    task["started_at"] = now_iso()
    task["updated_at"] = now_iso()
    _append_log(task, "升级任务已提交，等待 upgrade-runner 执行。")
    _save_task(task)
    return _public_task(task)


def start_component_upgrade(task_id: str) -> dict[str, Any]:
    task = _load_component_task_or_404(task_id)
    if not task.get("precheck_ok"):
        raise HTTPException(status_code=400, detail="请先完成并通过组件预检查。")
    if task.get("status") in RUNNING_STATUSES:
        raise HTTPException(status_code=409, detail="组件升级任务已经在执行。")
    if _has_running_platform_upgrade():
        raise HTTPException(status_code=409, detail="平台升级任务正在执行，请完成后再升级组件。")
    task["status"] = "running"
    task["started_at"] = now_iso()
    _ensure_steps(task, COMPONENT_STEPS)
    task["updated_at"] = now_iso()
    _append_log(task, "组件升级开始，由 web-api 执行。")
    _save_component_task(task)
    _execute_component_upgrade(task)
    return _public_component_task(_load_component_task_or_404(task_id))


def rollback_upgrade(task_id: str) -> dict[str, Any]:
    task = _load_task_or_404(task_id)
    if task.get("status") in RUNNING_STATUSES:
        raise HTTPException(status_code=409, detail="任务正在执行，不能同时回滚。")
    if not task.get("started_at"):
        raise HTTPException(status_code=400, detail="升级尚未开始，不能回滚。")
    task["status"] = "rollback_pending"
    task["rollback_started_at"] = now_iso()
    task["updated_at"] = now_iso()
    _append_log(task, "手动回滚任务已提交。")
    _save_task(task)
    return _public_task(task)


def delete_upgrade_package(task_id: str) -> dict[str, Any]:
    task = _load_task_or_404(task_id)
    if task.get("status") in RUNNING_STATUSES:
        raise HTTPException(status_code=409, detail="升级任务正在执行，不能删除。")
    if task.get("started_at"):
        raise HTTPException(status_code=400, detail="升级已开始，不能删除该升级包记录。")
    shutil.rmtree(_task_dir(task_id), ignore_errors=True)
    return {"ok": True, "task_id": task_id}


def delete_component_package(task_id: str) -> dict[str, Any]:
    task = _load_component_task_or_404(task_id)
    if task.get("status") in RUNNING_STATUSES:
        raise HTTPException(status_code=409, detail="组件升级任务正在执行，不能删除。")
    if task.get("started_at"):
        raise HTTPException(status_code=400, detail="组件升级已开始，不能删除该升级包记录。")
    shutil.rmtree(_component_task_dir(task_id), ignore_errors=True)
    return {"ok": True, "task_id": task_id}


def upgrade_status(task_id: str) -> dict[str, Any]:
    return _public_task(_load_task_or_404(task_id))


def upgrade_history() -> list[dict[str, Any]]:
    tasks = []
    for task_file in sorted(_upgrade_root().glob("*/" + TASK_FILE), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            tasks.append(_public_task(json.loads(task_file.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError):
            continue
    return tasks[:30]


def component_upgrade_status(task_id: str) -> dict[str, Any]:
    return _public_component_task(_load_component_task_or_404(task_id))


def component_upgrade_history() -> list[dict[str, Any]]:
    tasks = []
    for task_file in sorted(_component_upgrade_root().glob("*/" + TASK_FILE), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            tasks.append(_public_component_task(json.loads(task_file.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError):
            continue
    return tasks[:30]


def verification_summary() -> dict[str, Any]:
    settings = get_settings()
    latest_task = _latest_successful_platform_task()
    package = _verification_package(latest_task)
    services = _platform_runtime_services()
    return {
        "app_version": settings.app_version,
        "runner_version": runner_version(),
        "compose_project": settings.compose_project_name,
        "compose_file": settings.compose_file,
        "package": package,
        "services": services,
    }


def runner_loop() -> None:
    while True:
        try:
            runner_once()
        except Exception:
            pass
        time.sleep(2)


def runner_once() -> dict[str, Any] | None:
    for task in _iter_tasks_oldest_first():
        if task.get("status") == "pending":
            _execute_upgrade(task)
            return _public_task(_load_task_or_404(task["task_id"]))
        if task.get("status") == "rollback_pending":
            _execute_rollback(task)
            return _public_task(_load_task_or_404(task["task_id"]))
    return None


def _execute_upgrade(task: dict[str, Any]) -> None:
    task["status"] = "running"
    _ensure_steps(task, UPGRADE_STEPS)
    task["updated_at"] = now_iso()
    _save_task(task)
    try:
        _run_step(task, "backup", "生成升级前数据备份", lambda: _create_backup(task))
        _run_step(task, "load_images", "加载升级镜像", lambda: _load_images(task))
        _run_step(task, "project_files", "同步项目文件", lambda: _sync_project_files(task))
        _run_step(task, "write_override", "写入服务镜像覆盖配置", lambda: _write_compose_override(task))
        _run_step(task, "migration", "执行数据库迁移脚本", lambda: _run_migration_script(task))
        _run_step(task, "restart", "重启升级服务", lambda: _compose_up(task))
        _run_step(task, "healthcheck", "执行服务健康检查", lambda: _healthcheck(task))
        task["status"] = "succeeded"
        task["finished_at"] = now_iso()
        _append_log(task, "升级完成。")
    except Exception as exc:
        task["status"] = "failed"
        task["finished_at"] = now_iso()
        _append_log(task, f"升级失败：{exc}")
    finally:
        task["updated_at"] = now_iso()
        _save_task(task)


def _execute_rollback(task: dict[str, Any]) -> None:
    task["status"] = "rollback_running"
    _ensure_steps(task, ROLLBACK_STEPS)
    task["updated_at"] = now_iso()
    _save_task(task)
    try:
        _run_step(task, "rollback_project_files", "恢复升级前项目文件", lambda: _restore_project_files_backup(task))
        _run_step(task, "rollback_config", "恢复升级前镜像配置", lambda: _restore_previous_override(task))
        _run_step(task, "rollback_restart", "重启回滚服务", lambda: _compose_up(task))
        _run_step(task, "rollback_healthcheck", "执行回滚健康检查", lambda: _healthcheck(task))
        task["status"] = "rolled_back"
        task["rollback_finished_at"] = now_iso()
        _append_log(task, "手动回滚完成。")
    except Exception as exc:
        task["status"] = "rollback_failed"
        task["rollback_finished_at"] = now_iso()
        _append_log(task, f"回滚失败：{exc}")
    finally:
        task["updated_at"] = now_iso()
        _save_task(task)


def _execute_component_upgrade(task: dict[str, Any]) -> None:
    try:
        _run_component_step(task, "load_images", "加载组件镜像", lambda: _load_images(task))
        _run_component_step(task, "write_override", "写入组件镜像覆盖配置", lambda: _write_runner_override(task))
        _run_component_step(task, "restart", "重启升级中心组件", lambda: _compose_up_runner(task))
        _run_component_step(task, "healthcheck", "检查组件运行状态", lambda: _runner_healthcheck())
        task["status"] = "succeeded"
        task["finished_at"] = now_iso()
        _write_runner_version(str(task.get("manifest", {}).get("version") or ""))
        _append_log(task, "组件升级完成。")
    except Exception as exc:
        task["status"] = "failed"
        task["finished_at"] = now_iso()
        _append_log(task, f"组件升级失败：{exc}")
    finally:
        task["updated_at"] = now_iso()
        _save_component_task(task)


def _ensure_steps(task: dict[str, Any], definitions: tuple[tuple[str, str], ...]) -> None:
    steps = task.setdefault("steps", [])
    existing_by_key = {item.get("key"): item for item in steps}
    expected_keys = {key for key, _ in definitions}
    ordered: list[dict[str, Any]] = []
    for key, title in definitions:
        item = existing_by_key.get(key)
        if item is None:
            item = {"key": key, "title": title, "status": "pending"}
        else:
            item.setdefault("title", title)
            item.setdefault("status", "pending")
        ordered.append(item)
    ordered.extend(item for item in steps if item.get("key") not in expected_keys)
    task["steps"] = ordered


def _run_step(task: dict[str, Any], key: str, title: str, action) -> None:
    steps = task.setdefault("steps", [])
    existing = next((item for item in steps if item.get("key") == key), None)
    if existing is None:
        existing = {"key": key, "title": title, "status": "running", "started_at": now_iso()}
        steps.append(existing)
    else:
        existing.update({"status": "running", "started_at": now_iso(), "message": ""})
    _append_log(task, f"开始：{title}")
    _save_task(task)
    try:
        message = action() or "完成"
        existing.update({"status": "succeeded", "finished_at": now_iso(), "message": str(message)})
        _append_log(task, f"完成：{title}。{message}")
        _save_task(task)
    except Exception as exc:
        existing.update({"status": "failed", "finished_at": now_iso(), "message": str(exc)})
        _append_log(task, f"失败：{title}。{exc}")
        _save_task(task)
        raise


def _run_component_step(task: dict[str, Any], key: str, title: str, action) -> None:
    steps = task.setdefault("steps", [])
    existing = next((item for item in steps if item.get("key") == key), None)
    if existing is None:
        existing = {"key": key, "title": title, "status": "running", "started_at": now_iso()}
        steps.append(existing)
    else:
        existing.update({"status": "running", "started_at": now_iso(), "message": ""})
    _append_log(task, f"开始：{title}")
    _save_component_task(task)
    try:
        message = action() or "完成"
        existing.update({"status": "succeeded", "finished_at": now_iso(), "message": str(message)})
        _append_log(task, f"完成：{title}。{message}")
        _save_component_task(task)
    except Exception as exc:
        existing.update({"status": "failed", "finished_at": now_iso(), "message": str(exc)})
        _append_log(task, f"失败：{title}。{exc}")
        _save_component_task(task)
        raise


def _create_backup(task: dict[str, Any]) -> str:
    settings = get_settings()
    settings.backup_path.mkdir(parents=True, exist_ok=True)
    version = _safe_name(str(task.get("manifest", {}).get("version") or "unknown"))
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = settings.backup_path / f"upgrade-{version}-before-{timestamp}.tar.gz"
    manifest = {
        "format": "smartx-storage-forecast-migration",
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "upgrade-before-backup",
        "excluded": {
            APP_DATA_DIR: sorted(APP_BACKUP_SKIP_NAMES),
            PROMETHEUS_DATA_DIR: sorted(PROMETHEUS_BACKUP_SKIP_NAMES),
        },
        "contains": {
            APP_DATA_DIR: settings.data_path.exists(),
            PROMETHEUS_DATA_DIR: settings.prometheus_data_path.exists(),
        },
    }
    _update_step_message(task, "backup", "正在扫描需要备份的数据文件...")
    _save_task(task)
    backup_files = [
        *_iter_backup_files(settings.data_path, APP_DATA_DIR, APP_BACKUP_SKIP_NAMES),
        *_iter_backup_files(settings.prometheus_data_path, PROMETHEUS_DATA_DIR, PROMETHEUS_BACKUP_SKIP_NAMES),
    ]
    total_bytes = sum(item[0].stat().st_size for item in backup_files)
    task["backup_total_files"] = len(backup_files)
    task["backup_total_bytes"] = total_bytes
    _append_log(task, f"备份扫描完成：{len(backup_files)} 个文件，{_format_bytes(total_bytes)}。")
    _update_step_message(task, "backup", f"准备备份 {len(backup_files)} 个文件，共 {_format_bytes(total_bytes)}。")
    _save_task(task)
    progress = _BackupProgress(task)
    _write_upgrade_backup_archive(backup_path, backup_files, manifest, progress)
    progress.finish()
    task["backup_path"] = str(backup_path)
    task["backup_size_bytes"] = backup_path.stat().st_size
    return f"备份文件：{backup_path}，大小：{_format_bytes(backup_path.stat().st_size)}，已排除 upgrades/backups/exports/compose-runtime。"


def _write_upgrade_backup_archive(backup_path: Path, backup_files: list[tuple[Path, str, int]], manifest: dict[str, Any], progress: "_BackupProgress") -> None:
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    temp_path = backup_path.with_suffix(backup_path.suffix + ".tmp")
    temp_path.unlink(missing_ok=True)
    try:
        with tarfile.open(temp_path, mode="w:gz", compresslevel=1) as archive:
            manifest_info = tarfile.TarInfo(MIGRATION_MANIFEST_NAME)
            manifest_info.size = len(manifest_bytes)
            manifest_info.mtime = int(time.time())
            archive.addfile(manifest_info, _BytesReader(manifest_bytes))
            for source, arcname, size in backup_files:
                try:
                    info = archive.gettarinfo(str(source), arcname=arcname)
                    with source.open("rb") as source_file:
                        archive.addfile(info, _ProgressFileReader(source_file, source, arcname, progress))
                except OSError as exc:
                    progress.skip_file(arcname, exc)
                    continue
                progress.finish_file(source, arcname, size)
        temp_path.replace(backup_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _iter_backup_files(source: Path, arcname: str, skip_names: set[str]) -> list[tuple[Path, str, int]]:
    files: list[tuple[Path, str, int]] = []
    if not source.exists():
        return files
    for child in source.rglob("*"):
        try:
            relative = child.relative_to(source)
        except ValueError:
            continue
        if _skip_backup_path(relative, skip_names):
            continue
        if not child.is_file() or child.is_symlink():
            continue
        try:
            size = child.stat().st_size
        except OSError:
            continue
        files.append((child, str(Path(arcname) / relative), size))
    return files


def _skip_backup_path(relative: Path, skip_names: set[str]) -> bool:
    return any(part in skip_names or part == ".DS_Store" or part.startswith("._") for part in relative.parts)


class _BackupProgress:
    def __init__(self, task: dict[str, Any]) -> None:
        self.task = task
        self.total_bytes = int(task.get("backup_total_bytes") or 0)
        self.total_files = int(task.get("backup_total_files") or 0)
        self.processed_bytes = 0
        self.processed_files = 0
        self.last_saved_at = 0.0
        self.last_percent = -1

    def add_bytes(self, source: Path, arcname: str, size: int) -> None:
        if size <= 0:
            return
        self.processed_bytes += size
        self._maybe_save(arcname)

    def finish_file(self, source: Path, arcname: str, size: int) -> None:
        self.processed_files += 1
        self._maybe_save(arcname, force=size == 0)

    def skip_file(self, arcname: str, exc: OSError) -> None:
        message = f"跳过备份文件：{arcname}，原因：{exc}"
        _append_log(self.task, message)
        _update_step_message(self.task, "backup", message)
        _save_task(self.task)

    def _maybe_save(self, arcname: str, force: bool = False) -> None:
        percent = 100 if self.total_bytes <= 0 else min(100, int((self.processed_bytes / self.total_bytes) * 100))
        now = time.monotonic()
        should_save = percent >= 100 or percent >= self.last_percent + 10 or now - self.last_saved_at >= 5
        if not force and not should_save:
            return
        self.last_percent = percent
        self.last_saved_at = now
        message = (
            f"备份中 {percent}%：{self.processed_files}/{self.total_files} 个文件，"
            f"{_format_bytes(self.processed_bytes)}/{_format_bytes(self.total_bytes)}，当前 {arcname}"
        )
        self.task["backup_processed_files"] = self.processed_files
        self.task["backup_processed_bytes"] = self.processed_bytes
        _update_step_message(self.task, "backup", message)
        _append_log(self.task, message)
        _save_task(self.task)

    def finish(self) -> None:
        message = f"备份数据写入完成：{self.processed_files}/{self.total_files} 个文件，{_format_bytes(self.processed_bytes)}。"
        self.task["backup_processed_files"] = self.processed_files
        self.task["backup_processed_bytes"] = self.processed_bytes
        _update_step_message(self.task, "backup", message)
        _append_log(self.task, message)
        _save_task(self.task)


class _ProgressFileReader:
    def __init__(self, handle: BinaryIO, source: Path, arcname: str, progress: _BackupProgress) -> None:
        self.handle = handle
        self.source = source
        self.arcname = arcname
        self.progress = progress

    def read(self, size: int = -1) -> bytes:
        chunk = self.handle.read(size)
        if chunk:
            self.progress.add_bytes(self.source, self.arcname, len(chunk))
        return chunk


class _BytesReader:
    def __init__(self, content: bytes) -> None:
        self._content = content
        self._offset = 0

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self._content) - self._offset
        chunk = self._content[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk


def _format_bytes(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{value} B"


def _load_images(task: dict[str, Any]) -> str:
    package_dir = Path(task["package_dir"])
    loaded = []
    for image in task.get("manifest", {}).get("images") or []:
        image_path = _safe_child(package_dir, str(image["file"]))
        output = _run_command(["docker", "load", "-i", str(image_path)], cwd=package_dir)
        loaded.append(str(image.get("image") or image_path.name))
        _append_log(task, output[-2000:])
    return "已加载镜像：" + ", ".join(loaded)


def _validate_project_file_path(relative: str) -> Path:
    rel = Path(str(relative))
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise HTTPException(status_code=400, detail=f"项目文件路径不安全：{relative}")
    lowered = rel.as_posix().lower()
    blocked_parts = {"data", "backups", "upgrades", "__pycache__"}
    if rel.name == ".env" or any(part.lower() in blocked_parts for part in rel.parts):
        raise HTTPException(status_code=400, detail=f"项目文件路径禁止同步：{relative}")
    if lowered.endswith("smartx.db") or any(word in lowered for word in ("credential", "secret", "password", "tower_password", "access_key", "token")):
        raise HTTPException(status_code=400, detail=f"项目文件路径疑似包含敏感信息：{relative}")
    return rel


def _sync_project_files(task: dict[str, Any]) -> str:
    manifest = task.get("manifest") or {}
    project_files = manifest.get("project_files") or []
    if not project_files:
        raise RuntimeError("升级包缺少 project_files，不能同步项目文件。")
    package_dir = Path(task["package_dir"])
    project_root = get_settings().project_path
    version = _safe_name(str(manifest.get("version") or "unknown"))
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_root = get_settings().backup_path / f"project-files-before-{version}-{timestamp}"
    copied: list[str] = []
    missing_before: list[str] = []
    for item in project_files:
        rel = _validate_project_file_path(str(item))
        source = _safe_child(package_dir / "project", rel.as_posix())
        if not source.is_file():
            raise RuntimeError(f"升级包缺少项目文件：{rel.as_posix()}")
        target = project_root / rel
        if target.exists():
            backup = backup_root / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
        else:
            missing_before.append(rel.as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(rel.as_posix())
    task["project_files_backup_path"] = str(backup_root)
    task["project_files_synced"] = copied
    task["project_files_missing_before"] = missing_before
    return f"已同步项目文件 {len(copied)} 个，备份目录：{backup_root}"


def _restore_project_files_backup(task: dict[str, Any]) -> str:
    backup_value = task.get("project_files_backup_path")
    synced = [str(item) for item in task.get("project_files_synced") or []]
    missing_before = set(str(item) for item in task.get("project_files_missing_before") or [])
    if not backup_value or not synced:
        return "没有需要恢复的项目文件。"
    backup_root = Path(str(backup_value))
    project_root = get_settings().project_path
    restored = 0
    removed = 0
    for item in synced:
        rel = _validate_project_file_path(item)
        target = project_root / rel
        backup = backup_root / rel
        if backup.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
            restored += 1
        elif item in missing_before and target.exists():
            target.unlink()
            removed += 1
    return f"已恢复项目文件 {restored} 个，移除升级新增文件 {removed} 个。"


def _write_compose_override(task: dict[str, Any]) -> str:
    override_path = get_settings().project_path / "docker-compose.upgrade.yml"
    if "previous_override" not in task:
        task["previous_override"] = override_path.read_text(encoding="utf-8") if override_path.exists() else None
    lines = ["services:"]
    for item in task.get("manifest", {}).get("images") or []:
        if item.get("service") not in PLATFORM_RESTART_SERVICES:
            continue
        lines.extend([f"  {item['service']}:", f"    image: {item['image']}"])
    override_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"已写入 {override_path}"


def _write_runner_override(task: dict[str, Any]) -> str:
    override_path = _runner_override_path()
    if "previous_runner_override" not in task:
        task["previous_runner_override"] = override_path.read_text(encoding="utf-8") if override_path.exists() else None
    image = _runner_image_from_manifest(task.get("manifest") or {})
    override_path.parent.mkdir(parents=True, exist_ok=True)
    override_path.write_text(f"services:\n  {RUNNER_SERVICE}:\n    image: {image}\n", encoding="utf-8")
    return f"已写入 {override_path}"


def _run_migration_script(task: dict[str, Any]) -> str:
    if not task.get("manifest", {}).get("database_migration"):
        return "manifest 标记无需数据库迁移。"
    package_dir = Path(task["package_dir"])
    script_path = package_dir / "scripts" / "migrate.sh"
    if not script_path.is_file():
        raise RuntimeError("manifest 标记需要迁移，但 scripts/migrate.sh 不存在。")
    env = os.environ.copy()
    env.update({
        "SMARTX_DATA_PATH": str(get_settings().data_path),
        "SMARTX_PROMETHEUS_DATA_PATH": str(get_settings().prometheus_data_path),
        "SMARTX_PROJECT_PATH": str(get_settings().project_path),
    })
    output = _run_command(["sh", str(script_path)], cwd=package_dir, env=env)
    return output[-2000:] or "迁移脚本执行完成。"


def _compose_up(task: dict[str, Any]) -> str:
    services = [service for service in task.get("manifest", {}).get("restart_services") or [] if service in PLATFORM_RESTART_SERVICES]
    if not services:
        services = sorted(_manifest_services(task.get("manifest") or {}).intersection(PLATFORM_RESTART_SERVICES)) or ["web-api", "collector-worker", "frontend"]
    return _run_command(_compose_command() + ["up", "-d", "--no-build", "--no-deps", *services], cwd=_compose_cwd())


def _compose_up_runner(task: dict[str, Any]) -> str:
    return _run_command(_compose_command(runner_override=True) + ["up", "-d", "--no-build", "--no-deps", RUNNER_SERVICE], cwd=_compose_cwd())


def _healthcheck(task: dict[str, Any]) -> str:
    checks = [("web-api", "http://web-api:8000/metrics"), ("frontend", "http://frontend/")]
    messages = []
    for name, url in checks:
        for attempt in range(1, 31):
            try:
                request = Request(url, headers={"User-Agent": "smartx-upgrade-runner"})
                with urlopen(request, timeout=5) as response:
                    if response.status < 500:
                        messages.append(f"{name} 健康检查通过")
                        break
            except Exception:
                if attempt == 30:
                    raise RuntimeError(f"{name} 健康检查失败：{url}")
                time.sleep(2)
    return "；".join(messages)


def _runner_healthcheck() -> str:
    container = f"{get_settings().compose_project_name}-{RUNNER_SERVICE}-1"
    for attempt in range(1, 31):
        completed = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", container], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        if completed.returncode == 0 and completed.stdout.strip().lower() == "true":
            return f"{RUNNER_SERVICE} 容器运行中"
        if attempt == 30:
            raise RuntimeError(f"{RUNNER_SERVICE} 容器未运行：{completed.stdout[-1000:]}")
        time.sleep(2)


def runner_version() -> str:
    version_file = get_settings().data_path / "upgrade-runner.version"
    if version_file.exists():
        version = version_file.read_text(encoding="utf-8").strip()
        if version:
            return version
    return get_settings().runner_version


def _write_runner_version(version: str) -> None:
    if not version:
        return
    version_file = get_settings().data_path / "upgrade-runner.version"
    version_file.write_text(version, encoding="utf-8")


def _restore_previous_override(task: dict[str, Any]) -> str:
    override_path = get_settings().project_path / "docker-compose.upgrade.yml"
    previous = task.get("previous_override")
    if previous:
        override_path.write_text(previous, encoding="utf-8")
        return f"已恢复 {override_path}"
    if override_path.exists():
        override_path.unlink()
    return "已移除升级镜像覆盖配置。"


def _compose_command(runner_override: bool = False) -> list[str]:
    settings = get_settings()
    base = ["docker", "compose"] if _has_docker_compose_plugin() else ["docker-compose"]
    compose_path = _docker_safe_compose_file(settings.project_path / settings.compose_file)
    command = [*base, "-p", settings.compose_project_name, "-f", str(compose_path)]
    override_path = _docker_safe_compose_file(settings.project_path / "docker-compose.upgrade.yml")
    if override_path.exists():
        command.extend(["-f", str(override_path)])
    runner_override_path = _runner_override_path()
    if runner_override and runner_override_path.exists():
        command.extend(["-f", str(runner_override_path)])
    return command


def _runner_override_path() -> Path:
    return get_settings().runtime_path / "docker-compose.runner-upgrade.yml"


def _compose_cwd() -> Path:
    settings = get_settings()
    if settings.project_path.exists():
        return settings.project_path
    if settings.data_path.exists():
        return settings.data_path
    return Path("/")


def _docker_safe_compose_file(path: Path) -> Path:
    project_path = get_settings().project_path
    safe_project = _docker_safe_project_path()
    try:
        relative = path.relative_to(project_path)
    except ValueError:
        return path
    safe_path = safe_project / relative
    if safe_path == path:
        return path
    if safe_path.exists():
        return safe_path
    if path.exists():
        return _rewrite_compose_for_docker_socket(path, safe_project)
    return safe_path


def _docker_safe_project_path() -> Path:
    settings = get_settings()
    configured = Path(os.environ.get("SMARTX_HOST_PROJECT_PATH") or "") if os.environ.get("SMARTX_HOST_PROJECT_PATH") else None
    if configured and configured.exists():
        return configured
    mount_source = _container_mount_source(str(settings.project_path))
    if mount_source:
        return Path(mount_source)
    return settings.project_path


def _container_mount_source(destination: str) -> str | None:
    try:
        container_id = Path("/etc/hostname").read_text(encoding="utf-8").strip()
        if not container_id:
            return None
        status, body = _docker_request("GET", f"/containers/{container_id}/json")
        if status >= 300:
            return None
        payload = json.loads(body.decode("utf-8") or "{}")
    except Exception:
        return None
    for mount in payload.get("Mounts") or []:
        if mount.get("Destination") == destination and mount.get("Source"):
            return str(mount["Source"])
    return None


def _rewrite_compose_for_docker_socket(path: Path, host_project_path: Path) -> Path:
    target_dir = get_settings().runtime_path
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / path.name
    text = path.read_text(encoding="utf-8")
    container_project = get_settings().project_path.as_posix()
    host_project = host_project_path.as_posix()
    text = text.replace(f"- .:", f"- {host_project}:")
    text = text.replace(f"- ./", f"- {host_project}/")
    text = text.replace(f"  - .env", f"  - {container_project}/.env")
    target.write_text(text, encoding="utf-8")
    return target


def _has_docker_compose_plugin() -> bool:
    return shutil.which("docker") is not None and subprocess.run(["docker", "compose", "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0


def _docker_cli_available() -> tuple[bool, str]:
    if shutil.which("docker") is None:
        return False, "容器内未安装 docker CLI。"
    if _has_docker_compose_plugin():
        return True, "docker compose 可用。"
    if shutil.which("docker-compose") is not None:
        return True, "docker-compose 可用。"
    return False, "未检测到 docker compose 或 docker-compose。"


def _run_command(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(command, cwd=str(cwd), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1800, check=False)
    output = completed.stdout or ""
    if completed.returncode != 0:
        raise RuntimeError(f"命令失败 ({completed.returncode})：{' '.join(command)}\n{output[-4000:]}")
    return output


def _compose_volume_safe() -> tuple[bool, str]:
    settings = get_settings()
    compose_path = settings.project_path / settings.compose_file
    if not compose_path.exists():
        return False, f"找不到 compose 文件：{compose_path}。"
    text = compose_path.read_text(encoding="utf-8")
    missing = [marker for marker in CORE_VOLUME_MARKERS if marker not in text]
    if missing:
        return False, "核心数据目录挂载缺失：" + ", ".join(missing)
    if "down -v" in text:
        return False, "compose 配置中包含禁止的 down -v。"
    return True, "核心数据目录挂载保持安全：/data/smartx-capacity-insight-data/app 和 /data/smartx-capacity-insight-data/prometheus 不会被替换。"


def _compose_network_safe(package_dir: Path) -> tuple[bool, str, list[str]]:
    settings = get_settings()
    current_compose = settings.project_path / settings.compose_file
    target_compose = package_dir / "project" / "docker-compose.offline.yml"
    details = [
        f"当前 compose 文件：{settings.compose_file}",
        f"目标网络网段：{EXPECTED_NETWORK_SUBNET}",
    ]
    ok = True
    for label, path in (("当前 compose", current_compose), ("升级包 offline compose", target_compose)):
        if not path.exists():
            details.append(f"{label} 不存在：{path}")
            ok = False
            continue
        text = path.read_text(encoding="utf-8")
        if EXPECTED_NETWORK_SUBNET not in text:
            details.append(f"{label} 未配置 {EXPECTED_NETWORK_SUBNET}")
            ok = False
        if "172.16." in text or "172.17." in text:
            details.append(f"{label} 包含不允许的 172.16/172.17 网段")
            ok = False
    if ok:
        details.append("compose 网络使用 smartx-net，未发现 172.16/172.17 网段。")
    return ok, "compose 网络网段符合 10.249.249.0/24 规划。" if ok else "compose 网络配置不符合规划。", details


def _image_names_check(manifest: dict[str, Any]) -> tuple[bool, str, list[str]]:
    version = str(manifest.get("version") or "")
    details: list[str] = []
    expected = {
        "web-api": f"nazawsze/smartx-hci-capacity-insight-web-api:{version}",
        "collector-worker": f"nazawsze/smartx-hci-capacity-insight-collector-worker:{version}",
        "frontend": f"nazawsze/smartx-hci-capacity-insight-frontend:{version}",
    }
    ok = True
    unexpected = sorted(_manifest_services(manifest) - PLATFORM_PACKAGE_SERVICES)
    if unexpected:
        details.append("平台升级包不允许包含：" + ", ".join(unexpected))
        ok = False
    for service, image in expected.items():
        actual = next((str(item.get("image") or "") for item in manifest.get("images") or [] if item.get("service") == service), "")
        if not actual:
            details.append(f"{service} 缺少镜像")
            ok = False
            continue
        if actual != image:
            details.append(f"{service} 镜像应为 {image}，实际为 {actual}")
            ok = False
        else:
            details.append(f"{service} 镜像匹配 {version}")
    return ok, "镜像名和目标版本一致。" if ok else "镜像名与目标版本不一致。", details


def _project_files_check(package_dir: Path, manifest: dict[str, Any]) -> tuple[bool, str, list[str]]:
    project_files = manifest.get("project_files")
    details: list[str] = []
    if not isinstance(project_files, list) or not project_files:
        return False, "升级包缺少 project_files，不能同步 compose 和项目文件。", []
    ok = True
    seen: set[str] = set()
    for item in project_files:
        try:
            rel = _validate_project_file_path(str(item))
        except HTTPException as exc:
            details.append(str(exc.detail))
            ok = False
            continue
        if rel.as_posix() in seen:
            details.append(f"重复项目文件：{rel.as_posix()}")
            ok = False
        seen.add(rel.as_posix())
        if not _safe_child(package_dir / "project", rel.as_posix()).is_file():
            details.append(f"缺少 project/{rel.as_posix()}")
            ok = False
    for required in ("docker-compose.offline.yml", "docker-compose.release.yml"):
        if required not in seen:
            details.append(f"缺少 project/{required}")
            ok = False
    if ok:
        details.append(f"包含项目文件同步：{len(seen)} 个白名单文件")
    return ok, "包含项目文件同步。" if ok else "项目文件同步内容不完整或不安全。", details


def _project_compose_tag_check(package_dir: Path, manifest: dict[str, Any]) -> tuple[bool, str, list[str]]:
    version = str(manifest.get("version") or "")
    offline = package_dir / "project" / "docker-compose.offline.yml"
    if not offline.is_file():
        return False, "升级包缺少 offline compose。", []
    text = offline.read_text(encoding="utf-8")
    current_compose = get_settings().project_path / get_settings().compose_file
    current_text = current_compose.read_text(encoding="utf-8") if current_compose.exists() else ""
    details = [
        f"当前 compose 文件：{get_settings().compose_file}",
        f"当前镜像 tag：{_extract_compose_default_tag(current_text) or '-'}",
        f"目标镜像 tag：{version}",
        "包含项目文件同步：是",
        "会更新 offline compose：是",
    ]
    if "SMARTX_IMAGE_TAG:-latest" in text:
        details.append("offline compose 仍默认 latest")
        return False, "offline compose 默认 tag 不能是 latest。", details
    if f"SMARTX_IMAGE_TAG:-{version}" not in text:
        details.append(f"未找到 SMARTX_IMAGE_TAG:-{version}")
        return False, "offline compose 默认 tag 与 manifest version 不一致。", details
    return True, "offline compose 默认 tag 与目标版本一致。", details


def _extract_compose_default_tag(text: str) -> str | None:
    marker = "SMARTX_IMAGE_TAG:-"
    index = text.find(marker)
    if index < 0:
        return None
    rest = text[index + len(marker):]
    return rest.split("}", 1)[0].strip() or None


def _disk_space_ok(package_dir: Path, manifest: dict[str, Any]) -> tuple[bool, str]:
    image_size = 0
    for image in manifest.get("images") or []:
        image_path = _safe_child(package_dir, str(image.get("file") or ""))
        if image_path.exists():
            image_size += image_path.stat().st_size
    usage = shutil.disk_usage(str(get_settings().data_path))
    required = max(image_size * 2, 1024**3)
    return usage.free > required, f"可用空间 {usage.free // 1024**3} GiB，预计至少需要 {required // 1024**3} GiB。"


def _extract_safe(archive_path: Path, target: Path) -> None:
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            for member in archive.getmembers():
                if member.islnk() or member.issym():
                    raise HTTPException(status_code=400, detail="升级包不能包含符号链接或硬链接。")
                _safe_child(target, member.name)
            archive.extractall(target)
    except tarfile.TarError as exc:
        raise HTTPException(status_code=400, detail=f"升级包不是有效的 tar.gz：{exc}") from exc


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise HTTPException(status_code=400, detail="升级包缺少 manifest.json。")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="manifest.json 不是有效 JSON。") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="manifest.json 格式不正确。")
    return payload


def _validate_manifest_shape(manifest: dict[str, Any]) -> None:
    if manifest.get("product") != PRODUCT_NAME:
        raise HTTPException(status_code=400, detail="manifest product 不匹配。")
    if not manifest.get("version"):
        raise HTTPException(status_code=400, detail="manifest 缺少 version。")
    images = manifest.get("images")
    if not isinstance(images, list) or not images:
        raise HTTPException(status_code=400, detail="manifest 缺少 images 列表。")
    for image in images:
        if not isinstance(image, dict):
            raise HTTPException(status_code=400, detail="manifest images 格式不正确。")
        service = image.get("service")
        if service not in PLATFORM_PACKAGE_SERVICES:
            raise HTTPException(status_code=400, detail=f"不支持升级服务：{service}。")
        if not image.get("file") or not image.get("image"):
            raise HTTPException(status_code=400, detail="manifest image 缺少 file 或 image。")
        if ".." in str(image.get("file")):
            raise HTTPException(status_code=400, detail="manifest image file 路径不安全。")
    restart_services = manifest.get("restart_services") or [item["service"] for item in images]
    if not isinstance(restart_services, list) or any(service not in PLATFORM_PACKAGE_SERVICES for service in restart_services):
        raise HTTPException(status_code=400, detail="manifest restart_services 包含不支持的服务。")
    project_files = manifest.get("project_files")
    if not isinstance(project_files, list) or not project_files:
        raise HTTPException(status_code=400, detail="manifest 缺少 project_files。")
    for item in project_files:
        _validate_project_file_path(str(item))


def _validate_component_manifest_shape(manifest: dict[str, Any]) -> None:
    if manifest.get("product") != COMPONENT_PRODUCT_NAME:
        raise HTTPException(status_code=400, detail="组件 manifest product 不匹配。")
    if manifest.get("component") != RUNNER_SERVICE:
        raise HTTPException(status_code=400, detail="组件升级包只支持 upgrade-runner。")
    if not manifest.get("version"):
        raise HTTPException(status_code=400, detail="组件 manifest 缺少 version。")
    images = manifest.get("images")
    if not isinstance(images, list) or len(images) != 1:
        raise HTTPException(status_code=400, detail="组件 manifest 必须且只能包含一个镜像。")
    image = images[0]
    if not isinstance(image, dict):
        raise HTTPException(status_code=400, detail="组件 manifest images 格式不正确。")
    if image.get("service") != RUNNER_SERVICE:
        raise HTTPException(status_code=400, detail="组件升级包只允许升级 upgrade-runner。")
    if not image.get("file") or not image.get("image"):
        raise HTTPException(status_code=400, detail="组件 manifest image 缺少 file 或 image。")
    if ".." in str(image.get("file")):
        raise HTTPException(status_code=400, detail="组件 manifest image file 路径不安全。")
    restart_services = manifest.get("restart_services") or [RUNNER_SERVICE]
    if restart_services != [RUNNER_SERVICE]:
        raise HTTPException(status_code=400, detail="组件 manifest restart_services 只能包含 upgrade-runner。")


def _runner_image_from_manifest(manifest: dict[str, Any]) -> str:
    images = manifest.get("images") or []
    if not images:
        raise RuntimeError("组件 manifest 缺少镜像。")
    image = images[0].get("image")
    if not image:
        raise RuntimeError("组件 manifest image 缺少 image。")
    return str(image)


def _manifest_services(manifest: dict[str, Any]) -> set[str]:
    services = {str(item.get("service")) for item in manifest.get("images") or [] if item.get("service")}
    services.update(str(service) for service in manifest.get("restart_services") or [] if service)
    return services


def _safe_child(base: Path, relative: str) -> Path:
    child = (base / relative).resolve()
    base_resolved = base.resolve()
    if child != base_resolved and base_resolved not in child.parents:
        raise HTTPException(status_code=400, detail="升级包包含不安全路径。")
    return child


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version_tuple(value: str) -> tuple[int, ...]:
    clean = value.strip().lower().lstrip("v")
    parts = []
    for part in clean.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts or [0])


def _version_gte(left: str, right: str) -> bool:
    left_parts = _version_tuple(left)
    right_parts = _version_tuple(right)
    length = max(len(left_parts), len(right_parts))
    return left_parts + (0,) * (length - len(left_parts)) >= right_parts + (0,) * (length - len(right_parts))


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ".-_" else "-" for ch in value).strip(".-") or "unknown"


def _upgrade_root() -> Path:
    root = get_settings().upgrade_path
    root.mkdir(parents=True, exist_ok=True)
    return root


def _component_upgrade_root() -> Path:
    root = get_settings().upgrade_path / "components"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _task_dir(task_id: str) -> Path:
    if not task_id or any(ch not in "0123456789abcdef" for ch in task_id):
        raise HTTPException(status_code=404, detail="升级任务不存在。")
    return _upgrade_root() / task_id


def _component_task_dir(task_id: str) -> Path:
    if not task_id or any(ch not in "0123456789abcdef" for ch in task_id):
        raise HTTPException(status_code=404, detail="组件升级任务不存在。")
    return _component_upgrade_root() / task_id


def _load_task_or_404(task_id: str) -> dict[str, Any]:
    path = _task_dir(task_id) / TASK_FILE
    if not path.exists():
        raise HTTPException(status_code=404, detail="升级任务不存在。")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_component_task_or_404(task_id: str) -> dict[str, Any]:
    path = _component_task_dir(task_id) / TASK_FILE
    if not path.exists():
        raise HTTPException(status_code=404, detail="组件升级任务不存在。")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_task(task: dict[str, Any]) -> None:
    path = _task_dir(task["task_id"]) / TASK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _save_component_task(task: dict[str, Any]) -> None:
    path = _component_task_dir(task["task_id"]) / TASK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _append_log(task: dict[str, Any], message: str) -> None:
    task.setdefault("logs", []).append(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")
    task["logs"] = task["logs"][-500:]


def _update_step_message(task: dict[str, Any], key: str, message: str) -> None:
    for step in task.setdefault("steps", []):
        if step.get("key") == key:
            step["message"] = message
            return
    task.setdefault("steps", []).append({"key": key, "title": key, "status": "running", "message": message})


def _iter_tasks_oldest_first() -> list[dict[str, Any]]:
    tasks = []
    for task_file in _upgrade_root().glob("*/" + TASK_FILE):
        try:
            tasks.append(json.loads(task_file.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(tasks, key=lambda item: item.get("updated_at") or item.get("uploaded_at") or "")


def _has_running_platform_upgrade() -> bool:
    return any(task.get("status") in RUNNING_STATUSES for task in _iter_tasks_oldest_first())


def _latest_successful_platform_task() -> dict[str, Any] | None:
    tasks = [task for task in _iter_tasks_oldest_first() if task.get("status") == "succeeded"]
    if not tasks:
        return None
    return sorted(tasks, key=lambda item: item.get("finished_at") or item.get("updated_at") or item.get("uploaded_at") or "", reverse=True)[0]


def _verification_package(task: dict[str, Any] | None) -> dict[str, Any] | None:
    if task is None:
        return None
    manifest = task.get("manifest") or {}
    image_sha256 = {
        str(image.get("service")): str(image.get("sha256") or "")
        for image in manifest.get("images") or []
        if image.get("service")
    }
    package_sha256 = _task_package_sha256(task)
    return {
        "task_id": task.get("task_id"),
        "version": _display_version(manifest.get("version")),
        "filename": task.get("package_filename"),
        "sha256": package_sha256,
        "image_sha256": image_sha256,
        "uploaded_at": task.get("uploaded_at"),
        "finished_at": task.get("finished_at"),
    }


def _task_package_sha256(task: dict[str, Any]) -> str:
    package_path = task.get("package_path")
    if package_path:
        path = Path(str(package_path))
        if path.is_file():
            return _sha256_file(path)
    return ""


def _platform_runtime_services() -> list[dict[str, Any]]:
    services = ("web-api", "collector-worker", "frontend", "prometheus", RUNNER_SERVICE)
    return [_runtime_service_summary(service) for service in services]


def _runtime_service_summary(service: str) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "service": service,
        "container": f"{get_settings().compose_project_name}-{service}-1",
        "status": "unknown",
        "running": False,
        "image": "-",
        "image_id": "",
        "app_version": None,
        "started_at": None,
        "error": None,
    }
    try:
        container_id = _container_id_for_service(service)
        if not container_id:
            summary["status"] = "missing"
            summary["error"] = "未找到容器"
            return summary
        status, body = _docker_request("GET", f"/containers/{container_id}/json")
        if status >= 300:
            summary["error"] = body.decode("utf-8", errors="ignore") or "读取容器状态失败"
            return summary
        payload = json.loads(body.decode("utf-8") or "{}")
    except Exception as exc:
        summary["error"] = str(exc)
        return summary

    config = payload.get("Config") or {}
    state = payload.get("State") or {}
    summary.update({
        "container": (payload.get("Name") or summary["container"]).lstrip("/"),
        "status": str(state.get("Status") or "unknown"),
        "running": bool(state.get("Running")),
        "image": str(config.get("Image") or payload.get("Image") or "-"),
        "image_id": str(payload.get("Image") or ""),
        "started_at": state.get("StartedAt"),
        "error": state.get("Error") or None,
    })
    if service in {"web-api", "collector-worker", "frontend"}:
        summary["app_version"] = get_settings().app_version
    if service == RUNNER_SERVICE:
        summary["app_version"] = runner_version()
    return summary


def _container_id_for_service(service: str) -> str | None:
    label_filter = {
        "label": [
            f"com.docker.compose.project={get_settings().compose_project_name}",
            f"com.docker.compose.service={service}",
        ]
    }
    filters = quote(json.dumps(label_filter, separators=(",", ":")), safe="")
    status, body = _docker_request("GET", f"/containers/json?all=true&filters={filters}")
    if status >= 300:
        return None
    containers = json.loads(body.decode("utf-8") or "[]")
    if not containers:
        return None
    return str(containers[0].get("Id") or "") or None


def _env_value(env: list[str], key: str) -> str | None:
    prefix = f"{key}="
    for item in env:
        if item.startswith(prefix):
            return item[len(prefix):]
    return None


def _display_version(value: Any) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return normalized if normalized.lower().startswith("v") else f"v{normalized}"


def _public_task(task: dict[str, Any]) -> dict[str, Any]:
    manifest = task.get("manifest") or {}
    steps = task.get("steps") or []
    if task.get("status") in {"pending", "running", "succeeded", "failed"}:
        _ensure_steps(task, UPGRADE_STEPS)
        steps = task.get("steps") or []
    elif task.get("status") in {"rollback_pending", "rollback_running", "rolled_back", "rollback_failed"}:
        _ensure_steps(task, ROLLBACK_STEPS)
        steps = task.get("steps") or []
    return {
        "task_id": task.get("task_id"),
        "status": task.get("status"),
        "uploaded_at": task.get("uploaded_at"),
        "started_at": task.get("started_at"),
        "finished_at": task.get("finished_at"),
        "updated_at": task.get("updated_at"),
        "rollback_started_at": task.get("rollback_started_at"),
        "rollback_finished_at": task.get("rollback_finished_at"),
        "package_filename": task.get("package_filename"),
        "backup_path": task.get("backup_path"),
        "manifest": manifest,
        "target_version": _display_version(manifest.get("version")),
        "release_notes": manifest.get("release_notes"),
        "database_migration": bool(manifest.get("database_migration")),
        "restart_services": manifest.get("restart_services") or sorted(_manifest_services(manifest)),
        "checks": task.get("checks") or [],
        "steps": steps,
        "logs": task.get("logs") or [],
        "precheck_ok": bool(task.get("precheck_ok")),
    }


def _public_component_task(task: dict[str, Any]) -> dict[str, Any]:
    manifest = task.get("manifest") or {}
    steps = task.get("steps") or []
    if task.get("status") in {"running", "succeeded", "failed"}:
        _ensure_steps(task, COMPONENT_STEPS)
        steps = task.get("steps") or []
    return {
        "task_id": task.get("task_id"),
        "kind": "component",
        "component": task.get("component") or manifest.get("component") or RUNNER_SERVICE,
        "status": task.get("status"),
        "uploaded_at": task.get("uploaded_at"),
        "started_at": task.get("started_at"),
        "finished_at": task.get("finished_at"),
        "updated_at": task.get("updated_at"),
        "package_filename": task.get("package_filename"),
        "backup_path": task.get("backup_path"),
        "manifest": manifest,
        "target_version": _display_version(manifest.get("version")),
        "release_notes": manifest.get("release_notes"),
        "database_migration": False,
        "restart_services": [RUNNER_SERVICE],
        "checks": task.get("checks") or [],
        "steps": steps,
        "logs": task.get("logs") or [],
        "precheck_ok": bool(task.get("precheck_ok")),
    }
