"""49-52：升级单飞守卫——已有升级在执行/待恢复时，禁止开始新的升级动作。

设计：docs/superpowers/specs/2026-09-27-us05-us23-release-blocking-fix-design.md
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app.v2.upgrade.service._compat import HTTPException


class _DummyPlan:
    def to_dict(self) -> dict:
        return {"steps": []}


def _service(tmpdir: str):
    from app.v2.config import V2Settings
    from app.v2.database import V2Database
    from app.v2.tasks.service import TaskService
    from app.v2.upgrade.service import UpgradeService

    settings = V2Settings(data_root=Path(tmpdir), secret_key="single-flight-secret", app_version="v0.5.3")
    database = V2Database(settings)
    database.initialize()
    return UpgradeService(settings, TaskService(database), project_path=Path(tmpdir) / "project")


def _write_task(service, task_id: str, status: str, **extra) -> None:
    task_dir = service.settings.upgrades_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    payload = {"task_id": task_id, "status": status, "manifest": {}, **extra}
    (task_dir / "task.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _register_task(service, task_id: str, status) -> None:
    from app.v2.tasks.models import TaskType

    service.tasks.create_task(task_id, TaskType.UPGRADE, "执行系统升级", status=status, progress=1, message="test")


class SingleFlightGuardTest(unittest.TestCase):
    def test_start_rejected_when_other_task_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = _service(tmpdir)
            _write_task(service, "other-1", "running")
            _write_task(service, "t1", "precheck_passed")

            with self.assertRaises(HTTPException) as ctx:
                service.start("t1", submit_to_runner=True)

            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("正在执行或需要恢复", str(ctx.exception.detail))
            self.assertIn("other-1", str(ctx.exception.detail))

    def test_start_rejected_for_each_active_status(self) -> None:
        active_statuses = ["pending", "running", "runner_restarting", "recovery_required", "rollback_pending", "rollback_running"]
        for status in active_statuses:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmpdir:
                service = _service(tmpdir)
                _write_task(service, "other-1", status)
                _write_task(service, "t1", "precheck_passed")

                with self.assertRaises(HTTPException) as ctx:
                    service.start("t1", submit_to_runner=True)

                self.assertEqual(ctx.exception.status_code, 400)
                self.assertIn("正在执行或需要恢复", str(ctx.exception.detail))

    def test_guard_allows_idle_and_terminal_statuses(self) -> None:
        idle_statuses = ["uploaded", "precheck_failed", "precheck_passed", "prechecked", "succeeded", "success", "failed", "cancelled"]
        for status in idle_statuses:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmpdir:
                service = _service(tmpdir)
                _write_task(service, "other-1", status)
                _write_task(service, "t1", "precheck_passed")

                service._ensure_no_active_upgrade("t1")

    def test_guard_excludes_self(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = _service(tmpdir)
            _write_task(service, "self-1", "running")

            service._ensure_no_active_upgrade("self-1")

    def test_component_upgrade_entry_uses_same_guard(self) -> None:
        """组件升级走 start(submit_to_runner=False)，必须同样被拦（同一守卫）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = _service(tmpdir)
            _write_task(service, "other-1", "pending")
            _write_task(service, "runner-comp", "precheck_passed")

            with self.assertRaises(HTTPException) as ctx:
                service.start("runner-comp", submit_to_runner=False)

            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("正在执行或需要恢复", str(ctx.exception.detail))

    def test_post_cleanup_running_blocks_new_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = _service(tmpdir)
            _write_task(service, "post-cleanup-abc", "running")
            _write_task(service, "t1", "precheck_passed")

            with self.assertRaises(HTTPException) as ctx:
                service.start("t1", submit_to_runner=True)

            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("post-cleanup-abc", str(ctx.exception.detail))

    def test_concurrent_starts_yield_exactly_one_winner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = _service(tmpdir)
            _write_task(service, "t1", "precheck_passed")
            _write_task(service, "t2", "precheck_passed")
            barrier = threading.Barrier(2)
            results: list[dict] = []
            lock = threading.Lock()

            def attempt(task_id: str) -> None:
                barrier.wait()
                try:
                    service.start(task_id, submit_to_runner=True)
                except HTTPException as exc:
                    outcome = {"task_id": task_id, "ok": False, "status_code": exc.status_code, "detail": str(exc.detail)}
                else:
                    outcome = {"task_id": task_id, "ok": True}
                with lock:
                    results.append(outcome)

            with patch(
                "app.v2.upgrade.service.execution.compile_execution_plan",
                side_effect=lambda manifest: _DummyPlan(),
            ):
                threads = [threading.Thread(target=attempt, args=(task_id,)) for task_id in ("t1", "t2")]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

            self.assertEqual(len(results), 2)
            winners = [item for item in results if item["ok"]]
            losers = [item for item in results if not item["ok"]]
            self.assertEqual(len(winners), 1, f"必须恰好一个成功：{results}")
            self.assertEqual(len(losers), 1, f"必须恰好一个被拒：{results}")
            self.assertEqual(losers[0]["status_code"], 400)

    def test_retry_recovery_rollback_entries_guarded_but_cancel_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = _service(tmpdir)
            _write_task(service, "other-1", "running")

            with self.assertRaises(HTTPException) as ctx:
                service.retry_post_upgrade_cleanup("parent-x")
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("正在执行或需要恢复", str(ctx.exception.detail))

        with tempfile.TemporaryDirectory() as tmpdir:
            service = _service(tmpdir)
            _write_task(service, "other-1", "running")
            _write_task(service, "r1", "recovery_required", available_recovery_actions=["continue"])

            with self.assertRaises(HTTPException) as ctx:
                service.recovery_continue("r1")
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("正在执行或需要恢复", str(ctx.exception.detail))

        with tempfile.TemporaryDirectory() as tmpdir:
            service = _service(tmpdir)
            _write_task(service, "other-1", "running")
            _write_task(service, "rb1", "failed", started_at="2026-09-27T00:00:00")

            with self.assertRaises(HTTPException) as ctx:
                service.rollback("rb1")
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("正在执行或需要恢复", str(ctx.exception.detail))

        with tempfile.TemporaryDirectory() as tmpdir:
            service = _service(tmpdir)
            _write_task(service, "other-1", "running")
            _write_task(service, "c1", "pending")
            from app.v2.tasks.models import TaskStatus

            _register_task(service, "c1", TaskStatus.PENDING)

            cancelled = service.cancel("c1")
            self.assertEqual(cancelled["status"], "cancelled")

    def test_corrupt_task_json_does_not_block_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = _service(tmpdir)
            broken_dir = service.settings.upgrades_dir / "broken-1"
            broken_dir.mkdir(parents=True, exist_ok=True)
            (broken_dir / "task.json").write_text("{not json", encoding="utf-8")
            _write_task(service, "t1", "precheck_passed")

            service._ensure_no_active_upgrade("t1")


if __name__ == "__main__":
    unittest.main()
