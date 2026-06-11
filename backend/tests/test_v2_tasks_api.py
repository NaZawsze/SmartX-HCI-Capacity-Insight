import os
import tempfile
import unittest
from pathlib import Path


try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local host may not have web deps.
    TestClient = None


class V2TaskServiceTest(unittest.TestCase):
    def test_database_initializes_versioned_schema_migrations_table(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=tmpdir, secret_key="tasks-secret")
            database = V2Database(settings)
            database.initialize()

            with database.connection() as conn:
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(schema_migrations)").fetchall()}

            self.assertTrue({"id", "version", "description", "script_sha256", "applied_at"}.issubset(columns))

    def test_task_service_persists_lists_updates_and_clears_finished_tasks(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.models import TaskStatus, TaskType
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=tmpdir, secret_key="tasks-secret")
            database = V2Database(settings)
            database.initialize()
            tasks = TaskService(database)

            created = tasks.create_task(
                "task-1",
                TaskType.REPORT,
                "导出预测报表",
                message="排队中",
                steps=[{"key": "prepare", "title": "准备数据", "status": "running"}],
            )
            self.assertEqual(created["status"], TaskStatus.PENDING.value)
            self.assertEqual(created["progress"], 0)
            self.assertEqual(created["steps"][0]["key"], "prepare")

            updated = tasks.update_task(
                "task-1",
                status=TaskStatus.SUCCESS,
                progress=120,
                message="完成",
                links=[{"label": "Excel", "url": "/download"}],
                steps=[{"key": "prepare", "title": "准备数据", "status": "succeeded"}],
            )
            self.assertEqual(updated["status"], TaskStatus.SUCCESS.value)
            self.assertEqual(updated["progress"], 100)
            self.assertEqual(updated["links"][0]["label"], "Excel")
            self.assertEqual(updated["steps"][0]["status"], "succeeded")

            listed = tasks.list_tasks()
            self.assertEqual([task["id"] for task in listed], ["task-1"])
            self.assertEqual(listed[0]["message"], "完成")
            self.assertEqual(listed[0]["steps"][0]["title"], "准备数据")

            tasks.create_task("task-pending", TaskType.UPGRADE, "执行系统升级", progress=1, message="等待 upgrade-runner 执行")
            tasks.create_task("task-running", TaskType.UPGRADE, "执行系统升级", status=TaskStatus.RUNNING, progress=30)
            tasks.create_task("task-failed", TaskType.UPGRADE, "执行系统升级", status=TaskStatus.FAILED, progress=100)
            tasks.create_task("task-cancelled", TaskType.UPGRADE, "执行系统升级", status=TaskStatus.CANCELLED, progress=100)

            self.assertEqual(tasks.clear_finished(), 1)
            self.assertEqual([task["id"] for task in tasks.list_tasks()], ["task-cancelled", "task-failed", "task-running", "task-pending"])

            self.assertFalse(tasks.delete_inactive("task-running"))
            self.assertTrue(tasks.delete_inactive("task-failed"))
            self.assertTrue(tasks.delete_inactive("task-cancelled"))
            self.assertEqual([task["id"] for task in tasks.list_tasks()], ["task-running", "task-pending"])

    def test_task_notifications_track_severity_seen_ack_and_clearable_tasks(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.models import TaskStatus, TaskType
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=tmpdir, secret_key="tasks-secret")
            database = V2Database(settings)
            database.initialize()
            tasks = TaskService(database)

            report = tasks.create_task("report-1", TaskType.REPORT, "导出预测报表", status=TaskStatus.SUCCESS, progress=100)
            cleanup = tasks.create_task("cleanup-1", TaskType.CLEANUP, "空间清理", status=TaskStatus.FAILED, progress=100)
            upgrade = tasks.create_task("upgrade-1", TaskType.UPGRADE, "执行系统升级", status=TaskStatus.FAILED, progress=100)

            self.assertEqual(report["severity"], "info")
            self.assertTrue(report["unhandled"])
            self.assertTrue(report["clearable"])
            self.assertEqual(cleanup["severity"], "warning")
            self.assertTrue(cleanup["unhandled"])
            self.assertFalse(cleanup["clearable"])
            self.assertEqual(upgrade["severity"], "critical")
            self.assertTrue(upgrade["unhandled"])
            self.assertFalse(upgrade["clearable"])

            seen = tasks.mark_info_seen(["report-1", "cleanup-1", "upgrade-1"])
            self.assertEqual(seen, 1)
            acknowledged = tasks.acknowledge("cleanup-1")
            self.assertEqual(acknowledged["severity"], "warning")
            self.assertFalse(acknowledged["unhandled"])
            self.assertTrue(acknowledged["clearable"])

            listed = {task["id"]: task for task in tasks.list_tasks()}
            self.assertFalse(listed["report-1"]["unhandled"])
            self.assertTrue(listed["report-1"]["clearable"])
            self.assertTrue(listed["upgrade-1"]["unhandled"])
            self.assertFalse(listed["upgrade-1"]["clearable"])

            self.assertEqual(tasks.clear_clearable(), 2)
            self.assertEqual([task["id"] for task in tasks.list_tasks()], ["upgrade-1"])

    def test_acknowledge_warning_task_does_not_change_sort_timestamp(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.models import TaskStatus, TaskType
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=tmpdir, secret_key="tasks-secret")
            database = V2Database(settings)
            database.initialize()
            tasks = TaskService(database)

            tasks.create_task("older-warning", TaskType.CLEANUP, "空间清理", status=TaskStatus.FAILED, progress=100)
            tasks.create_task("newer-report", TaskType.REPORT, "导出预测报表", status=TaskStatus.SUCCESS, progress=100)
            with database.connection() as conn:
                conn.execute(
                    "UPDATE tasks SET updated_at = ? WHERE id = ?",
                    ("2026-06-01T00:00:00+00:00", "older-warning"),
                )
                conn.execute(
                    "UPDATE tasks SET updated_at = ? WHERE id = ?",
                    ("2026-06-02T00:00:00+00:00", "newer-report"),
                )

            before = tasks.get_task("older-warning")
            acknowledged = tasks.acknowledge("older-warning")
            listed_ids = [task["id"] for task in tasks.list_tasks()]

            self.assertEqual(acknowledged["updated_at"], before["updated_at"])
            self.assertIsNotNone(acknowledged["acknowledged_at"])
            self.assertFalse(acknowledged["unhandled"])
            self.assertTrue(acknowledged["clearable"])
            self.assertEqual(listed_ids, ["newer-report", "older-warning"])

    def test_task_clear_handles_legacy_null_severity_rows(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.models import TaskStatus, TaskType
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=tmpdir, secret_key="tasks-secret")
            database = V2Database(settings)
            database.initialize()
            tasks = TaskService(database)

            tasks.create_task("legacy-report", TaskType.REPORT, "导出预测报表", status=TaskStatus.SUCCESS, progress=100)
            tasks.create_task("legacy-cleanup", TaskType.CLEANUP, "空间清理", status=TaskStatus.SUCCESS, progress=100)
            tasks.create_task("legacy-upgrade", TaskType.UPGRADE, "执行系统升级", status=TaskStatus.FAILED, progress=100)
            with database.connection() as conn:
                conn.execute("UPDATE tasks SET severity = NULL")

            listed = {task["id"]: task for task in tasks.list_tasks()}
            self.assertEqual(listed["legacy-report"]["severity"], "info")
            self.assertEqual(listed["legacy-cleanup"]["severity"], "info")
            self.assertEqual(listed["legacy-upgrade"]["severity"], "critical")
            self.assertTrue(listed["legacy-report"]["clearable"])
            self.assertTrue(listed["legacy-cleanup"]["clearable"])
            self.assertFalse(listed["legacy-upgrade"]["clearable"])

            self.assertEqual(tasks.clear_clearable(), 2)
            self.assertEqual([task["id"] for task in tasks.list_tasks()], ["legacy-upgrade"])

    def test_task_links_report_missing_export_files_as_expired(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.models import TaskStatus, TaskType
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=tmpdir, secret_key="tasks-secret")
            database = V2Database(settings)
            database.initialize()
            tasks = TaskService(database)
            existing = settings.reports_dir / "report.docx"
            existing.parent.mkdir(parents=True, exist_ok=True)
            existing.write_bytes(b"report")
            missing = settings.migrations_dir / "missing.tar.gz"

            tasks.create_task(
                "task-links",
                TaskType.REPORT,
                "导出预测报表",
                status=TaskStatus.SUCCESS,
                progress=100,
                links=[
                    {"label": "Word", "filename": existing.name, "url": "/api/admin/exports/reports/report.docx", "path": str(existing)},
                    {"label": "迁移包", "filename": missing.name, "url": "/api/admin/exports/migrations/missing.tar.gz", "path": str(missing)},
                    {"label": "整理前备份", "filename": "backup.db", "url": "", "path": str(Path(tmpdir) / "backups" / "backup.db")},
                ],
            )

            links = tasks.list_tasks()[0]["links"]
            self.assertTrue(links[0]["exists"])
            self.assertFalse(links[0]["expired"])
            self.assertFalse(links[1]["exists"])
            self.assertTrue(links[1]["expired"])
            self.assertNotIn("exists", links[2])


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed.")
class V2TaskApiTest(unittest.TestCase):
    def test_task_api_requires_auth_lists_and_clears_finished_tasks(self) -> None:
        from app.v2.config import settings_from_environment
        from app.v2.database import V2Database
        from app.v2.main import create_app
        from app.v2.tasks.models import TaskStatus, TaskType
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_SECRET_KEY"] = "tasks-api-secret"
            os.environ["SMARTX_ADMIN_PASSWORD"] = "password"
            try:
                app = create_app()
                with TestClient(app) as client:
                    self.assertEqual(client.get("/api/tasks").status_code, 401)
                    token = client.post("/api/auth/login", json={"username": "admin", "password": "password"}).json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}

                    database = V2Database(settings_from_environment())
                    service = TaskService(database)
                    service.create_task("task-1", TaskType.REPORT, "导出预测报表")
                    service.update_task("task-1", status=TaskStatus.SUCCESS, progress=100, message="完成")
                    service.create_task("task-pending", TaskType.UPGRADE, "执行系统升级", progress=1, message="等待 upgrade-runner 执行")
                    service.create_task("task-running", TaskType.UPGRADE, "执行系统升级", status=TaskStatus.RUNNING, progress=30)
                    service.create_task("task-failed", TaskType.UPGRADE, "执行系统升级", status=TaskStatus.FAILED, progress=100)
                    service.create_task("task-cancelled", TaskType.UPGRADE, "执行系统升级", status=TaskStatus.CANCELLED, progress=100)
                    listed = client.get("/api/tasks", headers=headers)
                    self.assertEqual(listed.status_code, 200)
                    self.assertIn("task-1", {task["id"] for task in listed.json()})

                    cleared = client.delete("/api/tasks/finished", headers=headers)
                    self.assertEqual(cleared.status_code, 200)
                    self.assertEqual(cleared.json()["deleted"], 1)
                    remaining = client.get("/api/tasks", headers=headers).json()
                    self.assertEqual([task["id"] for task in remaining], ["task-cancelled", "task-failed", "task-running", "task-pending"])

                    self.assertEqual(client.delete("/api/tasks/task-running", headers=headers).status_code, 400)
                    deleted = client.delete("/api/tasks/task-failed", headers=headers)
                    self.assertEqual(deleted.status_code, 200)
                    remaining = client.get("/api/tasks", headers=headers).json()
                    self.assertEqual([task["id"] for task in remaining], ["task-cancelled", "task-running", "task-pending"])
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_SECRET_KEY", None)
                os.environ.pop("SMARTX_ADMIN_PASSWORD", None)

    def test_task_api_marks_seen_acknowledges_and_clears_only_clearable_tasks(self) -> None:
        from app.v2.config import settings_from_environment
        from app.v2.database import V2Database
        from app.v2.main import create_app
        from app.v2.tasks.models import TaskStatus, TaskType
        from app.v2.tasks.service import TaskService

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_SECRET_KEY"] = "tasks-api-secret"
            os.environ["SMARTX_ADMIN_PASSWORD"] = "password"
            try:
                app = create_app()
                with TestClient(app) as client:
                    token = client.post("/api/auth/login", json={"username": "admin", "password": "password"}).json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}

                    service = TaskService(V2Database(settings_from_environment()))
                    service.create_task("report-1", TaskType.REPORT, "导出预测报表", status=TaskStatus.SUCCESS, progress=100)
                    service.create_task("cleanup-1", TaskType.CLEANUP, "空间清理", status=TaskStatus.FAILED, progress=100)
                    service.create_task("upgrade-1", TaskType.UPGRADE, "执行系统升级", status=TaskStatus.FAILED, progress=100)

                    self.assertEqual(client.post("/api/tasks/cleanup-1/ack", headers=headers).json()["task_id"], "cleanup-1")
                    cleared = client.delete("/api/tasks/clearable", headers=headers)
                    self.assertEqual(cleared.status_code, 200)
                    self.assertEqual(cleared.json()["deleted"], 2)

                    remaining = client.get("/api/tasks", headers=headers).json()
                    self.assertEqual([task["id"] for task in remaining], ["upgrade-1"])
                    self.assertEqual(remaining[0]["severity"], "critical")
                    self.assertTrue(remaining[0]["unhandled"])
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_SECRET_KEY", None)
                os.environ.pop("SMARTX_ADMIN_PASSWORD", None)


if __name__ == "__main__":
    unittest.main()
