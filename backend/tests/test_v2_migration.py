import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path


try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local host may not have web deps.
    TestClient = None


class V2MigrationServiceTest(unittest.TestCase):
    def test_export_archive_includes_sqlite_and_prometheus_history_and_saves_task(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService
        from app.v2.migration.service import MigrationService
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="migration-secret")
            database = V2Database(settings)
            database.initialize()
            inventory = InventoryService(database, settings)
            tower = inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com"))
            inventory.sync_clusters(tower.id, [ClusterInput(cluster_id="cluster-a", name="Cluster A")])
            block = settings.prometheus_data_dir / "01ABC"
            block.mkdir(parents=True)
            (block / "meta.json").write_text("{}", encoding="utf-8")
            (settings.prometheus_data_dir / "wal").mkdir()
            (settings.prometheus_data_dir / "wal" / "runtime").write_text("skip", encoding="utf-8")

            content, filename, path, download_url = MigrationService(database, settings, TaskService(database)).build_export_archive()
            second_content, second_filename, second_path, _ = MigrationService(database, settings, TaskService(database)).build_export_archive(record_task=False)

            self.assertTrue(filename.startswith("smartx-capacity-insight-migration-"))
            self.assertNotEqual(filename, second_filename)
            self.assertTrue(path.is_file())
            self.assertTrue(second_path.is_file())
            self.assertEqual(path.parent, settings.migrations_dir)
            self.assertTrue(download_url.startswith("/api/admin/exports/migrations/"))
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
                names = set(archive.getnames())
                manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))
                archived_db = archive.extractfile("app/smartx.db").read()
            self.assertIn("manifest.json", names)
            self.assertIn("app/smartx.db", names)
            self.assertIn("prometheus/01ABC/meta.json", names)
            self.assertNotIn("prometheus/wal/runtime", names)
            self.assertIn("files", manifest)
            self.assertIn("app/smartx.db", manifest["files"])
            self.assertEqual(manifest["files"]["app/smartx.db"]["sha256"], __import__("hashlib").sha256(archived_db).hexdigest())
            tasks = TaskService(database).list_tasks()
            self.assertEqual(tasks[0]["type"], "migration_export")
            self.assertEqual(tasks[0]["links"][0]["url"], download_url)

    def test_import_merge_creates_backup_and_does_not_overwrite_existing_cluster(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService
        from app.v2.migration.service import MigrationService
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as source_tmp, tempfile.TemporaryDirectory() as target_tmp:
            source_settings = V2Settings(data_root=Path(source_tmp), secret_key="source-secret")
            source_db = V2Database(source_settings)
            source_db.initialize()
            source_inventory = InventoryService(source_db, source_settings)
            source_tower = source_inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com"))
            source_inventory.sync_clusters(source_tower.id, [ClusterInput(cluster_id="cluster-a", name="Incoming Cluster")])
            archive_content, _, _, _ = MigrationService(source_db, source_settings, TaskService(source_db)).build_export_archive()

            target_settings = V2Settings(data_root=Path(target_tmp), secret_key="target-secret")
            target_db = V2Database(target_settings)
            target_db.initialize()
            target_inventory = InventoryService(target_db, target_settings)
            target_tower = target_inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com"))
            target_inventory.sync_clusters(target_tower.id, [ClusterInput(cluster_id="cluster-a", name="Existing Cluster")])
            (target_settings.prometheus_data_dir / "01TARGET").mkdir(parents=True)

            result = MigrationService(target_db, target_settings, TaskService(target_db)).restore_archive_bytes(archive_content, filename="migration.tar.gz", mode="merge")

            self.assertTrue(result["ok"])
            self.assertTrue(result["health"]["sqlite"]["exists"])
            self.assertTrue(result["health"]["prometheus"]["exists"])
            self.assertFalse(result["health"]["complete"])
            self.assertTrue(Path(result["backup_path"]).is_file())
            with tarfile.open(result["backup_path"], mode="r:gz") as backup:
                backup_names = set(backup.getnames())
            self.assertIn("app/smartx.db", backup_names)
            self.assertIn("prometheus/01TARGET", backup_names)
            clusters = target_inventory.list_towers()[0].clusters
            self.assertEqual(clusters[0].name, "Existing Cluster")
            self.assertIn("smartx_db", result["restored"])


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed.")
class V2MigrationApiTest(unittest.TestCase):
    def test_migration_api_requires_auth_exports_downloads_and_imports_with_backup(self) -> None:
        import os

        from app.v2.main import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_SECRET_KEY"] = "migration-api-secret"
            os.environ["SMARTX_ADMIN_PASSWORD"] = "password"
            try:
                app = create_app()
                with TestClient(app) as client:
                    self.assertEqual(client.get("/api/admin/migration/export").status_code, 401)
                    token = client.post("/api/auth/login", json={"username": "admin", "password": "password"}).json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}

                    exported = client.get("/api/admin/migration/export", headers=headers)
                    self.assertEqual(exported.status_code, 200)
                    self.assertEqual(exported.headers["content-type"], "application/gzip")
                    self.assertTrue(Path(exported.headers["x-smartx-export-path"]).is_file())
                    self.assertTrue(exported.headers["x-smartx-export-url"].startswith("/api/admin/exports/migrations/"))

                    task = client.post("/api/admin/migration/export/start", headers=headers)
                    self.assertEqual(task.status_code, 200)
                    task_payload = task.json()
                    self.assertIn(task_payload["status"], {"running", "succeeded"})
                    self.assertGreaterEqual(task_payload["progress"], 0)
                    self.assertIn("steps", task_payload)
                    self.assertIn("total_bytes", task_payload)
                    self.assertIn("processed_bytes", task_payload)

                    task_status = client.get(f"/api/admin/migration/export/status/{task_payload['task_id']}", headers=headers)
                    self.assertEqual(task_status.status_code, 200)
                    status_payload = task_status.json()
                    self.assertEqual(status_payload["task_id"], task_payload["task_id"])
                    self.assertTrue(status_payload["logs"])
                    self.assertTrue(any("当前文件" in line for line in status_payload["logs"]))
                    self.assertEqual(status_payload["processed_bytes"], task_payload["processed_bytes"])
                    self.assertEqual(status_payload["total_bytes"], task_payload["total_bytes"])

                    downloaded = client.get(exported.headers["x-smartx-export-url"], headers=headers)
                    self.assertEqual(downloaded.status_code, 200)
                    self.assertEqual(downloaded.content, exported.content)

                    imported = client.post(
                        "/api/admin/migration/import",
                        data={"mode": "merge", "confirmed": "false"},
                        files={"file": ("migration.tar.gz", exported.content, "application/gzip")},
                        headers=headers,
                    )
                    self.assertEqual(imported.status_code, 200)
                    payload = imported.json()
                    self.assertTrue(payload["ok"])
                    self.assertTrue(Path(payload["backup_path"]).is_file())
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_SECRET_KEY", None)
                os.environ.pop("SMARTX_ADMIN_PASSWORD", None)


if __name__ == "__main__":
    unittest.main()
