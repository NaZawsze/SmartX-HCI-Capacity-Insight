from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable


class RevisionConflict(RuntimeError):
    pass


class TaskStore:
    def __init__(self, task_dir: Path) -> None:
        self.task_dir = Path(task_dir)
        self.path = self.task_dir / "task.json"

    def load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, task: dict[str, Any], *, expected_revision: int | None = None) -> dict[str, Any]:
        current_revision = 0
        if self.path.exists():
            current_revision = int(self.load().get("revision") or 0)
        if expected_revision is not None and current_revision != expected_revision:
            raise RevisionConflict(f"任务 revision 已变化：期望 {expected_revision}，实际 {current_revision}")
        payload = dict(task)
        payload["revision"] = current_revision + 1
        self.task_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.task_dir / "task.json.tmp"
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)
        directory_fd = os.open(self.task_dir, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return payload

    def update(
        self,
        transform: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        current = self.load()
        if expected_revision is None:
            expected_revision = int(current.get("revision") or 0)
        return self.save(transform(dict(current)), expected_revision=expected_revision)
