"""49-50：runner 组件升级不得停掉「同 project 内刚启动的新 runner」。"""

from __future__ import annotations

import unittest


class ShouldStopPreviousRunnerTest(unittest.TestCase):
    def test_same_project_must_skip_stop(self) -> None:
        """目标布局机器原地做组件升级：新旧 runner 同 project → 不能停（否则停掉新的）。"""
        from app.v2.upgrade.service.execution import _should_stop_previous_runner

        bootstrap = {"enabled": True, "target_project": "smartx-hci-capacity-insight"}
        self.assertFalse(
            _should_stop_previous_runner(bootstrap, "smartx-hci-capacity-insight"),
            "同 project 必须跳过 stop，否则会停掉刚 up -d 的新 runner",
        )

    def test_legacy_project_still_stops_old_runner(self) -> None:
        """v0.5.1u2（旧 project）→ bootstrap 到新 project：旧行为必须保留。"""
        from app.v2.upgrade.service.execution import _should_stop_previous_runner

        bootstrap = {"enabled": True, "target_project": "smartx-hci-capacity-insight"}
        self.assertTrue(_should_stop_previous_runner(bootstrap, "smartx-storage-forecast"))

    def test_missing_target_keeps_legacy_behaviour(self) -> None:
        from app.v2.upgrade.service.execution import _should_stop_previous_runner

        # 未声明 target_project：保持旧行为（停止），避免旧 runner 心跳覆盖
        self.assertTrue(_should_stop_previous_runner({"enabled": True}, "smartx-hci-capacity-insight"))
        # 非 bootstrap：本来就不该停
        self.assertFalse(_should_stop_previous_runner({}, "smartx-hci-capacity-insight"))
        self.assertFalse(_should_stop_previous_runner(None, "smartx-hci-capacity-insight"))

    def test_call_site_uses_the_guard(self) -> None:
        """调用点必须走 _should_stop_previous_runner，防止回归到无条件 stop。"""
        import inspect

        from app.v2.upgrade.service import execution

        source = inspect.getsource(execution)
        self.assertIn("_should_stop_previous_runner(bootstrap, self.settings.compose_project_name)", source)
        self.assertNotIn(
            'if _runner_bootstrap(task["manifest"]):\n                    self.executor.run(\n                        ["docker", "compose", "-f", self.settings.compose_file, "--project-name", self.settings.compose_project_name, "stop", "upgrade-runner"]',
            source,
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
