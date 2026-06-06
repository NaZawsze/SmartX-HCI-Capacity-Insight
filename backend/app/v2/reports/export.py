from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from docx import Document
from docx.shared import Pt
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.v2.config import V2Settings


DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
VM_ALERT_FILL = "F4CCCC"
VM_ALERT_RATIO = 0.2
VM_ALERT_BYTES = 100 * 1024**3


def build_report_docx(report: dict[str, Any], settings: V2Settings, *, period_days: int) -> tuple[bytes, str, Path, str]:
    context = _export_context(report, settings, period_days, "docx")
    document = Document()
    _setup_document(document)
    document.add_heading("SmartX HCI 容量预测报表", level=0)
    _add_paragraph_table(
        document,
        [
            ("导出范围", context["scope_label"]),
            ("生成时间", context["generated_at"]),
            ("统计窗口", _period_window_label(report)),
            ("预测窗口", f"{report.get('forecast_days', 90)} 天"),
            ("集群数量", str(len(report.get("clusters") or []))),
            ("当前软件版本", settings.app_version),
        ],
    )
    document.add_heading("集群预测汇总", level=1)
    _add_cluster_table(document, report.get("clusters") or [])
    document.add_heading("月增长 TOP100 VM", level=1)
    document.add_paragraph(f"统计窗口：{_period_window_label(report)}")
    _add_vm_table(document, report.get("month_fastest_growing_vms") or [])
    content = _docx_bytes(document)
    return _persist_report(content, settings, context["filename"])


def build_report_xlsx(report: dict[str, Any], settings: V2Settings, *, period_days: int) -> tuple[bytes, str, Path, str]:
    context = _export_context(report, settings, period_days, "xlsx")
    workbook = Workbook()
    summary = workbook.active
    summary.title = "汇总"
    summary.append(["导出范围", context["scope_label"]])
    summary.append(["生成时间", context["generated_at"]])
    summary.append(["统计窗口", _period_window_label(report)])
    summary.append(["预测窗口", f"{report.get('forecast_days', 90)} 天"])
    summary.append(["集群数量", len(report.get("clusters") or [])])
    summary.append(["当前软件版本", settings.app_version])
    summary.append([])
    summary.append(["集群", "当前容量", "90 天预测", "容量阈值", "预计耗尽天数"])
    for cluster in report.get("clusters") or []:
        labels = cluster.get("labels", {})
        forecast = cluster.get("forecast", {})
        summary.append(
            [
                labels.get("cluster") or labels.get("cluster_id") or "",
                forecast.get("current"),
                forecast.get("forecast_90d"),
                cluster.get("warning"),
                forecast.get("exhaustion_days"),
            ]
        )
    _autosize(summary)

    vm_sheet = workbook.create_sheet("VM_TOP100_汇总")
    vm_sheet.append([f"统计窗口：{_period_window_label(report)}"])
    vm_sheet.append([])
    vm_sheet.append(["集群", "VM", "当前容量", "期初容量", "增长量", "增长率"])
    for vm in report.get("month_fastest_growing_vms") or []:
        labels = vm.get("labels", {})
        row = [
            labels.get("cluster") or labels.get("cluster_id") or "",
            labels.get("vm") or labels.get("vm_name") or labels.get("vm_id") or "",
            (vm.get("forecast") or {}).get("current"),
            vm.get("previous_value"),
            vm.get("growth_amount"),
            vm.get("growth_ratio"),
        ]
        vm_sheet.append(row)
        if _is_alert_vm(vm):
            for cell in vm_sheet[vm_sheet.max_row]:
                cell.fill = PatternFill("solid", fgColor=VM_ALERT_FILL)
    _style_sheet(summary)
    _style_sheet(vm_sheet)

    output = BytesIO()
    workbook.save(output)
    return _persist_report(output.getvalue(), settings, context["filename"])


def _setup_document(document: Document) -> None:
    styles = document.styles
    styles["Normal"].font.name = "Noto Serif"
    styles["Normal"].font.size = Pt(10.5)


def _add_paragraph_table(document: Document, rows: list[tuple[str, str]]) -> None:
    table = document.add_table(rows=1, cols=2)
    table.style = "Table Grid"
    table.rows[0].cells[0].text = "项目"
    table.rows[0].cells[1].text = "内容"
    for key, value in rows:
        cells = table.add_row().cells
        cells[0].text = key
        cells[1].text = value


