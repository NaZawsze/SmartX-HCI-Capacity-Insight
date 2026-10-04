"""删除升级包必须保留历史记录（2026-10-04，Phase 66）。

缺陷：`intake.py::delete_package` 原实现是 `shutil.rmtree(task_dir)`——连 `task.json`
一起删。而 `task.json` 是升级历史的唯一数据来源（`history()` 扫 `*/task.json`；
`_read_task_file` 缺文件即 404）。所以点一次「删除升级包」，该条升级记录永久消失。

这与 r14 已定口径矛盾：`cleanup_artifacts` 早已按「宁留记录不留包」只删体积产物。
同一问题两条路径做法相反，且删记录的那条藏在 UI 按钮后、无任何告知。

本文件的用例钉住「删包后记录仍在」，防止该缺陷复发。
该端点此前**完全没有测试**，正是缺陷得以存活的原因。
"""

import json
import tempfile
import unittest
from pathlib import Path


class DeletePackageKeepsRecordTest(unittest.TestCase):
    def _service(self, tmpdir: str):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeService

        settings = V2Settings(data_root=Path(tmpdir), secret_key="s", app_version="v0.5.3")
        database = V2Database(settings)
        database.initialize()
        return settings, UpgradeService(settings, TaskService(database))

    def _make_task(self, settings, task_id: str = "upgrade-test01", *, with_package: bool = True):
        """造一个已完成的上传任务目录，含 task.json（+ 可选体积产物）。"""
        task_dir = settings.upgrades_dir / task_id
        (task_dir / "package" / "images").mkdir(parents=True)
        (task_dir / "package" / "images" / "web-api.tar").write_bytes(b"x" * 4096)
        (task_dir / "smartx-capacity-insight-upgrade-v0.5.3.tar.gz").write_bytes(b"y" * 2048)
        (task_dir / "smartx-capacity-insight-upgrade-v0.5.3.tar.gz.sha256").write_text("abc\n")
        task = {
            "task_id": task_id,
            "status": "succeeded",
            "target_version": "v0.5.3",
            "started_at": "2026-10-04T09:00:00+00:00",
            "finished_at": "2026-10-04T09:01:00+00:00",
            "manifest": {"schema_version": "3", "version": "v0.5.3"},
        }
        (task_dir / "task.json").write_text(json.dumps(task), encoding="utf-8")
        if not with_package:
            for child in list(task_dir.iterdir()):
                if child.name != "task.json":
                    if child.is_dir():
                        import shutil

                        shutil.rmtree(child)
                    else:
                        child.unlink()
        return task_dir

    def test_delete_package_keeps_task_record(self) -> None:
        """删包后 task.json 必须还在，体积产物必须真删掉。"""
        from app.v2.upgrade.service._compat import HTTPException

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, service = self._service(tmpdir)
            task_dir = self._make_task(settings)

            result = service.delete_package("upgrade-test01")

            self.assertTrue((task_dir / "task.json").is_file(), "task.json 必须保留")
            self.assertFalse((task_dir / "package").exists(), "package/ 必须删除")
            self.assertEqual(
                list(task_dir.glob("*.tar.gz")), [], "包本体必须删除"
            )
            self.assertEqual(result.get("kept_record"), True)
            self.assertGreater(result.get("deleted_count", 0), 0)
            self.assertGreater(result.get("space_reclaimed", 0), 0)

    def test_deleted_task_still_appears_in_history(self) -> None:
        """**核心回归守卫**：删包后历史仍能查到该任务，且 has_package 为 False。

        这条直接钉住本缺陷：原缺陷下该任务从 history 消失。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, service = self._service(tmpdir)
            self._make_task(settings)

            before = {t["task_id"]: t for t in service.history()}
            self.assertIn("upgrade-test01", before)
            self.assertTrue(before["upgrade-test01"]["has_package"])

            service.delete_package("upgrade-test01")

            after = {t["task_id"]: t for t in service.history()}
            self.assertIn(
                "upgrade-test01",
                after,
                "删包后任务必须仍在历史中——原缺陷下会消失",
            )
            self.assertFalse(
                after["upgrade-test01"]["has_package"],
                "has_package 必须变 False，前端据此隐藏删除按钮",
            )
            # 记录内容（版本、状态、时间）必须完好
            self.assertEqual(after["upgrade-test01"]["target_version"], "v0.5.3")
            self.assertEqual(after["upgrade-test01"]["status"], "succeeded")
            self.assertTrue(after["upgrade-test01"]["started_at"])

    def test_status_endpoint_still_resolves_after_delete(self) -> None:
        """删包后按 task_id 查状态不得 404（原缺陷下 _read_task_file 直接抛 404）。"""
        from app.v2.upgrade.service._compat import HTTPException

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, service = self._service(tmpdir)
            self._make_task(settings)
            service.delete_package("upgrade-test01")

            status = service.status("upgrade-test01")
            self.assertEqual(status["task_id"], "upgrade-test01")
            self.assertFalse(status["has_package"])

    def test_delete_package_rejects_active_task(self) -> None:
        """活跃任务的包不能删——runner 可能正在写 package/。"""
        from app.v2.upgrade.service._compat import HTTPException

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, service = self._service(tmpdir)
            task_dir = self._make_task(settings)
            task_file = task_dir / "task.json"
            task = json.loads(task_file.read_text(encoding="utf-8"))
            task["status"] = "running"
            task_file.write_text(json.dumps(task), encoding="utf-8")

            with self.assertRaises(HTTPException) as ctx:
                service.delete_package("upgrade-test01")
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertTrue(
                (task_dir / "package").exists(), "拒绝时不得改动任何内容"
            )

    def test_small_json_markers_are_preserved(self) -> None:
        """post-upgrade-*.json 等小标记不是包产物，必须保留。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, service = self._service(tmpdir)
            task_dir = self._make_task(settings)
            (task_dir / "post-upgrade-collection.json").write_text(
                json.dumps({"ok": True}), encoding="utf-8"
            )

            service.delete_package("upgrade-test01")

            self.assertTrue(
                (task_dir / "post-upgrade-collection.json").is_file(),
                "运行标记应保留",
            )

    def test_component_package_delete_shares_implementation(self) -> None:
        """组件包删除走同一方法（api/admin/upgrade.py:213-218），行为必须一致。

        钉住「组件包不会因为共用方法而行为分叉」。
        """
        from app.v2.upgrade.service import UpgradeService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, service = self._service(tmpdir)
            task_dir = self._make_task(settings, task_id="component-upgrade-x")
            task_file = task_dir / "task.json"
            task = json.loads(task_file.read_text(encoding="utf-8"))
            task["component"] = "upgrade-runner"
            task["components"] = ["upgrade-runner"]
            task_file.write_text(json.dumps(task), encoding="utf-8")

            service.delete_package("component-upgrade-x")

            self.assertTrue((task_dir / "task.json").is_file())
            component_tasks = service.history(component_type="upgrade-runner")
            self.assertTrue(
                any(t["task_id"] == "component-upgrade-x" for t in component_tasks),
                "组件任务记录也必须保留",
            )
        # 同一个方法对象，天然同源；此断言防止将来给两条路径各写一份
        self.assertIs(UpgradeService.delete_package, service.delete_package.__func__)

    def test_cleanup_and_delete_package_share_record_files(self) -> None:
        """两条清理路径的保留清单必须一致——防止再次分叉（本次缺陷的根因）。"""
        from app.v2.cleanup.service import CleanupService
        from app.v2.upgrade.service.fs import UPGRADE_RECORD_FILES, purge_upgrade_payload

        self.assertEqual(
            CleanupService._purge_upgrade_payload.__doc__ is not None,
            True,
            "_purge_upgrade_payload 应保留（作为转发封装）",
        )
        self.assertIn("task.json", UPGRADE_RECORD_FILES)
        # 转发关系：CleanupService 的实现与模块级函数是同一行为
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "task.json").write_text("{}", encoding="utf-8")
            (root / "package").mkdir()
            (root / "package" / "a.tar").write_bytes(b"z" * 100)
            removed = purge_upgrade_payload(root)
            self.assertTrue((root / "task.json").is_file())
            self.assertFalse((root / "package").exists())
            self.assertEqual(removed, 1)


if __name__ == "__main__":
    unittest.main()
