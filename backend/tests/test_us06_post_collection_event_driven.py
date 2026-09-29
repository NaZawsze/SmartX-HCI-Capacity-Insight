"""US-06：升级后采集改为事件驱动，5 秒常驻轮询降级为可关闭的兜底。

原状：`worker.py` 每 5 秒扫 `upgrades/*/` 来发现"该采集了"——事件驱动的事用高频轮询，
链路隐蔽、难观测、**没有任何开关**（用户想临时停掉做不到）。
现改为：升级收尾守护线程（US-30 的 settlement）扫到成功任务时**顺手投递**，
轮询降级为兜底且间隔可配置、0 即关闭。
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class PostUpgradeCollectionDispatchTest(unittest.TestCase):
    def _service(self, tmpdir: str):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService

        project_dir = Path(tmpdir) / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        settings = V2Settings(
            data_root=Path(tmpdir), secret_key="us06-secret", app_version="v0.5.3",
            project_path_override=project_dir,
        )
        database = V2Database(settings)
        database.initialize()
        return settings, database, TaskService(database)

    def _write_success_upgrade(self, settings, task_id: str = "upgrade-us06") -> Path:
        task_dir = Path(settings.upgrades_dir) / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "task_id": task_id,
            "status": "success",
            "target_version": "v0.5.3",
            "updated_at": "2026-09-29T10:00:00+00:00",
            "manifest": {
                "package_type": "platform",
                "version": "v0.5.3",
                "components": [{"type": "platform", "services": []}],
                "post_upgrade": {"platform_collection": True},
            },
        }
        (task_dir / "task.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return task_dir

    # ---------- 事件驱动投递 ----------

    def test_dispatch_creates_marker_for_successful_upgrade(self) -> None:
        from app.v2.worker import ensure_post_upgrade_collection_for

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, _ = self._service(tmpdir)
            task_dir = self._write_success_upgrade(settings)

            task_id = ensure_post_upgrade_collection_for(settings, database)

            self.assertTrue(task_id, "成功升级后必须投递采集任务")
            marker = task_dir / "post-upgrade-collection.json"
            self.assertTrue(marker.is_file(), "应写采集标记")
            self.assertEqual(json.loads(marker.read_text(encoding="utf-8"))["task_id"], task_id)

    def test_dispatch_is_idempotent(self) -> None:
        from app.v2.worker import ensure_post_upgrade_collection_for

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, _ = self._service(tmpdir)
            self._write_success_upgrade(settings)

            first = ensure_post_upgrade_collection_for(settings, database)
            second = ensure_post_upgrade_collection_for(settings, database)

            self.assertEqual(first, second, "重复调用不得产生第二个采集任务")
            markers = list(Path(settings.upgrades_dir).glob("*/post-upgrade-collection.json"))
            self.assertEqual(len(markers), 1, f"只应有一个标记，实际 {markers}")

    def test_no_upgrade_no_dispatch(self) -> None:
        from app.v2.worker import ensure_post_upgrade_collection_for

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, _ = self._service(tmpdir)
            self.assertEqual(ensure_post_upgrade_collection_for(settings, database), "")

    def test_failed_upgrade_is_not_dispatched(self) -> None:
        """失败升级不该触发采集（只对成功升级收尾采集）。"""
        from app.v2.worker import ensure_post_upgrade_collection_for

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, _ = self._service(tmpdir)
            self._write_success_upgrade(settings, "upgrade-failed")
            task_file = Path(settings.upgrades_dir) / "upgrade-failed" / "task.json"
            payload = json.loads(task_file.read_text(encoding="utf-8"))
            payload["status"] = "failed"
            task_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            self.assertEqual(ensure_post_upgrade_collection_for(settings, database), "")

    def test_settlement_sweep_triggers_dispatch(self) -> None:
        """核心：守护线程扫到成功任务时应**顺手投递**采集（不依赖 5 秒轮询）。"""
        from app.v2.upgrade.settlement import ensure_settlement_once

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, _ = self._service(tmpdir)
            task_dir = self._write_success_upgrade(settings)

            with mock.patch(
                "app.v2.upgrade.service.UpgradeService.create_post_upgrade_cleanup_task"
            ) as _cleanup:
                ensure_settlement_once(settings, database)

            self.assertTrue(
                (task_dir / "post-upgrade-collection.json").is_file(),
                "守护线程必须触发采集投递（事件驱动主路径）",
            )

    def test_dispatch_failure_does_not_break_settlement(self) -> None:
        """采集投递坏掉不得影响清理兜底（两件事互相独立）。"""
        from app.v2.upgrade.settlement import ensure_settlement_once

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, _ = self._service(tmpdir)
            self._write_success_upgrade(settings)

            with mock.patch(
                "app.v2.worker.ensure_post_upgrade_collection_for",
                side_effect=RuntimeError("boom"),
            ):
                result = ensure_settlement_once(settings, database)

            self.assertIn("created", result, "投递失败不得让整个 sweep 抛错")

    # ---------- 轮询降级为可关闭兜底 ----------

    def test_fallback_interval_is_configurable(self) -> None:
        from app.v2.worker import _int_setting

        class _Settings:
            pass

        original = os.environ.get("SMARTX_UPGRADE_POST_COLLECTION_FALLBACK_SECONDS")
        try:
            os.environ["SMARTX_UPGRADE_POST_COLLECTION_FALLBACK_SECONDS"] = "45"
            self.assertEqual(_int_setting(_Settings(), "SMARTX_UPGRADE_POST_COLLECTION_FALLBACK_SECONDS", 30), 45)
            os.environ["SMARTX_UPGRADE_POST_COLLECTION_FALLBACK_SECONDS"] = "0"
            self.assertEqual(_int_setting(_Settings(), "SMARTX_UPGRADE_POST_COLLECTION_FALLBACK_SECONDS", 30), 0)
            os.environ["SMARTX_UPGRADE_POST_COLLECTION_FALLBACK_SECONDS"] = "junk"
            self.assertEqual(_int_setting(_Settings(), "SMARTX_UPGRADE_POST_COLLECTION_FALLBACK_SECONDS", 30), 30)
            os.environ["SMARTX_UPGRADE_POST_COLLECTION_FALLBACK_SECONDS"] = "-5"
            self.assertEqual(_int_setting(_Settings(), "SMARTX_UPGRADE_POST_COLLECTION_FALLBACK_SECONDS", 30), 30)
        finally:
            if original is None:
                os.environ.pop("SMARTX_UPGRADE_POST_COLLECTION_FALLBACK_SECONDS", None)
            else:
                os.environ["SMARTX_UPGRADE_POST_COLLECTION_FALLBACK_SECONDS"] = original

    def test_worker_no_longer_hardcodes_5_seconds(self) -> None:
        """US-06 的直接判别：worker 不得再有固定 5 秒的采集轮询。"""
        from pathlib import Path as _Path

        worker = _Path(__file__).resolve().parent.parent / "app" / "v2" / "worker.py"
        text = worker.read_text(encoding="utf-8")
        # 采集兜底轮询那一段不得写死 seconds=5
        self.assertIn('id="post-upgrade-auto-collection"', text)
        self.assertNotIn(
            'seconds=5,\n        id="post-upgrade-auto-collection"',
            text,
            "采集轮询不得写死 5 秒",
        )
        self.assertIn("SMARTX_UPGRADE_POST_COLLECTION_FALLBACK_SECONDS", text)


if __name__ == "__main__":
    unittest.main()
