import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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

            # 语义更新（2026-10-04）：keep_recent 下限强制为 1，upgrades/ 下唯一那个
            # `pkg.tar.gz` 被保留（回滚需旧镜像，用户口径），其余 3 个目录条目各删 1。
            self.assertEqual(result["kept_count"], 1)
            self.assertEqual(result["deleted_count"], 3)
            self.assertTrue((settings.upgrades_dir / "pkg.tar.gz").exists())
            self.assertEqual(result["space_reclaimed"], scan["total_size"])
            self.assertTrue((settings.backups_dir / "keep.tar.gz").is_file())
            self.assertFalse((settings.reports_dir / "report.xlsx").exists())
            task = TaskService(database).list_tasks()[0]
            self.assertEqual(task["type"], "cleanup")
            self.assertEqual(task["status"], "success")
            self.assertGreater(task["progress"], 0)

    def test_cleanup_keep_recent_upgrades_preserves_newest_task_dirs(self) -> None:
        import os

        from app.v2.cleanup.service import CleanupService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="cleanup-secret")
            database = V2Database(settings)
            database.initialize()
            dirs = []
            for index, age in enumerate((300, 200, 100)):
                task_dir = settings.upgrades_dir / f"upgrade-task-{index}"
                task_dir.mkdir(parents=True)
                (task_dir / "package.tar.gz").write_bytes(b"x" * 10)
                stamp = (datetime.now().timestamp()) - age
                os.utime(task_dir, (stamp, stamp))
                dirs.append(task_dir)
            (settings.reports_dir / "report.xlsx").write_bytes(b"report")

            cleanup = CleanupService(settings, TaskService(database))
            result = cleanup.cleanup_artifacts(keep_recent_upgrades=2)

            # 语义更新（2026-10-04）：3 个任务目录 + 1 个报表，共 4 个条目；
            # keep_recent=2 保留 upgrades 下最近 2 个目录，故删 1 个目录 + 1 个报表 = 2。
            self.assertEqual(result["deleted_count"], 2)
            self.assertEqual(result["kept_count"], 2)
            # 语义更新（2026-10-04）：被清理的任务目录**本身保留**（记录优先），
            # 只有其中的体积产物 package.tar.gz 被删。
            self.assertTrue(dirs[0].exists(), "任务目录本身应保留")
            self.assertFalse(
                (dirs[0] / "package.tar.gz").exists(), "最旧任务的包应被删"
            )
            self.assertTrue(dirs[1].exists())
            self.assertTrue((dirs[1] / "package.tar.gz").exists(), "保留的目录其包不应删")
            self.assertTrue(dirs[2].exists())
            self.assertTrue((dirs[2] / "package.tar.gz").exists())
            self.assertFalse((settings.reports_dir / "report.xlsx").exists())

    def test_cleanup_artifacts_refuses_while_upgrade_task_active(self) -> None:
        from app.v2.cleanup.service import CleanupService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.models import TaskStatus, TaskType
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="cleanup-secret")
            database = V2Database(settings)
            database.initialize()
            tasks = TaskService(database)
            tasks.create_task("upgrade-live", TaskType.UPGRADE, "平台升级", status=TaskStatus.RUNNING, progress=10)
            package = settings.upgrades_dir / "pkg.tar.gz"
            package.write_bytes(b"upgrade")

            cleanup = CleanupService(settings, tasks)
            result = cleanup.cleanup_artifacts()

            self.assertFalse(result["ok"])
            self.assertEqual(result["deleted_count"], 0)
            self.assertTrue(package.exists())
            self.assertIn("upgrade-live", result["message"])

    def test_image_cleanup_classifies_unused_protected_and_in_use_images(self) -> None:
        from app.v2.cleanup.service import CleanupService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService

        class FakeExecutor:
            def __init__(self) -> None:
                self.rm_calls: list[str] = []

            def output(self, command: list[str]) -> str:
                if command[:3] == ["docker", "image", "ls"]:
                    if "--filter" in command:
                        return '[{"ID":"aaa111","Repository":"<none>","Tag":"<none>","CreatedAt":"2026-01-01"}]'
                    return (
                        '[{"ID":"aaa111","Repository":"<none>","Tag":"<none>","CreatedAt":"2026-01-01"},'
                        '{"ID":"bbb222","Repository":"nazawsze/smartx-storage-forecast-web-api","Tag":"v0.4.0","CreatedAt":"2026-01-02"},'
                        '{"ID":"ccc333","Repository":"nazawsze/smartx-hci-capacity-insight-web-api","Tag":"v0.5.2","CreatedAt":"2026-01-03"},'
                        '{"ID":"ddd444","Repository":"thirdparty/tool","Tag":"1.0","CreatedAt":"2026-01-04"}]'
                    )
                if command[:3] == ["docker", "ps", "-a"]:
                    return '[{"Image":"nazawsze/smartx-hci-capacity-insight-web-api:v0.5.3"},{"Image":"thirdparty/tool:1.0"}]'
                if command[:3] == ["docker", "image", "inspect"]:
                    image_id = command[3]
                    payloads = {
                        "aaa111": {"Id": "aaa111", "Size": 1048576, "RepoTags": None},
                        "bbb222": {"Id": "bbb222", "Size": 2097152, "RepoTags": ["nazawsze/smartx-storage-forecast-web-api:v0.4.0"]},
                        "ccc333": {"Id": "ccc333", "Size": 4194304, "RepoTags": ["nazawsze/smartx-hci-capacity-insight-web-api:v0.5.2"]},
                        "ddd444": {"Id": "ddd444", "Size": 8388608, "RepoTags": ["thirdparty/tool:1.0"]},
                    }
                    return f"[{json.dumps(payloads.get(image_id, {}))}]"
                if command[:3] == ["docker", "image", "rm"]:
                    self.rm_calls.append(command[3])
                    return f"Untagged: {command[3]}\n"
                return ""

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="cleanup-secret")
            database = V2Database(settings)
            database.initialize()
            executor = FakeExecutor()
            cleanup = CleanupService(settings, TaskService(database), executor=executor)

            scan = cleanup.scan_unused_images()
            self.assertEqual({image["id"] for image in scan["images"]}, {"aaa111", "bbb222"})
            categories = {image["id"]: image["category"] for image in scan["images"]}
            self.assertEqual(categories["aaa111"], "dangling")
            self.assertEqual(categories["bbb222"], "unused")
            self.assertEqual([image["id"] for image in scan["protected_images"]], ["ccc333"])
            self.assertEqual(scan["protected_count"], 1)
            self.assertEqual(scan["space_reclaimable"], 1048576 + 2097152)
            self.assertIn("回滚保护", scan["message"])

            result = cleanup.cleanup_unused_images(image_ids=["bbb222", "ccc333", "missing999"])
            self.assertEqual(result["deleted_count"], 1)
            self.assertEqual(executor.rm_calls, ["bbb222"])
            self.assertEqual(result["space_reclaimed"], 2097152)
            self.assertEqual(result["errors"], [])
            self.assertTrue(any("ccc333" in log for log in result["logs"]))

    def test_image_cleanup_without_ids_removes_all_candidates(self) -> None:
        from app.v2.cleanup.service import CleanupService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService

        class FakeExecutor:
            def __init__(self) -> None:
                self.rm_calls: list[str] = []

            def output(self, command: list[str]) -> str:
                if command[:3] == ["docker", "image", "ls"]:
                    if "--filter" in command:
                        return '[{"ID":"aaa111","Repository":"<none>","Tag":"<none>","CreatedAt":"2026-01-01"}]'
                    return '[{"ID":"aaa111","Repository":"<none>","Tag":"<none>","CreatedAt":"2026-01-01"}]'
                if command[:3] == ["docker", "image", "inspect"]:
                    return '[{"Id":"aaa111","Size":1048576,"RepoTags":null}]'
                if command[:3] == ["docker", "image", "rm"]:
                    self.rm_calls.append(command[3])
                    return "Untagged: aaa111\n"
                return ""

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="cleanup-secret")
            database = V2Database(settings)
            database.initialize()
            executor = FakeExecutor()
            cleanup = CleanupService(settings, TaskService(database), executor=executor)

            result = cleanup.cleanup_unused_images()
            self.assertEqual(result["deleted_count"], 1)
            self.assertEqual(executor.rm_calls, ["aaa111"])

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

    def test_local_storage_usage_uses_data_root_filesystem(self) -> None:
        from app.v2.cleanup.service import CleanupService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="cleanup-secret")
            database = V2Database(settings)
            database.initialize()
            cleanup = CleanupService(settings, TaskService(database))

            usage = cleanup.local_storage_usage()

            self.assertEqual(usage["path"], str(settings.data_root))
            self.assertGreater(usage["total_bytes"], 0)
            self.assertGreaterEqual(usage["free_ratio"], 0)
            self.assertLessEqual(usage["used_ratio"], 1)

    def test_sqlite_vacuum_scan_and_cleanup_creates_backup_before_vacuum(self) -> None:
        from app.v2.cleanup.service import CleanupService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="cleanup-secret")
            database = V2Database(settings)
            database.initialize()
            with database.connection() as conn:
                conn.execute("CREATE TABLE bloat (value TEXT)")
                conn.executemany("INSERT INTO bloat (value) VALUES (?)", [("x" * 1024,) for _ in range(200)])
                conn.execute("DELETE FROM bloat")

            cleanup = CleanupService(settings, TaskService(database))
            scan = cleanup.scan_sqlite_vacuum()
            self.assertTrue(scan["ok"])
            self.assertEqual(scan["path"], str(settings.sqlite_path))
            self.assertGreater(scan["size"], 0)
            self.assertIn("estimated_reclaimable", scan)

            result = cleanup.vacuum_sqlite()
            self.assertTrue(result["ok"])
            self.assertTrue(Path(result["backup_path"]).is_file())
            self.assertGreater(result["before_size"], 0)
            self.assertGreater(result["after_size"], 0)
            task = TaskService(database).list_tasks()[0]
            self.assertEqual(task["type"], "cleanup")
            self.assertIn("SQLite", task["title"])

    def test_sqlite_cleanup_applies_runtime_cache_retention_before_vacuum(self) -> None:
        from app.v2.cleanup.service import CleanupService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.models import TaskStatus, TaskType
        from app.v2.tasks.service import TaskService

        def iso(days_ago: int) -> str:
            return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="cleanup-secret")
            database = V2Database(settings)
            database.initialize()
            tasks = TaskService(database)
            tasks.create_task("old-report", TaskType.REPORT, "导出预测报表", status=TaskStatus.SUCCESS, progress=100)
            tasks.create_task("new-report", TaskType.REPORT, "导出预测报表", status=TaskStatus.SUCCESS, progress=100)
            tasks.create_task("old-warning", TaskType.CLEANUP, "空间清理", status=TaskStatus.FAILED, progress=100)
            tasks.create_task("old-critical", TaskType.UPGRADE, "执行系统升级", status=TaskStatus.FAILED, progress=100)
            tasks.acknowledge("old-warning")
            with database.connection() as conn:
                conn.executemany(
                    "INSERT INTO collection_runs (status, message, started_at, finished_at) VALUES (?, ?, ?, ?)",
                    [
                        ("success", "old", iso(8), iso(8)),
                        ("success", "new", iso(1), iso(1)),
                    ],
                )
                conn.execute("INSERT OR REPLACE INTO metric_snapshots (id, metrics_text, updated_at) VALUES (1, ?, ?)", ("latest", iso(0)))
                conn.execute("UPDATE tasks SET finished_at = ?, updated_at = ? WHERE id IN ('old-report', 'old-warning', 'old-critical')", (iso(31), iso(31)))
                conn.execute("UPDATE tasks SET finished_at = ?, updated_at = ? WHERE id = 'new-report'", (iso(1), iso(1)))

            cleanup = CleanupService(settings, tasks)
            scan = cleanup.scan_sqlite_vacuum()
            self.assertEqual(scan["runtime_cache"]["metric_snapshots"]["delete_count"], 0)
            self.assertEqual(scan["runtime_cache"]["collection_runs"]["delete_count"], 1)
            self.assertEqual(scan["runtime_cache"]["tasks"]["delete_count"], 2)

            result = cleanup.vacuum_sqlite()
            self.assertTrue(Path(result["backup_path"]).is_file())
            self.assertEqual(result["runtime_cache"]["collection_runs_deleted"], 1)
            self.assertEqual(result["runtime_cache"]["tasks_deleted"], 2)
            self.assertEqual(result["runtime_cache"]["metric_snapshots_deleted"], 0)
            with database.connection() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM collection_runs").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM metric_snapshots").fetchone()[0], 1)
                task_ids = {row["id"] for row in conn.execute("SELECT id FROM tasks").fetchall()}
            self.assertEqual(task_ids, {"new-report", "old-critical", "cleanup-sqlite-runtime"})

    def test_sqlite_backup_cleanup_scans_db_backups_and_deletes_selected_files_only(self) -> None:
        from app.v2.cleanup.service import CleanupService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="cleanup-secret")
            database = V2Database(settings)
            database.initialize()
            settings.backups_dir.mkdir(parents=True, exist_ok=True)
            first = settings.backups_dir / "sqlite-before-vacuum-20260607015411.db"
            second = settings.backups_dir / "smartx-before-drop-legacy-volume-items.db"
            ignored_tar = settings.backups_dir / "upgrade-v0.5.0-before-20260606085950.tar.gz"
            nested = settings.backups_dir / "nested" / "sqlite-before-cleanup.db"
            first.write_bytes(b"a" * 10)
            second.write_bytes(b"b" * 20)
            ignored_tar.write_bytes(b"tar")
            nested.parent.mkdir()
            nested.write_bytes(b"nested")

            cleanup = CleanupService(settings, TaskService(database))
            scan = cleanup.scan_sqlite_backups()

            self.assertEqual(scan["total_count"], 2)
            self.assertEqual(scan["total_size"], 30)
            self.assertEqual({item["filename"] for item in scan["items"]}, {first.name, second.name})

            result = cleanup.cleanup_sqlite_backups([first.name, "../smartx-before-drop-legacy-volume-items.db", "missing.db"])

            self.assertEqual(result["deleted_count"], 2)
            self.assertEqual(result["space_reclaimed"], 30)
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())
            self.assertTrue(ignored_tar.exists())
            self.assertTrue(nested.exists())
            task = TaskService(database).list_tasks()[0]
            self.assertEqual(task["type"], "cleanup")
            self.assertIn("SQLite 备份清理", task["title"])


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed.")
class V2CleanupApiTest(unittest.TestCase):
    def test_cleanup_api_requires_auth_scans_and_cleans_artifacts(self) -> None:
        import os

        from app.v2.config import settings_from_environment
        from app.v2.api import get_system_control_service
        from app.v2.main import create_app

        class FakeSystemControl:
            def __init__(self) -> None:
                self.restart_calls = 0

            def restart_data_services(self) -> dict:
                self.restart_calls += 1
                return {"ok": True, "services": ["web-api", "collector-worker", "prometheus"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_SECRET_KEY"] = "cleanup-api-secret"
            os.environ["SMARTX_ADMIN_PASSWORD"] = "password"
            try:
                app = create_app()
                fake_system = FakeSystemControl()
                app.dependency_overrides[get_system_control_service] = lambda: fake_system
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

                    local_storage = client.get("/api/admin/system/local-storage", headers=headers)
                    self.assertEqual(local_storage.status_code, 200)
                    self.assertEqual(local_storage.json()["path"], str(settings.data_root))
                    self.assertIn("free_ratio", local_storage.json())

                    sqlite_scan = client.get("/api/admin/system/sqlite-vacuum/scan", headers=headers)
                    self.assertEqual(sqlite_scan.status_code, 200)
                    self.assertIn("estimated_reclaimable", sqlite_scan.json())

                    sqlite_vacuum = client.post("/api/admin/system/sqlite-vacuum", headers=headers)
                    self.assertEqual(sqlite_vacuum.status_code, 200)
                    self.assertTrue(Path(sqlite_vacuum.json()["backup_path"]).is_file())

                    sqlite_backup = settings.backups_dir / "sqlite-before-cleanup-test.db"
                    sqlite_backup.write_bytes(b"backup")
                    sqlite_backup_scan = client.get("/api/admin/system/sqlite-backups/scan", headers=headers)
                    self.assertEqual(sqlite_backup_scan.status_code, 200)
                    self.assertIn(sqlite_backup.name, {item["filename"] for item in sqlite_backup_scan.json()["items"]})
                    sqlite_backup_cleanup = client.post("/api/admin/system/sqlite-backups/delete", headers=headers, json={"filenames": [sqlite_backup.name]})
                    self.assertEqual(sqlite_backup_cleanup.status_code, 200)
                    self.assertEqual(sqlite_backup_cleanup.json()["deleted_count"], 1)
                    self.assertFalse(sqlite_backup.exists())

                    restart = client.post("/api/admin/system/restart", headers=headers)
                    self.assertEqual(restart.status_code, 200)
                    self.assertEqual(restart.json()["services"], ["web-api", "collector-worker", "prometheus"])
                    self.assertEqual(fake_system.restart_calls, 1)
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_SECRET_KEY", None)
                os.environ.pop("SMARTX_ADMIN_PASSWORD", None)


if __name__ == "__main__":
    unittest.main()


class CleanupKeepsRecordsDropsPackagesTest(unittest.TestCase):
    """清理只删包、保留记录（用户口径 2026-10-04）。

    背景：单个升级任务目录里 `package/` + `*.tar.gz` 占 200M~853M，
    而 `task.json` 只有 40K~172K，且**升级中心历史完全依赖它**
    （`intake.py::history` 只扫 `*/task.json`，不读 `package/`）。
    """

    def _make_task(self, settings, name: str, age_seconds: int) -> Path:
        import os

        task_dir = settings.upgrades_dir / name
        (task_dir / "package" / "images").mkdir(parents=True)
        (task_dir / "package" / "images" / "web-api.tar").write_bytes(b"x" * 4096)
        (task_dir / "smartx-capacity-insight-upgrade-v0.5.3.tar.gz").write_bytes(b"y" * 4096)
        (task_dir / "task.json").write_text('{"status": "success"}', encoding="utf-8")
        (task_dir / "post-upgrade-cleanup.json").write_text("{}", encoding="utf-8")
        stamp = datetime.now().timestamp() - age_seconds
        os.utime(task_dir, (stamp, stamp))
        return task_dir

    def test_old_task_loses_package_but_keeps_record(self) -> None:
        from app.v2.cleanup.service import CleanupService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="s")
            database = V2Database(settings)
            database.initialize()
            old = self._make_task(settings, "upgrade-old", age_seconds=10_000)
            self._make_task(settings, "upgrade-new", age_seconds=10)

            cleanup = CleanupService(settings, TaskService(database))
            result = cleanup.cleanup_artifacts()

            self.assertTrue(result["ok"])
            # 记录仍在（升级中心历史靠它）
            self.assertTrue((old / "task.json").is_file(), "旧任务的 task.json 必须保留")
            self.assertTrue(
                (old / "post-upgrade-cleanup.json").is_file(), "小标记文件应保留"
            )
            # 包被删
            self.assertFalse((old / "package").exists(), "旧任务的 package/ 应被删")
            self.assertFalse(
                (old / "smartx-capacity-insight-upgrade-v0.5.3.tar.gz").exists(),
                "旧任务的升级包本体应被删",
            )

    def test_keep_recent_defaults_to_one_and_is_floored(self) -> None:
        """默认保留最近 1 个包；即使显式传 0 也不得清光（回滚需旧镜像）。"""
        from app.v2.cleanup.service import CleanupService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="s")
            database = V2Database(settings)
            database.initialize()
            newest = self._make_task(settings, "upgrade-newest", age_seconds=10)
            self._make_task(settings, "upgrade-older", age_seconds=5_000)

            cleanup = CleanupService(settings, TaskService(database))
            result = cleanup.cleanup_artifacts(keep_recent_upgrades=0)

            self.assertTrue(result["ok"])
            self.assertEqual(
                result["kept_count"], 1, "传 0 也必须保留下限 1 个（回滚需旧镜像来源）"
            )
            self.assertTrue(
                (newest / "package").exists(), "最近一次的包应保留（供回滚/重装）"
            )

    def test_ghost_running_task_does_not_block_cleanup(self) -> None:
        """僵尸 running 任务（目录已不存在）不得锁死清理。

        `.12` 实测 2026-10-04：tasks 表有两个 7 月的 running 僵尸任务，
        目录早已不存在，导致该机从 7 月起空间清理功能实际是废的、磁盘堆到 94%。
        """
        from app.v2.cleanup.service import CleanupService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.models import TaskStatus, TaskType
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="s")
            database = V2Database(settings)
            database.initialize()
            tasks = TaskService(database)
            # 僵尸：库里有 running 记录、磁盘上无目录、且状态陈旧（数月前）
            tasks.create_task(
                "upgrade-ghost", TaskType.UPGRADE, "平台升级",
                status=TaskStatus.RUNNING, progress=10,
            )
            with tasks.database.connection() as conn:
                conn.execute(
                    "UPDATE tasks SET updated_at = ?, created_at = ? WHERE id = ?",
                    (
                        (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(),
                        (datetime.now(timezone.utc) - timedelta(days=91)).isoformat(),
                        "upgrade-ghost",
                    ),
                )
            self.assertFalse((settings.upgrades_dir / "upgrade-ghost").exists())
            # 两个任务目录：因keep_recent 下限为 1，会保留最近 1 个、清理更旧的 1 个
            for name, age in (("upgrade-old", 5000), ("upgrade-new", 10)):
                d = settings.upgrades_dir / name
                (d / "package").mkdir(parents=True)
                (d / "package" / "a.tar").write_bytes(b"z" * 2048)
                (d / "task.json").write_text("{}", encoding="utf-8")
                import os as _os
                stamp = datetime.now().timestamp() - age
                _os.utime(d, (stamp, stamp))

            cleanup = CleanupService(settings, tasks)
            result = cleanup.cleanup_artifacts()

            self.assertTrue(result["ok"], f"僵尸任务不应阻塞清理：{result.get('message')}")
            self.assertGreater(
                result["deleted_count"], 0, "放行后应能实际清理旧任务的包"
            )
            # 记录仍保留（历史可查）
            self.assertTrue((settings.upgrades_dir / "upgrade-old" / "task.json").is_file())

    def test_real_running_task_still_blocks_cleanup(self) -> None:
        """真正在跑的任务（目录存在）仍必须阻塞清理——不能为了清僵尸而放开真任务。"""
        from app.v2.cleanup.service import CleanupService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.models import TaskStatus, TaskType
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="s")
            database = V2Database(settings)
            database.initialize()
            tasks = TaskService(database)
            tasks.create_task(
                "upgrade-live", TaskType.UPGRADE, "平台升级",
                status=TaskStatus.RUNNING, progress=10,
            )
            live_dir = settings.upgrades_dir / "upgrade-live"
            (live_dir / "package").mkdir(parents=True)
            (live_dir / "package" / "a.tar").write_bytes(b"z" * 2048)

            cleanup = CleanupService(settings, tasks)
            result = cleanup.cleanup_artifacts()

            self.assertFalse(result["ok"], "真在跑的任务必须继续阻塞清理")
            self.assertTrue((live_dir / "package").exists(), "活跃任务的包不能被删")


    def test_fresh_running_task_without_dir_still_blocks(self) -> None:
        """目录缺失但状态新鲜 ⇒ 仍按活跃处理（刚创建、目录尚未落盘的窗口）。

        这条锁住双重判定：若只按「目录不存在」放行，会在任务刚创建时误清其产物。
        """
        from app.v2.cleanup.service import CleanupService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.models import TaskStatus, TaskType
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="s")
            database = V2Database(settings)
            database.initialize()
            tasks = TaskService(database)
            tasks.create_task(
                "upgrade-fresh", TaskType.UPGRADE, "平台升级",
                status=TaskStatus.RUNNING, progress=10,
            )
            self.assertFalse((settings.upgrades_dir / "upgrade-fresh").exists())
            stray = settings.upgrades_dir / "old-payload" / "package"
            stray.mkdir(parents=True)
            (stray / "a.tar").write_bytes(b"z" * 2048)

            cleanup = CleanupService(settings, tasks)
            result = cleanup.cleanup_artifacts()

            self.assertFalse(result["ok"], "状态新鲜的 running 任务必须继续阻塞清理")
            self.assertTrue(stray.exists())
