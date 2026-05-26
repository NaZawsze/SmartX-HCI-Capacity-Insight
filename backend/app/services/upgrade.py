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
from typing import Any

from fastapi import HTTPException, UploadFile

from app.core.config import get_settings
from app.services.data_migration import build_migration_archive
from app.services.system_control import _docker_request


PACKAGE_MEDIA_TYPE = "application/gzip"
MANIFEST_NAME = "manifest.json"
TASK_PENDING = "pending"
TASK_RUNNING = "running"
TASK_SUCCESS = "success"
TASK_FAILED = "failed"
TASK_ROLLBACK_READY = "rollback_ready"
TASK_ROLLED_BACK = "rolled_back"
TASK_ROLLBACK_FAILED = "rollback_failed"
ALLOWED_SERVICES = {"web-api", "frontend", "collector-worker", "prometheus"}
IMAGE_SERVICES = {"web-api", "frontend", "collector-worker"}
CORE_VOLUME_MOUNTS = {
    "web-api": {"smartx-data:/data", "prometheus-data:/prometheus-data"},
    "collector-worker": {"smartx-data:/data"},
    "prometheus": {"prometheus-data:/prometheus"},
}


def current_version() -> dict[str, Any]:
    settings = get_settings()
    return {"version": settings.app_version, "upgrade_path": str(settings.upgrade_path)}


async def upload_upgrade_package(upload: UploadFile) -> dict[str, Any]:
    content = await upload.read()
    if not content:
        raise HTTPException(status_code=400, detail="升级包为空。")
    task_id = uuid.uuid4().hex[:12]
    task_dir = _task_dir(task_id)
    package_path = task_dir / "package.tar.gz"
    extract_dir = task_dir / "package"
    task_dir.mkdir(parents=True, exist_ok=False)
    package_path.write_bytes(content)
    try:
        _safe_extract(package_path, extract_dir)
        manifest = _load_manifest(extract_dir)
        _validate_manifest(manifest, extract_dir)
        _write_task(
            task_id,
            {
                "id": task_id,
                "status": "uploaded",
                "created_at": _now(),
                "updated_at": _now(),
                "package_filename": upload.filename or "upgrade.tar.gz",
                "package_path": str(package_path),
                "package_dir": str(extract_dir),
                "manifest": manifest,
                "steps": _initial_steps(manifest),
                "logs": [f"升级包已上传：{upload.filename or 'upgrade.tar.gz'}"],
            },
        )
    except Exception:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise
    return _public_task(_read_task(task_id))


def precheck_upgrade(task_id: str) -> dict[str, Any]:
    task = _read_task_or_404(task_id)
    task["logs"].append("开始预检查。")
    checks = _run_prechecks(task)
    task["precheck"] = checks
    task["updated_at"] = _now()
    if all(item["ok"] for item in checks):
        task["logs"].append("预检查通过。")
        task["status"] = "ready"
    else:
        task["logs"].append("预检查未通过。")
        task["status"] = "precheck_failed"
    _write_task(task_id, task)
    return _public_task(task)


def start_upgrade(task_id: str) -> dict[str, Any]:
    task = _read_task_or_404(task_id)
    if task.get("status") not in {"ready", "precheck_failed", "uploaded"}:
        raise HTTPException(status_code=400, detail="当前升级任务状态不能开始升级。")
    checks = task.get("precheck") or _run_prechecks(task)
    if not all(item["ok"] for item in checks):
        task["precheck"] = checks
        task["status"] = "precheck_failed"
        task["updated_at"] = _now()
        _write_task(task_id, task)
        raise HTTPException(status_code=400, detail="预检查未通过，不能开始升级。")
    task["status"] = TASK_PENDING
    task["requested_action"] = "upgrade"
    task["updated_at"] = _now()
    task["logs"].append("升级任务已提交，等待 upgrade-runner 执行。")
    _write_task(task_id, task)
    return _public_task(task)


def request_rollback(task_id: str) -> dict[str, Any]:
    task = _read_task_or_404(task_id)
    if task.get("status") not in {TASK_FAILED, TASK_ROLLBACK_READY, TASK_SUCCESS}:
        raise HTTPException(status_code=400, detail="当前升级任务状态不能回滚。")
    if not task.get("rollback"):
        raise HTTPException(status_code=400, detail="没有可用的回滚信息。")
    task["status"] = TASK_PENDING
    task["requested_action"] = "rollback"
    task["updated_at"] = _now()
    task["logs"].append("回滚任务已提交，等待 upgrade-runner 执行。")
    _write_task(task_id, task)
    return _public_task(task)


