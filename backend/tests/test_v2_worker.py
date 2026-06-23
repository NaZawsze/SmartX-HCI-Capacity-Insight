import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
