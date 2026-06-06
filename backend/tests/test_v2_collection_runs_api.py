import os
import tempfile
import unittest


try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local host may not have web deps.
    TestClient = None


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed.")
class V2CollectionRunsApiTest(unittest.TestCase):
    def test_collection_runs_api_requires_auth_lists_and_returns_details(self) -> None:
        from app.v2.config import settings_from_environment
        from app.v2.database import V2Database
        from app.v2.main import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_SECRET_KEY"] = "collection-runs-secret"
            os.environ["SMARTX_ADMIN_PASSWORD"] = "password"
            try:
                app = create_app()
                database = V2Database(settings_from_environment())
                database.initialize()
                with database.connection() as conn:
                    first = conn.execute(
                        "INSERT INTO collection_runs (status, message, started_at, finished_at) VALUES ('success', 'first run', '2026-06-06T01:00:00Z', '2026-06-06T01:01:00Z')"
                    ).lastrowid
                    second = conn.execute(
                        "INSERT INTO collection_runs (status, message, started_at, finished_at) VALUES ('failed', 'second run', '2026-06-06T02:00:00Z', '2026-06-06T02:01:00Z')"
                    ).lastrowid
                with TestClient(app) as client:
                    self.assertEqual(client.get("/api/collection/runs").status_code, 401)
                    token = client.post("/api/auth/login", json={"username": "admin", "password": "password"}).json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}

                    listed = client.get("/api/collection/runs", headers=headers)
                    self.assertEqual(listed.status_code, 200)
                    payload = listed.json()
                    self.assertEqual([item["id"] for item in payload], [second, first])
                    self.assertEqual(payload[0]["status"], "failed")
                    self.assertEqual(payload[0]["message"], "second run")

                    detail = client.get(f"/api/collection/runs/{first}", headers=headers)
                    self.assertEqual(detail.status_code, 200)
                    self.assertEqual(detail.json()["id"], first)
                    self.assertEqual(detail.json()["message"], "first run")

                    missing = client.get("/api/collection/runs/9999", headers=headers)
                    self.assertEqual(missing.status_code, 404)
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_SECRET_KEY", None)
                os.environ.pop("SMARTX_ADMIN_PASSWORD", None)


if __name__ == "__main__":
    unittest.main()
