"""Upgrade service package (split from the original service.py).

``UpgradeService`` is composed from domain mixins; the constructor
signature and public method set are unchanged.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.v2.config import V2Settings
from app.v2.tasks.service import TaskService

from ._compat import HTTPException, UploadFile
from .cleanup import CleanupMixin
from .execution import ExecutionMixin
from .intake import IntakeMixin
from .manual_rollback import ManualRollbackMixin
from .paths import PathsMixin
from .precheck import PrecheckMixin
from .taskfile import TaskFileMixin, _save_task_file
from .verification import VerificationMixin


class UpgradeCommandExecutor:
    def run(self, command: list[str], *, cwd: Path | None = None) -> None:
        if os.environ.get("SMARTX_UPGRADE_DRY_RUN") == "1":
            return
        subprocess.run(command, cwd=str(cwd) if cwd else None, check=True)

    def output(self, command: list[str], *, cwd: Path | None = None) -> str:
        if os.environ.get("SMARTX_UPGRADE_DRY_RUN") == "1":
            return ""
        completed = subprocess.run(command, cwd=str(cwd) if cwd else None, check=True, text=True, capture_output=True)
        return completed.stdout


class UpgradeService(IntakeMixin, PrecheckMixin, ExecutionMixin, CleanupMixin, VerificationMixin, TaskFileMixin, PathsMixin, ManualRollbackMixin):
    def __init__(
        self,
        settings: V2Settings,
        tasks: TaskService,
        *,
        executor: UpgradeCommandExecutor | None = None,
        project_path: Path | None = None,
        hostname_path: Path | None = None,
    ) -> None:
        self.settings = settings
        self.tasks = tasks
        self.executor = executor or UpgradeCommandExecutor()
        self.project_path = project_path or Path(os.environ.get("SMARTX_PROJECT_PATH", "/data/smartx-storage-forecast/project"))
        self.hostname_path = hostname_path or Path("/etc/hostname")


__all__ = ["UpgradeService", "UpgradeCommandExecutor", "HTTPException", "ManualRollbackMixin", "_save_task_file"]