def upgrade_status(task_id: str) -> dict[str, Any]:
    return _public_task(_read_task_or_404(task_id))


def upgrade_history() -> list[dict[str, Any]]:
    root = get_settings().upgrade_path / "tasks"
    if not root.exists():
        return []
    tasks: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/task.json"), reverse=True):
        try:
            tasks.append(_public_task(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return tasks[:30]


def runner_once() -> bool:
    root = get_settings().upgrade_path / "tasks"
    if not root.exists():
        return False
    for task_file in sorted(root.glob("*/task.json")):
        task = json.loads(task_file.read_text(encoding="utf-8"))
        if task.get("status") == TASK_PENDING:
            action = task.get("requested_action")
            if action == "rollback":
                _execute_rollback(task)
            else:
                _execute_upgrade(task)
            return True
    return False


def runner_loop(interval_seconds: float = 2.0) -> None:
    while True:
        try:
            runner_once()
        except Exception:
            pass
        time.sleep(interval_seconds)


def _execute_upgrade(task: dict[str, Any]) -> None:
    task_id = task["id"]
    try:
        _mark_running(task, "upgrade")
        _set_step(task, "backup", "running")
        backup_file = _create_backup(task)
        task.setdefault("rollback", {})["backup_file"] = backup_file
        _set_step(task, "backup", "success")
        _persist(task)

        _set_step(task, "load_images", "running")
        _load_images(task)
        _set_step(task, "load_images", "success")
        _persist(task)

        _set_step(task, "update_services", "running")
        _write_compose_override(task)
        _compose_up(task)
        _set_step(task, "update_services", "success")
        _persist(task)

        if _manifest(task).get("database_migration") or (Path(task["package_dir"]) / "scripts" / "migrate.sh").exists():
            _set_step(task, "migrate", "running")
            _run_migration_script(task)
            _set_step(task, "migrate", "success")
        else:
            _set_step(task, "migrate", "skipped")
        _persist(task)

        _set_step(task, "healthcheck", "running")
        _healthcheck(task)
        _set_step(task, "healthcheck", "success")
        task["status"] = TASK_SUCCESS
        task["updated_at"] = _now()
        task["logs"].append("升级完成。")
        _persist(task)
    except Exception as exc:
        task["status"] = TASK_FAILED
        task["updated_at"] = _now()
        task["logs"].append(f"升级失败：{exc}")
        for step in task.get("steps", []):
            if step.get("status") == "running":
                step["status"] = "failed"
        _write_task(task_id, task)


def _execute_rollback(task: dict[str, Any]) -> None:
    try:
        _mark_running(task, "rollback")
        rollback = task.get("rollback") or {}
        override = rollback.get("compose_override")
        if override and Path(override).exists():
            shutil.copy2(override, _compose_override_path())
            task["logs"].append("已恢复升级前镜像配置。")
        _compose_up(task)
        _healthcheck(task)
        task["status"] = TASK_ROLLED_BACK
        task["updated_at"] = _now()
        task["logs"].append("回滚完成。")
        _persist(task)
    except Exception as exc:
        task["status"] = TASK_ROLLBACK_FAILED
        task["updated_at"] = _now()
        task["logs"].append(f"回滚失败：{exc}")
        _persist(task)


def _create_backup(task: dict[str, Any]) -> str:
    settings = get_settings()
    settings.backup_path.mkdir(parents=True, exist_ok=True)
    version = str(_manifest(task).get("version") or "unknown").replace("/", "-")
    filename = f"upgrade-{version}-before-{datetime.now().strftime('%Y%m%d%H%M%S')}.tar.gz"
    content, _ = build_migration_archive()
    target = settings.backup_path / filename
    target.write_bytes(content)
    task["logs"].append(f"升级前备份已生成：{target}")
    return str(target)


def _load_images(task: dict[str, Any]) -> None:
    package_dir = Path(task["package_dir"])
    for image in _manifest(task).get("images", []):
        file_path = package_dir / str(image.get("file") or "")
        _run(["docker", "load", "-i", str(file_path)], task)
        task["logs"].append(f"镜像已加载：{image.get('image')}")


def _write_compose_override(task: dict[str, Any]) -> None:
    path = _compose_override_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    before = get_settings().upgrade_path / "tasks" / task["id"] / "compose.override.before.yml"
    if path.exists() and not before.exists():
        shutil.copy2(path, before)
        task.setdefault("rollback", {})["compose_override"] = str(before)
    images = {item["service"]: item["image"] for item in _manifest(task).get("images", []) if item.get("service") in IMAGE_SERVICES}
    lines = ["services:"]
    for service, image in images.items():
        lines.extend([f"  {service}:", f"    image: {image}"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    task["logs"].append(f"已写入镜像覆盖配置：{path}")


def _compose_up(task: dict[str, Any]) -> None:
    services = [item["service"] for item in _manifest(task).get("images", []) if item.get("service") in IMAGE_SERVICES]
    if not services:
        services = ["web-api", "frontend", "collector-worker"]
    cmd = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.upgrade.yml", "up", "-d", "--no-build", *services]
    _run(cmd, task, cwd=get_settings().project_path)


def _run_migration_script(task: dict[str, Any]) -> None:
    script = Path(task["package_dir"]) / "scripts" / "migrate.sh"
    if not script.exists():
        task["logs"].append("未提供迁移脚本，跳过。")
        return
    script.chmod(0o750)
    _run(["/bin/sh", str(script)], task, cwd=get_settings().project_path)


def _healthcheck(task: dict[str, Any]) -> None:
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            result = subprocess.run(
                ["python", "-c", "import urllib.request; urllib.request.urlopen('http://web-api:8000/metrics', timeout=3).read()"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                task["logs"].append("健康检查通过。")
                return
        except Exception:
            pass
        time.sleep(3)
    raise RuntimeError("健康检查超时。")


def _run(cmd: list[str], task: dict[str, Any], cwd: Path | None = None) -> None:
    task["logs"].append("$ " + " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=600)
    if result.stdout:
        task["logs"].extend(result.stdout.rstrip().splitlines()[-80:])
    if result.returncode != 0:
        raise RuntimeError(f"命令执行失败：{' '.join(cmd)}")


def _run_prechecks(task: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    manifest = _manifest(task)
    package_dir = Path(task["package_dir"])
    checks.append(_check("版本信息", bool(manifest.get("version")), f"目标版本：{manifest.get('version') or '-'}"))
    checks.append(_check("服务范围", _services_are_allowed(manifest), "只允许更新 web-api、frontend、collector-worker、prometheus。"))
    checks.append(_check("镜像校验", _hashes_match(manifest, package_dir), "镜像文件 sha256 校验。"))
    checks.append(_check("Docker 可用", _docker_available(), "Docker socket 可访问。"))
    checks.append(_check("磁盘空间", _disk_ok(package_dir), "升级目录可用空间充足。"))
    checks.append(_check("Volume 安全", _compose_volume_safe(), "核心 volume 名称和挂载路径保持不变。"))
    return checks


def _services_are_allowed(manifest: dict[str, Any]) -> bool:
    services = {item.get("service") for item in manifest.get("images", [])}
    restart_services = set(manifest.get("restart_services") or [])
    return bool(services) and services <= ALLOWED_SERVICES and restart_services <= ALLOWED_SERVICES


def _hashes_match(manifest: dict[str, Any], package_dir: Path) -> bool:
    for image in manifest.get("images", []):
        file_path = package_dir / str(image.get("file") or "")
        expected = str(image.get("sha256") or "")
        if not file_path.exists() or not expected:
            return False
        if _sha256(file_path) != expected.lower():
            return False
    return True


def _docker_available() -> bool:
    try:
        status, body = _docker_request("GET", "/_ping")
        return status == 200 and body.strip() == b"OK"
    except OSError:
        return False


def _disk_ok(path: Path) -> bool:
    usage = shutil.disk_usage(path)
    package_size = sum(file.stat().st_size for file in path.rglob("*") if file.is_file())
    return usage.free > max(package_size * 3, 1024 * 1024 * 1024)


def _compose_volume_safe() -> bool:
    compose = get_settings().project_path / "docker-compose.yml"
    if not compose.exists():
        return False
    text = compose.read_text(encoding="utf-8")
    for mounts in CORE_VOLUME_MOUNTS.values():
        for mount in mounts:
            if mount not in text:
                return False
    return "down -v" not in text


def _validate_manifest(manifest: dict[str, Any], package_dir: Path) -> None:
    if manifest.get("product") not in {None, "smartx-storage-forecast"}:
        raise HTTPException(status_code=400, detail="升级包产品类型不匹配。")
    if not manifest.get("version"):
        raise HTTPException(status_code=400, detail="升级包缺少版本号。")
    if not isinstance(manifest.get("images"), list) or not manifest["images"]:
        raise HTTPException(status_code=400, detail="升级包缺少镜像列表。")
    for image in manifest["images"]:
        if image.get("service") not in IMAGE_SERVICES:
            raise HTTPException(status_code=400, detail="升级包包含不支持的服务。")
        if not image.get("file") or not image.get("image") or not image.get("sha256"):
            raise HTTPException(status_code=400, detail="镜像条目缺少 file、image 或 sha256。")
        file_path = package_dir / str(image["file"])
        if not file_path.exists():
            raise HTTPException(status_code=400, detail=f"镜像文件不存在：{image['file']}")


def _safe_extract(package_path: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(package_path, "r:gz") as archive:
            for member in archive.getmembers():
                member_path = Path(member.name)
                if member.issym() or member.islnk() or member_path.is_absolute() or ".." in member_path.parts:
                    raise HTTPException(status_code=400, detail="升级包包含非法路径或链接。")
            archive.extractall(target)
    except tarfile.TarError as exc:
        raise HTTPException(status_code=400, detail=f"无法读取升级包：{exc}") from exc


def _load_manifest(package_dir: Path) -> dict[str, Any]:
    path = package_dir / MANIFEST_NAME
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="升级包缺少有效 manifest.json。") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check(name: str, ok: bool, message: str) -> dict[str, Any]:
    return {"name": name, "ok": ok, "message": message}


def _initial_steps(manifest: dict[str, Any]) -> list[dict[str, str]]:
    steps = [
        {"key": "backup", "label": "创建升级前备份", "status": "pending"},
        {"key": "load_images", "label": "加载 Docker 镜像", "status": "pending"},
        {"key": "update_services", "label": "更新并重启服务", "status": "pending"},
        {"key": "migrate", "label": "执行数据库迁移", "status": "pending" if manifest.get("database_migration") else "skipped"},
        {"key": "healthcheck", "label": "健康检查", "status": "pending"},
    ]
    return steps


def _set_step(task: dict[str, Any], key: str, status: str) -> None:
    for step in task.get("steps", []):
        if step.get("key") == key:
            step["status"] = status
            break
    task["updated_at"] = _now()


def _mark_running(task: dict[str, Any], action: str) -> None:
    task["status"] = TASK_RUNNING
    task["running_action"] = action
    task["updated_at"] = _now()
    task["logs"].append("开始执行" + ("回滚。" if action == "rollback" else "升级。"))
    _persist(task)


def _manifest(task: dict[str, Any]) -> dict[str, Any]:
    return dict(task.get("manifest") or {})


def _public_task(task: dict[str, Any]) -> dict[str, Any]:
    public = dict(task)
    public.pop("package_path", None)
    public.pop("package_dir", None)
    logs = public.get("logs") or []
    public["logs"] = logs[-300:]
    return public


def _task_dir(task_id: str) -> Path:
    safe = "".join(ch for ch in task_id if ch.isalnum() or ch in {"-", "_"})
    if not safe:
        raise HTTPException(status_code=400, detail="任务 ID 不正确。")
    return get_settings().upgrade_path / "tasks" / safe


def _task_file(task_id: str) -> Path:
    return _task_dir(task_id) / "task.json"


def _read_task(task_id: str) -> dict[str, Any]:
    return json.loads(_task_file(task_id).read_text(encoding="utf-8"))


def _read_task_or_404(task_id: str) -> dict[str, Any]:
    try:
        return _read_task(task_id)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="升级任务不存在。") from exc


def _write_task(task_id: str, task: dict[str, Any]) -> None:
    path = _task_file(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _persist(task: dict[str, Any]) -> None:
    _write_task(task["id"], task)


def _compose_override_path() -> Path:
    return get_settings().project_path / "docker-compose.upgrade.yml"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
