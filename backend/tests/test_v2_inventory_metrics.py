import tempfile
import unittest
from pathlib import Path


class V2InventoryMetricsTest(unittest.TestCase):
    def test_tower_crud_keeps_credentials_private_and_syncs_clusters(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="inventory-secret")
            db = V2Database(settings)
            db.initialize()
            inventory = InventoryService(db, settings)

            tower = inventory.create_tower(
                TowerInput(
                    name="Tower A",
                    base_url="https://tower.example.com",
                    username="admin",
                    password="secret-password",
                    api_token="secret-token",
                    verify_tls=False,
                )
            )
            self.assertEqual(tower.name, "Tower A")
            self.assertEqual(tower.username, "admin")
            self.assertFalse(tower.verify_tls)
            self.assertEqual(tower.clusters, [])
            self.assertNotIn("secret-password", repr(tower))
            self.assertNotIn("secret-token", repr(tower))

            stored = inventory.get_tower_secret_material(tower.id)
            self.assertEqual(stored["password"], "secret-password")
            self.assertEqual(stored["api_token"], "secret-token")

            clusters = inventory.sync_clusters(
                tower.id,
                [
                    ClusterInput(cluster_id="cluster-a", name="Cluster A", enabled=True),
                    ClusterInput(cluster_id="cluster-b", name="Cluster B", enabled=False),
                ],
            )
            self.assertEqual([cluster.cluster_id for cluster in clusters], ["cluster-a", "cluster-b"])

            listed = inventory.list_towers()
            self.assertEqual(len(listed), 1)
            self.assertEqual([cluster.name for cluster in listed[0].clusters], ["Cluster A", "Cluster B"])
            self.assertFalse(listed[0].clusters[1].enabled)

            updated_cluster = inventory.update_cluster(tower.id, "cluster-b", enabled=True, name="Cluster B Renamed")
            self.assertTrue(updated_cluster.enabled)
            self.assertEqual(updated_cluster.name, "Cluster B Renamed")

            renamed_tower = inventory.update_tower(tower.id, TowerInput(name="Tower Renamed", base_url="https://new.example.com"))
            self.assertEqual(renamed_tower.name, "Tower Renamed")
            self.assertEqual(inventory.get_tower_secret_material(tower.id)["password"], "secret-password")

            self.assertTrue(inventory.delete_tower(tower.id))
            self.assertEqual(inventory.list_towers(), [])

    def test_scope_requires_cluster_identity_when_cluster_is_selected(self) -> None:
        from app.v2.inventory.scope import DashboardScope, ScopeType

        self.assertEqual(DashboardScope.from_query(None, None).type, ScopeType.ALL)
        self.assertEqual(DashboardScope.from_query(3, None).type, ScopeType.TOWER)
        cluster_scope = DashboardScope.from_query(3, "cluster-a")
        self.assertEqual(cluster_scope.type, ScopeType.CLUSTER)
        self.assertEqual(cluster_scope.tower_id, 3)
        self.assertEqual(cluster_scope.cluster_id, "cluster-a")

        with self.assertRaises(ValueError):
            DashboardScope.from_query(None, "cluster-a")

    def test_prometheus_metrics_include_stable_identity_labels(self) -> None:
        from app.v2.metrics.formatter import ClusterCapacitySample, VmCapacitySample, render_capacity_metrics

        metrics = render_capacity_metrics(
            clusters=[
                ClusterCapacitySample(tower_id=7, cluster_id="cluster-a", used_bytes=80, total_bytes=100),
            ],
            vms=[
                VmCapacitySample(tower_id=7, cluster_id="cluster-a", vm_id="vm-uuid", vm_name="Renamed VM", used_bytes=42),
            ],
        )

        self.assertIn('smartx_cluster_storage_used_bytes{tower_id="7",cluster_id="cluster-a"} 80', metrics)
        self.assertIn('smartx_cluster_storage_total_bytes{tower_id="7",cluster_id="cluster-a"} 100', metrics)
        self.assertIn('smartx_vm_storage_used_bytes{tower_id="7",cluster_id="cluster-a",vm_id="vm-uuid",vm_name="Renamed VM"} 42', metrics)


if __name__ == "__main__":
    unittest.main()
