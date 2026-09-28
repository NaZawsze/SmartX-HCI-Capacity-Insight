from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.upgrade_runner.store import TaskStore  # noqa: E402
from app.v2.config import V2Settings  # noqa: E402
from app.v2.database import V2Database  # noqa: E402
from app.v2.tasks.models import TaskStatus, TaskType  # noqa: E402
from app.v2.tasks.service import TaskService  # noqa: E402
from app.v2.upgrade.service import UpgradeCommandExecutor, UpgradeService  # noqa: E402
from app.v2.upgrade.service._compat import HTTPException  # noqa: E402


class StuckRunningRecoveryTest(unittest.TestCase):
    """US-25：卡在 running 且无 runner 持有的任务，必须能通过产品接口被标记失败。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = V2Settings(data_root=Path(self.tmp.name), secret_key="upgrade-secret", app_version="v0.5.3")
        self.database = V2Database(self.settings)
        self.database.initialize()
        self.tasks = TaskService(self.database)
        self.project_path = Path(self.tmp.name) / "project"

    def _service(self) -> UpgradeService:
        class FakeExecutor(UpgradeCommandExecutor):
            def run(self, command, *, cwd=None):  # pragma: no cover
                return None

            def output(self, command, *, cwd=None):  # pragma: no cover
                return ""

        return UpgradeService(self.settings, self.tasks, executor=FakeExecutor(), project_path=self.project_path)

    def _running_task(self, task_id: str = "upgrade-stuck") -> Path:
        task_dir = Path(self.settings.upgrades_dir) / task_id
        TaskStore(task_dir).save(
            {
                "task_id": task_id,
                "status": "running",
                "created_at": "2026-09-28T00:00:00+00:00",
                "updated_at": "2026-09-28T00:00:00+00:00",
                "execution_plan": {"actions": [{"id": "a1", "type": "compose.override", "status": "running"}]},
            }
        )
        self.tasks.create_task(
            task_id, TaskType.UPGRADE, "执行系统升级",
            status=TaskStatus.RUNNING, progress=50, message="执行中",
        )
        return task_dir

    def _add_lease(self, task_id: str = "upgrade-stuck", *, expires_in: int, heartbeat_ago: int = 0) -> None:
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=expires_in)).isoformat()
        heartbeat = (now - timedelta(seconds=heartbeat_ago)).isoformat()
        with self.database.connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO upgrade_task_leases (task_id, lease_owner, lease_expires_at, heartbeat_at, revision)"
                " VALUES (?, 'runner-a', ?, ?, 0)",
                (task_id, expires, heartbeat),
            )

    # ---- 逃生门 ------------------------------------------------------------
    def test_fail_is_allowed_when_task_running_without_live_lease(self):
        task_dir = self._running_task()
        service = self._service()
        result = service.recovery_fail("upgrade-stuck")
        saved = TaskStore(task_dir).load()
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["recovery_command"], "fail")
        self.assertIn("runner 已不再持有该任务", saved["error"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.tasks.get_task("upgrade-stuck")["status"], "failed")

    def test_fail_is_allowed_when_lease_expired(self):
        self._running_task()
        self._add_lease(expires_in=-60, heartbeat_ago=90)
        service = self._service()
        self.assertEqual(service.recovery_fail("upgrade-stuck")["status"], "failed")

    def test_fail_is_rejected_while_runner_still_holds_the_task(self):
        self._running_task()
        self._add_lease(expires_in=30)
        service = self._service()
        with self.assertRaises(HTTPException) as ctx:
            service.recovery_fail("upgrade-stuck")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("可以标记失败", ctx.exception.detail)

    def test_public_view_exposes_runner_lost_and_fail_action(self):
        self._running_task()
        service = self._service()
        public = service._public_task(TaskStore(Path(self.settings.upgrades_dir) / "upgrade-stuck").load())
        self.assertTrue(public["runner_lost"])
        self.assertIn("fail", public["available_recovery_actions"])

    def test_public_view_hides_runner_lost_while_lease_is_live(self):
        self._running_task()
        self._add_lease(expires_in=30)
        service = self._service()
        public = service._public_task(TaskStore(Path(self.settings.upgrades_dir) / "upgrade-stuck").load())
        self.assertNotIn("runner_lost", public)

    # ---- 逃生门开后不再锁死环境 --------------------------------------------
    def test_single_flight_released_after_failing_the_stuck_task(self):
        self._running_task()
        service = self._service()
        with self.assertRaises(HTTPException):
            service._ensure_no_active_upgrade("upgrade-other")
        service.recovery_fail("upgrade-stuck")
        service._ensure_no_active_upgrade("upgrade-other")  # 不应再抛

    def test_recovery_required_path_unchanged(self):
        task_dir = Path(self.settings.upgrades_dir) / "upgrade-rec"
        TaskStore(task_dir).save(
            {
                "task_id": "upgrade-rec",
                "status": "recovery_required",
                "available_recovery_actions": ["continue", "fail"],
                "created_at": "2026-09-28T00:00:00+00:00",
                "updated_at": "2026-09-28T00:00:00+00:00",
            }
        )
        self.tasks.create_task(
            task_id="upgrade-rec", task_type=TaskType.UPGRADE, title="执行系统升级",
            status=TaskStatus.RUNNING, progress=50, message="等待恢复",
        )
        service = self._service()
        self.assertEqual(service.recovery_fail("upgrade-rec")["status"], "failed")


if __name__ == "__main__":
    unittest.main()
