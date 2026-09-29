"""US-31：任何 failed 任务都必须有收尾指引，不能只有走人工 recovery/fail 的那些。

背景（`.12` 实测）：早期动作失败（`image.load` 校验失败）由 runner 自行判定为 `failed`，
不经过任何人工入口。此前这条路上：
  - `available_recovery_actions` 是 `None`（不是缺失）→ 前端 `?.includes()` 拿不到任何按钮；
  - US-27 的 `cleanup_required` / 残留路径清单只挂在人工 `recovery/fail` 上 → 完全没出现。

`None` 的成因是 `setdefault` 陷阱：键存在且值为 `None` 时 `setdefault` **不会**替换。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class FailedTaskGuidanceTest(unittest.TestCase):
    def _service(self, tmpdir: str):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeService

        project_dir = Path(tmpdir) / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        settings = V2Settings(
            data_root=Path(tmpdir), secret_key="us31-secret", app_version="v0.5.3",
            project_path_override=project_dir,
        )
        database = V2Database(settings)
        database.initialize()
        return settings, database, UpgradeService(settings, TaskService(database), project_path=project_dir)

    def _task(self, task_id: str, **overrides) -> dict:
        task = {
            "task_id": task_id,
            "status": "failed",
            "target_version": "v0.5.3",
            "error": "镜像归档校验失败：web-api.tar",
            "manifest": {"version": "v0.5.3"},
        }
        task.update(overrides)
        return task

    # ---------- 判别用例 ----------

    def test_none_actions_becomes_fail_entry(self) -> None:
        """判别：available_recovery_actions=None（.12 真实形态）必须变成可用入口。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, _database, service = self._service(tmpdir)
            public = service._public_task(self._task("upgrade-f1", available_recovery_actions=None))

            self.assertEqual(public["available_recovery_actions"], ["fail"])

    def test_absent_actions_gets_fail_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, _database, service = self._service(tmpdir)
            public = service._public_task(self._task("upgrade-f2"))
            self.assertEqual(public["available_recovery_actions"], ["fail"])

    def test_residual_paths_and_guidance_reported(self) -> None:
        """有 legacy 残留时必须给出可执行指引。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _settings, _database, service = self._service(tmpdir)
            # 模拟探测到残留
            service._residual_legacy_paths = lambda: ["/data/upgrades", "/prometheus-data"]  # type: ignore[method-assign]

            public = service._public_task(self._task("upgrade-f3", available_recovery_actions=None))

            self.assertTrue(public["cleanup_required"])
            self.assertEqual(public["residual_paths"], ["/data/upgrades", "/prometheus-data"])
            guidance = public["cleanup_guidance"]
            self.assertIn("/data/upgrades", guidance)
            self.assertIn("/prometheus-data", guidance)
            self.assertIn("post-cleanup", guidance)
            self.assertIn("不要开始新的升级任务", guidance)

    def test_no_residual_no_guidance_but_still_has_fail_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _settings, _database, service = self._service(tmpdir)
            service._residual_legacy_paths = lambda: []  # type: ignore[method-assign]

            public = service._public_task(self._task("upgrade-f4", available_recovery_actions=None))

            self.assertFalse(public["cleanup_required"])
            self.assertNotIn("cleanup_guidance", public)
            self.assertEqual(public["available_recovery_actions"], ["fail"])

    def test_preserves_existing_actions(self) -> None:
        """已有动作列表不得被覆盖。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _settings, _database, service = self._service(tmpdir)
            public = service._public_task(
                self._task("upgrade-f5", status="recovery_required", available_recovery_actions=["continue", "rollback"])
            )
            self.assertEqual(public["available_recovery_actions"], ["continue", "rollback"])

    def test_success_task_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _settings, _database, service = self._service(tmpdir)
            public = service._public_task(self._task("upgrade-ok", status="success", available_recovery_actions=None))
            self.assertEqual(public["available_recovery_actions"], [])

    def test_engine_normalizes_none_actions(self) -> None:
        """判别：runner 侧 setdefault 陷阱修正——None 必须被显式归一为 []。"""
        from app.upgrade_runner.engine import UpgradeEngine
        from app.upgrade_runner.store import TaskStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = TaskStore(Path(tmpdir) / "upgrade-1")
            store.save(
                {
                    "task_id": "upgrade-1",
                    "status": "pending",
                    "available_recovery_actions": None,
                    "recovery_status": None,
                    "logs": None,
                    "execution_plan": {
                        "protocol_version": 1,
                        "required_capabilities": [],
                        "actions": [],
                    },
                }
            )
            engine = UpgradeEngine(store, handlers={}, context={})
            engine.run()

            saved = store.load()
            self.assertEqual(saved["available_recovery_actions"], [])
            self.assertEqual(saved["recovery_status"], "none")
            self.assertEqual(saved["logs"], [])


if __name__ == "__main__":
    unittest.main()
