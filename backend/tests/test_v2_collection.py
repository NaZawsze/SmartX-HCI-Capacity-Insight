import tempfile
import unittest
from pathlib import Path
import sqlite3


class FakeCloudTowerClient:
    def __init__(self) -> None:
        self.collected_cluster_ids: list[str] = []

    def collect_cluster(self, tower, cluster):
        self.collected_cluster_ids.append(cluster.cluster_id)
        return {
            "cluster": {"used_bytes": 80, "total_bytes": 100},
            "vms": [
                {
                    "vm_id": "vm-1",
                    "name": "VM One Renamed",
                    "used_bytes": 42,
                    "volumes": [
                        {
                            "volume_id": "vol-1",
                            "name": "Root",
                            "path": "/root",
                            "size_bytes": 100,
                            "used_bytes": 60,
                            "storage_policy": "Replica-2",
                            "replica_num": 2,
                            "thin_provision": True,
                        }
                    ],
                },
            ],
        }


class FailingCloudTowerClient:
    def collect_cluster(self, tower, cluster):
        raise RuntimeError("login failed for password secret-password token secret-token")


class MissingCredentialsCloudTowerClient:
    def collect_cluster(self, tower, cluster):
        raise RuntimeError("Tower requires either an API token or username/password.")


class LoginFailedCloudTowerClient:
    def collect_cluster(self, tower, cluster):
        raise RuntimeError("Login failed with HTTP 401: user not found or password is incorrect")


class ConnectionRefusedCloudTowerClient:
    def collect_cluster(self, tower, cluster):
        raise RuntimeError("[Errno 111] Connection refused")


class PartiallyFailingCloudTowerClient:
    def __init__(self) -> None:
        self.collected_cluster_ids: list[str] = []

    def collect_cluster(self, tower, cluster):
        self.collected_cluster_ids.append(cluster.cluster_id)
        if cluster.cluster_id == "cluster-b":
            raise RuntimeError("cluster-b failed with token secret-token")
        return {
            "cluster": {"used_bytes": 80, "total_bytes": 100},
            "vms": [{"vm_id": "vm-a", "name": "VM A", "used_bytes": 42, "volumes": []}],
        }


