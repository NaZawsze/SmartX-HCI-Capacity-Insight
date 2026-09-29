"""US-04：拦截"先升 runner、再升平台"这个会打断升级的顺序。

根因：目标布局机器上**原地**做 runner 组件升级时，v0.5.2 及更早的源端 web-api 会
**无条件** `compose stop upgrade-runner`——停掉的正是刚 `up -d` 起来的新 runner
（`.12` 两轮实测：启动后 10s SIGKILL、`exit=137`、心跳过期 → 后续预检查失败）。

源端镜像**改不到**（那是已发布版本），因此唯一可行的根治手段是**在预检查阶段拦截**，
把"不可行"变成"当场可读的错误"而不是"踩了之后排查半天"。
"""

from __future__ import annotations

import unittest


class _Settings:
    def __init__(self, app_version: str, compose_project_name: str = "smartx-hci-capacity-insight"):
        self.app_version = app_version
        self.compose_project_name = compose_project_name


def _component_manifest(*, target_project: str | None = "smartx-hci-capacity-insight", enabled: bool = True):
    return {
        "schema_version": "3",
        "package_type": "component",
        "version": "v0.3.2",
        "components": [{"type": "runner", "services": []}],
        "bootstrap_runner": {"enabled": enabled, "target_project": target_project},
    }


class RunnerFirstOrderGuardTest(unittest.TestCase):
    def _check(self, manifest, settings):
        from app.v2.upgrade.service.precheck import _check_runner_first_order

        return _check_runner_first_order(manifest, settings)

    # ---------- 拦截：老源端 + 原地升级 ----------

    def test_blocks_old_source_in_place_upgrade(self) -> None:
        """US-04 核心：v0.5.2 源端原地升 runner 必须被拦。"""
        result = self._check(_component_manifest(), _Settings("v0.5.2"))
        self.assertFalse(result["ok"], "老源端原地升级必须拦截")
        self.assertEqual(result["name"], "runner_first_order")
        self.assertIn("先升级平台", result["message"])
        self.assertIn("SIGKILL", result["message"], "消息应含实测症状，便于运维自查历史日志")

    def test_blocks_v051u2_source(self) -> None:
        result = self._check(_component_manifest(), _Settings("v0.5.1u2"))
        self.assertFalse(result["ok"], "v0.5.1u2 同样无守卫")

    # ---------- 放行：新源端已含守卫 ----------

    def test_allows_v053_source(self) -> None:
        """v0.5.3 源端已含同 project 守卫，原地升级安全。"""
        result = self._check(_component_manifest(), _Settings("v0.5.3"))
        self.assertTrue(result["ok"], "v0.5.3 源端已修（US-04 平台侧守卫），应放行")
        self.assertIn("守卫", result["message"])

    def test_allows_newer_source(self) -> None:
        result = self._check(_component_manifest(), _Settings("v0.5.4"))
        self.assertTrue(result["ok"])

    # ---------- 放行：非原地升级 ----------

    def test_allows_bridge_layout(self) -> None:
        """旧桥接布局（bootstrap 到不同 project）历来可行，不该拦。"""
        manifest = _component_manifest(target_project="smartx-storage-forecast")
        result = self._check(manifest, _Settings("v0.5.2"))
        self.assertTrue(result["ok"], "非原地升级无 US-04 风险")
        self.assertIn("非原地升级", result["message"])

    # ---------- 无关场景 ----------

    def test_ignores_non_bootstrap_component(self) -> None:
        """不涉及 runner bootstrap 的组件升级与本项无关。"""
        result = self._check(_component_manifest(enabled=False), _Settings("v0.5.2"))
        self.assertTrue(result["ok"])

    def test_message_is_actionable(self) -> None:
        """拦截消息必须可直接照做（告诉运维下一步做什么）。"""
        message = self._check(_component_manifest(), _Settings("v0.5.2"))["message"]
        self.assertIn("先升级平台", message)
        self.assertIn("后 runner", message)
        self.assertIn("无法修改", message, "应说明源端改不了，避免运维试图改镜像")


class RunnerFirstOrderWiringTest(unittest.TestCase):
    def test_guard_is_wired_into_precheck(self) -> None:
        import inspect

        from app.v2.upgrade.service import precheck

        source = inspect.getsource(precheck)
        self.assertIn("_check_runner_first_order", source, "守卫必须接入预检查主流程")
        # 必须只在 runner-only（组件升级）路径上调用
        self.assertIn("else:\n                # US-04", source.replace("\r\n", "\n"))


if __name__ == "__main__":
    unittest.main()
