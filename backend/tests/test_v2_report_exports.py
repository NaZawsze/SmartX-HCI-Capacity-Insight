import os
import tempfile
import unittest
from pathlib import Path


try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local host may not have web deps.
    TestClient = None


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed.")
class V2ReportExportApiTest(unittest.TestCase):
    def test_report_exports_require_auth_save_files_and_expose_download_link(self) -> None:
        from app.v2.api import get_report_service
        from app.v2.main import create_app

        class FakeReportService:
            def latest_report(self, tower_id=None, cluster_id=None, period_days=30, chart_days=365):
                return {
                    "scope": {"tower_id": tower_id, "cluster_id": cluster_id},
                    "clusters": [
                        {
                            "labels": {"tower_id": "1", "cluster_id": "cluster-a", "cluster": "Cluster A"},
                            "forecast": {
                                "status": "ok",
                                "slope_per_day": 10,
                                "current": 190,
                                "forecast_90d": 1090,
                                "exhaustion_days": None,
                            },
                            "points": [],
                            "total": 1000,
                            "warning": 900,
                        }
                    ],
                    "day_fastest_growing_vms": [],
                    "month_fastest_growing_vms": [
                        {
                            "labels": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-1", "vm": "VM One"},
                            "forecast": {"status": "ok", "slope_per_day": 4, "current": 240},
                            "growth_amount": 120,
                            "previous_value": 120,
                            "growth_ratio": 1.0,
                        }
                    ],
                    "day_new_vms": [],
                    "month_new_vms": [],
                    "cluster_growth_rate": {"per_day": 10, "per_month": 300, "per_quarter": 900},
                    "window_days": period_days,
                    "chart_days": chart_days,
                    "growth_rate_window_days": 7,
                    "forecast_days": 90,
                    "period_window": {"days": period_days, "start_at": "2026-05-01T00:00:00+08:00", "end_at": "2026-05-31T00:00:00+08:00"},
                }

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_SECRET_KEY"] = "reports-export-secret"
            os.environ["SMARTX_ADMIN_PASSWORD"] = "password"
            try:
                app = create_app()
                app.dependency_overrides[get_report_service] = lambda: FakeReportService()
                with TestClient(app) as client:
                    self.assertEqual(client.get("/api/reports/export/word").status_code, 401)
                    token = client.post("/api/auth/login", json={"username": "admin", "password": "password"}).json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}

                    word = client.get("/api/reports/export/word?period_days=30", headers=headers)
                    self.assertEqual(word.status_code, 200)
                    self.assertEqual(word.headers["content-type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
                    self.assertIn("storage-forecast-all-", word.headers["content-disposition"])
                    word_path = Path(word.headers["x-smartx-export-path"])
                    self.assertTrue(word_path.is_file())
                    self.assertEqual(word_path.parent, Path(tmpdir) / "exports" / "reports")
                    self.assertTrue(word.headers["x-smartx-export-url"].startswith("/api/admin/exports/reports/"))
                    self.assertGreater(len(word.content), 1000)

                    excel = client.get("/api/reports/export/excel?period_days=30", headers=headers)
                    self.assertEqual(excel.status_code, 200)
                    self.assertEqual(excel.headers["content-type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    excel_path = Path(excel.headers["x-smartx-export-path"])
                    self.assertTrue(excel_path.is_file())
                    self.assertEqual(excel_path.parent, Path(tmpdir) / "exports" / "reports")
                    self.assertGreater(len(excel.content), 1000)

                    download = client.get(word.headers["x-smartx-export-url"], headers=headers)
                    self.assertEqual(download.status_code, 200)
                    self.assertEqual(download.content, word.content)
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_SECRET_KEY", None)
                os.environ.pop("SMARTX_ADMIN_PASSWORD", None)


if __name__ == "__main__":
    unittest.main()
