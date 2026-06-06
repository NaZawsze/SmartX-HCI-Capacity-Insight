from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.v2.database import V2Database
from app.v2.tasks.models import TaskStatus, TaskType


class TaskService:
    def __init__(self, database: V2Database) -> None:
        self.database = database

    def create_task(
        self,
        task_id: str,
        task_type: TaskType | str,
        title: str,
        *,
        status: TaskStatus | str = TaskStatus.PENDING,
        progress: int = 0,
        message: str = "",
        links: list[dict[str, Any]] | None = None,
        logs: list[str] | None = None,
        steps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        now = _now()
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO tasks (id, type, status, title, progress, message, links_json, logs_json, steps_json, created_at, updated_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM tasks WHERE id = ?), ?), ?, ?)
                """,
                (
                    task_id,
                    _value(task_type),
                    _value(status),
                    title,
                    _clamp(progress),
                    message,
                    _json(links or []),
                    _json(logs or []),
                    _json(steps or []),
                    task_id,
                    now,
                    now,
                    now if _value(status) in {TaskStatus.SUCCESS.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value} else None,
                ),
            )
        return self.get_task(task_id) or {}

    def update_task(
        self,
        task_id: str,
        *,
        status: TaskStatus | str | None = None,
        progress: int | None = None,
        message: str | None = None,
        links: list[dict[str, Any]] | None = None,
        logs: list[str] | None = None,
        steps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        existing = self.get_task(task_id)
        if existing is None:
            raise KeyError(task_id)
        next_status = _value(status) if status is not None else existing["status"]
        finished_at = _now() if next_status in {TaskStatus.SUCCESS.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value} else None
        with self.database.connection() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, progress = ?, message = ?, links_json = ?, logs_json = ?, steps_json = ?, updated_at = ?, finished_at = COALESCE(?, finished_at)
                WHERE id = ?
                """,
                (
                    next_status,
                    _clamp(progress if progress is not None else existing["progress"]),
                    message if message is not None else existing.get("message") or "",
                    _json(links if links is not None else existing.get("links") or []),
                    _json(logs if logs is not None else existing.get("logs") or []),
                    _json(steps if steps is not None else existing.get("steps") or []),
                    _now(),
                    finished_at,
                    task_id,
                ),
            )
        return self.get_task(task_id) or {}

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self.database.connection() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _task_row(row) if row else None

    def list_tasks(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.database.connection() as conn:
            rows = conn.execute("SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?", (int(limit),)).fetchall()
        return [_task_row(row) for row in rows]

    def clear_finished(self) -> int:
        with self.database.connection() as conn:
            cursor = conn.execute("DELETE FROM tasks WHERE status IN (?, ?, ?)", (TaskStatus.SUCCESS.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value))
            return int(cursor.rowcount or 0)


def _task_row(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "type": row["type"],
        "kind": _frontend_kind(row["type"]),
        "status": row["status"],
        "title": row["title"],
        "progress": _clamp(row["progress"]),
        "message": row["message"] or "",
        "detail": row["message"] or "",
        "links": _load_json(row["links_json"], []),
        "logs": _load_json(row["logs_json"], []),
        "steps": _load_json(row["steps_json"], []),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "finished_at": row["finished_at"],
    }


def _frontend_kind(task_type: str) -> str:
    return {
        TaskType.REPORT.value: "export",
        TaskType.MIGRATION_EXPORT.value: "export",
        TaskType.MIGRATION_IMPORT.value: "import",
        TaskType.UPGRADE.value: "upgrade",
        TaskType.CLEANUP.value: "upgrade",
        TaskType.COLLECTION.value: "download",
    }.get(task_type, "download")


def _value(value: TaskStatus | TaskType | str) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _clamp(value: Any) -> int:
    try:
        return min(100, max(0, int(value)))
    except (TypeError, ValueError):
        return 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
