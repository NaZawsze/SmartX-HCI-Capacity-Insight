from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from io import BytesIO
from secrets import token_hex
from typing import Any

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.services.dashboard import latest_report


DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def build_report_docx(tower_id: int | None = None, cluster_id: str | None = None, period_days: int = 30) -> tuple[bytes, str]:
    report = await latest_report(tower_id=tower_id, cluster_id=cluster_id, period_days=period_days)
    context = _export_context(report, tower_id, cluster_id)
    document = Document()
    _set_landscape(document)

    title = document.add_heading("存储容量预测报表", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    document.add_paragraph(f"导出范围：{context['scope_label']}")
    document.add_paragraph(f"生成时间：{context['generated_at']}")
    document.add_paragraph(f"预测窗口：最近 {report.get('window_days') or 30} 天，预测 {report.get('forecast_days') or 60} 天后容量")
    document.add_paragraph(f"集群数量：{len(context['clusters'])}")

    document.add_heading("集群预测汇总", level=1)
    _add_cluster_summary_table(document, context["clusters"])

    vms_by_cluster = _vms_by_cluster(report.get("month_fastest_growing_vms") or [])
    for cluster in context["clusters"]:
        labels = cluster.get("labels", {})
        key = _cluster_key(labels)
        vms = vms_by_cluster.get(key, [])
        document.add_page_break()
        document.add_heading(_cluster_title(labels), level=1)
        _add_cluster_paragraph(document, cluster, len(vms))
        document.add_heading("月增长量 TOP100 VM", level=2)
        _add_vm_table(document, _top_vms(vms, "amount"))
        document.add_heading("月增长率 TOP100 VM", level=2)
        _add_vm_table(document, _top_vms(vms, "ratio"))

    return _docx_bytes(document), _export_filename(context, "docx")


async def build_report_xlsx(tower_id: int | None = None, cluster_id: str | None = None, period_days: int = 30) -> tuple[bytes, str]:
    report = await latest_report(tower_id=tower_id, cluster_id=cluster_id, period_days=period_days)
    context = _export_context(report, tower_id, cluster_id)
    workbook = Workbook()
    summary_sheet = workbook.active
    summary_sheet.title = "汇总"
    _write_cluster_summary_sheet(summary_sheet, context)

    vms = report.get("month_fastest_growing_vms") or []
    _write_vm_summary_sheet(workbook.create_sheet("VM_TOP100_汇总"), vms)

    vms_by_cluster = _vms_by_cluster(vms)
    for cluster in context["clusters"]:
        labels = cluster.get("labels", {})
        sheet = workbook.create_sheet(_safe_sheet_name(labels.get("cluster") or labels.get("cluster_id") or "集群"))
        cluster_vms = vms_by_cluster.get(_cluster_key(labels), [])
        _write_cluster_vm_sheet(sheet, cluster, cluster_vms)

    output = BytesIO()
    workbook.save(output)
    return output.getvalue(), _export_filename(context, "xlsx")


def _export_context(report: dict[str, Any], tower_id: int | None, cluster_id: str | None) -> dict[str, Any]:
    now = datetime.now()
    clusters = report.get("clusters") or []
    if cluster_id:
        cluster_name = _first_label(clusters, "cluster") or cluster_id
        scope_slug = _slug(cluster_name)
        scope_label = f"集群 {cluster_name}"
    elif tower_id is not None:
        tower_name = _first_label(clusters, "tower") or str(tower_id)
        scope_slug = f"{_slug(tower_name)}-{token_hex(2)}"
        scope_label = f"Tower {tower_name}"
    else:
        scope_slug = "all"
        scope_label = "全部集群"
    return {
        "clusters": clusters,
        "date_slug": now.strftime("%Y%m%d"),
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "scope_label": scope_label,
        "scope_slug": scope_slug,
        "report": report,
    }


def _export_filename(context: dict[str, Any], extension: str) -> str:
    return f"storage-forecast-{context['scope_slug']}-{context['date_slug']}.{extension}"


def _set_landscape(document: Document) -> None:
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = section.page_height, section.page_width
    section.left_margin = Inches(0.5)
    section.right_margin = Inches(0.5)


def _add_cluster_summary_table(document: Document, clusters: list[dict[str, Any]]) -> None:
    headers = ["Tower", "集群", "当前容量", "60天预测", "月增长速率", "容量阈值", "耗尽天数"]
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    _set_docx_headers(table.rows[0].cells, headers)
    for cluster in clusters:
        labels = cluster.get("labels", {})
        forecast = cluster.get("forecast", {})
        values = [
            labels.get("tower") or labels.get("tower_id") or "-",
            labels.get("cluster") or labels.get("cluster_id") or "-",
            _format_bytes(forecast.get("current")),
            _format_bytes(forecast.get("forecast_60d")),
            _format_bytes(_monthly_growth(cluster)),
            _format_bytes(cluster.get("warning")),
            _format_days(forecast.get("exhaustion_days")),
        ]
        _set_docx_row(table.add_row().cells, values)


def _add_cluster_paragraph(document: Document, cluster: dict[str, Any], vm_count: int) -> None:
    forecast = cluster.get("forecast", {})
    document.add_paragraph(
        "；".join(
            [
                f"当前容量 {_format_bytes(forecast.get('current'))}",
                f"60 天预测 {_format_bytes(forecast.get('forecast_60d'))}",
                f"月增长速率 {_format_bytes(_monthly_growth(cluster))}",
                f"容量阈值 {_format_bytes(cluster.get('warning'))}",
                f"月增长 VM 样本 {vm_count} 台",
            ]
        )
    )


def _add_vm_table(document: Document, vms: list[dict[str, Any]]) -> None:
    headers = ["VM", "当前容量", "上期容量", "月增长量", "增长率"]
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    _set_docx_headers(table.rows[0].cells, headers)
    if not vms:
        _set_docx_row(table.add_row().cells, ["暂无增长数据", "-", "-", "-", "-"])
        return
    for vm in vms:
        _set_docx_row(table.add_row().cells, _vm_row(vm, include_cluster=False))


def _set_docx_headers(cells: Any, headers: list[str]) -> None:
    for cell, header in zip(cells, headers):
        cell.text = header
        for paragraph in cell.paragraphs:
            paragraph.runs[0].bold = True


def _set_docx_row(cells: Any, values: list[str]) -> None:
    for cell, value in zip(cells, values):
        cell.text = value


def _write_cluster_summary_sheet(sheet: Any, context: dict[str, Any]) -> None:
    sheet.append(["存储容量预测报表"])
    sheet.append(["导出范围", context["scope_label"]])
    sheet.append(["生成时间", context["generated_at"]])
    sheet.append([])
    headers = ["Tower", "集群", "当前容量", "60天预测", "月增长速率", "容量阈值", "耗尽天数"]
    sheet.append(headers)
    for cluster in context["clusters"]:
        labels = cluster.get("labels", {})
        forecast = cluster.get("forecast", {})
        sheet.append(
            [
                labels.get("tower") or labels.get("tower_id") or "-",
                labels.get("cluster") or labels.get("cluster_id") or "-",
                forecast.get("current") or 0,
                forecast.get("forecast_60d") or 0,
                _monthly_growth(cluster),
                cluster.get("warning") or 0,
                forecast.get("exhaustion_days") or "",
            ]
        )
    _style_sheet(sheet, header_rows={1, 5}, bytes_cols={3, 4, 5, 6})


def _write_vm_summary_sheet(sheet: Any, vms: list[dict[str, Any]]) -> None:
    headers = ["Tower", "集群", "VM", "当前容量", "上期容量", "月增长量", "增长率"]
    sheet.append(headers)
    for vm in _top_vms(vms, "amount"):
        sheet.append(_vm_row(vm, include_cluster=True, raw=True))
    _style_sheet(sheet, header_rows={1}, bytes_cols={4, 5, 6}, percent_cols={7})


def _write_cluster_vm_sheet(sheet: Any, cluster: dict[str, Any], vms: list[dict[str, Any]]) -> None:
    labels = cluster.get("labels", {})
    sheet.append([_cluster_title(labels)])
    sheet.append(["月增长量 TOP100"])
    amount_headers = ["VM", "当前容量", "上期容量", "月增长量", "增长率"]
    sheet.append(amount_headers)
    for vm in _top_vms(vms, "amount"):
        sheet.append(_vm_row(vm, include_cluster=False, raw=True))
    start = sheet.max_row + 2
    sheet.cell(row=start, column=1, value="月增长率 TOP100")
    sheet.cell(row=start + 1, column=1, value="VM")
    for col, header in enumerate(amount_headers[1:], start=2):
        sheet.cell(row=start + 1, column=col, value=header)
    for row_index, vm in enumerate(_top_vms(vms, "ratio"), start=start + 2):
        for col, value in enumerate(_vm_row(vm, include_cluster=False, raw=True), start=1):
            sheet.cell(row=row_index, column=col, value=value)
    _style_sheet(sheet, header_rows={1, 2, 3, start, start + 1}, bytes_cols={2, 3, 4}, percent_cols={5})


def _style_sheet(sheet: Any, header_rows: set[int], bytes_cols: set[int] | None = None, percent_cols: set[int] | None = None) -> None:
    bytes_cols = bytes_cols or set()
    percent_cols = percent_cols or set()
    fill = PatternFill(fill_type="solid", fgColor="D9EAF7")
    for row in sheet.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="center")
            if cell.row in header_rows:
                cell.font = Font(bold=True)
                cell.fill = fill
            if cell.column in bytes_cols and isinstance(cell.value, (int, float)):
                cell.number_format = '#,##0'
            if cell.column in percent_cols and isinstance(cell.value, (int, float)):
                cell.number_format = "0.00%"
    for column in range(1, sheet.max_column + 1):
        max_len = 10
        for cell in sheet[get_column_letter(column)]:
            max_len = max(max_len, len(str(cell.value or "")))
        sheet.column_dimensions[get_column_letter(column)].width = min(max_len + 2, 36)
    sheet.freeze_panes = "A2"


