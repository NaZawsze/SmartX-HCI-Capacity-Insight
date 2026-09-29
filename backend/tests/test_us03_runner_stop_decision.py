"""US-03：runner 生命周期收敛到**单一决策处**。

现象：三个入口各自隐含"能不能停这个 runner"的判断——组件升级（web-api compose stop/up）、
平台升级 handoff（runner 起 helper）、legacy 清理（`runner.stop_legacy_runtime`）。
任何一处漏判就会误停刚启动的 runner——US-04 正是这么产生的
（v0.5.2 源端无条件 stop，10s SIGKILL / `exit=137` / 心跳过期）。

收敛做法：把规则写成 `resolve_runner_stop_decision()`（可断言、可留痕），
各入口经它判断，而不是各自 if。
"""

from __future__ import annotations

import unittest


class RunnerStopDecisionTest(unittest.TestCase):
    def _decide(self, runner_project: str, target_project: str, purpose: str = "test"):
        from app.upgrade_runner.actions import resolve_runner_stop_decision

        return resolve_runner_stop_decision(
            runner_project=runner_project, target_project=target_project, purpose=purpose
        )

    # ---------- 核心规则 ----------

    def test_same_project_must_not_stop(self) -> None:
        """US-04 根因：同 project 停掉的就是刚 up 起来的新 runner。"""
        decision = self._decide("smartx-hci-capacity-insight", "smartx-hci-capacity-insight")
        self.assertFalse(decision["stop"], "同 project 必须跳过停止")
        self.assertIn("刚启动的新 runner", decision["reason"])

    def test_different_project_must_stop(self) -> None:
        decision = self._decide("smartx-storage-forecast", "smartx-hci-capacity-insight")
        self.assertTrue(decision["stop"], "旧 project 的 runner 必须停，否则心跳覆盖")
        self.assertIn("心跳覆盖", decision["reason"])

    def test_missing_target_project_is_conservative_stop(self) -> None:
        """未声明目标 project：保守停止（旧行为），避免旧 runner 心跳覆盖。"""
        decision = self._decide("whatever", "")
        self.assertTrue(decision["stop"])

    def test_empty_runner_project_still_stops(self) -> None:
        decision = self._decide("", "smartx-hci-capacity-insight")
        self.assertTrue(decision["stop"], "不知道 runner 属于哪个 project 时保守停止")

    def test_reason_records_purpose_for_forensics(self) -> None:
        """决策理由必须带 purpose，便于事后取证（US-04 排查靠的就是这个）。"""
        decision = self._decide("a", "b", purpose="handoff")
        self.assertIn("handoff", decision["reason"])

    def test_decision_is_pure_data(self) -> None:
        """决策是纯数据（不碰 docker），因此可单测、可复用。"""
        decision = self._decide("a", "b")
        self.assertEqual(
            sorted(decision), ["reason", "runner_project", "stop", "target_project"]
        )


class StopDecisionConvergenceTest(unittest.TestCase):
    def test_web_api_and_runner_share_the_same_rule(self) -> None:
        """web-api 侧 `_should_stop_previous_runner` 必须与 runner 侧决策同规则。

        两边判断"同 project 跳过 / 不同 project 停止"必须一致——不一致正是
        US-04 这类时序 bug 的温床。
        """
        from app.upgrade_runner.actions import resolve_runner_stop_decision
        from app.v2.upgrade.service.execution import _should_stop_previous_runner

        project = "smartx-hci-capacity-insight"
        # 注意 None（没有 bootstrap 对象）与 {}（有对象但未声明 target_project）是两回事：
        #   · None → web-api 返回 False（根本没拿到 bootstrap，不动）
        #   · {}  → web-api 返回 True（保守停止，避免旧 runner 心跳覆盖）
        # runner 侧决策函数只处理"有 target_project 语境"，用空串表示未声明 → 同样 True。
        cases = [
            ({"target_project": project}, False),          # 同 project → 不停
            ({"target_project": "other-project"}, True),   # 不同 project → 停
            ({}, True),                                     # 有对象未声明 → 停
        ]
        for bootstrap, expected in cases:
            web_api_says = _should_stop_previous_runner(bootstrap, project)
            runner_says = resolve_runner_stop_decision(
                runner_project=project, target_project=str(bootstrap.get("target_project") or ""), purpose="convergence"
            )["stop"]
            self.assertEqual(
                web_api_says, expected, f"web-api 侧对 {bootstrap} 判定不符预期"
            )
            self.assertEqual(
                runner_says, expected, f"runner 侧对 {bootstrap} 判定不符预期"
            )

    def test_web_api_skips_when_bootstrap_absent(self) -> None:
        """bootstrap 完全缺失（None）时 web-api 不做任何停止动作——这是既有语义，保留。"""
        from app.v2.upgrade.service.execution import _should_stop_previous_runner

        self.assertFalse(
            _should_stop_previous_runner(None, "smartx-hci-capacity-insight"),
            "没有 bootstrap 对象时不应停止",
        )

    def test_stop_legacy_runtime_consults_decision(self) -> None:
        """legacy 清理动作必须经唯一决策处，且拒绝时给出结构化 skip_reason。"""
        import inspect

        from app.upgrade_runner.actions import runner_stop_legacy_runtime

        source = inspect.getsource(runner_stop_legacy_runtime)
        self.assertIn("resolve_runner_stop_decision", source, "必须经统一决策")
        self.assertIn('decision["stop"]', source, "必须在 stop 前应用决策")
        self.assertIn("skip_reason", source, "跳过时必须留结构化原因")

    def test_no_independent_stop_judgement_left_in_actions(self) -> None:
        """actions.py 不得再出现"同 project 就跳过"这类重复内联判断。"""
        from pathlib import Path

        actions = Path(__file__).resolve().parent.parent / "app" / "upgrade_runner" / "actions.py"
        text = actions.read_text(encoding="utf-8")
        # 同 project 跳过的语义只能在 resolve_runner_stop_decision 里出现一次
        occurrences = text.count("停掉的就是刚启动的新 runner")
        self.assertEqual(
            occurrences, 1,
            f"该判断应在唯一决策函数里只出现一次，实际 {occurrences} 次",
        )


if __name__ == "__main__":
    unittest.main()
