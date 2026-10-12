from __future__ import annotations

"""Excel (xlsx) report builder and template writers."""

from copy import copy
from io import BytesIO
from pathlib import Path
from typing import Any
from openpyxl.chart import BarChart, Reference
from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.drawing.image import Image as XlsxImage
from openpyxl.styles import Alignment, Border, Color, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.worksheet.table import Table, TableStyleInfo
from app.v2.config import V2Settings

from .common import (
    ReportPeriodProfile, _capacity_risk_summary, _cluster_full_name, _cluster_key, _cluster_name, _cluster_period_growth, _cluster_scope_label, _cluster_used_ratio,
    _customer_growth_vms, _customer_key_findings, _data_quality_status_message, _data_quality_summary_rows, _days_label, _effective_report_window, _export_context, _float_or_none,
    _growth_rate_method_lines, _is_alert_vm, _line_chart_image, _merged_cluster_points, _overall_risk_status, _parse_report_datetime, _percent_label, _period_window_label, _persist_report, _report_data_quality,
    _risk_level, _top_vms, _tower_scope_label, _vm_sample_window_label, _vms_by_cluster, ACCENT, ACCENT_DARK, ACCENT_LIGHT,
    ACCENT_SOFT, GROWTH_BLUE, RATIO_ORANGE, RATIO_RED, REPORT_COVER_SUBTITLE, REPORT_COVER_TITLE, REPORT_PRODUCT_NAME,
    TEXT_DARK, TEXT_MUTED, USAGE_CRITICAL_RATIO, USAGE_WARNING_RATIO,
    VM_ALERT_FILL, XLSX_CLUSTER_TEMPLATE_SHEET, XLSX_FONT_NAME, XLSX_TEMPLATE_PATH,
)

BORDER_SOLID_GRAY = Side(style="thin", color="64748B")
BORDER_HEADER_DARK = Side(style="medium", color="0F2942")
DATA_BORDER = Border(
    left=BORDER_SOLID_GRAY,
    right=BORDER_SOLID_GRAY,
    top=BORDER_SOLID_GRAY,
    bottom=BORDER_SOLID_GRAY,
)
HEADER_BORDER = Border(
    left=Side(style="thin", color="0F2942"),
    right=Side(style="thin", color="0F2942"),
    top=BORDER_HEADER_DARK,
    bottom=BORDER_HEADER_DARK,
)

RISK_BADGES = {
    "高": {
        "fill": PatternFill(fill_type="solid", fgColor="FDE8E8"),
        "font": Font(name=XLSX_FONT_NAME, size=12, bold=True, color="C5221F"),
    },
    "高风险": {
        "fill": PatternFill(fill_type="solid", fgColor="FDE8E8"),
        "font": Font(name=XLSX_FONT_NAME, size=12, bold=True, color="C5221F"),
    },
    "中": {
        "fill": PatternFill(fill_type="solid", fgColor="FEF3D6"),
        "font": Font(name=XLSX_FONT_NAME, size=12, bold=True, color="B06000"),
    },
    "中风险": {
        "fill": PatternFill(fill_type="solid", fgColor="FEF3D6"),
        "font": Font(name=XLSX_FONT_NAME, size=12, bold=True, color="B06000"),
    },
    "低": {
        "fill": PatternFill(fill_type="solid", fgColor="EAF7EF"),
        "font": Font(name=XLSX_FONT_NAME, size=12, bold=False, color="188038"),
    },
    "正常": {
        "fill": PatternFill(fill_type="solid", fgColor="EAF7EF"),
        "font": Font(name=XLSX_FONT_NAME, size=12, bold=False, color="188038"),
    },
}

def _is_numeric_column(header_text: str, cell_val: Any) -> bool:
    h = str(header_text or "")
    if any(k in h for k in ["容量", "增长量", "增长率", "使用率", "预测", "率", "已分配"]):
        return True
    s = str(cell_val or "").strip()
    if s.endswith("%"):
        return True
    parts = s.split()
    if len(parts) >= 2 and parts[-1] in ["B", "KiB", "MiB", "GiB", "TiB", "PiB", "KB", "MB", "GB", "TB", "PB"]:
        return True
    return False

def _is_center_column(header_text: str, cell_val: Any) -> bool:
    h = str(header_text or "")
    if any(k in h for k in ["排名", "风险", "状态", "耗尽", "天数", "时间"]):
        return True
    s = str(cell_val or "").strip()
    if s in RISK_BADGES:
        return True
    if s.endswith("天") or s == "未触发":
        return True
    return False

def _column_alignment(header_text: str, cell_val: Any, *, is_header: bool = False) -> Alignment:
    if is_header:
        return Alignment(horizontal="center", vertical="center", wrap_text=True)
    if _is_numeric_column(header_text, cell_val):
        return Alignment(horizontal="right", vertical="center", wrap_text=False)
    if _is_center_column(header_text, cell_val):
        return Alignment(horizontal="center", vertical="center", wrap_text=False)
    return Alignment(horizontal="left", vertical="center", wrap_text=False)

def build_report_xlsx(report: dict[str, Any], settings: V2Settings, *, period_days: int) -> tuple[bytes, str, Path, str]:
    context = _export_context(report, settings, period_days, "xlsx")
    clusters = report.get("clusters") or []
    month_vms = report.get("month_fastest_growing_vms") or []
    profile = context["profile"]
    workbook = _load_customer_xlsx_template()
    _write_xlsx_template_cover(workbook["封面"], report, context, settings)
    _write_xlsx_template_summary(workbook["执行摘要"], report, context, clusters, settings, profile)
    quality_sheet = _get_or_create_sheet_after(workbook, "数据质量说明", after="执行摘要")
    _write_xlsx_data_quality_sheet(quality_sheet, report, context)
    _write_xlsx_template_capacity_trend(workbook["容量趋势"], report, context, clusters, profile)
    top_sheet = workbook["VM增长TOP20"] if "VM增长TOP20" in workbook.sheetnames else _get_or_create_sheet(workbook, "VM增长TOP100")
    top_sheet.title = "VM增长TOP100"
    _write_xlsx_template_vm_top100(top_sheet, _customer_growth_vms(report), report, profile)
    day_growth_sheet = workbook["日增长详情"]
    day_growth_sheet.sheet_properties.tabColor = None
    _write_xlsx_template_growth_detail(
        day_growth_sheet,
        report.get("day_fastest_growing_vms") or [],
        report,
        title="日增长最快虚拟机",
        growth_header="日增长量",
    )
    month_growth_sheet = _get_or_create_sheet_after(workbook, "月增长详情", after="日增长详情")
    _write_xlsx_template_growth_detail(
        month_growth_sheet,
        report.get("month_fastest_growing_vms") or [],
        report,
        title="月增长最快虚拟机",
        growth_header="月增长量",
    )

    _write_simple_vm_sheet(_get_or_create_sheet(workbook, "本日新建VM"), report.get("day_new_vms") or [], "暂无本日新建 VM", include_growth=False)
    _write_simple_vm_sheet(_get_or_create_sheet(workbook, "本月新建VM"), report.get("month_new_vms") or [], "暂无本月新建 VM", include_growth=False)
    vms_by_cluster = _vms_by_cluster(month_vms)
    for cluster in clusters:
        labels = cluster.get("labels", {})
        cluster_name = labels.get("cluster") or labels.get("cluster_id") or "集群"
        tab_name = f"集群-{cluster_name}" if not str(cluster_name).startswith("集群") else str(cluster_name)
        sheet = _clone_cluster_template_sheet(
            workbook,
            _safe_sheet_name(tab_name),
        )
        _write_cluster_vm_sheet(sheet, cluster, vms_by_cluster.get(_cluster_key(labels), []), report, profile)
    _remove_sheets(workbook, ["目录", "范围明细", "集群汇总", "VM_TOP100_汇总", "汇总", XLSX_CLUSTER_TEMPLATE_SHEET])
    _normalize_xlsx_fonts(workbook)
    _apply_xlsx_tab_colors(workbook)
    _apply_xlsx_page_footers(workbook)
    if "执行摘要" in workbook.sheetnames:
        workbook.active = workbook["执行摘要"]

    output = BytesIO()
    workbook.save(output)
    return _persist_report(output.getvalue(), settings, context["filename"])


