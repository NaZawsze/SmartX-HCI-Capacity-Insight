"""US-26：平台包对 runner 只有「基线声明」没有「部署指令」。

设计：docs/superpowers/specs/2026-09-28-us26-runner-declaration-not-instruction-design.md

实现路径（编译期解析，**不改 runner**）：
  1. manifest 的 runner 条目标 `deploy: false`（仅基线声明，不携带镜像）；
  2. web-api 在 `start()` 编译计划前调用 `_inject_field_runner_image()`，把**现场正在运行的
     runner 镜像**写回 manifest 副本；
  3. 编译器照常把该镜像放进 handoff 动作的 `params["image"]`——旧 runner 收到具体镜像照常执行，
     现场更高版本因此不会被包内基线降级；
  4. 取不到现场镜像 → 保留包内基线（= 现状，不会更坏）。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class RunnerDeclarationNotInstructionTest(unittest.TestCase):
    # ---------- 编译器：读取（已注入的）runner 镜像 ----------

    def _manifest(self, runner_image: str = "repo/upgrade-runner:v0.3.1") -> dict:
        entry = {"service": "upgrade-runner", "image": runner_image, "archive": None}
        return {
            "schema_version": "3",
            "version": "v0.5.3",
            "components": [
                {
                    "type": "platform",
                    "services": ["web-api", "collector-worker", "frontend", "upgrade-runner"],
                    "images": [
                        {"service": "web-api", "image": "repo/web-api:v0.5.3", "archive": None},
                        entry,
                    ],
                }
            ],
            "environment_transitions": [
                {"from_project": "old", "to_project": "smartx-hci-capacity-insight", "to_network": "smartx-hci-capacity-insight-net"}
            ],
            "directory_transition": {
                "project_path": "/data/smartx-storage-forecast/project",
                "app_data_path": "/data/smartx-storage-forecast/app",
                "upgrades_path": "/data/smartx-storage-forecast/upgrades",
                "backups_path": "/data/smartx-storage-forecast/backups",
                "exports_path": "/data/smartx-storage-forecast/exports",
                "compose_runtime_path": "/data/smartx-storage-forecast/compose-runtime",
                "prometheus_data_path": "/data/smartx-storage-forecast/prometheus",
            },
            "legacy_cleanup": {"legacy_projects": ["old"], "legacy_paths": ["/opt/old"]},
        }

    def _handoffs(self, plan: dict) -> list[dict]:
        return [
            action
            for action in plan["actions"]
            if action["type"] in {"runner.handoff_target_runtime", "runner.schedule_target_runtime_handoff"}
        ]

    def test_compiler_emits_injected_field_image(self) -> None:
        """web-api 注入现场镜像后，编译出的 handoff 携带现场版本（旧 runner 可直接执行）。"""
        from app.v2.upgrade.compiler import compile_execution_plan

        plan = compile_execution_plan(self._manifest(runner_image="repo/upgrade-runner:v0.3.2")).to_dict()
        for action in self._handoffs(plan):
            self.assertEqual(action["params"].get("image"), "repo/upgrade-runner:v0.3.2")
            self.assertNotIn("preserve_current", action["params"], "不应引入旧 runner 不认识的新参数")

    def test_compile_apply_never_redeploys_runner(self) -> None:
        """固化既有正确行为：compose.apply 的服务列表不含 upgrade-runner。"""
        from app.v2.upgrade.compiler import compile_execution_plan

        plan = compile_execution_plan(self._manifest()).to_dict()
        applies = [action for action in plan["actions"] if action["type"] == "compose.apply"]
        self.assertTrue(applies)
        for action in applies:
            self.assertNotIn("upgrade-runner", list(action["params"].get("services") or []))

    # ---------- web-api：编译前注入现场镜像 ----------

    def _service(self, tmpdir: str, field_image: str):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeService, UpgradeCommandExecutor

        project_dir = Path(tmpdir) / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        settings = V2Settings(
            data_root=Path(tmpdir), secret_key="us26-secret", app_version="v0.5.3",
            project_path_override=project_dir,
        )
        database = V2Database(settings)
        database.initialize()

        class FakeExecutor(UpgradeCommandExecutor):
            def output(self, command, cwd=None):
                return field_image

            def run(self, command, cwd=None):
                return None

        return UpgradeService(
            settings, TaskService(database), executor=FakeExecutor(), project_path=project_dir
        )

    def test_injects_field_runner_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir, "repo/upgrade-runner:v0.3.2")
            manifest = self._manifest()
            updated = service._inject_field_runner_image(manifest)
            runner = next(
                i for c in updated["components"] for i in c["images"] if i["service"] == "upgrade-runner"
            )
            self.assertEqual(runner["image"], "repo/upgrade-runner:v0.3.2")
            # 原 manifest 不得被就地修改（保持不可变，避免污染预检查等其它读方）
            original = next(
                i for c in manifest["components"] for i in c["images"] if i["service"] == "upgrade-runner"
            )
            self.assertEqual(original["image"], "repo/upgrade-runner:v0.3.1")

    def test_falls_back_to_package_baseline_when_field_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir, "")
            manifest = self._manifest()
            updated = service._inject_field_runner_image(manifest)
            runner = next(
                i for c in updated["components"] for i in c["images"] if i["service"] == "upgrade-runner"
            )
            self.assertEqual(runner["image"], "repo/upgrade-runner:v0.3.1", "取不到现场镜像须保留包内基线")

    def test_end_to_end_plan_keeps_field_runner_version(self) -> None:
        """编译期注入 → 计划 handoff 携带现场 v0.3.2（= 修复 US-26 的判别点）。"""
        from app.v2.upgrade.compiler import compile_execution_plan

        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir, "repo/upgrade-runner:v0.3.2")
            plan = compile_execution_plan(service._inject_field_runner_image(self._manifest())).to_dict()
            handoffs = self._handoffs(plan)
            self.assertTrue(handoffs, "计划应包含 handoff/cutover 动作")
            for action in handoffs:
                self.assertIn("v0.3.2", action["params"].get("image", ""))

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
            project_compose.write_text(compose, encoding="utf-8")
            runtime_compose = settings.compose_runtime_dir / "docker-compose.runner-upgrade.yml"
            runtime_compose.parent.mkdir(parents=True, exist_ok=True)
            runtime_compose.write_text(compose, encoding="utf-8")

            updated = service._sync_runner_image_into_compose_files("repo/upgrade-runner:v0.3.2")

            self.assertEqual(len(updated), 2)
            for path in (project_compose, runtime_compose):
                text = path.read_text(encoding="utf-8")
                self.assertIn("repo/upgrade-runner:v0.3.2", text)
                self.assertNotIn("v0.3.1", text)
                self.assertIn("repo/web-api:v0.5.3", text, "只应改 runner")

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
            project_compose.write_text(
                "services:\n  upgrade-runner:\n    image: repo/upgrade-runner:v0.3.1\n", encoding="utf-8"
            )
            first = service._sync_runner_image_into_compose_files("repo/upgrade-runner:v0.3.2")
            second = service._sync_runner_image_into_compose_files("repo/upgrade-runner:v0.3.2")
            self.assertEqual(len(first), 1)
            self.assertEqual(second, [], "已是目标 tag 时不应重复写入")
            self.assertIn("v0.3.2", project_compose.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
