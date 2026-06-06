from __future__ import annotations

import signal
import time
from pathlib import Path

from app.v2.config import V2Settings, settings_from_environment
from app.v2.database import V2Database
from app.v2.tasks.service import TaskService
from app.v2.upgrade.service import UpgradeCommandExecutor, UpgradeService, _read_task_file


def run_pending_once(
    settings: V2Settings,
    tasks: TaskService,
    *,
    executor: UpgradeCommandExecutor | None = None,
    project_path: Path | None = None,
) -> int:
    count = 0
    for task_file in sorted(settings.upgrades_dir.glob("*/task.json"), key=lambda path: path.stat().st_mtime):
        task = _read_task_file(task_file.parent)
        if task.get("status") != "pending" or not task.get("runner_requested"):
            continue
        UpgradeService(settings, tasks, executor=executor, project_path=project_path).execute_task(task)
        count += 1
    return count


def main() -> None:
    settings = settings_from_environment()
    database = V2Database(settings)
    database.initialize()
    tasks = TaskService(database)
    stop = False

    def request_stop(*_: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    while not stop:
        run_pending_once(settings, tasks)
        time.sleep(3)


if __name__ == "__main__":
    main()
