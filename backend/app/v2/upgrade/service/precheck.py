from __future__ import annotations

"""Upgrade precheck: manifest/protocol/images/project validation."""

import hashlib
import re
import shutil
from pathlib import Path
from typing import Any, Callable
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
        package_path = Path(task["package_path"]) if task.get("package_path") else None
        if package_path is None or not package_path.exists():
            # US-09：包内容可能已被自动清理（见 upgrade/housekeeping.py），给出可读失败而不是路径异常
            checks = [
                {
                    "name": "package",
                    "ok": False,
                    "message": "升级包内容已被自动清理（超过保留期限），请重新上传后再预检查。",
                }
            ]
            task["checks"] = checks
            task["status"] = "precheck_failed"
            task["updated_at"] = _now().isoformat()
            _save_task_file(task_dir, task)
            self.tasks.create_task(
                task_id,
                TaskType.UPGRADE,
                "升级预检查",
                status=TaskStatus.FAILED,
                progress=100,
                message="预检查失败",
                logs=[check["message"] for check in checks],
            )
            return self._public_task(task)
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
                checks.append(self._check_runner_actions(manifest))
            checks.append(_check_package_checksums(package_path))
            checks.append(
                _check_disk_space(
                    package_path,
                    [self.settings.upgrades_dir, self.settings.backups_dir, Path("/")],
                    self.settings.upgrade_disk_headroom_bytes,
                )
            )
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

    def _check_runner_actions(self, manifest: dict[str, Any]) -> dict[str, Any]:
        """49-50：动作级校验。

        能力级（`_check_runner_protocol`）只比 `required_capabilities`，无法区分「同版本不同能力」的
        runner（已发布 v0.3.1 声明 task.recovery.v1 但不实现 post_upgrade.schedule_collection），
        结果是预检查放行、失败落在 cutover 之后。这里改为：编译计划取动作类型，逐条比对当前 runner 的动作集。
        """
        from app.upgrade_protocol.constants import runner_supported_actions
        from app.v2.upgrade.compiler import compile_execution_plan

        runner_version = str(self._active_runner_version() or "").strip()
        try:
            plan_actions = [
                str(action.get("type") or "")
                for action in compile_execution_plan(manifest).to_dict().get("actions") or []
            ]
        except Exception as exc:  # noqa: BLE001 - 预检查必须给出可读失败原因而不是抛栈
            return {
                "name": "runner_actions",
                "ok": False,
                "message": f"无法编译升级计划以校验 runner 动作：{exc}",
            }
        supported = runner_supported_actions(runner_version)
        if supported is None:
            return {
                "name": "runner_actions",
                "ok": False,
                "message": (
                    f"无法确认 upgrade-runner {runner_version or '(未检测到心跳版本)'} 支持的升级动作，"
                    "至少需要 v0.3.1。请先在升级中心执行「组件升级」把 upgrade-runner 升到 v0.3.3 后重试。"
                ),
                "detail": {"runner_version": runner_version or None, "plan_actions": plan_actions},
            }
        missing = sorted({item for item in plan_actions if item} - supported)
        if missing:
            return {
                "name": "runner_actions",
                "ok": False,
                "message": (
                    f"upgrade-runner {runner_version} 不支持升级计划动作：{', '.join(missing)}。"
                    "请先在升级中心执行「组件升级」把 upgrade-runner 升到 v0.3.3 后重试。"
                ),
                "detail": {
                    "runner_version": runner_version,
                    "missing_actions": missing,
                    "supported_count": len(supported),
                },
            }
        return {
            "name": "runner_actions",
            "ok": True,
            "message": f"升级计划 {len(plan_actions)} 个动作 upgrade-runner {runner_version} 全部支持",
        }


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


