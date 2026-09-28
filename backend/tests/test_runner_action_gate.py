"""49-50：升级预检查「动作级」runner 校验。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


MINIMAL_PLATFORM_MANIFEST = {
    "schema_version": "3",
    "version": "v0.5.3",
    "min_version": "v0.5.0",
    "package_type": "platform",
    "minimum_runner_protocol": 1,
    "minimum_runner_version": "v0.3.1",
    "required_capabilities": ["backup.v1", "image.v1", "files.v1", "compose.v1", "health.v1"],
    "source_compatibility": {
        "min_version": "v0.5.0",
        "max_version_inclusive": "v0.5.3",
        "target_version": "v0.5.3",
        "supported_versions": ["v0.5.2", "v0.5.3"],
    },
    "components": [
        {
            "type": "platform",
            "services": ["web-api"],
            "images": [
                {
                    "service": "web-api",
                    "image": "repo/web-api:v0.5.3",
                    "archive": "images/web-api.tar",
                }
            ],
        }
    ],
    "post_upgrade": {"auto_collection": False, "platform_collection": True, "create_cleanup_task": True},
}


class RunnerActionSetsTest(unittest.TestCase):
    def test_released_and_current_action_sets_match_reality(self) -> None:
        from app.upgrade_protocol.constants import RELEASED_RUNNER_ACTIONS, current_runner_actions
        from app.upgrade_runner.actions import default_handlers

        # 发行版 v0.3.1（Release 资产 d10e15cf）：25 个动作、无 schedule_collection
        self.assertEqual(len(RELEASED_RUNNER_ACTIONS), 25)
        self.assertNotIn("post_upgrade.schedule_collection", RELEASED_RUNNER_ACTIONS)

        # 当前仓库 runner = 发行版 + schedule_collection，且必须与 runner 代码一致（改 runner 忘更新表会挂）
        current = current_runner_actions()
        self.assertEqual(current, frozenset(default_handlers()))
        self.assertEqual(current - RELEASED_RUNNER_ACTIONS, {"post_upgrade.schedule_collection"})
        self.assertEqual(RELEASED_RUNNER_ACTIONS - current, set())

    def test_runner_supported_actions_lookup(self) -> None:
        from app.upgrade_protocol.constants import (
            RELEASED_RUNNER_ACTIONS,
            current_runner_actions,
            runner_supported_actions,
        )

        self.assertEqual(runner_supported_actions("v0.3.1"), RELEASED_RUNNER_ACTIONS)
        self.assertEqual(runner_supported_actions("v0.3.2"), current_runner_actions())
        self.assertEqual(runner_supported_actions("v0.9.9"), current_runner_actions())
        self.assertIsNone(runner_supported_actions("v0.3.0"))
        self.assertIsNone(runner_supported_actions(""))
        self.assertIsNone(runner_supported_actions(None))  # type: ignore[arg-type]


class PrecheckRunnerActionsTest(unittest.TestCase):
    def _service(self, tmpdir: str, runner_version: str):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeCommandExecutor, UpgradeService

        class FakeExecutor(UpgradeCommandExecutor):
            def run(self, command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
                return None

        settings = V2Settings(data_root=Path(tmpdir), secret_key="action-gate-secret", app_version="v0.5.3")
        database = V2Database(settings)
        database.initialize()
        record_runner_state(database, version=runner_version)
        return UpgradeService(
            settings,
            TaskService(database),
            executor=FakeExecutor(),
            project_path=Path(tmpdir) / "project",
        )

    def test_gate_passes_for_released_runner_when_plan_needs_nothing_new(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir, "v0.3.1")
            check = service._check_runner_actions(MINIMAL_PLATFORM_MANIFEST)

        self.assertTrue(check["ok"], check["message"])
        self.assertIn("全部支持", check["message"])
        self.assertIn("v0.3.1", check["message"])

    def test_gate_fails_for_older_runner_and_tells_user_to_upgrade_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir, "v0.3.0")
            check = service._check_runner_actions(MINIMAL_PLATFORM_MANIFEST)

        self.assertFalse(check["ok"])
        self.assertIn("至少需要 v0.3.1", check["message"])
        self.assertIn("组件升级", check["message"])
        self.assertIn("v0.3.2", check["message"])

    def test_gate_passes_for_current_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir, "v0.3.2")
            check = service._check_runner_actions(MINIMAL_PLATFORM_MANIFEST)

        self.assertTrue(check["ok"], check["message"])

    def test_gate_fails_when_plan_requires_action_missing_from_released_runner(self) -> None:
        """人为构造「计划需要发行版没有的动作」的场景（49-49 后编译器不再产生，故直接注入）。"""
        from app.upgrade_protocol.constants import RELEASED_RUNNER_ACTIONS, runner_supported_actions

        plan_actions = {"post_upgrade.schedule_collection"}
        supported = runner_supported_actions("v0.3.1")
        self.assertIsNotNone(supported)
        missing = sorted(plan_actions - supported)  # type: operator-arg-type
        self.assertEqual(missing, ["post_upgrade.schedule_collection"])
        self.assertNotIn(missing[0], RELEASED_RUNNER_ACTIONS)


class ImagesGateRunnerHintTest(unittest.TestCase):
    def test_missing_runner_image_hint_mentions_component_upgrade(self) -> None:
        """49-50：manifest 声明的 runner 镜像本地不存在时，提示必须指向「组件升级到该版本」。"""
        from app.v2.upgrade.service.precheck import _check_images_with_executor

        class MissingImageExecutor:
            def run(self, command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
                raise RuntimeError("No such image")

        manifest = {
            "components": [
                {
                    "type": "runner",
                    "services": ["upgrade-runner"],
                    "images": [
                        {
                            "service": "upgrade-runner",
                            "image": "nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.2",
                            "archive": None,
                        }
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            check = _check_images_with_executor(Path(tmpdir), manifest, MissingImageExecutor())  # type: ignore[arg-type]

        self.assertFalse(check["ok"])
        self.assertIn("本地 Docker 镜像不存在", check["message"])
        self.assertIn("组件升级", check["message"])
        self.assertIn("v0.3.2", check["message"])


def record_runner_state(database, *, version: str, capabilities: list[str] | None = None) -> None:
    import json

    if capabilities is None:
        from app.upgrade_protocol.constants import RUNNER_CAPABILITIES

        capabilities = sorted(RUNNER_CAPABILITIES)
    with database.connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO upgrade_runner_state
                (id, instance_id, runner_version, protocol_version, capabilities_json, heartbeat_at, updated_at)
            VALUES (1, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            ("runner-a", version, 1, json.dumps(capabilities)),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
