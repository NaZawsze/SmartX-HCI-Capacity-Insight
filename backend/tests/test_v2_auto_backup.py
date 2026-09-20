import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


class AutoBackupServiceTest(unittest.TestCase):
    def _make_service(self, tmpdir: str):
        from app.v2.auto_backup import AutoBackupService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService

        settings = V2Settings(
            data_root=Path(tmpdir),
            secret_key="auto-backup-secret",
            project_path_override=Path(tmpdir) / "project",
        )
        database = V2Database(settings)
        database.initialize()
        return settings, database, AutoBackupService(database, settings, TaskService(database))

    def test_run_backup_creates_paired_snapshot_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, service = self._make_service(tmpdir)
            with database.connection() as conn:
                conn.execute("CREATE TABLE probe (value TEXT)")
                conn.execute("INSERT INTO probe VALUES ('hello')")
            settings.project_path.mkdir(parents=True, exist_ok=True)
            settings.project_path.joinpath(".env").write_text("SMARTX_SECRET_KEY=pair-key\n", encoding="utf-8")

            now = datetime(2026, 9, 20, 6, 0, 0, tzinfo=timezone.utc)
            result = service.run_backup(now=now)

            self.assertEqual(result["status"], "success")
            backup_dir = Path(result["backup_dir"])
            self.assertEqual(backup_dir.name, "auto-backup-20260920T060000Z")
            snapshot = backup_dir / "smartx.db"
            self.assertTrue(snapshot.is_file())
            with sqlite3.connect(snapshot) as conn:
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(conn.execute("SELECT value FROM probe").fetchone()[0], "hello")
            env_copy = backup_dir / "project.env"
            self.assertTrue(env_copy.is_file())
            self.assertEqual(env_copy.read_text(encoding="utf-8"), "SMARTX_SECRET_KEY=pair-key\n")
            manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["format"], "smartx-auto-backup")
            self.assertEqual(manifest["env"]["included"], True)
            self.assertTrue(manifest["database"]["sha256"])
            from app.v2.tasks.service import TaskService
            record = TaskService(database).list_tasks()[0]
            self.assertEqual(record["type"], "backup")
            self.assertEqual(record["status"], "success")
            self.assertIn("配对", record["message"])

    def test_run_backup_without_env_file_still_backs_up_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, service = self._make_service(tmpdir)
            result = service.run_backup(now=datetime(2026, 9, 20, 6, 0, 0, tzinfo=timezone.utc))
            self.assertEqual(result["status"], "success")
            self.assertFalse(result["env_included"])
            from app.v2.tasks.service import TaskService
            record = TaskService(database).list_tasks()[0]
            self.assertTrue(any("警告" in line for line in record["logs"]))

    def test_retention_prunes_oldest_sets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, service = self._make_service(tmpdir)
            settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            settings.backups_dir.mkdir(parents=True, exist_ok=True)
            for index in range(1, 8):
                stale = settings.backups_dir / f"auto-backup-2026090{index}T000000Z"
                stale.mkdir()
                (stale / "smartx.db").write_bytes(b"x")
            (settings.backups_dir / "auto-backup-20260907T000000Z" / "project.env").write_bytes(b"e")

            result = service.run_backup(now=datetime(2026, 9, 20, 6, 0, 0, tzinfo=timezone.utc))

            remaining = sorted(path.name for path in settings.backups_dir.iterdir() if path.is_dir())
            self.assertEqual(len(remaining), 7)
            self.assertIn("auto-backup-20260920T060000Z", remaining)
            self.assertNotIn("auto-backup-20260901T000000Z", remaining)
            self.assertIn("auto-backup-20260902T000000Z", remaining)
            self.assertEqual(len(result["pruned"]), 1)

    def test_missing_database_reports_failure_without_task_write(self) -> None:
        from app.v2.auto_backup import AutoBackupService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(
                data_root=Path(tmpdir),
                secret_key="auto-backup-secret",
                db_path_override=Path(tmpdir) / "missing" / "smartx.db",
                project_path_override=Path(tmpdir) / "project",
            )
            service = AutoBackupService(V2Database(settings), settings, tasks=None)
            result = service.run_backup(now=datetime(2026, 9, 20, 6, 0, 0, tzinfo=timezone.utc))
            self.assertEqual(result["status"], "failed")

    def test_daemon_disabled_with_nonpositive_interval(self) -> None:
        from app.v2.auto_backup import start_auto_backup_daemon
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, database, _ = self._make_service(tmpdir)
            os.environ["SMARTX_AUTO_BACKUP_INTERVAL_HOURS"] = "0"
            try:
                self.assertIsNone(start_auto_backup_daemon(database, settings))
            finally:
                os.environ.pop("SMARTX_AUTO_BACKUP_INTERVAL_HOURS", None)


if __name__ == "__main__":
    unittest.main()