def _vms_by_cluster(vms: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for vm in vms:
        grouped[_cluster_key(vm.get("labels", {}))].append(vm)
    return grouped


def _top_vms(vms: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    key = (lambda vm: vm.get("growth_ratio") or 0) if mode == "ratio" else (lambda vm: vm.get("growth_amount") or 0)
    return sorted(vms, key=key, reverse=True)[:100]


def _vm_row(vm: dict[str, Any], include_cluster: bool, raw: bool = False) -> list[Any]:
    labels = vm.get("labels", {})
    forecast = vm.get("forecast", {})
    ratio = vm.get("growth_ratio")
    values: list[Any] = []
    if include_cluster:
        values.extend([labels.get("tower") or labels.get("tower_id") or "-", labels.get("cluster") or labels.get("cluster_id") or "-"])
    values.extend(
        [
            labels.get("vm") or labels.get("vm_id") or "-",
            forecast.get("current") or 0,
            vm.get("previous_value") or 0,
            vm.get("growth_amount") or 0,
            ratio if ratio is not None else "",
        ]
    )
    if raw:
        return values
    formatted = [str(values[0])]
    formatted.extend(_format_bytes(value) for value in values[1:4])
    formatted.append(_format_percent(ratio))
    return formatted


def _cluster_title(labels: dict[str, Any]) -> str:
    tower = labels.get("tower") or labels.get("tower_id") or "Tower"
    cluster = labels.get("cluster") or labels.get("cluster_id") or "集群"
    return f"{tower} / {cluster}"


def _cluster_key(labels: dict[str, Any]) -> tuple[str, str]:
    return (str(labels.get("tower_id") or ""), str(labels.get("cluster_id") or ""))


def _monthly_growth(cluster: dict[str, Any]) -> float:
    forecast = cluster.get("forecast", {})
    return max(0.0, float(forecast.get("slope_per_day") or 0) * 30)


def _format_bytes(value: Any) -> str:
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        size = 0
    if size <= 0:
        return "0 B"
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    return f"{size:.0f} {units[index]}" if index < 3 else f"{size:.2f} {units[index]}"


def _format_percent(value: Any) -> str:
    try:
        if value is None:
            return "-"
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{numeric * 100:.2f}%"


def _format_days(value: Any) -> str:
    try:
        if value is None:
            return "未触发"
        return f"{float(value):.0f} 天"
    except (TypeError, ValueError):
        return "未触发"


def _first_label(clusters: list[dict[str, Any]], key: str) -> str | None:
    for cluster in clusters:
        value = cluster.get("labels", {}).get(key)
        if value:
            return str(value)
    return None


def _safe_sheet_name(value: str) -> str:
    invalid = set('[]:*?/\\')
    cleaned = "".join("_" if char in invalid else char for char in str(value))
    return (cleaned or "集群")[:31]


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "-" for char in value)[:48]


def _docx_bytes(document: Document) -> bytes:
    output = BytesIO()
    document.save(output)
    return output.getvalue()
