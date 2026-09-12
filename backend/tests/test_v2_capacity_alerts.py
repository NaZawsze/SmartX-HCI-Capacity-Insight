from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


NOW_TS = 1_700_000_000


class CapacityPrometheus:
    def __init__(self, *, used: float, total: float, tower_id: int = 1, cluster_id: str = "cluster-a", fail: bool = False) -> None:
        self.used = used
        self.total = total
        self.tower_id = tower_id
        self.cluster_id = cluster_id
        self.fail = fail

    def instant(self, query: str):
        if self.fail:
            raise RuntimeError("prometheus unavailable")
        metric = {"tower_id": str(self.tower_id), "cluster_id": self.cluster_id}
        if query == "smartx_cluster_storage_used_bytes":
            return [{"metric": metric, "value": [NOW_TS, str(self.used)]}]
        if query == "smartx_cluster_storage_total_bytes":
            return [{"metric": metric, "value": [NOW_TS, str(self.total)]}]
        return []

    def range(self, query: str, *, start: int, end: int, step: str):
        return []


class V2CapacityAlertsTest(unittest.TestCase):
    def _seed(self, tmpdir: str, *, second_cluster_enabled: bool = False, first_cluster_enabled: bool = True):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService
        from app.v2.tasks.service import TaskService

        settings = V2Settings(data_root=Path(tmpdir), secret_key="capacity-secret", prometheus_url="http://prometheus:9090")
        database = V2Database(settings)
        database.initialize()
        inventory = InventoryService(database, settings)
        tower = inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com", username="admin"))
        clusters = [ClusterInput(cluster_id="cluster-a", name="Cluster A", enabled=first_cluster_enabled)]
        if second_cluster_enabled:
            clusters.append(ClusterInput(cluster_id="cluster-b", name="Cluster B", enabled=True))
        inventory.sync_clusters(tower.id, clusters)
        return settings, database, TaskService(database), tower.id

    def _service(self, database, settings, tasks, *, prometheus, **kwargs):
        from app.v2.capacity_alerts.service import CapacityAlertService

        return CapacityAlertService(
            database,
            settings,
            prometheus=prometheus,
            tasks=tasks,
            now_ts=NOW_TS,
            **kwargs,
        )

    def test_threshold_boundaries(self):
        cases = [
            (0.749, None),
            (0.75, "warning"),
            (0.799, "warning"),
            (0.80, "critical"),
        ]
        for ratio, expected in cases:
            with tempfile.TemporaryDirectory() as tmpdir:
                settings, database, tasks, tower_id = self._seed(tmpdir)
                prometheus = CapacityPrometheus(used=1000 * ratio, total=1000)
                result = self._service(database, settings, tasks, prometheus=prometheus).evaluate()
                level = result["alerts"][0]["level"] if result["alerts"] else None
                self.assertEqual(level, expected, f"ratio={ratio}")

    def test_min_free_bytes_promotes_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, tasks, tower_id = self._seed(tmpdir)
            prometheus = CapacityPrometheus(used=500, total=1000)
            result = self._service(database, settings, tasks, prometheus=prometheus, min_free_bytes=600).evaluate()
            self.assertEqual(result["alerts"][0]["level"], "warning")
            self.assertEqual(result["alerts"][0]["free_bytes"], 500)

    def test_missing_total_or_disabled_cluster_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, tasks, tower_id = self._seed(tmpdir, first_cluster_enabled=False)
            prometheus = CapacityPrometheus(used=900, total=1000)
            result = self._service(database, settings, tasks, prometheus=prometheus).evaluate()
            self.assertEqual(result["alerts"], [])
            self.assertEqual(result["clusters_checked"], 0)

    def test_alert_task_created_with_severity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, tasks, tower_id = self._seed(tmpdir)
            prometheus = CapacityPrometheus(used=900, total=1000)
            self._service(database, settings, tasks, prometheus=prometheus).evaluate_and_alert()
            alert = tasks.get_task(f"capacity-alert-critical-{tower_id}-" + self._hash("cluster-a"))
            self.assertIsNotNone(alert)
            self.assertEqual(alert["severity"], "critical")
            self.assertIn("集群容量高风险", alert["title"])
            self.assertIn("90.00%", alert["message"])

    def test_dedup_preserves_acknowledgement(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, tasks, tower_id = self._seed(tmpdir)
            prometheus = CapacityPrometheus(used=850, total=1000)
            service = self._service(database, settings, tasks, prometheus=prometheus)
            service.evaluate_and_alert()
            task_id = f"capacity-alert-critical-{tower_id}-" + self._hash("cluster-a")
            tasks.acknowledge(task_id)
            first = tasks.get_task(task_id)
            self.assertIsNotNone(first["acknowledged_at"])
            service.evaluate_and_alert()
            second = tasks.get_task(task_id)
            self.assertEqual(second["acknowledged_at"], first["acknowledged_at"])
            self.assertIn("评估时间", second["message"])

    def test_escalation_creates_critical_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, tasks, tower_id = self._seed(tmpdir)
            prometheus = CapacityPrometheus(used=780, total=1000)
            service = self._service(database, settings, tasks, prometheus=prometheus)
            service.evaluate_and_alert()
            warning_id = f"capacity-alert-warning-{tower_id}-" + self._hash("cluster-a")
            self.assertIsNotNone(tasks.get_task(warning_id))
            prometheus.used = 850
            service.evaluate_and_alert()
            critical_id = f"capacity-alert-critical-{tower_id}-" + self._hash("cluster-a")
            self.assertIsNotNone(tasks.get_task(critical_id))
            self.assertIsNotNone(tasks.get_task(warning_id))

    def test_prometheus_failure_propagates_to_worker_guard(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, tasks, tower_id = self._seed(tmpdir)
            prometheus = CapacityPrometheus(used=0, total=1000, fail=True)
            service = self._service(database, settings, tasks, prometheus=prometheus)
            with self.assertRaises(RuntimeError):
                service.evaluate()
            # worker 侧由 _run_capacity_alert_check 的 try/except 兜底，保证调度线程存活。

    def test_summary_fail_closed_and_cluster_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, tasks, tower_id = self._seed(tmpdir, first_cluster_enabled=False)
            from app.v2.dashboard.service import DashboardService

            prometheus = CapacityPrometheus(used=900, total=1000)
            dashboard = DashboardService(database, settings, prometheus=prometheus, now_ts=NOW_TS)
            summary = dashboard.summary(tower_id=tower_id, cluster_id="cluster-a")
            self.assertEqual(summary["scope"]["cluster_enabled"], False)
            self.assertEqual(summary["clusters"], [])
            self.assertEqual(summary["capacity_risk"]["level"], "normal")
            self.assertTrue(summary["capacity_risk"]["evaluated_at"])
            all_summary = dashboard.summary()
            self.assertIsNone(all_summary["scope"]["cluster_enabled"])

    def test_shared_scope_helper_fail_closed(self):
        from app.v2.scope import in_enabled_scope

        self.assertFalse(in_enabled_scope((1, "cluster-a"), set()))
        self.assertTrue(in_enabled_scope((1, "cluster-a"), {(1, "cluster-a")}))

    @staticmethod
    def _hash(cluster_id: str) -> str:
        import hashlib

        return hashlib.sha1(cluster_id.encode("utf-8")).hexdigest()[:8]


if __name__ == "__main__":
    unittest.main()
