"""US-28 治本：runner 的 LeaseManager 必须**显式关闭** SQLite 连接。

`.12` 现场证据：runner 在空闲态持有 **52 个**指向业务库的 fd，造成约 **10 分钟**写锁窗口，
期间 web-api 的升级预检查连报 500 `sqlite3.OperationalError: database is locked`
（平台 DB 是 WAL 模式，写-写互斥）。根因：`with sqlite3.connect(...) as conn`
**只提交事务、不关闭连接**，而心跳每 5 秒调用一次。

本测试固化不变量：每次 `_connect()` 退出后连接必须已关闭；异常路径也必须关闭。
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path


class LeaseConnectionLifecycleTest(unittest.TestCase):
    def _manager(self, tmpdir: str):
        from app.upgrade_runner.lease import LeaseManager

        return LeaseManager(Path(tmpdir) / "smartx.db", owner="runner-test")

    def test_connection_is_closed_after_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self._manager(tmpdir)
            with manager._connect() as connection:
                self.assertIsInstance(connection, sqlite3.Connection)
            # 退出后连接不可再使用 → 证明真的 close 了
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")

    def test_connection_closed_on_exception(self) -> None:
        """异常路径也必须关闭（否则异常频繁时同样会堆积）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self._manager(tmpdir)
            captured: list[sqlite3.Connection] = []
            with self.assertRaises(ValueError):
                with manager._connect() as connection:
                    captured.append(connection)
                    raise ValueError("boom")
            with self.assertRaises(sqlite3.ProgrammingError):
                captured[0].execute("SELECT 1")

    def test_heartbeat_does_not_accumulate_open_connections(self) -> None:
        """反复心跳（模拟长驻运行）不得留下打开的连接。"""
        import gc

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self._manager(tmpdir)
            database_path = Path(tmpdir) / "smartx.db"
            baseline = self._open_connection_count(database_path)
            for _ in range(50):
                manager.heartbeat("task-1", revision=1)
                manager.acquire("task-1", revision=1)
                manager.release("task-1")
            gc.collect()
            after = self._open_connection_count(database_path)
            self.assertEqual(
                after,
                baseline,
                f"50 轮心跳/租约后打开的连接数应回到基线（{baseline}），实际 {after}",
            )

    def _open_connection_count(self, database_path: Path) -> int:
        """用 /proc 统计指向该库的 fd 数（仅 Linux 可用，否则跳过）。"""
        import os

        proc = Path("/proc/self/fd")
        if not proc.is_dir():
            self.skipTest("/proc 不可用（非 Linux）")
        target = str(database_path.resolve())
        count = 0
        for entry in proc.iterdir():
            try:
                if os.readlink(entry) == target:
                    count += 1
            except OSError:
                continue
        return count

    def test_acquire_and_release_still_work(self) -> None:
        """功能不回归：租约仍能正常获取/续约/释放。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self._manager(tmpdir)
            self.assertTrue(manager.acquire("task-x", revision=1))
            with sqlite3.connect(Path(tmpdir) / "smartx.db") as conn:
                row = conn.execute(
                    "SELECT lease_owner FROM upgrade_task_leases WHERE task_id = ?", ("task-x",)
                ).fetchone()
            self.assertEqual(row[0], "runner-test")
            manager.release("task-x")
            with sqlite3.connect(Path(tmpdir) / "smartx.db") as conn:
                remaining = conn.execute(
                    "SELECT count(*) FROM upgrade_task_leases WHERE task_id = ?", ("task-x",)
                ).fetchone()[0]
            self.assertEqual(remaining, 0)

    def test_update_runner_state_still_works(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self._manager(tmpdir)
            manager.update_runner_state("v0.3.2")
            with sqlite3.connect(Path(tmpdir) / "smartx.db") as conn:
                version = conn.execute("SELECT runner_version FROM upgrade_runner_state WHERE id = 1").fetchone()[0]
            self.assertEqual(version, "v0.3.2")


if __name__ == "__main__":
    unittest.main()
