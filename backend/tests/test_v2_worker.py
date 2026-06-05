import tempfile
import unittest
from pathlib import Path


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
        from app.v2.worker import build_collection_trigger

        trigger = build_collection_trigger(timezone="Asia/Shanghai", hour=2, minute=10)

        self.assertIn("hour='2'", str(trigger))
        self.assertIn("minute='10'", str(trigger))


if __name__ == "__main__":
    unittest.main()
