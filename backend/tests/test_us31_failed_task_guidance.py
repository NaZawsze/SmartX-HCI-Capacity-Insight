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
from unittest import mock


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


class ResidualPathFalsePositiveTest(unittest.TestCase):
    """US-31：残留探测必须在**宿主**视角判断，否则挂载点永远误报。

    `.12` 实测：7 个 legacy 宿主路径全部已清空（环境干净），但 web-api 容器内
    `/data/backups`、`/data/exports`、`/data/compose-runtime`、`/prometheus-data`
    是 bind mount 挂载点、必然存在 → 旧实现报 5 个"残留"，把管理员引向无意义的收尾操作。
    """

    MOUNT_MAP = {
        "/data/backups": "/data/smartx-storage-forecast/backups",
        "/data/exports": "/data/smartx-storage-forecast/exports",
        "/data/compose-runtime": "/data/smartx-storage-forecast/compose-runtime",
        "/prometheus-data": "/data/smartx-storage-forecast/prometheus",
    }

    def _service(self, tmpdir: str):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeService

        project_dir = Path(tmpdir) / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        settings = V2Settings(
            data_root=Path(tmpdir), secret_key="us31b-secret", app_version="v0.5.3",
            project_path_override=project_dir,
        )
        database = V2Database(settings)
        database.initialize()
        return settings, database, UpgradeService(settings, TaskService(database), project_path=project_dir)

    def test_mount_points_are_not_reported_as_residual(self) -> None:
        """判别：容器内挂载点存在 ≠ 宿主 legacy 残留。

        构造宿主视角：目标布局目录（`/data/smartx-storage-forecast/*`）存在——那是**正常布局**、
        不是残留；真正的 legacy 宿主路径（`/opt/...`、`/data/upgrades` 等）也已清空。
        期望：**一条残留都不报**。旧实现会因为容器内挂载点必然存在而误报 4 条。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            _settings, _database, service = self._service(tmpdir)
            service._container_mount_source = lambda dest: self.MOUNT_MAP.get(dest, "")  # type: ignore[method-assign]

            def fake(self):
                # 宿主视角：目标布局目录存在（正常布局），legacy 路径都不存在
                return str(self).startswith("/data/smartx-storage-forecast/")

            with mock.patch.object(Path, "exists", fake), mock.patch.object(Path, "is_dir", fake):
                self.assertEqual(service._residual_legacy_paths(), [])

    def test_real_legacy_paths_still_reported(self) -> None:
        """修误报的同时不能漏报：真 legacy 路径残留必须仍然报出来。

        真实语义：宿主上 `/opt/smartx-storage-forecast`、`/data/upgrades` 确实还在
        （半迁移残留），而目标布局目录也存在（正常）。挂载点经映射后指向目标布局目录，
        因此**不该**被报成残留。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            _settings, _database, service = self._service(tmpdir)
            service._container_mount_source = lambda dest: self.MOUNT_MAP.get(dest, "")  # type: ignore[method-assign]
            # 宿主上真实存在的：目标布局目录（正常）+ 两个真 legacy 残留
            present = {
                "/data/smartx-storage-forecast/backups",
                "/data/smartx-storage-forecast/exports",
                "/data/smartx-storage-forecast/compose-runtime",
                "/data/smartx-storage-forecast/prometheus",
                "/opt/smartx-storage-forecast",
                "/data/upgrades",
            }

            def fake(self):
                return str(self) in present

            with mock.patch.object(Path, "exists", fake), mock.patch.object(Path, "is_dir", fake):
                residual = service._residual_legacy_paths()

            self.assertEqual(sorted(residual), ["/data/upgrades", "/opt/smartx-storage-forecast"])
            for mount_point in self.MOUNT_MAP:
                self.assertNotIn(mount_point, residual, f"挂载点 {mount_point} 不该被报成残留")

    def test_degrades_to_container_path_when_mapping_unavailable(self) -> None:
        """拿不到映射时保守退化：仍能报出挂载点残留（宁多报不漏报）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _settings, _database, service = self._service(tmpdir)
            service._container_mount_source = lambda dest: None  # type: ignore[method-assign]
            legacy = {"/prometheus-data"}

            def fake(self):
                return str(self) in legacy

            with mock.patch.object(Path, "exists", fake), mock.patch.object(Path, "is_dir", fake):
                self.assertEqual(service._residual_legacy_paths(), ["/prometheus-data"])

    def test_maps_container_path_to_host_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _settings, _database, service = self._service(tmpdir)
            service._container_mount_source = lambda dest: self.MOUNT_MAP.get(dest, "")  # type: ignore[method-assign]

            self.assertEqual(
                service._legacy_residual_host_path("/data/backups"), Path("/data/smartx-storage-forecast/backups")
            )
            self.assertEqual(
                service._legacy_residual_host_path("/prometheus-data"), Path("/data/smartx-storage-forecast/prometheus")
            )
            # 非挂载点：容器与宿主同路径
            self.assertEqual(service._legacy_residual_host_path("/opt/smartx-storage-forecast"),
                             Path("/opt/smartx-storage-forecast"))
            self.assertEqual(service._legacy_residual_host_path("/data/upgrades"), Path("/data/upgrades"))

    def test_falls_back_to_container_path_when_inspect_unavailable(self) -> None:
        """拿不到映射时保守用容器路径——宁可多报也不漏报。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _settings, _database, service = self._service(tmpdir)
            service._container_mount_source = lambda dest: None  # type: ignore[method-assign]
            self.assertEqual(service._legacy_residual_host_path("/data/backups"), Path("/data/backups"))

    def test_inspect_exception_does_not_break_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _settings, _database, service = self._service(tmpdir)

            def boom(_dest):
                raise RuntimeError("docker unavailable")

            service._container_mount_source = boom  # type: ignore[method-assign]
            self.assertEqual(service._legacy_residual_host_path("/data/backups"), Path("/data/backups"))
            # 探测整体不应抛异常
            self.assertIsInstance(service._residual_legacy_paths(), list)


if __name__ == "__main__":
    unittest.main()
