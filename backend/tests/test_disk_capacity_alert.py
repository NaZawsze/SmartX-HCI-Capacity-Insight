"""磁盘占用告警（2026-10-04）。

事故链（`.12` 实测）：2026-07 起两个 running 僵尸任务永久锁死空间清理 →
磁盘堆到 94%（`upgrades/` 14G）→ `/tmp` tmpfs 也 100% 满 → 客户全程无通知。
`capacity_alerts` 原先只管集群容量，磁盘无人看管，故补本模块。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class _FakeUsage:
    def __init__(self, total: int, free: int) -> None:
        self.total = total
        self.free = free
        self.used = total - free


class DiskAlertServiceTest(unittest.TestCase):
    def _settings(self, tmpdir: str):
        from app.v2.config import V2Settings

        return V2Settings(data_root=Path(tmpdir), secret_key="s")

    def _service(self, tmpdir: str, total_gb: float, free_gb: float, **kwargs):
        from app.v2.capacity_alerts.disk import DiskAlertService

        settings = self._settings(tmpdir)
        total = int(total_gb * 1024**3)
        free = int(free_gb * 1024**3)
        return DiskAlertService(
            settings,
            None,
            usage=lambda path: _FakeUsage(total, free),
            **kwargs,
        )

    def test_no_alert_when_disk_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir, total_gb=60, free_gb=30)
            result = service.evaluate()
            self.assertEqual(result["alerts"], [])

    def test_warning_at_80_percent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir, total_gb=100, free_gb=20)  # 80%
            result = service.evaluate()
            self.assertEqual(len(result["alerts"]), 1)
            self.assertEqual(result["alerts"][0]["level"], "warning")

    def test_critical_at_90_percent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir, total_gb=100, free_gb=10)  # 90%
            result = service.evaluate()
            self.assertEqual(result["alerts"][0]["level"], "critical")

    def test_absolute_floor_triggers_below_ratio(self) -> None:
        """**小盘**客户：占用率才 62.5%，但剩余已不足 2 GiB → 仍要预警。

        百分比阈值对大盘够用，但对小盘会漏：4 GiB 盘写了 2.5 GiB（占用率 62.5%，
        远低于 80% 阈值），可剩余 1.5 GiB 已写不下一个升级包
        （实测 242M 包 + 611M 解包 = 853M，再加 2 GiB 余量）。

        注意别用「大盘剩 1.5G」举例——那必然是 99%+ 占用，百分比阈值早命中了，
        证明不了是绝对下限在起作用（本轮就踩过这个算术错误）。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir, total_gb=4, free_gb=1.5)
            result = service.evaluate()
            self.assertEqual(len(result["alerts"]), 1, "绝对下限应独立触发")
            self.assertEqual(result["alerts"][0]["level"], "warning")
            self.assertLess(
                result["alerts"][0]["used_ratio"], 0.8,
                "占用率必须低于百分比阈值，才能证明是绝对下限在起作用",
            )

    def test_thresholds_overridable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(
                tmpdir, total_gb=100, free_gb=40,  # 60% 占用
                warning_ratio=0.5, critical_ratio=0.6, min_free_bytes=0,
            )
            result = service.evaluate()
            self.assertEqual(result["alerts"][0]["level"], "critical")

    def test_message_points_to_cleanup_page(self) -> None:
        """告警必须告诉客户去哪处置，否则等于没告警。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir, total_gb=100, free_gb=5)
            lines = service._message_lines(service.evaluate()["alerts"][0])
            text = "\n".join(lines)
            self.assertIn("空间清理", text)
            self.assertIn("占用率", text)
            self.assertIn("剩余空间", text)

    def test_upsert_creates_alert_task(self) -> None:
        """接到任务中心：走同一套 upsert_alert 去重机制。"""
        from app.v2.capacity_alerts.disk import DiskAlertService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="s")
            database = V2Database(settings)
            database.initialize()
            tasks = TaskService(database)
            service = DiskAlertService(
                settings, tasks,
                usage=lambda path: _FakeUsage(int(100 * 1024**3), int(5 * 1024**3)),
            )

            result = service.evaluate_and_alert()

            self.assertEqual(len(result["alerts"]), 1)
            with database.connection() as conn:
                rows = conn.execute(
                    "SELECT id, severity FROM tasks WHERE id LIKE 'disk-alert-%'"
                ).fetchall()
            self.assertEqual(len(rows), 1, f"应产生 1 条磁盘告警，实际 {rows}")
            self.assertEqual(rows[0]["severity"], "critical")

    def test_worker_wires_disk_alert(self) -> None:
        """守护线程必须真的调用它，否则是死代码。"""
        from pathlib import Path as P

        # tests/ -> backend/ -> app/v2/worker.py
        worker = (P(__file__).resolve().parents[1] / "app" / "v2" / "worker.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("DiskAlertService", worker, "worker 未接入磁盘告警")


if __name__ == "__main__":
    unittest.main()