def _load_customer_xlsx_template() -> Workbook:
    if XLSX_TEMPLATE_PATH.exists():
        return load_workbook(XLSX_TEMPLATE_PATH)
    workbook = Workbook()
    workbook.active.title = "封面"
    for name in ["执行摘要", "容量趋势", "VM增长TOP20", "日增长详情"]:
        workbook.create_sheet(name)
    return workbook


def _get_or_create_sheet(workbook: Workbook, name: str):
    return workbook[name] if name in workbook.sheetnames else workbook.create_sheet(name)


def _get_or_create_sheet_after(workbook: Workbook, name: str, *, after: str):
    if name in workbook.sheetnames:
        sheet = workbook[name]
        current_index = workbook._sheets.index(sheet)
        target_index = workbook.sheetnames.index(after) + 1
        if current_index != target_index:
            workbook._sheets.pop(current_index)
            workbook._sheets.insert(target_index, sheet)
        return sheet
    return workbook.create_sheet(name, workbook.sheetnames.index(after) + 1)


def _clone_cluster_template_sheet(workbook: Workbook, name: str):
    if name in workbook.sheetnames:
        workbook.remove(workbook[name])
    if XLSX_CLUSTER_TEMPLATE_SHEET in workbook.sheetnames:
        sheet = workbook.copy_worksheet(workbook[XLSX_CLUSTER_TEMPLATE_SHEET])
        sheet.title = name
        sheet.sheet_state = "visible"
        return sheet
    return workbook.create_sheet(name)


def _remove_sheets(workbook: Workbook, names: list[str]) -> None:
    for name in names:
        if name in workbook.sheetnames and len(workbook.sheetnames) > 1:
            workbook.remove(workbook[name])


def _clear_xlsx_sheet(sheet) -> None:
    for row in sheet.iter_rows():
        for cell in row:
            if not isinstance(cell, MergedCell):
                cell.value = None


def _clear_xlsx_tables(sheet) -> None:
    for name in list(sheet.tables.keys()):
        del sheet.tables[name]


def _reset_xlsx_sheet_rows(sheet) -> None:
    for merged_range in list(sheet.merged_cells.ranges):
        sheet.unmerge_cells(str(merged_range))
    if sheet.max_row:
        sheet.delete_rows(1, sheet.max_row)


def _set_xlsx_cell(sheet, coordinate: str, value: Any, *, size: float | None = None, bold: bool | None = None, color: str | None = None, align: str | None = None) -> None:
    cell = sheet[coordinate]
    cell.value = value
    cell.font = Font(
        name="Noto Sans CJK SC",
        size=size if size is not None else cell.font.sz,
        bold=bold if bold is not None else cell.font.bold,
        color=color if color is not None else cell.font.color,
    )
    if align is not None:
        cell.alignment = Alignment(horizontal=align, vertical="center", wrap_text=True)


def _format_first_seen_time(val: Any) -> str:
    if not val:
        return "-"
    s = str(val).strip()
    if not s or s == "-":
        return "-"
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        s_clean = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s_clean)
        if dt.tzinfo is not None:
            local_dt = dt.astimezone(ZoneInfo("Asia/Shanghai"))
        else:
            local_dt = dt
        return local_dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        if "T" in s:
            return s.replace("T", " ").split("+")[0].split(".")[0]
        return s


def _write_xlsx_template_cover(sheet, report: dict[str, Any], context: dict[str, Any], settings: V2Settings) -> None:
    clusters = report.get("clusters") or []
    _clear_xlsx_sheet(sheet)
    _set_xlsx_cell(sheet, "B7", REPORT_PRODUCT_NAME, size=14, color=GROWTH_BLUE, align="center")
    _set_xlsx_cell(sheet, "B8", REPORT_COVER_TITLE, size=26, bold=True, color=ACCENT_DARK, align="center")
    _set_xlsx_cell(sheet, "B9", REPORT_COVER_SUBTITLE, size=12, color=TEXT_MUTED, align="center")
    _set_xlsx_cell(sheet, "B11", "───────────────────────────────────────────────────────", size=7, color="CCCCCC", align="center")
    _set_xlsx_cell(sheet, "B13", "客户名称：", size=12, color="555555", align="center")
    _set_xlsx_cell(sheet, "B14", f"Tower范围：{_tower_scope_label(clusters, context['scope_label'])}", size=12, color="555555", align="center")
    _set_xlsx_cell(sheet, "B15", f"集群范围：{_cluster_scope_label(clusters, context['scope_label'])}", size=12, color="555555", align="center")
    _set_xlsx_cell(sheet, "B16", f"统计窗口：{_period_window_label(report)}", size=12, color="555555", align="center")


def _write_xlsx_template_summary(
    sheet,
    report: dict[str, Any],
    context: dict[str, Any],
    clusters: list[dict[str, Any]],
    settings: V2Settings,
    profile: ReportPeriodProfile,
) -> None:
    _clear_xlsx_sheet(sheet)
    current = sum(float((cluster.get("forecast") or {}).get("current") or 0) for cluster in clusters)
    allocated = sum(float(cluster.get("allocated") or 0) for cluster in clusters)
    forecast_90d = sum(float((cluster.get("forecast") or {}).get("forecast_90d") or 0) for cluster in clusters)
    total = sum(float(cluster.get("total") or 0) for cluster in clusters)
    growth = sum(_cluster_period_growth(cluster, profile.days) for cluster in clusters)
    risk_status, _, risk_note = _overall_risk_status(clusters)
    growth_ratio = growth / max(current - growth, 1) if growth > 0 else 0.0
    usage_ratio = current / total if total else 0.0
    allocated_ratio = allocated / total if total else 0.0
    forecast_ratio = forecast_90d / total if total else 0.0

    _set_xlsx_cell(sheet, "A1", "一、执行摘要", size=16, bold=True, color=ACCENT_DARK)
    _set_xlsx_cell(
        sheet,
        "A2",
        f"报告周期：{_period_window_label(report)}  |  Tower：{_tower_scope_label(clusters, context['scope_label'])}  |  集群：{_cluster_scope_label(clusters, context['scope_label'])}  |  统计口径：{profile.window_growth_label}",
        size=10,
        color=TEXT_MUTED,
    )
    headers = ["当前已用容量", "已分配容量", profile.window_growth_label, "90 天预测容量", "风险状态"]
    values = [_xlsx_bytes_label(current), _xlsx_bytes_label(allocated), _xlsx_signed_bytes_label(growth), _xlsx_bytes_label(forecast_90d), risk_status]
    subtitles = [
        f"使用率 {_percent_label(usage_ratio)}",
        f"已分配率 {_percent_label(allocated_ratio)}" if total else "-",
        f"增长率 {_percent_label(growth_ratio)}",
        f"预计使用率 {_percent_label(forecast_ratio)}",
        risk_note,
    ]
    for column, (header, value, subtitle) in enumerate(zip(headers, values, subtitles), start=1):
        for row in [4, 5, 6]:
            cell = sheet.cell(row=row, column=column)
            cell.fill = PatternFill(fill_type="solid", fgColor=ACCENT_LIGHT)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = DATA_BORDER
        sheet.cell(row=4, column=column).value = header
        sheet.cell(row=4, column=column).font = Font(name=XLSX_FONT_NAME, size=11, bold=True, color="000000")
        sheet.cell(row=5, column=column).value = value
        sheet.cell(row=5, column=column).font = Font(name=XLSX_FONT_NAME, size=18, bold=True, color=RATIO_RED if risk_status == "高风险" and column == 5 else ACCENT_DARK)
        sheet.cell(row=6, column=column).value = subtitle
        sheet.cell(row=6, column=column).font = Font(name=XLSX_FONT_NAME, size=11, bold=True, color="000000")

    _set_xlsx_cell(sheet, "A8", "关键发现", size=14, bold=True, color=ACCENT_DARK)
    findings = _customer_key_findings(clusters, _customer_growth_vms(report), risk_note, context)
    for offset, finding in enumerate(findings[:4], start=9):
        _set_xlsx_cell(sheet, f"A{offset}", finding, size=12, color="0F172A")
    _set_xlsx_cell(sheet, "A13", "容量风险摘要", size=14, bold=True, color=ACCENT_DARK)
    _set_xlsx_cell(sheet, "A14", _capacity_risk_summary(report), size=12, color="0F172A")
    _set_xlsx_cell(sheet, "A15", f"当前软件版本：{settings.app_version}", size=10, color=TEXT_MUTED)
    _set_xlsx_cell(sheet, "A16", _profile_sample_notice(report, profile), size=10, color=TEXT_MUTED)
    _set_xlsx_cell(
        sheet,
        "A17",
        "虚拟机容量口径说明：分配空间为虚拟机虚拟磁盘供给总容量（精简置备配置上限），当前容量为实际已占用的物理存储，使用率 = 当前容量 / 分配空间。",
        size=10,
        color=TEXT_MUTED,
    )
    _set_xlsx_cell(sheet, "A18", "容量增长速率口径", size=14, bold=True, color=ACCENT_DARK)
    growth_lines = list(_growth_rate_method_lines(report))
    for offset, line in enumerate(growth_lines, start=19):
        _set_xlsx_cell(sheet, f"A{offset}", line, size=10, color=TEXT_DARK)
    disclaimer_row = 19 + len(growth_lines) + 1
    _set_xlsx_cell(
        sheet,
        f"A{disclaimer_row}",
        "声明：预测结果基于历史增长趋势推算，预测值可能会有偏差，仅供参考，请以实际使用情况为准。",
        size=10,
        color=TEXT_MUTED,
    )
    for row in [1, 2, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, disclaimer_row]:
        _merge_title_row(sheet, row, 1, 6)
    for column, width in {"A": 26, "B": 24, "C": 24, "D": 24, "E": 26, "F": 16}.items():
        sheet.column_dimensions[column].width = width
    for row, height in {
        1: 30,
        2: 38,
        3: 15,
        4: 24,
        5: 36,
        6: 28,
        7: 15,
        8: 30,
        9: 38,
        10: 38,
        11: 38,
        12: 38,
        13: 15,
        14: 15,
        15: 15,
        16: 38,
        17: 24,
        18: 26,
        19: 28,
        20: 28,
        21: 28,
    }.items():
        sheet.row_dimensions[row].height = height


