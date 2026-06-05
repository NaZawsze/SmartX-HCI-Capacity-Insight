import unittest


class V2TaskModelsTest(unittest.TestCase):
    def test_task_status_values_are_stable_for_frontend_and_runner(self) -> None:
        from app.v2.tasks.models import TaskStatus

        self.assertEqual(
            [status.value for status in TaskStatus],
            ["pending", "running", "success", "failed", "cancelled"],
        )

    def test_task_snapshot_progress_is_clamped_for_ui(self) -> None:
        from app.v2.tasks.models import TaskSnapshot, TaskStatus, TaskType

        low = TaskSnapshot(task_id="task-low", task_type=TaskType.REPORT, status=TaskStatus.RUNNING, progress=-10)
        high = TaskSnapshot(task_id="task-high", task_type=TaskType.REPORT, status=TaskStatus.RUNNING, progress=120)

        self.assertEqual(low.progress, 0)
        self.assertEqual(high.progress, 100)

    def test_error_snapshot_uses_safe_public_message(self) -> None:
        from app.v2.tasks.models import ErrorSnapshot

        error = ErrorSnapshot(code="upgrade.precheck_failed", message="预检查失败")

        self.assertEqual(error.to_dict(), {"code": "upgrade.precheck_failed", "message": "预检查失败"})


if __name__ == "__main__":
    unittest.main()
