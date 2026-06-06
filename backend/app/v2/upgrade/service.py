from __future__ import annotations

import hashlib
import io
import json
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_hex
from typing import Any

from fastapi import HTTPException, UploadFile

from app.v2.config import V2Settings
from app.v2.tasks.models import TaskStatus, TaskType
from app.v2.tasks.service import TaskService


MANIFEST_NAME = "manifest.json"
SENSITIVE_NAMES = {".env", "smartx.db"}
SENSITIVE_PARTS = {"backups", "exports", "compose-runtime", "password", "token", "secret"}


class UpgradeService:
    def __init__(self, settings: V2Settings, tasks: TaskService) -> None:
        self.settings = settings
        self.tasks = tasks

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
                archive.extractall(package_path)
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
        return task

    def precheck(self, task_id: str) -> dict[str, Any]:
        task_dir = self.settings.upgrades_dir / task_id
        task = _read_task_file(task_dir)
        package_path = Path(task["package_path"])
        manifest = task["manifest"]
        checks = [
            _check_manifest(manifest),
            {"name": "paths", "ok": True, "message": "包内路径安全"},
            _check_images(package_path, manifest),
            _check_project_files(package_path, manifest),
        ]
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
        return {"ok": task["status"] == "precheck_passed", "task_id": task_id, "checks": checks, "components": task.get("components", [])}


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
    if manifest.get("schema_version") != "2":
        raise HTTPException(status_code=400, detail="升级包 schema_version 必须为 2。")
    return manifest


def _component_types(manifest: dict[str, Any]) -> list[str]:
    return [str(component.get("type")) for component in manifest.get("components") or [] if component.get("type")]


def _check_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    ok = bool(manifest.get("version")) and isinstance(manifest.get("components"), list)
    return {"name": "manifest", "ok": ok, "message": "manifest 格式正确" if ok else "manifest 缺少 version 或 components"}


def _check_images(package_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    for component in manifest.get("components") or []:
        for image in component.get("images") or []:
            archive_name = image.get("archive")
            sha256 = image.get("sha256")
            if not archive_name or not sha256:
                return {"name": "images", "ok": False, "message": "镜像声明缺少 archive 或 sha256"}
            image_path = package_path / str(archive_name)
            if not image_path.is_file():
                return {"name": "images", "ok": False, "message": f"镜像文件不存在：{archive_name}"}
            actual = hashlib.sha256(image_path.read_bytes()).hexdigest()
            if actual != sha256:
                return {"name": "images", "ok": False, "message": f"镜像 sha256 不匹配：{archive_name}"}
    return {"name": "images", "ok": True, "message": "镜像文件和 sha256 校验通过"}


def _check_project_files(package_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    if not manifest.get("project_files"):
        return {"name": "project_files", "ok": True, "message": "升级包不包含项目文件同步"}
    project_dir = package_path / "project"
    ok = project_dir.is_dir() and (project_dir / "docker-compose.offline.yml").is_file()
    return {"name": "project_files", "ok": ok, "message": "项目文件同步包完整" if ok else "project 文件包缺少 docker-compose.offline.yml"}


def _save_task_file(task_dir: Path, task: dict[str, Any]) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.json").write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_task_file(task_dir: Path) -> dict[str, Any]:
    path = task_dir / "task.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="升级任务不存在。")
    return json.loads(path.read_text(encoding="utf-8"))


def _now() -> datetime:
    return datetime.now(timezone.utc)
