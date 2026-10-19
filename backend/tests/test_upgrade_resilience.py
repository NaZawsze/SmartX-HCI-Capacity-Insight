"""#94-B / #96：组件升级的平台下限与 runner 心跳可观测性。

背景（`.12`/`.14` 全链路重测）：
- **#94**：v0.5.2 及更早的 web-api 在原地做组件升级时会无条件 stop 掉刚启动的新 runner
  （SIGKILL + handoff 死循环），之后所有平台升级都被「未检测到心跳」拒绝。旧镜像改不到，
  所以让组件包声明 `minimum_platform_version`，由新平台在**收包阶段**拦截（覆盖 Web 路径）。
- **#96**：cutover 失败后 runner 心跳循环静默死亡，容器仍 Up、平台只报「未检测到心跳」，
  现场无法区分。修复是「实例心跳看门狗（与任务执行解耦）+ 容器 healthcheck + 文案带容器状态」。
"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]


class ComponentPlatformCheckTests(unittest.TestCase):
    def _check(self, manifest: dict, current: str) -> dict:
        from app.v2.upgrade.service.precheck import _check_component_platform

        return _check_component_platform(manifest, current)

    def test_blocked_on_old_platform(self) -> None:
        check = self._check({"minimum_platform_version": "v0.5.3"}, "v0.5.2")
        self.assertFalse(check["ok"])
        self.assertEqual(check["name"], "component_platform")
        self.assertIn("先升级平台", check["message"])
        self.assertEqual(check["detail"]["minimum_platform_version"], "v0.5.3")

    def test_passes_on_supported_platform(self) -> None:
        for version in ("v0.5.3", "v0.5.4", "v0.5.5"):
            check = self._check({"minimum_platform_version": "v0.5.3"}, version)
            self.assertTrue(check["ok"], (version, check["message"]))

    def test_missing_field_keeps_old_behaviour(self) -> None:
        check = self._check({}, "v0.5.2")
        self.assertTrue(check["ok"])
        self.assertIn("未声明", check["message"])

    def test_component_package_declares_minimum_platform(self) -> None:
        """组件包构建脚本必须写出该字段（否则 #94-B 形同虚设）。"""
        text = (ROOT / "scripts" / "build_runner_component_package.py").read_text(encoding="utf-8")
        self.assertIn("minimum_platform_version", text)
        self.assertIn("MINIMUM_PLATFORM_VERSION = 'v0.5.3'", text)


class RunnerHeartbeatWatchdogTests(unittest.TestCase):
    def test_main_starts_instance_heartbeat_thread(self) -> None:
        """实例心跳必须与任务执行解耦：`main()` 里要有独立守护线程持续刷心跳。"""
        text = (ROOT / "backend" / "app" / "upgrade_runner" / "main.py").read_text(encoding="utf-8")
        self.assertIn("runner-instance-heartbeat", text)
        self.assertIn("update_runner_state(settings.runner_version)", text)
        self.assertIn("daemon=True", text)
        # 收尾必须停线程，避免测试/退出时泄漏
        self.assertIn("stop_heartbeat.set()", text)

    def test_upgrade_runner_container_has_healthcheck(self) -> None:
        for name in ("docker-compose.dev.yml", "docker-compose.offline.yml", "docker-compose.online.yml"):
            text = (ROOT / name).read_text(encoding="utf-8")
            start = text.index("  upgrade-runner:")
            block = text[start:]
            self.assertIn("healthcheck:", block, name)
            self.assertIn("upgrade-runner-state.json", block, name)
            # 90s 与 RUNNER_HEARTBEAT_STALE_SECONDS 同量级：容器 Up 但心跳停 → unhealthy
            self.assertIn("-lt 90", block, name)

    def test_healthcheck_is_version_aware_for_baseline_runner(self) -> None:
        """交付 compose 的心跳判据必须按 runner 版本区分（2026-10-20 接手轮实测）。

        交付安装基线钉已发布 v0.3.1，它**没有**周期心跳看门狗（`instance_heartbeat_loop`
        是 v0.3.2 起的），只在启动时写一次状态文件。若仍按「文件存在但超 90s」判定，
        全新安装约 90 秒后必然误报 `(unhealthy)`（实测 RestartCount=0、health API 仍 ok）。
        """
        for name in ("docker-compose.dev.yml", "docker-compose.offline.yml", "docker-compose.online.yml"):
            text = (ROOT / name).read_text(encoding="utf-8")
            start = text.index("  upgrade-runner:")
            block = text[start:]
            self.assertIn("/app/RUNNER_VERSION", block, name)
            self.assertIn("v0.3.2", block, name)
            self.assertIn("exit 0", block, name)

    def test_healthcheck_override_matches_delivery_compose(self) -> None:
        """settlement 的覆盖文件与三份交付 compose 必须同源（#101 的教训）。"""
        from app.v2.upgrade import settlement

        for name in ("docker-compose.dev.yml", "docker-compose.offline.yml", "docker-compose.online.yml"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for line in settlement._HEALTHCHECK_SCRIPT_LINES:
                self.assertIn(line, text, f"{name} 与 settlement 覆盖文件不同源：{line}")


class RunnerContainerHintTests(unittest.TestCase):
    def _hint(self, output: str) -> str:
        from app.v2.upgrade.service.execution import ExecutionMixin

        fake = SimpleNamespace(executor=SimpleNamespace(output=lambda *a, **k: output))
        return ExecutionMixin._runner_container_hint(fake)

    def test_distinguishes_container_present_but_stale(self) -> None:
        hint = self._hint("smartx-hci-capacity-insight-upgrade-runner-1|Up 2 hours")
        self.assertIn("容器存在", hint)
        self.assertIn("cutover", hint)

    def test_reports_missing_container(self) -> None:
        hint = self._hint("")
        self.assertIn("未发现", hint)

    def test_probe_failure_is_silent(self) -> None:
        from app.v2.upgrade.service.execution import ExecutionMixin

        def boom(*_a, **_k):
            raise RuntimeError("docker unavailable")

        fake = SimpleNamespace(executor=SimpleNamespace(output=boom))
        self.assertEqual(ExecutionMixin._runner_container_hint(fake), "")


if __name__ == "__main__":
    unittest.main()
