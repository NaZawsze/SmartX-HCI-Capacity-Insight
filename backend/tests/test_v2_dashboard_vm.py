import tempfile
import unittest
from pathlib import Path


class FakePrometheus:
    def __init__(self) -> None:
        self.instant_queries: list[str] = []
        self.range_calls: list[dict] = []

    def instant(self, query: str):
        self.instant_queries.append(query)
        if query == "smartx_cluster_storage_used_bytes":
            return [
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a"}, "value": [100, "81"]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-b"}, "value": [100, "10"]},
            ]
        if query == "smartx_cluster_storage_total_bytes":
            return [
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a"}, "value": [100, "100"]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-b"}, "value": [100, "100"]},
            ]
        if query.startswith("smartx_vm_storage_used_bytes"):
            return [
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-1", "vm_name": "VM One Latest"}, "value": [100, "70"]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-2", "vm_name": "VM Two"}, "value": [100, "10"]},
            ]
        return []

    def range(self, query: str, *, start: int, end: int, step: str):
        self.range_calls.append({"query": query, "start": start, "end": end, "step": step})
        if 'vm_id="vm-1"' in query:
            return [{"metric": {"vm_id": "vm-1"}, "values": [[start, "50"], [end, "70"]]}]
        if 'vm_id="vm-2"' in query:
            return [{"metric": {"vm_id": "vm-2"}, "values": [[end, "10"]]}]
        return [
            {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-1", "vm_name": "VM One Old"}, "values": [[start, "50"], [end, "70"]]},
            {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-2", "vm_name": "VM Two"}, "values": [[end, "10"]]},
        ]


class V2DashboardVmTest(unittest.TestCase):
    def _seed_inventory(self, tmpdir: str):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService

        settings = V2Settings(data_root=Path(tmpdir), secret_key="dashboard-secret")
        db = V2Database(settings)
        db.initialize()
        inventory = InventoryService(db, settings)
        tower = inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com", username="admin"))
        inventory.sync_clusters(
            tower.id,
            [
                ClusterInput(cluster_id="cluster-a", name="Cluster A", enabled=True),
                ClusterInput(cluster_id="cluster-b", name="Cluster B", enabled=True),
            ],
        )
        with db.connection() as conn:
            conn.execute(
                "INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (1, 'cluster-a', 'vm-1', 'VM One Latest', 70)"
            )
            conn.execute("INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (1, 'cluster-a', 'vm-2', 'VM Two', 10)")
            conn.execute(
                """
                INSERT INTO vm_volumes (
                    tower_id, cluster_id, vm_id, volume_id, name, path, size_bytes,
                    used_bytes, storage_policy, replica_num, thin_provision
                )
                VALUES (1, 'cluster-a', 'vm-1', 'vol-1', 'Root', '/root', 100, 60, 'Replica-2', 2, 1)
                """
            )
            conn.execute("INSERT INTO collection_runs (status, message, finished_at) VALUES ('success', 'ok', '2026-06-06 02:00:00')")
        return settings, db

    def test_dashboard_summary_uses_single_cluster_risk_and_latest_vm_names(self) -> None:
        from app.v2.dashboard.service import DashboardService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            summary = DashboardService(db, settings, prometheus=FakePrometheus(), now_ts=200).summary()

            self.assertEqual(summary["capacity_risk"]["level"], "high")
            self.assertIn("Cluster A", summary["capacity_risk"]["message"])
            self.assertEqual(summary["totals"], {"towers": 1, "clusters": 2, "vms": 2})
            self.assertEqual(summary["storage"]["used_bytes"], 91)
            self.assertEqual(summary["storage"]["total_bytes"], 200)
            self.assertEqual(summary["day_fastest_growing_vms"][0]["vm_name"], "VM One Latest")
            self.assertEqual(summary["day_fastest_growing_vms"][0]["growth_amount"], 20)
            self.assertEqual(summary["day_new_vms"], [{"tower_id": 1, "cluster_id": "cluster-a", "vm_id": "vm-2", "vm_name": "VM Two", "current_bytes": 10}])

    def test_vm_list_and_trend_use_stable_identity_and_latest_names(self) -> None:
        from app.v2.vms.service import VmService

        prometheus = FakePrometheus()
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            service = VmService(db, settings, prometheus=prometheus, now_ts=200)

            vms = service.list_vms(tower_id=1, cluster_id="cluster-a")
            trend = service.trend(vm_id="vm-1", tower_id=1, cluster_id="cluster-a", days=1)

            self.assertEqual(vms[0]["vm_name"], "VM One Latest")
            self.assertEqual(trend["vm_name"], "VM One Latest")
            self.assertEqual(trend["points"], [{"timestamp": -86200, "used_bytes": 50.0}, {"timestamp": 200, "used_bytes": 70.0}])
            self.assertIn('tower_id="1"', prometheus.range_calls[-1]["query"])
            self.assertIn('cluster_id="cluster-a"', prometheus.range_calls[-1]["query"])
            self.assertIn('vm_id="vm-1"', prometheus.range_calls[-1]["query"])

    def test_vm_detail_and_volumes_return_structured_latest_data(self) -> None:
        from app.v2.vms.service import VmService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            service = VmService(db, settings, prometheus=FakePrometheus(), now_ts=200)

            detail = service.detail(vm_id="vm-1", tower_id=1, cluster_id="cluster-a")
            volumes = service.volumes(vm_id="vm-1", tower_id=1, cluster_id="cluster-a")

            self.assertEqual(detail["vm_name"], "VM One Latest")
            self.assertEqual(detail["used_bytes"], 70)
            self.assertEqual(volumes[0]["volume_id"], "vol-1")
            self.assertEqual(volumes[0]["storage_policy"], "Replica-2")
            self.assertEqual(volumes[0]["replica_num"], 2)
            self.assertTrue(volumes[0]["thin_provision"])


if __name__ == "__main__":
    unittest.main()