def _add_cluster_table(document: Document, clusters: list[dict[str, Any]]) -> None:
    table = document.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    headers = ["集群", "当前容量", "90 天预测", "容量阈值", "预计耗尽天数"]
    for index, header in enumerate(headers):
        table.rows[0].cells[index].text = header
    if not clusters:
        row = table.add_row().cells
        row[0].text = "暂无集群预测数据"
        return
    for cluster in clusters:
        labels = cluster.get("labels", {})
        forecast = cluster.get("forecast", {})
        values = [
            labels.get("cluster") or labels.get("cluster_id") or "",
            _bytes_label(forecast.get("current")),
            _bytes_label(forecast.get("forecast_90d")),
            _bytes_label(cluster.get("warning")),
            _days_label(forecast.get("exhaustion_days")),
        ]
        row = table.add_row().cells
        for index, value in enumerate(values):
            row[index].text = value


def _add_vm_table(document: Document, vms: list[dict[str, Any]]) -> None:
    table = document.add_table(rows=1, cols=6)
    table.style = "Table Grid"
    headers = ["集群", "VM", "当前容量", "期初容量", "增长量", "增长率"]
    for index, header in enumerate(headers):
        table.rows[0].cells[index].text = header
    if not vms:
        row = table.add_row().cells
        row[0].text = "暂无满足 30 天样本跨度的月增长 VM"
        return
    for vm in vms[:100]:
        labels = vm.get("labels", {})
        forecast = vm.get("forecast", {})
        values = [
            labels.get("cluster") or labels.get("cluster_id") or "",
            labels.get("vm") or labels.get("vm_name") or labels.get("vm_id") or "",
            _bytes_label(forecast.get("current")),
            _bytes_label(vm.get("previous_value")),
            _bytes_label(vm.get("growth_amount")),
            _percent_label(vm.get("growth_ratio")),
        ]
        row = table.add_row().cells
        for index, value in enumerate(values):
            row[index].text = value


def _export_context(report: dict[str, Any], settings: V2Settings, period_days: int, extension: str) -> dict[str, str]:
    now = _local_now(settings)
    scope = report.get("scope") or {}
    clusters = report.get("clusters") or []
    if scope.get("cluster_id"):
        scope_label = _first_cluster_name(clusters) or str(scope["cluster_id"])
    elif scope.get("tower_id") is not None:
        scope_label = f"tower-{scope['tower_id']}"
    else:
        scope_label = "all"
    scope_slug = _slug(scope_label)
    filename = f"storage-forecast-{scope_slug}-{now.strftime('%Y%m%d-%H%M%S')}-{period_days}d.{extension}"
    return {
        "filename": filename,
        "scope_label": scope_label,
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
    }


def _persist_report(content: bytes, settings: V2Settings, filename: str) -> tuple[bytes, str, Path, str]:
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    path = settings.reports_dir / Path(filename).name
    path.write_bytes(content)
    return content, filename, path, f"/api/admin/exports/reports/{quote(path.name)}"


def _period_window_label(report: dict[str, Any]) -> str:
    window = report.get("period_window") or {}
    start = str(window.get("start_at") or "")
    end = str(window.get("end_at") or "")
    if start and end:
        return f"{start[:10]} - {end[:10]}"
    return f"近 {report.get('window_days', 30)} 天"


def _first_cluster_name(clusters: list[dict[str, Any]]) -> str | None:
    if not clusters:
        return None
    labels = clusters[0].get("labels", {})
    return labels.get("cluster") or labels.get("cluster_id")


def _is_alert_vm(vm: dict[str, Any]) -> bool:
    return float(vm.get("growth_ratio") or 0) > VM_ALERT_RATIO and float(vm.get("growth_amount") or 0) > VM_ALERT_BYTES


def _docx_bytes(document: Document) -> bytes:
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _style_sheet(sheet) -> None:
    for row in sheet.iter_rows():
        for cell in row:
            if cell.row in {1, 8} or cell.value in {"集群", "VM", "当前容量"}:
                cell.font = Font(bold=True)
    _autosize(sheet)


def _autosize(sheet) -> None:
    for column_cells in sheet.columns:
        width = max(len(str(cell.value or "")) for cell in column_cells) + 2
        sheet.column_dimensions[get_column_letter(column_cells[0].column)].width = min(max(width, 10), 32)


def _local_now(settings: V2Settings) -> datetime:
    try:
        return datetime.now(ZoneInfo(settings.timezone))
    except ZoneInfoNotFoundError:
        return datetime.now()


def _slug(value: str) -> str:
    normalized = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value.strip())
    return normalized.strip("-") or "all"


def _bytes_label(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    index = 0
    while abs(numeric) >= 1024 and index < len(units) - 1:
        numeric /= 1024
        index += 1
    return f"{numeric:.2f} {units[index]}"


def _days_label(value: Any) -> str:
    try:
        return f"{float(value):.0f} 天"
    except (TypeError, ValueError):
        return "未触发"


def _percent_label(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "-"
