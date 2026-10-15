"""#87 采集接口异步化测试：提交即返回 / 单飞 409 / 环境变量回退同步。

设计：docs/superpowers/specs/2026-10-14-collection-api-async-design.md
被测行为：
- `POST /api/collection/run` 默认**异步**：202 + `status=running` + `run_id`，
  后台线程执行，前端轮询 `GET /api/collection/runs/{run_id}` 直到终态；
- 已有 `running` 采集记录时**单飞拒绝**（409，不排队）；
- `SMARTX_COLLECTION_RUN_ASYNC=0` 回退同步（200 + 终态）。
"""

import os
import tempfile
import time
import unittest

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local host may not have web deps.
    TestClient = None


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed.")
class CollectionAsyncApiTest(unittest.TestCase):
    def _login(self, client: TestClient) -> dict:
        token = client.post(
            "/api/auth/login", json={"username": "admin", "password": "password"}
        ).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def _app(self, tmpdir: str):
        from app.v2.config import settings_from_environment
        from app.v2.database import V2Database
        from app.v2.main import create_app

        os.environ["SMARTX_DATA_ROOT"] = tmpdir
        os.environ["SMARTX_SECRET_KEY"] = "collection-async-secret"
        os.environ["SMARTX_ADMIN_PASSWORD"] = "password"
        app = create_app()
        database = V2Database(settings_from_environment())
        database.initialize()
        return app, database

    def test_submit_returns_immediately_and_run_finishes_in_background(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app, _ = self._app(tmpdir)
            try:
                with TestClient(app) as client:
                    headers = self._login(client)
                    started = time.monotonic()
                    submitted = client.post("/api/collection/run", headers=headers)
                    elapsed = time.monotonic() - started
                    self.assertEqual(submitted.status_code, 202, submitted.text)
                    body = submitted.json()
                    self.assertEqual(body["status"], "running")
                    self.assertIsInstance(body["run_id"], int)
                    self.assertLess(elapsed, 5.0, f"提交应即时返回，实际 {elapsed:.1f}s")

                    # 轮询既有端点直到终态（无配置 Tower ⇒ 0 集群成功）
                    run_id = body["run_id"]
                    deadline = time.monotonic() + 20
                    final = None
                    while time.monotonic() < deadline:
                        detail = client.get(f"/api/collection/runs/{run_id}", headers=headers)
                        self.assertEqual(detail.status_code, 200)
                        final = detail.json()
                        if final["status"] != "running":
                            break
                        time.sleep(0.2)
                    self.assertIsNotNone(final)
                    self.assertNotEqual(final["status"], "running", "后台采集应已收敛")
                    self.assertEqual(final["status"], "success")
                    self.assertIn("采集完成", final["message"])
                    self.assertIsNotNone(final.get("finished_at"), "终态必须写 finished_at")
            finally:
                for key in ("SMARTX_DATA_ROOT", "SMARTX_SECRET_KEY", "SMARTX_ADMIN_PASSWORD"):
                    os.environ.pop(key, None)

    def test_concurrent_submit_is_rejected_with_single_flight(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app, database = self._app(tmpdir)
            try:
                with database.connection() as conn:
                    # 用 CURRENT_TIMESTAMP 造「真在跑」的记录：陈旧阈值（1h）之内的 running 才该拦
                    conn.execute(
                        "INSERT INTO collection_runs (status, message, started_at)"
                        " VALUES ('running', '采集中', CURRENT_TIMESTAMP)"
                    )
                with TestClient(app) as client:
                    headers = self._login(client)
                    rejected = client.post("/api/collection/run", headers=headers)
                    self.assertEqual(rejected.status_code, 409, rejected.text)
                    self.assertIn("已有采集任务在执行中", rejected.json()["detail"])
                    with database.connection() as conn:
                        count = conn.execute("SELECT COUNT(*) FROM collection_runs").fetchone()[0]
                    self.assertEqual(count, 1, "被拒绝时不得产生新的采集记录")
            finally:
                for key in ("SMARTX_DATA_ROOT", "SMARTX_SECRET_KEY", "SMARTX_ADMIN_PASSWORD"):
                    os.environ.pop(key, None)

    def test_stale_running_row_is_converged_and_new_run_allowed(self) -> None:
        """中断残留（超阈值仍 running）不得永久挡住手动采集——收敛为 failed 后放行。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            app, database = self._app(tmpdir)
            try:
                with database.connection() as conn:
                    conn.execute(
                        "INSERT INTO collection_runs (status, message, started_at)"
                        " VALUES ('running', '采集中', datetime('now', '-12 days'))"
                    )
                    stale_id = conn.execute("SELECT id FROM collection_runs ORDER BY id DESC LIMIT 1").fetchone()[0]
                with TestClient(app) as client:
                    headers = self._login(client)
                    submitted = client.post("/api/collection/run", headers=headers)
                    self.assertEqual(submitted.status_code, 202, submitted.text)
                    self.assertNotEqual(submitted.json()["run_id"], stale_id)
                    with database.connection() as conn:
                        row = conn.execute(
                            "SELECT status, finished_at, message FROM collection_runs WHERE id = ?", (stale_id,)
                        ).fetchone()
                    self.assertEqual(row[0], "failed", "残留 running 记录必须被收敛为 failed")
                    self.assertIsNotNone(row[1], "收敛必须写 finished_at")
                    self.assertIn("中断残留", row[2])

                    # 等后台采集收敛，避免临时目录在写库中被清理
                    run_id = submitted.json()["run_id"]
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline:
                        state = client.get(f"/api/collection/runs/{run_id}", headers=headers).json()["status"]
                        if state != "running":
                            break
                        time.sleep(0.2)
            finally:
                for key in ("SMARTX_DATA_ROOT", "SMARTX_SECRET_KEY", "SMARTX_ADMIN_PASSWORD"):
                    os.environ.pop(key, None)

    def test_env_switch_falls_back_to_synchronous(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app, _ = self._app(tmpdir)
            os.environ["SMARTX_COLLECTION_RUN_ASYNC"] = "0"
            try:
                with TestClient(app) as client:
                    headers = self._login(client)
                    started = time.monotonic()
                    submitted = client.post("/api/collection/run", headers=headers)
                    self.assertEqual(submitted.status_code, 200, submitted.text)
                    body = submitted.json()
                    self.assertEqual(body["status"], "success", "同步回退应立即返回终态")
                    self.assertLess(time.monotonic() - started, 20.0)
            finally:
                os.environ.pop("SMARTX_COLLECTION_RUN_ASYNC", None)
                for key in ("SMARTX_DATA_ROOT", "SMARTX_SECRET_KEY", "SMARTX_ADMIN_PASSWORD"):
                    os.environ.pop(key, None)


if __name__ == "__main__":
    unittest.main()