def _write_xlsx_template_capacity_trend(sheet, report: dict[str, Any], context: dict[str, Any], clusters: list[dict[str, Any]], profile: ReportPeriodProfile) -> None:
    _reset_xlsx_sheet_rows(sheet)
    sheet.append(["二、集群容量趋势"])
    sheet.append([f"统计窗口：{_period_window_label(report)}；{_profile_sample_notice(report, profile)}"])
    headers = ["Tower", "集群", "当前已用容量", profile.window_growth_label, "90 天预测容量", "总容量", "已分配容量", "已分配率", "使用率", "预计耗尽天数", "风险状态"]
    sheet.append(headers)
    if not clusters:
        sheet.append(["当前范围暂无集群容量数据"] + [""] * (len(headers) - 1))
    for cluster in clusters:
        labels = cluster.get("labels") or {}
        forecast = cluster.get("forecast") or {}
        risk, _ = _risk_level(cluster)
        total = float(cluster.get("total") or 0)
        allocated = float(cluster.get("allocated") or 0)
        allocated_ratio = allocated / total if total else 0.0
        sheet.append(
            [
                labels.get("tower") or labels.get("tower_id") or "",
                labels.get("cluster") or labels.get("cluster_id") or "",
                _xlsx_bytes_label(forecast.get("current")),
                _xlsx_signed_bytes_label(_cluster_period_growth(cluster, profile.days)),
                _xlsx_bytes_label(forecast.get("forecast_90d")),
                _xlsx_bytes_label(cluster.get("total")),
                _xlsx_bytes_label(allocated),
                _percent_label(allocated_ratio),
                _percent_label(_cluster_used_ratio(cluster)),
                _days_label(forecast.get("exhaustion_days")),
                risk,
            ]
        )
    _style_customer_xlsx_table(sheet, title_rows={1, 2}, header_rows={3})
    _apply_usage_ratio_colors(sheet, [9], 4, sheet.max_row)
    _merge_title_row(sheet, 1, 1, len(headers))
    _merge_title_row(sheet, 2, 1, len(headers))
    sheet.freeze_panes = "A4"
    sheet.auto_filter.ref = f"A3:{get_column_letter(len(headers))}{sheet.max_row}"
    for column, width in {
        "A": 28,
        "B": 26,
        "C": 22,
        "D": 25,
        "E": 22,
        "F": 20,
        "G": 22,
        "H": 18,
        "I": 16,
        "J": 20,
        "K": 16,
    }.items():
        sheet.column_dimensions[column].width = width
    sheet.row_dimensions[1].height = 32
    sheet.row_dimensions[2].height = 42
    sheet.row_dimensions[3].height = 30
    for row_index in range(4, sheet.max_row + 1):
        sheet.row_dimensions[row_index].height = 26

    _add_capacity_trend_chart(sheet, clusters)
    _setup_xlsx_print_layout(sheet)


def _add_capacity_trend_chart(sheet, clusters: list[dict[str, Any]]) -> None:
    points = _merged_cluster_points(clusters)
    image = _line_chart_image(points, "集群容量使用趋势", "容量 (TiB)")
    if image is None:
        return
    anchor_row = sheet.max_row + 2
    xlsx_image = XlsxImage(image)
    xlsx_image.width = 750
    xlsx_image.height = 420
    sheet.add_image(xlsx_image, f"A{anchor_row}")


def _setup_xlsx_print_layout(sheet) -> None:
    sheet.print_area = f"A1:{get_column_letter(sheet.max_column)}{sheet.max_row}"
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToPage = True
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)


def _write_xlsx_data_quality_sheet(sheet, report: dict[str, Any], context: dict[str, Any]) -> None:
    _reset_xlsx_sheet_rows(sheet)
    quality = _report_data_quality(report)
    summary_rows = _data_quality_summary_rows(report, quality)
    sheet.append(["数据质量说明"])
    sheet.append([_data_quality_status_message(quality)])
    sheet.append(["指标", "说明"])
    for label, value in summary_rows:
        sheet.append([label, value])

    incomplete_clusters = quality.get("incomplete_clusters") or []
    start_row = sheet.max_row + 2
    sheet.cell(row=start_row, column=1).value = "数据不完整集群"
    sheet.cell(row=start_row + 1, column=1).value = "Tower"
    sheet.cell(row=start_row + 1, column=2).value = "集群"
    sheet.cell(row=start_row + 1, column=3).value = "原因"
    if incomplete_clusters:
        for item in incomplete_clusters:
            sheet.append([
                item.get("tower") or item.get("tower_id") or "-",
                item.get("cluster") or item.get("cluster_id") or "-",
                item.get("reason") or "-",
            ])
    else:
        sheet.append(["-", "-", "当前报表范围内未发现明显数据不完整集群"])

    _style_customer_xlsx_table(sheet, title_rows={1, 2, start_row}, header_rows={3, start_row + 1})
    _merge_title_row(sheet, 1, 1, 3)
    _merge_title_row(sheet, 2, 1, 3, align="left")
    _merge_title_row(sheet, 3, 2, 3, align="left")
    for r in range(4, start_row - 1):
        _merge_title_row(sheet, r, 2, 3, align="left")
    _merge_title_row(sheet, start_row, 1, 3)
    sheet.freeze_panes = "A4"
    sheet.column_dimensions["A"].width = 28
    sheet.column_dimensions["B"].width = 44
    sheet.column_dimensions["C"].width = 58
    sheet.row_dimensions[1].height = 32
    sheet.row_dimensions[2].height = 52
    sheet.row_dimensions[3].height = 30
    sheet.row_dimensions[start_row].height = 32
    sheet.row_dimensions[start_row + 1].height = 30
    for row_index in range(4, sheet.max_row + 1):
        if row_index == start_row - 1:
            sheet.row_dimensions[row_index].height = 16
        elif row_index not in {start_row, start_row + 1}:
            sheet.row_dimensions[row_index].height = 26