# US-07：升级要 docker load 镜像（在 docker 存储里再写一份 ≈ 包内容大小）、写备份、解临时文件；
# 空间不足会在执行中段失败，留下半升级现场。上传时包已解到 <task_dir>/package，镜像 tar 是
# 未压缩的 docker save 归档，所以「目录内文件求和」就是镜像落盘的量级；headroom 覆盖备份与余量。
COMPRESSED_ARCHIVE_EXPANSION = 3


def package_payload_bytes(package_path: Path) -> int:
    """升级包的落盘量级：目录（已解包）取文件求和；直接给压缩包文件时按膨胀系数估。"""
    if not package_path.exists():
        raise FileNotFoundError(f"{package_path} 不存在")
    if package_path.is_file():
        return package_path.stat().st_size * COMPRESSED_ARCHIVE_EXPANSION
    total = 0
    for child in package_path.rglob("*"):
        try:
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def required_upgrade_bytes(payload_bytes: int, headroom_bytes: int) -> int:
    return max(int(payload_bytes), 0) + max(int(headroom_bytes), 0)


def human_bytes(value: float) -> str:
    """与 capacity_alerts/reports 的字节文案保持同一量级与精度（KiB 起、两位小数）。"""
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(size) < 1024 or unit == "PiB":
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PiB"


def _check_disk_space(
    package_path: Path,
    required_dirs: list[Path],
    headroom_bytes: int,
    usage: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    usage = usage or shutil.disk_usage
    try:
        payload_bytes = package_payload_bytes(package_path)
    except OSError as exc:
        return {"name": "disk_space", "ok": False, "message": f"无法读取升级包大小：{exc}"}

    required = required_upgrade_bytes(payload_bytes, headroom_bytes)
    seen_devices: set[int] = set()
    filesystems: list[dict[str, Any]] = []
    for path in required_dirs:
        try:
            device = path.stat().st_dev
            free_bytes = usage(path).free
        except OSError:
            continue
        if device in seen_devices:
            continue
        seen_devices.add(device)
        filesystems.append({"path": str(path), "free_bytes": int(free_bytes), "required_bytes": required})
    if not filesystems:
        return {"name": "disk_space", "ok": False, "message": "无法获取升级所需目录的磁盘可用空间"}

    detail = {
        "package_bytes": payload_bytes,
        "required_bytes": required,
        "headroom_bytes": headroom_bytes,
        "payload_uncompressed": not package_path.is_file(),
        "filesystems": filesystems,
    }
    insufficient = [item for item in filesystems if item["free_bytes"] < required]
    if insufficient:
        worst = min(insufficient, key=lambda item: item["free_bytes"])
        return {
            "name": "disk_space",
            "ok": False,
            "message": (
                f"磁盘空间不足：{worst['path']} 可用 {human_bytes(worst['free_bytes'])}，"
                f"升级需要 {human_bytes(required)}"
                f"（包内容 {human_bytes(payload_bytes)} + 预留 {human_bytes(headroom_bytes)}）"
            ),
            "detail": detail,
        }
    return {
        "name": "disk_space",
        "ok": True,
        "message": (
            f"磁盘空间充足（最少可用 {human_bytes(min(item['free_bytes'] for item in filesystems))}"
            f" ≥ 需要 {human_bytes(required)}）"
        ),
        "detail": detail,
    }



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
            message = f"本地 Docker 镜像不存在：{image_name}"
            if "upgrade-runner" in image_name:
                # 49-50：平台包不打包 runner 镜像，handoff 步骤要 docker run 它 → 必须先做组件升级
                tag = image_name.rsplit(":", 1)[-1] if ":" in image_name else "目标版本"
                message += (
                    f"。升级计划的 runner 切换需要该镜像已就位，平台升级包不包含 runner 镜像；"
                    f"请先在升级中心执行「组件升级」把 upgrade-runner 升到 {tag}"
                    f"（组件包 smartx-upgrade-runner-{tag}.tar.gz）后重试。"
                )
            return {"name": "images", "ok": False, "message": message}
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
