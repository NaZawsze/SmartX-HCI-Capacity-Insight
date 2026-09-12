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


class RobustForecastTest(unittest.TestCase):
    DAY = 86_400

    def _points(self, *, days: int, per_day: float, base: float = 10 * 1024 ** 3, last_day_delta: float | None = None):
        # per_day 为每日净增字节数（不再乘以 DAY）
        points = [(NOW_TS - (days - index) * self.DAY, base + index * per_day) for index in range(days)]
        if last_day_delta is not None:
            last_ts, last_value = points[-1]
            points[-1] = (last_ts, last_value + last_day_delta)
        return points

    def test_stable_series_no_spike(self):
        from app.v2.reports.service import forecast_series

        result = forecast_series(self._points(days=60, per_day=1024 ** 2), capacity=100 * 1024 ** 3)
        self.assertFalse(result.spike_detected)
        self.assertIsNotNone(result.exhaustion_days_30d)
        self.assertIsNotNone(result.exhaustion_days)

    def test_spike_detected_and_30d_slower(self):
        from app.v2.reports.service import forecast_series

        points = self._points(days=90, per_day=1024 ** 2, last_day_delta=200 * 1024 ** 3)
        result = forecast_series(points, capacity=500 * 1024 ** 3)
        self.assertTrue(result.spike_detected)
        self.assertGreater(result.recent_day_delta or 0, 0)
        # 全窗口回归已有 _drop_outliers 保护，两口径都应存在且为正
        self.assertIsNotNone(result.exhaustion_days_30d)
        self.assertIsNotNone(result.exhaustion_days)

    def test_declining_series_no_exhaustion_30d(self):
        from app.v2.reports.service import forecast_series

        # 时间越往后容量越少（每 24 小时减少 1 GiB）
        points = [(NOW_TS - index * self.DAY, 100 * 1024 ** 3 + index * 1024 ** 3) for index in range(30)]
        result = forecast_series(points, capacity=200 * 1024 ** 3)
        self.assertIsNone(result.exhaustion_days_30d)

    def test_insufficient_points_defaults(self):
        from app.v2.reports.service import forecast_series

        result = forecast_series([(NOW_TS, 1024)], capacity=2048)
        self.assertEqual(result.status, "insufficient_data")
        self.assertFalse(result.spike_detected)
        self.assertIsNone(result.exhaustion_days_30d)
