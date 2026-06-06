import os
import tempfile
import unittest


try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local host may not have web deps.
    TestClient = None


class V2TaskServiceTest(unittest.TestCase):
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
                    self.assertEqual(listed.json()[0]["id"], "task-1")

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


if __name__ == "__main__":
    unittest.main()
