"""W3：runner 自换组件升级。

工程规格：docs/superpowers/specs/2026-10-05-upgrade-architecture-v054-impl-spec.md §W3
用户 2026-10-05 追加的三条硬要求（全部有对应用例）：

a. `schedule_target_runtime_handoff` 必须是该任务执行路径里**最后一句可执行代码**
   ——它之后的代码不会执行；一切收尾走新 runner 启动路径。
b. 组件回滚锚点必须在 compose writeback **之前**捕获并存 task.json + 状态文件。
c. presence_wait 120s 是上限不是目标，正常自换 ~15s。

覆盖面：
- 哨兵机制（a）：handoff 后引擎不写任何状态；
- 锚点时序（b）：捕获早于 writeback，且锚点内容是**旧** tag/镜像 ID；
- 新 runner 收尾路径（a）：`self_handoff.scheduled` + 版本校验；
- 动作词汇冻结：平台升级计划不得出现 `component.*`；
- 旧编排路径保留（M3 格）。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.upgrade_runner import main as runner_main  # noqa: E402
from app.upgrade_runner.actions import (  # noqa: E402
    ActionContext,
    default_handlers,
    reconcile_project_runner_tag,
)
from app.upgrade_runner.engine import UpgradeEngine  # noqa: E402
from app.upgrade_runner.selfhandoff import (  # noqa: E402
    EXPECTED_HANDOFF_SECONDS,
    PRESENCE_WAIT_TIMEOUT_SECONDS,
    capture_component_rollback_anchor,
    component_handoff_finished,
    handoff_final_result,
    handoff_outcome_message,
    is_handoff_final,
    presence_reached_target,
)
from app.upgrade_runner.store import TaskStore  # noqa: E402

COMPOSE = """services:
  web-api:
    image: repo/web-api:v0.5.4
  upgrade-runner:
    image: {runner_image}
    restart: unless-stopped
  prometheus:
    image: prom/prometheus:v2.55.1
