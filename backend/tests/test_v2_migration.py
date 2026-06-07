import io
import json
import sqlite3
import tarfile
import tempfile
import time
import unittest
from pathlib import Path


try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local host may not have web deps.
    TestClient = None


class V2MigrationServiceTest(unittest.TestCase):
    def test_config_export_archive_contains_only_towers_and_clusters(self) -> None:
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
            with database.connection() as conn:
                conn.execute("INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (?, ?, ?, ?, ?)", (tower.id, "cluster-a", "vm-1", "VM 1", 1024))
            block = settings.prometheus_data_dir / "01ABC"
            block.mkdir(parents=True)
            (block / "meta.json").write_text("{}", encoding="utf-8")

            content, filename, path, download_url = MigrationService(database, settings, TaskService(database)).build_config_export_archive()

            self.assertTrue(filename.startswith("smartx-config-migration-"))
            self.assertTrue(path.is_file())
            self.assertTrue(download_url.startswith("/api/admin/exports/migrations/"))
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
                names = set(archive.getnames())
                manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))
                archived_db = archive.extractfile("app/smartx.db").read()
            self.assertEqual(manifest["migration_scope"], "config")
            self.assertTrue(manifest["contains"]["sqlite"])
            self.assertFalse(manifest["contains"]["prometheus"])
            self.assertIn("app/smartx.db", names)
            self.assertNotIn("prometheus/01ABC/meta.json", names)

            exported_db = Path(tmpdir) / "exported-config.db"
            exported_db.write_bytes(archived_db)
            with sqlite3.connect(exported_db) as conn:
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
                tower_count = conn.execute("SELECT COUNT(*) FROM towers").fetchone()[0]
                cluster_count = conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
            self.assertEqual(tower_count, 1)
            self.assertEqual(cluster_count, 1)
            self.assertNotIn("vm_latest", tables)

    def test_config_import_merges_only_towers_and_clusters(self) -> None:
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
            source_inventory.sync_clusters(source_tower.id, [ClusterInput(cluster_id="cluster-a", name="Cluster A")])
            with source_db.connection() as conn:
                conn.execute("INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (?, ?, ?, ?, ?)", (source_tower.id, "cluster-a", "vm-1", "VM 1", 1024))
            block = source_settings.prometheus_data_dir / "01SOURCE"
            block.mkdir(parents=True)
            (block / "meta.json").write_text("{}", encoding="utf-8")
            archive_content, _, _, _ = MigrationService(source_db, source_settings, TaskService(source_db)).build_config_export_archive(record_task=False)

            target_settings = V2Settings(data_root=Path(target_tmp), secret_key="target-secret")
            target_db = V2Database(target_settings)
            target_db.initialize()
            target_block = target_settings.prometheus_data_dir / "01TARGET"
            target_block.mkdir(parents=True)
            (target_block / "meta.json").write_text("{}", encoding="utf-8")

            result = MigrationService(target_db, target_settings, TaskService(target_db)).restore_archive_bytes(archive_content, filename="config.tar.gz", mode="merge")

            self.assertTrue(result["ok"])
            self.assertEqual(result["summary"]["scope"], "config")
            self.assertEqual(result["summary"]["sqlite"]["tables"], {"towers": 1, "clusters": 1})
            self.assertNotIn("prometheus", result["restored"])
            self.assertTrue(Path(result["backup_path"]).is_file())
            self.assertTrue((target_settings.prometheus_data_dir / "01TARGET" / "meta.json").is_file())
            self.assertFalse((target_settings.prometheus_data_dir / "01SOURCE" / "meta.json").exists())
            with target_db.connection() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM towers").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM vm_latest").fetchone()[0], 0)

    def test_export_archive_includes_config_sqlite_and_prometheus_history_and_saves_task(self) -> None:
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
            with database.connection() as conn:
                conn.execute("INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (?, ?, ?, ?, ?)", (tower.id, "cluster-a", "vm-1", "VM 1", 1024))
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
            self.assertEqual(manifest["migration_scope"], "full")
            self.assertEqual(manifest["sqlite_scope"], "config")
            self.assertTrue(manifest["contains"]["prometheus"])
            self.assertEqual(manifest["files"]["app/smartx.db"]["sha256"], __import__("hashlib").sha256(archived_db).hexdigest())
            exported_db = Path(tmpdir) / "exported-full-config.db"
            exported_db.write_bytes(archived_db)
            with sqlite3.connect(exported_db) as conn:
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM towers").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0], 1)
            self.assertNotIn("vm_latest", tables)
            self.assertNotIn("vm_volumes", tables)
            self.assertNotIn("collection_runs", tables)
            self.assertNotIn("metric_snapshots", tables)
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

    def test_import_v1_archive_extracts_latest_vm_volume_payload_into_v2_volumes(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.migration.service import MigrationService
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_db = root / "v1-smartx.db"
            with sqlite3.connect(source_db) as conn:
                conn.executescript(
                    """
                    CREATE TABLE towers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, base_url TEXT NOT NULL, username TEXT, password_encrypted TEXT, api_token_encrypted TEXT, verify_tls INTEGER NOT NULL DEFAULT 1, enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT, updated_at TEXT);
                    CREATE TABLE clusters (id INTEGER PRIMARY KEY, tower_id INTEGER NOT NULL, cluster_id TEXT NOT NULL, name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, updated_at TEXT);
                    CREATE TABLE latest_vm_volumes (tower_id INTEGER NOT NULL, cluster_id TEXT NOT NULL, vm_id TEXT NOT NULL, payload_json TEXT NOT NULL, collected_at TEXT);
                    """
                )
                conn.execute("INSERT INTO towers (id, name, base_url) VALUES (1, 'Tower A', 'https://tower.example.com')")
                conn.execute("INSERT INTO clusters (tower_id, cluster_id, name) VALUES (1, 'cluster-a', 'Cluster A')")
                payload = [
                    {
                        "id": "vol-1",
                        "name": "System",
                        "path": "/vm/system",
                        "size": 1000,
                        "used_size": 450,
                        "elf_storage_policy": "Replica-2",
                        "elf_storage_policy_replica_num": 2,
                        "elf_storage_policy_thin_provision": True,
                        "cluster": {"raw": "discard"},
                        "vm_disks": [{"raw": "discard"}],
                    }
                ]
                conn.execute(
                    "INSERT INTO latest_vm_volumes (tower_id, cluster_id, vm_id, payload_json, collected_at) VALUES (1, 'cluster-a', 'vm-1', ?, '2026-06-01T00:00:00Z')",
                    (json.dumps(payload),),
                )

            archive_buffer = io.BytesIO()
            with tarfile.open(fileobj=archive_buffer, mode="w:gz") as archive:
                manifest_bytes = json.dumps({"format": "smartx-storage-forecast-migration", "version": 2}).encode("utf-8")
                manifest_info = tarfile.TarInfo("manifest.json")
                manifest_info.size = len(manifest_bytes)
                archive.addfile(manifest_info, io.BytesIO(manifest_bytes))
                archive.add(source_db, arcname="smartx-data/smartx.db", recursive=False)

            settings = V2Settings(data_root=root / "target", secret_key="target-secret")
            database = V2Database(settings)
            database.initialize()
            result = MigrationService(database, settings, TaskService(database)).restore_archive_bytes(archive_buffer.getvalue(), filename="v1-migration.tar.gz", mode="merge")

            self.assertIn("smartx_db", result["restored"])
            with database.connection() as conn:
                volume = conn.execute(
                    "SELECT volume_id, name, path, size_bytes, used_bytes, storage_policy, replica_num, thin_provision FROM vm_volumes WHERE tower_id = 1 AND cluster_id = 'cluster-a' AND vm_id = 'vm-1'"
                ).fetchone()
            self.assertEqual(tuple(volume), ("vol-1", "System", "/vm/system", 1000, 450, "Replica-2", 2, 1))

    def test_start_import_task_reports_backup_merge_prometheus_and_health_progress(self) -> None:
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
            block = source_settings.prometheus_data_dir / "01SOURCE"
            block.mkdir(parents=True)
            (block / "meta.json").write_text("{}", encoding="utf-8")
            archive_content, _, _, _ = MigrationService(source_db, source_settings, TaskService(source_db)).build_export_archive(record_task=False)

            target_settings = V2Settings(data_root=Path(target_tmp), secret_key="target-secret")
            target_db = V2Database(target_settings)
            target_db.initialize()
            service = MigrationService(target_db, target_settings, TaskService(target_db))

            result = service.start_import_task(archive_content, filename="migration.tar.gz", mode="merge", confirmed=False)
            status = service.import_task_status(result["task_id"])

            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(status["progress"], 100)
            self.assertTrue(Path(status["backup_path"]).is_file())
            self.assertTrue(Path(status["saved_path"]).is_file())
            self.assertEqual(status["summary"]["sqlite"]["inserted"], 2)
            self.assertEqual(status["summary"]["sqlite"]["tables"]["towers"], 1)
            self.assertEqual(status["summary"]["sqlite"]["tables"]["clusters"], 1)
            self.assertEqual(status["summary"]["prometheus"]["copied"], 1)
            self.assertEqual(status["summary"]["health"]["complete"], True)
            self.assertTrue(any(step["key"] == "backup" and step["status"] == "succeeded" for step in status["steps"]))
            self.assertTrue(any("Prometheus" in line for line in status["logs"]))

    def test_start_export_task_can_return_before_archive_finishes(self) -> None:
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
            block = settings.prometheus_data_dir / "01SOURCE"
            block.mkdir(parents=True)
            (block / "meta.json").write_text("{}", encoding="utf-8")
            service = MigrationService(database, settings, TaskService(database))

            result = service.start_export_task(run_inline=False)

            self.assertEqual(result["status"], "running")
            self.assertLess(result["progress"], 100)
            self.assertFalse(result.get("download_url"))
            task_id = result["task_id"]
            for _ in range(30):
                status = service.export_task_status(task_id)
                if status["status"] == "succeeded":
                    break
                time.sleep(0.1)
            self.assertEqual(status["status"], "succeeded")
            self.assertEqual(status["progress"], 100)
            self.assertTrue(status["download_url"])
            self.assertTrue(Path(status["saved_path"]).is_file())


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
                    self.assertEqual(task_payload["status"], "running")
                    self.assertLess(task_payload["progress"], 100)
                    self.assertIn("steps", task_payload)
                    self.assertIn("total_bytes", task_payload)
                    self.assertIn("processed_bytes", task_payload)

                    for _ in range(30):
                        task_status = client.get(f"/api/admin/migration/export/status/{task_payload['task_id']}", headers=headers)
                        self.assertEqual(task_status.status_code, 200)
                        status_payload = task_status.json()
                        if status_payload["status"] == "succeeded":
                            break
                        time.sleep(0.1)
                    self.assertEqual(status_payload["task_id"], task_payload["task_id"])
                    self.assertEqual(status_payload["status"], "succeeded")
                    self.assertTrue(status_payload["logs"])
                    self.assertTrue(status_payload["download_url"])
                    self.assertTrue(Path(status_payload["saved_path"]).is_file())
                    self.assertGreaterEqual(status_payload["processed_bytes"], task_payload["processed_bytes"])
                    self.assertGreaterEqual(status_payload["total_bytes"], task_payload["total_bytes"])

                    downloaded = client.get(exported.headers["x-smartx-export-url"], headers=headers)
                    self.assertEqual(downloaded.status_code, 200)
                    self.assertEqual(downloaded.content, exported.content)

                    config_export = client.get("/api/admin/migration/config/export", headers=headers)
                    self.assertEqual(config_export.status_code, 200)
                    self.assertEqual(config_export.headers["content-type"], "application/gzip")
                    with tarfile.open(fileobj=io.BytesIO(config_export.content), mode="r:gz") as archive:
                        config_manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))
                        config_names = set(archive.getnames())
                    self.assertEqual(config_manifest["migration_scope"], "config")
                    self.assertIn("app/smartx.db", config_names)
                    self.assertFalse(any(name.startswith("prometheus/") for name in config_names))

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

                    import_task = client.post(
                        "/api/admin/migration/import/start",
                        data={"mode": "merge", "confirmed": "false"},
                        files={"file": ("migration.tar.gz", exported.content, "application/gzip")},
                        headers=headers,
                    )
                    self.assertEqual(import_task.status_code, 200)
                    import_payload = import_task.json()
                    self.assertIn(import_payload["status"], {"running", "succeeded"})
                    self.assertIn("steps", import_payload)
                    for _ in range(20):
                        import_status = client.get(f"/api/admin/migration/import/status/{import_payload['task_id']}", headers=headers)
                        self.assertEqual(import_status.status_code, 200)
                        status_json = import_status.json()
                        if status_json["status"] == "succeeded":
                            break
                        __import__("time").sleep(0.1)
                    self.assertEqual(status_json["task_id"], import_payload["task_id"])
                    self.assertEqual(status_json["status"], "succeeded")
                    self.assertIn("backup_path", status_json)
                    self.assertIn("summary", status_json)

                    overwrite_without_confirm = client.post(
                        "/api/admin/migration/import",
                        data={"mode": "overwrite", "confirmed": "false"},
                        files={"file": ("migration.tar.gz", exported.content, "application/gzip")},
                        headers=headers,
                    )
                    self.assertEqual(overwrite_without_confirm.status_code, 400)
                    self.assertIn("覆盖导入会清空当前系统数据", overwrite_without_confirm.json()["detail"])
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_SECRET_KEY", None)
                os.environ.pop("SMARTX_ADMIN_PASSWORD", None)


if __name__ == "__main__":
    unittest.main()
