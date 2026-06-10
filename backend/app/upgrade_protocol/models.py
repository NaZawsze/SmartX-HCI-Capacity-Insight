from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ActionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RECOVERY_REQUIRED = "recovery_required"
    SKIPPED = "skipped"


class RecoveryStatus(str, Enum):
    NONE = "none"
    AUTO_RESUMING = "auto_resuming"
    REQUIRED = "recovery_required"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"


@dataclass
class ExecutionAction:
    id: str
    type: str
    params: dict[str, Any]
    status: ActionStatus = ActionStatus.PENDING
    attempt: int = 0
    checkpoint: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


@dataclass
class ExecutionPlan:
    protocol_version: int
    required_capabilities: list[str]
    actions: list[ExecutionAction]

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "required_capabilities": list(self.required_capabilities),
            "actions": [action.to_dict() for action in self.actions],
        }
