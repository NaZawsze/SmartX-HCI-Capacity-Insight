"""US-26：平台包对 runner 只有「声明」没有「指令」——现场 runner 已够用时平台升级不得重建它。

设计：docs/superpowers/specs/2026-09-28-us26-runner-declaration-not-instruction-design.md
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class RunnerDeclarationNotInstructionTest(unittest.TestCase):
    # ---------- 编译层：只取可部署条目 ----------

    def _manifest(self, *, runner_deploy: bool | None) -> dict:
        runner_entry = {
            "service": "upgrade-runner",
            "image": "repo/upgrade-runner:v0.3.1",
            "archive": None,
        }
        if runner_deploy is not None:
            runner_entry["deploy"] = runner_deploy
        return {
            "schema_version": "3",
            "version": "v0.5.3",
            "components": [
                {
                    "type": "platform",
                    "services": ["web-api", "collector-worker", "frontend", "upgrade-runner"],
                    "images": [
                        {"service": "web-api", "image": "repo/web-api:v0.5.3", "archive": None},
                        {"service": "collector-worker", "image": "repo/collector-worker:v0.5.3", "archive": None},
                        {"service": "frontend", "image": "repo/frontend:v0.5.3", "archive": None},
                        runner_entry,
                    ],
                }
            ],
        }

    def _compile(self, manifest: dict) -> dict:
        from app.v2.upgrade.compiler import compile_execution_plan

        return compile_execution_plan(manifest).to_dict()

    def test_declaration_only_entry_yields_no_runner_deploy_image(self) -> None:
        """平台包把 runner 标为 deploy:False → 计划里不得出现 runner 部署镜像。"""
        plan = self._compile(self._manifest(runner_deploy=False))
        handoffs = [
            action
            for action in plan["actions"]
            if action["type"] in {"runner.handoff_target_runtime", "runner.schedule_target_runtime_handoff"}
        ]
        for action in handoffs:
            self.assertEqual(action["params"].get("image", ""), "", "平台包不得指挥 runner 镜像")
            self.assertTrue(action["params"].get("preserve_current"), "必须标记 preserve_current")

    def test_deployable_entry_still_carries_image(self) -> None:
        """显式 deploy:True（老包/组件包语义）仍应下发镜像，保持向后兼容。"""
        plan = self._compile(self._manifest(runner_deploy=True))
        handoffs = [
            action
            for action in plan["actions"]
            if action["type"] in {"runner.handoff_target_runtime", "runner.schedule_target_runtime_handoff"}
        ]
        for action in handoffs:
            self.assertEqual(action["params"].get("image"), "repo/upgrade-runner:v0.3.1")
            self.assertFalse(action["params"].get("preserve_current"))

    def test_compose_apply_never_redeploys_runner(self) -> None:
        """固化既有正确行为：compose.apply 的服务列表不含 upgrade-runner。"""
        plan = self._compile(self._manifest(runner_deploy=False))
        applies = [action for action in plan["actions"] if action["type"] == "compose.apply"]
        self.assertTrue(applies, "计划应包含 compose.apply")
        for action in applies:
            self.assertNotIn("upgrade-runner", list(action["params"].get("services") or []))

    # ---------- 动作层：preserve_current 沿用现场镜像 ----------

    def _context(self, root: Path, current_image: str, executor):
        from app.upgrade_runner.actions import ActionContext

        return ActionContext(
            package_path=root,
            project_path=root / "project",
            data_path=root / "app",
            upgrades_path=root / "upgrades",
            backups_path=root / "backups",
            exports_path=root / "exports",
            compose_runtime_path=root / "compose-runtime",
            prometheus_path=root / "prometheus",
            compose_file=str(root / "project" / "docker-compose.yml"),
            compose_project="smartx-hci-capacity-insight",
            executor=executor,
            task_id="upgrade-test",
            host_data_path=root / "app",
            host_upgrades_path=root / "upgrades",
            host_backups_path=root / "backups",
            host_exports_path=root / "exports",
            host_compose_runtime_path=root / "compose-runtime",
            host_prometheus_path=root / "prometheus",
            current_container_id="runner-container-1",
        )

    def test_preserve_current_uses_field_runner_image(self) -> None:
        from app.upgrade_runner.actions import _write_runner_runtime_compose

        class FakeExecutor:
            def output(self, command):
                return json.dumps([{"Config": {"Image": "repo/upgrade-runner:v0.3.2"}}])

            def run(self, command, cwd=None):
                return None

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for name in ("project", "app", "upgrades", "backups", "exports", "compose-runtime", "prometheus"):
                (root / name).mkdir(parents=True, exist_ok=True)
            context = self._context(root, "repo/upgrade-runner:v0.3.2", FakeExecutor())

            runtime = _write_runner_runtime_compose(
                context, {"image": "", "preserve_current": True, "compose_project": "smartx-hci-capacity-insight"}
            )

            self.assertEqual(runtime["image"], "repo/upgrade-runner:v0.3.2", "必须沿用现场更高版本")
            self.assertEqual(runtime["image_source"], "field")
            content = Path(runtime["compose_file"]).read_text(encoding="utf-8")
            self.assertIn("repo/upgrade-runner:v0.3.2", content)
            self.assertNotIn("v0.3.1", content)

    def test_missing_image_without_preserve_still_raises(self) -> None:
        """防真缺镜像被静默跳过：无 preserve_current 且无 image 仍应报错。"""
        from app.upgrade_runner.actions import _write_runner_runtime_compose

        class FakeExecutor:
            def output(self, command):
                return "[]"

            def run(self, command, cwd=None):
                return None

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for name in ("project", "app", "upgrades", "backups", "exports", "compose-runtime", "prometheus"):
                (root / name).mkdir(parents=True, exist_ok=True)
            context = self._context(root, "", FakeExecutor())

            with self.assertRaises(ValueError):
                _write_runner_runtime_compose(context, {"image": "", "compose_project": "smartx-hci-capacity-insight"})

    def test_preserve_current_without_field_image_refuses_to_downgrade(self) -> None:
        """现场镜像取不到时必须报错，绝不退回包内基线。"""
        from app.upgrade_runner.actions import _write_runner_runtime_compose

        class FakeExecutor:
            def output(self, command):
                return "[]"

            def run(self, command, cwd=None):
                return None

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for name in ("project", "app", "upgrades", "backups", "exports", "compose-runtime", "prometheus"):
                (root / name).mkdir(parents=True, exist_ok=True)
            context = self._context(root, "", FakeExecutor())

            with self.assertRaises(ValueError):
                _write_runner_runtime_compose(
                    context, {"image": "", "preserve_current": True, "compose_project": "smartx-hci-capacity-insight"}
                )

    # ---------- 组件升级侧：tag 回写 ----------

    def test_component_upgrade_writes_back_runner_tag(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeService

        compose = (
            "services:\n"
            "  web-api:\n"
            "    image: repo/web-api:v0.5.3\n"
            "  upgrade-runner:\n"
            "    image: repo/upgrade-runner:v0.3.1\n"
            "    command: [\"python\", \"-m\", \"app.upgrade_runner.main\"]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "project"
            project_dir.mkdir(parents=True, exist_ok=True)
            settings = V2Settings(
                data_root=Path(tmpdir), secret_key="us26-secret", app_version="v0.5.3",
                project_path_override=project_dir,
            )
            database = V2Database(settings)
            database.initialize()
            service = UpgradeService(settings, TaskService(database), project_path=project_dir)
            project_compose = project_dir / "docker-compose.yml"
            project_compose.parent.mkdir(parents=True, exist_ok=True)
            project_compose.write_text(compose, encoding="utf-8")
            runtime_compose = settings.compose_runtime_dir / "docker-compose.runner-upgrade.yml"
            runtime_compose.parent.mkdir(parents=True, exist_ok=True)
            runtime_compose.write_text(compose, encoding="utf-8")

            updated = service._sync_runner_image_into_compose_files("repo/upgrade-runner:v0.3.2")

            self.assertEqual(len(updated), 2, f"应回写 project compose 与 runner-upgrade compose，实际 {updated}")
            for path in (project_compose, runtime_compose):
                text = path.read_text(encoding="utf-8")
                self.assertIn("repo/upgrade-runner:v0.3.2", text)
                self.assertNotIn("v0.3.1", text)
                self.assertIn("repo/web-api:v0.5.3", text, "只应改 runner，不得波及其他服务")

    def test_write_back_is_idempotent(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeService

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "project"
            project_dir.mkdir(parents=True, exist_ok=True)
            settings = V2Settings(
                data_root=Path(tmpdir), secret_key="us26-secret", app_version="v0.5.3",
                project_path_override=project_dir,
            )
            database = V2Database(settings)
            database.initialize()
            service = UpgradeService(settings, TaskService(database), project_path=project_dir)
            project_compose = project_dir / "docker-compose.yml"
            project_compose.parent.mkdir(parents=True, exist_ok=True)
            project_compose.write_text(
                "services:\n  upgrade-runner:\n    image: repo/upgrade-runner:v0.3.1\n",
                encoding="utf-8",
            )

            first = service._sync_runner_image_into_compose_files("repo/upgrade-runner:v0.3.2")
            second = service._sync_runner_image_into_compose_files("repo/upgrade-runner:v0.3.2")

            self.assertEqual(len(first), 1)
            self.assertEqual(second, [], "已是目标 tag 时不应重复写入")
            self.assertIn("v0.3.2", project_compose.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
