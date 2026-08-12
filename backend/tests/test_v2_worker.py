import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch


class V2WorkerTest(unittest.TestCase):
    def test_metrics_body_reads_latest_v2_collection_snapshot(self) -> None:
        from app.v2.collection.service import CollectionService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.worker import metrics_body

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="worker-secret")
            db = V2Database(settings)
            db.initialize()
            with db.connection() as conn:
                conn.execute("INSERT INTO metric_snapshots (id, metrics_text) VALUES (1, ?)", ("smartx_metric 1\n",))

            self.assertEqual(metrics_body(db).decode("utf-8"), "smartx_metric 1\n")
            self.assertEqual(CollectionService(db, settings, cloudtower_client=object()).latest_metrics_text(), "smartx_metric 1\n")

    def test_scheduler_uses_configured_collection_time(self) -> None:
        try:
            import apscheduler  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("APScheduler test dependency is not installed.")
        from app.v2.worker import build_collection_trigger

        trigger = build_collection_trigger(timezone="Asia/Shanghai", hour=2, minute=10)

        self.assertIn("hour='2'", str(trigger))
        self.assertIn("minute='10'", str(trigger))

    def test_scheduled_collection_retries_only_failed_targets(self) -> None:
        from app.v2 import worker
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="worker-secret")
            db = V2Database(settings)
            db.initialize()
            inventory = InventoryService(db, settings)
            tower = inventory.create_tower(
                TowerInput(
                    name="Tower A",
                    base_url="https://tower.example.com",
                    collection_retry_interval_minutes=1,
                    collection_retry_max_attempts=1,
                )
            )
            inventory.sync_clusters(tower.id, [ClusterInput(cluster_id="cluster-a", name="Cluster A"), ClusterInput(cluster_id="cluster-b", name="Cluster B")])

            class FlakyCloudTower:
                calls: list[str] = []

                def __init__(self, *_args, **_kwargs) -> None:
                    pass

                def collect_cluster(self, _tower, cluster):
                    self.calls.append(cluster.cluster_id)
                    if cluster.cluster_id == "cluster-b" and self.calls.count("cluster-b") == 1:
                        raise RuntimeError("temporary failure")
                    return {"cluster": {"used_bytes": 1, "total_bytes": 2}, "vms": []}

            with patch.object(worker, "CloudTowerService", FlakyCloudTower), patch.object(worker.time, "sleep") as sleep:
                worker.run_collection(db)

            self.assertEqual(FlakyCloudTower.calls, ["cluster-a", "cluster-b", "cluster-b"])
            sleep.assert_called_once_with(60)
            body = worker.metrics_body(db).decode("utf-8")
            self.assertIn('cluster_id="cluster-a"', body)
            self.assertIn('cluster_id="cluster-b"', body)

    def test_scheduled_collection_runs_data_quality_alert_after_final_metrics(self) -> None:
        from app.v2 import worker
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="worker-secret")
            db = V2Database(settings)
            db.initialize()
            inventory = InventoryService(db, settings)
            tower = inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com"))
            inventory.sync_clusters(tower.id, [ClusterInput(cluster_id="cluster-a", name="Cluster A")])

            class WorkingCloudTower:
                def __init__(self, *_args, **_kwargs) -> None:
                    pass

                def collect_cluster(self, _tower, _cluster):
                    return {"cluster": {"used_bytes": 1, "total_bytes": 2}, "vms": [{"vm_id": "vm-1", "name": "VM 1", "used_bytes": 1}]}

            class FakeDataQuality:
                calls = 0

                def __init__(self, database, settings, *, tasks=None, **_kwargs) -> None:
                    self.database = database
                    self.settings = settings
                    self.tasks = tasks

                def evaluate_and_alert(self, *, period_days: int = 30):
                    self.__class__.calls += 1
                    self.tasks.create_task(
                        "data-quality-warning",
                        "collection",
                        "数据质量需关注",
                        status="failed",
                        progress=100,
                        message="SQLite VM 数：1\nPrometheus VM series 数：0",
                    )
                    return {"status": "warning"}

            with patch.object(worker, "CloudTowerService", WorkingCloudTower), patch.object(worker, "DataQualityService", FakeDataQuality):
                worker.run_collection(db)

            self.assertEqual(FakeDataQuality.calls, 1)
            alert = next(task for task in worker.TaskService(db).list_tasks(limit=20) if task["title"] == "数据质量需关注")
            self.assertIn("Prometheus VM series 数", alert["message"])

    def test_post_upgrade_collection_waits_for_parent_success_and_runs_once(self) -> None:
        from app.v2 import worker
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = V2Settings(data_root=root, secret_key="worker-secret")
            db = V2Database(settings)
            db.initialize()
            inventory = InventoryService(db, settings)
            tower = inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com"))
            inventory.sync_clusters(tower.id, [ClusterInput(cluster_id="cluster-a", name="Cluster A")])

            parent_id = "upgrade-auto-collection"
            parent_dir = settings.upgrades_dir / parent_id
            parent_dir.mkdir(parents=True)
            parent_file = parent_dir / "task.json"
            parent_file.write_text(json.dumps({"task_id": parent_id, "status": "running"}), encoding="utf-8")
            marker_file = parent_dir / "post-upgrade-collection.json"
            marker_file.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "parent_upgrade_task_id": parent_id,
                        "task_id": f"post-upgrade-collection-{parent_id}",
                        "target_version": "v0.5.2",
                        "status": "pending",
                    }
                ),
                encoding="utf-8",
            )

            class WorkingCloudTower:
                calls = 0

                def __init__(self, *_args, **_kwargs) -> None:
                    pass

                def collect_cluster(self, _tower, _cluster):
                    self.__class__.calls += 1
                    return {
                        "cluster": {"used_bytes": 80, "total_bytes": 100},
                        "vms": [{"vm_id": "vm-1", "name": "VM One Renamed", "used_bytes": 42}],
                    }

            with patch.object(worker, "CloudTowerService", WorkingCloudTower):
                self.assertIsNone(worker.run_pending_post_upgrade_collection(db))
                self.assertEqual(WorkingCloudTower.calls, 0)

                parent_file.write_text(json.dumps({"task_id": parent_id, "status": "success"}), encoding="utf-8")
                result = worker.run_pending_post_upgrade_collection(db)
                self.assertEqual(result.status, "success")
                self.assertEqual(WorkingCloudTower.calls, 1)

                self.assertIsNone(worker.run_pending_post_upgrade_collection(db))
                self.assertEqual(WorkingCloudTower.calls, 1)

            marker = json.loads(marker_file.read_text(encoding="utf-8"))
            self.assertEqual(marker["status"], "success")
            task = worker.TaskService(db).get_task(f"post-upgrade-collection-{parent_id}")
            self.assertEqual(task["title"], "升级后自动采集")
            self.assertEqual(task["status"], "success")
            with db.connection() as conn:
                row = conn.execute("SELECT name FROM vm_latest WHERE vm_id = 'vm-1'").fetchone()
            self.assertEqual(row["name"], "VM One Renamed")

    def test_post_upgrade_collection_discovers_successful_released_bridge_task_without_marker(self) -> None:
        from app.v2 import worker
        from app.v2.config import V2Settings
        from app.v2.database import V2Database

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="worker-secret")
            db = V2Database(settings)
            db.initialize()
            parent_id = "upgrade-released-bridge"
            parent_dir = settings.upgrades_dir / parent_id
            parent_dir.mkdir(parents=True)
            (parent_dir / "task.json").write_text(
                json.dumps(
                    {
                        "task_id": parent_id,
                        "status": "success",
                        "target_version": "v0.5.2",
                        "finished_at": "2026-07-15T01:00:00+00:00",
                        "manifest": {
                            "version": "v0.5.2",
                            "package_type": "platform",
                            "components": [{"type": "platform", "services": ["web-api"]}],
                            "post_upgrade": {"auto_collection": True},
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = worker.run_pending_post_upgrade_collection(db)

            self.assertIsNotNone(result)
            self.assertEqual(result.status, "success")
            marker = json.loads((parent_dir / "post-upgrade-collection.json").read_text(encoding="utf-8"))
            self.assertEqual(marker["parent_upgrade_task_id"], parent_id)
            self.assertEqual(marker["task_id"], f"post-upgrade-collection-{parent_id}")
            self.assertEqual(marker["status"], "success")
            task = worker.TaskService(db).get_task(f"post-upgrade-collection-{parent_id}")
            self.assertEqual(task["status"], "success")
            with db.connection() as conn:
                run = conn.execute("SELECT status, trigger FROM collection_runs ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual((run["status"], run["trigger"]), ("success", "post_upgrade"))

    def test_post_upgrade_collection_compatibility_marker_only_targets_latest_successful_platform_task(self) -> None:
        from app.v2 import worker
        from app.v2.config import V2Settings
        from app.v2.database import V2Database

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="worker-secret")
            db = V2Database(settings)
            db.initialize()
            for task_id, finished_at in (
                ("upgrade-older-platform", "2026-07-14T01:00:00+00:00"),
                ("upgrade-latest-platform", "2026-07-15T01:00:00+00:00"),
            ):
                task_dir = settings.upgrades_dir / task_id
                task_dir.mkdir(parents=True)
                (task_dir / "task.json").write_text(
                    json.dumps(
                        {
                            "task_id": task_id,
                            "status": "success",
                            "target_version": "v0.5.2",
                            "finished_at": finished_at,
                            "manifest": {
                                "version": "v0.5.2",
                                "package_type": "platform",
                                "components": [{"type": "platform", "services": ["web-api"]}],
                                "post_upgrade": {"auto_collection": True},
                            },
                        }
                    ),
                    encoding="utf-8",
                )

            result = worker.run_pending_post_upgrade_collection(db)

            self.assertIsNotNone(result)
            self.assertFalse((settings.upgrades_dir / "upgrade-older-platform" / "post-upgrade-collection.json").exists())
            self.assertTrue((settings.upgrades_dir / "upgrade-latest-platform" / "post-upgrade-collection.json").is_file())

    def test_post_upgrade_collection_compatibility_does_not_recreate_marker_for_existing_task(self) -> None:
        from app.v2 import worker
        from app.v2.config import V2Settings
        from app.v2.database import V2Database

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="worker-secret")
            db = V2Database(settings)
            db.initialize()
            parent_id = "upgrade-already-collected"
            parent_dir = settings.upgrades_dir / parent_id
            parent_dir.mkdir(parents=True)
            (parent_dir / "task.json").write_text(
                json.dumps(
                    {
                        "task_id": parent_id,
                        "status": "success",
                        "finished_at": "2026-07-15T01:00:00+00:00",
                        "manifest": {
                            "version": "v0.5.2",
                            "package_type": "platform",
                            "components": [{"type": "platform", "services": ["web-api"]}],
                            "post_upgrade": {"auto_collection": True},
                        },
                    }
                ),
                encoding="utf-8",
            )
            task_id = f"post-upgrade-collection-{parent_id}"
            worker.TaskService(db).create_task(
                task_id,
                "collection",
                "升级后自动采集",
                status="success",
                progress=100,
                message="采集已完成",
            )

            self.assertIsNone(worker.run_pending_post_upgrade_collection(db))
            self.assertFalse((parent_dir / "post-upgrade-collection.json").exists())

    def test_post_upgrade_collection_marks_interrupted_run_failed_without_retry(self) -> None:
        from app.v2 import worker
        from app.v2.config import V2Settings
        from app.v2.database import V2Database

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="worker-secret")
            db = V2Database(settings)
            db.initialize()
            parent_id = "upgrade-interrupted"
            task_id = f"post-upgrade-collection-{parent_id}"
            parent_dir = settings.upgrades_dir / parent_id
            parent_dir.mkdir(parents=True)
            (parent_dir / "task.json").write_text(json.dumps({"task_id": parent_id, "status": "success"}), encoding="utf-8")
            marker_file = parent_dir / "post-upgrade-collection.json"
            marker_file.write_text(
                json.dumps({"parent_upgrade_task_id": parent_id, "task_id": task_id, "status": "running"}),
                encoding="utf-8",
            )
            worker.TaskService(db).create_task(task_id, "collection", "升级后自动采集", status="running", progress=10)

            self.assertIsNone(worker.run_pending_post_upgrade_collection(db))

            marker = json.loads(marker_file.read_text(encoding="utf-8"))
            task = worker.TaskService(db).get_task(task_id)
            self.assertEqual(marker["status"], "failed")
            self.assertEqual(task["status"], "failed")
            self.assertEqual(task["severity"], "warning")


if __name__ == "__main__":
    unittest.main()
