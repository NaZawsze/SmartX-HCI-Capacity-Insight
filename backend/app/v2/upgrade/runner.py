from __future__ import annotations

from pathlib import Path

from app.v2.config import V2Settings, settings_from_environment
from app.v2.database import V2Database
from app.v2.tasks.service import TaskService
from app.upgrade_runner.actions import CommandExecutor
from app.upgrade_runner.actions import default_handlers
from app.upgrade_runner.main import RunnerSettings, main, run_pending_once as run_standalone_pending_once


def run_pending_once(
    settings: V2Settings,
    tasks: TaskService,
    *,
    executor: CommandExecutor | None = None,
    project_path: Path | None = None,
) -> int:
    runner_settings = RunnerSettings(
        database_path=settings.sqlite_path,
        upgrades_path=settings.upgrades_dir,
        data_path=settings.sqlite_path.parent,
        backups_path=settings.backups_dir,
        compose_runtime_path=settings.compose_runtime_dir,
        prometheus_path=settings.prometheus_data_dir,
        project_path=project_path or Path("/opt/smartx-storage-forecast"),
        compose_file=settings.compose_file,
        compose_project=settings.compose_project_name,
        runner_version=settings.runner_version,
    )
    handlers = None
    if executor is not None:
        handlers = default_handlers()
        handlers["health.http"] = lambda _action, _context: {"status": 200, "checkpoint": {"healthy": True}}
        handlers["health.prometheus"] = handlers["health.http"]
    return run_standalone_pending_once(runner_settings, executor=executor, handlers=handlers)


if __name__ == "__main__":
    main()