def _write_xlsx_template_vm_top100(sheet, vms: list[dict[str, Any]], report: dict[str, Any], profile: ReportPeriodProfile) -> None:
    _reset_xlsx_sheet_rows(sheet)
    window_label = _vm_sample_window_label(vms, report)
    # Phase 74：每侧 +2 列（分配空间/使用率）——左侧 1..11，分隔列 12，右侧 13..22。
    RIGHT_START = 13
    sheet.append([f"三、{profile.vm_growth_title}全部虚拟机（{window_label}）", *([""] * 11), "四、虚拟机增长率全部虚拟机"])
    sheet.append([
        "* 注：周期初始容量指统计周期起始时虚拟机的物理占用容量；若机器在周期内新建，则为建机首次采样容量。",
        *([""] * 5),
        "向右滑动查看增长率榜单 ▶",
        *([""] * 4),
        "",
        "* 注：周期初始容量指统计周期起始时虚拟机的物理占用容量；若机器在周期内新建，则为建机首次采样容量。",
        *([""] * 5),
        "◀ 向左滑动返回增长量榜单",
        *([""] * 3),
    ])
    sheet.append(["按增长量降序", *([""] * 11), "按增长率降序"])
    amount_headers = ["排名", "虚拟机名称", "所有者", "虚拟机组", "分配空间", "当前容量", "使用率", "周期初始容量", "增长量", "增长率", "风险"]
    ratio_headers = ["排名", "虚拟机名称", "所有者", "虚拟机组", "分配空间", "当前容量", "使用率", "周期初始容量", "增长量", "增长率"]
    for index, value in enumerate(amount_headers, start=1):
        sheet.cell(row=4, column=index).value = value
    for index, value in enumerate(ratio_headers, start=RIGHT_START):
        sheet.cell(row=4, column=index).value = value
    amount_vms = _top_vms(vms, "amount")
    ratio_vms = _top_vms(vms, "ratio")
    if not amount_vms and not ratio_vms:
        sheet.cell(row=5, column=1).value = profile.vm_empty_text
    for row_index, vm in enumerate(amount_vms, start=5):
        for column, value in enumerate(_xlsx_vm_display_row(vm, row_index - 4, include_risk=True), start=1):
            sheet.cell(row=row_index, column=column).value = value
    for row_index, vm in enumerate(ratio_vms, start=5):
        for column, value in enumerate(_xlsx_vm_display_row(vm, row_index - 4, include_risk=False), start=RIGHT_START):
            sheet.cell(row=row_index, column=column).value = value
    _style_customer_xlsx_table(sheet, title_rows={1, 2, 3}, header_rows={4})
    _apply_vm_top100_layout(sheet, left_header_row=4, right_header_row=4)
    _apply_usage_ratio_colors(sheet, [7, 19], 5, sheet.max_row)
    sheet.freeze_panes = "A5"
    sheet.sheet_view.topLeftCell = "A1"
    for selection in sheet.sheet_view.selection:
        selection.activeCell = "A5"
        selection.sqref = "A5"


def _write_xlsx_template_growth_detail(
    sheet,
    vms: list[dict[str, Any]],
    report: dict[str, Any],
    *,
    title: str,
    growth_header: str,
) -> None:
    _reset_xlsx_sheet_rows(sheet)
    sheet.append([f"{title}（{_period_window_label(report)}）"])
    sheet.append(["* 注：周期初始容量指统计周期起始时虚拟机的物理占用容量；若机器在周期内新建，则为建机首次采样容量。"])
    # Phase 74：加入「分配空间」「使用率」两列（11→13）
    headers = ["排名", "虚拟机名称", "所有者", "虚拟机组", "Tower", "集群", "分配空间", "当前容量", "使用率", "周期初始容量", growth_header, "增长率", "风险"]
    sheet.append(headers)
    if not vms:
        sheet.append(["暂无日增长 VM 数据"])
    for index, vm in enumerate(vms, start=1):
        row = _xlsx_vm_display_row(vm, index, include_risk=True)
        labels = vm.get("labels") or {}
        sheet.append([row[0], row[1], row[2], row[3], labels.get("tower") or labels.get("tower_id") or "", labels.get("cluster") or labels.get("cluster_id") or "", *row[4:]])
    _style_customer_xlsx_table(sheet, title_rows={1, 2}, header_rows={3})
    _merge_title_row(sheet, 1, 1, 13)
    _merge_title_row(sheet, 2, 1, 13, align="left")
    sheet["A1"].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet["A2"].font = Font(name=XLSX_FONT_NAME, size=12, color="334155")
    sheet["A2"].alignment = Alignment(horizontal="left", vertical="center")
    _apply_usage_ratio_colors(sheet, [9], 4, sheet.max_row)
    sheet.freeze_panes = "A4"
    sheet.auto_filter.ref = f"A3:{get_column_letter(len(headers))}{sheet.max_row}"
    for column, width in {
        "A": 12,
        "B": 50,
        "C": 16,
        "D": 20,
        "E": 20,
        "F": 22,
        "G": 18,
        "H": 18,
        "I": 14,
        "J": 18,
        "K": 24,
        "L": 16,
        "M": 14,
    }.items():
        sheet.column_dimensions[column].width = width
    sheet.row_dimensions[1].height = 30
    sheet.row_dimensions[2].height = 24
    sheet.row_dimensions[3].height = 24
    for row_index in range(4, sheet.max_row + 1):
        sheet.row_dimensions[row_index].height = 22


def _style_customer_xlsx_table(sheet, *, title_rows: set[int] | None = None, header_rows: set[int] | None = None) -> None:
    title_rows = title_rows or set()
    header_rows = header_rows or {1}

    # 关闭外部网格线干扰，突出内部清晰实线边框
    if hasattr(sheet, "sheet_view"):
        sheet.sheet_view.showGridLines = False
    if getattr(sheet, "views", None) and sheet.views.sheetView:
        sheet.views.sheetView[0].showGridLines = False

    header_map: dict[int, str] = {}
    for h_row in sorted(header_rows):
        for cell in sheet[h_row]:
            if cell.value:
                header_map[cell.column] = str(cell.value).strip()

    for row in sheet.iter_rows():
        r = row[0].row if row else 0
        if r not in title_rows and r not in header_rows and all(c.value is None for c in row):
            continue

        for cell in row:
            if isinstance(cell, MergedCell):
                continue
            r = cell.row
            c = cell.column
            val = cell.value

            if r in title_rows:
                cell.font = Font(name=XLSX_FONT_NAME, size=16 if r == 1 else 13, bold=True, color=ACCENT_DARK)
                cell.alignment = Alignment(vertical="center", wrap_text=True)
                continue

            col_header = header_map.get(c, "")
            if r in header_rows:
                cell.font = Font(name=XLSX_FONT_NAME, size=12, bold=True, color="FFFFFF")
                cell.fill = PatternFill(fill_type="solid", fgColor=ACCENT_DARK)
                cell.border = HEADER_BORDER
                cell.alignment = _column_alignment(col_header, val, is_header=True)
            else:
                cell.font = Font(name=XLSX_FONT_NAME, size=12, color="0F172A")
                cell.border = DATA_BORDER
                s_val = str(val or "").strip()
                if s_val in RISK_BADGES:
                    cell.fill = RISK_BADGES[s_val]["fill"]
                    cell.font = RISK_BADGES[s_val]["font"]
                elif r % 2 == 0:
                    cell.fill = PatternFill(fill_type="solid", fgColor=ACCENT_SOFT)
                else:
                    cell.fill = PatternFill(fill_type="solid", fgColor="FFFFFF")

                # 说明/原因列统一步调居左，不被数字百分比打乱
                if col_header in {"说明", "原因"}:
                    cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=False)
                else:
                    cell.alignment = _column_alignment(col_header, val, is_header=False)


