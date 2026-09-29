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

    def _task(self, image: str, *, plan_image: str | None = None) -> dict:
        """构造任务。

        `plan_image` 模拟真实形态：落盘 manifest 仍是包内基线，**现场镜像只存在于执行计划**
        （web-api 的 `_inject_field_runner_image` 只注入编译用的计划，不回写落盘 manifest）。
        """
        manifest_image = "repo/upgrade-runner:v0.3.1" if plan_image else image
        task = {
            "task_id": "upgrade-1",
            "status": "running",
            "manifest": {
                "version": "v0.5.3",
                "components": [
                    {
                        "type": "platform",
                        "images": [
                            {"service": "upgrade-runner", "image": manifest_image, "archive": None},
                        ],
                    }
                ],
            },
        }
        if plan_image is not None:
            task["execution_plan"] = {
                "protocol_version": 1,
                "required_capabilities": [],
                "actions": [
                    {
                        "id": "schedule-runner-target-runtime-handoff",
                        "type": "runner.handoff.v1",
                        "status": "pending",
                        "attempt": 0,
                        "checkpoint": {},
                        "result": {},
                        "params": {"image": plan_image},
                    }
                ],
            }
        return task

    def test_plan_image_wins_over_stale_manifest(self) -> None:
        """判别：落盘 manifest 是基线 v0.3.1、计划里是现场 v0.3.2 → 必须用计划的。"""
        from app.upgrade_runner.actions import _runner_image_from_task

        task = self._task("repo/upgrade-runner:v0.3.2", plan_image="repo/upgrade-runner:v0.3.2")
        self.assertEqual(task["manifest"]["components"][0]["images"][0]["image"], "repo/upgrade-runner:v0.3.1")
        self.assertEqual(_runner_image_from_task(task), "repo/upgrade-runner:v0.3.2")

    def test_falls_back_to_compose_override_images(self) -> None:
        from app.upgrade_runner.actions import _runner_image_from_task

        task = self._task("repo/upgrade-runner:v0.3.2")
        task["execution_plan"] = {
            "protocol_version": 1,
            "required_capabilities": [],
            "actions": [
                {
                    "id": "write-compose-override",
                    "type": "compose.override",
                    "status": "pending",
                    "attempt": 0,
                    "checkpoint": {},
                    "result": {},
                    "params": {
                        "images": [
                            {"service": "web-api", "image": "repo/web-api:v0.5.3", "archive": "images/web-api.tar"},
                            {"service": "upgrade-runner", "image": "repo/upgrade-runner:v0.3.2", "archive": None},
                        ]
                    },
                }
            ],
        }
        self.assertEqual(_runner_image_from_task(task), "repo/upgrade-runner:v0.3.2")

    def test_falls_back_to_manifest_when_plan_absent(self) -> None:
        from app.upgrade_runner.actions import _runner_image_from_task

        self.assertEqual(_runner_image_from_task(self._task("repo/upgrade-runner:v0.3.2")), "repo/upgrade-runner:v0.3.2")
        self.assertEqual(_runner_image_from_task({}), "")
        self.assertEqual(_runner_image_from_task({"manifest": None}), "")
        self.assertEqual(_runner_image_from_task(None), "")

    # ---------- 判别用例 ----------

    def test_aligns_stale_baseline_tag_to_field_image(self) -> None:
        """平台升级把包内基线 v0.3.1 写回后，必须重新对齐到现场 v0.3.2。"""
        from app.upgrade_runner.actions import reconcile_project_runner_tag

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            context = self._context(root, "repo/upgrade-runner:v0.3.1")

            previous = reconcile_project_runner_tag(context, self._task("repo/upgrade-runner:v0.3.2", plan_image="repo/upgrade-runner:v0.3.2"))

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
            saved = self._task("repo/upgrade-runner:v0.3.2", plan_image="repo/upgrade-runner:v0.3.2")
            # 真实形态：落盘 manifest 是基线 v0.3.1，现场 v0.3.2 只在计划里
            saved["execution_plan"]["actions"].append(
                {"id": "noop", "type": "image.load", "status": "pending", "attempt": 0, "checkpoint": {}, "result": {}}
            )
            store.save(saved)

            result = UpgradeEngine(
                store,
                handlers={"image.load": handler, "runner.handoff.v1": handler},
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
            saved = self._task("repo/upgrade-runner:v0.3.2", plan_image="repo/upgrade-runner:v0.3.2")
            # 真实形态：落盘 manifest 是基线 v0.3.1，现场 v0.3.2 只在计划里
            saved["execution_plan"]["actions"].append(
                {"id": "noop", "type": "image.load", "status": "pending", "attempt": 0, "checkpoint": {}, "result": {}}
            )
            store.save(saved)

            result = UpgradeEngine(
                store,
                handlers={"image.load": lambda _a, _c: {"ok": True}, "runner.handoff.v1": lambda _a, _c: {"ok": True}},
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


class ComponentUpgradeTagWritebackTest(unittest.TestCase):
    """US-32 补洞：组件升级（web-api execute_task 收尾）也必须回写 compose tag。

    `.14` 实测：runner 组件升级成功后 `runner_version` 已是 v0.3.2，但
    `project/docker-compose.yml` 仍写 v0.3.1。根因是代码里**只有一句注释**
    （"compose tag 由 runner 在任务收尾时对齐"），而 runner 侧 engine 的对账
    只覆盖"runner 执行计划"的路径（平台升级）——组件升级由 web-api 收尾，那段对账
    从未执行。典型的"注释声称做了、代码没做"。
    """

    def test_component_upgrade_path_calls_writeback(self) -> None:
        import inspect

        from app.v2.upgrade.service import execution

        source = inspect.getsource(execution)
        self.assertIn(
            "_sync_runner_image_into_compose_files(runner_image)",
            source,
            "组件升级收尾必须调用 compose tag 回写",
        )
        # 不得再出现"由 runner 在任务收尾时对齐"这种把责任推给别人的注释
        self.assertNotIn(
            "compose tag 由 runner 在任务收尾时对齐",
            source,
            "组件升级由 web-api 收尾，不能声称由 runner 对齐",
        )

    def test_writeback_failure_is_logged_not_silent(self) -> None:
        """回写失败必须留痕（web-api 的 project 目录是只读挂载，可能失败）。"""
        import inspect

        from app.v2.upgrade.service import execution

        source = inspect.getsource(execution)
        self.assertIn("compose tag 回写未生效", source, "回写失败必须写进任务日志")

    def test_writeback_helper_warns_on_failure(self) -> None:
        """底层回写函数在只读挂载下必然失败，必须 warning 而非静默。"""
        from app.v2.upgrade.service.paths import PathsMixin

        import inspect as _inspect

        source = _inspect.getsource(PathsMixin._sync_runner_image_into_compose_files)
        self.assertIn("logging", source)
        self.assertIn("只读挂载", source, "必须点明只读挂载这一真实原因")
        self.assertNotIn("except OSError:\n                continue", source, "不得静默吞掉写入失败")