"""


class _Executor:
    """按命令前缀返回固定输出的假执行器（记录调用序列）。

    `containers` 形如 `[(容器 ID, compose project, RUNNER_VERSION 内容)]`，
    用来复现「同一 service 名、多个 project 并存」的真实场景。
    """

    def __init__(
        self,
        *,
        running_container: str = "",
        image_id: str = "",
        runner_version: str = "v0.3.1",
        containers: list[tuple[str, str, str]] | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self._running_container = running_container
        self._image_id = image_id
        self._runner_version = runner_version
        self._containers = containers or []

    def run(self, command: list[str], **_: Any) -> str:
        self.calls.append(list(command))
        return ""

    def output(self, command: list[str], **_: Any) -> str:
        self.calls.append(list(command))
        joined = " ".join(command)
        if "label=com.docker.compose.service=upgrade-runner" in joined:
            # 无 containers 列表时按旧式单容器参数返回（保持既有用例可读）
            if not self._containers:
                return (
                    f"{self._running_container} p\n" if self._running_container else ""
                )
            # 按传入的 filter 条件过滤（复现 docker ps 的真实语义）。
            # 注意 label 形如 `label=<key>=<value>`：要按**第二个** `=` 切，
            # 切第一个会得到 "com.docker.compose.project=<value>" 而匹配不上。
            wanted = ""
            for part in command:
                if part.startswith("label=com.docker.compose.project="):
                    wanted = part.split("=", 2)[2]
            rows = [item for item in self._containers if not wanted or item[1] == wanted]
            return "".join(f"{cid} {project}\n" for cid, project, _ in rows)
        if "/app/RUNNER_VERSION" in joined:
            if self._containers and "exec" in command:
                target = command[command.index("exec") + 1]
                for cid, _project, version in self._containers:
                    if cid.startswith(target[:12]):
                        return f"{version}\n"
            return f"{self._runner_version}\n"
        if "docker image inspect" in joined:
            return f"sha256:{self._image_id}\n"
        if "docker inspect" in joined and "--format" in joined:
            return f"sha256:{self._image_id}\n"
        return ""


def _context(tmp: Path, *, package: Path | None = None) -> ActionContext:
    return ActionContext(
        package_path=package or (tmp / "package"),
        project_path=tmp / "project",
        data_path=tmp,
        upgrades_path=tmp / "upgrades",
        backups_path=tmp / "backups",
        exports_path=tmp / "exports",
        compose_runtime_path=tmp / "compose-runtime",
        prometheus_path=tmp / "prometheus",
        compose_file="docker-compose.yml",
        compose_project="smartx-hci-capacity-insight",
        executor=_Executor(),
        task_id="upgrade-selfhandoff",
        target_version="v0.3.3",
    )


def _self_handoff_task(tmp: Path, *, target_version: str = "v0.3.3") -> dict[str, Any]:
    archive = tmp / "package" / "images" / "upgrade-runner.tar"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"fake-runner-image")
    return {
        "task_id": "upgrade-selfhandoff",
        "status": "pending",
        "target_version": target_version,
        "components": ["runner"],
        "package_path": str(tmp / "package"),
        "self_handoff": {"target_version": target_version, "previous_version": "v0.3.2"},
        "execution_plan": {
            "actions": [
                {
                    "id": "component-verify",
                    "type": "component.verify",
                    "params": {"archive": "images/upgrade-runner.tar", "sha256": ""},
                    "status": "pending",
                    "attempt": 0,
                    "checkpoint": {},
                    "result": {},
                },
                {
                    "id": "component-load",
                    "type": "component.image_load",
                    "params": {"archive": "images/upgrade-runner.tar", "image": "repo/runner:v0.3.3"},
                    "status": "pending",
                    "attempt": 0,
                    "checkpoint": {},
                    "result": {},
                },
                {
                    "id": "component-writeback",
                    "type": "component.compose_writeback",
                    "params": {"image": "repo/runner:v0.3.3"},
                    "status": "pending",
                    "attempt": 0,
                    "checkpoint": {},
                    "result": {},
                },
                {
                    "id": "component-handoff",
                    "type": "component.schedule_self_handoff",
                    "params": {"image": "repo/runner:v0.3.3", "compose_project": "smartx-hci-capacity-insight"},
                    "status": "pending",
                    "attempt": 0,
                    "checkpoint": {},
                    "result": {},
                },
            ]
        },
        "logs": [],
    }


class HandoffSentinelTests(unittest.TestCase):
    """硬要求 a：handoff 之后本进程不得再写任何状态。"""

    def test_sentinel_roundtrip(self) -> None:
        self.assertTrue(is_handoff_final(handoff_final_result(a=1)))
        self.assertFalse(is_handoff_final({"a": 1}))
        self.assertFalse(is_handoff_final(None))
        self.assertFalse(is_handoff_final("handoff_final"))

    def test_engine_stops_without_saving_after_handoff(self) -> None:
        """handoff 动作之后 task.json 的 revision 不得再增加。

        这正是 US-24 崩溃循环的机制：一边被 SIGKILL 一边保存，revision 与实际
        状态对不上，重启后再次保存必然冲突。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "upgrades" / "upgrade-selfhandoff")
            store.save(_self_handoff_task(root))

            seen: list[int] = []

            def verify(_action, _context):
                return {"ok": True}

            def load_image(_action, context):
                return {"ok": True}

            def writeback(_action, _context):
                return {"ok": True}

            def handoff(_action, _context):
                seen.append(int(TaskStore(root / "upgrades" / "upgrade-selfhandoff").load()["revision"]))
                return handoff_final_result(helper_container="cutover-1")

            final = UpgradeEngine(
                store,
                handlers={
                    "component.verify": verify,
                    "component.image_load": load_image,
                    "component.compose_writeback": writeback,
                    "component.schedule_self_handoff": handoff,
                },
                context={**_context(root).as_dict(), "database_path": str(root / "smartx.db")},
            ).run()
            after = TaskStore(root / "upgrades" / "upgrade-selfhandoff").load()

        self.assertEqual(len(seen), 1, "handoff 动作必须被调用一次")
        self.assertEqual(
            after["revision"],
            seen[0],
            "handoff 返回后不得再保存（revision 必须停在 handoff 调用那一刻）",
        )
        self.assertNotEqual(final["status"], "success", "handoff 后不得把任务置 success")

    def test_handoff_action_is_not_marked_succeeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "upgrades" / "upgrade-selfhandoff")
            store.save(_self_handoff_task(root))
            # 只留 handoff 一个动作：验证"引擎在它返回处停下"，不被前面动作的失败干扰
            task = store.load()
            task["execution_plan"]["actions"] = [
                action
                for action in task["execution_plan"]["actions"]
                if action["type"] == "component.schedule_self_handoff"
            ]
            store.save(task, expected_revision=int(task["revision"]))

            def handoff(_action, _context):
                return handoff_final_result()

            final = UpgradeEngine(
                store,
                handlers={"component.schedule_self_handoff": handoff},
                context=_context(root).as_dict(),
            ).run()
        handoff_action = next(
            action for action in final["execution_plan"]["actions"] if action["type"] == "component.schedule_self_handoff"
        )
        self.assertEqual(handoff_action["status"], "running")

    def test_scheduled_marker_is_persisted_before_handoff_runs(self) -> None:
        """硬要求 a 的前提：新 runner 必须能从 task.json 认出"该收尾了"。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "upgrades" / "upgrade-selfhandoff")
            store.save(_self_handoff_task(root))
            task = store.load()
            task["execution_plan"]["actions"] = [
                action
                for action in task["execution_plan"]["actions"]
                if action["type"] == "component.schedule_self_handoff"
            ]
            store.save(task, expected_revision=int(task["revision"]))
            observed: list[dict] = []

            def handoff(_action, _context):
                observed.append(TaskStore(root / "upgrades" / "upgrade-selfhandoff").load())
                return handoff_final_result()

            UpgradeEngine(
                store,
                handlers={"component.schedule_self_handoff": handoff},
                context=_context(root).as_dict(),
            ).run()
        self.assertEqual(len(observed), 1)
        handoff_state = observed[0].get("self_handoff") or {}
        self.assertTrue(handoff_state.get("scheduled"), "handoff 执行前必须已落盘 scheduled 标记")
        self.assertIn("scheduled_at", handoff_state)


class RollbackAnchorTests(unittest.TestCase):
    """硬要求 b：锚点必须在 writeback 之前捕获，且内容是**旧**值。"""

    def test_anchor_captures_previous_tag_and_image_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "project").mkdir(parents=True)
            (root / "project" / "docker-compose.yml").write_text(
                COMPOSE.format(runner_image="repo/runner:v0.3.2"), encoding="utf-8"
            )
            executor = _Executor(running_container="abc123", image_id="deadbeef")
            context = _context(root)
            context.executor = executor
            anchor = capture_component_rollback_anchor(
                context, {}, executor=executor, target_version="v0.3.3"
            )
        self.assertEqual(anchor["previous_version"], "v0.3.1")  # 读的是**运行中**容器
        self.assertEqual(anchor["previous_image_tag"], "repo/runner:v0.3.2")
        self.assertEqual(anchor["previous_image_id"], "sha256:deadbeef")
        self.assertEqual(anchor["container_id"], "abc123")
        self.assertEqual(anchor["target_version"], "v0.3.3")

    def test_anchor_uses_running_version_not_compose_tag(self) -> None:
        """compose 可能长期滞后于运行态（US-26/32 的多事实源现场）。

        组件回滚要退回的是**实际跑着的那个版本**，不是 compose 里写的那个。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "project").mkdir(parents=True)
            (root / "project" / "docker-compose.yml").write_text(
                COMPOSE.format(runner_image="repo/runner:v0.3.1"), encoding="utf-8"
            )
            executor = _Executor(running_container="abc", image_id="cafe", runner_version="v0.3.2")
            context = _context(root)
            context.executor = executor
            anchor = capture_component_rollback_anchor(
                context, {}, executor=executor, target_version="v0.3.3"
            )
        self.assertEqual(anchor["previous_version"], "v0.3.2")
        self.assertEqual(anchor["previous_image_tag"], "repo/runner:v0.3.1")

    def test_anchor_falls_back_to_tag_when_container_gone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "project").mkdir(parents=True)
            (root / "project" / "docker-compose.yml").write_text(
                COMPOSE.format(runner_image="repo/runner:v0.3.2"), encoding="utf-8"
            )
            executor = _Executor(running_container="", image_id="")
            context = _context(root)
            context.executor = executor
            anchor = capture_component_rollback_anchor(
                context, {}, executor=executor, target_version="v0.3.3"
            )
        self.assertEqual(anchor["previous_version"], "v0.3.2", "容器不可 exec 时应从 tag 推断，不留空")
        self.assertEqual(anchor["previous_image_id"], "")

    def test_incomplete_anchor_warns_but_does_not_raise(self) -> None:
        """锚点缺失只影响回滚能力，不该让组件升级整体失败。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "project").mkdir(parents=True)
            (root / "project" / "docker-compose.yml").write_text(
                "services:\n  web-api:\n    image: repo/web-api:v0.5.4\n", encoding="utf-8"
            )
            executor = _Executor()
            context = _context(root)
            context.executor = executor
            with self.assertLogs("app.upgrade_runner.selfhandoff", level="WARNING") as captured:
                anchor = capture_component_rollback_anchor(
                    context, {}, executor=executor, target_version="v0.3.3"
                )
        self.assertEqual(anchor["previous_image_tag"], "")
        self.assertTrue(any("锚点不完整" in message for message in captured.output))

    def test_anchor_injected_into_writeback_and_handoff_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "project").mkdir(parents=True)
            (root / "project" / "docker-compose.yml").write_text(
                COMPOSE.format(runner_image="repo/runner:v0.3.2"), encoding="utf-8"
            )
            task = _self_handoff_task(root)
            executor = _Executor(running_container="abc", image_id="dead", runner_version="v0.3.2")
            task = runner_main._inject_self_handoff_anchor(
                runner_main.RunnerSettings(
                    database_path=root / "smartx.db",
                    upgrades_path=root / "upgrades",
                    data_path=root,
                    exports_path=root / "exports",
                    backups_path=root / "backups",
                    compose_runtime_path=root / "compose-runtime",
                    prometheus_path=root / "prometheus",
                    project_path=root / "project",
                    compose_file="docker-compose.yml",
                    compose_project="smartx-hci-capacity-insight",
                    runner_version="v0.3.2",
                ),
                task,
                executor=executor,
            )
        actions = {action["type"]: action for action in task["execution_plan"]["actions"]}
        anchor = task["self_handoff"]["rollback_anchor"]
        self.assertEqual(actions["component.compose_writeback"]["params"]["rollback_anchor"], anchor)
        self.assertEqual(actions["component.schedule_self_handoff"]["params"]["rollback_anchor"], anchor)
        self.assertEqual(anchor["previous_image_tag"], "repo/runner:v0.3.2")

    def test_anchor_capture_is_idempotent(self) -> None:
        """恢复重跑时沿用第一次的锚点，不重复捕获（否则会读到 writeback 后的新 tag）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "project").mkdir(parents=True)
            (root / "project" / "docker-compose.yml").write_text(
                COMPOSE.format(runner_image="repo/runner:v0.3.2"), encoding="utf-8"
            )
            task = _self_handoff_task(root)
            task["self_handoff"]["rollback_anchor"] = {"previous_image_tag": "repo/runner:v0.3.2"}
            executor = _Executor()
            task = runner_main._inject_self_handoff_anchor(
                runner_main.RunnerSettings(
                    database_path=root / "smartx.db",
                    upgrades_path=root / "upgrades",
                    data_path=root,
                    exports_path=root / "exports",
                    backups_path=root / "backups",
                    compose_runtime_path=root / "compose-runtime",
                    prometheus_path=root / "prometheus",
                    project_path=root / "project",
                    compose_file="docker-compose.yml",
                    compose_project="smartx-hci-capacity-insight",
                    runner_version="v0.3.2",
                ),
                task,
                executor=executor,
            )
        self.assertEqual(executor.calls, [], "已有锚点时不应再探测")
        self.assertEqual(task["self_handoff"]["rollback_anchor"]["previous_image_tag"], "repo/runner:v0.3.2")

    def test_writeback_preserves_anchor_recorded_before_it(self) -> None:
        """端到端时序：先取锚点 → 再 writeback，锚点里必须还是旧 tag。"""
        handlers = default_handlers()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "project").mkdir(parents=True)
            compose_path = root / "project" / "docker-compose.yml"
            compose_path.write_text(COMPOSE.format(runner_image="repo/runner:v0.3.2"), encoding="utf-8")
            executor = _Executor(running_container="abc", image_id="oldimage", runner_version="v0.3.2")
            context = _context(root)
            context.executor = executor

            anchor = capture_component_rollback_anchor(
                context, {}, executor=executor, target_version="v0.3.3"
            )
            writeback = handlers["component.compose_writeback"](
                {
                    "type": "component.compose_writeback",
                    "params": {"image": "repo/runner:v0.3.3", "rollback_anchor": anchor},
                },
                context.as_dict(),
            )
            after = compose_path.read_text(encoding="utf-8")
        self.assertIn("repo/runner:v0.3.3", after, "writeback 应把 tag 改成目标版本")
        self.assertEqual(anchor["previous_image_tag"], "repo/runner:v0.3.2")
        self.assertEqual(writeback["previous_image_tag"], "repo/runner:v0.3.2")


