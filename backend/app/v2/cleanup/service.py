from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.v2.config import V2Settings
from app.v2.tasks.models import TaskStatus, TaskType
from app.v2.tasks.service import TaskService


class CleanupService:
    def __init__(self, settings: V2Settings, tasks: TaskService) -> None:
        self.settings = settings
        self.tasks = tasks

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
