import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Optional


try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local host may not have web deps.
    TestClient = None


class FakeReportService:
    def __init__(self, *, month_vms: Optional[list[dict]] = None) -> None:
        self.month_vms = month_vms

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
                    "points": [[1764547200, 780], [1764633600, 790], [1764720000, 810]],
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
                    "points": [[1764547200, 110], [1764633600, 115], [1764720000, 120]],
                    "total": 1000,
                    "warning": 900,
                }
            ],
            "day_fastest_growing_vms": [
                {
                    "labels": {"tower_id": "1", "tower": "Tower A", "cluster_id": "cluster-a", "cluster": "Cluster A", "vm_id": "vm-day", "vm": "Day VM"},
                    "forecast": {"status": "ok", "slope_per_day": 4, "current": 240 * 1024**3},
                    "growth_amount": 8 * 1024**3,
                    "previous_value": 232 * 1024**3,
                    "growth_ratio": 0.03,
                }
            ],
            "month_fastest_growing_vms": self.month_vms
            if self.month_vms is not None
            else [
                {
                    "labels": {"tower_id": "1", "tower": "Tower A", "cluster_id": "cluster-a", "cluster": "Cluster A", "vm_id": "vm-1", "vm": "VM One"},
                    "forecast": {"status": "ok", "slope_per_day": 4, "current": 240 * 1024**3},
                    "growth_amount": 150 * 1024**3,
                    "previous_value": 120 * 1024**3,
                    "growth_ratio": 1.0,
                    "sample_span_days": 31,
                    "window_start_at": "2026-05-01T00:00:00+08:00",
                    "window_end_at": "2026-05-31T00:00:00+08:00",
                }
            ],
            "day_new_vms": [
                {
                    "labels": {"tower_id": "1", "tower": "Tower A", "cluster_id": "cluster-a", "cluster": "Cluster A", "vm_id": "vm-new-day", "vm": "New Day VM"},
                    "forecast": {"status": "ok", "slope_per_day": 0, "current": 10 * 1024**3},
                    "first_seen_at": "2026-05-31T09:00:00+08:00",
                }
            ],
            "month_new_vms": [
                {
                    "labels": {"tower_id": "1", "tower": "Tower A", "cluster_id": "cluster-b", "cluster": "Cluster B", "vm_id": "vm-new-month", "vm": "New Month VM"},
                    "forecast": {"status": "ok", "slope_per_day": 0, "current": 30 * 1024**3},
                    "first_seen_at": "2026-05-03T09:00:00+08:00",
                }
            ],
            "cluster_growth_rate": {"per_day": 10, "per_month": 300, "per_quarter": 900},
            "window_days": period_days,
            "chart_days": chart_days,
            "growth_rate_window_days": 7,
            "forecast_days": 90,
            "period_window": {"days": period_days, "start_at": "2026-05-01T00:00:00+08:00", "end_at": "2026-05-31T00:00:00+08:00"},
            "data_window": {"start_at": "2026-05-22T13:00:00+00:00", "end_at": "2026-06-06T19:00:00+00:00"},
            "timezone": "Asia/Shanghai",
        }


