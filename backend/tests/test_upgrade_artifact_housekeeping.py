from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.upgrade_runner.store import TaskStore  # noqa: E402
from app.v2.config import V2Settings  # noqa: E402
from app.v2.database import V2Database  # noqa: E402
from app.v2.tasks.service import TaskService  # noqa: E402
from app.v2.upgrade.housekeeping import (  # noqa: E402
    CLEANED_MESSAGE,
    UpgradeArtifactHousekeeper,
    start_upgrade_housekeeping_daemon,
)

PAYLOAD = b"p" * 2048
ARCHIVE = b"a" * 128


def _make_task(
    upgrades_dir: Path,
    task_id: str,
    status: str,
    *,
    age_days: float = 10,
    mtime_offset: float = 0,
    package_outside: bool = False,
) -> Path:
    task_dir = upgrades_dir / task_id
    package_dir = task_dir / "package"
    (package_dir / "images").mkdir(parents=True)
    (package_dir / "images" / "web-api.tar").write_bytes(PAYLOAD)
    archive = task_dir / f"{task_id}.tar.gz"
    archive.write_bytes(ARCHIVE)
    stamp = (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat()
    package_path = package_dir
    if package_outside:
        outside = upgrades_dir.parent / f"{task_id}-outside"
        (outside / "images").mkdir(parents=True)
        (outside / "images" / "web-api.tar").write_bytes(PAYLOAD)
        package_path = outside
    TaskStore(task_dir).save(
        {
            "task_id": task_id,
            "status": status,
            "created_at": stamp,
            "updated_at": stamp,
            "filename": archive.name,
            "package_path": str(package_path),
            "uploaded_path": str(archive),
        }
    )
    seconds = datetime.now(timezone.utc).timestamp() + mtime_offset
    os.utime(task_dir, (seconds, seconds))
    return task_dir


class HousekeepingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = V2Settings(data_root=Path(self.tmp.name), secret_key="upgrade-secret")
        self.database = V2Database(self.settings)
        self.database.initialize()
        self.tasks = TaskService(self.database)
        self.housekeeper = UpgradeArtifactHousekeeper(self.settings, self.tasks)
        self.upgrades = Path(self.settings.upgrades_dir)

    def _load(self, task_dir: Path) -> dict:
        return TaskStore(task_dir).load()

    def test_cleans_expired_precheck_failed_payload_only(self):
        task_dir = _make_task(self.upgrades, "upgrade-old", "precheck_failed", age_days=10)
        result = self.housekeeper.cleanup_stale(keep_recent=0)
        self.assertEqual(result["deleted"], ["upgrade-old"])
        self.assertGreater(result["reclaimed_bytes"], 0)
        self.assertFalse((task_dir / "package").exists())
        self.assertFalse((task_dir / "upgrade-old.tar.gz").exists())
        self.assertTrue((task_dir / "task.json").is_file())
        saved = self._load(task_dir)
        self.assertIsNone(saved["package_path"])
        self.assertIsNone(saved["uploaded_path"])
        self.assertIn("package_cleaned_at", saved)

    def test_cleans_expired_uploaded_task(self):
        task_dir = _make_task(self.upgrades, "upgrade-uploaded", "uploaded", age_days=30)
        result = self.housekeeper.cleanup_stale(keep_recent=0)
        self.assertEqual(result["deleted"], ["upgrade-uploaded"])
        self.assertFalse((task_dir / "package").exists())

    def test_within_ttl_is_kept(self):
        task_dir = _make_task(self.upgrades, "upgrade-fresh", "precheck_failed", age_days=1)
        result = self.housekeeper.cleanup_stale()
        self.assertEqual(result["deleted"], [])
        self.assertTrue((task_dir / "package").exists())

    def test_executed_tasks_are_never_cleaned(self):
        dirs = [
            _make_task(self.upgrades, f"upgrade-{status}", status, age_days=60)
            for status in ("success", "failed", "cancelled", "precheck_passed", "running")
        ]
        result = self.housekeeper.cleanup_stale(keep_recent=0)
        self.assertEqual(result["deleted"], [])
        for task_dir in dirs:
            self.assertTrue((task_dir / "package").exists(), task_dir)

    def test_keeps_recent_n_candidates(self):
        oldest = _make_task(self.upgrades, "upgrade-a", "precheck_failed", age_days=30, mtime_offset=-3000)
        middle = _make_task(self.upgrades, "upgrade-b", "precheck_failed", age_days=30, mtime_offset=-2000)
        newest = _make_task(self.upgrades, "upgrade-c", "precheck_failed", age_days=30, mtime_offset=-1000)
        result = self.housekeeper.cleanup_stale(keep_recent=1)
        self.assertEqual(result["kept"], ["upgrade-c"])
        self.assertEqual(sorted(result["deleted"]), ["upgrade-a", "upgrade-b"])
        self.assertTrue((newest / "package").exists())
        self.assertFalse((oldest / "package").exists())
        self.assertFalse((middle / "package").exists())

    def test_active_upgrade_blocks_the_whole_run(self):
        self.database.initialize()
        _make_task(self.upgrades, "upgrade-expired", "precheck_failed", age_days=30)
        active = _make_task(self.upgrades, "upgrade-running", "running", age_days=0, mtime_offset=10)
        result = self.housekeeper.cleanup_stale(keep_recent=0)
        self.assertEqual(result["skipped"], "active_upgrade")
        self.assertEqual(result["active_task_ids"], ["upgrade-running"])
        self.assertEqual(result["deleted"], [])
        self.assertTrue((self.upgrades / "upgrade-expired" / "package").exists())
        self.assertTrue((active / "package").exists())

    def test_ttl_zero_disables_cleanup(self):
        task_dir = _make_task(self.upgrades, "upgrade-old", "precheck_failed", age_days=30)
        result = self.housekeeper.cleanup_stale(ttl_days=0, keep_recent=0)
        self.assertEqual(result["skipped"], "disabled")
        self.assertTrue((task_dir / "package").exists())

    def test_payload_outside_task_dir_is_skipped(self):
        task_dir = _make_task(self.upgrades, "upgrade-outside", "precheck_failed", age_days=30, package_outside=True)
        outside = Path(self.tmp.name) / "upgrade-outside-outside"
        self.housekeeper.cleanup_stale(keep_recent=0)
        self.assertTrue((outside / "images" / "web-api.tar").exists())
        self.assertTrue((task_dir / "package").exists())

    def test_creates_cleanup_task_record_only_when_deleted(self):
        _make_task(self.upgrades, "upgrade-old", "precheck_failed", age_days=30)
        self.housekeeper.cleanup_stale(keep_recent=0)
        records = [task for task in self.tasks.list_tasks() if task["type"] == "cleanup"]
        self.assertEqual(len(records), 1)
        self.assertIn(CLEANED_MESSAGE, records[0]["logs"])

    def test_no_task_record_when_nothing_deleted(self):
        _make_task(self.upgrades, "upgrade-fresh", "precheck_failed", age_days=1)
        self.housekeeper.cleanup_stale()
        self.assertEqual([task for task in self.tasks.list_tasks() if task["type"] == "cleanup"], [])

    def test_daemon_disabled_for_non_positive_interval(self):
        self.assertIsNone(start_upgrade_housekeeping_daemon(self.settings, self.database, interval_seconds=0))

    def test_daemon_starts_and_reports_stop_event(self):
        event = start_upgrade_housekeeping_daemon(self.settings, self.database, interval_seconds=3600)
        self.assertIsNotNone(event)
        assert event is not None
        event.set()


class PrecheckAfterCleanupTest(unittest.TestCase):
    """包内容被清理后，预检查给出可读失败而不是路径异常。"""

    def test_precheck_reports_cleaned_package(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="upgrade-secret")
            database = V2Database(settings)
            database.initialize()
            tasks = TaskService(database)
            task_dir = Path(settings.upgrades_dir) / "upgrade-cleaned"
            TaskStore(task_dir).save(
                {
                    "task_id": "upgrade-cleaned",
                    "status": "precheck_failed",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "manifest": {"version": "v0.5.3", "schema_version": "3", "components": []},
                    "package_path": None,
                }
            )
            from app.v2.upgrade.service import UpgradeCommandExecutor, UpgradeService

            class FakeExecutor(UpgradeCommandExecutor):
                def run(self, command, *, cwd=None):  # pragma: no cover
                    return None

            service = UpgradeService(
                settings, tasks, executor=FakeExecutor(), project_path=Path(tmpdir) / "project"
            )
            result = service.precheck("upgrade-cleaned")
        self.assertFalse(result["ok"] if "ok" in result else all(c["ok"] for c in result["checks"]))
        self.assertEqual(result["checks"][0]["name"], "package")
        self.assertIn("已被自动清理", result["checks"][0]["message"])


if __name__ == "__main__":
    unittest.main()
