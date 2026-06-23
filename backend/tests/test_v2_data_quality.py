from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


SECONDS_PER_DAY = 86_400


class QualityPrometheus:
    def __init__(
        self,
        now_ts: int,
        *,
        vm_series: list[dict] | None = None,
        cluster_series: list[dict] | None = None,
        fail: bool = False,
    ) -> None:
        self.now_ts = now_ts
        self.vm_series = vm_series if vm_series is not None else [
            {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-1"}, "value": [now_ts, "100"]},
            {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-2"}, "value": [now_ts, "200"]},
        ]
        self.cluster_series = cluster_series if cluster_series is not None else [
            {"metric": {"tower_id": "1", "cluster_id": "cluster-a"}, "value": [now_ts, "300"]},
        ]
        self.fail = fail

    def instant(self, query: str):
        if self.fail:
            raise RuntimeError("prometheus unavailable")
        if query.startswith("smartx_vm_storage_used_bytes"):
            return self.vm_series
        if query.startswith("smartx_cluster_storage_used_bytes"):
            return self.cluster_series
        return []

    def range(self, query: str, *, start: int, end: int, step: str):
        if self.fail:
            raise RuntimeError("prometheus unavailable")
        if query.startswith("smartx_vm_storage_used_bytes"):
            return [
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-1"},
                    "values": [[self.now_ts - 13 * SECONDS_PER_DAY, "10"], [self.now_ts, "100"]],
                },
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-2"},
                    "values": [[self.now_ts - 13 * SECONDS_PER_DAY, "20"], [self.now_ts, "200"]],
                },
            ]
        if query.startswith("smartx_cluster_storage_used_bytes"):
            return [
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a"},
                    "values": [[self.now_ts - 13 * SECONDS_PER_DAY, "30"], [self.now_ts, "300"]],
                }
            ]
        return []