def _merge_title_row(sheet, row: int, start_col: int, end_col: int, *, align: str | None = None) -> None:
    if end_col <= start_col:
        return
    range_ref = f"{get_column_letter(start_col)}{row}:{get_column_letter(end_col)}{row}"
    if range_ref not in {str(merged) for merged in sheet.merged_cells.ranges}:
        sheet.merge_cells(range_ref)
    cell = sheet.cell(row=row, column=start_col)
    if align:
        cell.alignment = Alignment(horizontal=align, vertical="center", wrap_text=True)
    else:
        cell.alignment = Alignment(vertical="center", wrap_text=True)


def _apply_vm_top100_layout(sheet, *, left_header_row: int, right_header_row: int | None = None) -> None:
    widths = {
        "A": 15.83203125,   # 排名
        "B": 50,            # 虚拟机名称
        "C": 16,            # 所有者（Phase 69）
        "D": 20,            # 虚拟机组（Phase 69）
        "E": 18,            # 分配空间（Phase 74）
        "F": 18,            # 当前容量
        "G": 14,            # 使用率（Phase 74）
        "H": 18,            # 周期初始容量
        "I": 22,            # 增长量
        "J": 14,            # 增长率
        "K": 10,            # 风险
        "L": 10,            # 分隔列
        "M": 15.83203125,
        "N": 50,
        "O": 16,
        "P": 20,
        "Q": 18,
        "R": 18,
        "S": 14,
        "T": 18,
        "U": 22,
        "V": 14,
    }
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width
    for row_index in range(1, sheet.max_row + 1):
        if row_index == 1:
            sheet.row_dimensions[row_index].height = 34
        elif row_index == 2:
            sheet.row_dimensions[row_index].height = 24
        elif row_index == 3:
            sheet.row_dimensions[row_index].height = 34
        elif row_index in {left_header_row, right_header_row}:
            sheet.row_dimensions[row_index].height = 28
            for c_idx in range(1, 23):
                cell = sheet.cell(row=row_index, column=c_idx)
                if c_idx == 12:
                    continue
                cell.border = HEADER_BORDER
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        else:
            sheet.row_dimensions[row_index].height = 26
            for c_idx in range(1, 23):
                cell = sheet.cell(row=row_index, column=c_idx)
                if isinstance(cell, MergedCell) or c_idx == 12:
                    continue
                cell.font = Font(name=XLSX_FONT_NAME, size=12, color="0F172A")
                cell.border = DATA_BORDER
                s_val = str(cell.value or "").strip()
                if s_val in RISK_BADGES:
                    cell.fill = RISK_BADGES[s_val]["fill"]
                    cell.font = RISK_BADGES[s_val]["font"]
                elif row_index % 2 == 0:
                    cell.fill = PatternFill(fill_type="solid", fgColor=ACCENT_SOFT)
                else:
                    cell.fill = PatternFill(fill_type="solid", fgColor="FFFFFF")

                if c_idx in {5, 6, 7, 8, 9, 10, 17, 18, 19, 20, 21, 22}:
                    cell.alignment = Alignment(horizontal="right", vertical="center", wrap_text=False)
                elif c_idx in {1, 11, 13}:
                    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=False)
                    if c_idx in {1, 13} and row_index in {5, 6, 7}:
                        cell.font = Font(name=XLSX_FONT_NAME, size=12, bold=True, color="1D4ED8")
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=False)
    # Phase 74/75：每侧 11/10 列后——左侧合并 1..11、右侧 13..22、分隔列 12（L）
    _merge_title_row(sheet, 1, 1, 11)
    if sheet.cell(row=1, column=13).value:
        _merge_title_row(sheet, 1, 13, 22)
    # 第 2 行：左侧放置「周期初始容量说明」（第 1..6 列 A~F，宽度 137.8），右侧放置「向右滑动查看增长率榜单 ➡」（第 7..11 列 G~K，宽度 78.0）
    _merge_title_row(sheet, 2, 1, 6, align="left")
    sheet.cell(row=2, column=1).font = Font(name=XLSX_FONT_NAME, size=12, color="334155")

    # 统一滑动提示卡片样式（与集群专属 Sheet 完全一致的底纹、边框与配色）
    card_fill = PatternFill(fill_type="solid", fgColor="EFF6FF")
    card_border_side = Side(border_style="thin", color="BFDBFE")
    card_border = Border(
        left=card_border_side,
        right=card_border_side,
        top=card_border_side,
        bottom=card_border_side,
    )
    card_font = Font(name=XLSX_FONT_NAME, size=13, bold=True, color="1D4ED8")
    card_align = Alignment(horizontal="center", vertical="center")

    sheet.cell(row=2, column=7).value = "向右滑动查看增长率榜单 ▶"
    _merge_title_row(sheet, 2, 7, 11, align="center")
    for c_idx in range(7, 12):
        cell_item = sheet.cell(row=2, column=c_idx)
        cell_item.fill = card_fill
        cell_item.border = card_border
    sheet.cell(row=2, column=7).font = card_font
    sheet.cell(row=2, column=7).alignment = card_align

    # 右侧第 13..18 列（M~R，宽度 137.8）放置「周期初始容量说明」，第 19..22 列（S~V，宽度 68.0）放置「◀ 向左滑动返回增长量榜单」
    sheet.cell(row=2, column=13).value = "* 注：周期初始容量指统计周期起始时虚拟机的物理占用容量；若机器在周期内新建，则为建机首次采样容量。"
    _merge_title_row(sheet, 2, 13, 18, align="left")
    sheet.cell(row=2, column=13).font = Font(name=XLSX_FONT_NAME, size=12, color="334155")

    sheet.cell(row=2, column=19).value = "◀ 向左滑动返回增长量榜单"
    _merge_title_row(sheet, 2, 19, 22, align="center")
    for c_idx in range(19, 23):
        cell_item = sheet.cell(row=2, column=c_idx)
        cell_item.fill = card_fill
        cell_item.border = card_border
    sheet.cell(row=2, column=19).font = card_font
    sheet.cell(row=2, column=19).alignment = card_align

    sheet.row_dimensions[2].height = 28
    if sheet.cell(row=3, column=1).value:
        _merge_title_row(sheet, 3, 1, 11)
    if sheet.cell(row=3, column=13).value:
        _merge_title_row(sheet, 3, 13, 22)
    if sheet.max_row >= 1:
        sheet.merge_cells(start_row=1, start_column=12, end_row=sheet.max_row, end_column=12)
        separator = sheet.cell(row=1, column=12)
        separator.value = None
        separator.fill = PatternFill(fill_type=None)
        sheet.column_dimensions["L"].width = 10


def _xlsx_vm_display_row(vm: dict[str, Any], rank: int, *, include_risk: bool) -> list[Any]:
    labels = vm.get("labels") or {}
    forecast = vm.get("forecast") or {}
    current = forecast.get("current")
    allocated = labels.get("allocated")
    try:
        current_num = float(current) if current is not None else None
    except (TypeError, ValueError):
        current_num = None
    try:
        allocated_num = float(allocated) if allocated is not None else None
    except (TypeError, ValueError):
        allocated_num = None

    if current_num is not None and allocated_num and allocated_num > 0:
        used_ratio_label = _percent_label(current_num / allocated_num)
    else:
        used_ratio_label = "-"

    # Phase 74：名称后插入「所有者」「虚拟机组」「分配空间」「当前容量」「使用率」
    values: list[Any] = [
        rank,
        labels.get("vm") or labels.get("vm_name") or labels.get("vm_id") or "",
        labels.get("owner") or "-",
        labels.get("folder_name") or "-",
        _xlsx_bytes_label(allocated) if (allocated_num and allocated_num > 0) else "-",
        _xlsx_bytes_label(current),
        used_ratio_label,
        _xlsx_bytes_label(vm.get("previous_value")),
        _xlsx_signed_bytes_label(vm.get("growth_amount")),
        _percent_label(vm.get("growth_ratio")),
    ]
    if include_risk:
        values.append(_vm_risk_label(vm))
    return values


