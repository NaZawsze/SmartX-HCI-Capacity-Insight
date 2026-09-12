from __future__ import annotations

import json
import os
import tempfile
import unittest


try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover
    TestClient = None


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed.")
class V2TowerUiApiTest(unittest.TestCase):
    def _client(self):
        from app.v2.main import create_app

        return TestClient(create_app())

    def _auth(self, client):
        login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    def test_tower_params_test_reports_failure_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_SECRET_KEY"] = "tower-ui-secret"
            os.environ["SMARTX_ADMIN_PASSWORD"] = "password"
            try:
                with self._client() as client:
                    headers = self._auth(client)
                    # 连不上的本地地址：应返回 ok=False 与原因，而不是 500
                    result = client.post(
                        "/api/towers/test",
                        json={"base_url": "http://127.0.0.1:1", "username": "u", "password": "p", "verify_tls": False},
                        headers=headers,
                    )
                    self.assertEqual(result.status_code, 200)
                    payload = result.json()
                    self.assertFalse(payload["ok"])
                    self.assertTrue(payload["message"])
                    # 认证方式缺失：业务校验提示
                    missing = client.post(
                        "/api/towers/test",
                        json={"base_url": "https://tower.example.com"},
                        headers=headers,
                    )
                    self.assertEqual(missing.status_code, 200)
                    self.assertFalse(missing.json()["ok"])
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_SECRET_KEY", None)
                os.environ.pop("SMARTX_ADMIN_PASSWORD", None)

    def test_tower_response_contains_last_collection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_SECRET_KEY"] = "tower-ui-secret"
            os.environ["SMARTX_ADMIN_PASSWORD"] = "password"
            try:
                with self._client() as client:
                    headers = self._auth(client)
                    created = client.post(
                        "/api/towers",
                        json={"name": "T", "base_url": "https://tower.example.com", "username": "u", "password": "p"},
                        headers=headers,
                    )
                    tower_id = created.json()["id"]
                    listing = client.get("/api/towers", headers=headers).json()
                    self.assertIn("last_collection", listing[0])
                    self.assertIsNone(listing[0]["last_collection"])

                    targets = [{"tower_id": tower_id, "tower_name": "T", "cluster_id": "c", "cluster_name": "C"}]
                    from app.v2.config import settings_from_environment
                    from app.v2.database import V2Database

                    database = V2Database(settings_from_environment())
                    with database.connection() as conn:
                        conn.execute(
                            """INSERT INTO collection_runs (status, message, started_at, finished_at, trigger, success_targets_json, failed_targets_json, published_metrics_targets_json)
                               VALUES ('success', 'ok', '2026-09-12T10:00:00', '2026-09-12T10:01:00', 'scheduled', ?, '[]', ?)""",
                            (json.dumps(targets), json.dumps(targets)),
                        )
                    listing = client.get("/api/towers", headers=headers).json()
                    self.assertEqual(listing[0]["last_collection"]["status"], "success")
                    self.assertTrue(listing[0]["last_collection"]["finished_at"])
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_SECRET_KEY", None)
                os.environ.pop("SMARTX_ADMIN_PASSWORD", None)


if __name__ == "__main__":
    unittest.main()
