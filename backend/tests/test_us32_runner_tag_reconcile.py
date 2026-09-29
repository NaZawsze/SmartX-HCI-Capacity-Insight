"""US-32：compose 里的 runner tag 必须与计划声明的现场镜像一致。

背景：US-26 想在 runner 组件升级后把新 tag 回写进 `project/docker-compose.yml`，但实现放在
web-api 侧，而 web-api 的 project 目录是**只读挂载**（`docker-compose.yml` 的 `:ro`），写入
必然抛 OSError 并被 `except OSError: continue` 吞掉 —— 该回写自实现起从未生效，compose 长期
停留在包内基线（实测 v0.3.1）而现场实际跑 v0.3.2，任何一次宿主侧 `docker compose up -d`
都会把 runner 静默降级。

回写职责已移到 runner：任务收尾时用计划里已注入的现场镜像对齐 tag。
判别用例：**不新增动作、不改能力集**（旧 runner 缺这段逻辑只是维持现状，不会让升级失败）。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

COMPOSE = (
    "services:\n"
    "  web-api:\n"
    "    image: repo/web-api:v0.5.3\n"
    "  upgrade-runner:\n"
    "    build:\n"
    "      context: .\n"
    "    image: {tag}\n"
    "    env_file:\n"
    "      - .env\n"
    "  prometheus:\n"
    "    image: repo/prometheus:v2.40.0\n"
)


class ReconcileProjectRunnerTagTest(unittest.TestCase):
    def _context(self, root: Path, tag: str):
        from app.upgrade_runner.actions import ActionContext

        project = root / "project"
        project.mkdir(parents=True, exist_ok=True)
        (project / "docker-compose.yml").write_text(COMPOSE.format(tag=tag), encoding="utf-8")
        return ActionContext.minimal(root, project_path=project)

    def _task(self, image: str) -> dict:
        return {
            "task_id": "upgrade-1",
            "status": "running",
            "manifest": {
                "version": "v0.5.3",
                "components": [
                    {
                        "type": "platform",
                        "images": [
                            {"service": "upgrade-runner", "image": image, "archive": None},
                        ],
                    }
                ],
            },
        }

    # ---------- 判别用例 ----------

    def test_aligns_stale_baseline_tag_to_field_image(self) -> None:
        """平台升级把包内基线 v0.3.1 写回后，必须重新对齐到现场 v0.3.2。"""
        from app.upgrade_runner.actions import reconcile_project_runner_tag

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            context = self._context(root, "repo/upgrade-runner:v0.3.1")

            previous = reconcile_project_runner_tag(context, self._task("repo/upgrade-runner:v0.3.2"))

            self.assertEqual(previous, "repo/upgrade-runner:v0.3.1")
            content = (context.project_path / "docker-compose.yml").read_text(encoding="utf-8")
            self.assertIn("image: repo/upgrade-runner:v0.3.2", content)
            self.assertNotIn("image: repo/upgrade-runner:v0.3.1", content)
            # 逐行状态机不能破坏 upgrade-runner 块内其它键，更不能误伤后面的服务
            self.assertIn("    build:\n", content)
            self.assertIn("      - .env\n", content)
            self.assertIn("image: repo/prometheus:v2.40.0", content)
            self.assertIn("image: repo/web-api:v0.5.3", content)

    def test_idempotent_when_already_aligned(self) -> None:
        from app.upgrade_runner.actions import reconcile_project_runner_tag

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            context = self._context(root, "repo/upgrade-runner:v0.3.2")
            before = (context.project_path / "docker-compose.yml").read_text(encoding="utf-8")

            self.assertEqual(reconcile_project_runner_tag(context, self._task("repo/upgrade-runner:v0.3.2")), "")
            self.assertEqual((context.project_path / "docker-compose.yml").read_text(encoding="utf-8"), before)

    def test_skips_when_manifest_has_no_runner_image(self) -> None:
        """post-cleanup 等任务没有 runner 条目 → 不得写任何东西。"""
        from app.upgrade_runner.actions import reconcile_project_runner_tag

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            context = self._context(root, "repo/upgrade-runner:v0.3.1")
            before = (context.project_path / "docker-compose.yml").read_text(encoding="utf-8")

            self.assertEqual(reconcile_project_runner_tag(context, {"manifest": {"package_type": "post_upgrade_cleanup"}}), "")
            self.assertEqual(reconcile_project_runner_tag(context, {}), "")
            self.assertEqual(reconcile_project_runner_tag(context, {"manifest": None}), "")
            self.assertEqual((context.project_path / "docker-compose.yml").read_text(encoding="utf-8"), before)

    def test_missing_compose_file_is_noop(self) -> None:
        from app.upgrade_runner.actions import reconcile_project_runner_tag

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            context = self._context(root, "repo/upgrade-runner:v0.3.1")
            (context.project_path / "docker-compose.yml").unlink()
            self.assertEqual(reconcile_project_runner_tag(context, self._task("repo/upgrade-runner:v0.3.2")), "")

    def test_write_failure_is_logged_not_swallowed(self) -> None:
        """只读挂载下写入失败必须留 warning —— 这正是旧实现长期静默失效的元凶。"""
        import logging

        from app.upgrade_runner.actions import reconcile_project_runner_tag

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            context = self._context(root, "repo/upgrade-runner:v0.3.1")
            compose = context.project_path / "docker-compose.yml"
            original = Path.write_text

            def boom(self, *args, **kwargs):
                if self == compose:
                    raise OSError(30, "Read-only file system")
                return original(self, *args, **kwargs)

            Path.write_text = boom
            try:
                with self.assertLogs("app.upgrade_runner.actions", level="WARNING") as captured:
                    result = reconcile_project_runner_tag(context, self._task("repo/upgrade-runner:v0.3.2"))
            finally:
                Path.write_text = original

            self.assertEqual(result, "")
            self.assertTrue(any("Read-only file system" in line for line in captured.output), captured.output)

    def test_engine_runs_reconcile_on_success(self) -> None:
        """判别：任务收尾自动对齐，无需任何调用方显式触发。"""
        from app.upgrade_runner.engine import UpgradeEngine
        from app.upgrade_runner.store import TaskStore

        def handler(_action, _context):
            return {"ok": True}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            context = self._context(root, "repo/upgrade-runner:v0.3.1")
            store = TaskStore(root / "upgrade-1")
            store.save(
                {
                    "task_id": "upgrade-1",
                    "status": "pending",
                    "manifest": self._task("repo/upgrade-runner:v0.3.2")["manifest"],
                    "execution_plan": {
                        "protocol_version": 1,
                        "required_capabilities": [],
                        "actions": [
                            {"id": "noop", "type": "image.load", "status": "pending", "attempt": 0, "checkpoint": {}, "result": {}}
                        ],
                    },
                }
            )

            result = UpgradeEngine(
                store,
                handlers={"image.load": handler},
                context={"action_context": context},
            ).run()

            self.assertEqual(result["status"], "success")
            content = (context.project_path / "docker-compose.yml").read_text(encoding="utf-8")
            self.assertIn("image: repo/upgrade-runner:v0.3.2", content)
            self.assertTrue(any("compose runner tag 已对齐" in line for line in result.get("logs", [])), result.get("logs"))

    def test_reconcile_failure_never_fails_the_task(self) -> None:
        """对账是善后动作：它坏了也不能把已经成功的升级判成失败。"""
        from app.upgrade_runner.engine import UpgradeEngine
        from app.upgrade_runner.store import TaskStore

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            context = self._context(root, "repo/upgrade-runner:v0.3.1")
            context.project_path = None  # 触发 AttributeError
            store = TaskStore(root / "upgrade-1")
            store.save(
                {
                    "task_id": "upgrade-1",
                    "status": "pending",
                    "manifest": self._task("repo/upgrade-runner:v0.3.2")["manifest"],
                    "execution_plan": {
                        "protocol_version": 1,
                        "required_capabilities": [],
                        "actions": [
                            {"id": "noop", "type": "image.load", "status": "pending", "attempt": 0, "checkpoint": {}, "result": {}}
                        ],
                    },
                }
            )

            result = UpgradeEngine(
                store,
                handlers={"image.load": lambda _a, _c: {"ok": True}},
                context={"action_context": context},
            ).run()

            self.assertEqual(result["status"], "success")
            self.assertTrue(any("runner tag 对账跳过" in line for line in result.get("logs", [])), result.get("logs"))

    def test_no_new_action_or_capability_required(self) -> None:
        """回写不得引入新动作或新能力集，否则旧 runner 会因能力不足而无法执行。"""
        from app.upgrade_runner.actions import default_handlers

        handlers = default_handlers()
        self.assertNotIn("compose.reconcile_runner_tag", handlers)
        # 能力集来源是动作表本身；断言表里没有为对账新增的动作类型
        types = {
            str(getattr(handler, "__module__", "")) for handler in handlers.values()
        }
        self.assertNotIn("app.upgrade_runner.actions.us32", types)


if __name__ == "__main__":
    unittest.main()
