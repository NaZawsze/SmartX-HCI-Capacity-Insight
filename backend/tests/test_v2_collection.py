import tempfile
import unittest
from pathlib import Path


class FakeCloudTowerClient:
    def __init__(self) -> None:
        self.collected_cluster_ids: list[str] = []

    def collect_cluster(self, tower, cluster):
        self.collected_cluster_ids.append(cluster.cluster_id)
        return {
            "cluster": {"used_bytes": 80, "total_bytes": 100},
            "vms": [
                {"vm_id": "vm-1", "name": "VM One Renamed", "used_bytes": 42},
            ],
        }


class FailingCloudTowerClient:
    def collect_cluster(self, tower, cluster):
        raise RuntimeError("login failed for password secret-password token secret-token")


class V2CollectionTest(unittest.TestCase):
    def test_manual_collection_collects_enabled_clusters_and_updates_latest_vm_names(self) -> None:
        from app.v2.collection.service import CollectionService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="collection-secret")
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
                )
            )
            inventory.sync_clusters(
                tower.id,
                [
                    ClusterInput(cluster_id="enabled-cluster", name="Enabled", enabled=True),
                    ClusterInput(cluster_id="disabled-cluster", name="Disabled", enabled=False),
                ],
            )

            fake_client = FakeCloudTowerClient()
            result = CollectionService(db, settings, cloudtower_client=fake_client).run_manual_collection()

            self.assertEqual(result.status, "success")
            self.assertEqual(fake_client.collected_cluster_ids, ["enabled-cluster"])
            self.assertIn('smartx_vm_storage_used_bytes{tower_id="1",cluster_id="enabled-cluster",vm_id="vm-1",vm_name="VM One Renamed"} 42', result.metrics_text)
            latest_vm = CollectionService(db, settings, cloudtower_client=fake_client).latest_vm(1, "enabled-cluster", "vm-1")
            self.assertEqual(latest_vm["name"], "VM One Renamed")
            self.assertEqual(latest_vm["used_bytes"], 42)
            self.assertIn("VM One Renamed", CollectionService(db, settings, cloudtower_client=fake_client).latest_metrics_text())

    def test_collection_failure_masks_secret_material(self) -> None:
        from app.v2.collection.service import CollectionService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="collection-secret")
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
                )
            )
            inventory.sync_clusters(tower.id, [ClusterInput(cluster_id="cluster-a", name="Cluster A", enabled=True)])

            result = CollectionService(db, settings, cloudtower_client=FailingCloudTowerClient()).run_manual_collection()

            self.assertEqual(result.status, "failed")
            self.assertIn("login failed", result.message)
            self.assertNotIn("secret-password", result.message)
            self.assertNotIn("secret-token", result.message)


if __name__ == "__main__":
    unittest.main()