class V2DataQualityTest(unittest.TestCase):
    def _seed(
        self,
        tmpdir: str,
        *,
        vm_count: int = 2,
        collection_status: str = "success",
        period_days: int = 30,
        include_second_cluster: bool = False,
    ):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService
        from app.v2.tasks.service import TaskService

        now_ts = 1_700_000_000
        settings = V2Settings(data_root=Path(tmpdir), secret_key="quality-secret", prometheus_url="http://prometheus:9090")
        database = V2Database(settings)
        database.initialize()
        inventory = InventoryService(database, settings)
        tower = inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com", username="admin"))
        clusters = [ClusterInput(cluster_id="cluster-a", name="Cluster A", enabled=True)]
        if include_second_cluster:
            clusters.append(ClusterInput(cluster_id="cluster-b", name="Cluster B", enabled=True))
        inventory.sync_clusters(tower.id, clusters)
        with database.connection() as conn:
            for index in range(vm_count):
                conn.execute(
                    "INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (?, ?, ?, ?, ?)",
                    (tower.id, "cluster-a", f"vm-{index + 1}", f"VM {index + 1}", (index + 1) * 100),
                )
            success_targets = [{"tower_id": tower.id, "tower_name": "Tower A", "cluster_id": "cluster-a", "cluster_name": "Cluster A"}]
            failed_targets = []
            message = "采集完成"
            if collection_status == "partial_failed":
                failed_targets = [{"tower_id": tower.id, "tower_name": "Tower A", "cluster_id": "cluster-a", "cluster_name": "Cluster A", "message": "timeout"}]
                message = "部分集群采集异常"
            if collection_status == "failed":
                success_targets = []
                failed_targets = [{"tower_id": tower.id, "tower_name": "Tower A", "cluster_id": "cluster-a", "cluster_name": "Cluster A", "message": "timeout"}]
                message = "采集失败"
            if include_second_cluster:
                success_targets = [{"tower_id": tower.id, "tower_name": "Tower A", "cluster_id": "cluster-a", "cluster_name": "Cluster A"}]
                failed_targets = [{"tower_id": tower.id, "tower_name": "Tower A", "cluster_id": "cluster-b", "cluster_name": "Cluster B", "message": "timeout"}]
                collection_status = "partial_failed"
                message = "部分集群采集异常"
            conn.execute(
                """
                INSERT INTO collection_runs (
                    status, message, started_at, finished_at, trigger,
                    success_targets_json, failed_targets_json, published_metrics_targets_json
                )
                VALUES (?, ?, '2023-11-14T21:13:20+00:00', '2023-11-14T21:14:20+00:00', 'scheduled', ?, ?, ?)
                """,
                (
                    collection_status,
                    message,
                    json.dumps(success_targets, ensure_ascii=False),
                    json.dumps(failed_targets, ensure_ascii=False),
                    json.dumps(success_targets, ensure_ascii=False),
                ),
            )
        return settings, database, TaskService(database), now_ts, period_days

    def _evaluate(self, database, settings, now_ts: int, prometheus, *, period_days: int = 30, tasks=None, cluster_id=None):
        from app.v2.data_quality.service import DataQualityService

        return DataQualityService(database, settings, prometheus=prometheus, tasks=tasks, now_ts=now_ts).evaluate(period_days=period_days, cluster_id=cluster_id)

    def test_returns_ok_when_sqlite_and_prometheus_current_samples_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, _tasks, now_ts, _ = self._seed(tmpdir, vm_count=2)

            result = self._evaluate(database, settings, now_ts, QualityPrometheus(now_ts), period_days=14)

            self.assertEqual(result["status"], "ok")
            self.assertTrue(result["sample_sufficient"])
            self.assertEqual(result["sqlite_vm_count"], 2)
            self.assertEqual(result["prometheus_vm_series_count"], 2)
            self.assertEqual(result["incomplete_clusters"], [])

    def test_successful_collection_without_prometheus_samples_is_critical(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, _tasks, now_ts, _ = self._seed(tmpdir, vm_count=2)

            result = self._evaluate(database, settings, now_ts, QualityPrometheus(now_ts, vm_series=[], cluster_series=[]))

            self.assertEqual(result["status"], "critical")
            self.assertIn("最近一次采集成功但 Prometheus 当前样本为空", " ".join(result["messages"]))

    def test_large_vm_series_difference_is_warning_or_critical(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, _tasks, now_ts, _ = self._seed(tmpdir, vm_count=100)
            warning_rows = [
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": f"vm-{index}"}, "value": [now_ts, "1"]}
                for index in range(85)
            ]
            critical_rows = [
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": f"vm-{index}"}, "value": [now_ts, "1"]}
                for index in range(40)
            ]

            warning = self._evaluate(database, settings, now_ts, QualityPrometheus(now_ts, vm_series=warning_rows), period_days=14)
            critical = self._evaluate(database, settings, now_ts, QualityPrometheus(now_ts, vm_series=critical_rows), period_days=14)

            self.assertEqual(warning["status"], "warning")
            self.assertEqual(critical["status"], "critical")
            self.assertEqual(warning["vm_count_difference"], 15)
            self.assertGreater(warning["vm_count_difference_ratio"], 0.1)

    def test_partial_failed_collection_returns_missing_dates_and_incomplete_cluster(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, _tasks, now_ts, _ = self._seed(tmpdir, vm_count=2, collection_status="partial_failed")

            result = self._evaluate(database, settings, now_ts, QualityPrometheus(now_ts, cluster_series=[]), period_days=14)

            self.assertEqual(result["status"], "warning")
            self.assertEqual(result["missing_collection_dates"], ["2023-11-15"])
            self.assertEqual(result["incomplete_clusters"][0]["cluster"], "Cluster A")

    def test_cluster_scoped_quality_ignores_other_cluster_collection_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, _tasks, now_ts, _ = self._seed(tmpdir, vm_count=2, include_second_cluster=True)

            result = self._evaluate(database, settings, now_ts, QualityPrometheus(now_ts), period_days=14, cluster_id="cluster-a")

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["missing_collection_dates"], [])
            self.assertEqual(result["incomplete_clusters"], [])

    def test_sample_window_shorter_than_requested_period_is_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, _tasks, now_ts, _ = self._seed(tmpdir, vm_count=2)

            result = self._evaluate(database, settings, now_ts, QualityPrometheus(now_ts), period_days=30)

            self.assertEqual(result["status"], "warning")
            self.assertFalse(result["sample_sufficient"])
            self.assertLess(result["actual_data_window"]["days"], 30)

    def test_prometheus_query_failure_is_critical_without_hiding_sqlite_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, _tasks, now_ts, _ = self._seed(tmpdir, vm_count=2)

            result = self._evaluate(database, settings, now_ts, QualityPrometheus(now_ts, fail=True))

            self.assertEqual(result["status"], "critical")
            self.assertEqual(result["sqlite_vm_count"], 2)
            self.assertIn("Prometheus 查询失败", " ".join(result["messages"]))

    def test_records_or_updates_single_data_quality_alert(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, tasks, now_ts, _ = self._seed(tmpdir, vm_count=2)
            from app.v2.data_quality.service import DataQualityService

            service = DataQualityService(database, settings, prometheus=QualityPrometheus(now_ts, vm_series=[], cluster_series=[]), tasks=tasks, now_ts=now_ts)
            first = service.evaluate_and_alert(period_days=30)
            second = service.evaluate_and_alert(period_days=30)

            all_tasks = tasks.list_tasks(limit=20)
            alerts = [task for task in all_tasks if task["title"] == "数据一致性异常"]
            self.assertEqual(first["status"], "critical")
            self.assertEqual(second["status"], "critical")
            self.assertEqual(len(alerts), 1)
            self.assertIn("SQLite VM 数", alerts[0]["message"])


if __name__ == "__main__":
    unittest.main()
