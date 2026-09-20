"""Shared v2 task model primitives.

These models are intentionally dependency-light so web-api, runner, and tests
can share the same task vocabulary before concrete persistence is introduced.
"""

from dataclasses import dataclass
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(str, Enum):
    REPORT = "report"
    MIGRATION_EXPORT = "migration_export"
    MIGRATION_IMPORT = "migration_import"
    UPGRADE = "upgrade"
    CLEANUP = "cleanup"
    COLLECTION = "collection"


@dataclass(frozen=True)
class ErrorSnapshot:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    task_type: TaskType
    status: TaskStatus
    progress: int = 0
    message: str = ""

    def __post_init__(self) -> None:
        clamped = min(100, max(0, int(self.progress)))
        object.__setattr__(self, "progress", clamped)
