from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class FakeJob:
    def __init__(self, job_id: str, signature=None):
        self.id = job_id
        self.signature = signature


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: dict[str, FakeJob] = {}
        self.added: list[tuple] = []
        self.removed: list[str] = []

    def get_jobs(self):
        return list(self.jobs.values())

    def get_job(self, job_id: str):
        return self.jobs.get(job_id)

    def add_job(self, fn, trigger=None, *, id: str, **kwargs):
        self.jobs[id] = FakeJob(id)
        self.added.append((id, trigger, kwargs.get("args")))

    def remove_job(self, job_id: str):
        self.jobs.pop(job_id, None)
        self.removed.append(job_id)


class V2CollectionScheduleSyncTest(unittest.TestCase):
    def _seed(self, tmpdir: str, *, interval: int, hour: int = 2, minute: int = 10, enabled: bool = True):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService

        settings = V2Settings(data_root=Path(tmpdir), secret_key="sync-secret", prometheus_url="http://prometheus:9090")
        database = V2Database(settings)
        database.initialize()
        inventory = InventoryService(database, settings)
        tower = inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com", username="admin"))
        inventory.sync_clusters(tower.id, [ClusterInput(cluster_id="cluster-a", name="Cluster A", enabled=True)])
        with database.connection() as conn:
            conn.execute(
                "UPDATE towers SET enabled = ?, collection_interval_minutes = ?, collection_hour = ?, collection_minute = ? WHERE id = ?",
                (int(enabled), interval, hour, minute, tower.id),
            )
        return settings, database, tower.id

    def test_interval_tower_creates_interval_job(self):
        from app.v2.worker import sync_collection_schedules

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, tower_id = self._seed(tmpdir, interval=30)
            scheduler = FakeScheduler()
            sync_collection_schedules(scheduler, database, timezone="Asia/Shanghai")
            self.assertEqual([item[0] for item in scheduler.added], [f"collect-tower-{tower_id}"])
            trigger = scheduler.added[0][1]
            self.assertEqual(trigger, "interval")

    def test_zero_interval_uses_daily_cron_trigger(self):
        try:
            import apscheduler  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("apscheduler not installed")
        from app.v2.worker import sync_collection_schedules

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, tower_id = self._seed(tmpdir, interval=0, hour=3, minute=25)
            scheduler = FakeScheduler()
            sync_collection_schedules(scheduler, database, timezone="Asia/Shanghai")
            trigger = scheduler.added[0][1]
            self.assertIsNotNone(trigger)
            self.assertIn("3", str(trigger))
            self.assertIn("25", str(trigger))

    def test_unchanged_schedule_not_readded_and_removed_when_disabled(self):
        from app.v2.worker import sync_collection_schedules

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, tower_id = self._seed(tmpdir, interval=60)
            scheduler = FakeScheduler()
            sync_collection_schedules(scheduler, database, timezone="Asia/Shanghai")
            added_first = list(scheduler.added)
            sync_collection_schedules(scheduler, database, timezone="Asia/Shanghai")
            self.assertEqual(scheduler.added, added_first)

            from app.v2.inventory.models import TowerInput
            from app.v2.inventory.service import InventoryService

            inventory = InventoryService(database, settings)
            inventory.update_tower(tower_id, TowerInput(name="Tower A", base_url="https://tower.example.com", username="admin", enabled=False))
            sync_collection_schedules(scheduler, database, timezone="Asia/Shanghai")
            self.assertIn(f"collect-tower-{tower_id}", scheduler.removed)


if __name__ == "__main__":
    unittest.main()
