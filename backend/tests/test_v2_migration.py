import io
import json
import shutil
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
            # #68 名实相符：全量包 SQLite 携带全量业务数据（sqlite_scope 如实标 full）
            self.assertEqual(manifest["sqlite_scope"], "full")
            self.assertTrue(manifest["contains"]["prometheus"])
            self.assertEqual(manifest["files"]["app/smartx.db"]["sha256"], __import__("hashlib").sha256(archived_db).hexdigest())
            exported_db = Path(tmpdir) / "exported-full-config.db"
            exported_db.write_bytes(archived_db)
            with sqlite3.connect(exported_db) as conn:
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM towers").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0], 1)
                # #68：业务数据随全量包走
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM vm_latest").fetchone()[0], 1)
            self.assertIn("vm_latest", tables)
            self.assertIn("vm_volumes", tables)
            self.assertIn("collection_runs", tables)
            self.assertIn("metric_snapshots", tables)
            # 本机运行状态仍不随包
            self.assertNotIn("users", tables)
            self.assertNotIn("tasks", tables)
            self.assertNotIn("upgrade_runner_state", tables)
            self.assertNotIn("upgrade_task_leases", tables)
            tasks = TaskService(database).list_tasks()
            self.assertEqual(tasks[0]["type"], "migration_export")
            self.assertEqual(tasks[0]["links"][0]["url"], download_url)

    def test_export_archives_create_paired_env_snapshot_with_task_link(self) -> None:
        import stat

        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import TowerInput
        from app.v2.inventory.service import InventoryService
        from app.v2.migration.service import MigrationService
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "project"
            project_dir.mkdir()
            env_content = "SMARTX_SECRET_KEY=migration-secret\n"
            (project_dir / ".env").write_text(env_content, encoding="utf-8")
            settings = V2Settings(data_root=Path(tmpdir), secret_key="migration-secret", project_path_override=project_dir)
            database = V2Database(settings)
            database.initialize()
            InventoryService(database, settings).create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com"))
            tasks = TaskService(database)
            service = MigrationService(database, settings, tasks)

            _, _, bundle_path, _ = service.build_export_archive()
            env_snapshot = bundle_path.with_suffix(".env")
            self.assertTrue(env_snapshot.is_file())
            self.assertEqual(env_snapshot.parent, settings.migrations_dir)
            self.assertEqual(env_snapshot.read_text(encoding="utf-8"), env_content)
            self.assertEqual(stat.S_IMODE(env_snapshot.stat().st_mode), 0o600)
            links = tasks.list_tasks()[0]["links"]
            env_link = next(link for link in links if link["label"].startswith("恢复密钥"))
            self.assertEqual(env_link["filename"], env_snapshot.name)
            self.assertEqual(env_link["url"], f"/api/admin/exports/migrations/{env_snapshot.name}")

            _, _, config_path, _ = service.build_config_export_archive()
            config_env = config_path.with_suffix(".env")
            self.assertTrue(config_env.is_file())
            self.assertEqual(stat.S_IMODE(config_env.stat().st_mode), 0o600)
            config_links = tasks.list_tasks()[0]["links"]
            self.assertTrue(any(link["label"].startswith("恢复密钥") for link in config_links))

            inline = service.start_export_task(run_inline=True)
            self.assertEqual(inline["status"], "succeeded")
            inline_task = tasks.get_task(inline["task_id"])
            self.assertIsNotNone(inline_task)
            inline_links = inline_task["links"] if inline_task else []
            self.assertTrue(any(link["label"].startswith("恢复密钥") for link in inline_links))

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

    def test_data_export_archive_strips_config_and_keeps_monitoring_data(self) -> None:
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
                conn.execute("INSERT INTO vm_volumes (tower_id, cluster_id, vm_id, volume_id, name, used_bytes) VALUES (?, ?, ?, ?, ?, ?)", (tower.id, "cluster-a", "vm-1", "vol-1", "Vol 1", 512))
            block = settings.prometheus_data_dir / "01ABC"
            block.mkdir(parents=True)
            (block / "meta.json").write_text("{}", encoding="utf-8")

            content, filename, path, _ = MigrationService(database, settings, TaskService(database)).build_export_archive(scope="data")

            self.assertTrue(filename.startswith("smartx-data-migration-"))
            self.assertTrue(path.is_file())
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
                names = set(archive.getnames())
                manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))
                archived_db = archive.extractfile("app/smartx.db").read()
            self.assertEqual(manifest["migration_scope"], "data")
            self.assertEqual(manifest["sqlite_scope"], "data")
            self.assertTrue(manifest["contains"]["prometheus"])
            self.assertIn("prometheus/01ABC/meta.json", names)
            exported_db = Path(tmpdir) / "exported-data.db"
            exported_db.write_bytes(archived_db)
            with sqlite3.connect(exported_db) as conn:
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM vm_latest").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM vm_volumes").fetchone()[0], 1)
            # 配置与本机运行状态必须被剥掉
            for stripped in ("towers", "clusters", "users", "tasks", "upgrade_runner_state", "upgrade_task_leases"):
                self.assertNotIn(stripped, tables, f"数据包不应包含 {stripped}")
            # 数据包不需要恢复密钥：任务无恢复密钥链接、服务器无 .env 快照
            task = TaskService(database).list_tasks()[0]
            self.assertEqual(task["title"], "仅导出存储监测数据")
            self.assertFalse(any(link["label"].startswith("恢复密钥") for link in task["links"]))
            self.assertFalse(path.with_suffix(".env").is_file())

    def test_data_import_merge_keeps_towers_and_adds_monitoring_data(self) -> None:
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
            (source_settings.prometheus_data_dir / "01SOURCE").mkdir(parents=True)
            (source_settings.prometheus_data_dir / "01SOURCE" / "meta.json").write_text("{}", encoding="utf-8")
            archive_content, _, _, _ = MigrationService(source_db, source_settings, TaskService(source_db)).build_export_archive(record_task=False, scope="data")

            target_settings = V2Settings(data_root=Path(target_tmp), secret_key="target-secret")
            target_db = V2Database(target_settings)
            target_db.initialize()
            target_inventory = InventoryService(target_db, target_settings)
            target_tower = target_inventory.create_tower(TowerInput(name="Tower B", base_url="https://tower-b.example.com"))
            target_inventory.sync_clusters(target_tower.id, [ClusterInput(cluster_id="cluster-b", name="Cluster B")])
            (target_settings.prometheus_data_dir / "01TARGET").mkdir(parents=True)
            (target_settings.prometheus_data_dir / "01TARGET" / "meta.json").write_text("{}", encoding="utf-8")

            result = MigrationService(target_db, target_settings, TaskService(target_db)).restore_archive_bytes(archive_content, filename="data.tar.gz", mode="merge")

            self.assertTrue(result["ok"])
            self.assertEqual(result["summary"]["scope"], "data")
            # #63 新语义：目标机没有配置源集群（cluster-a）→ 数据行无法归属 → 跳过。
            # 旧行为是照搬源 tower_id 硬插（造孤儿行），正是 .3 三代冗余的成因——
            # 旧测试曾编码该错误行为，随 #63 修正。
            self.assertEqual(result["summary"]["sqlite"]["tables"]["vm_latest"], 0)
            self.assertEqual(result["summary"]["sqlite"]["skipped"], 1)
            self.assertIn("prometheus", result["restored"])
            with target_db.connection() as conn:
                # 本机 Tower 配置原样保留，源机的 Tower/集群不并入，也不产生孤儿数据行
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM towers").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT name FROM clusters").fetchone()[0], "Cluster B")
                self.assertEqual(conn.execute("SELECT name FROM towers").fetchone()[0], "Tower B")
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM vm_latest").fetchone()[0], 0)
            self.assertTrue((target_settings.prometheus_data_dir / "01TARGET" / "meta.json").is_file())
            self.assertTrue((target_settings.prometheus_data_dir / "01SOURCE" / "meta.json").is_file())


    def test_full_package_merge_restores_monitoring_data(self) -> None:
        """#68 T2：迁移包+恢复密钥=完整恢复——业务数据真随全量包走。"""
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService
        from app.v2.migration.service import MigrationService
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as source_tmp, tempfile.TemporaryDirectory() as target_tmp:
            source_settings = V2Settings(data_root=Path(source_tmp), secret_key="s")
            source_db = V2Database(source_settings)
            source_db.initialize()
            source_inventory = InventoryService(source_db, source_settings)
            source_tower = source_inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com"))
            source_inventory.sync_clusters(source_tower.id, [ClusterInput(cluster_id="cm551", name="Cluster A")])
            with source_db.connection() as conn:
                conn.execute("INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (?, 'cm551', 'vm-1', 'VM 1', 1)", (source_tower.id,))
            archive_content, _, _, _ = MigrationService(source_db, source_settings, TaskService(source_db)).build_export_archive(record_task=False)

            target_settings = V2Settings(data_root=Path(target_tmp), secret_key="t")
            target_db = V2Database(target_settings)
            target_db.initialize()
            result = MigrationService(target_db, target_settings, TaskService(target_db)).restore_archive_bytes(archive_content, filename="full.tar.gz", mode="merge")

            self.assertTrue(result["ok"])
            with target_db.connection() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM vm_latest").fetchone()[0], 1, "监测数据随全量包恢复")
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM towers").fetchone()[0], 1)

    def test_data_import_overwrite_is_rejected_and_changes_nothing(self) -> None:
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
            with source_db.connection() as conn:
                conn.execute("INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (1, 'c', 'vm-1', 'VM 1', 1024)")
            archive_content, _, _, _ = MigrationService(source_db, source_settings, TaskService(source_db)).build_export_archive(record_task=False, scope="data")

            target_settings = V2Settings(data_root=Path(target_tmp), secret_key="target-secret")
            target_db = V2Database(target_settings)
            target_db.initialize()
            target_inventory = InventoryService(target_db, target_settings)
            target_tower = target_inventory.create_tower(TowerInput(name="Tower B", base_url="https://tower-b.example.com"))

            from fastapi import HTTPException

            # confirmed=True 绕过通用确认闸，确保 400 打到数据包专属拒绝（否则测不到目标分支）
            with self.assertRaises(HTTPException) as ctx:
                MigrationService(target_db, target_settings, TaskService(target_db)).restore_archive_bytes(archive_content, filename="data.tar.gz", mode="overwrite", confirmed=True)
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("整库替换", ctx.exception.detail)
            with target_db.connection() as conn:
                self.assertEqual(conn.execute("SELECT name FROM towers").fetchone()[0], "Tower B")
                self.assertEqual(conn.execute("SELECT id FROM towers").fetchone()[0], target_tower.id)


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed.")
class V2MigrationApiTest(unittest.TestCase):
    def test_migration_api_requires_auth_exports_downloads_and_imports_with_backup(self) -> None:
        import os

        from app.v2.main import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_SECRET_KEY"] = "migration-api-secret"
            os.environ["SMARTX_ADMIN_PASSWORD"] = "password"
            project_dir = Path(tmpdir) / "project"
            project_dir.mkdir()
            os.environ["SMARTX_PROJECT_PATH"] = str(project_dir)
            env_content = "SMARTX_SECRET_KEY=migration-api-secret\n"
            (project_dir / ".env").write_text(env_content, encoding="utf-8")
            try:
                app = create_app()
                with TestClient(app) as client:
                    self.assertEqual(client.get("/api/admin/migration/export").status_code, 401)
                    self.assertEqual(client.post("/api/admin/migration/data/export/start").status_code, 401)
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

                    data_start = client.post("/api/admin/migration/data/export/start", headers=headers)
                    self.assertEqual(data_start.status_code, 200)
                    data_payload = data_start.json()
                    self.assertEqual(data_payload["status"], "running")
                    data_status_payload: dict = {}
                    for _ in range(30):
                        data_status = client.get(f"/api/admin/migration/export/status/{data_payload['task_id']}", headers=headers)
                        self.assertEqual(data_status.status_code, 200)
                        data_status_payload = data_status.json()
                        if data_status_payload["status"] == "succeeded":
                            break
                        time.sleep(0.1)
                    self.assertEqual(data_status_payload["status"], "succeeded")
                    self.assertFalse(any("恢复密钥" in (link.get("label") or "") for link in data_status_payload.get("links") or []))
                    data_download = client.get(data_status_payload["download_url"], headers=headers)
                    self.assertEqual(data_download.status_code, 200)
                    with tarfile.open(fileobj=io.BytesIO(data_download.content), mode="r:gz") as archive:
                        data_manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))
                    self.assertEqual(data_manifest["migration_scope"], "data")
                    self.assertEqual(data_manifest["sqlite_scope"], "data")

                    data_overwrite = client.post(
                        "/api/admin/migration/import",
                        data={"mode": "overwrite", "confirmed": "true"},
                        files={"file": ("data.tar.gz", data_download.content, "application/gzip")},
                        headers=headers,
                    )
                    self.assertEqual(data_overwrite.status_code, 400)
                    self.assertIn("合并数据", data_overwrite.json()["detail"])

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

                    self.assertEqual(client.get("/api/admin/migration/env-file").status_code, 405)
                    self.assertEqual(client.post("/api/admin/migration/env-file", headers=headers, json={}).status_code, 403)
                    self.assertEqual(
                        client.post("/api/admin/migration/env-file", headers=headers, json={"password": "wrong-password"}).status_code,
                        403,
                    )
                    env_download = client.post("/api/admin/migration/env-file", headers=headers, json={"password": "password"})
                    self.assertEqual(env_download.status_code, 200)
                    self.assertEqual(env_download.text, env_content)
                    (project_dir / ".env").unlink()
                    self.assertEqual(
                        client.post("/api/admin/migration/env-file", headers=headers, json={"password": "password"}).status_code,
                        404,
                    )
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_SECRET_KEY", None)
                os.environ.pop("SMARTX_ADMIN_PASSWORD", None)
                os.environ.pop("SMARTX_PROJECT_PATH", None)


