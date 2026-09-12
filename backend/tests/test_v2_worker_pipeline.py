from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

NOW_TS = 1_700_000_000
TARGET = (1, "cluster-a")


class FakeResult:
    def __init__(self, run_id: int, metrics_text: str = "# HELP test", status: str = "success"):
        self.run_id = run_id
        self.metrics_text = metrics_text
        self.status = status


class FakeService:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def run_manual_collection(self, **kwargs):
        self.calls.append(kwargs)
        return self.results.pop(0)


class FakeScheduler:
    def __init__(self):
        self.jobs = []

    def add_job(self, fn, trigger=None, *, id=None, args=None, **kwargs):
        self.jobs.append({"id": id, "trigger": trigger, "args": args})


class V2WorkerPipelineTest(unittest.TestCase):
    def _seed(self, tmpdir: str):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService
        from app.v2.tasks.service import TaskService

        settings = V2Settings(data_root=Path(tmpdir), secret_key="pipe-secret", prometheus_url="http://prometheus:9090")
        database = V2Database(settings)
        database.initialize()
        inventory = InventoryService(database, settings)
        tower = inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com", username="admin"))
        inventory.sync_clusters(tower.id, [ClusterInput(cluster_id="cluster-a", name="Cluster A", enabled=True)])
        return settings, database, TaskService(database), tower.id

    def run_outcome(self, database, tasks, service, result, scheduler=None, previous_metrics=""):
        from app.v2 import worker
        from app.v2.worker import _handle_collection_outcome as handler

        with mock.patch("app.v2.worker._run_data_quality_check") as dq, mock.patch(
            "app.v2.worker._record_collection_warning"
        ) as warn, mock.patch("app.v2.worker._schedule_retry_cycle") as schedule, mock.patch.object(
            worker, "metrics_body", return_value=previous_metrics.encode("utf-8")
        ):
            failed = handler(database, scheduler, tasks, service, result, previous_metrics)
            return {
                "failed": failed,
                "dq_calls": dq.call_count,
                "warnings": [call.kwargs for call in warn.call_args_list],
                "scheduled": [call.kwargs for call in schedule.call_args_list],
            }

    def test_success_path_saves_metrics_and_no_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, tasks, tower_id = self._seed(tmpdir)
            service = FakeService([FakeResult(1, "# HELP test 1")])
            info = self.run_outcome(database, tasks, service, FakeResult(1, "# HELP test 1"))
            self.assertEqual(info["failed"], [])
            self.assertEqual(info["dq_calls"], 1)
            self.assertEqual(info["warnings"], [])
            self.assertEqual(info["scheduled"], [])
            with database.connection() as conn:
                text = conn.execute("SELECT metrics_text FROM metric_snapshots WHERE id = 1").fetchone()["metrics_text"]
            self.assertIn("# HELP test 1", text)

    def test_failure_with_scheduler_registers_retry_not_warning(self):
        from app.v2 import worker

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, tasks, tower_id = self._seed(tmpdir)
            result = FakeResult(2, "")
            failed = [{"tower_id": tower_id, "tower_name": "Tower A", "cluster_id": "cluster-a", "cluster_name": "Cluster A", "message": "timeout"}]
            with mock.patch.object(worker, "_failed_targets", return_value=failed):
                info = self.run_outcome(database, tasks, FakeService([result]), result, scheduler=FakeScheduler())
            self.assertEqual(len(info["failed"]), 1)
            self.assertEqual(len(info["scheduled"]), 1)
            self.assertEqual(info["scheduled"][0]["attempt"], 1)
            self.assertEqual(info["warnings"], [])

    def test_failure_without_retry_config_records_warning(self):
        from app.v2 import worker

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, tasks, tower_id = self._seed(tmpdir)
            with database.connection() as conn:
                conn.execute("UPDATE towers SET collection_retry_enabled = 0 WHERE id = ?", (tower_id,))
            result = FakeResult(3, "")
            failed = [{"tower_id": tower_id, "tower_name": "Tower A", "cluster_id": "cluster-a", "cluster_name": "Cluster A", "message": "timeout"}]
            with mock.patch.object(worker, "_failed_targets", return_value=failed):
                info = self.run_outcome(database, tasks, FakeService([result]), result)
            self.assertEqual(len(info["warnings"]), 1)
            self.assertEqual(info["warnings"][0]["attempt"], 0)

    def test_retry_cycle_success_runs_dq_only(self):
        from app.v2 import worker

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, tasks, tower_id = self._seed(tmpdir)
            service = FakeService([FakeResult(10, "# retry metrics")])
            with mock.patch.object(worker, "_failed_targets", return_value=[]), mock.patch.object(
                worker, "_run_data_quality_check"
            ) as dq, mock.patch.object(worker, "_record_collection_warning") as warn, mock.patch.object(
                worker, "_schedule_retry_cycle"
            ) as schedule, mock.patch.object(worker, "metrics_body", return_value=b"# previous"):
                worker._run_retry_cycle(FakeScheduler(), database, attempt=1, max_attempts=3, targets={TARGET}, service=service, tasks=tasks)
            self.assertEqual(dq.call_count, 1)
            self.assertEqual(warn.call_count, 0)
            self.assertEqual(schedule.call_count, 0)
            with database.connection() as conn:
                text = conn.execute("SELECT metrics_text FROM metric_snapshots WHERE id = 1").fetchone()["metrics_text"]
            self.assertIn("# previous", text)
            self.assertIn("# retry metrics", text)

    def test_retry_cycle_final_failure_records_warning(self):
        from app.v2 import worker

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, tasks, tower_id = self._seed(tmpdir)
            service = FakeService([FakeResult(11, "")])
            with mock.patch.object(worker, "_failed_targets", return_value=[{"tower_id": TARGET[0], "cluster_id": TARGET[1], "message": "timeout"}]), mock.patch.object(
                worker, "_run_data_quality_check"
            ) as dq, mock.patch.object(worker, "_record_collection_warning") as warn, mock.patch.object(
                worker, "_schedule_retry_cycle"
            ) as schedule:
                worker._run_retry_cycle(FakeScheduler(), database, attempt=3, max_attempts=3, targets={TARGET}, service=service, tasks=tasks)
            self.assertEqual(schedule.call_count, 0)
            self.assertEqual(warn.call_count, 1)
            self.assertEqual(dq.call_count, 1)


if __name__ == "__main__":
    unittest.main()
