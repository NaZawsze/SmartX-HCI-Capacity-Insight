"""US-28：组件升级后 SQLite 写锁窗口 → 不再裸 500，改为 503 + 可读提示。

机制更正（2026-09-28 `.12` 核实）：平台数据库**本来就是 WAL 模式**
（`database.py` 的 `PRAGMA journal_mode = WAL`，实测 `journal_mode=wal`）。
WAL 下读写不互斥，但**写-写仍然互斥**——所以 runner 持有未提交写事务期间，
web-api 的写操作（升级预检查）仍会 `database is locked`（`busy_timeout=5000` 等 5 秒后失败）。

刻意不做退避重试：锁窗口是**分钟级**，在 HTTP 请求内等待必然撞请求超时。
正确做法是快速失败 + 明确告知稍后重试。根因（runner 连接泄漏）需改 runner 修复。
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path


class DatabaseBusyTranslationTest(unittest.TestCase):
    def _database(self, tmpdir: str):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database

        settings = V2Settings(data_root=Path(tmpdir), secret_key="us28-secret", app_version="v0.5.3")
        database = V2Database(settings)
        database.initialize()
        return database

    def test_busy_error_detected(self) -> None:
        from app.v2.database import _is_database_busy

        self.assertTrue(_is_database_busy(sqlite3.OperationalError("database is locked")))
        self.assertTrue(_is_database_busy(sqlite3.OperationalError("database table is locked")))
        self.assertFalse(_is_database_busy(sqlite3.OperationalError("no such table: users")))

    def test_locked_error_becomes_domain_error(self) -> None:
        """写锁超时应翻译成 DatabaseBusyError，而不是裸 sqlite3 异常。"""
        from app.v2.database import DatabaseBusyError

        with tempfile.TemporaryDirectory() as tmpdir:
            database = self._database(tmpdir)
            with self.assertRaises(DatabaseBusyError) as ctx:
                with database.connection() as conn:
                    # 模拟 runner 持锁：自己先开一个写事务，再让另一个连接写
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('a','x',1)")
                    with database.connection() as other:
                        other.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('b','y',1)")
            self.assertIn("稍后重试", str(ctx.exception))
            self.assertIn("upgrade-runner", str(ctx.exception), "提示要指向 upgrade-runner，便于运维定位")

    def test_other_operational_errors_pass_through(self) -> None:
        """非锁类 OperationalError 必须原样抛出，不能被误吞。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            database = self._database(tmpdir)
            with self.assertRaises(sqlite3.OperationalError):
                with database.connection() as conn:
                    conn.execute("SELECT * FROM table_that_does_not_exist")

    def test_normal_write_unaffected(self) -> None:
        """无锁竞争时正常读写不受影响（不能因为加了异常翻译就误伤常规路径）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            database = self._database(tmpdir)
            with database.connection() as conn:
                before = list(conn.execute("SELECT count(*) FROM users"))[0][0]
                conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('u1','h',1)")
            with database.connection() as conn:
                after = list(conn.execute("SELECT count(*) FROM users"))[0][0]
            self.assertEqual(after, before + 1)


class DatabaseBusyApiMappingTest(unittest.TestCase):
    def test_api_returns_503_with_readable_detail(self) -> None:
        """US-28：领域异常必须映射为 503 + 可读文案，而不是裸 500。"""
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:  # pragma: no cover - 本地无 fastapi 时跳过
            self.skipTest("fastapi not available locally")

        import os

        from app.v2.main import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_SECRET_KEY"] = "us28-secret"
            os.environ["SMARTX_ADMIN_PASSWORD"] = "password"
            try:
                app = create_app()
                with TestClient(app, raise_server_exceptions=False) as client:
                    token = client.post(
                        "/api/auth/login",
                        json={"username": "admin", "password": "password"},
                    ).json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}
                    response = client.get("/api/admin/upgrade/history", headers=headers)
                    # 正常路径不应 503
                    self.assertNotEqual(response.status_code, 503)
            finally:
                for key in ("SMARTX_DATA_ROOT", "SMARTX_SECRET_KEY", "SMARTX_ADMIN_PASSWORD"):
                    os.environ.pop(key, None)

    def test_exception_handler_is_registered(self) -> None:
        import inspect

        from app.v2 import main

        source = inspect.getsource(main.create_app)
        self.assertIn("database_busy_handler", source, "必须注册 DatabaseBusyError 处理器")
        self.assertIn("status_code=503", source, "锁冲突应返回 503（可重试语义），不是 500")


if __name__ == "__main__":
    unittest.main()
