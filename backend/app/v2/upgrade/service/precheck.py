from __future__ import annotations

"""Upgrade precheck: manifest/protocol/images/project validation."""

import hashlib
import re
from pathlib import Path
from typing import Any
from app.v2.tasks.models import TaskStatus, TaskType
from app.upgrade_protocol.constants import RUNNER_CAPABILITIES, RUNNER_PROTOCOL_VERSION
from app.upgrade_protocol.validation import ProtocolValidationError, validate_manifest_compatibility

from ._compat import HTTPException, UploadFile

from .fs import _now
from .taskfile import _component_types, _read_task_file, _save_task_file

from .constants import OBSERVABILITY_SERVICES, PLATFORM_COMPOSE_SERVICES, PLATFORM_SERVICES, RUNNER_SERVICES

class PrecheckMixin:
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
            if "platform" in _component_types(manifest):
                checks.append(_check_source_compatibility(manifest, self.settings.app_version))
            if not _runner_only(manifest):
                checks.append(self._check_runner_protocol(manifest))
            checks.append(_check_package_checksums(package_path))
        checks.extend([_check_images_with_executor(package_path, manifest, self.executor), _check_project_files(package_path, manifest)])
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


def _check_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    ok = bool(manifest.get("version")) and isinstance(manifest.get("components"), list)
    return {"name": "manifest", "ok": ok, "message": "manifest 格式正确" if ok else "manifest 缺少 version 或 components"}



def _check_protocol(manifest: dict[str, Any]) -> dict[str, Any]:
    try:
        validate_manifest_compatibility(manifest, RUNNER_PROTOCOL_VERSION, RUNNER_CAPABILITIES)
    except (ProtocolValidationError, TypeError, ValueError) as exc:
        return {"name": "runner_protocol", "ok": False, "message": str(exc)}
    return {"name": "runner_protocol", "ok": True, "message": "Runner 协议与能力满足升级包要求"}



def _check_source_compatibility(manifest: dict[str, Any], current_version: str) -> dict[str, Any]:
    target_version = str(manifest.get("version") or "")
    source_compatibility = manifest.get("source_compatibility") if isinstance(manifest.get("source_compatibility"), dict) else {}
    min_version = str(source_compatibility.get("min_version") or (manifest.get("compatibility") or {}).get("min_platform_version") or manifest.get("min_version") or "")
    max_version = str(source_compatibility.get("max_version_inclusive") or target_version)
    current_tuple = _version_tuple(current_version)
    min_tuple = _version_tuple(min_version)
    max_tuple = _version_tuple(max_version)
    ok = bool(current_version and min_version and target_version and min_tuple <= current_tuple <= max_tuple)
    supported_versions = source_compatibility.get("supported_versions")
    detail = {
        "current_version": current_version,
        "target_version": target_version,
        "min_version": min_version,
        "max_version_inclusive": max_version,
        "supported_versions": supported_versions if isinstance(supported_versions, list) else [],
        "allow_same_version": bool(source_compatibility.get("allow_same_version", True)),
    }
    if ok:
        message = str(source_compatibility.get("message") or f"当前版本 {current_version} 可升级到 {target_version}")
    else:
        message = f"当前版本 {current_version or '-'} 不在升级包兼容范围 {min_version or '-'} 至 {max_version or '-'} 内"
    return {"name": "source_compatibility", "ok": ok, "message": message, "detail": detail}



def _version_tuple(value: str) -> tuple[int, int, int]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", str(value or ""))
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())



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



def _check_images_with_executor(package_path: Path, manifest: dict[str, Any], executor: UpgradeCommandExecutor) -> dict[str, Any]:
    archive_check = _check_images(package_path, manifest)
    if not archive_check["ok"]:
        return archive_check
    for image_name in sorted(_local_image_requirements(package_path, manifest)):
        try:
            executor.run(["docker", "image", "inspect", image_name])
        except Exception:
            return {"name": "images", "ok": False, "message": f"本地 Docker 镜像不存在：{image_name}"}
    return archive_check



def _local_image_requirements(package_path: Path, manifest: dict[str, Any]) -> set[str]:
    images: set[str] = set()
    for component in manifest.get("components") or []:
        for image in component.get("images") or []:
            image_name = str(image.get("image") or "").strip()
            if image_name and not image.get("archive"):
                images.add(image_name)
    if "prometheus" in _platform_services(manifest):
        prometheus_image = _packaged_compose_service_image(package_path, "prometheus")
        if prometheus_image:
            images.add(prometheus_image)
    return images



def _packaged_compose_service_image(package_path: Path, service_name: str) -> str:
    compose_path = package_path / "project" / "docker-compose.offline.yml"
    if not compose_path.is_file():
        return ""
    lines = compose_path.read_text(encoding="utf-8").splitlines()
    in_services = False
    in_service = False
    service_indent = -1
    for raw_line in lines:
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            in_services = stripped == "services:"
            in_service = False
            service_indent = -1
            continue
        if not in_services:
            continue
        if indent == 2 and stripped.endswith(":"):
            current_service = stripped[:-1].strip().strip('"').strip("'")
            in_service = current_service == service_name
            service_indent = indent if in_service else -1
            continue
        if in_service and indent <= service_indent:
            in_service = False
            service_indent = -1
            continue
        if in_service and indent > service_indent and stripped.startswith("image:"):
            return stripped.split(":", 1)[1].strip().strip('"').strip("'")
    return ""



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
            if service in PLATFORM_COMPOSE_SERVICES:
                services.add(str(service))
    if services:
        return services
    return {str(image.get("service")) for image in _platform_images(manifest) if image.get("service") in PLATFORM_COMPOSE_SERVICES}



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



def _runner_bootstrap(manifest: dict[str, Any]) -> dict[str, Any]:
    bootstrap = manifest.get("bootstrap_runner")
    if isinstance(bootstrap, dict) and bootstrap.get("enabled") is True:
        return bootstrap
    return {}



def _runner_bootstrap_target_root(bootstrap: dict[str, Any]) -> Path | None:
    if not bootstrap:
        return None
    raw = str(bootstrap.get("target_root") or "/data/smartx-storage-forecast").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute() or ".." in path.parts or str(path) in {"/", "/data", "/opt"}:
        raise HTTPException(status_code=400, detail=f"Runner bootstrap target_root 不安全：{raw}")
    return path



def _runner_compose_project_name(manifest: dict[str, Any], default: str) -> str:
    bootstrap = _runner_bootstrap(manifest)
    if not bootstrap:
        return default
    return str(bootstrap.get("target_project") or default)



def _runtime_network_name(compose_project_name: str) -> str:
    if compose_project_name == "smartx-hci-capacity-insight":
        return "smartx-hci-capacity-insight-net"
    return f"{compose_project_name}_smartx-net"



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



def _service_from_docker_ps_item(item: dict[str, Any]) -> str:
    label = item.get("Label")
    if isinstance(label, str) and label.strip():
        return label.strip()
    labels = item.get("Labels")
    if isinstance(labels, str):
        for part in labels.split(","):
            key, separator, value = part.partition("=")
            if separator and key.strip() == "com.docker.compose.service" and value.strip():
                return value.strip()
    names = str(item.get("Names") or item.get("Name") or "")
    prefix = "smartx-storage-forecast-"
    suffix = "-1"
    if names.startswith(prefix) and names.endswith(suffix):
        return names[len(prefix) : -len(suffix)]
    return ""
