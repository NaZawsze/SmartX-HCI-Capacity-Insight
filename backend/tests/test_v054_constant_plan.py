"""B5b / W6：v0.5.4 常量计划断言 + 退役登记（防编译器回归）。

## 锁的是什么

**动作集合**（不是步数）。七步是设计里的流程分组
（backup → load → sync → swap → health → verify → checkpoint），
一个分组可以对应多个动作（`image.load` 三份镜像、`health.*` 两个探针），
所以测试锁集合与"不该出现的集合"，不锁数字。

## 为什么锁集合

收窄支持矩阵（v0.5.4 只支持目标布局 v0.5.2+）之后，
`directory_transition` 与 `legacy_cleanup` 为空，编译出的计划应当是常量形状。
一旦有人给 v0.5.4 重新加回迁移/交接/legacy 声明，计划会静默长出
`compose.project_migrate` / `filesystem.prepare` / `task.*_runtime_state` /
`post_upgrade.schedule_cleanup` / `runner.*` / `legacy.cleanup` —— 这些动作正是
US-26 一类事故的高发区（旧布局交接必须按包内基线重建 runner，静默降级现场更高版本）。
本文件就是那道锁。
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

from app.upgrade_runner.actions import default_handlers  # noqa: E402
from app.upgrade_runner.rollback import is_rollback_trigger, rollback_on_failure_enabled  # noqa: E402
from app.v2.upgrade.compiler import compile_execution_plan  # noqa: E402

_spec = importlib.util.spec_from_file_location("build_upgrade_package", REPO_ROOT / "scripts" / "build_upgrade_package.py")
assert _spec and _spec.loader
_builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_builder)

TARGET = "v0.5.4"

#: v0.5.4 计划**必须**出现的动作（平台包，platform-only 组件）。
REQUIRED_ACTIONS = {
    "backup.create",
    "image.load",
    "files.sync",
    "compose.override",
    "compose.apply",
    "health.http",
}
#: 带 observability 组件（bundle 包）时额外出现。
OBSERVABILITY_ACTIONS = {"health.prometheus"}
#: v0.5.4 计划**绝不**出现的动作：迁移 / 交接 / 清理 / 平台侧采集。
FORBIDDEN_ACTIONS = {
    "compose.project_migrate",
    "filesystem.prepare",
    "task.migrate_runtime_state",
    "task.sync_runtime_state",
    "runner.handoff_target_runtime",
    "runner.schedule_target_runtime_handoff",
    "runner.stop_legacy_runtime",
    "legacy.cleanup",
    "compose.stop_legacy_project",
    "network.remove_legacy",
    "filesystem.cleanup_legacy_paths",
    "filesystem.cleanup_target_app_residuals",
    "post_cleanup.precheck_target_health",
    "post_cleanup.verify",
    "post_upgrade.schedule_cleanup",
    "post_upgrade.schedule_collection",
}


def _manifest(
    *,
    observability: bool = False,
    project_files: bool = True,
    migration_required: bool = False,
) -> dict[str, Any]:
    components: list[dict[str, Any]] = [
        {
            "type": "platform",
            "services": ["web-api", "collector-worker", "frontend"],
            "images": [
                {
                    "service": service,
                    "image": f"nazawsze/smartx-hci-capacity-insight-{service}:{TARGET}",
                    "archive": f"images/{service}.tar",
                    "sha256": "0" * 64,
                }
                for service in ("web-api", "collector-worker", "frontend")
            ],
        }
    ]
    if observability:
        components.append(
            {
                "type": "observability",
                "services": ["prometheus"],
                "images": [
                    {
                        "service": "prometheus",
                        "image": f"nazawsze/smartx-hci-capacity-insight-prometheus:{TARGET}",
                        "archive": "images/prometheus.tar",
                        "sha256": "1" * 64,
                    }
                ],
            }
        )
    manifest: dict[str, Any] = {
        "schema_version": "3",
        "version": TARGET,
        "package_type": "platform",
        "components": components,
        # B5b：v0.5.4 不声明目录迁移与 legacy 清理（打包侧已收窄，这里如实反映产物形状）。
        "environment_transitions": [],
        "directory_transition": {},
        "legacy_cleanup": {},
        "post_upgrade": _builder._post_upgrade(
            target_version=TARGET, legacy_cleanup=_builder._legacy_cleanup(target_version=TARGET)
        ),
        "source_compatibility": _builder._source_compatibility(min_version="v0.5.0", target_version=TARGET),
    }
    if project_files:
        manifest["project_files"] = True
        manifest["project_source"] = "project"
        manifest["project_file_list"] = ["docker-compose.offline.yml", "compose-guard.sh"]
    if migration_required:
        manifest["migration"] = {
            "required": True,
            "image_service": "web-api",
            "runner": "migrations/run_migrations.py",
            "runner_sha256": "2" * 64,
            "post_check": "PRAGMA integrity_check",
        }
    return manifest


class SupportMatrixNarrowingTests(unittest.TestCase):
    """收窄支持矩阵：旧布局先升 v0.5.3，再升 v0.5.4。"""

    def test_effective_min_version_is_raised_for_v054(self) -> None:
        self.assertEqual(_builder._effective_min_version("v0.5.0", TARGET), "v0.5.2")
        self.assertEqual(_builder._effective_min_version("v0.5.1u2", TARGET), "v0.5.2")

    def test_older_targets_keep_their_wide_matrix(self) -> None:
        """v0.5.3 及更早**不受影响**：仍支持 v0.5.0/v0.5.1u2 直升。"""
        for target in ("v0.5.2", "v0.5.3"):
            self.assertEqual(_builder._effective_min_version("v0.5.0", target), "v0.5.0", target)
        supported = _builder._supported_source_versions("v0.5.0", "v0.5.3")
        self.assertEqual(
            supported, ["v0.5.0", "v0.5.1", "v0.5.1u1", "v0.5.1u2", "v0.5.2", "v0.5.3"]
        )

    def test_supported_sources_are_target_layout_only(self) -> None:
        supported = _builder._supported_source_versions("v0.5.0", TARGET)
        self.assertEqual(supported, ["v0.5.2", "v0.5.3", TARGET])
        for legacy in ("v0.5.0", "v0.5.1", "v0.5.1u1", "v0.5.1u2"):
            self.assertNotIn(legacy, supported, f"{legacy} 必须先升 v0.5.3")

    def test_no_environment_transition_or_directory_or_legacy_cleanup(self) -> None:
        self.assertEqual(_builder._environment_transitions(min_version="v0.5.0", target_version=TARGET), [])
        self.assertEqual(_builder._directory_transition(target_version=TARGET), {})
        self.assertEqual(_builder._legacy_cleanup(target_version=TARGET), {})

    def test_post_upgrade_collection_survives_the_narrowing(self) -> None:
        """收窄不能把「升级后自动采集」这个已发布特性关掉（49-49 platform_collection）。"""
        post_upgrade = _builder._post_upgrade(target_version=TARGET, legacy_cleanup={})
        self.assertTrue(post_upgrade.get("platform_collection"))
        self.assertFalse(post_upgrade.get("auto_collection"), "auto_collection 必须保持 False（旧编译器会据此下发 schedule_collection）")
        self.assertNotIn("create_cleanup_task", post_upgrade, "没有 legacy 就没有 post-cleanup 任务")


class ApplyServiceScopeTests(unittest.TestCase):
    """r21：`components[].services` 必须把 prometheus 排除在 apply 集合之外。

    2026-10-06 `.14` C1'' 实测：平台包升级**不改变** prometheus（镜像清单里没有它、
    `compose.override` 也不为它写段），但它出现在服务清单里就会被编译器派生成
    `compose.apply` 的服务集合，于是 `docker compose up` 按 config-hash 比对
    **重建了 prometheus**（T3 判据不过）。而 config-hash 是 compose **版本相关**的
    算法（实测 v2.26.1-4 与 v5.1.4 对同一份 compose 算出不同值），容器永久携带
    创建者版本的 hash，apply 用的却是 runner 镜像内置的 compose → 版本不一致必然重建。

    健康门不受影响：平台包的健康门是 `health.http` → `/api/system/health`，
    其 `checks.prometheus` 真探活；平台包从来没有 `health.prometheus` 动作。
    """

    APPLY_SERVICES = ["collector-worker", "frontend", "web-api"]

    def _apply_services(self, manifest: dict[str, Any]) -> list[str]:
        for action in compile_execution_plan(manifest).actions:
            if action.type == "compose.apply":
                return sorted(action.params.get("services") or [])
        raise AssertionError("计划里没有 compose.apply 动作")

    def _platform_manifest(self) -> dict[str, Any]:
        return _manifest()

    def test_builder_excludes_prometheus_from_component_services(self) -> None:
        """裁剪的是 prometheus；`upgrade-runner` 必须**留在**清单里。

        它留在 `components[].services` 是必需的：`compose.override` 靠它把 runner 的
        tag 钉在已发布基线上（US-26 的防线之一）；编译器在派生 `compose.apply` 时才
        剔除它（`compiler.py:53`）。
        """
        services = _builder._apply_services_for_version(TARGET)
        self.assertNotIn("prometheus", services)
        self.assertIn("upgrade-runner", services)
        self.assertEqual(sorted(s for s in services if s != "upgrade-runner"), self.APPLY_SERVICES)

    def test_restart_services_still_lists_everything(self) -> None:
        """`restart_services` 是"影响服务"的展示口径，不该被裁剪。"""
        full = _builder._platform_services_for_version(TARGET)
        self.assertIn("prometheus", full)
        self.assertIn("upgrade-runner", full)

    def test_apply_services_from_full_manifest_exclude_prometheus(self) -> None:
        manifest = self._platform_manifest()
        manifest["components"][0]["services"] = _builder._apply_services_for_version(TARGET)
        self.assertEqual(self._apply_services(manifest), self.APPLY_SERVICES)

    def test_putting_prometheus_back_would_reintroduce_the_recreate(self) -> None:
        """反向证明：prometheus 回到服务清单 ⇒ 它就回到 apply 集合（T3 失效的机制）。"""
        manifest = self._platform_manifest()
        manifest["components"][0]["services"] = _builder._platform_services_for_version(TARGET)
        self.assertIn("prometheus", self._apply_services(manifest))

    def test_platform_package_has_no_prometheus_health_action(self) -> None:
        """裁剪不得顺手删掉健康门——平台包的健康门本来只有 health.http。"""
        types = [action.type for action in compile_execution_plan(self._platform_manifest()).actions]
        self.assertIn("health.http", types)
        self.assertNotIn("health.prometheus", types)

    def test_action_sequence_length_unchanged(self) -> None:
        """动作**类型集合**不变，且序列长度仍是 8（image.load 按镜像数出现 3 次）。"""
        plan = compile_execution_plan(self._platform_manifest())
        self.assertEqual({action.type for action in plan.actions}, REQUIRED_ACTIONS)
        self.assertEqual(len(plan.actions), 8, [action.type for action in plan.actions])


class ConstantPlanActionSetTests(unittest.TestCase):
    """锁动作集合（不是步数）。"""

    def _types(self, manifest: dict[str, Any]) -> list[str]:
        return [action.type for action in compile_execution_plan(manifest).actions]

    def test_platform_package_action_set_is_exact(self) -> None:
        types = set(self._types(_manifest()))
        self.assertEqual(types, REQUIRED_ACTIONS, f"实际={sorted(types)}")

    def test_bundle_package_adds_prometheus_health_only(self) -> None:
        types = set(self._types(_manifest(observability=True)))
        self.assertEqual(types, REQUIRED_ACTIONS | OBSERVABILITY_ACTIONS, f"实际={sorted(types)}")

    def test_each_source_version_cell_compiles_to_the_same_set(self) -> None:
        """偏斜矩阵每一格编译结果一致（编译器已退化为常量模板）。"""
        supported = _builder._supported_source_versions("v0.5.0", TARGET)
        baseline = set(self._types(_manifest()))
        for source in supported:
            with self.subTest(source=source):
                manifest = _manifest()
                manifest["source_compatibility"] = {
                    **manifest["source_compatibility"],
                    "supported_versions": [source],
                }
                self.assertEqual(set(self._types(manifest)), baseline)

    def test_no_forbidden_action_is_emitted(self) -> None:
        for observability in (False, True):
            with self.subTest(observability=observability):
                emitted = set(self._types(_manifest(observability=observability)))
                leaked = sorted(emitted & FORBIDDEN_ACTIONS)
                self.assertEqual(leaked, [], f"v0.5.4 计划泄漏了迁移/交接/清理动作：{leaked}")

    def test_migration_required_does_not_break_the_constant_shape(self) -> None:
        """有 schema 迁移时只多一个沙箱脚本动作（SQLite 迁移走沙箱，不是 legacy 迁移）。"""
        types = set(self._types(_manifest(migration_required=True)))
        self.assertEqual(types, REQUIRED_ACTIONS | {"script.run_sandboxed"})
        # 布局迁移 / 交接 / legacy 清理一个都不许出现
        self.assertEqual(sorted(types & FORBIDDEN_ACTIONS), [])

    def test_files_sync_is_present_because_project_files_are_declared(self) -> None:
        """丢掉 files.sync 会让磁盘 compose 停在旧 tag（A6 守卫脚本也投递不到）。"""
        self.assertIn("files.sync", set(self._types(_manifest())))
        self.assertNotIn("files.sync", set(self._types(_manifest(project_files=False))))

    def test_image_load_appears_once_per_image_with_archive(self) -> None:
        types = self._types(_manifest())
        self.assertEqual(types.count("image.load"), 3)

    def test_collection_is_platform_side_not_a_plan_action(self) -> None:
        """49-49：升级后自动采集由平台侧调度，编译计划**不得**下发 schedule_collection。"""
        emitted = set(self._types(_manifest()))
        self.assertNotIn("post_upgrade.schedule_collection", emitted)
        self.assertNotIn("post_upgrade.schedule_cleanup", emitted)
        # runner 仍实现这两个动作：老桥接场景（v0.5.3 及更早的计划）仍会下发
        self.assertIn("post_upgrade.schedule_collection", default_handlers())
        self.assertIn("post_upgrade.schedule_cleanup", default_handlers())


class RollbackTriggerOptInTests(unittest.TestCase):
    """A5b 触发面开关：v0.5.4+ 包必须显式声明，否则 compose.apply/post_upgrade 失败不会回滚。"""

    def test_v054_manifest_opts_in(self) -> None:
        # 与 build_package 里的写入条件保持一致（目标 ≥ TARGET_LAYOUT_FLOOR_VERSION）
        self.assertTrue(_builder._version_tuple(TARGET) >= _builder._version_tuple(_builder.TARGET_LAYOUT_FLOOR_VERSION))
        self.assertTrue(rollback_on_failure_enabled({"manifest": {"rollback_on_failure": True}}))
        self.assertFalse(rollback_on_failure_enabled({"manifest": {"version": TARGET}}))

    def test_precheck_would_not_opt_in_without_the_flag(self) -> None:
        """缺这个键时新触发面不生效——所以它必须在打包侧显式写出来，不能靠默认。"""
        self.assertFalse(rollback_on_failure_enabled({"manifest": _source_compatibility_without_flag()}))
        self.assertTrue(is_rollback_trigger("compose.apply"))
        self.assertTrue(is_rollback_trigger("post_upgrade.schedule_collection"))


def _source_compatibility_without_flag() -> dict:
    return {
        "min_version": "v0.5.2",
        "max_version_inclusive": TARGET,
        "target_version": TARGET,
        "supported_versions": ["v0.5.2", "v0.5.3", TARGET],
    }


class VocabularyTests(unittest.TestCase):
    """v0.5.4 计划的动作必须全部是 runner 已实现的动作（W7.1 的前置条件）。"""

    def test_every_emitted_action_has_a_handler(self) -> None:
        handlers = default_handlers()
        for observability in (False, True):
            for action in compile_execution_plan(_manifest(observability=observability)).actions:
                self.assertIn(action.type, handlers, action.type)

    def test_retired_actions_stay_in_the_handler_table_for_legacy_bridges(self) -> None:
        """退役的是「v0.5.4 计划里的位置」，不是动作实现——老桥接计划仍会下发它们。"""
        handlers = default_handlers()
        for action_type in (
            "filesystem.prepare",
            "task.migrate_runtime_state",
            "task.sync_runtime_state",
            "compose.project_migrate",
            "runner.handoff_target_runtime",
            "legacy.cleanup",
        ):
            self.assertIn(action_type, handlers, action_type)


if __name__ == "__main__":
    unittest.main()