if __name__ == "__main__":
    unittest.main()

    def test_merge_remaps_source_tower_generations_onto_current_tower(self) -> None:
        """#63 T2/T5：源包数据行带多代 tower_id（含源库孤儿 ID）→ 全部归一到目标现役 Tower。

        复刻 .3 实况：同一 (Tower, 集群) 的数据在源库里挂了三代 tower_id，
        目标机现役 Tower 是另一代。修复前照搬会造出孤儿行；修复后按 cluster 归属归一。
        """
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService
        from app.v2.migration.service import MigrationService
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as source_tmp, tempfile.TemporaryDirectory() as target_tmp:
            source_settings = V2Settings(data_root=Path(source_tmp), secret_key="s")
            source_db = V2Database(source_settings)
            source_db.initialize()
            source_inventory = InventoryService(source_db, source_settings)
            source_tower = source_inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com"))
            source_inventory.sync_clusters(source_tower.id, [ClusterInput(cluster_id="cm551", name="Cluster A")])
            with source_db.connection() as conn:
                # 源库换代残留：tower_id 2 / 9 在源 towers 表里不存在（孤儿代）
                conn.execute("INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (1, 'cm551', 'vm-1', 'VM 1', 1)")
                conn.execute("INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (2, 'cm551', 'vm-1', 'VM 1', 1)")
                conn.execute("INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (9, 'cm551', 'vm-2', 'VM 2', 2)")
                conn.execute("INSERT INTO vm_volumes (tower_id, cluster_id, vm_id, volume_id, used_bytes) VALUES (2, 'cm551', 'vm-1', 'vol-1', 5)")
            # 全量导出包的 SQLite 只含配置表（#68 范畴），数据行重映射直接对 _merge_sqlite 单元验证
            source_db_path = Path(source_tmp) / "manual-source.db"
            shutil.copy2(source_settings.sqlite_path, source_db_path)

            target_settings = V2Settings(data_root=Path(target_tmp), secret_key="t")
            target_db = V2Database(target_settings)
            target_db.initialize()
            target_inventory = InventoryService(target_db, target_settings)
            # 目标机 Tower 换过两代：现役「Tower A」不是 id=1
            target_inventory.create_tower(TowerInput(name="Old Tower", base_url="https://old.example.com"))
            target_tower = target_inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com"))

            summary = MigrationService(target_db, target_settings, TaskService(target_db))._merge_sqlite(source_db_path)

            self.assertEqual(summary["tables"]["towers"], 2, "Old Tower + 身份匹配的 Tower A（不新增）")
            self.assertEqual(summary["skipped"], 0, "三行都能按 cluster 归属解析")
            with target_db.connection() as conn:
                # 三代全部归一到目标现役 Tower（身份匹配，不新增重复 Tower）
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM towers").fetchone()[0], 2)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM vm_latest").fetchone()[0], 2)
                self.assertEqual(conn.execute("SELECT DISTINCT tower_id FROM vm_latest").fetchall()[0][0], target_tower.id)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM vm_volumes").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT DISTINCT tower_id FROM vm_volumes").fetchall()[0][0], target_tower.id)
                self.assertEqual(conn.execute("SELECT tower_id FROM clusters WHERE cluster_id='cm551'").fetchone()[0], target_tower.id)

    def test_merge_resolves_cross_system_tower_id_collision(self) -> None:
        """#63 T3/T4：源库 tower id=1 与目标库 id=1 是不同 Tower → 源 Tower 以新 ID 插入，集群挂对。"""
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService
        from app.v2.migration.service import MigrationService
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as source_tmp, tempfile.TemporaryDirectory() as target_tmp:
            source_settings = V2Settings(data_root=Path(source_tmp), secret_key="s")
            source_db = V2Database(source_settings)
            source_db.initialize()
            source_inventory = InventoryService(source_db, source_settings)
            # 源库第一个 Tower（id=1）叫 TowerX
            source_tower = source_inventory.create_tower(TowerInput(name="TowerX", base_url="https://towerx.example.com"))
            source_inventory.sync_clusters(source_tower.id, [ClusterInput(cluster_id="cmX", name="Cluster X")])

            target_settings = V2Settings(data_root=Path(target_tmp), secret_key="t")
            target_db = V2Database(target_settings)
            target_db.initialize()
            target_inventory = InventoryService(target_db, target_settings)
            # 目标库 id=1 是另一个 Tower
            target_inventory.create_tower(TowerInput(name="TowerY", base_url="https://towery.example.com"))
            archive_content, _, _, _ = MigrationService(source_db, source_settings, TaskService(source_db)).build_export_archive(record_task=False)

            result = MigrationService(target_db, target_settings, TaskService(target_db)).restore_archive_bytes(archive_content, filename="m.tar.gz", mode="merge")

            self.assertTrue(result["ok"])
            self.assertEqual(result["summary"]["sqlite"]["tables"]["towers"], 2)
            with target_db.connection() as conn:
                rows = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT id, name, base_url FROM towers")}
                self.assertEqual(rows[1], ("TowerY", "https://towery.example.com"), "目标现役 Tower 不被源库同 ID 记录污染")
                towerx_ids = [tid for tid, (name, _) in rows.items() if name == "TowerX"]
                self.assertEqual(len(towerx_ids), 1, "源 TowerX 以新 ID 插入")
                # 集群挂在 TowerX 名下，而不是被同 ID 的 TowerY 吞掉
                self.assertEqual(conn.execute("SELECT tower_id FROM clusters WHERE cluster_id='cmX'").fetchone()[0], towerx_ids[0])

    def test_data_package_import_remaps_to_target_tower(self) -> None:
        """#63 T6：数据包（DATA_SCOPE）导入同样经 cluster 归属重映射；无法归属的行跳过。"""
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService
        from app.v2.migration.service import MigrationService
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as source_tmp, tempfile.TemporaryDirectory() as target_tmp:
            source_settings = V2Settings(data_root=Path(source_tmp), secret_key="s")
            source_db = V2Database(source_settings)
            source_db.initialize()
            source_inventory = InventoryService(source_db, source_settings)
            source_tower = source_inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com"))
            source_inventory.sync_clusters(source_tower.id, [ClusterInput(cluster_id="cm551", name="Cluster A")])
            with source_db.connection() as conn:
                conn.execute("INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (7, 'cm551', 'vm-1', 'VM 1', 1)")
                # 源库孤儿集群（clusters 表里没有 cmUnknown）——导入应跳过而不是造孤儿
                conn.execute("INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (7, 'cmUnknown', 'vm-2', 'VM 2', 2)")
            archive_content, _, _, _ = MigrationService(source_db, source_settings, TaskService(source_db)).build_export_archive(record_task=False, scope="data")

            target_settings = V2Settings(data_root=Path(target_tmp), secret_key="t")
            target_db = V2Database(target_settings)
            target_db.initialize()
            target_inventory = InventoryService(target_db, target_settings)
            target_tower = target_inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com"))
            target_inventory.sync_clusters(target_tower.id, [ClusterInput(cluster_id="cm551", name="Cluster A")])

            result = MigrationService(target_db, target_settings, TaskService(target_db)).restore_archive_bytes(archive_content, filename="d.tar.gz", mode="merge")

            self.assertTrue(result["ok"])
            self.assertEqual(result["summary"]["sqlite"]["tables"]["vm_latest"], 1)
            self.assertEqual(result["summary"]["sqlite"]["skipped"], 1, "无法归属的源行应跳过")
            with target_db.connection() as conn:
                self.assertEqual(conn.execute("SELECT tower_id FROM vm_latest WHERE vm_id='vm-1'").fetchone()[0], target_tower.id)
                self.assertIsNone(conn.execute("SELECT 1 FROM vm_latest WHERE vm_id='vm-2'").fetchone(), "孤儿集群的行不得入库")
