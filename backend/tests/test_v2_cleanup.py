import tempfile
import unittest
from pathlib import Path


try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local host may not have web deps.
    TestClient = None


class V2CleanupServiceTest(unittest.TestCase):
    def test_cleanup_scans_and_removes_runtime_artifacts_without_touching_backups(self) -> None:
        from app.v2.cleanup.service import CleanupService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="cleanup-secret")
            database = V2Database(settings)
            database.initialize()
            (settings.upgrades_dir / "pkg.tar.gz").write_bytes(b"upgrade")
            (settings.reports_dir / "report.xlsx").write_bytes(b"report")
            (settings.migrations_dir / "migration.tar.gz").write_bytes(b"migration")
            (settings.imports_dir / "task" / "upload.tar.gz").parent.mkdir(parents=True)
            (settings.imports_dir / "task" / "upload.tar.gz").write_bytes(b"import")
            settings.backups_dir.mkdir(parents=True, exist_ok=True)
            (settings.backups_dir / "keep.tar.gz").write_bytes(b"backup")

            cleanup = CleanupService(settings, TaskService(database))
            scan = cleanup.scan_artifacts()

            self.assertGreater(scan["total_size"], 0)
            self.assertEqual(scan["total_count"], 4)
            self.assertEqual({item["key"] for item in scan["items"]}, {"upgrades", "reports", "migrations", "imports"})

            result = cleanup.cleanup_artifacts()

            self.assertEqual(result["deleted_count"], 4)
            self.assertEqual(result["space_reclaimed"], scan["total_size"])
            self.assertTrue((settings.backups_dir / "keep.tar.gz").is_file())
            self.assertFalse((settings.reports_dir / "report.xlsx").exists())
            task = TaskService(database).list_tasks()[0]
            self.assertEqual(task["type"], "cleanup")
            self.assertEqual(task["status"], "success")
            self.assertGreater(task["progress"], 0)

    def test_image_cleanup_scans_and_cleans_with_executor_output(self) -> None:
        from app.v2.cleanup.service import CleanupService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService

        class FakeExecutor:
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def output(self, command: list[str]) -> str:
                self.commands.append(command)
                if command[:3] == ["docker", "image", "ls"]:
                    return '[{"ID":"sha256:abc","Repository":"old","Tag":"v0.1","Size":"128MB","CreatedAt":"2026-01-01 00:00:00 +0000 UTC"}]'
                if command[:3] == ["docker", "image", "inspect"]:
                    return '[{"Id":"sha256:abc","Size":134217728,"RepoTags":["old:v0.1"],"Created": "2026-01-01T00:00:00Z"}]'
                if command[:3] == ["docker", "image", "rm"]:
                    return "Untagged: old:v0.1\nDeleted: sha256:abc\n"
                return ""

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="cleanup-secret")
            database = V2Database(settings)
            database.initialize()
            executor = FakeExecutor()
            cleanup = CleanupService(settings, TaskService(database), executor=executor)

            scan = cleanup.scan_unused_images()
            self.assertEqual(scan["image_count"], 1)
            self.assertEqual(scan["space_reclaimable"], 134217728)
            self.assertEqual(scan["images"][0]["display_name"], "old:v0.1")

            result = cleanup.cleanup_unused_images()
            self.assertEqual(result["deleted_count"], 1)
            self.assertEqual(result["space_reclaimed"], 134217728)
            self.assertTrue(any(command[:3] == ["docker", "image", "rm"] for command in executor.commands))


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed.")
class V2CleanupApiTest(unittest.TestCase):
    def test_cleanup_api_requires_auth_scans_and_cleans_artifacts(self) -> None:
        import os

        from app.v2.config import settings_from_environment
        from app.v2.main import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_SECRET_KEY"] = "cleanup-api-secret"
            os.environ["SMARTX_ADMIN_PASSWORD"] = "password"
            try:
                app = create_app()
                settings = settings_from_environment()
                settings.ensure_directories()
                (settings.reports_dir / "report.xlsx").write_bytes(b"report")
                with TestClient(app) as client:
                    self.assertEqual(client.get("/api/admin/system/cleanup-artifacts/scan").status_code, 401)
                    token = client.post("/api/auth/login", json={"username": "admin", "password": "password"}).json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}
                    scan = client.get("/api/admin/system/cleanup-artifacts/scan", headers=headers)
                    self.assertEqual(scan.status_code, 200)
                    self.assertGreater(scan.json()["total_size"], 0)
                    result = client.post("/api/admin/system/cleanup-artifacts", headers=headers)
                    self.assertEqual(result.status_code, 200)
                    self.assertEqual(result.json()["deleted_count"], 1)
                    self.assertFalse((settings.reports_dir / "report.xlsx").exists())

                    image_scan = client.get("/api/admin/system/cleanup-images/scan", headers=headers)
                    self.assertEqual(image_scan.status_code, 200)

                    image_cleanup = client.post("/api/admin/system/cleanup-images", headers=headers)
                    self.assertEqual(image_cleanup.status_code, 200)

                    restart = client.post("/api/admin/system/restart", headers=headers)
                    self.assertEqual(restart.status_code, 200)
                    self.assertEqual(restart.json()["services"], ["web-api", "collector-worker", "prometheus"])
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_SECRET_KEY", None)
                os.environ.pop("SMARTX_ADMIN_PASSWORD", None)


if __name__ == "__main__":
    unittest.main()
