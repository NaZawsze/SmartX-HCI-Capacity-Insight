"""runner 心跳遇 SQLite 锁不得让进程退出（2026-10-04，pending #82）。

## 根因（`.12` 实测）

升级期间 web-api / runner 自身写库持锁，`upgrade_runner_state` 的 upsert 撞上
`sqlite3.OperationalError: database is locked`。该异常原先**一路冒泡到 `main()` 的
`while` 循环外**，进程直接退出（exit 0、OOMKilled=false），靠
`restart: unless-stopped` 被拉起——`.12` 实测 `upgrade-runner` 的 `RestartCount=1`。

风险三条：
1. 升级正进行中时 runner 反复退出，可能拖慢甚至卡住任务；
2. 撞上重启上限会进入 crash-loop；
3. 崩溃发生在接管任务**之前**会漏执行。

## 为什么可以直接改而不 bump 版本号

`RUNNER_VERSION` 当前是 **v0.3.2，仍在开发线、尚未发布**（客户现场是 v0.3.1；
组件包交付随下一版一起发，见 pending #53）。AGENTS §6 的「改 runner 必须 bump 版本号」
是为了防止**已发布版本**出现「同版本号、不同能力」；对未发布版本不适用。
故本次直接在 v0.3.2 内修复。

## 本文件钉住的两个行为

1. `_heartbeat_with_retry`：锁是短暂的，短退避重试可覆盖；重试耗尽也**返回 False 而非抛出**
2. `main()` 循环：单轮任何异常都**记录后继续下一轮**，runner 保持存活
"""

import sqlite3
import unittest


class _FakeLease:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def update_runner_state(self, _version: str) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise sqlite3.OperationalError("database is locked")


class HeartbeatRetryTest(unittest.TestCase):
    def _retry(self, failures: int):
        from app.upgrade_runner import main as runner_main

        lease = _FakeLease(failures)
        # 把退避睡掉，测试不真的等 3.7 秒
        original = runner_main.time.sleep
        runner_main.time.sleep = lambda _s: None
        try:
            ok = runner_main._heartbeat_with_retry(lease, "v0.3.2")
        finally:
            runner_main.time.sleep = original
        return ok, lease

    def test_succeeds_first_try(self) -> None:
        ok, lease = self._retry(0)
        self.assertTrue(ok)
        self.assertEqual(lease.calls, 1)

    def test_recovers_after_transient_lock(self) -> None:
        """锁是短暂的：重试后应成功。"""
        ok, lease = self._retry(2)
        self.assertTrue(ok, "短暂锁应被退避重试覆盖")
        self.assertEqual(lease.calls, 3)

    def test_exhausted_retries_returns_false_without_raising(self) -> None:
        """重试耗尽也**不得抛异常**——心跳丢一次不该让 runner 退出。"""
        ok, lease = self._retry(99)
        self.assertFalse(ok)
        self.assertGreater(lease.calls, 1, "应确尝试过重试")

    def test_non_lock_error_not_retried(self) -> None:
        """非锁原因的 OperationalError 重试无意义，不浪费时间。"""

        class _BadLease:
            def __init__(self) -> None:
                self.calls = 0

            def update_runner_state(self, _v: str) -> None:
                self.calls += 1
                raise sqlite3.OperationalError("no such table: upgrade_runner_state")

        from app.upgrade_runner import main as runner_main

        lease = _BadLease()
        original = runner_main.time.sleep
        runner_main.time.sleep = lambda _s: None
        try:
            ok = runner_main._heartbeat_with_retry(lease, "v0.3.2")
        finally:
            runner_main.time.sleep = original
        self.assertFalse(ok)
        self.assertEqual(lease.calls, 1, "非锁错误只试一次")


class RunnerLoopResilienceTest(unittest.TestCase):
    def test_main_loop_survives_exceptions(self) -> None:
        """**核心断言**：单轮异常不得终止 runner 进程。

        做法：把 `run_pending_once` 换成「第一次抛、第二次正常」的桩，
        跑 `main()` 至 stop 被置位，断言它至少进入了第二轮（即没被第一次异常带走）。
        """
        import app.upgrade_runner.main as runner_main

        calls = {"n": 0}

        def _boom_then_ok(_settings, *, owner=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise sqlite3.OperationalError("database is locked")
            if calls["n"] >= 3:
                raise KeyboardInterrupt  # 用来跳出 while
            return 0

        original_run = runner_main.run_pending_once
        original_signal = runner_main.signal.signal
        original_sleep = runner_main.time.sleep
        runner_main.run_pending_once = _boom_then_ok
        runner_main.signal.signal = lambda *a, **k: None
        runner_main.time.sleep = lambda _s: None
        try:
            with self.assertRaises(KeyboardInterrupt):
                runner_main.main()
        finally:
            runner_main.run_pending_once = original_run
            runner_main.signal.signal = original_signal
            runner_main.time.sleep = original_sleep

        self.assertGreaterEqual(
            calls["n"],
            3,
            "第一次异常后 runner 应继续下一轮（未退出）；实际只跑了 "
            f"{calls['n']} 轮，说明进程被异常带走了",
        )


if __name__ == "__main__":
    unittest.main()
