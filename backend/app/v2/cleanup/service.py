from __future__ import annotations

import shutil
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from app.v2.config import V2Settings
from app.v2.tasks.models import TaskStatus, TaskType
from app.v2.tasks.service import TaskService


class CleanupCommandExecutor:
    def output(self, command: list[str]) -> str:
        if os.environ.get("SMARTX_UPGRADE_DRY_RUN") == "1":
            return ""
        return subprocess.check_output(command, text=True)


class CleanupService:
    def __init__(self, settings: V2Settings, tasks: TaskService, *, executor: CleanupCommandExecutor | None = None) -> None:
        self.settings = settings
        self.tasks = tasks
        self.executor = executor or CleanupCommandExecutor()

    def scan_artifacts(self) -> dict[str, Any]:
        items = [_scan_item(key, label, path) for key, label, path in self._targets()]
        items = [item for item in items if item["count"] > 0]
        total_size = sum(int(item["size"]) for item in items)
        total_count = sum(int(item["count"]) for item in items)
        return {
            "ok": True,
            "items": items,
            "total_count": total_count,
            "total_size": total_size,
            "total_size_label": _size_label(total_size),
            "space_reclaimable": total_size,
            "space_reclaimable_label": _size_label(total_size),
            "message": f"发现 {total_count} 个可清理项目，可释放 {_size_label(total_size)}。",
        }

    def local_storage_usage(self) -> dict[str, Any]:
        path = self.settings.data_root
        path.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(path)
        total = int(usage.total)
        free = int(usage.free)
        used = int(usage.used)
        used_ratio = used / total if total > 0 else 0
        free_ratio = free / total if total > 0 else 0
        return {
            "path": str(path),
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "used_ratio": used_ratio,
            "free_ratio": free_ratio,
            "total_label": _size_label(total),
            "used_label": _size_label(used),
            "free_label": _size_label(free),
        }

    def cleanup_artifacts(self) -> dict[str, Any]:
        scan = self.scan_artifacts()
        logs: list[str] = []
        deleted_count = 0
        for item in scan["items"]:
            path = Path(item["path"])
            if not path.exists():
                continue
            for child in path.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
                deleted_count += 1
            logs.append(f"{item['label']}：清理 {item['count']} 项，释放 {item['size_label']}")
        self.tasks.create_task(
            f"cleanup-artifacts-{deleted_count}-{int(scan['total_size'])}",
            TaskType.CLEANUP,
            "空间清理",
            status=TaskStatus.SUCCESS,
            progress=100,
            message=f"清理完成，释放 {scan['total_size_label']}",
            logs=logs,
        )
        return {
            "ok": True,
            "deleted_count": deleted_count,
            "space_reclaimed": scan["total_size"],
            "space_reclaimed_label": scan["total_size_label"],
            "logs": logs,
            "message": f"清理完成，释放 {scan['total_size_label']}。",
        }

    def scan_unused_images(self) -> dict[str, Any]:
        try:
            raw = self.executor.output(["docker", "image", "ls", "--filter", "dangling=true", "--format", "{{json .}}"])
        except Exception as exc:
            return {"ok": False, "images": [], "image_count": 0, "space_reclaimable": 0, "space_reclaimable_label": "0B", "message": f"扫描 Docker 镜像失败：{exc}"}
        images: list[dict[str, Any]] = []
        for item in _parse_docker_json_lines(raw):
            image_id = str(item.get("ID") or item.get("ID".lower()) or "")
            detail = self._inspect_image(image_id)
            size = int(detail.get("Size") or 0)
            repo_tags = detail.get("RepoTags") or []
            display_name = repo_tags[0] if repo_tags else f"{item.get('Repository', '<none>')}:{item.get('Tag', '<none>')}"
            images.append(
                {
                    "id": image_id,
                    "short_id": image_id.replace("sha256:", "")[:12],
                    "repo_tags": repo_tags,
                    "display_name": display_name,
                    "size": size,
                    "size_label": _size_label(size),
                    "reclaimable_size": size,
                    "reclaimable_size_label": _size_label(size),
                    "created_at": item.get("CreatedAt"),
                }
            )
        total = sum(int(image["reclaimable_size"]) for image in images)
        return {
            "ok": True,
            "images": images,
            "image_count": len(images),
            "space_reclaimable": total,
            "space_reclaimable_label": _size_label(total),
            "message": f"发现 {len(images)} 个未使用镜像，可释放 {_size_label(total)}。",
        }

    def cleanup_unused_images(self) -> dict[str, Any]:
        scan = self.scan_unused_images()
        logs: list[str] = [scan["message"]]
        deleted = 0
        errors: list[str] = []
        for image in scan["images"]:
            try:
                output = self.executor.output(["docker", "image", "rm", str(image["id"])])
                logs.extend([line for line in output.splitlines() if line.strip()])
                deleted += 1
            except Exception as exc:
                errors.append(f"{image['display_name']}：{exc}")
        self.tasks.create_task(
            f"cleanup-images-{deleted}-{int(scan['space_reclaimable'])}",
            TaskType.CLEANUP,
            "清理旧版本镜像",
            status=TaskStatus.SUCCESS if not errors else TaskStatus.FAILED,
            progress=100,
            message=f"镜像清理完成，释放 {scan['space_reclaimable_label']}",
            logs=logs + errors,
        )
        return {
            "ok": not errors,
            "deleted_count": deleted,
            "space_reclaimed": scan["space_reclaimable"],
            "space_reclaimed_label": scan["space_reclaimable_label"],
            "space_reclaimable_before": scan["space_reclaimable"],
            "space_reclaimable_before_label": scan["space_reclaimable_label"],
            "errors": errors,
            "message": f"镜像清理完成，释放 {scan['space_reclaimable_label']}。",
        }

    def _inspect_image(self, image_id: str) -> dict[str, Any]:
        if not image_id:
            return {}
        try:
            raw = self.executor.output(["docker", "image", "inspect", image_id])
            payload = json.loads(raw)
        except Exception:
            return {}
        if isinstance(payload, list) and payload:
            return payload[0]
        return {}

    def _targets(self) -> list[tuple[str, str, Path]]:
        return [
            ("upgrades", "升级包", self.settings.upgrades_dir),
            ("reports", "报表导出", self.settings.reports_dir),
            ("migrations", "数据迁出", self.settings.migrations_dir),
            ("imports", "数据迁入留档", self.settings.imports_dir),
        ]


def _scan_item(key: str, label: str, path: Path) -> dict[str, Any]:
    count = 0
    size = 0
    if path.exists():
        for child in path.iterdir():
            count += 1
            size += _path_size(child)
    return {
        "key": key,
        "label": label,
        "description": f"{label}运行产物",
        "path": str(path),
        "count": count,
        "size": size,
        "size_label": _size_label(size),
    }


def _parse_docker_json_lines(raw: str) -> list[dict[str, Any]]:
    raw = raw.strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            return [payload]
    except json.JSONDecodeError:
        pass
    items: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            items.append(item)
    return items


def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
    return 0


def _size_label(size: int) -> str:
    value = float(size)
    units = ["B", "KB", "MB", "GB", "TB"]
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    if index == 0:
        return f"{int(value)}B"
    return f"{value:.2f}{units[index]}"
