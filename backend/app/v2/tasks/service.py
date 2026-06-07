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
        task_type_value = _value(task_type)
        status_value = _value(status)
        severity = _severity(task_type_value, status_value, title)
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO tasks (
                    id, type, status, title, progress, message, links_json, logs_json, steps_json,
                    severity, seen_at, acknowledged_at, created_at, updated_at, finished_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, COALESCE((SELECT created_at FROM tasks WHERE id = ?), ?), ?, ?)
                """,
                (
                    task_id,
                    task_type_value,
                    status_value,
                    title,
                    _clamp(progress),
                    message,
                    _json(links or []),
                    _json(logs or []),
                    _json(steps or []),
                    severity,
                    task_id,
                    now,
                    now,
                    now if status_value in _FINISHED_STATUSES else None,
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
        next_progress = _clamp(progress if progress is not None else existing["progress"])
        next_message = message if message is not None else existing.get("message") or ""
        next_links = links if links is not None else existing.get("links") or []
        next_logs = logs if logs is not None else existing.get("logs") or []
        next_steps = steps if steps is not None else existing.get("steps") or []
        next_severity = _severity(existing["type"], next_status, existing["title"])
        finished_at = _now() if next_status in _FINISHED_STATUSES else None
        with self.database.connection() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, progress = ?, message = ?, links_json = ?, logs_json = ?, steps_json = ?,
                    severity = ?, updated_at = ?, finished_at = COALESCE(?, finished_at)
                WHERE id = ?
                """,
                (
                    next_status,
                    next_progress,
                    next_message,
                    _json(next_links),
                    _json(next_logs),
                    _json(next_steps),
                    next_severity,
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
            cursor = conn.execute("DELETE FROM tasks WHERE status = ?", (TaskStatus.SUCCESS.value,))
            return int(cursor.rowcount or 0)

    def mark_info_seen(self, task_ids: list[str]) -> int:
        ids = [str(task_id) for task_id in task_ids if str(task_id)]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self.database.connection() as conn:
            cursor = conn.execute(
                f"""
                UPDATE tasks
                SET seen_at = COALESCE(seen_at, ?), updated_at = ?
                WHERE {_effective_severity_sql()} = ? AND seen_at IS NULL AND id IN ({placeholders})
                """,
                (_now(), _now(), "info", *ids),
            )
            return int(cursor.rowcount or 0)

    def acknowledge(self, task_id: str) -> dict[str, Any]:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        if task["severity"] == "info":
            self.mark_info_seen([task_id])
            return self.get_task(task_id) or {}
        with self.database.connection() as conn:
            conn.execute(
                f"""
                UPDATE tasks
                SET acknowledged_at = COALESCE(acknowledged_at, ?), updated_at = ?
                WHERE id = ? AND {_effective_severity_sql()} IN ('warning', 'critical')
                """,
                (_now(), _now(), task_id),
            )
        return self.get_task(task_id) or {}

    def clear_clearable(self) -> int:
        with self.database.connection() as conn:
            cursor = conn.execute(
                f"""
                DELETE FROM tasks
                WHERE status IN (?, ?, ?)
                  AND (
                    {_effective_severity_sql()} = 'info'
                    OR ({_effective_severity_sql()} IN ('warning', 'critical') AND acknowledged_at IS NOT NULL)
                  )
                """,
                (TaskStatus.SUCCESS.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value),
            )
            return int(cursor.rowcount or 0)

    def delete_inactive(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if task is None or task["status"] in {TaskStatus.PENDING.value, TaskStatus.RUNNING.value}:
            return False
        with self.database.connection() as conn:
            cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            return bool(cursor.rowcount)


def _task_row(row) -> dict[str, Any]:
    severity = row["severity"] or _severity(row["type"], row["status"], row["title"])
    seen_at = row["seen_at"]
    acknowledged_at = row["acknowledged_at"]
    unhandled = _unhandled(severity, row["status"], seen_at, acknowledged_at)
    return {
        "id": row["id"],
        "task_id": row["id"],
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
        "severity": severity,
        "seen_at": seen_at,
        "acknowledged_at": acknowledged_at,
        "unhandled": unhandled,
        "clearable": _clearable(severity, row["status"], seen_at, acknowledged_at),
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


def _effective_severity_sql() -> str:
    return """
    COALESCE(
      severity,
      CASE
        WHEN status = 'success' THEN 'info'
        WHEN status IN ('failed', 'cancelled')
             AND (type = 'upgrade' OR lower(title) LIKE '%升级%' OR lower(title) LIKE '%重启%' OR lower(title) LIKE '%回滚%' OR lower(title) LIKE '%upgrade%' OR lower(title) LIKE '%restart%' OR lower(title) LIKE '%rollback%' OR lower(title) LIKE '%component%') THEN 'critical'
        WHEN status IN ('failed', 'cancelled') THEN 'warning'
        ELSE 'info'
      END
    )
    """


_FINISHED_STATUSES = {TaskStatus.SUCCESS.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}
_CRITICAL_FAILURE_KEYWORDS = ("升级", "重启", "回滚", "upgrade", "restart", "rollback", "component")


def _severity(task_type: str, status: str, title: str) -> str:
    if status == TaskStatus.SUCCESS.value:
        return "info"
    if status in {TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}:
        if task_type == TaskType.UPGRADE.value or any(keyword in title.lower() for keyword in _CRITICAL_FAILURE_KEYWORDS):
            return "critical"
        return "warning"
    return "info"


def _unhandled(severity: str, status: str, seen_at: str | None, acknowledged_at: str | None) -> bool:
    if status not in _FINISHED_STATUSES:
        return False
    if severity == "info":
        return seen_at is None
    return acknowledged_at is None


def _clearable(severity: str, status: str, seen_at: str | None, acknowledged_at: str | None) -> bool:
    if status not in _FINISHED_STATUSES:
        return False
    if severity == "info":
        return True
    return acknowledged_at is not None


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
