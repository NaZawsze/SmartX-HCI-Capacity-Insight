"""#89 任务终态收敛竞态：幽灵 running 行的识别、收敛与可见性。

场景（2026-10-14 `.12`/`.14` 跨机坐实）：升级 apply 成功后 post-cleanup（或产品
「删除升级包」）回收任务目录，但 tasks 表行停在 `running`——cancel/recovery/delete
全部 404「升级任务不存在。」，cleanup 被挡 6 小时（GHOST_TASK_STALE_SECONDS）。

本文件锁定三件事：
1. 清理服务能立即识别「runner 执行过且已释放 + 目录不存在」的幽灵行（正面证据 =
   状态文件 rollback_anchors 持久段），不再等 6h；无证据时维持原陈旧规则；
2. recovery/fail 能收敛无 task.json 的 DB 行（有活租约仍拒绝）；
3. status() 对幽灵行回落 DB 视图而不是 404（升级中心可见、可操作）。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.upgrade_runner.statefile import state_file_path  # noqa: E402
from app.v2.config import V2Settings  # noqa: E402
from app.v2.database import V2Database  # noqa: E402
from app.v2.tasks.models import TaskStatus, TaskType  # noqa: E402
from app.v2.tasks.service import TaskService  # noqa: E402
from app.v2.upgrade.service import UpgradeCommandExecutor, UpgradeService  # noqa: E402
from app.v2.upgrade.service._compat import HTTPException  # noqa: E402
from app.v2.cleanup.service import CleanupService  # noqa: E402


class GhostTaskConvergenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = V2Settings(
            data_root=Path(self.tmp.name), secret_key="ghost-secret", app_version="v0.5.4"
        )
        self.database = V2Database(self.settings)
        self.database.initialize()
        self.tasks = TaskService(self.database)
        self.project_path = Path(self.tmp.name) / "project"

    # ---- 工具 ------------------------------------------------------------
    def _service(self) -> UpgradeService:
        class FakeExecutor(UpgradeCommandExecutor):
            def run(self, command, *, cwd=None):  # pragma: no cover
                return None

            def output(self, command, *, cwd=None):  # pragma: no cover
                return ""

        return UpgradeService(
            self.settings, self.tasks, executor=FakeExecutor(), project_path=self.project_path
        )

    def _running_db_row(self, task_id: str) -> None:
        """只在 tasks 表留 running 行——模拟产物被回收后的幽灵行。"""
        self.tasks.create_task(
            task_id, TaskType.UPGRADE, "执行系统升级",
            status=TaskStatus.RUNNING, progress=80, message="执行系统升级/准备运行目录",
        )

    def _write_rollback_anchor(self, task_id: str) -> None:
        """写 runner 状态文件 rollback_anchors 持久段（runner 执行过的正面证据）。"""
        path = state_file_path(self.settings.sqlite_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"rollback_anchors": {task_id: {"previous_version": "v0.5.3"}}}
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _add_lease(self, task_id: str, *, expires_in: int, heartbeat_ago: int = 0) -> None:
        now = datetime.now(timezone.utc)
        with self.database.connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO upgrade_task_leases"
                " (task_id, lease_owner, lease_expires_at, heartbeat_at, revision)"
                " VALUES (?, 'runner-a', ?, ?, 0)",
                (
                    task_id,
                    (now + timedelta(seconds=expires_in)).isoformat(),
                    (now - timedelta(seconds=heartbeat_ago)).isoformat(),
                ),
            )

    def _two_cleanup_targets(self) -> None:
        """造两个可清理的旧任务目录（保持最近 1 个、清更旧 1 个）。"""
        for name, age in (("upgrade-old", 5000), ("upgrade-new", 10)):
            d = self.settings.upgrades_dir / name
            (d / "package").mkdir(parents=True)
            (d / "package" / "a.tar").write_bytes(b"z" * 2048)
            (d / "task.json").write_text("{}", encoding="utf-8")
            import os

            stamp = datetime.now().timestamp() - age
            os.utime(d, (stamp, stamp))

    # ---- 清理服务：幽灵识别 ----------------------------------------------
    def test_fresh_ghost_with_anchor_does_not_block_cleanup(self):
        """幽灵行（runner 执行过且释放 + 目录不存在）立即放行，不再等 6 小时。"""
        self._running_db_row("upgrade-ghost-fresh")
        self._write_rollback_anchor("upgrade-ghost-fresh")
        self.assertFalse((self.settings.upgrades_dir / "upgrade-ghost-fresh").exists())
        self._two_cleanup_targets()

        result = CleanupService(self.settings, self.tasks).cleanup_artifacts()

        self.assertTrue(result["ok"], f"新鲜幽灵行不应阻塞清理：{result.get('message')}")
        self.assertGreater(result["deleted_count"], 0)

    def test_anchor_with_live_lease_still_blocks_cleanup(self):
        """有活租约 = runner 还在执行，即使目录暂时不在也必须阻塞（防误放行真任务）。"""
        self._running_db_row("upgrade-live-nodir")
        self._write_rollback_anchor("upgrade-live-nodir")
        self._add_lease("upgrade-live-nodir", expires_in=120)
        self._two_cleanup_targets()

        result = CleanupService(self.settings, self.tasks).cleanup_artifacts()

        self.assertFalse(result["ok"], "租约存活的任务必须继续阻塞清理")

    def test_running_without_dir_and_without_anchor_still_blocks(self):
        """无锚点证据的目录缺失 running 行：维持「新建窗口」保护，仍阻塞。"""
        self._running_db_row("upgrade-fresh-window")
        self._two_cleanup_targets()

        result = CleanupService(self.settings, self.tasks).cleanup_artifacts()

        self.assertFalse(result["ok"], "无正面证据时不得放行（防误清刚创建的任务）")

    def test_stale_ghost_without_anchor_still_ignored(self):
        """锚点被历史淘汰的老幽灵：维持 6h 陈旧规则（backward compatible）。"""
        self._running_db_row("upgrade-ghost-old")
        with self.tasks.database.connection() as conn:
            conn.execute(
                "UPDATE tasks SET updated_at = ?, created_at = ? WHERE id = ?",
                (
                    (datetime.now(timezone.utc) - timedelta(days=80)).isoformat(),
                    (datetime.now(timezone.utc) - timedelta(days=81)).isoformat(),
                    "upgrade-ghost-old",
                ),
            )
        self._two_cleanup_targets()

        result = CleanupService(self.settings, self.tasks).cleanup_artifacts()

        self.assertTrue(result["ok"], "陈旧无锚点幽灵仍应按 6h 规则放行")

    # ---- recovery/fail：DB-only 收敛 --------------------------------------
    def test_recovery_fail_converges_orphan_db_row(self):
        """task.json 丢失 + running + 无租约 → 管理员可直接收敛 DB 行。"""
        self._running_db_row("upgrade-orphan")
        self._write_rollback_anchor("upgrade-orphan")

        result = self._service().recovery_fail("upgrade-orphan")

        self.assertEqual(result["status"], "failed")
        self.assertTrue(result.get("orphan_converged"))
        row = self.tasks.get_task("upgrade-orphan")
        self.assertEqual(row["status"], "failed")
        self.assertIn("已被回收", row["message"])
        self.assertIn("/api/system/health", row["message"])

    def test_recovery_fail_rejects_orphan_with_live_lease(self):
        """runner 仍持有（租约存活）→ 拒绝标记失败。"""
        self._running_db_row("upgrade-held")
        self._add_lease("upgrade-held", expires_in=120)

        with self.assertRaises(HTTPException) as ctx:
            self._service().recovery_fail("upgrade-held")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("仍被 upgrade-runner 持有", ctx.exception.detail)
        self.assertEqual(self.tasks.get_task("upgrade-held")["status"], "running")

    def test_recovery_fail_unknown_id_raises_404(self):
        with self.assertRaises(HTTPException) as ctx:
            self._service().recovery_fail("upgrade-missing")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_recovery_fail_rejects_terminal_row(self):
        """已终态的行再点标记失败 → 400（幂等拒绝），不会被改成 failed。"""
        self._running_db_row("upgrade-done")
        self.tasks.update_task("upgrade-done", status=TaskStatus.FAILED, progress=100, message="x")

        with self.assertRaises(HTTPException) as ctx:
            self._service().recovery_fail("upgrade-done")

        self.assertEqual(ctx.exception.status_code, 400)

    # ---- status：DB 回落 ---------------------------------------------------
    def test_status_falls_back_to_db_view_for_ghost_row(self):
        """幽灵行的任务详情不再 404：回落 DB 视图并暴露「标记失败」入口。"""
        self._running_db_row("upgrade-ghost-view")

        view = self._service().status("upgrade-ghost-view")

        self.assertEqual(view["status"], "running")
        self.assertTrue(view["artifacts_missing"])
        self.assertTrue(view["runner_lost"])
        self.assertIn("fail", view["available_recovery_actions"])

    def test_status_unknown_id_raises_404(self):
        with self.assertRaises(HTTPException) as ctx:
            self._service().status("upgrade-missing")
        self.assertEqual(ctx.exception.status_code, 404)

    # ---- 契约：损坏文件不得被 DB 回落掩盖 ---------------------------------
    def test_status_corrupt_task_json_still_reports_corruption(self):
        """task.json 在但读不了 → 保留「已损坏」干净 404，不用 DB 视图掩盖。"""
        bad = self.settings.upgrades_dir / "upgrade-bad01"
        bad.mkdir(parents=True)
        (bad / "task.json").write_bytes(os.urandom(512))

        with self.assertRaises(HTTPException) as ctx:
            self._service().status("upgrade-bad01")

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("损坏", str(ctx.exception.detail))

    def test_recovery_fail_corrupt_task_json_still_reports_corruption(self):
        """同上：recovery/fail 对「在但损坏」的 task.json 保持原契约。"""
        bad = self.settings.upgrades_dir / "upgrade-bad02"
        bad.mkdir(parents=True)
        (bad / "task.json").write_bytes(os.urandom(512))

        with self.assertRaises(HTTPException) as ctx:
            self._service().recovery_fail("upgrade-bad02")

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("损坏", str(ctx.exception.detail))


if __name__ == "__main__":
    unittest.main()
