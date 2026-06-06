import tempfile
import unittest
from pathlib import Path


SECONDS_PER_DAY = 86_400


class FakePrometheus:
    def __init__(self, now_ts: int) -> None:
        self.now_ts = now_ts

    def instant(self, query: str):
        if query.startswith("smartx_cluster_storage_total_bytes"):
            return [
                {"metric": {"tower_id": "9", "cluster_id": "orphan-cluster"}, "value": [self.now_ts, "1000"]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a"}, "value": [self.now_ts, "1000"]},
            ]
        if query.startswith("smartx_cluster_storage_used_bytes"):
            return [
                {"metric": {"tower_id": "9", "cluster_id": "orphan-cluster"}, "value": [self.now_ts, "900"]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a"}, "value": [self.now_ts, "190"]},
            ]
        if query.startswith("smartx_vm_storage_used_bytes"):
            return [
                {"metric": {"tower_id": "9", "cluster_id": "orphan-cluster", "vm_id": "vm-orphan", "vm_name": "Orphan Raw"}, "value": [self.now_ts, "900"]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-old", "vm_name": "Old Raw"}, "value": [self.now_ts, "300"]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-new", "vm_name": "New Raw"}, "value": [self.now_ts, "50"]},
            ]
        return []

    def range(self, query: str, *, start: int, end: int, step: str):
        if query.startswith("smartx_cluster_storage_used_bytes"):
            return [
                {
                    "metric": {"tower_id": "9", "cluster_id": "orphan-cluster"},
                    "values": [[self.now_ts - day * SECONDS_PER_DAY, str(900 - day)] for day in reversed(range(14))],
                },
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a"},
                    "values": [[self.now_ts - day * SECONDS_PER_DAY, str(190 - day * 10)] for day in reversed(range(14))],
                }
            ]
        if query.startswith("smartx_vm_storage_used_bytes"):
            return [
                {
                    "metric": {"tower_id": "9", "cluster_id": "orphan-cluster", "vm_id": "vm-orphan", "vm_name": "Orphan Raw"},
                    "values": [[self.now_ts - 31 * SECONDS_PER_DAY, "10"], [self.now_ts, "900"]],
                },
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-old", "vm_name": "Old Raw"},
                    "values": [[self.now_ts - 31 * SECONDS_PER_DAY, "100"], [self.now_ts, "300"]],
                },
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-new", "vm_name": "New Raw"},
                    "values": [[self.now_ts - 3600, "10"], [self.now_ts, "50"]],
                },
            ]
        return []


class RangeOnlyPrometheus(FakePrometheus):
    def instant(self, query: str):
        return []

    def range(self, query: str, *, start: int, end: int, step: str):
        if query.startswith("smartx_cluster_storage_total_bytes"):
            return [
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a"},
                    "values": [[self.now_ts - 31 * SECONDS_PER_DAY, "1000"], [self.now_ts, "1000"]],
                },
            ]
        return super().range(query, start=start, end=end, step=step)


class DuplicateClusterLabelPrometheus(FakePrometheus):
    def range(self, query: str, *, start: int, end: int, step: str):
        if query.startswith("smartx_cluster_storage_used_bytes"):
            return [
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "cluster": "Cluster A", "tower": "Tower A"},
                    "values": [[self.now_ts - 2 * SECONDS_PER_DAY, "100"], [self.now_ts - SECONDS_PER_DAY, "120"]],
                },
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a"},
                    "values": [[self.now_ts, "150"]],
                },
            ]
        return super().range(query, start=start, end=end, step=step)


class V2ReportsTest(unittest.TestCase):
    def _seed_inventory(self, tmpdir: str):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService

        settings = V2Settings(data_root=Path(tmpdir), secret_key="reports-secret")
        db = V2Database(settings)
        db.initialize()
        inventory = InventoryService(db, settings)
        tower = inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com", username="admin"))
        inventory.sync_clusters(tower.id, [ClusterInput(cluster_id="cluster-a", name="Cluster A", enabled=True)])
        with db.connection() as conn:
            conn.execute("INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (1, 'cluster-a', 'vm-old', 'Old Latest', 300)")
            conn.execute("INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (1, 'cluster-a', 'vm-new', 'New Latest', 50)")
        return settings, db

    def test_latest_report_uses_v2_growth_and_forecast_contract(self) -> None:
        from app.v2.reports.service import ReportService

        now_ts = 1_700_000_000
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            report = ReportService(db, settings, prometheus=FakePrometheus(now_ts), now_ts=now_ts).latest_report(period_days=30, chart_days=90)

            self.assertEqual(report["forecast_days"], 90)
            self.assertEqual(report["window_days"], 30)
            self.assertEqual(report["chart_days"], 90)
            self.assertEqual(report["growth_rate_window_days"], 7)
            self.assertEqual(report["period_window"]["days"], 30)
            self.assertEqual(report["clusters"][0]["labels"]["cluster"], "Cluster A")
            self.assertEqual(report["clusters"][0]["forecast"]["forecast_90d"], 1090.0)
            self.assertEqual(report["cluster_growth_rate"]["per_day"], 10.0)
            self.assertEqual(report["month_fastest_growing_vms"][0]["labels"]["vm"], "Old Latest")
            self.assertEqual([item["labels"]["vm_id"] for item in report["month_fastest_growing_vms"]], ["vm-old"])
            self.assertEqual([item["labels"]["vm_id"] for item in report["day_new_vms"]], ["vm-new"])
            self.assertEqual([item["labels"]["cluster_id"] for item in report["clusters"]], ["cluster-a"])

    def test_latest_report_uses_range_tail_when_current_vm_instant_is_empty(self) -> None:
        from app.v2.reports.service import ReportService

        now_ts = 1_700_000_000
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            report = ReportService(db, settings, prometheus=RangeOnlyPrometheus(now_ts), now_ts=now_ts).latest_report(period_days=30, chart_days=90)

            self.assertIn("vm-old", [item["labels"]["vm_id"] for item in report["day_fastest_growing_vms"]])
            self.assertEqual([item["labels"]["vm_id"] for item in report["month_fastest_growing_vms"]], ["vm-old"])
            self.assertEqual(report["month_fastest_growing_vms"][0]["labels"]["vm"], "Old Latest")
            self.assertEqual(report["clusters"][0]["total"], 1000.0)

    def test_latest_report_merges_duplicate_cluster_series_by_identity(self) -> None:
        from app.v2.reports.service import ReportService

        now_ts = 1_700_000_000
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            report = ReportService(db, settings, prometheus=DuplicateClusterLabelPrometheus(now_ts), now_ts=now_ts).latest_report(period_days=30, chart_days=90)

            self.assertEqual(len(report["clusters"]), 1)
            self.assertEqual(report["clusters"][0]["labels"]["cluster"], "Cluster A")
            self.assertEqual(len(report["clusters"][0]["points"]), 3)
            self.assertEqual(report["clusters"][0]["forecast"]["current"], 150.0)


if __name__ == "__main__":
    unittest.main()