class SelfHandoffActionTests(unittest.TestCase):
    def test_verify_rejects_missing_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = _self_handoff_task(root)
            import hashlib

            digest = hashlib.sha256((root / "package" / "images" / "upgrade-runner.tar").read_bytes()).hexdigest()
            handler = default_handlers()["component.verify"]
            with self.assertRaises(ValueError):
                handler({"params": {"archive": "images/upgrade-runner.tar", "sha256": ""}}, _context(root).as_dict())
            ok = handler(
                {"params": {"archive": "images/upgrade-runner.tar", "sha256": digest}},
                _context(root).as_dict(),
            )
        self.assertTrue(ok["checkpoint"]["verified"])
        self.assertEqual(ok["sha256"], digest)

    def test_verify_rejects_wrong_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _self_handoff_task(root)
            handler = default_handlers()["component.verify"]
            with self.assertRaises(ValueError):
                handler(
                    {"params": {"archive": "images/upgrade-runner.tar", "sha256": "0" * 64}},
                    _context(root).as_dict(),
                )

    def test_writeback_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "project").mkdir(parents=True)
            compose_path = root / "project" / "docker-compose.yml"
            compose_path.write_text(COMPOSE.format(runner_image="repo/runner:v0.3.3"), encoding="utf-8")
            handler = default_handlers()["component.compose_writeback"]
            result = handler(
                {"params": {"image": "repo/runner:v0.3.3"}}, _context(root).as_dict()
            )
        self.assertFalse(result["changed"])
        self.assertEqual(result["previous_image_tag"], "repo/runner:v0.3.3")

    def test_writeback_requires_image(self) -> None:
        handler = default_handlers()["component.compose_writeback"]
        with self.assertRaises(ValueError):
            handler({"params": {}}, _context(Path("/tmp")).as_dict())

    def test_schedule_self_handoff_refuses_without_anchor(self) -> None:
        """锚点缺失不得放行：writeback 之后旧 tag 已不可读，回滚能力会静默消失。"""
        handler = default_handlers()["component.schedule_self_handoff"]
        with self.assertRaises(ValueError) as caught:
            handler({"params": {"image": "repo/runner:v0.3.3"}}, _context(Path("/tmp")).as_dict())
        self.assertIn("回滚锚点", str(caught.exception))

    def test_self_handoff_delegates_and_keeps_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "project").mkdir(parents=True)
            (root / "project" / "docker-compose.yml").write_text(
                COMPOSE.format(runner_image="repo/runner:v0.3.2"), encoding="utf-8"
            )
            task = _self_handoff_task(root)
            store = TaskStore(root / "upgrades" / "upgrade-selfhandoff")
            store.save(task)
            handler = default_handlers()["component.schedule_self_handoff"]
            result = handler(
                {
                    "params": {
                        "image": "repo/runner:v0.3.3",
                        "compose_project": "smartx-hci-capacity-insight",
                        "network_name": "smartx-hci-capacity-insight-net",
                        "rollback_anchor": {"previous_image_tag": "repo/runner:v0.3.2"},
                    }
                },
                {**_context(root).as_dict(), "task": task, "task_mirror_dir": None},
            )
        self.assertTrue(is_handoff_final(result))
        self.assertEqual(result["rollback_anchor"]["previous_image_tag"], "repo/runner:v0.3.2")


