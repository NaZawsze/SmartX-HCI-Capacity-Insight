from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOW = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)


class CollectionFreshnessTest(unittest.TestCase):
    def _database(self, tmpdir: str):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database

        settings = V2Settings(data_root=Path(tmpdir), secret_key="fresh-secret", prometheus_url="http://prometheus:9090")
        database = V2Database(settings)
        database.initialize()
        return database

    def _add_enabled_tower(self, database, interval_minutes: int = 60) -> None:
        with database.connection() as conn:
            conn.execute(
                "INSERT INTO towers (name, base_url, username, enabled, collection_interval_minutes, collection_mode) "
                "VALUES ('T1', 'https://t.example.com', 'admin', 1, ?, 'interval')",
                (interval_minutes,),
            )

    def _add_success_run(self, database, finished_at: str) -> None:
        with database.connection() as conn:
            conn.execute(
                "INSERT INTO collection_runs (status, message, started_at, finished_at) VALUES ('success', 'ok', ?, ?)",
                (finished_at, finished_at),
            )

    def _service(self, database, **kwargs):
        from app.v2.freshness import CollectionFreshnessService

        return CollectionFreshnessService(database, **kwargs)

    def test_ok_when_recent_success_within_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = self._database(tmpdir)
            self._add_enabled_tower(database, interval_minutes=60)
            # 阈值 = max(2*60, 60) = 120 分钟；70 分钟前成功 → ok
            self._add_success_run(database, "2026-09-19 10:50:00")
            result = self._service(database).evaluate(now=NOW)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["threshold_minutes"], 120)
            self.assertAlmostEqual(result["minutes_since_success"], 70, delta=0.1)

    def test_stale_when_success_older_than_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = self._database(tmpdir)
            self._add_enabled_tower(database, interval_minutes=60)
            # 200 分钟前成功 > 120 分钟阈值 → stale
            self._add_success_run(database, "2026-09-19 08:40:00")
            service = self._service(database)
            result = service.evaluate(now=NOW)
            self.assertEqual(result["status"], "stale")

    def test_stale_alert_uses_fixed_task_id_and_replaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = self._database(tmpdir)
            self._add_enabled_tower(database, interval_minutes=60)
            self._add_success_run(database, "2026-09-19 08:40:00")
            from app.v2.freshness import FRESHNESS_TASK_ID
            from app.v2.tasks.service import TaskService

            tasks = TaskService(database)
            service = self._service(database, tasks=tasks)
            first = service.evaluate_and_alert(now=NOW)
            self.assertEqual(first["status"], "stale")
            second = service.evaluate_and_alert(now=NOW)
            self.assertEqual(second["status"], "stale")
            with database.connection() as conn:
                rows = conn.execute("SELECT id, status, title FROM tasks WHERE id = ?", (FRESHNESS_TASK_ID,)).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "failed")
            self.assertEqual(rows[0]["title"], "采集停摆告警")

    def test_ok_alert_not_created_when_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = self._database(tmpdir)
            self._add_enabled_tower(database, interval_minutes=60)
            self._add_success_run(database, "2026-09-19 11:30:00")
            from app.v2.freshness import FRESHNESS_TASK_ID
            from app.v2.tasks.service import TaskService

            tasks = TaskService(database)
            self._service(database, tasks=tasks).evaluate_and_alert(now=NOW)
            with database.connection() as conn:
                rows = conn.execute("SELECT id FROM tasks WHERE id = ?", (FRESHNESS_TASK_ID,)).fetchall()
            self.assertEqual(rows, [])

    def test_skipped_when_no_enabled_towers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = self._database(tmpdir)
            result = self._service(database).evaluate(now=NOW)
            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["reason"], "no_enabled_towers")

    def test_no_success_ever_alerts_after_probe_age_exceeds_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = self._database(tmpdir)
            self._add_enabled_tower(database, interval_minutes=60)
            started_at = NOW - timedelta(minutes=200)
            service = self._service(database, probe_started_at=started_at)
            result = service.evaluate(now=NOW)
            self.assertEqual(result["status"], "stale")
            self.assertEqual(result["reason"], "no_success_ever")
            # 探针刚启动时不告警（新部署留出首个采集周期）
            young = self._service(database, probe_started_at=NOW - timedelta(minutes=5))
            self.assertEqual(young.evaluate(now=NOW)["status"], "ok")

    def test_unparseable_timestamp_is_unknown_without_alert(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = self._database(tmpdir)
            self._add_enabled_tower(database, interval_minutes=60)
            self._add_success_run(database, "not-a-timestamp")
            from app.v2.tasks.service import TaskService

            tasks = TaskService(database)
            result = self._service(database, tasks=tasks).evaluate_and_alert(now=NOW)
            self.assertEqual(result["status"], "unknown")
            with database.connection() as conn:
                rows = conn.execute("SELECT id FROM tasks").fetchall()
            self.assertEqual(rows, [])

    def test_daily_mode_threshold_uses_2880(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = self._database(tmpdir)
            with database.connection() as conn:
                conn.execute(
                    "INSERT INTO towers (name, base_url, username, enabled, collection_interval_minutes, collection_mode) "
                    "VALUES ('T1', 'https://t.example.com', 'admin', 1, 60, 'daily')"
                )
            # 1300 分钟前成功，daily 模式阈值 2880 → ok
            self._add_success_run(database, "2026-09-18 14:20:00")
            result = self._service(database).evaluate(now=NOW)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["threshold_minutes"], 2880)

    def test_iso_z_timestamp_from_tests_format_parses(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = self._database(tmpdir)
            self._add_enabled_tower(database, interval_minutes=60)
            self._add_success_run(database, "2026-09-19T10:50:00Z")
            result = self._service(database).evaluate(now=NOW)
            self.assertEqual(result["status"], "ok")

    def test_threshold_shared_with_data_quality(self) -> None:
        from app.v2.data_quality.service import freshness_threshold_minutes

        with tempfile.TemporaryDirectory() as tmpdir:
            database = self._database(tmpdir)
            self._add_enabled_tower(database, interval_minutes=90)
            self.assertEqual(freshness_threshold_minutes(database), 180)

    def test_daemon_disabled_on_non_positive_interval(self) -> None:
        from app.v2.freshness import start_freshness_probe_daemon

        with tempfile.TemporaryDirectory() as tmpdir:
            database = self._database(tmpdir)
            self.assertIsNone(start_freshness_probe_daemon(database, interval_seconds=0))


if __name__ == "__main__":
    unittest.main()
