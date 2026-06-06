import io
import os
import tempfile
import unittest
import zipfile
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
                            "labels": {"tower_id": "1", "tower": "Tower A", "cluster_id": "cluster-a", "cluster": "Cluster A"},
                            "forecast": {
                                "status": "ok",
                                "slope_per_day": 10,
                                "current": 810,
                                "forecast_90d": 1090,
                                "exhaustion_days": None,
                            },
                            "points": [],
                            "total": 1000,
                            "warning": 900,
                        },
                        {
                            "labels": {"tower_id": "1", "tower": "Tower A", "cluster_id": "cluster-b", "cluster": "Cluster B"},
                            "forecast": {
                                "status": "ok",
                                "slope_per_day": 2,
                                "current": 120,
                                "forecast_90d": 300,
                                "exhaustion_days": 2056,
                            },
                            "points": [],
                            "total": 1000,
                            "warning": 900,
                        }
                    ],
                    "day_fastest_growing_vms": [],
                    "month_fastest_growing_vms": [
                        {
                            "labels": {"tower_id": "1", "tower": "Tower A", "cluster_id": "cluster-a", "cluster": "Cluster A", "vm_id": "vm-1", "vm": "VM One"},
                            "forecast": {"status": "ok", "slope_per_day": 4, "current": 240 * 1024**3},
                            "growth_amount": 150 * 1024**3,
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
                    word_xml, footer_xml = _docx_xml(word.content)
                    self.assertIn("目录", word_xml)
                    self.assertIn("容量风险摘要", word_xml)
                    self.assertIn("Cluster A 使用率超过 80%", word_xml)
                    self.assertIn("Cluster A", word_xml)
                    self.assertIn("Cluster B", word_xml)
                    self.assertIn('w:fill="F4CCCC"', word_xml)
                    self.assertIn("Tower A", footer_xml)
                    self.assertIn("Cluster A", footer_xml)
                    self.assertIn("2026", footer_xml)

                    excel = client.get("/api/reports/export/excel?period_days=30", headers=headers)
                    self.assertEqual(excel.status_code, 200)
                    self.assertEqual(excel.headers["content-type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    excel_path = Path(excel.headers["x-smartx-export-path"])
                    self.assertTrue(excel_path.is_file())
                    self.assertEqual(excel_path.parent, Path(tmpdir) / "exports" / "reports")
                    self.assertGreater(len(excel.content), 1000)
                    with zipfile.ZipFile(excel_path) as workbook:
                        styles_xml = workbook.read("xl/styles.xml").decode("utf-8")
                    from openpyxl import load_workbook

                    workbook = load_workbook(excel_path, read_only=True)
                    summary_values = [cell for row in workbook["汇总"].iter_rows(values_only=True) for cell in row if cell]
                    self.assertIn("容量风险摘要", summary_values)
                    self.assertTrue(any("Cluster A 使用率超过 80%" in str(value) for value in summary_values))
                    self.assertIn("F4CCCC", styles_xml)

                    download = client.get(word.headers["x-smartx-export-url"], headers=headers)
                    self.assertEqual(download.status_code, 200)
                    self.assertEqual(download.content, word.content)

                    tasks = client.get("/api/tasks", headers=headers).json()
                    report_tasks = [task for task in tasks if task["type"] == "report"]
                    self.assertGreaterEqual(len(report_tasks), 2)
                    self.assertEqual(report_tasks[0]["status"], "success")
                    self.assertTrue(report_tasks[0]["links"][0]["url"].startswith("/api/admin/exports/reports/"))
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_SECRET_KEY", None)
                os.environ.pop("SMARTX_ADMIN_PASSWORD", None)


if __name__ == "__main__":
    unittest.main()


def _docx_xml(content: bytes) -> tuple[str, str]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        footer_xml = "\n".join(
            archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.startswith("word/footer")
        )
    return document_xml, footer_xml
