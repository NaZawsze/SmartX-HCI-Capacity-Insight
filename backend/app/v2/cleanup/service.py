from __future__ import annotations

import shutil
import sqlite3
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
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

    def scan_sqlite_vacuum(self) -> dict[str, Any]:
        path = self.settings.sqlite_path
        if not path.exists():
            return {
                "ok": True,
                "path": str(path),
                "size": 0,
                "size_label": _size_label(0),
                "page_count": 0,
                "freelist_count": 0,
                "page_size": 0,
                "estimated_reclaimable": 0,
                "estimated_reclaimable_label": _size_label(0),
                "runtime_cache": _empty_runtime_cache_scan(),
                "message": "SQLite 数据库尚不存在，无需整理。",
            }
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            page_count = int(conn.execute("PRAGMA page_count").fetchone()[0] or 0)
            freelist_count = int(conn.execute("PRAGMA freelist_count").fetchone()[0] or 0)
            page_size = int(conn.execute("PRAGMA page_size").fetchone()[0] or 0)
            runtime_cache = _scan_runtime_cache(conn)
        size = path.stat().st_size
        estimated = max(0, freelist_count * page_size)
        return {
            "ok": True,
            "path": str(path),
            "size": size,
            "size_label": _size_label(size),
            "page_count": page_count,
            "freelist_count": freelist_count,
            "page_size": page_size,
            "estimated_reclaimable": estimated,
            "estimated_reclaimable_label": _size_label(estimated),
            "runtime_cache": runtime_cache,
            "message": f"SQLite 当前大小 {_size_label(size)}，预计可整理释放 {_size_label(estimated)}。",
        }

    def vacuum_sqlite(self) -> dict[str, Any]:
        scan = self.scan_sqlite_vacuum()
        path = self.settings.sqlite_path
        if not path.exists():
            return {
                "ok": True,
                "backup_path": "",
                "before_size": 0,
                "after_size": 0,
                "space_reclaimed": 0,
                "space_reclaimed_label": _size_label(0),
                "runtime_cache": {
                    "metric_snapshots_deleted": 0,
                    "collection_runs_deleted": 0,
                    "tasks_deleted": 0,
                },
                "message": "SQLite 数据库尚不存在，无需整理。",
            }
        self.settings.backups_dir.mkdir(parents=True, exist_ok=True)
        backup_path = self.settings.backups_dir / f"sqlite-before-cleanup-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.db"
        shutil.copy2(path, backup_path)
        before_size = path.stat().st_size
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            runtime_result = _cleanup_runtime_cache(conn)
            conn.commit()
            conn.execute("VACUUM")
        after_size = path.stat().st_size
        reclaimed = max(0, before_size - after_size)
        logs = [
            scan["message"],
            f"指标快照：清理 {runtime_result['metric_snapshots_deleted']} 条，保留最新 1 条",
            f"采集记录：清理 {runtime_result['collection_runs_deleted']} 条，保留最近 7 天",
            f"任务记录：清理 {runtime_result['tasks_deleted']} 条，保留最近 30 天和未确认告警",
            f"整理前备份：{backup_path}",
            f"整理前：{_size_label(before_size)}",
            f"整理后：{_size_label(after_size)}",
            f"释放：{_size_label(reclaimed)}",
        ]
        self.tasks.create_task(
            "cleanup-sqlite-runtime",
            TaskType.CLEANUP,
            "SQLite 清理并整理",
            status=TaskStatus.SUCCESS,
            progress=100,
            message=f"SQLite 清理并整理完成，释放 {_size_label(reclaimed)}",
            logs=logs,
            links=[{"label": "整理前备份", "filename": backup_path.name, "url": "", "path": str(backup_path)}],
        )
        return {
            "ok": True,
            "backup_path": str(backup_path),
            "before_size": before_size,
            "after_size": after_size,
            "before_size_label": _size_label(before_size),
            "after_size_label": _size_label(after_size),
            "space_reclaimed": reclaimed,
            "space_reclaimed_label": _size_label(reclaimed),
            "runtime_cache": runtime_result,
            "message": f"SQLite 清理并整理完成，释放 {_size_label(reclaimed)}。",
            "logs": logs,
        }

    def scan_sqlite_backups(self) -> dict[str, Any]:
        self.settings.backups_dir.mkdir(parents=True, exist_ok=True)
        items: list[dict[str, Any]] = []
        for path in sorted(self.settings.backups_dir.iterdir(), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True):
            if not path.is_file() or not _is_sqlite_backup_file(path):
                continue
            stat = path.stat()
            items.append(
                {
                    "filename": path.name,
                    "path": str(path),
                    "size": int(stat.st_size),
                    "size_label": _size_label(int(stat.st_size)),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                }
            )
        total_size = sum(int(item["size"]) for item in items)
        return {
            "ok": True,
            "items": items,
            "total_count": len(items),
            "total_size": total_size,
            "total_size_label": _size_label(total_size),
            "message": f"发现 {len(items)} 个 SQLite 数据库备份，可释放 {_size_label(total_size)}。",
        }

    def cleanup_sqlite_backups(self, filenames: list[str]) -> dict[str, Any]:
        selected = [_safe_backup_filename(filename) for filename in filenames]
        selected = [filename for filename in selected if filename]
        deleted_count = 0
        reclaimed = 0
        logs: list[str] = []
        for filename in selected:
            path = self.settings.backups_dir / filename
            if not path.is_file() or not _is_sqlite_backup_file(path):
                logs.append(f"{filename}：不存在或不是 SQLite 数据库备份，已跳过")
                continue
            size = path.stat().st_size
            path.unlink()
            deleted_count += 1
            reclaimed += int(size)
            logs.append(f"{filename}：删除，释放 {_size_label(int(size))}")
        self.tasks.create_task(
            f"cleanup-sqlite-backups-{deleted_count}-{int(reclaimed)}",
            TaskType.CLEANUP,
            "SQLite 备份清理",
            status=TaskStatus.SUCCESS,
            progress=100,
            message=f"SQLite 备份清理完成，释放 {_size_label(reclaimed)}",
            logs=logs,
        )
        return {
            "ok": True,
            "deleted_count": deleted_count,
            "space_reclaimed": reclaimed,
            "space_reclaimed_label": _size_label(reclaimed),
            "logs": logs,
            "message": f"SQLite 备份清理完成，释放 {_size_label(reclaimed)}。",
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


def _is_sqlite_backup_file(path: Path) -> bool:
    if path.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        return False
    name = path.name
    return name.startswith(("sqlite-before-", "smartx-db-before-", "smartx-before-"))


def _safe_backup_filename(filename: object) -> str:
    name = Path(str(filename or "")).name
    if name in {"", ".", ".."}:
        return ""
    return name


def _empty_runtime_cache_scan() -> dict[str, Any]:
    return {
        "metric_snapshots": {"keep": 1, "delete_count": 0},
        "collection_runs": {"retention_days": 7, "delete_count": 0},
        "tasks": {"retention_days": 30, "delete_count": 0},
    }


def _scan_runtime_cache(conn: sqlite3.Connection) -> dict[str, Any]:
    snapshot_count = _table_count(conn, "metric_snapshots")
    collection_cutoff = _utc_cutoff(days=7)
    task_cutoff = _utc_cutoff(days=30)
    collection_delete_count = _count_collection_runs_before(conn, collection_cutoff)
    task_delete_count = _count_expired_tasks(conn, task_cutoff)
    return {
        "metric_snapshots": {"keep": 1, "delete_count": max(0, snapshot_count - 1)},
        "collection_runs": {"retention_days": 7, "delete_count": collection_delete_count},
        "tasks": {"retention_days": 30, "delete_count": task_delete_count},
    }


def _cleanup_runtime_cache(conn: sqlite3.Connection) -> dict[str, int]:
    snapshot_deleted = _delete_old_metric_snapshots(conn)
    collection_cutoff = _utc_cutoff(days=7)
    task_cutoff = _utc_cutoff(days=30)
    collection_deleted = _delete_collection_runs_before(conn, collection_cutoff)
    task_deleted = _delete_expired_tasks(conn, task_cutoff)
    return {
        "metric_snapshots_deleted": snapshot_deleted,
        "collection_runs_deleted": collection_deleted,
        "tasks_deleted": task_deleted,
    }


def _delete_old_metric_snapshots(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "metric_snapshots"):
        return 0
    cursor = conn.execute(
        """
        DELETE FROM metric_snapshots
        WHERE id NOT IN (
            SELECT id FROM metric_snapshots ORDER BY updated_at DESC, id DESC LIMIT 1
        )
        """
    )
    return int(cursor.rowcount or 0)


def _count_collection_runs_before(conn: sqlite3.Connection, cutoff: str) -> int:
    if not _table_exists(conn, "collection_runs"):
        return 0
    return int(conn.execute("SELECT COUNT(*) FROM collection_runs WHERE started_at < ?", (cutoff,)).fetchone()[0] or 0)


def _delete_collection_runs_before(conn: sqlite3.Connection, cutoff: str) -> int:
    if not _table_exists(conn, "collection_runs"):
        return 0
    cursor = conn.execute("DELETE FROM collection_runs WHERE started_at < ?", (cutoff,))
    return int(cursor.rowcount or 0)


def _count_expired_tasks(conn: sqlite3.Connection, cutoff: str) -> int:
    if not _table_exists(conn, "tasks"):
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM tasks WHERE {_expired_task_where_sql()}", (cutoff,)).fetchone()[0] or 0)


def _delete_expired_tasks(conn: sqlite3.Connection, cutoff: str) -> int:
    if not _table_exists(conn, "tasks"):
        return 0
    cursor = conn.execute(f"DELETE FROM tasks WHERE {_expired_task_where_sql()}", (cutoff,))
    return int(cursor.rowcount or 0)


def _expired_task_where_sql() -> str:
    return """
        status IN ('success', 'failed', 'cancelled')
        AND COALESCE(finished_at, updated_at) < ?
        AND (
            COALESCE(severity, CASE
                WHEN status = 'success' THEN 'info'
                WHEN status IN ('failed', 'cancelled')
                     AND (type = 'upgrade' OR lower(title) LIKE '%升级%' OR lower(title) LIKE '%重启%' OR lower(title) LIKE '%回滚%' OR lower(title) LIKE '%upgrade%' OR lower(title) LIKE '%restart%' OR lower(title) LIKE '%rollback%' OR lower(title) LIKE '%component%') THEN 'critical'
                WHEN status IN ('failed', 'cancelled') THEN 'warning'
                ELSE 'info'
            END) = 'info'
            OR (
                COALESCE(severity, CASE
                    WHEN status = 'success' THEN 'info'
                    WHEN status IN ('failed', 'cancelled')
                         AND (type = 'upgrade' OR lower(title) LIKE '%升级%' OR lower(title) LIKE '%重启%' OR lower(title) LIKE '%回滚%' OR lower(title) LIKE '%upgrade%' OR lower(title) LIKE '%restart%' OR lower(title) LIKE '%rollback%' OR lower(title) LIKE '%component%') THEN 'critical'
                    WHEN status IN ('failed', 'cancelled') THEN 'warning'
                    ELSE 'info'
                END) IN ('warning', 'critical')
                AND acknowledged_at IS NOT NULL
            )
        )
    """


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] or 0)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None


def _utc_cutoff(*, days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


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
