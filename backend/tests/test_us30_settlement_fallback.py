"""US-30：升级收尾兜底——post-cleanup 不得依赖客户端轮询。

判别用例：**全程不调用 status 接口**，只跑 `ensure_settlement_once()`，
已成功但缺清理任务的任务仍必须被补建（修复前永远不会被创建）。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class SettlementFallbackTest(unittest.TestCase):
    def _service(self, tmpdir: str):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeService

        project_dir = Path(tmpdir) / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        settings = V2Settings(
            data_root=Path(tmpdir), secret_key="us30-secret", app_version="v0.5.3",
            project_path_override=project_dir,
        )
        database = V2Database(settings)
        database.initialize()
        return settings, database, UpgradeService(settings, TaskService(database), project_path=project_dir)

    def _write_upgrade_task(self, settings, task_id: str, status: str, *, with_legacy: bool = True) -> None:
        manifest: dict = {
            "version": "v0.5.3",
            "components": [{"type": "platform", "services": []}],
            "post_upgrade": {"create_cleanup_task": True, "auto_collection": False, "platform_collection": True},
        }
        if with_legacy:
            manifest["legacy_cleanup"] = {"legacy_projects": ["old"], "legacy_paths": ["/opt/old"]}
        task_dir = settings.upgrades_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        payload = {"task_id": task_id, "status": status, "manifest": manifest, "target_version": "v0.5.3"}
        (task_dir / "task.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _cleanup_exists(self, settings, task_id: str) -> bool:
        return (settings.upgrades_dir / f"post-cleanup-{task_id}" / "task.json").is_file()

    # ---------- 判别用例 ----------

    def test_settles_without_any_status_poll(self) -> None:
        """核心判别：从不调用 status 接口，兜底仍补建清理任务。"""
        from app.v2.upgrade.settlement import ensure_settlement_once

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, _ = self._service(tmpdir)
            self._write_upgrade_task(settings, "upgrade-noPoll", "success")
            self.assertFalse(self._cleanup_exists(settings, "upgrade-noPoll"))

            result = ensure_settlement_once(settings, database)

            self.assertEqual(result["created"], ["upgrade-noPoll"])
            self.assertEqual(result["failed"], [])
            self.assertTrue(self._cleanup_exists(settings, "upgrade-noPoll"), "兜底必须补建清理任务")

    def test_creates_legit_cleanup_task_plan(self) -> None:
        """补建出来的必须是可执行的清理任务（有 execution_plan + legacy_cleanup）。"""
        from app.v2.upgrade.settlement import ensure_settlement_once

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, _ = self._service(tmpdir)
            self._write_upgrade_task(settings, "upgrade-plan", "success")
            ensure_settlement_once(settings, database)
            cleanup = json.loads(
                (settings.upgrades_dir / "post-cleanup-upgrade-plan" / "task.json").read_text(encoding="utf-8")
            )
            self.assertEqual(cleanup["task_type"], "post_upgrade_cleanup")
            self.assertEqual(cleanup["parent_task_id"], "upgrade-plan")
            self.assertTrue(cleanup.get("execution_plan"), "清理任务必须有执行计划")
            parent = json.loads((settings.upgrades_dir / "upgrade-plan" / "task.json").read_text(encoding="utf-8"))
            self.assertEqual(parent.get("post_upgrade_cleanup_task_id"), "post-cleanup-upgrade-plan")

    # ---------- 幂等 ----------

    def test_idempotent(self) -> None:
        from app.v2.upgrade.settlement import ensure_settlement_once

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, _ = self._service(tmpdir)
            self._write_upgrade_task(settings, "upgrade-idem", "success")

            first = ensure_settlement_once(settings, database)
            second = ensure_settlement_once(settings, database)

            self.assertEqual(first["created"], ["upgrade-idem"])
            self.assertEqual(second["created"], [], "已补建过不得重复创建")
            self.assertEqual(second["failed"], [])

    # ---------- 扫描范围 ----------

    def test_only_settled_tasks_are_swept(self) -> None:
        """只有 success/succeeded + 有 legacy_cleanup 才补建；其它状态一律不动。"""
        from app.v2.upgrade.settlement import scan_missing_settlement

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, _, _ = self._service(tmpdir)
            self._write_upgrade_task(settings, "ok-1", "success")
            self._write_upgrade_task(settings, "ok-2", "succeeded")
            self._write_upgrade_task(settings, "failed-1", "failed")
            self._write_upgrade_task(settings, "rolled-1", "rolled_back")
            self._write_upgrade_task(settings, "running-1", "running")
            self._write_upgrade_task(settings, "pending-1", "pending")
            self._write_upgrade_task(settings, "no-legacy", "success", with_legacy=False)

            found = {task_id for task_id, _ in scan_missing_settlement(settings)}

            self.assertEqual(found, {"ok-1", "ok-2"})

    def test_existing_cleanup_is_not_recreated(self) -> None:
        from app.v2.upgrade.settlement import ensure_settlement_once, scan_missing_settlement

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, _ = self._service(tmpdir)
            self._write_upgrade_task(settings, "upgrade-has", "success")
            ensure_settlement_once(settings, database)
            # 父任务记录 id + 目录有 task.json → 不应再被扫到
            self.assertEqual(scan_missing_settlement(settings), [])
            self.assertEqual(ensure_settlement_once(settings, database)["created"], [])

    def test_scan_is_read_only(self) -> None:
        """扫描不得修改任何文件。"""
        from app.v2.upgrade.settlement import scan_missing_settlement

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, _, _ = self._service(tmpdir)
            self._write_upgrade_task(settings, "upgrade-ro", "success")
            before = (settings.upgrades_dir / "upgrade-ro" / "task.json").read_text(encoding="utf-8")
            before_listing = sorted(p.name for p in settings.upgrades_dir.iterdir())
            scan_missing_settlement(settings)
            self.assertEqual((settings.upgrades_dir / "upgrade-ro" / "task.json").read_text(encoding="utf-8"), before)
            self.assertEqual(sorted(p.name for p in settings.upgrades_dir.iterdir()), before_listing)

    # ---------- 开关 ----------

    def test_daemon_disabled_by_zero(self) -> None:
        from app.v2.upgrade.settlement import start_settlement_daemon

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, _ = self._service(tmpdir)
            self.assertIsNone(start_settlement_daemon(settings, database, interval_seconds=0))

    def test_daemon_runs_once_immediately(self) -> None:
        """守护线程启动即跑一次（覆盖 web-api 重启后仍未收尾的历史任务）。"""
        import threading
        import time

        from app.v2.upgrade.settlement import start_settlement_daemon

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, _ = self._service(tmpdir)
            self._write_upgrade_task(settings, "upgrade-boot", "success")
            stop = start_settlement_daemon(settings, database, interval_seconds=3600)
            self.assertIsNotNone(stop)
            try:
                deadline = time.time() + 5
                while time.time() < deadline and not self._cleanup_exists(settings, "upgrade-boot"):
                    time.sleep(0.1)
                self.assertTrue(self._cleanup_exists(settings, "upgrade-boot"), "启动即应补建")
            finally:
                stop.set()

    def test_main_wires_settlement_daemon(self) -> None:
        import inspect

        from app.v2 import main

        source = inspect.getsource(main.create_app)
        self.assertIn("start_settlement_daemon", source, "web-api 必须接线收尾兜底守护线程")
        self.assertIn("settlement_stop_event.set()", source, "shutdown 必须停止该线程")


if __name__ == "__main__":
    unittest.main()