class NewRunnerFinishTests(unittest.TestCase):
    """硬要求 a：新 runner 启动路径的收尾判定。"""

    def _settings(self, root: Path, runner_version: str) -> runner_main.RunnerSettings:
        return runner_main.RunnerSettings(
            database_path=root / "smartx.db",
            upgrades_path=root / "upgrades",
            data_path=root,
            exports_path=root / "exports",
            backups_path=root / "backups",
            compose_runtime_path=root / "compose-runtime",
            prometheus_path=root / "prometheus",
            project_path=root / "project",
            compose_file="docker-compose.yml",
            compose_project="smartx-hci-capacity-insight",
            runner_version=runner_version,
        )

    def test_scheduled_task_is_recognised(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task = _self_handoff_task(Path(tmp))
            task["status"] = "running"
            task["self_handoff"]["scheduled"] = True
            self.assertTrue(runner_main._is_self_handoff_scheduled(task))
            self.assertTrue(runner_main._is_self_handoff_task(task))

    def test_unscheduled_task_is_not_finished_early(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task = _self_handoff_task(Path(tmp))
            task["status"] = "running"
            self.assertFalse(runner_main._is_self_handoff_scheduled(task))

    def test_finished_status_is_not_treated_as_scheduled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task = _self_handoff_task(Path(tmp))
            task["status"] = "success"
            task["self_handoff"]["scheduled"] = True
            self.assertFalse(runner_main._is_self_handoff_scheduled(task))

    def test_legacy_orchestration_task_is_not_self_handoff(self) -> None:
        """M3 格：旧编排的组件任务不含 component.* 动作，不得被自换路径接管。"""
        with tempfile.TemporaryDirectory() as tmp:
            task = _self_handoff_task(Path(tmp))
            task["self_handoff"] = {}
            for action in task["execution_plan"]["actions"]:
                action["type"] = "runner.schedule_target_runtime_handoff"
            self.assertFalse(runner_main._is_self_handoff_task(task))
            self.assertFalse(runner_main._is_self_handoff_scheduled(task))

    def test_new_runner_finishes_only_when_version_matches_target(self) -> None:
        """旧 runner 轮询到"已调度 handoff"的任务时必须**跳过**，不得重跑计划。

        若继续执行会：再 load 一次镜像、再 writeback 一次、并**再调度一次 handoff**
        （多起一个 cutover 辅助容器）。这是实测发现的第三种竞态。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = _self_handoff_task(root, target_version="v0.3.3")
            task["status"] = "running"
            task["self_handoff"]["scheduled"] = True
            store = TaskStore(root / "upgrades" / "upgrade-selfhandoff")
            store.save(task)
            revision_before = int(store.load()["revision"])
            executed_old = runner_main.run_pending_once(
                self._settings(root, "v0.3.2"),
                handlers=default_handlers(),
                owner="runner-old",
            )
            untouched = TaskStore(root / "upgrades" / "upgrade-selfhandoff").load()
        self.assertEqual(executed_old, 0)
        self.assertEqual(untouched["status"], "running", "旧 runner 不得推进这条任务")
        self.assertEqual(
            int(untouched["revision"]), revision_before, "旧 runner 不得写这条任务（revision 不变）"
        )

    def test_new_runner_finishes_when_version_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "project").mkdir(parents=True)
            (root / "project" / "docker-compose.yml").write_text(
                COMPOSE.format(runner_image="repo/runner:v0.3.3"), encoding="utf-8"
            )
            task = _self_handoff_task(root, target_version="v0.3.3")
            task["status"] = "running"
            task["self_handoff"]["scheduled"] = True
            store = TaskStore(root / "upgrades" / "upgrade-selfhandoff")
            store.save(task)
            executed = runner_main.run_pending_once(
                self._settings(root, "v0.3.3"), handlers=default_handlers(), owner="runner-new"
            )
            finished = TaskStore(root / "upgrades" / "upgrade-selfhandoff").load()
        self.assertEqual(executed, 1)
        self.assertEqual(finished["status"], "success")
        self.assertFalse(runner_main._has_unfinished_steps(finished))


class PresenceObservationTests(unittest.TestCase):
    """硬要求 c：120s 是上限不是目标，正常 ~15s。"""

    def test_timeout_constant_is_120_seconds(self) -> None:
        self.assertEqual(PRESENCE_WAIT_TIMEOUT_SECONDS, 120)

    def test_expected_handoff_is_faster_than_timeout(self) -> None:
        self.assertLess(EXPECTED_HANDOFF_SECONDS, PRESENCE_WAIT_TIMEOUT_SECONDS)

    def test_handoff_finished_only_on_exact_version_match(self) -> None:
        self.assertTrue(component_handoff_finished({}, runner_version="v0.3.3", expected_version="v0.3.3"))
        self.assertFalse(component_handoff_finished({}, runner_version="v0.3.2", expected_version="v0.3.3"))
        self.assertFalse(component_handoff_finished({}, runner_version="", expected_version="v0.3.3"))
        self.assertFalse(component_handoff_finished({}, runner_version="v0.3.3", expected_version=""))

    def test_presence_requires_new_instance_for_same_version_handoff(self) -> None:
        """同版本重装场景：版本号相同但进程没换，不能算自换完成。"""
        state = {"runner_version": "v0.3.3", "instance_id": "runner-aaa"}
        self.assertFalse(presence_reached_target(state, target_version="v0.3.3", previous_instance_id="runner-aaa"))
        self.assertTrue(presence_reached_target(state, target_version="v0.3.3", previous_instance_id="runner-bbb"))
        self.assertTrue(presence_reached_target(state, target_version="v0.3.3"))

    def test_presence_rejects_wrong_version_and_missing_file(self) -> None:
        self.assertFalse(presence_reached_target(None, target_version="v0.3.3"))
        self.assertFalse(presence_reached_target({"runner_version": "v0.3.2"}, target_version="v0.3.3"))

    def test_outcome_message_flags_slow_handoff_but_does_not_fail_it(self) -> None:
        fast = handoff_outcome_message(waited_seconds=12.0, reached=True)
        slow = handoff_outcome_message(waited_seconds=40.0, reached=True)
        missed = handoff_outcome_message(waited_seconds=120.0, reached=False)
        self.assertIn("自换完成", fast)
        self.assertIn("超过预期", slow)
        self.assertIn("上限内", slow)
        self.assertIn("未在", missed)


class VocabularyFreezeTests(unittest.TestCase):
    """动作词汇冻结：平台升级计划不得出现自换新动作。"""

    def test_platform_plan_has_no_component_actions(self) -> None:
        from app.v2.upgrade.compiler import compile_execution_plan

        manifest = {
            "schema_version": "3",
            "version": "v0.5.4",
            "min_version": "v0.5.0",
            "package_type": "platform",
            "components": [
                {
                    "type": "platform",
                    "services": ["web-api", "collector-worker", "frontend", "prometheus"],
                    "images": [
                        {"service": "web-api", "image": "repo/web-api:v0.5.4", "archive": "images/web-api.tar"},
                    ],
                }
            ],
        }
        actions = {action.type for action in compile_execution_plan(manifest).actions}
        self.assertEqual(
            actions & runner_main.SELF_HANDOFF_ACTIONS,
            set(),
            "平台升级计划里不得出现自换动作（词汇冻结）",
        )

    def test_component_actions_are_new_only(self) -> None:
        """W3 只新增自换这四个动作；`post_upgrade.schedule_collection` 是 v0.3.2 早先就有的
        （已发布 v0.3.1 没有它，见 constants.RELEASED_RUNNER_ACTIONS 注释），不是本次新增。"""
        from app.upgrade_protocol.constants import RELEASED_RUNNER_ACTIONS

        handlers = set(default_handlers())
        added_by_w3 = {action for action in handlers if action.startswith("component.")}
        self.assertEqual(
            added_by_w3,
            {
                "component.verify",
                "component.image_load",
                "component.compose_writeback",
                "component.schedule_self_handoff",
            },
        )
        self.assertEqual(
            handlers - RELEASED_RUNNER_ACTIONS - added_by_w3,
            {"post_upgrade.schedule_collection"},
            "除自换四个之外不应有其他新增动作",
        )


class ComposeTagWritebackCompatTests(unittest.TestCase):
    """US-32 对账在自换时代的行为：已是目标 tag 时不得再动。"""

    def test_reconcile_returns_empty_when_already_aligned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "project").mkdir(parents=True)
            compose_path = root / "project" / "docker-compose.yml"
            compose_path.write_text(COMPOSE.format(runner_image="repo/runner:v0.3.3"), encoding="utf-8")
            task = {
                "execution_plan": {
                    "actions": [
                        {
                            "type": "runner.schedule_target_runtime_handoff",
                            "params": {"image": "repo/runner:v0.3.3"},
                        }
                    ]
                }
            }
            before = reconcile_project_runner_tag(_context(root), task)
            after = compose_path.read_text(encoding="utf-8")
        self.assertEqual(before, "")
        self.assertIn("repo/runner:v0.3.3", after)


class ProjectScopingTests(unittest.TestCase):
    """回归锁：同一 service 名、两个 project 并存时必须选中本 project 的容器。

    这条是 `.3` 实测事故的直接产物——锚点抓到了另一 project 的 runner，
    会让组件回滚换到不相干的版本。
    """

    def _compose(self, root: Path, tag: str = "repo/runner:v0.3.2") -> None:
        (root / "project").mkdir(parents=True, exist_ok=True)
        (root / "project" / "docker-compose.yml").write_text(
            COMPOSE.format(runner_image=tag), encoding="utf-8"
        )

    def test_two_projects_same_service_name_picks_current_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._compose(root)
            executor = _Executor(
                containers=[
                    ("aaaa111", "smartx-hci-capacity-insight", "v0.3.1"),
                    ("bbbb222", "w3selfhandoff", "v0.3.2"),
                ]
            )
            context = _context(root)
            context.compose_project = "w3selfhandoff"
            context.executor = executor
            anchor = capture_component_rollback_anchor(
                context, {}, executor=executor, target_version="v0.3.3"
            )
        self.assertEqual(anchor["container_id"], "bbbb222")
        self.assertEqual(anchor["previous_version"], "v0.3.2")

    def test_filter_includes_project_label(self) -> None:
        """探测命令必须带 project 过滤（这是修复本身，不只是结果断言）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._compose(root)
            executor = _Executor(containers=[("bbbb222", "w3selfhandoff", "v0.3.2")])
            context = _context(root)
            context.compose_project = "w3selfhandoff"
            context.executor = executor
            capture_component_rollback_anchor(context, {}, executor=executor, target_version="v0.3.3")
        ps_calls = [call for call in executor.calls if "docker" in call and "ps" in call]
        self.assertTrue(ps_calls, "应当调用过 docker ps")
        self.assertIn(
            "label=com.docker.compose.project=w3selfhandoff",
            ps_calls[0],
            "docker ps 必须带 project 过滤，否则会命中同机其它 project 的 runner",
        )

    def test_no_container_in_current_project_yields_empty_id(self) -> None:
        """本 project 下没有 runner 时留空并记 warning——绝不退回"抓别人的"。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._compose(root)
            executor = _Executor(containers=[("aaaa111", "smartx-hci-capacity-insight", "v0.3.1")])
            context = _context(root)
            context.compose_project = "w3selfhandoff"
            context.executor = executor
            with self.assertLogs("app.upgrade_runner.selfhandoff", level="WARNING") as captured:
                anchor = capture_component_rollback_anchor(context, {}, executor=executor, target_version="v0.3.3")
        self.assertEqual(anchor["container_id"], "")
        self.assertTrue(any("未找到 project" in message for message in captured.output))

    def test_same_project_multiple_containers_picks_stable_one(self) -> None:
        """--force-recreate 窗口内同 project 会有两个容器，取 ID 最小者保证稳定。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._compose(root)
            executor = _Executor(
                containers=[
                    ("cccc333", "w3selfhandoff", "v0.3.2"),
                    ("aaaa111", "w3selfhandoff", "v0.3.2"),
                ]
            )
            context = _context(root)
            context.compose_project = "w3selfhandoff"
            context.executor = executor
            first = capture_component_rollback_anchor(context, {}, executor=executor, target_version="v0.3.3")
            second = capture_component_rollback_anchor(context, {}, executor=executor, target_version="v0.3.3")
        self.assertEqual(first["container_id"], "aaaa111")
        self.assertEqual(first["container_id"], second["container_id"])


if __name__ == "__main__":
    unittest.main()