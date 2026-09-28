"""US-27 / US-29：放弃人工回滚后的失败收尾提示。

- US-29：人工回滚下线（保留实现与路由仅为老客户端兼容），**失败自动回滚路径不受影响**。
- US-27：`recovery/fail` 标记失败后不做任何清理，必须暴露「环境半迁移、需重跑升级收尾」与残留路径。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class FailCleanupHintTest(unittest.TestCase):
    def _service(self, tmpdir: str):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeService

        project_dir = Path(tmpdir) / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        settings = V2Settings(
            data_root=Path(tmpdir),
            secret_key="us27-secret",
            app_version="v0.5.3",
            project_path_override=project_dir,
        )
        database = V2Database(settings)
        database.initialize()
        return UpgradeService(settings, TaskService(database), project_path=project_dir)

    def _write_task(self, service, task_id: str, status: str, **extra) -> None:
        from app.v2.tasks.models import TaskStatus, TaskType

        task_dir = service.settings.upgrades_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        payload = {"task_id": task_id, "status": status, "manifest": {}, **extra}
        (task_dir / "task.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        # recovery_fail 末尾会写 tasks 表，先注册对应记录
        service.tasks.create_task(
            task_id, TaskType.UPGRADE, "执行系统升级",
            status=TaskStatus.RUNNING, progress=50, message="test",
        )

    # ---------- US-27：收尾提示 ----------

    def test_fail_exposes_cleanup_required_and_residual_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir)
            self._write_task(service, "t1", "running")

            with patch.object(service, "task_has_live_runner", return_value=False), patch.object(
                service, "_residual_legacy_paths", return_value=["/data/upgrades", "/data/smartx-capacity-insight-data"]
            ):
                result = service.recovery_fail("t1")

            self.assertEqual(result["status"], "failed")
            self.assertTrue(result["cleanup_required"], "有残留时必须提示需收尾")
            self.assertEqual(result["residual_paths"], ["/data/upgrades", "/data/smartx-capacity-insight-data"])
            self.assertIn("半迁移", result["error"])
            self.assertIn("/data/upgrades", result["error"])
            self.assertIn("post-cleanup", result["error"], "必须指明由升级后清理收尾")

    def test_no_residual_means_no_cleanup_required(self) -> None:
        """环境本来就干净时不该制造噪音提示。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir)
            self._write_task(service, "t2", "running")

            with patch.object(service, "task_has_live_runner", return_value=False), patch.object(
                service, "_residual_legacy_paths", return_value=[]
            ):
                result = service.recovery_fail("t2")

            self.assertFalse(result.get("cleanup_required"))
            self.assertEqual(result.get("residual_paths"), [])
            self.assertNotIn("半迁移", result["error"])

    def test_recovery_required_fail_also_reports_cleanup(self) -> None:
        """recovery_required 任务标记失败同样要提示收尾（不限于 stuck_running）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir)
            self._write_task(service, "t3", "recovery_required")

            with patch.object(service, "_residual_legacy_paths", return_value=["/opt/smartx-storage-forecast"]):
                result = service.recovery_fail("t3")

            self.assertTrue(result["cleanup_required"])
            self.assertEqual(result["residual_paths"], ["/opt/smartx-storage-forecast"])

    def test_residual_probe_is_read_only(self) -> None:
        """残留探测只能读，不能删改任何东西。"""
        import inspect

        from app.v2.upgrade.service.execution import ExecutionMixin

        source = inspect.getsource(ExecutionMixin._residual_legacy_paths)
        for forbidden in ("rmtree", "unlink", "rm -", "shutil", "mkdir", "write_text"):
            self.assertNotIn(forbidden, source, f"残留探测不得包含 {forbidden}")

    def test_recovery_fail_still_rejects_live_running_task(self) -> None:
        """runner 仍持有的 running 任务不得被标记失败（US-25 边界不能被 US-27 破坏）。"""
        from app.v2.upgrade.service._compat import HTTPException

        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir)
            self._write_task(service, "t4", "running")

            with patch.object(service, "task_has_live_runner", return_value=True):
                with self.assertRaises(HTTPException) as ctx:
                    service.recovery_fail("t4")

            self.assertEqual(ctx.exception.status_code, 400)


class ManualRollbackRetiredTest(unittest.TestCase):
    """US-29：人工回滚下线，但**失败自动回滚路径必须完好**。"""

    def test_manual_rollback_routes_still_exist(self) -> None:
        """保留路由仅为老客户端不 404（不删实现，避免破坏历史任务与在途客户端）。"""
        from app.v2.api.admin.upgrade import router

        paths = {route.path for route in router.routes}
        self.assertIn("/api/admin/upgrade/rollback/{task_id}", paths)
        self.assertIn("/api/admin/upgrade/recovery/{task_id}/rollback", paths)

    def test_automatic_rollback_path_untouched(self) -> None:
        """失败自动回滚能力必须仍然存在（`rolled_back` 终态 + 恢复步骤 + 恢复项目文件动作）。"""
        import inspect

        from app.v2.upgrade.service.execution import ExecutionMixin

        rollback_source = inspect.getsource(ExecutionMixin.rollback)
        self.assertIn("rollback_config", rollback_source, "回滚恢复步骤不得被 US-29 移除")
        self.assertIn("rolled_back", rollback_source, "rolled_back 终态不得被 US-29 移除")
        # 自动回滚的三个步骤定义仍在（执行失败时由服务层触发的路径所依赖）
        execute_source = inspect.getsource(ExecutionMixin.execute_task)
        self.assertIn('task["status"] = "failed"', execute_source, "执行失败仍应走失败分支（其内含自动回滚）")
        # 单飞守卫仍作用于人工回滚入口（US-23 不因 US-29 下线而失效）
        self.assertIn("_ensure_no_active_upgrade", rollback_source)

    def test_ui_no_longer_exposes_rollback_button(self) -> None:
        """前端不得再暴露「执行回滚」按钮（人工回滚已下线）。"""
        shared = Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "service" / "shared.tsx"
        text = shared.read_text(encoding="utf-8")
        self.assertNotIn('onRecovery("rollback")', text, "恢复操作区不得再提供回滚按钮")
        self.assertIn('onRecovery("fail")', text, "「标记失败」必须保留（它是 US-29 后的唯一出路）")
        self.assertIn('onRecovery("continue")', text, "「继续执行」必须保留")
        # 自动回滚的内部步骤名仍需存在
        self.assertIn("rollback_healthcheck", text)


if __name__ == "__main__":
    unittest.main()