def _vm_risk_label(vm: dict[str, Any]) -> str:
    if _is_alert_vm(vm):
        return "高"
    ratio = _float_or_none(vm.get("growth_ratio")) or 0.0
    amount = _float_or_none(vm.get("growth_amount")) or 0.0
    if ratio >= 0.1 or amount >= 50 * 1024**3:
        return "中"
    return "低"


def _xlsx_bytes_label(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    index = 0
    while abs(numeric) >= 1024 and index < len(units) - 1:
        numeric /= 1024
        index += 1
    return f"{numeric:.2f} {units[index]}"


def _xlsx_signed_bytes_label(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    label = _xlsx_bytes_label(abs(numeric))
    if numeric > 0:
        return f"+{label}"
    if numeric < 0:
        return f"-{label}"
    return label


def _write_simple_vm_sheet(sheet, vms: list[dict[str, Any]], empty_text: str, *, include_growth: bool) -> None:
    _clear_xlsx_sheet(sheet)
    _clear_xlsx_tables(sheet)
    # Phase 74：加入「分配空间」「当前容量」「使用率」
    headers = ["Tower", "集群", "VM", "所有者", "虚拟机组", "分配空间", "当前容量", "使用率"]
    if include_growth:
        headers.extend(["周期初始容量", "增长量", "增长率"])
    else:
        headers.append("首次出现时间")
    sheet.cell(row=1, column=1).value = sheet.title
    for column, header in enumerate(headers, start=1):
        sheet.cell(row=2, column=column).value = header
    if not vms:
        sheet.cell(row=3, column=1).value = empty_text
    for row_index, vm in enumerate(vms, start=3):
        labels = vm.get("labels", {})
        current = (vm.get("forecast") or {}).get("current")
        allocated = labels.get("allocated")
        try:
            current_num = float(current) if current is not None else None
        except (TypeError, ValueError):
            current_num = None
        try:
            allocated_num = float(allocated) if allocated is not None else None
        except (TypeError, ValueError):
            allocated_num = None
        if current_num is not None and allocated_num and allocated_num > 0:
            used_ratio_label = _percent_label(current_num / allocated_num)
        else:
            used_ratio_label = "-"

        row = [
            labels.get("tower") or labels.get("tower_id") or "",
            labels.get("cluster") or labels.get("cluster_id") or "",
            labels.get("vm") or labels.get("vm_id") or "",
            labels.get("owner") or "-",
            labels.get("folder_name") or "-",
            _xlsx_bytes_label(allocated) if (allocated_num and allocated_num > 0) else "-",
            _xlsx_bytes_label(current),
            used_ratio_label,
        ]
        if include_growth:
            row.extend([
                _xlsx_bytes_label(vm.get("previous_value")),
                _xlsx_signed_bytes_label(vm.get("growth_amount")),
                _percent_label(vm.get("growth_ratio")),
            ])
        else:
            row.append(_format_first_seen_time(vm.get("first_seen_at")))
        for column, value in enumerate(row, start=1):
            sheet.cell(row=row_index, column=column).value = value
    _style_customer_xlsx_table(sheet, title_rows={1}, header_rows={2})
    _merge_title_row(sheet, 1, 1, len(headers))
    _apply_usage_ratio_colors(sheet, [8], 3, sheet.max_row)
    sheet.freeze_panes = "A3"
    sheet.auto_filter.ref = f"A2:{get_column_letter(len(headers))}{sheet.max_row}"
    widths = {
        "A": 18,
        "B": 20,
        "C": 48,
        "D": 16,
        "E": 20,
        "F": 18,
        "G": 18,
        "H": 14,
    }
    if not include_growth:
        widths["I"] = 24
    else:
        widths["I"] = 18
        widths["J"] = 22
        widths["K"] = 14
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width
    sheet.row_dimensions[1].height = 24
    sheet.row_dimensions[2].height = 20
    for row_index in range(3, sheet.max_row + 1):
        sheet.row_dimensions[row_index].height = 20


def _write_cluster_vm_sheet(sheet, cluster: dict[str, Any], vms: list[dict[str, Any]], report: dict[str, Any], profile: ReportPeriodProfile) -> None:
    _clear_xlsx_tables(sheet)
    _reset_xlsx_sheet_rows(sheet)
    forecast = cluster.get("forecast") or {}
    risk, _ = _risk_level(cluster)
    labels = cluster.get("labels") or {}
    cluster_title = _cluster_full_name(cluster)
    cluster_overview_headers = ["Tower", "集群", "当前容量", profile.window_growth_label, "风险", "90 天预测容量", "总容量", "已分配容量", "使用率", "预计耗尽天数"]
    cluster_overview_values = [
        labels.get("tower") or labels.get("tower_id") or "",
        labels.get("cluster") or labels.get("cluster_id") or "",
        _xlsx_bytes_label(forecast.get("current")),
        _xlsx_signed_bytes_label(_cluster_period_growth(cluster, profile.days)),
        risk,
        _xlsx_bytes_label(forecast.get("forecast_90d")),
        _xlsx_bytes_label(cluster.get("total")),
        _xlsx_bytes_label(cluster.get("allocated")),
        _percent_label(_cluster_used_ratio(cluster)),
        _days_label(forecast.get("exhaustion_days")),
    ]
    notice_text = _profile_sample_notice(report, profile)
    note_text = "* 注：周期初始容量指统计周期起始时虚拟机的物理占用容量；若机器在周期内新建，则为建机首次采样容量。"
    window_label = _vm_sample_window_label(vms, report)
    left_sub_title = f"{profile.vm_growth_title} 增长量全部虚拟机（按增长量降序，统计窗口：{window_label}）"
    right_sub_title = f"{profile.vm_growth_title} 增长率全部虚拟机（按增长率降序，统计窗口：{window_label}）"
    headers = ["VM", "所有者", "虚拟机组", "分配空间", "当前容量", "使用率", "周期初始容量", "增长量", "增长率"]

    # 第 1 行：集群全称大标题（左 1..9，右 11..19）及返回执行摘要链接（J1 与 T1）
    sheet.cell(row=1, column=1).value = cluster_title
    sheet.cell(row=1, column=10).value = "返回执行摘要 ➔"
    sheet.cell(row=1, column=11).value = cluster_title
    sheet.cell(row=1, column=20).value = "返回执行摘要 ➔"

    # 第 2 行：集群概览指标表头（左右对称各 10 列）
    for idx, h_val in enumerate(cluster_overview_headers, start=1):
        sheet.cell(row=2, column=idx).value = h_val
        sheet.cell(row=2, column=idx + 10).value = h_val

    # 第 3 行：集群概览数据（左右对称各 10 列）
    for idx, d_val in enumerate(cluster_overview_values, start=1):
        sheet.cell(row=3, column=idx).value = d_val
        sheet.cell(row=3, column=idx + 10).value = d_val

    # 第 4 行：样本说明（左右对称，整行展示，左 1..10，右 11..20）
    sheet.cell(row=4, column=1).value = notice_text
    sheet.cell(row=4, column=11).value = notice_text

    # 第 5 行：周期初始容量口径说明（左 1..5，右 11..15）
    sheet.cell(row=5, column=1).value = note_text
    sheet.cell(row=5, column=11).value = note_text

    # 滑动提示卡片（第 5 行单行胶囊卡片，左 6..9 列 F~I 宽 80.0，右 16..19 列 P~S 宽 80.0）
    sheet.cell(row=5, column=6).value = "向右滑动查看增长率榜单 ▶"
    sheet.cell(row=5, column=16).value = "◀ 向左滑动返回增长量榜单"

    # 第 6 行：榜单子标题
    sheet.cell(row=6, column=1).value = left_sub_title
    sheet.cell(row=6, column=11).value = right_sub_title

    # 第 7 行：VM 表格表头（左 9 列，右 9 列）
    for idx, h_val in enumerate(headers, start=1):
        sheet.cell(row=7, column=idx).value = h_val
        sheet.cell(row=7, column=idx + 10).value = h_val

    # 第 8 行起：左右双轨虚拟机数据
    amount_vms = _top_vms(vms, "amount")
    ratio_vms = _top_vms(vms, "ratio")
    total_rows = max(len(amount_vms), len(ratio_vms))

    if total_rows == 0:
        sheet.cell(row=8, column=1).value = profile.vm_empty_text
        sheet.cell(row=8, column=11).value = profile.vm_empty_text
        end_row = 8
    else:
        for i in range(total_rows):
            r = 8 + i
            if i < len(amount_vms):
                left_row = _vm_xlsx_row(amount_vms[i], include_cluster=False)
                for c_idx, val in enumerate(left_row, start=1):
                    sheet.cell(row=r, column=c_idx).value = val
            if i < len(ratio_vms):
                right_row = _vm_xlsx_row(ratio_vms[i], include_cluster=False)
                for c_idx, val in enumerate(right_row, start=1):
                    sheet.cell(row=r, column=c_idx + 10).value = val
        end_row = 7 + total_rows

    _apply_cluster_sheet_layout(sheet, end_row=end_row)
    _apply_usage_ratio_colors(sheet, [9, 19], 3, 3)      # 集群概览行「使用率」
    _apply_usage_ratio_colors(sheet, [6, 16], 8, end_row)  # 左右双轨 VM 表「使用率」
    sheet.freeze_panes = "A8"


def _apply_cluster_sheet_layout(sheet, *, end_row: int) -> None:
    widths = {
        "A": 52,
        "B": 39.5,
        "C": 24,
        "D": 20,
        "E": 20,
        "F": 22,
        "G": 20,
        "H": 22,
        "I": 16,
        "J": 18,
        "K": 52,
        "L": 39.5,
        "M": 24,
        "N": 20,
        "O": 20,
        "P": 22,
        "Q": 20,
        "R": 22,
        "S": 16,
        "T": 18,
    }
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width

    if hasattr(sheet, "sheet_view"):
        sheet.sheet_view.showGridLines = False
    if getattr(sheet, "views", None) and sheet.views.sheetView:
        sheet.views.sheetView[0].showGridLines = False

    sheet.row_dimensions[1].height = 32
    sheet.row_dimensions[2].height = 24
    sheet.row_dimensions[3].height = 24
    sheet.row_dimensions[4].height = 24
    sheet.row_dimensions[5].height = 28
    sheet.row_dimensions[6].height = 30
    sheet.row_dimensions[7].height = 24
    for r in range(8, end_row + 1):
        sheet.row_dimensions[r].height = 22

    _merge_title_row(sheet, 1, 1, 10)
    _merge_title_row(sheet, 1, 11, 20)
    # 第 4 行：样本说明整行居左展示
    _merge_title_row(sheet, 4, 1, 10, align="left")
    _merge_title_row(sheet, 4, 11, 20, align="left")
    # 第 5 行：左侧 1..5（A~E 宽 155.5）说明，右侧 6..9（F~I 宽 80.0）滑动卡片
    _merge_title_row(sheet, 5, 1, 5, align="left")
    _merge_title_row(sheet, 5, 11, 15, align="left")
    _merge_title_row(sheet, 5, 6, 9, align="center")
    _merge_title_row(sheet, 5, 16, 19, align="center")
    _merge_title_row(sheet, 6, 1, 9, align="left")
    _merge_title_row(sheet, 6, 11, 19, align="left")

    for start_c in [1, 11]:
        c_node = sheet.cell(row=1, column=start_c)
        c_node.font = Font(name=XLSX_FONT_NAME, size=23, bold=True, color=ACCENT_DARK)
        c_node.alignment = Alignment(vertical="center", wrap_text=True)

    for offset in [0, 10]:
        for col in range(1, 11):
            c_node = sheet.cell(row=2, column=col + offset)
            c_node.font = Font(name=XLSX_FONT_NAME, size=12, bold=True, color="FFFFFF")
            c_node.fill = PatternFill(fill_type="solid", fgColor=ACCENT_DARK)
            c_node.border = HEADER_BORDER
            c_node.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for offset in [0, 10]:
        for col in range(1, 11):
            c_node = sheet.cell(row=3, column=col + offset)
            c_node.font = Font(name=XLSX_FONT_NAME, size=12, color="0F172A")
            c_node.border = DATA_BORDER
            s_val = str(c_node.value or "").strip()
            if s_val in RISK_BADGES:
                c_node.fill = RISK_BADGES[s_val]["fill"]
                c_node.font = RISK_BADGES[s_val]["font"]
            else:
                c_node.fill = PatternFill(fill_type="solid", fgColor=ACCENT_LIGHT)
            if col in {3, 4, 6, 7, 8}:
                c_node.alignment = Alignment(horizontal="right", vertical="center", wrap_text=False)
            elif col in {5, 9, 10}:
                c_node.alignment = Alignment(horizontal="center", vertical="center", wrap_text=False)
            else:
                c_node.alignment = Alignment(horizontal="left", vertical="center", wrap_text=False)

    for start_c in [1, 11]:
        c4 = sheet.cell(row=4, column=start_c)
        c4.font = Font(name=XLSX_FONT_NAME, size=12, color="334155")
        c4.alignment = Alignment(vertical="center", wrap_text=True)
        c5 = sheet.cell(row=5, column=start_c)
        c5.font = Font(name=XLSX_FONT_NAME, size=12, color="334155")
        c5.alignment = Alignment(vertical="center", wrap_text=True)

    card_fill = PatternFill(fill_type="solid", fgColor="EFF6FF")
    card_border_side = Side(border_style="thin", color="BFDBFE")
    card_border = Border(
        left=card_border_side,
        right=card_border_side,
        top=card_border_side,
        bottom=card_border_side,
    )
    card_font = Font(name=XLSX_FONT_NAME, size=13, bold=True, color="1D4ED8")
    card_align = Alignment(horizontal="center", vertical="center")

    for start_col, end_col, hint_text in [(6, 9, "向右滑动查看增长率榜单 ▶"), (16, 19, "◀ 向左滑动返回增长量榜单")]:
        top_cell = sheet.cell(row=5, column=start_col)
        top_cell.value = hint_text
        top_cell.font = card_font
        top_cell.alignment = card_align
        for c_idx in range(start_col, end_col + 1):
            cell_item = sheet.cell(row=5, column=c_idx)
            cell_item.fill = card_fill
            cell_item.border = card_border

    for start_c in [1, 11]:
        c6 = sheet.cell(row=6, column=start_c)
        c6.font = Font(name=XLSX_FONT_NAME, size=14, bold=True, color=ACCENT_DARK)
        c6.alignment = Alignment(vertical="center", wrap_text=True)

    for offset in [0, 10]:
        for col in range(1, 10):
            c_node = sheet.cell(row=7, column=col + offset)
            c_node.font = Font(name=XLSX_FONT_NAME, size=12, bold=True, color="FFFFFF")
            c_node.fill = PatternFill(fill_type="solid", fgColor=ACCENT_DARK)
            c_node.border = HEADER_BORDER
            c_node.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for r in range(8, end_row + 1):
        for offset in [0, 10]:
            first_c = sheet.cell(row=r, column=1 + offset)
            if first_c.value is None or first_c.value == "":
                continue
            amt_val = sheet.cell(row=r, column=8 + offset).value
            ratio_val = sheet.cell(row=r, column=9 + offset).value
            amt = _parse_xlsx_bytes_label(amt_val)
            rat = _parse_percent_label(ratio_val)
            is_alert = _is_alert_vm({"growth_amount": amt, "growth_ratio": rat})
            for col in range(1, 10):
                c_node = sheet.cell(row=r, column=col + offset)
                if isinstance(c_node, MergedCell):
                    continue
                c_node.font = Font(name=XLSX_FONT_NAME, size=12, color="0F172A")
                c_node.border = DATA_BORDER
                if is_alert:
                    c_node.fill = PatternFill(fill_type="solid", fgColor=VM_ALERT_FILL)
                elif r % 2 == 0:
                    c_node.fill = PatternFill(fill_type="solid", fgColor=ACCENT_SOFT)
                else:
                    c_node.fill = PatternFill(fill_type="solid", fgColor="FFFFFF")

                if col in {4, 5, 6, 7, 8, 9}:
                    c_node.alignment = Alignment(horizontal="right", vertical="center", wrap_text=False)
                else:
                    c_node.alignment = Alignment(horizontal="left", vertical="center", wrap_text=False)


def _normalize_xlsx_fonts(workbook: Workbook) -> None:
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell, MergedCell) or cell.value is None:
                    continue
                font = copy(cell.font)
                font.name = XLSX_FONT_NAME
                font.sz = float(font.sz or 12)
                font.scheme = None
                cell.font = font


def _apply_xlsx_tab_colors(workbook: Workbook) -> None:
    """按功能分类为底部工作表 Tab 赋予清晰专业的品牌主题色。"""
    # 统一使用 8 位 ARGB（FF 不透明）——原先 6 位写法被 openpyxl 补成 00（全透明），
    # 与模板封面（FF1A3C6E）不一致，部分渲染器可能不显色。
    color_map = {
        # 概览驾驶舱：品牌深蓝
        "执行摘要": "FF1D4ED8",
        "容量趋势": "FF1D4ED8",
        # 增长分析与详情：商务翡翠绿
        "VM增长TOP100": "FF059669",
        "日增长详情": "FF059669",
        "月增长详情": "FF059669",
        # 新增纳管视角：科技活力蓝
        "本日新建VM": "FF2563EB",
        "本月新建VM": "FF2563EB",
        # 数据说明：中性冷灰
        "数据质量说明": "FF64748B",
    }
    for sheet_name in workbook.sheetnames:
        sheet = workbook[sheet_name]
        if sheet_name in color_map:
            sheet.sheet_properties.tabColor = color_map[sheet_name]
        elif str(sheet_name).startswith("集群"):
            # 各集群专属 Sheet：高质感灰青/紫灰
            sheet.sheet_properties.tabColor = "FF6366F1"


def _apply_xlsx_page_footers(workbook: Workbook) -> None:
    """统一配置横向自适应打印与企业级装订页脚（左侧报告名称，右侧当前页/总页数）。"""
    for sheet_name in workbook.sheetnames:
        sheet = workbook[sheet_name]
        sheet.oddFooter.left.text = "SmartX HCI 存储容量分析报告"
        sheet.oddFooter.right.text = "第 &P 页 / 共 &N 页"
        sheet.oddFooter.left.size = 9
        sheet.oddFooter.right.size = 9


def _vm_xlsx_row(vm: dict[str, Any], *, include_cluster: bool) -> list[Any]:
    labels = vm.get("labels", {})
    forecast = vm.get("forecast", {})
    current = forecast.get("current")
    allocated = labels.get("allocated")
    try:
        current_num = float(current) if current is not None else None
    except (TypeError, ValueError):
        current_num = None
    try:
        allocated_num = float(allocated) if allocated is not None else None
    except (TypeError, ValueError):
        allocated_num = None
    if current_num is not None and allocated_num and allocated_num > 0:
        used_ratio_label = _percent_label(current_num / allocated_num)
    else:
        used_ratio_label = "-"

    row: list[Any] = []
    if include_cluster:
        row.extend([labels.get("tower") or labels.get("tower_id") or "", labels.get("cluster") or labels.get("cluster_id") or ""])
    row.extend([
        labels.get("vm") or labels.get("vm_name") or labels.get("vm_id") or "",
        labels.get("owner") or "-",
        labels.get("folder_name") or "-",
        _xlsx_bytes_label(allocated) if (allocated_num and allocated_num > 0) else "-",
        _xlsx_bytes_label(current),
        used_ratio_label,
        _xlsx_bytes_label(vm.get("previous_value")),
        _xlsx_signed_bytes_label(vm.get("growth_amount")),
        _percent_label(vm.get("growth_ratio")),
    ])
    return row


def _style_vm_rows(sheet, start_row: int, end_row: int, column_count: int) -> None:
    if end_row < start_row:
        return
    fill = PatternFill(fill_type="solid", fgColor=VM_ALERT_FILL)
    for row_index in range(start_row, end_row + 1):
        values = [sheet.cell(row=row_index, column=column).value for column in range(1, column_count + 1)]
        amount = _parse_xlsx_bytes_label(values[-2]) if len(values) >= 2 else 0
        ratio = _parse_percent_label(values[-1]) if values else 0
        if _is_alert_vm({"growth_amount": amount, "growth_ratio": ratio}):
            for column in range(1, column_count + 1):
                sheet.cell(row=row_index, column=column).fill = fill


def _parse_xlsx_bytes_label(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().replace(",", "")
    sign = -1.0 if text.startswith("-") else 1.0
    text = text.lstrip("+-").strip()
    parts = text.split()
    if not parts:
        return 0.0
    try:
        number = float(parts[0])
    except (TypeError, ValueError):
        return 0.0
    unit = parts[1] if len(parts) > 1 else "B"
    multipliers = {
        "B": 1,
        "KiB": 1024,
        "MiB": 1024**2,
        "GiB": 1024**3,
        "TiB": 1024**4,
        "PiB": 1024**5,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
        "TB": 1024**4,
        "PB": 1024**5,
    }
    return sign * number * multipliers.get(unit, 1)


def _parse_percent_label(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text.endswith("%"):
        return 0.0
    try:
        return float(text[:-1]) / 100
    except (TypeError, ValueError):
        return 0.0


def _usage_ratio_font_color(value: Any) -> str | None:
    """占用率配色：≥80% 红、≥70% 黄，其余不染色（用户口径）。"""
    ratio = _parse_percent_label(value)
    if ratio >= USAGE_CRITICAL_RATIO:
        return RATIO_RED
    if ratio >= USAGE_WARNING_RATIO:
        return RATIO_ORANGE
    return None


def _apply_usage_ratio_colors(sheet, columns: list[int], start_row: int, end_row: int) -> None:
    """给「使用率」列按占用率上色（须在各表样式应用之后调用，否则会被样式覆盖）。"""
    if end_row < start_row:
        return
    for column in columns:
        for row_index in range(start_row, end_row + 1):
            cell = sheet.cell(row=row_index, column=column)
            color = _usage_ratio_font_color(cell.value)
            if color is None:
                continue
            font = copy(cell.font)
            font.color = Color(rgb="FF" + color)
            font.bold = True
            cell.font = font


def _add_excel_table(sheet, name: str, header_row: int, end_row: int, column_count: int) -> None:
    if end_row <= header_row:
        return
    ref = f"A{header_row}:{get_column_letter(column_count)}{end_row}"
    table = Table(displayName=name[:255], ref=ref)
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True, showColumnStripes=False)
    sheet.add_table(table)


def _safe_sheet_name(value: str) -> str:
    cleaned = "".join(char if char not in "[]:*?/\\'" else "_" for char in str(value))
    return (cleaned[:31] or "Sheet").strip()


def _table_safe_name(sheet_name: str, suffix: str) -> str:
    return "".join(char for char in f"{sheet_name}_{suffix}" if char.isalnum())[:200] or f"Table{suffix}"


def _profile_sample_notice(report: dict[str, Any], profile: ReportPeriodProfile) -> str:
    effective = _effective_report_window(report)
    start = _parse_report_datetime(str(effective.get("start_at") or ""))
    end = _parse_report_datetime(str(effective.get("end_at") or ""))
    if start and end:
        actual_days = max(1, (end.date() - start.date()).days + 1)
        if actual_days < profile.days:
            return f"说明：当前实际采集样本约 {actual_days} 天，{profile.window_growth_label} 已按当前可用样本窗口计算。"
    return f"说明：{profile.window_growth_label} 按当前统计窗口样本计算；如采集历史不足对应天数，则按可用样本窗口计算。"
