"""W4：compose diff 收敛（US-26 根治）。

工程规格：docs/superpowers/specs/2026-10-05-upgrade-architecture-v054-impl-spec.md §W4

三层防护：
1. **前置断言**：`compose.apply` 的服务列表含 `upgrade-runner` → 剔除 + warning；
2. **观测**：apply 前逐服务比对「运行容器镜像引用」与「计划期望镜像」，输出
   `将重建 / 未变更 / 未判定` 三段差异清单；apply 后再记一次**实际**重建结果；
3. **apply 后断言**：`upgrade-runner` 容器 ID 必须与 apply 前一致，变化即判失败。

期望镜像取自计划里的 `compose.override` 动作（编译器只给 `compose.apply` 传 `services`，
`backend/app/v2/upgrade/compiler.py:183`），不额外要求编译器改形状。

外加 W7 的禁令门禁：`--force-recreate` 不得出现在 `compose.apply` 路径里
（白名单与判定实现在 `scripts/verify_upgrade_plan_vocabulary.py`，测试直接复用，避免
门禁与单测两套规则分叉）。
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.upgrade_runner.actions import (  # noqa: E402
    APPLY_FORBIDDEN_SERVICES,
    ActionContext,
    compose_apply,
    default_handlers,
)

_spec = importlib.util.spec_from_file_location(
    "verify_upgrade_plan_vocabulary",
    REPO_ROOT / "scripts" / "verify_upgrade_plan_vocabulary.py",
)
assert _spec and _spec.loader
_vocabulary = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_vocabulary)

RUNNER = "upgrade-runner"
PROJECT = "smartx-hci-capacity-insight"


class _Executor:
    """记录命令、并按脚本返回 `docker ps` 结果的假执行器。"""

    def __init__(self, facts: dict[tuple[str, str], dict[str, str]] | None = None) -> None:
        self.commands: list[list[str]] = []
        self.facts = facts or {}

    def run(self, command: list[str], **_: Any) -> str:
        self.commands.append(list(command))
        return ""

    def output(self, command: list[str], **_: Any) -> str:
        self.commands.append(list(command))
        joined = " ".join(command)
        if not joined.startswith("docker ps"):
            return ""
        project = ""
        service = ""
        for part in command:
            if part.startswith("label=com.docker.compose.project="):
                project = part.split("=", 2)[2]
            if part.startswith("label=com.docker.compose.service="):
                service = part.split("=", 2)[2]
        if not service:
            return ""
        facts = self.facts.get((project, service))
        if not facts:
            return ""
        return (
            f"{facts.get('container_id','')} {facts.get('image_ref','')} "
            f"{facts.get('config_hash','')}\n"
        )


class _Swapper(_Executor):
    """apply 之后把指定服务的容器 ID 换掉（模拟 compose 真重建了它）。"""

    def __init__(
        self,
        facts: dict[tuple[str, str], dict[str, str]] | None = None,
        *,
        swap: tuple[str, ...] = (),
    ) -> None:
        super().__init__(facts)
        self.swap = set(swap)
        self.seen: dict[str, int] = {}

    def output(self, command: list[str], **_: Any) -> str:
        joined = " ".join(command)
        if joined.startswith("docker ps"):
            service = ""
            project = ""
            for part in command:
                if part.startswith("label=com.docker.compose.service="):
                    service = part.split("=", 2)[2]
                if part.startswith("label=com.docker.compose.project="):
                    project = part.split("=", 2)[2]
            if service in self.swap:
                self.seen[service] = self.seen.get(service, 0) + 1
                if self.seen[service] > 1:
                    base = self.facts.get((project, service), {})
                    return (
                        f"{base.get('container_id','')}-next {base.get('image_ref','')} "
                        f"{base.get('config_hash','')}\n"
                    )
        return super().output(command, **_)


def _context(root: Path, executor: Any, *, plan_images: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    """构造动作上下文 payload；`plan_images` 模拟计划里 `compose.override` 带的 images。"""
    context = ActionContext(
        package_path=root / "package",
        project_path=root / "project",
        data_path=root,
        upgrades_path=root / "upgrades",
        backups_path=root / "backups",
        exports_path=root / "exports",
        compose_runtime_path=root / "compose-runtime",
        prometheus_path=root / "prometheus",
        compose_file="docker-compose.offline.yml",
        compose_project=PROJECT,
        executor=executor,
        task_id="upgrade-diff",
    )
    payload = context.as_dict()
    if plan_images is not None:
        payload["task"] = {
            "task_id": context.task_id,
            "execution_plan": {
                "actions": [
                    {
                        "id": "write-compose-override",
                        "type": "compose.override",
                        "params": {
                            "images": [
                                {"service": service, "image": image}
                                for service, image in plan_images
                            ],
                            "services": [service for service, _ in plan_images],
                        },
                    }
                ]
            },
        }
    return payload


def _action(services: list[str], images: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    """构造 `compose.apply` 动作。

    `images` 只在「计划显式带 images」时出现；编译器真实产物里 `compose.apply` **没有**
    这个键（`compiler.py:183` 只传 `services`），因此默认为 None，保证主路径测试跑的
    就是真实形状。
    """
    params: dict[str, Any] = {"services": services}
    if images is not None:
        params["images"] = [{"service": service, "image": image} for service, image in images]
    return {"id": "apply-compose", "type": "compose.apply", "params": params}


def _facts(container_id: str, image_ref: str, config_hash: str = "h") -> dict[str, str]:
    return {
        "container_id": container_id,
        "image_ref": image_ref,
        "config_hash": config_hash,
    }


def _up_command(executor: _Executor) -> list[str]:
    return next(
        command for command in executor.commands if command[:2] == ["docker", "compose"] and "up" in command
    )


class ForbiddenServiceGuardTests(unittest.TestCase):
    """第 1 层：前置断言。"""

    def test_upgrade_runner_is_rejected_and_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            executor = _Executor()
            with self.assertLogs("app.upgrade_runner.actions", level="WARNING") as captured:
                result = compose_apply(
                    _action(["web-api", RUNNER, "prometheus"]),
                    _context(Path(tmp), executor, plan_images=[("web-api", "repo/web-api:v0.5.4")]),
                )
            up = _up_command(executor)
        self.assertEqual(result["services"], ["web-api", "prometheus"])
        self.assertEqual(result["rejected_services"], [RUNNER])
        self.assertNotIn(RUNNER, up, "剔除后的 up 命令里绝不能出现 upgrade-runner")
        self.assertTrue(any("剔除禁止触碰的服务" in message for message in captured.output))

    def test_runner_only_scope_becomes_empty_up(self) -> None:
        """整张计划只有 runner 时，宁可什么都不做，也不重建自己。"""
        with tempfile.TemporaryDirectory() as tmp:
            executor = _Executor()
            result = compose_apply(_action([RUNNER]), _context(Path(tmp), executor))
            up = _up_command(executor)
        self.assertEqual(result["services"], [])
        self.assertNotIn(RUNNER, up)

    def test_forbidden_set_is_exactly_the_runner(self) -> None:
        self.assertEqual(APPLY_FORBIDDEN_SERVICES, frozenset({RUNNER}))


class ExpectedImageSourceTests(unittest.TestCase):
    """期望镜像必须真的拿得到，否则第 2 层观测形同虚设。"""

    def test_expected_images_come_from_plan_override_action(self) -> None:
        """编译器真实形状：apply 无 images，靠计划里的 compose.override 动作。"""
        facts = {
            (PROJECT, "web-api"): _facts("aaa111", "repo/web-api:v0.5.4"),
            (PROJECT, "prometheus"): _facts("bbb222", "repo/prometheus:v2.0.0"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            result = compose_apply(
                _action(["web-api", "prometheus"]),
                _context(
                    Path(tmp),
                    _Executor(facts),
                    plan_images=[
                        ("web-api", "repo/web-api:v0.5.4"),
                        ("prometheus", "repo/prometheus:v3.0.0"),
                    ],
                ),
            )
        self.assertEqual(result["diff"]["will_rebuild"], ["prometheus"])
        self.assertEqual(result["diff"]["unchanged"], ["web-api"])
        self.assertEqual(result["diff"]["unknown"], [])

    def test_action_level_images_win(self) -> None:
        """动作自带 images（未来编译器或手工计划）时以它为准。"""
        facts = {(PROJECT, "web-api"): _facts("aaa111", "repo/web-api:v0.5.4")}
        with tempfile.TemporaryDirectory() as tmp:
            result = compose_apply(
                _action(["web-api"], [("web-api", "repo/web-api:v0.5.4")]),
                _context(Path(tmp), _Executor(facts), plan_images=[("web-api", "repo/web-api:v0.0.1")]),
            )
        self.assertEqual(result["diff"]["unchanged"], ["web-api"])

    def test_no_expected_image_anywhere_is_unknown_not_guess(self) -> None:
        facts = {(PROJECT, "web-api"): _facts("aaa111", "repo/web-api:v0.5.4")}
        with tempfile.TemporaryDirectory() as tmp:
            result = compose_apply(_action(["web-api"]), _context(Path(tmp), _Executor(facts)))
        self.assertEqual(result["diff"]["unknown"], ["web-api"])
        self.assertEqual(result["diff"]["will_rebuild"], [])


class DiffObservationTests(unittest.TestCase):
    """第 2 层：观测。只用 compose 自己的事实，不自研哈希。"""

    def test_changed_image_service_is_reported_as_will_rebuild(self) -> None:
        facts = {
            (PROJECT, "web-api"): _facts("aaa111", "repo/web-api:v0.5.3", "h1"),
            (PROJECT, "prometheus"): _facts("bbb222", "repo/prometheus:v3.0.0", "h2"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertLogs("app.upgrade_runner.actions", level="WARNING") as captured:
                result = compose_apply(
                    _action(["web-api", "prometheus"]),
                    _context(
                        Path(tmp),
                        _Executor(facts),
                        plan_images=[
                            ("web-api", "repo/web-api:v0.5.4"),
                            ("prometheus", "repo/prometheus:v3.0.0"),
                        ],
                    ),
                )
        self.assertEqual(result["diff"]["will_rebuild"], ["web-api"])
        self.assertEqual(result["diff"]["unchanged"], ["prometheus"])
        summary = next(m for m in captured.output if "差异清单" in m)
        self.assertIn("将重建=[web-api]", summary)
        self.assertIn("未变更=[prometheus]", summary)
        self.assertIn("upgrade-runner 不在作用域：是", summary)

    def test_missing_container_is_unknown_not_guessed(self) -> None:
        """容器没跑 → 归入「未判定」，绝不猜成"将重建"。"""
        with tempfile.TemporaryDirectory() as tmp:
            result = compose_apply(
                _action(["web-api"]),
                _context(Path(tmp), _Executor(), plan_images=[("web-api", "repo/web-api:v0.5.4")]),
            )
        self.assertEqual(result["diff"]["unknown"], ["web-api"])
        self.assertEqual(result["diff"]["will_rebuild"], [])

    def test_registry_prefix_difference_is_not_a_change(self) -> None:
        facts = {(PROJECT, "web-api"): _facts("aaa111", "docker.io/repo/web-api:v0.5.4")}
        with tempfile.TemporaryDirectory() as tmp:
            result = compose_apply(
                _action(["web-api"]),
                _context(Path(tmp), _Executor(facts), plan_images=[("web-api", "repo/web-api:v0.5.4")]),
            )
        self.assertEqual(result["diff"]["unchanged"], ["web-api"])

    def test_same_tag_different_repo_is_a_change(self) -> None:
        """tag 相同但仓库不同 → 必须判成将重建（防「同 tag 掩盖换镜像」）。"""
        facts = {(PROJECT, "web-api"): _facts("aaa111", "other/repo-web-api:v0.5.4")}
        with tempfile.TemporaryDirectory() as tmp:
            result = compose_apply(
                _action(["web-api"]),
                _context(Path(tmp), _Executor(facts), plan_images=[("web-api", "repo/web-api:v0.5.4")]),
            )
        self.assertEqual(result["diff"]["will_rebuild"], ["web-api"])

    def test_observation_failure_does_not_break_apply(self) -> None:
        """观测是 best-effort：`docker ps` 报错不得让 apply 失败。"""

        class Broken(_Executor):
            def output(self, command: list[str], **_: Any) -> str:
                if " ".join(command).startswith("docker ps"):
                    raise RuntimeError("docker 不可用")
                return super().output(command, **_)

        with tempfile.TemporaryDirectory() as tmp:
            executor = Broken()
            result = compose_apply(
                _action(["web-api"]),
                _context(Path(tmp), executor, plan_images=[("web-api", "repo/web-api:v0.5.4")]),
            )
            up = _up_command(executor)
        self.assertEqual(result["diff"]["unknown"], ["web-api"])
        self.assertIn("web-api", up, "观测失败也不能吞掉 apply 本身")

    def test_actual_rebuild_is_recorded_after_apply(self) -> None:
        """收敛证据：apply 后容器 ID 变没变要留痕，未变更服务不该被重建。"""
        facts = {
            (PROJECT, "web-api"): _facts("aaa111", "repo/web-api:v0.5.3"),
            (PROJECT, "prometheus"): _facts("bbb222", "repo/prometheus:v3.0.0"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            executor = _Swapper(
                facts,
                swap=("web-api",),
            )
            with self.assertLogs("app.upgrade_runner.actions", level="WARNING") as captured:
                result = compose_apply(
                    _action(["web-api", "prometheus"]),
                    _context(
                        Path(tmp),
                        executor,
                        plan_images=[
                            ("web-api", "repo/web-api:v0.5.4"),
                            ("prometheus", "repo/prometheus:v3.0.0"),
                        ],
                    ),
                )
        self.assertEqual(result["diff"]["will_rebuild"], ["web-api"])
        self.assertEqual(result["diff"]["actually_rebuilt"], ["web-api"])
        self.assertEqual(result["checkpoint"]["actual_summary"], result["diff"]["actual_summary"])
        self.assertIn("实际结果：重建=[web-api]", captured.output[-1])

    def test_actual_diff_is_not_an_assertion(self) -> None:
        """实际重建集合与预期不一致只记录、不判失败（compose 的权威是它自己的 config-hash）。"""
        facts = {(PROJECT, "web-api"): _facts("aaa111", "repo/web-api:v0.5.3")}
        with tempfile.TemporaryDirectory() as tmp:
            executor = _Swapper(facts, swap=("web-api",))
            result = compose_apply(
                _action(["web-api"]),
                _context(Path(tmp), executor, plan_images=[("web-api", "repo/web-api:v0.5.3")]),
            )
        self.assertEqual(result["diff"]["unchanged"], ["web-api"])
        self.assertEqual(result["diff"]["actually_rebuilt"], ["web-api"])


class RunnerPreservationAssertionTests(unittest.TestCase):
    """第 3 层：apply 后断言。"""

    def test_preserved_runner_is_reported(self) -> None:
        facts = {(PROJECT, RUNNER): _facts("runner-1", "repo/runner:v0.3.2")}
        with tempfile.TemporaryDirectory() as tmp:
            result = compose_apply(
                _action(["web-api"]),
                _context(Path(tmp), _Executor(facts), plan_images=[("web-api", "repo/web-api:v0.5.4")]),
            )
        self.assertEqual(result["upgrade_runner_container_id_before"], "runner-1")
        self.assertEqual(result["upgrade_runner_container_id_after"], "runner-1")
        self.assertTrue(result["checkpoint"]["upgrade_runner_preserved"])

    def test_changed_runner_container_fails_the_step(self) -> None:
        """容器 ID 变了 = 执行者在自己作用域内被重建 → 宁可失败不可静默降级。"""

        class Swapping(_Executor):
            def __init__(self) -> None:
                super().__init__({(PROJECT, RUNNER): _facts("runner-1", "repo/runner:v0.3.2")})
                self.calls = 0

            def output(self, command: list[str], **_: Any) -> str:
                joined = " ".join(command)
                if joined.startswith("docker ps") and RUNNER in joined:
                    self.calls += 1
                    if self.calls > 1:
                        return "runner-2 repo/runner:v0.3.1 h\n"
                return super().output(command, **_)

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as caught:
                compose_apply(
                    _action(["web-api"]),
                    _context(Path(tmp), Swapping(), plan_images=[("web-api", "repo/web-api:v0.5.4")]),
                )
        self.assertIn("upgrade-runner 容器发生变化", str(caught.exception))
        self.assertIn("runner-1", str(caught.exception))

    def test_vanished_runner_container_fails_the_step(self) -> None:
        class Vanishing(_Executor):
            def __init__(self) -> None:
                super().__init__({(PROJECT, RUNNER): _facts("runner-1", "repo/runner:v0.3.2")})
                self.calls = 0

            def output(self, command: list[str], **_: Any) -> str:
                joined = " ".join(command)
                if joined.startswith("docker ps") and RUNNER in joined:
                    self.calls += 1
                    if self.calls > 1:
                        return ""
                return super().output(command, **_)

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                compose_apply(
                    _action(["web-api"]),
                    _context(Path(tmp), Vanishing(), plan_images=[("web-api", "repo/web-api:v0.5.4")]),
                )

    def test_runner_absent_before_apply_does_not_raise(self) -> None:
        """apply 前 runner 就不存在（全新安装/已被停掉）→ 无从比较，不判失败。"""
        with tempfile.TemporaryDirectory() as tmp:
            result = compose_apply(
                _action(["web-api"]),
                _context(Path(tmp), _Executor(), plan_images=[("web-api", "repo/web-api:v0.5.4")]),
            )
        self.assertEqual(result["upgrade_runner_container_id_before"], "")
        self.assertFalse(result["checkpoint"]["upgrade_runner_preserved"])


class ForceRecreateBanTests(unittest.TestCase):
    """W4 禁令：平台升级路径不得引入 `--force-recreate`（判定复用 W7 门禁实现）。"""

    def test_gate_allowlist_is_exactly_three_paths(self) -> None:
        self.assertEqual(
            _vocabulary.FORCE_RECREATE_ALLOWED,
            frozenset(
                {
                    "runner_handoff_target_runtime",
                    "component_schedule_self_handoff",
                    "runner_schedule_target_runtime_handoff",
                    "RUNNER_CUTOVER_HELPER_SCRIPT",
                    "rollback_restore",
                }
            ),
        )

    def test_repo_has_no_force_recreate_outside_allowlist(self) -> None:
        verdict = _vocabulary.check_force_recreate_ban()
        self.assertEqual(verdict["status"], "PASS", verdict["detail"])

    def test_compose_apply_has_no_force_recreate(self) -> None:
        source = (ROOT / "app" / "upgrade_runner" / "actions.py").read_text(encoding="utf-8")
        body = source.split("def compose_apply", 1)[1].split("\ndef ", 1)[0]
        self.assertNotIn(
            "--force-recreate",
            body,
            "compose.apply 不得引入 --force-recreate（会重建未变更服务，US-26 的形态）",
        )

    def test_compiler_keeps_runner_out_of_apply_services(self) -> None:
        """第 1 层的上游保证：编译器就不该把 runner 放进 apply 作用域。"""
        source = (REPO_ROOT / "backend" / "app" / "v2" / "upgrade" / "compiler.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('apply_services = [service for service in services if service != "upgrade-runner"]', source)

    def test_handler_table_still_registers_compose_apply(self) -> None:
        self.assertIn("compose.apply", default_handlers())


if __name__ == "__main__":
    unittest.main()
