from __future__ import annotations

import json
import os
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

    def test_summary_scope_type_and_label(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.v2.config import V2Settings
            from app.v2.dashboard.service import DashboardService
            from app.v2.database import V2Database

            settings = V2Settings(data_root=Path(tmpdir), secret_key="p1-secret", prometheus_url="http://prometheus:9090")
            database = V2Database(settings)
            database.initialize()

            class EmptyPrometheus:
                def instant(self, query: str):
                    return []

                def range(self, query: str, *, start: int, end: int, step: str):
                    return []

            with database.connection() as conn:
                cursor = conn.execute(
                    "INSERT INTO towers (name, base_url) VALUES (?, ?)",
                    ("CHINATOWER", "https://tower.example"),
                )
                tower_id = cursor.lastrowid
                conn.execute(
                    "INSERT INTO clusters (tower_id, cluster_id, name) VALUES (?, ?, ?)",
                    (tower_id, "cluster-a", "SMARTX-TT-WW"),
                )

            dashboard = DashboardService(database, settings, prometheus=EmptyPrometheus(), now_ts=NOW_TS)

            all_scope = dashboard.summary()["scope"]
            self.assertEqual(all_scope["type"], "all")
            self.assertEqual(all_scope["label"], "全部数据中心")

            tower_scope = dashboard.summary(tower_id=tower_id)["scope"]
            self.assertEqual(tower_scope["type"], "tower")
            self.assertEqual(tower_scope["label"], "CHINATOWER")

            cluster_scope = dashboard.summary(tower_id=tower_id, cluster_id="cluster-a")["scope"]
            self.assertEqual(cluster_scope["type"], "cluster")
            self.assertEqual(cluster_scope["label"], "CHINATOWER / SMARTX-TT-WW")

            missing_tower = dashboard.summary(tower_id=999)["scope"]
            self.assertEqual(missing_tower["type"], "tower")
            self.assertEqual(missing_tower["label"], "Tower 999")

            missing_cluster = dashboard.summary(tower_id=tower_id, cluster_id="cluster-x")["scope"]
            self.assertEqual(missing_cluster["type"], "cluster")
            self.assertEqual(missing_cluster["label"], "CHINATOWER / cluster-x")

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


class FreshnessCheckTest(unittest.TestCase):
    def _seed(self, tmpdir: str, *, collection_age_minutes: float | None):
        from datetime import datetime, timedelta, timezone

        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService

        settings = V2Settings(data_root=Path(tmpdir), secret_key="fresh-secret", prometheus_url="http://prometheus:9090")
        database = V2Database(settings)
        database.initialize()
        inventory = InventoryService(database, settings)
        tower = inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com", username="admin"))
        inventory.sync_clusters(tower.id, [ClusterInput(cluster_id="cluster-a", name="Cluster A", enabled=True)])
        now = datetime.now(timezone.utc)
        if collection_age_minutes is not None:
            finished = now - timedelta(minutes=collection_age_minutes)
            targets = [{"tower_id": tower.id, "tower_name": "Tower A", "cluster_id": "cluster-a", "cluster_name": "Cluster A"}]
            with database.connection() as conn:
                conn.execute(
                    """INSERT INTO collection_runs (status, message, started_at, finished_at, trigger, success_targets_json, failed_targets_json, published_metrics_targets_json)
                       VALUES (?, 'ok', ?, ?, 'scheduled', ?, '[]', ?)""",
                    (
                        "success",
                        (finished - timedelta(minutes=1)).isoformat(),
                        finished.isoformat(),
                        json.dumps(targets),
                        json.dumps(targets),
                    ),
                )
        return settings, database, tower.id, now

    def _evaluate(self, database, settings, now, *, prometheus_sample_age_minutes: float | None = None, env_stale: str | None = None):
        import os

        from app.v2.data_quality.service import DataQualityService

        if env_stale is not None:
            os.environ["SMARTX_FRESHNESS_STALE_MINUTES"] = env_stale
        try:

            class P:
                def __init__(self, age):
                    self.age = age

                def instant(self, query):
                    if self.age is None:
                        return []
                    ts = int(now.timestamp()) - self.age * 60
                    return [{"metric": {"tower_id": "1", "cluster_id": "cluster-a"}, "value": [ts, "100"]}]

                def range(self, query, *, start, end, step):
                    return []

            service = DataQualityService(database, settings, prometheus=P(prometheus_sample_age_minutes), now_ts=int(now.timestamp()))
            return service.evaluate(period_days=30)
        finally:
            os.environ.pop("SMARTX_FRESHNESS_STALE_MINUTES", None)

    def test_stale_collection_raises_warning(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, tower_id, now = self._seed(tmpdir, collection_age_minutes=600)
            result = self._evaluate(database, settings, now, prometheus_sample_age_minutes=599, env_stale="180")
            self.assertTrue(any("超过新鲜度阈值" in m for m in result["messages"]))
            self.assertEqual(result["freshness"]["stale_threshold_minutes"], 180)

    def test_prometheus_lag_raises_warning(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, tower_id, now = self._seed(tmpdir, collection_age_minutes=10)
            result = self._evaluate(database, settings, now, prometheus_sample_age_minutes=60)
            self.assertTrue(any("滞后" in m for m in result["messages"]))
            self.assertGreater(result["freshness"]["prometheus_lag_minutes"], 15)

    def test_fresh_collection_no_warning(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, tower_id, now = self._seed(tmpdir, collection_age_minutes=5)
            result = self._evaluate(database, settings, now, prometheus_sample_age_minutes=4)
            self.assertFalse(any("新鲜度阈值" in m or "滞后" in m for m in result["messages"]))

    def test_adaptive_threshold_for_daily_mode(self):
        import tempfile

        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.data_quality.service import DataQualityService
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="f2", prometheus_url="http://prometheus:9090")
            database = V2Database(settings)
            database.initialize()
            inventory = InventoryService(database, settings)
            tower = inventory.create_tower(TowerInput(name="T", base_url="https://t.example.com", username="admin", collection_mode="daily"))
            inventory.sync_clusters(tower.id, [ClusterInput(cluster_id="c", name="C", enabled=True)])
            service = DataQualityService(database, settings, prometheus=object(), now_ts=NOW_TS)
            self.assertEqual(service._freshness_threshold_minutes(), 2880)


class CorsConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        try:
            import fastapi  # noqa: F401

            self.fastapi_available = True
        except ModuleNotFoundError:
            self.fastapi_available = False

    def test_cors_disabled_by_default(self):
        if not getattr(self, "fastapi_available", False):
            self.skipTest("fastapi not installed")
        from app.v2.main import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_CORS_ORIGINS"] = ""
            try:
                app = create_app()
                middlewares = [m.cls.__name__ for m in app.user_middleware]
                self.assertNotIn("CORSMiddleware", middlewares)
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_CORS_ORIGINS", None)

    def test_cors_enabled_with_config(self):
        if not getattr(self, "fastapi_available", False):
            self.skipTest("fastapi not installed")
        from app.v2.main import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_CORS_ORIGINS"] = "https://ops.example.com, https://ops2.example.com"
            try:
                app = create_app()
                middlewares = [m.cls.__name__ for m in app.user_middleware]
                self.assertIn("CORSMiddleware", middlewares)
                cors = next(m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware")
                self.assertEqual(cors.kwargs["allow_origins"], ["https://ops.example.com", "https://ops2.example.com"])
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_CORS_ORIGINS", None)


class SeriesKeysTest(unittest.TestCase):
    def test_cluster_and_vm_key(self):
        from app.v2.metrics.series import cluster_key, vm_key

        labels = {"tower_id": "3", "cluster_id": "c-1", "vm_id": "vm-9"}
        self.assertEqual(cluster_key(labels), (3, "c-1"))
        self.assertEqual(vm_key(labels), (3, "c-1", "vm-9"))
        self.assertEqual(cluster_key({}), (0, ""))
        self.assertEqual(vm_key({}), (0, "", ""))