class SucceedsOnRetryCloudTowerClient:
    def __init__(self) -> None:
        self.collected_cluster_ids: list[str] = []

    def collect_cluster(self, tower, cluster):
        self.collected_cluster_ids.append(cluster.cluster_id)
        return {
            "cluster": {"used_bytes": 90, "total_bytes": 100},
            "vms": [{"vm_id": f"vm-{cluster.cluster_id}", "name": f"VM {cluster.cluster_id}", "used_bytes": 90, "volumes": []}],
        }


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
            self.assertEqual(set(latest_vm), {"tower_id", "cluster_id", "vm_id", "name", "used_bytes"})
            self.assertEqual(latest_vm["used_bytes"], 42)
            self.assertIn("VM One Renamed", CollectionService(db, settings, cloudtower_client=fake_client).latest_metrics_text())
            with db.connection() as conn:
                row = conn.execute(
                    "SELECT volume_id, name, size_bytes, used_bytes, storage_policy, replica_num, thin_provision FROM vm_volumes WHERE tower_id = 1 AND cluster_id = 'enabled-cluster' AND vm_id = 'vm-1'"
                ).fetchone()
            self.assertEqual(dict(row), {"volume_id": "vol-1", "name": "Root", "size_bytes": 100, "used_bytes": 60, "storage_policy": "Replica-2", "replica_num": 2, "thin_provision": 1})

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

    def test_manual_collection_records_progress_task(self) -> None:
        from app.v2.collection.service import CollectionService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="collection-secret")
            db = V2Database(settings)
            db.initialize()
            inventory = InventoryService(db, settings)
            tower = inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com", username="admin", api_token="secret-token"))
            inventory.sync_clusters(tower.id, [ClusterInput(cluster_id="cluster-a", name="Cluster A", enabled=True)])

            result = CollectionService(db, settings, cloudtower_client=FakeCloudTowerClient(), tasks=TaskService(db)).run_manual_collection()

            self.assertEqual(result.status, "success")
            tasks = TaskService(db).list_tasks()
            self.assertEqual(tasks[0]["id"], f"collection-run-{result.run_id}")
            self.assertEqual(tasks[0]["title"], "执行采集")
            self.assertEqual(tasks[0]["status"], "success")
            self.assertEqual(tasks[0]["progress"], 100)
            self.assertIn("采集完成", tasks[0]["message"])

    def test_collection_errors_are_normalized_for_user_action(self) -> None:
        from app.v2.collection.service import CollectionService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService

        cases = [
            (MissingCredentialsCloudTowerClient(), "账号凭据未配置或未保存"),
            (LoginFailedCloudTowerClient(), "账号或密码错误"),
            (ConnectionRefusedCloudTowerClient(), "CloudTower 地址或端口连接失败"),
        ]

        for client, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmpdir:
                settings = V2Settings(data_root=Path(tmpdir), secret_key="collection-secret")
                db = V2Database(settings)
                db.initialize()
                inventory = InventoryService(db, settings)
                tower = inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com", username="admin", api_token="secret-token"))
                inventory.sync_clusters(tower.id, [ClusterInput(cluster_id="cluster-a", name="Cluster A", enabled=True)])

                result = CollectionService(db, settings, cloudtower_client=client).run_manual_collection()

                self.assertEqual(result.status, "failed")
                self.assertIn(expected, result.message)

    def test_partial_collection_publishes_only_successful_targets_and_records_warning_task(self) -> None:
        from app.v2.collection.service import CollectionService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="collection-secret")
            db = V2Database(settings)
            db.initialize()
            inventory = InventoryService(db, settings)
            tower = inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com", username="admin", api_token="secret-token"))
            inventory.sync_clusters(
                tower.id,
                [
                    ClusterInput(cluster_id="cluster-a", name="Cluster A", enabled=True),
                    ClusterInput(cluster_id="cluster-b", name="Cluster B", enabled=True),
                ],
            )

            fake_client = PartiallyFailingCloudTowerClient()
            result = CollectionService(db, settings, cloudtower_client=fake_client, tasks=TaskService(db)).run_manual_collection(trigger="scheduled")

            self.assertEqual(result.status, "partial_failed")
            self.assertIn("成功 1 个集群，失败 1 个集群", result.message)
            self.assertEqual(fake_client.collected_cluster_ids, ["cluster-a", "cluster-b"])
            self.assertIn('cluster_id="cluster-a"', result.metrics_text)
            self.assertIn('vm_id="vm-a"', result.metrics_text)
            self.assertNotIn('cluster_id="cluster-b"', result.metrics_text)
            self.assertEqual(CollectionService(db, settings, cloudtower_client=fake_client).latest_vm(tower.id, "cluster-a", "vm-a")["name"], "VM A")
            self.assertIsNone(CollectionService(db, settings, cloudtower_client=fake_client).latest_vm(tower.id, "cluster-b", "vm-a"))
            with db.connection() as conn:
                run = conn.execute("SELECT status, failed_targets_json, success_targets_json FROM collection_runs ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(run["status"], "partial_failed")
            self.assertIn("Cluster B", run["failed_targets_json"])
            self.assertNotIn("secret-token", run["failed_targets_json"])
            tasks = TaskService(db).list_tasks()
            self.assertEqual(tasks[0]["title"], "Tower/集群采集异常")
            self.assertEqual(tasks[0]["severity"], "warning")
            self.assertTrue(tasks[0]["unhandled"])
            self.assertIn("Cluster B", tasks[0]["message"])

    def test_retry_collection_can_target_only_previous_failed_cluster(self) -> None:
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
            tower = inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com", username="admin"))
            inventory.sync_clusters(
                tower.id,
                [
                    ClusterInput(cluster_id="cluster-a", name="Cluster A", enabled=True),
                    ClusterInput(cluster_id="cluster-b", name="Cluster B", enabled=True),
                ],
            )

            fake_client = SucceedsOnRetryCloudTowerClient()
            result = CollectionService(db, settings, cloudtower_client=fake_client).run_manual_collection(
                trigger="retry",
                attempt=1,
                target_filter={(tower.id, "cluster-b")},
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(fake_client.collected_cluster_ids, ["cluster-b"])
            self.assertNotIn('cluster_id="cluster-a"', result.metrics_text)
            self.assertIn('cluster_id="cluster-b"', result.metrics_text)

    def test_tower_retry_defaults_are_backfilled_for_new_and_existing_towers(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import TowerInput
        from app.v2.inventory.service import InventoryService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="collection-secret")
            db = V2Database(settings)
            db.initialize()
            inventory = InventoryService(db, settings)

            tower = inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com"))
            self.assertTrue(tower.collection_retry_enabled)
            self.assertEqual(tower.collection_retry_interval_minutes, 15)
            self.assertEqual(tower.collection_retry_max_attempts, 3)
            self.assertEqual(tower.collection_hour, 2)
            self.assertEqual(tower.collection_minute, 10)

        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_path = Path(tmpdir) / "smartx-capacity-insight-data" / "app" / "smartx.db"
            legacy_path.parent.mkdir(parents=True)
            conn = sqlite3.connect(legacy_path)
            conn.execute(
                """
                CREATE TABLE towers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    username TEXT,
                    password_encrypted TEXT,
                    api_token_encrypted TEXT,
                    verify_tls INTEGER NOT NULL DEFAULT 1,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute("INSERT INTO towers (name, base_url) VALUES ('Legacy Tower', 'https://tower.example.com')")
            conn.commit()
            conn.close()

            settings = V2Settings(data_root=Path(tmpdir), secret_key="collection-secret")
            db = V2Database(settings)
            db.initialize()
            refreshed = InventoryService(db, settings).list_towers()[0]
            self.assertTrue(refreshed.collection_retry_enabled)
            self.assertEqual(refreshed.collection_retry_interval_minutes, 15)
            self.assertEqual(refreshed.collection_retry_max_attempts, 3)


if __name__ == "__main__":
    unittest.main()
