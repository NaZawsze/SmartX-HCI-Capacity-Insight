from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

NOW_TS = 1_700_000_000


class V2P1InfraTest(unittest.TestCase):
    def _database(self, tmpdir: str):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database

        settings = V2Settings(data_root=Path(tmpdir), secret_key="p1-secret", prometheus_url="http://prometheus:9090")
        database = V2Database(settings)
        database.initialize()
        return settings, database

    def test_wal_and_indexes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database = self._database(tmpdir)
            with database.connection() as conn:
                mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                self.assertEqual(str(mode).lower(), "wal")
                indexes = {
                    row["name"]
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
                }
                self.assertIn("idx_tasks_updated_at", indexes)
                self.assertIn("idx_collection_runs_started_at", indexes)
                self.assertIn("idx_collection_runs_finished_at", indexes)

    def test_busy_timeout_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database = self._database(tmpdir)
            conn = database.connect()
            try:
                self.assertEqual(conn.execute("PRAGMA busy_timeout").fetchone()[0], 5000)
            finally:
                conn.close()

    def test_day_bounds_timezone(self):
        from app.v2.dashboard.service import _day_bounds

        # 2023-11-14 20:00 UTC = 2023-11-15 04:00 北京；当日零点应落在不同日期
        start_sh, _ = _day_bounds(NOW_TS, "Asia/Shanghai")
        start_utc, _ = _day_bounds(NOW_TS, "UTC")
        self.assertEqual(start_sh, 1_699_977_600)  # 北京 2023-11-15 00:00（UTC+8）
        self.assertEqual(start_utc, 1_699_920_000)  # UTC 2023-11-14 00:00
        # 非法时区回退 UTC
        start_fallback, _ = _day_bounds(NOW_TS, "Not/AZone")
        self.assertEqual(start_fallback, start_utc)

    def test_capacity_risk_thresholds_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.v2.config import V2Settings
            from app.v2.dashboard.service import DashboardService

            settings = V2Settings(data_root=Path(tmpdir), secret_key="p1-secret", prometheus_url="http://prometheus:9090")
            from app.v2.database import V2Database

            database = V2Database(settings)
            database.initialize()

            class EmptyPrometheus:
                def instant(self, query: str):
                    return []

                def range(self, query: str, *, start: int, end: int, step: str):
                    return []

            dashboard = DashboardService(database, settings, prometheus=EmptyPrometheus(), now_ts=NOW_TS)
            summary = dashboard.summary()
            thresholds = summary["capacity_risk"]["thresholds"]
            self.assertEqual(thresholds["warning_ratio"], 0.75)
            self.assertEqual(thresholds["danger_ratio"], 0.80)


if __name__ == "__main__":
    unittest.main()