class V2ReportExportDocumentTest(unittest.TestCase):
    def test_docx_uses_v1_like_cluster_sections_with_top10_charts(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.reports.export import build_report_docx

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="reports-docx-secret")
            content, _, path, _ = build_report_docx(FakeReportService().latest_report(period_days=30), settings, period_days=30)
            self.assertTrue(path.is_file())
            word_xml, _ = _docx_xml(content)
            self.assertIn("SmartX HCI Capacity Insight", word_xml)
            self.assertIn("Storage Capacity Forecast Report", word_xml)
            self.assertIn("定位说明", word_xml)
            self.assertIn("1. 集群容量增长概览", word_xml)
            self.assertIn("2.1 Tower A - Cluster A", word_xml)
            self.assertIn("Top 10 VM 增长量", word_xml)

    def test_docx_keeps_day_growth_data_when_month_growth_is_empty(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.reports.export import build_report_docx

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="reports-docx-secret")
            content, _, _, _ = build_report_docx(FakeReportService(month_vms=[]).latest_report(period_days=7), settings, period_days=7)
            word_xml, _ = _docx_xml(content)
            self.assertIn("本次统计窗口增长 VM", word_xml)
            self.assertIn("日增长最快 VM", word_xml)
            self.assertIn("Day VM", word_xml)
            self.assertIn("当前样本跨度区间暂无 VM 增长数据", word_xml)

    def test_docx_vm_top_uses_actual_sample_window_not_requested_period(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.reports.export import build_report_docx, build_report_xlsx

        month_vms = [
            {
                "labels": {"tower_id": "1", "tower": "Tower A", "cluster_id": "cluster-a", "cluster": "Cluster A", "vm_id": "vm-1", "vm": "VM One"},
                "forecast": {"status": "ok", "slope_per_day": 4, "current": 240 * 1024**3},
                "growth_amount": 150 * 1024**3,
                "previous_value": 120 * 1024**3,
                "growth_ratio": 1.0,
                "window_start_at": "2026-06-05T16:00:00+00:00",
                "window_end_at": "2026-06-06T02:00:00+00:00",
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="reports-docx-secret")
            report = FakeReportService(month_vms=month_vms).latest_report(period_days=365)
            content, _, _, _ = build_report_docx(report, settings, period_days=365)
            word_xml, _ = _docx_xml(content)
            self.assertIn("统计窗口：2026-06-06 - 2026-06-06", word_xml)
            self.assertNotIn("统计窗口：2025-06-06 - 2026-06-06", word_xml)

            xlsx_content, _, _, _ = build_report_xlsx(report, settings, period_days=365)
            with zipfile.ZipFile(io.BytesIO(xlsx_content)) as zf:
                workbook_xml = "\n".join(
                    zf.read(name).decode("utf-8", "ignore")
                    for name in zf.namelist()
                    if name.endswith(".xml")
                )
            self.assertIn("2026-06-06 - 2026-06-06", workbook_xml)


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed.")
class V2ReportExportApiTest(unittest.TestCase):
    def test_report_exports_require_auth_save_files_and_expose_download_link(self) -> None:
        from app.v2.api import get_report_service
        from app.v2.main import create_app

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
                    self.assertIn("风险状态", word_xml)
                    self.assertIn("高风险", word_xml)
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

    def test_report_bundle_exports_word_and_excel_with_one_task(self) -> None:
        from app.v2.api import get_report_service
        from app.v2.main import create_app
        from openpyxl import load_workbook

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_SECRET_KEY"] = "reports-bundle-secret"
            os.environ["SMARTX_ADMIN_PASSWORD"] = "password"
            try:
                app = create_app()
                app.dependency_overrides[get_report_service] = lambda: FakeReportService(month_vms=[])
                with TestClient(app) as client:
                    self.assertEqual(client.post("/api/reports/export/bundle?period_days=30").status_code, 401)
                    token = client.post("/api/auth/login", json={"username": "admin", "password": "password"}).json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}

                    response = client.post("/api/reports/export/bundle?period_days=30&task_id=report-export-ui-1", headers=headers)
                    self.assertEqual(response.status_code, 200)
                    payload = response.json()
                    self.assertEqual(payload["task_id"], "report-export-ui-1")
                    self.assertEqual(payload["status"], "success")
                    self.assertEqual(payload["message"], "Word 和 Excel 报表已生成")
                    self.assertEqual(len(payload["files"]), 2)
                    self.assertEqual([link["label"] for link in payload["links"]], ["Word", "Excel"])

                    word_file = next(file for file in payload["files"] if file["label"] == "Word")
                    excel_file = next(file for file in payload["files"] if file["label"] == "Excel")
                    word_path = Path(word_file["path"])
                    excel_path = Path(excel_file["path"])
                    self.assertTrue(word_path.is_file())
                    self.assertTrue(excel_path.is_file())
                    self.assertEqual(word_path.parent, Path(tmpdir) / "exports" / "reports")
                    self.assertEqual(excel_path.parent, Path(tmpdir) / "exports" / "reports")

                    word_xml, _ = _docx_xml(word_path.read_bytes())
                    self.assertIn("目录", word_xml)
                    self.assertIn("SmartX HCI Capacity Insight", word_xml)
                    self.assertIn("Storage Capacity Forecast Report", word_xml)
                    self.assertIn("定位说明", word_xml)
                    self.assertIn("报告摘要", word_xml)
                    self.assertIn("1. 集群容量增长概览", word_xml)
                    self.assertIn("2.1 Tower A - Cluster A", word_xml)
                    self.assertIn("Top 10 VM 增长量", word_xml)
                    self.assertIn("增长量 TOP100", word_xml)
                    self.assertIn("增长率 TOP100", word_xml)
                    self.assertIn("当前软件版本", word_xml)
                    self.assertNotIn("虚拟机所属人", word_xml)

                    workbook = load_workbook(excel_path, read_only=True)
                    self.assertIn("目录", workbook.sheetnames)
                    self.assertIn("汇总", workbook.sheetnames)
                    self.assertIn("VM_TOP100_汇总", workbook.sheetnames)
                    self.assertTrue(any(name.startswith("Cluster A") for name in workbook.sheetnames))
                    workbook_values = [
                        str(cell)
                        for sheet in workbook.worksheets
                        for row in sheet.iter_rows(values_only=True)
                        for cell in row
                        if cell is not None
                    ]
                    self.assertNotIn("虚拟机所属人", workbook_values)
                    self.assertIn("当前样本跨度区间暂无 VM 增长数据", workbook_values)

                    tasks = client.get("/api/tasks", headers=headers).json()
                    report_tasks = [task for task in tasks if task["type"] == "report"]
                    self.assertEqual(len(report_tasks), 1)
                    self.assertEqual(report_tasks[0]["title"], "导出预测报表")
                    self.assertEqual(report_tasks[0]["status"], "success")
                    self.assertEqual([link["label"] for link in report_tasks[0]["links"]], ["Word", "Excel"])
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
