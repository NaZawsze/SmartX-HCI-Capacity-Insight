from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from fastapi import HTTPException, UploadFile

from app.core.config import get_settings
from app.services.data_migration import build_migration_archive
from app.services.system_control import _docker_request

PRODUCT_NAME = "smartx-storage-forecast"
COMPONENT_PRODUCT_NAME = "smartx-upgrade-runner"
RUNNER_SERVICE = "upgrade-runner"
TASK_FILE = "task.json"
MANIFEST_NAME = "manifest.json"
ALLOWED_SERVICES = {"web-api", "frontend", "collector-worker", "prometheus", "upgrade-runner"}
CORE_VOLUME_MARKERS = (
    "/data/smartx-capacity-insight-data/app:/data",
    "/data/smartx-capacity-insight-data/prometheus:/prometheus",
)
RUNNING_STATUSES = {"pending", "running", "rollback_pending", "rollback_running"}
UPGRADE_STEPS = (
    ("backup", "生成升级前数据备份"),
    ("load_images", "加载升级镜像"),
    ("write_override", "写入服务镜像覆盖配置"),
    ("migration", "执行数据库迁移脚本"),
    ("restart", "重启升级服务"),
    ("healthcheck", "执行服务健康检查"),
)
ROLLBACK_STEPS = (
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
    check("services", bool(service_names) and service_names.issubset(ALLOWED_SERVICES), f"影响服务：{', '.join(sorted(service_names)) or '-'}。")

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
    content, _ = build_migration_archive()
    backup_path.write_bytes(content)
    task["backup_path"] = str(backup_path)
    return f"备份文件：{backup_path}"


def _load_images(task: dict[str, Any]) -> str:
    package_dir = Path(task["package_dir"])
    loaded = []
    for image in task.get("manifest", {}).get("images") or []:
        image_path = _safe_child(package_dir, str(image["file"]))
        output = _run_command(["docker", "load", "-i", str(image_path)], cwd=package_dir)
        loaded.append(str(image.get("image") or image_path.name))
        _append_log(task, output[-2000:])
    return "已加载镜像：" + ", ".join(loaded)


def _write_compose_override(task: dict[str, Any]) -> str:
    override_path = get_settings().project_path / "docker-compose.upgrade.yml"
    if "previous_override" not in task:
        task["previous_override"] = override_path.read_text(encoding="utf-8") if override_path.exists() else None
    target_version = str(task.get("manifest", {}).get("version") or "")
    lines = ["services:"]
    for item in task.get("manifest", {}).get("images") or []:
        lines.extend([f"  {item['service']}:", f"    image: {item['image']}"])
        if target_version and item["service"] in {"web-api", "collector-worker"}:
            lines.extend(["    environment:", f"      SMARTX_APP_VERSION: \"{target_version}\""])
    override_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"已写入 {override_path}"


def _write_runner_override(task: dict[str, Any]) -> str:
    override_path = get_settings().project_path / "docker-compose.runner-upgrade.yml"
    if "previous_runner_override" not in task:
        task["previous_runner_override"] = override_path.read_text(encoding="utf-8") if override_path.exists() else None
    image = _runner_image_from_manifest(task.get("manifest") or {})
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
    services = [service for service in task.get("manifest", {}).get("restart_services") or [] if service in ALLOWED_SERVICES]
    if not services:
        services = sorted(_manifest_services(task.get("manifest") or {})) or ["web-api", "collector-worker", "frontend"]
    return _run_command(_compose_command() + ["up", "-d", "--no-build", *services], cwd=get_settings().project_path)


def _compose_up_runner(task: dict[str, Any]) -> str:
    return _run_command(_compose_command(runner_override=True) + ["up", "-d", "--no-build", RUNNER_SERVICE], cwd=get_settings().project_path)


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
    command = [*base, "-p", settings.compose_project_name, "-f", str(settings.project_path / settings.compose_file)]
    override_path = settings.project_path / "docker-compose.upgrade.yml"
    if override_path.exists():
        command.extend(["-f", str(override_path)])
    runner_override_path = settings.project_path / "docker-compose.runner-upgrade.yml"
    if runner_override and runner_override_path.exists():
        command.extend(["-f", str(runner_override_path)])
    return command


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
        if service not in ALLOWED_SERVICES:
            raise HTTPException(status_code=400, detail=f"不支持升级服务：{service}。")
        if not image.get("file") or not image.get("image"):
            raise HTTPException(status_code=400, detail="manifest image 缺少 file 或 image。")
        if ".." in str(image.get("file")):
            raise HTTPException(status_code=400, detail="manifest image file 路径不安全。")
    restart_services = manifest.get("restart_services") or [item["service"] for item in images]
    if not isinstance(restart_services, list) or any(service not in ALLOWED_SERVICES for service in restart_services):
        raise HTTPException(status_code=400, detail="manifest restart_services 包含不支持的服务。")


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
        "target_version": manifest.get("version"),
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
        "target_version": manifest.get("version"),
        "release_notes": manifest.get("release_notes"),
        "database_migration": False,
        "restart_services": [RUNNER_SERVICE],
        "checks": task.get("checks") or [],
        "steps": steps,
        "logs": task.get("logs") or [],
        "precheck_ok": bool(task.get("precheck_ok")),
    }
