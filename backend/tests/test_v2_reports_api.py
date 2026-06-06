import os
import tempfile
import unittest


try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local host may not have web deps.
    TestClient = None


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed.")
class V2ReportsApiTest(unittest.TestCase):
    def test_report_api_requires_auth_and_accepts_scope(self) -> None:
        from app.v2.api import get_report_service
        from app.v2.main import create_app

        class FakeReportService:
            def latest_report(self, tower_id=None, cluster_id=None, period_days=30, chart_days=365):
                return {
                    "scope": {"tower_id": tower_id, "cluster_id": cluster_id},
                    "clusters": [],
                    "fastest_growing_vms": [],
                    "day_fastest_growing_vms": [],
                    "month_fastest_growing_vms": [],
                    "day_new_vms": [],
                    "month_new_vms": [],
                    "cluster_growth_rate": {"per_day": 0, "per_month": 0, "per_quarter": 0},
                    "window_days": period_days,
                    "chart_days": chart_days,
                    "growth_rate_window_days": 7,
                    "forecast_days": 90,
                    "period_window": {"days": period_days},
                }

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_SECRET_KEY"] = "reports-api-secret"
            os.environ["SMARTX_ADMIN_PASSWORD"] = "password"
            try:
                app = create_app()
                app.dependency_overrides[get_report_service] = lambda: FakeReportService()
                with TestClient(app) as client:
                    self.assertEqual(client.get("/api/reports/latest").status_code, 401)
                    token = client.post("/api/auth/login", json={"username": "admin", "password": "password"}).json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}

                    response = client.get("/api/reports/latest?tower_id=1&cluster_id=cluster-a&period_days=90&chart_days=720", headers=headers)
                    self.assertEqual(response.status_code, 200)
                    payload = response.json()
                    self.assertEqual(payload["scope"], {"tower_id": 1, "cluster_id": "cluster-a"})
                    self.assertEqual(payload["window_days"], 90)
                    self.assertEqual(payload["chart_days"], 720)
                    self.assertEqual(payload["forecast_days"], 90)

                    missing_tower = client.get("/api/reports/latest?cluster_id=cluster-a", headers=headers)
                    self.assertEqual(missing_tower.status_code, 400)
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_SECRET_KEY", None)
                os.environ.pop("SMARTX_ADMIN_PASSWORD", None)


if __name__ == "__main__":
    unittest.main()
