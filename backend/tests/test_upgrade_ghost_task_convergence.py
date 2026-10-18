"""#89 自动化 / #96 收尾：幽灵 running 行收敛 + runner healthcheck 补齐。

现场依据（`.12`，2026-10-18）：任务 `upgrade-2ed73fd789f3ebc1` 自 2026-10-15 起一直 `running`，
新布局 `upgrades/<id>/` 目录为空、租约 3 天前过期，任务中心永久显示「执行中」。
既有僵尸规则只在空间清理时**跳过**这类行，从不收敛状态。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


class OrphanRunningConvergenceTest(unittest.TestCase):
    def _service(self, tmpdir: str):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeService

        project_dir = Path(tmpdir) / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        settings = V2Settings(
            data_root=Path(tmpdir),
            secret_key="ghost-secret",
            app_version="v0.5.4",
            project_path_override=project_dir,
        )
        database = V2Database(settings)
        database.initialize()
        return settings, database, UpgradeService(settings, TaskService(database), project_path=project_dir)

    def _running_task(self, service, task_id: str, *, age_seconds: int) -> None:
        from app.v2.tasks.models import TaskStatus, TaskType

        service.tasks.create_task(
            task_id, TaskType.UPGRADE, "执行系统升级",
            status=TaskStatus.RUNNING, progress=10, message="执行中",
        )
        stamp = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
        with service.tasks.database.connection() as conn:
            conn.execute("UPDATE tasks SET updated_at = ? WHERE id = ?", (stamp, task_id))

    def _status(self, service, task_id: str) -> str:
        return str(service.tasks.get_task(task_id)["status"])

    def test_orphan_running_task_converges(self) -> None:
        """task.json 已丢失 + 无租约 + 超阈值 → 自动收敛为 failed。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, _, service = self._service(tmpdir)
            self._running_task(service, "upgrade-ghost", age_seconds=3 * 24 * 3600)
            # 目录存在但没有 task.json（与 `.12` 现场一致）
            (settings.upgrades_dir / "upgrade-ghost").mkdir(parents=True, exist_ok=True)

            converged = service.converge_orphan_running_tasks()

            self.assertEqual(converged, ["upgrade-ghost"])
            self.assertEqual(self._status(service, "upgrade-ghost"), "failed")
            self.assertIn("自动收敛", service.tasks.get_task("upgrade-ghost")["message"])

    def test_task_with_artifact_is_kept(self) -> None:
        """task.json 还在 → 不收敛（任务可能真的在跑）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, _, service = self._service(tmpdir)
            self._running_task(service, "upgrade-alive", age_seconds=3 * 24 * 3600)
            task_dir = settings.upgrades_dir / "upgrade-alive"
            task_dir.mkdir(parents=True, exist_ok=True)
            (task_dir / "task.json").write_text("{}", encoding="utf-8")

            self.assertEqual(service.converge_orphan_running_tasks(), [])
            self.assertEqual(self._status(service, "upgrade-alive"), "running")

    def test_recent_orphan_is_kept(self) -> None:
        """未超阈值 → 不动（避免误伤刚开始、尚未写 task.json 的任务）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _, _, service = self._service(tmpdir)
            self._running_task(service, "upgrade-fresh", age_seconds=30)

            self.assertEqual(service.converge_orphan_running_tasks(), [])
            self.assertEqual(self._status(service, "upgrade-fresh"), "running")

    def test_live_lease_is_kept(self) -> None:
        """租约存活 → 不动（runner 仍在执行）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _, database, service = self._service(tmpdir)
            self._running_task(service, "upgrade-leased", age_seconds=3 * 24 * 3600)
            expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
            heartbeat = datetime.now(timezone.utc).isoformat()
            with database.connection() as conn:
                conn.execute(
                    "INSERT INTO upgrade_task_leases (task_id, lease_owner, lease_expires_at, heartbeat_at, revision)"
                    " VALUES (?, ?, ?, ?, ?)",
                    ("upgrade-leased", "runner-test", expires, heartbeat, 1),
                )

            self.assertEqual(service.converge_orphan_running_tasks(), [])
            self.assertEqual(self._status(service, "upgrade-leased"), "running")

    def test_settlement_once_reports_converged(self) -> None:
        """守护线程入口必须真正调用收敛（否则等于没修）。"""
        from app.v2.upgrade.settlement import ensure_settlement_once

        with tempfile.TemporaryDirectory() as tmpdir:
            _, database, service = self._service(tmpdir)
            self._running_task(service, "upgrade-sweep", age_seconds=3 * 24 * 3600)

            result = ensure_settlement_once(service.settings, database)

            self.assertIn("upgrade-sweep", result.get("converged") or [])
            self.assertEqual(self._status(service, "upgrade-sweep"), "failed")


class RunnerHealthcheckReconcileTest(unittest.TestCase):
    def _settings(self, tmpdir: str):
        from app.v2.config import V2Settings

        project_dir = Path(tmpdir) / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        return V2Settings(
            data_root=Path(tmpdir),
            secret_key="hc-secret",
            app_version="v0.5.4",
            project_path_override=project_dir,
        )

    def test_skipped_when_upgrade_active(self) -> None:
        """有 running/pending 升级时绝不重建 runner（会打断执行）。"""
        from app.v2.database import V2Database
        from app.v2.tasks.models import TaskStatus, TaskType
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.settlement import reconcile_runner_healthcheck_once

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = self._settings(tmpdir)
            database = V2Database(settings)
            database.initialize()
            TaskService(database).create_task(
                "upgrade-busy", TaskType.UPGRADE, "执行系统升级",
                status=TaskStatus.RUNNING, progress=10, message="执行中",
            )

            result = reconcile_runner_healthcheck_once(settings, database)

            self.assertEqual(result.get("skipped"), "active_upgrade")

    def test_disabled_by_env(self) -> None:
        from app.v2.database import V2Database
        from app.v2.upgrade.settlement import HEALTHCHECK_RECONCILE_ENV, reconcile_runner_healthcheck_once

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = self._settings(tmpdir)
            database = V2Database(settings)
            database.initialize()
            os.environ[HEALTHCHECK_RECONCILE_ENV] = "0"
            try:
                result = reconcile_runner_healthcheck_once(settings, database)
            finally:
                os.environ.pop(HEALTHCHECK_RECONCILE_ENV, None)

            self.assertEqual(result.get("skipped"), "disabled")


if __name__ == "__main__":
    unittest.main()
