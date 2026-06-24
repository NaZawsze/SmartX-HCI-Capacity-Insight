from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


RESTART_SERVICES = ["web-api", "collector-worker", "prometheus"]


class SystemCommandExecutor:
    def run(self, command: list[str], *, cwd: Path | None = None) -> None:
        if os.environ.get("SMARTX_UPGRADE_DRY_RUN") == "1":
            return
        subprocess.run(command, cwd=str(cwd) if cwd else None, check=True)


class SystemControlService:
    def __init__(self, *, executor: SystemCommandExecutor | None = None, project_path: Path | None = None) -> None:
        self.executor = executor or SystemCommandExecutor()
        self.project_path = project_path or Path(os.environ.get("SMARTX_PROJECT_PATH", "/opt/smartx-storage-forecast"))

    def restart_data_services(self) -> dict[str, Any]:
        self.executor.run(
            [
                "docker",
                "compose",
                "-f",
                os.environ.get("SMARTX_COMPOSE_FILE", "docker-compose.offline.yml"),
                "--project-name",
                os.environ.get("SMARTX_COMPOSE_PROJECT_NAME", "smartx-hci-capacity-insight"),
                "up",
                "-d",
                "--no-deps",
                *RESTART_SERVICES,
            ],
            cwd=self.project_path,
        )
        return {"ok": True, "services": RESTART_SERVICES, "message": "数据服务重启已提交。"}
