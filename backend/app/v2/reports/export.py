from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from openpyxl.chart import BarChart, Reference
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from app.v2.config import V2Settings


DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
VM_ALERT_FILL = "F4CCCC"
VM_ALERT_RATIO = 0.2
VM_ALERT_BYTES = 100 * 1024**3
DOCX_FONT_ASCII = "Noto Serif"
DOCX_FONT_EAST_ASIA = "Noto Serif CJK SC"
CHART_FONT_FAMILY = "Noto Serif CJK JP"
ACCENT = "1F4E79"
ACCENT_DARK = "17365D"
ACCENT_LIGHT = "D9EAF7"
ACCENT_SOFT = "F2F6FB"
BORDER = "C7D6E8"
SUCCESS = "EAF4EC"
WARNING = "FFF2CC"
DANGER = "FCE4D6"
EMPTY_MONTH_VM_TEXT = "当前样本跨度区间暂无 VM 增长数据"
PERIODS = [("month", "较上月", 30), ("quarter", "较上季度", 90), ("year", "较上一年", 365)]


def build_report_docx(report: dict[str, Any], settings: V2Settings, *, period_days: int) -> tuple[bytes, str, Path, str]:
    context = _export_context(report, settings, period_days, "docx")
    clusters = report.get("clusters") or []
    month_vms = report.get("month_fastest_growing_vms") or []
    document = Document()
    _setup_document(document)
    _setup_footer(document, report, context)
    _add_cover(document, report, context, settings)
    _add_cluster_directory(document, clusters)
    document.add_heading("报告摘要", level=1)
    _add_paragraph_table(
        document,
        [
            ("导出范围", context["scope_label"]),
            ("生成时间", context["generated_at"]),
            ("统计窗口", _period_window_label(report)),
            ("预测窗口", f"{report.get('forecast_days', 90)} 天"),
            ("集群数量", str(len(report.get("clusters") or []))),
            ("容量风险摘要", _capacity_risk_summary(report)),
            ("当前软件版本", settings.app_version),
        ],
    )
    _add_callout(document, "结论摘要", _overview_sentence(clusters))
    document.add_heading("集群容量增长概览", level=1)
    _add_cluster_growth_chart(document, clusters)
    _add_cluster_table(document, clusters)
    document.add_heading("日增长最快 VM", level=1)
    _add_vm_table(document, report.get("day_fastest_growing_vms") or [], empty_text="暂无日增长 VM 数据", include_cluster=True)
    document.add_heading("本日新建 VM", level=1)
    _add_new_vm_table(document, report.get("day_new_vms") or [], empty_text="暂无本日新建 VM")
    document.add_heading("本月新建 VM", level=1)
    _add_new_vm_table(document, report.get("month_new_vms") or [], empty_text="暂无本月新建 VM")
    document.add_heading("VM_TOP100_汇总", level=1)
    document.add_heading("增长量 TOP100", level=2)
    document.add_paragraph(f"统计窗口：{_period_window_label(report)}")
    _add_vm_table(document, _top_vms(month_vms, "amount"), empty_text=EMPTY_MONTH_VM_TEXT, include_cluster=True)
    document.add_heading("增长率 TOP100", level=2)
    document.add_paragraph(f"统计窗口：{_period_window_label(report)}")
    _add_vm_table(document, _top_vms(month_vms, "ratio"), empty_text=EMPTY_MONTH_VM_TEXT, include_cluster=True)
    document.add_heading("集群专项分析", level=1)
    figure_index = 3
    for index, cluster in enumerate(clusters, start=1):
        labels = cluster.get("labels", {})
        cluster_vms = _vms_by_cluster(month_vms).get(_cluster_key(labels), [])
        document.add_page_break()
        document.add_heading(f"{index}. {_cluster_name(cluster)} 集群容量概览", level=1)
        _add_single_cluster_summary(document, cluster, len(cluster_vms))
        figure_index = _add_single_cluster_charts(document, cluster, cluster_vms, figure_index=figure_index)
        document.add_heading("增长量 TOP100 虚拟机（按增长量降序）", level=2)
        document.add_paragraph(f"统计窗口：{_period_window_label(report)}")
        _add_vm_table(document, _top_vms(cluster_vms, "amount"), empty_text=EMPTY_MONTH_VM_TEXT, include_cluster=False)
        document.add_heading("增长率 TOP100 虚拟机（按增长率降序）", level=2)
        document.add_paragraph(f"统计窗口：{_period_window_label(report)}")
        _add_vm_table(document, _top_vms(cluster_vms, "ratio"), empty_text=EMPTY_MONTH_VM_TEXT, include_cluster=False)
    content = _docx_bytes(document)
    return _persist_report(content, settings, context["filename"])


def build_report_xlsx(report: dict[str, Any], settings: V2Settings, *, period_days: int) -> tuple[bytes, str, Path, str]:
    context = _export_context(report, settings, period_days, "xlsx")
    clusters = report.get("clusters") or []
    month_vms = report.get("month_fastest_growing_vms") or []
    workbook = Workbook()
    summary = workbook.active
    summary.title = "汇总"
    _write_directory_sheet(workbook.create_sheet("目录", 0), clusters)
    summary.append(["导出范围", context["scope_label"]])
    summary.append(["生成时间", context["generated_at"]])
    summary.append(["统计窗口", _period_window_label(report)])
    summary.append(["预测窗口", f"{report.get('forecast_days', 90)} 天"])
    summary.append(["集群数量", len(report.get("clusters") or [])])
    summary.append(["容量风险摘要", _capacity_risk_summary(report)])
    summary.append(["当前软件版本", settings.app_version])
    summary.append([])
    summary.append(["集群", "当前容量", "90 天预测", "容量阈值", "预计耗尽天数"])
    if not clusters:
        summary.append(["当前范围暂无集群容量数据", "", "", "", ""])
    for cluster in clusters:
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
    _style_sheet(summary, header_rows={1, 9}, bytes_cols={2, 3, 4})
    _add_xlsx_growth_chart(summary, start_row=9, end_row=summary.max_row)

    vm_sheet = workbook.create_sheet("VM_TOP100_汇总")
    _write_vm_top_sheet(vm_sheet, month_vms, report)
    _write_simple_vm_sheet(workbook.create_sheet("日增长最快VM"), report.get("day_fastest_growing_vms") or [], "暂无日增长 VM 数据", include_growth=True)
    _write_simple_vm_sheet(workbook.create_sheet("本日新建VM"), report.get("day_new_vms") or [], "暂无本日新建 VM", include_growth=False)
    _write_simple_vm_sheet(workbook.create_sheet("本月新建VM"), report.get("month_new_vms") or [], "暂无本月新建 VM", include_growth=False)
    vms_by_cluster = _vms_by_cluster(month_vms)
    for cluster in clusters:
        labels = cluster.get("labels", {})
        sheet = workbook.create_sheet(_safe_sheet_name(labels.get("cluster") or labels.get("cluster_id") or "集群"))
        _write_cluster_vm_sheet(sheet, cluster, vms_by_cluster.get(_cluster_key(labels), []), report)

    output = BytesIO()
    workbook.save(output)
    return _persist_report(output.getvalue(), settings, context["filename"])


def _setup_document(document: Document) -> None:
    section = document.sections[0]
    section.left_margin = Inches(0.62)
    section.right_margin = Inches(0.62)
    section.top_margin = Inches(0.66)
    section.bottom_margin = Inches(0.64)
    styles = document.styles
    styles["Normal"].font.name = DOCX_FONT_ASCII
    styles["Normal"].font.size = Pt(10.5)
    for style_name in ["Normal", "Heading 1", "Heading 2", "Heading 3"]:
        style = document.styles[style_name]
        style.font.name = DOCX_FONT_ASCII
        style._element.rPr.rFonts.set(qn("w:ascii"), DOCX_FONT_ASCII)
        style._element.rPr.rFonts.set(qn("w:hAnsi"), DOCX_FONT_ASCII)
        style._element.rPr.rFonts.set(qn("w:eastAsia"), DOCX_FONT_EAST_ASIA)


def _add_cover(document: Document, report: dict[str, Any], context: dict[str, str], settings: V2Settings) -> None:
    document.add_heading("存储容量预测分析报告", level=0)
    subtitle = document.add_paragraph("SmartX HCI Capacity Insight")
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in subtitle.runs:
        run.font.size = Pt(14)
        run.font.color.rgb = RGBColor.from_string(ACCENT_DARK)
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
    _add_callout(document, "报告说明", "本报告基于平台采集容量样本自动生成，用于客户容量趋势复盘、风险沟通与扩容规划参考。")
    document.add_page_break()


def _add_callout(document: Document, title: str, body: str) -> None:
    table = document.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    cell = table.rows[0].cells[0]
    _shade_cell(cell, ACCENT_SOFT)
    paragraph = cell.paragraphs[0]
    paragraph.add_run(f"{title}：").bold = True
    paragraph.add_run(body)


def _add_paragraph_table(document: Document, rows: list[tuple[str, str]]) -> None:
    table = document.add_table(rows=1, cols=2)
    table.style = "Table Grid"
    table.rows[0].cells[0].text = "项目"
    table.rows[0].cells[1].text = "内容"
    _shade_cell(table.rows[0].cells[0], ACCENT)
    _shade_cell(table.rows[0].cells[1], ACCENT)
    for key, value in rows:
        cells = table.add_row().cells
        cells[0].text = key
        cells[1].text = value


def _add_cluster_directory(document: Document, clusters: list[dict[str, Any]]) -> None:
    document.add_heading("报告正文目录", level=1)
    if not clusters:
        document.add_paragraph("暂无集群目录")
        return
    document.add_paragraph("1. 报告摘要")
    document.add_paragraph("2. 集群容量增长概览")
    document.add_paragraph("3. VM 增长与新建明细")
    document.add_paragraph("4. 集群专项分析")
    for index, cluster in enumerate(clusters, start=1):
        labels = cluster.get("labels", {})
        name = labels.get("cluster") or labels.get("cluster_id") or f"集群 {index}"
        document.add_paragraph(f"4.{index} {name}", style="List Number")


def _add_cluster_table(document: Document, clusters: list[dict[str, Any]]) -> None:
    table = document.add_table(rows=1, cols=8)
    table.style = "Table Grid"
    headers = ["Tower", "集群", "当前容量", "较上月", "较上季度", "较上一年", "90 天预测", "风险"]
    for index, header in enumerate(headers):
        table.rows[0].cells[index].text = header
        _shade_cell(table.rows[0].cells[index], ACCENT)
    if not clusters:
        row = table.add_row().cells
        row[0].text = "当前范围暂无集群容量数据"
        return
    for cluster in clusters:
        labels = cluster.get("labels", {})
        forecast = cluster.get("forecast", {})
        risk, fill = _risk_level(cluster)
        values = [
            labels.get("tower") or labels.get("tower_id") or "",
            labels.get("cluster") or labels.get("cluster_id") or "",
            _bytes_label(forecast.get("current")),
            _bytes_label(_cluster_period_growth(cluster, 30)),
            _bytes_label(_cluster_period_growth(cluster, 90)),
            _bytes_label(_cluster_period_growth(cluster, 365)),
            _bytes_label(forecast.get("forecast_90d")),
            risk,
        ]
        row = table.add_row().cells
        for index, value in enumerate(values):
            row[index].text = value
        _shade_cell(row[-1], fill)


def _add_vm_table(document: Document, vms: list[dict[str, Any]], *, empty_text: str, include_cluster: bool = True) -> None:
    headers = ["Tower", "集群", "VM", "当前容量", "期初容量", "增长量", "增长率"] if include_cluster else ["VM", "当前容量", "期初容量", "增长量", "增长率"]
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for index, header in enumerate(headers):
        table.rows[0].cells[index].text = header
        _shade_cell(table.rows[0].cells[index], ACCENT)
    if not vms:
        row = table.add_row().cells
        row[0].text = empty_text
        return
    for vm in vms[:100]:
        labels = vm.get("labels", {})
        forecast = vm.get("forecast", {})
        values = []
        if include_cluster:
            values.extend([labels.get("tower") or labels.get("tower_id") or "", labels.get("cluster") or labels.get("cluster_id") or ""])
        values.extend([
            labels.get("vm") or labels.get("vm_name") or labels.get("vm_id") or "",
            _bytes_label(forecast.get("current")),
            _bytes_label(vm.get("previous_value")),
            _bytes_label(vm.get("growth_amount")),
            _percent_label(vm.get("growth_ratio")),
        ])
        row = table.add_row().cells
        for index, value in enumerate(values):
            row[index].text = value
        if _is_alert_vm(vm):
            for cell in row:
                _shade_cell(cell, VM_ALERT_FILL)


def _add_new_vm_table(document: Document, vms: list[dict[str, Any]], *, empty_text: str) -> None:
    table = document.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    headers = ["Tower", "集群", "VM", "当前容量", "首次出现时间"]
    for index, header in enumerate(headers):
        table.rows[0].cells[index].text = header
        _shade_cell(table.rows[0].cells[index], ACCENT)
    if not vms:
        table.add_row().cells[0].text = empty_text
        return
    for vm in vms[:100]:
        labels = vm.get("labels", {})
        row = table.add_row().cells
        values = [
            labels.get("tower") or labels.get("tower_id") or "",
            labels.get("cluster") or labels.get("cluster_id") or "",
            labels.get("vm") or labels.get("vm_id") or "",
            _bytes_label((vm.get("forecast") or {}).get("current")),
            str(vm.get("first_seen_at") or ""),
        ]
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
        "clusters": clusters,
        "report": report,
        "period_window": report.get("period_window") or {},
        "app_version": settings.app_version,
    }


def _persist_report(content: bytes, settings: V2Settings, filename: str) -> tuple[bytes, str, Path, str]:
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    path = settings.reports_dir / Path(filename).name
    path.write_bytes(content)
    return content, filename, path, f"/api/admin/exports/reports/{quote(path.name)}"


def _setup_footer(document: Document, report: dict[str, Any], context: dict[str, str]) -> None:
    footer = document.sections[0].footer
    paragraph = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.text = _footer_label(report, context)


def _footer_label(report: dict[str, Any], context: dict[str, str]) -> str:
    clusters = report.get("clusters") or []
    tower_names = sorted({str((cluster.get("labels") or {}).get("tower") or "") for cluster in clusters if (cluster.get("labels") or {}).get("tower")})
    cluster_names = [str((cluster.get("labels") or {}).get("cluster") or (cluster.get("labels") or {}).get("cluster_id") or "") for cluster in clusters]
    tower_label = "、".join(tower_names[:2]) if tower_names else context["scope_label"]
    cluster_label = "、".join([name for name in cluster_names if name][:3]) if cluster_names else "全部集群"
    if len(cluster_names) > 3:
        cluster_label += f" 等 {len(cluster_names)} 个集群"
    return f"{tower_label} - {cluster_label} - {context['generated_at']}"


def _overview_sentence(clusters: list[dict[str, Any]]) -> str:
    if not clusters:
        return "当前范围内暂无可用于分析的集群容量数据。"
    fastest = max(clusters, key=lambda item: _cluster_period_growth(item, 30))
    risk_items = [cluster for cluster in clusters if _risk_level(cluster)[0] != "正常"]
    text = f"当前范围共 {len(clusters)} 个集群，月增长最高的是 {_cluster_name(fastest)}，较上月增加 {_bytes_label(_cluster_period_growth(fastest, 30))}。"
    if risk_items:
        text += f" 有 {len(risk_items)} 个集群在 90 天预测窗口内达到或接近容量阈值，建议优先复核容量规划。"
    else:
        text += " 当前 90 天预测窗口内未发现明显容量阈值风险。"
    return text


def _add_cluster_growth_chart(document: Document, clusters: list[dict[str, Any]]) -> None:
    trend_chart = _scope_trend_line_chart(clusters, "容量使用率趋势")
    if trend_chart is not None:
        _add_figure(document, trend_chart, "图 1：容量使用趋势", width=6.4)
    else:
        document.add_paragraph("暂无足够历史数据生成容量趋势图。")
    top_chart = _cluster_top_growth_bar_chart(clusters, "Top 5 集群月增长量")
    if top_chart is not None:
        _add_figure(document, top_chart, "图 2：Top 5 集群月增长量", width=6.5)


def _add_single_cluster_summary(document: Document, cluster: dict[str, Any], vm_count: int) -> None:
    forecast = cluster.get("forecast", {})
    risk, fill = _risk_level(cluster)
    rows = [
        ("当前容量", _bytes_label(forecast.get("current"))),
        ("较上月增加", _bytes_label(_cluster_period_growth(cluster, 30))),
        ("较上季度增加", _bytes_label(_cluster_period_growth(cluster, 90))),
        ("较上一年增加", _bytes_label(_cluster_period_growth(cluster, 365))),
        ("90 天预测", _bytes_label(forecast.get("forecast_90d"))),
        ("容量阈值", _bytes_label(cluster.get("warning"))),
        ("风险状态", risk),
        ("增长 VM 样本", f"{vm_count} 台"),
    ]
    table = document.add_table(rows=1, cols=2)
    table.style = "Table Grid"
    table.rows[0].cells[0].text = "项目"
    table.rows[0].cells[1].text = "内容"
    for key, value in rows:
        cells = table.add_row().cells
        cells[0].text = key
        cells[1].text = value
        if key == "风险状态":
            _shade_cell(cells[1], fill)


def _add_single_cluster_charts(document: Document, cluster: dict[str, Any], vms: list[dict[str, Any]], *, figure_index: int) -> int:
    cluster_name = _cluster_name(cluster)
    trend_chart = _cluster_trend_line_chart(cluster, "集群容量使用趋势")
    if trend_chart is not None:
        _add_figure(document, trend_chart, f"图 {figure_index}：{cluster_name} 容量使用趋势", width=5.9)
    else:
        document.add_paragraph(f"图 {figure_index}：{cluster_name} 容量使用趋势：暂无足够历史数据生成图表。")
    figure_index += 1
    top_chart = _vm_top_growth_bar_chart(vms, "Top 10 VM 增长量")
    if top_chart is not None:
        _add_figure(document, top_chart, f"图 {figure_index}：{cluster_name} Top 10 VM 增长量", width=6.4)
    else:
        document.add_paragraph(f"图 {figure_index}：{cluster_name} Top 10 VM 增长量：{EMPTY_MONTH_VM_TEXT}。")
    return figure_index + 1


def _add_figure(document: Document, image: BytesIO, caption: str, width: float) -> None:
    caption_paragraph = document.add_paragraph()
    caption_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = caption_paragraph.add_run(caption)
    run.bold = True
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor.from_string(ACCENT_DARK)
    picture_paragraph = document.add_paragraph()
    picture_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    picture_paragraph.add_run().add_picture(image, width=Inches(width))


def _period_window_label(report: dict[str, Any]) -> str:
    window = report.get("data_window") or report.get("period_window") or {}
    start = str(window.get("start_at") or "")
    end = str(window.get("end_at") or "")
    if start and end:
        timezone = _report_timezone(report)
        parsed_start = _parse_report_datetime(start)
        parsed_end = _parse_report_datetime(end)
        if parsed_start and parsed_end:
            return f"{parsed_start.astimezone(timezone).date().isoformat()} - {parsed_end.astimezone(timezone).date().isoformat()}"
        return f"{start[:10]} - {end[:10]}"
    return f"近 {report.get('window_days', 30)} 天"


def _vm_sample_window_label(vms: list[dict[str, Any]], report: dict[str, Any]) -> str:
    starts = [_parse_report_datetime(str(vm.get("window_start_at") or "")) for vm in vms]
    ends = [_parse_report_datetime(str(vm.get("window_end_at") or "")) for vm in vms]
    starts = [value for value in starts if value is not None]
    ends = [value for value in ends if value is not None]
    if starts and ends:
        timezone = _report_timezone(report)
        return f"{min(starts).astimezone(timezone).date().isoformat()} - {max(ends).astimezone(timezone).date().isoformat()}"
    return _period_window_label(report)


def _parse_report_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _report_timezone(report: dict[str, Any]) -> ZoneInfo:
    timezone_name = str(report.get("timezone") or "Asia/Shanghai")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Shanghai")


def _capacity_risk_summary(report: dict[str, Any]) -> str:
    clusters = report.get("clusters") or []
    if not clusters:
        return "暂无集群容量数据，无法判断容量风险。"
    ranked = sorted(clusters, key=_cluster_used_ratio, reverse=True)
    high = [cluster for cluster in ranked if _cluster_used_ratio(cluster) >= 0.8]
    warning = [cluster for cluster in ranked if _cluster_used_ratio(cluster) >= 0.75]
    if high:
        return _risk_summary_sentence(high, "使用率超过 80%，容量风险较高")
    if warning:
        return _risk_summary_sentence(warning, "使用率超过 75%，需要关注容量增长")
    return "当前所有集群暂无明显容量风险。"


def _risk_summary_sentence(clusters: list[dict[str, Any]], suffix: str) -> str:
    names = "、".join(_cluster_name(cluster) for cluster in clusters[:3])
    if len(clusters) > 3:
        names += f" 等 {len(clusters)} 个集群"
    return f"{names} {suffix}。"


def _cluster_name(cluster: dict[str, Any]) -> str:
    labels = cluster.get("labels") or {}
    return str(labels.get("cluster") or labels.get("cluster_id") or "未知集群")


def _cluster_used_ratio(cluster: dict[str, Any]) -> float:
    total = _float_or_none(cluster.get("total"))
    current = _float_or_none((cluster.get("forecast") or {}).get("current"))
    if total and total > 0 and current is not None:
        return current / total
    return 0.0


def _risk_level(cluster: dict[str, Any]) -> tuple[str, str]:
    used_ratio = _cluster_used_ratio(cluster)
    forecast = cluster.get("forecast") or {}
    future = _float_or_none(forecast.get("forecast_90d")) or _float_or_none(forecast.get("current")) or 0
    warning = _float_or_none(cluster.get("warning")) or 0
    if used_ratio >= 0.8:
        return "高风险", DANGER
    if warning and future >= warning:
        return "需关注", WARNING
    return "正常", SUCCESS


def _cluster_period_growth(cluster: dict[str, Any], days: int) -> float:
    points = _cluster_points(cluster)
    forecast = cluster.get("forecast") or {}
    current = _float_or_none(forecast.get("current"))
    if current is None and points:
        current = points[-1][1]
    current = current or 0.0
    if len(points) >= 2:
        target = points[-1][0] - days * 86_400
        candidates = [point for point in points if point[0] <= target]
        baseline = candidates[-1][1] if candidates else points[0][1]
        return max(0.0, current - baseline)
    return max(0.0, float(forecast.get("slope_per_day") or 0) * days)


def _cluster_points(cluster: dict[str, Any]) -> list[tuple[int, float]]:
    points = []
    for point in cluster.get("points") or []:
        try:
            points.append((int(float(point[0])), float(point[1])))
        except (TypeError, ValueError, IndexError):
            continue
    return sorted(points)


def _merged_cluster_points(clusters: list[dict[str, Any]]) -> list[tuple[int, float]]:
    by_ts: dict[int, float] = defaultdict(float)
    for cluster in clusters:
        for ts, value in _cluster_points(cluster):
            by_ts[ts] += value
    return sorted(by_ts.items())


def _vms_by_cluster(vms: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for vm in vms:
        grouped[_cluster_key(vm.get("labels", {}))].append(vm)
    return grouped


def _cluster_key(labels: dict[str, Any]) -> tuple[str, str]:
    return (str(labels.get("tower_id") or ""), str(labels.get("cluster_id") or ""))


def _top_vms(vms: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    key = (lambda vm: float(vm.get("growth_ratio") or 0)) if mode == "ratio" else (lambda vm: float(vm.get("growth_amount") or 0))
    return sorted(vms, key=key, reverse=True)[:100]


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_cluster_name(clusters: list[dict[str, Any]]) -> str | None:
    if not clusters:
        return None
    labels = clusters[0].get("labels", {})
    return labels.get("cluster") or labels.get("cluster_id")


def _is_alert_vm(vm: dict[str, Any]) -> bool:
    return float(vm.get("growth_ratio") or 0) > VM_ALERT_RATIO and float(vm.get("growth_amount") or 0) > VM_ALERT_BYTES


def _shade_cell(cell, fill: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    shading = properties.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        properties.append(shading)
    shading.set(qn("w:fill"), fill)


def _docx_bytes(document: Document) -> bytes:
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _style_sheet(sheet, header_rows: set[int] | None = None, bytes_cols: set[int] | None = None, percent_cols: set[int] | None = None) -> None:
    header_rows = header_rows or {1}
    bytes_cols = bytes_cols or set()
    percent_cols = percent_cols or set()
    title_fill = PatternFill(fill_type="solid", fgColor=ACCENT)
    header_fill = PatternFill(fill_type="solid", fgColor=ACCENT_LIGHT)
    for row in sheet.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            if cell.row == 1:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = title_fill
            elif cell.row in header_rows or cell.value in {"集群", "VM", "当前容量"}:
                cell.font = Font(bold=True, color=ACCENT_DARK)
                cell.fill = header_fill
            if cell.column in bytes_cols and isinstance(cell.value, (int, float)):
                cell.number_format = '#,##0'
            if cell.column in percent_cols and isinstance(cell.value, (int, float)):
                cell.number_format = "0.00%"
    _autosize(sheet)
    sheet.freeze_panes = "A2"


def _autosize(sheet) -> None:
    for column_cells in sheet.columns:
        width = max(len(str(cell.value or "")) for cell in column_cells) + 2
        sheet.column_dimensions[get_column_letter(column_cells[0].column)].width = min(max(width, 10), 32)


def _write_directory_sheet(sheet, clusters: list[dict[str, Any]]) -> None:
    sheet.append(["集群目录"])
    sheet.append(["序号", "集群", "Sheet"])
    if not clusters:
        sheet.append(["-", "当前范围暂无集群容量数据", ""])
    for index, cluster in enumerate(clusters, start=1):
        name = _safe_sheet_name(_cluster_name(cluster))
        sheet.append([index, _cluster_name(cluster), name])
        sheet.cell(row=sheet.max_row, column=3).hyperlink = f"#'{name}'!A1"
        sheet.cell(row=sheet.max_row, column=3).style = "Hyperlink"
    _style_sheet(sheet, header_rows={1, 2})


def _write_vm_top_sheet(sheet, vms: list[dict[str, Any]], report: dict[str, Any]) -> None:
    headers = ["Tower", "集群", "VM", "当前容量", "期初容量", "增长量", "增长率"]
    window_label = _vm_sample_window_label(vms, report)
    sheet.append([f"增长量 TOP100（按增长量降序，统计窗口：{window_label}）"])
    sheet.append(headers)
    amount_start = sheet.max_row + 1
    if not vms:
        sheet.append([EMPTY_MONTH_VM_TEXT])
    else:
        for vm in _top_vms(vms, "amount"):
            sheet.append(_vm_xlsx_row(vm, include_cluster=True))
    amount_end = sheet.max_row
    sheet.append([])
    sheet.append([f"增长率 TOP100（按增长率降序，统计窗口：{window_label}）"])
    sheet.append(headers)
    ratio_start = sheet.max_row + 1
    if not vms:
        sheet.append([EMPTY_MONTH_VM_TEXT])
    else:
        for vm in _top_vms(vms, "ratio"):
            sheet.append(_vm_xlsx_row(vm, include_cluster=True))
    ratio_end = sheet.max_row
    _style_sheet(sheet, header_rows={1, 2, ratio_start - 2, ratio_start - 1}, bytes_cols={4, 5, 6}, percent_cols={7})
    _style_vm_rows(sheet, amount_start, amount_end, 7)
    _style_vm_rows(sheet, ratio_start, ratio_end, 7)
    _add_excel_table(sheet, "VmAmountSummary", 2, amount_end, len(headers))
    _add_excel_table(sheet, "VmRatioSummary", ratio_start - 1, ratio_end, len(headers))


def _write_simple_vm_sheet(sheet, vms: list[dict[str, Any]], empty_text: str, *, include_growth: bool) -> None:
    headers = ["Tower", "集群", "VM", "当前容量"]
    if include_growth:
        headers.extend(["期初容量", "增长量", "增长率"])
    else:
        headers.append("首次出现时间")
    sheet.append([sheet.title])
    sheet.append(headers)
    if not vms:
        sheet.append([empty_text])
    for vm in vms[:100]:
        labels = vm.get("labels", {})
        row = [
            labels.get("tower") or labels.get("tower_id") or "",
            labels.get("cluster") or labels.get("cluster_id") or "",
            labels.get("vm") or labels.get("vm_id") or "",
            (vm.get("forecast") or {}).get("current") or 0,
        ]
        if include_growth:
            row.extend([vm.get("previous_value") or 0, vm.get("growth_amount") or 0, vm.get("growth_ratio") or 0])
        else:
            row.append(vm.get("first_seen_at") or "")
        sheet.append(row)
    _style_sheet(sheet, header_rows={1, 2}, bytes_cols={4, 5, 6}, percent_cols={7})


def _write_cluster_vm_sheet(sheet, cluster: dict[str, Any], vms: list[dict[str, Any]], report: dict[str, Any]) -> None:
    forecast = cluster.get("forecast") or {}
    risk, _ = _risk_level(cluster)
    sheet.append([_cluster_name(cluster)])
    sheet.append(["当前容量", forecast.get("current") or 0, "较上月增加", _cluster_period_growth(cluster, 30), "较上季度增加", _cluster_period_growth(cluster, 90), "较上一年增加", _cluster_period_growth(cluster, 365), "风险", risk])
    sheet.append([])
    headers = ["VM", "当前容量", "期初容量", "增长量", "增长率"]
    window_label = _vm_sample_window_label(vms, report)
    sheet.append([f"增长量 TOP100（按增长量降序，统计窗口：{window_label}）"])
    sheet.append(headers)
    amount_start = sheet.max_row + 1
    if not vms:
        sheet.append([EMPTY_MONTH_VM_TEXT])
    else:
        for vm in _top_vms(vms, "amount"):
            sheet.append(_vm_xlsx_row(vm, include_cluster=False))
    amount_end = sheet.max_row
    sheet.append([])
    sheet.append([f"增长率 TOP100（按增长率降序，统计窗口：{window_label}）"])
    sheet.append(headers)
    ratio_start = sheet.max_row + 1
    if not vms:
        sheet.append([EMPTY_MONTH_VM_TEXT])
    else:
        for vm in _top_vms(vms, "ratio"):
            sheet.append(_vm_xlsx_row(vm, include_cluster=False))
    ratio_end = sheet.max_row
    _style_sheet(sheet, header_rows={1, 2, 4, 5, ratio_start - 2, ratio_start - 1}, bytes_cols={2, 3, 4, 5}, percent_cols={5})
    _style_vm_rows(sheet, amount_start, amount_end, 5)
    _style_vm_rows(sheet, ratio_start, ratio_end, 5)
    _add_excel_table(sheet, _table_safe_name(sheet.title, "Amount"), 5, amount_end, len(headers))
    _add_excel_table(sheet, _table_safe_name(sheet.title, "Ratio"), ratio_start - 1, ratio_end, len(headers))


def _vm_xlsx_row(vm: dict[str, Any], *, include_cluster: bool) -> list[Any]:
    labels = vm.get("labels", {})
    forecast = vm.get("forecast", {})
    row: list[Any] = []
    if include_cluster:
        row.extend([labels.get("tower") or labels.get("tower_id") or "", labels.get("cluster") or labels.get("cluster_id") or ""])
    row.extend([
        labels.get("vm") or labels.get("vm_name") or labels.get("vm_id") or "",
        forecast.get("current") or 0,
        vm.get("previous_value") or 0,
        vm.get("growth_amount") or 0,
        vm.get("growth_ratio") or 0,
    ])
    return row


def _style_vm_rows(sheet, start_row: int, end_row: int, column_count: int) -> None:
    if end_row < start_row:
        return
    fill = PatternFill(fill_type="solid", fgColor=VM_ALERT_FILL)
    for row_index in range(start_row, end_row + 1):
        values = [sheet.cell(row=row_index, column=column).value for column in range(1, column_count + 1)]
        amount = values[-2] if len(values) >= 2 else 0
        ratio = values[-1] if values else 0
        if _is_alert_vm({"growth_amount": amount, "growth_ratio": ratio}):
            for column in range(1, column_count + 1):
                sheet.cell(row=row_index, column=column).fill = fill


def _add_excel_table(sheet, name: str, header_row: int, end_row: int, column_count: int) -> None:
    if end_row <= header_row:
        return
    ref = f"A{header_row}:{get_column_letter(column_count)}{end_row}"
    table = Table(displayName=name[:255], ref=ref)
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True, showColumnStripes=False)
    sheet.add_table(table)


def _add_xlsx_growth_chart(sheet, start_row: int, end_row: int) -> None:
    if end_row <= start_row:
        return
    chart = BarChart()
    chart.type = "bar"
    chart.style = 10
    chart.title = "集群容量增长对比"
    chart.y_axis.title = "容量增长"
    chart.x_axis.title = "集群"
    data = Reference(sheet, min_col=2, max_col=4, min_row=start_row, max_row=end_row)
    cats = Reference(sheet, min_col=1, min_row=start_row + 1, max_row=end_row)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    chart.height = 8
    chart.width = 18
    sheet.add_chart(chart, "L2")


def _safe_sheet_name(value: str) -> str:
    cleaned = "".join(char if char not in "[]:*?/\\'" else "_" for char in str(value))
    return (cleaned[:31] or "Sheet").strip()


def _table_safe_name(sheet_name: str, suffix: str) -> str:
    return "".join(char for char in f"{sheet_name}_{suffix}" if char.isalnum())[:200] or f"Table{suffix}"


def _scope_trend_line_chart(clusters: list[dict[str, Any]], title: str) -> BytesIO | None:
    return _line_chart_image(_merged_cluster_points(clusters), title=title, ylabel="容量 (TiB)")


def _cluster_trend_line_chart(cluster: dict[str, Any], title: str) -> BytesIO | None:
    return _line_chart_image(_cluster_points(cluster), title=title, ylabel="容量 (TiB)")


def _cluster_top_growth_bar_chart(clusters: list[dict[str, Any]], title: str) -> BytesIO | None:
    items = [(_cluster_name(cluster), _cluster_period_growth(cluster, 30)) for cluster in clusters if _cluster_period_growth(cluster, 30) > 0]
    return _horizontal_bar_chart_image(items, title=title, unit="TiB", limit=5, scale="tib")


def _vm_top_growth_bar_chart(vms: list[dict[str, Any]], title: str) -> BytesIO | None:
    items = []
    for vm in _top_vms(vms, "amount")[:10]:
        labels = vm.get("labels", {})
        value = float(vm.get("growth_amount") or 0)
        if value:
            items.append((str(labels.get("vm") or labels.get("vm_id") or "VM"), value))
    return _horizontal_bar_chart_image(items, title=title, unit="GB", limit=10, scale="gb")


def _line_chart_image(points: list[tuple[int, float]], title: str, ylabel: str) -> BytesIO | None:
    if len(points) < 2:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
        matplotlib.rcParams["font.family"] = [CHART_FONT_FAMILY, "DejaVu Serif"]
        matplotlib.rcParams["axes.unicode_minus"] = False
    except Exception:
        return None
    dates = [datetime.fromtimestamp(ts) for ts, _ in points]
    values = [_bytes_to_tib(value) for _, value in points]
    fig, ax = plt.subplots(figsize=(6.6, 4.0), dpi=180)
    ax.plot(dates, values, color="#003BFF", linewidth=1.4)
    ax.set_title(title, fontsize=12, pad=8)
    ax.set_xlabel("时间", fontsize=10)
    ax.set_ylabel(ylabel, fontsize=10)
    y_min, y_max = _chart_y_limits(values)
    ax.set_ylim(y_min, y_max)
    ax.grid(axis="y", color="#E6EDF5", linewidth=0.6)
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=6))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    ax.tick_params(axis="both", labelsize=9, colors="#333333")
    fig.tight_layout()
    return _figure_bytes(fig, plt)


def _horizontal_bar_chart_image(items: list[tuple[str, float]], title: str, unit: str, limit: int, scale: str) -> BytesIO | None:
    if not items:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        matplotlib.rcParams["font.family"] = [CHART_FONT_FAMILY, "DejaVu Serif"]
        matplotlib.rcParams["axes.unicode_minus"] = False
    except Exception:
        return None
    ranked = sorted(items, key=lambda item: item[1], reverse=True)[:limit]
    names = [_truncate_label(name) for name, _ in ranked][::-1]
    values = [_chart_bar_value(value, scale) for _, value in ranked][::-1]
    max_value = max(values) if values else 0
    fig, ax = plt.subplots(figsize=(6.8, max(2.2, 0.45 * len(values) + 1.1)), dpi=180)
    bars = ax.barh(names, values, color="#1155CC", height=0.32)
    ax.set_title(title, fontsize=12, pad=8)
    ax.set_xlim(0, max(max_value * 1.18, 1))
    ax.grid(axis="x", color="#E6EDF5", linewidth=0.6)
    for bar, value in zip(bars, values):
        ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2, f"{value:.2f} {unit}", va="center", ha="left", fontsize=9)
    fig.tight_layout()
    return _figure_bytes(fig, plt)


def _figure_bytes(fig: Any, plt: Any) -> BytesIO:
    output = BytesIO()
    fig.savefig(output, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    output.seek(0)
    return output


def _chart_y_limits(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 1.0
    y_min = min(values)
    y_max = max(values)
    padding = max((y_max - y_min) * 0.18, y_max * 0.01, 0.1) if y_min != y_max else max(abs(y_max) * 0.05, 0.1)
    lower = max(0.0, y_min - padding)
    upper = y_max + padding
    return lower, upper if upper > lower else lower + 1.0


def _truncate_label(value: str, limit: int = 22) -> str:
    text = str(value)
    return text if len(text) <= limit else f"{text[:8]}...{text[-8:]}"


def _bytes_to_tib(value: Any) -> float:
    try:
        return float(value or 0) / 1024**4
    except (TypeError, ValueError):
        return 0.0


def _bytes_to_gb(value: Any) -> float:
    try:
        return float(value or 0) / 1024**3
    except (TypeError, ValueError):
        return 0.0


def _chart_bar_value(value: float, scale: str) -> float:
    if scale == "gb":
        return _bytes_to_gb(value)
    return _bytes_to_tib(value)


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


# v2 keeps its report data service, task flow and Excel workbook, but the Word
# document intentionally uses the mature v1 customer-facing layout.
def build_report_docx(report: dict[str, Any], settings: V2Settings, *, period_days: int) -> tuple[bytes, str, Path, str]:
    context = _export_context(report, settings, period_days, "docx")
    clusters = report.get("clusters") or []
    month_vms = report.get("month_fastest_growing_vms") or []
    window_vms = report.get("window_fastest_growing_vms") or []
    day_vms = report.get("day_fastest_growing_vms") or []
    document = Document()
    _v1_setup_document(document, context)

    _v1_add_cover(document, context)
    _v1_add_cluster_directory(document, clusters)
    _v1_add_report_overview(document, context)
    document.add_heading("1. 集群容量增长概览", level=1)
    _v1_add_cluster_growth_chart(document, clusters)
    _v1_add_cluster_summary_table(document, clusters)
    document.add_heading("本次统计窗口增长 VM", level=2)
    _v1_add_vm_window_note(document, context, window_vms)
    _v1_add_vm_table(document, _top_vms(window_vms, "amount"), "amount", include_cluster=True, empty_text="暂无本次统计窗口 VM 增长数据")
    document.add_heading("日增长最快 VM", level=2)
    _v1_add_vm_table(document, _top_vms(day_vms, "amount"), "amount", include_cluster=True, empty_text="暂无日增长 VM 数据")
    document.add_heading("月增长 VM 说明", level=2)
    if month_vms:
        document.add_paragraph(_vm_growth_bucket_label(report))
    else:
        document.add_paragraph(f"{_vm_growth_bucket_label(report)}；{EMPTY_MONTH_VM_TEXT}。")

    vms_by_cluster = _vms_by_cluster(month_vms)
    window_vms_by_cluster = _vms_by_cluster(window_vms)
    day_vms_by_cluster = _vms_by_cluster(day_vms)
    for index, cluster in enumerate(clusters, start=1):
        labels = cluster.get("labels", {})
        vms = vms_by_cluster.get(_cluster_key(labels), [])
        window_cluster_vms = window_vms_by_cluster.get(_cluster_key(labels), [])
        day_cluster_vms = day_vms_by_cluster.get(_cluster_key(labels), [])
        _v1_start_section(document, context, _v1_cluster_footer_label(labels))
        _v1_add_bookmarked_heading(document, f"2.{index} {_v1_cluster_title(labels)}", _v1_cluster_bookmark(index), level=1, bookmark_id=index)
        _v1_add_cluster_customer_summary(document, cluster, len(vms))
        fallback_vms = window_cluster_vms or day_cluster_vms
        _v1_add_single_cluster_charts(document, cluster, vms or fallback_vms, vm_chart_title="Top 10 VM 增长量" if vms else "本次统计窗口 Top 10 VM 增长量")
        if not vms and fallback_vms:
            document.add_paragraph(f"{_vm_growth_bucket_label(report)}；{EMPTY_MONTH_VM_TEXT}。以下补充展示本次统计窗口内增长最快 VM。")
            _v1_add_vm_window_note(document, context, fallback_vms)
            _v1_add_vm_table(document, _top_vms(fallback_vms, "amount"), "amount")
        document.add_heading("增长量 TOP100 虚拟机（按增长量降序）", level=2)
        _v1_add_vm_window_note(document, context, vms)
        _v1_add_vm_table(document, _top_vms(vms, "amount"), "amount", empty_text=EMPTY_MONTH_VM_TEXT)
        document.add_heading("增长率 TOP100 虚拟机（按增长率降序）", level=2)
        _v1_add_vm_window_note(document, context, vms)
        _v1_add_vm_table(document, _top_vms(vms, "ratio"), "ratio", empty_text=EMPTY_MONTH_VM_TEXT)

    content = _docx_bytes(document)
    return _persist_report(content, settings, context["filename"])


def _v1_setup_document(document: Document, context: dict[str, Any]) -> None:
    section = document.sections[0]
    section.left_margin = Inches(0.62)
    section.right_margin = Inches(0.62)
    section.top_margin = Inches(0.66)
    section.bottom_margin = Inches(0.64)
    for style_name in ["Normal", "Heading 1", "Heading 2", "Heading 3"]:
        style = document.styles[style_name]
        _v1_apply_style_font(style)
    document.styles["Normal"].font.size = Pt(9)
    document.styles["Heading 1"].font.size = Pt(15)
    document.styles["Heading 1"].font.bold = True
    document.styles["Heading 1"].font.color.rgb = RGBColor(23, 54, 93)
    document.styles["Heading 2"].font.size = Pt(11)
    document.styles["Heading 2"].font.bold = True
    document.styles["Heading 2"].font.color.rgb = RGBColor(31, 78, 121)
    _v1_setup_header_footer(section, context)


def _v1_apply_style_font(style: Any) -> None:
    style.font.name = DOCX_FONT_ASCII
    style._element.rPr.rFonts.set(qn("w:ascii"), DOCX_FONT_ASCII)
    style._element.rPr.rFonts.set(qn("w:hAnsi"), DOCX_FONT_ASCII)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), DOCX_FONT_EAST_ASIA)


def _v1_apply_run_font(run: Any) -> None:
    run.font.name = DOCX_FONT_ASCII
    run._element.rPr.rFonts.set(qn("w:ascii"), DOCX_FONT_ASCII)
    run._element.rPr.rFonts.set(qn("w:hAnsi"), DOCX_FONT_ASCII)
    run._element.rPr.rFonts.set(qn("w:eastAsia"), DOCX_FONT_EAST_ASIA)


def _v1_setup_header_footer(section: Any, context: dict[str, Any], footer_label: str | None = None) -> None:
    header = section.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = header.add_run("SmartX Storage Forecast | 容量预测报告")
    _v1_apply_run_font(run)
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(122, 138, 160)

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run(f"{footer_label or context['scope_label']} · {context['generated_at']}")
    _v1_apply_run_font(run)
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(122, 138, 160)


def _v1_start_section(document: Document, context: dict[str, Any], footer_label: str) -> None:
    section = document.add_section(WD_SECTION.NEW_PAGE)
    section.left_margin = Inches(0.62)
    section.right_margin = Inches(0.62)
    section.top_margin = Inches(0.66)
    section.bottom_margin = Inches(0.64)
    section.header.is_linked_to_previous = False
    section.footer.is_linked_to_previous = False
    _v1_clear_paragraph(section.header.paragraphs[0])
    _v1_clear_paragraph(section.footer.paragraphs[0])
    _v1_setup_header_footer(section, context, footer_label=footer_label)


def _v1_clear_paragraph(paragraph: Any) -> None:
    for run in paragraph.runs:
        run._element.getparent().remove(run._element)


def _v1_add_cover_brand(document: Document) -> None:
    table = document.add_table(rows=1, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _v1_set_table_width(table, [900, 7200])
    _v1_set_table_borders(table, "FFFFFF")
    _v1_set_cell(table.rows[0].cells[0], "", fill=ACCENT)
    cell = table.rows[0].cells[1]
    _v1_set_cell(cell, "SmartX HCI Capacity Insight", fill="F7FAFC", color=ACCENT_DARK, bold=True)
    for paragraph in cell.paragraphs:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT


def _v1_add_cover_rule(document: Document) -> None:
    table = document.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _v1_set_table_width(table, [7800])
    _v1_set_table_borders(table, "FFFFFF")
    _shade_cell(table.rows[0].cells[0], ACCENT)


def _v1_add_callout(document: Document, title: str, body: str) -> None:
    table = document.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    _v1_set_table_width(table, [7900])
    _v1_set_table_borders(table, BORDER)
    cell = table.rows[0].cells[0]
    _shade_cell(cell, "F7FAFC")
    paragraph = cell.paragraphs[0]
    title_run = paragraph.add_run(f"{title}：")
    _v1_apply_run_font(title_run)
    title_run.bold = True
    title_run.font.size = Pt(9)
    title_run.font.color.rgb = RGBColor(23, 54, 93)
    body_run = paragraph.add_run(body)
    _v1_apply_run_font(body_run)
    body_run.font.size = Pt(9)
    body_run.font.color.rgb = RGBColor(38, 54, 79)
    document.add_paragraph()


def _v1_add_figure(document: Document, image: BytesIO, caption: str, width: float) -> None:
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.keep_with_next = True
    paragraph.paragraph_format.keep_together = True
    run = paragraph.add_run(caption)
    _v1_apply_run_font(run)
    run.bold = True
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(61, 78, 99)
    paragraph.paragraph_format.space_after = Pt(2)
    picture_paragraph = document.add_paragraph()
    picture_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    picture_paragraph.paragraph_format.keep_together = True
    picture_paragraph.add_run().add_picture(image, width=Inches(width))
    document.add_paragraph()


def _v1_add_cover(document: Document, context: dict[str, Any]) -> None:
    _v1_add_cover_brand(document)
    document.add_paragraph()
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("存储容量预测分析报告")
    _v1_apply_run_font(run)
    run.bold = True
    run.font.size = Pt(28)
    run.font.color.rgb = RGBColor(23, 54, 93)

    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run("Storage Capacity Forecast Report")
    _v1_apply_run_font(run)
    run.font.size = Pt(12)
    run.font.color.rgb = RGBColor(91, 115, 139)

    _v1_add_cover_rule(document)
    document.add_paragraph()

    table = document.add_table(rows=6, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    _v1_set_table_width(table, [2300, 5400])
    _v1_set_table_borders(table, BORDER)
    rows = [
        ("导出范围", context["scope_label"]),
        ("生成时间", context["generated_at"]),
        ("统计窗口", _v1_vm_window_label(context)),
        ("预测窗口", f"预测 {context['report'].get('forecast_days') or 90} 天"),
        ("集群数量", f"{len(context['clusters'])} 个"),
        ("当前软件版本", context.get("app_version", "-")),
    ]
    for row, (key, value) in zip(table.rows, rows):
        _v1_set_cell(row.cells[0], key, fill=ACCENT, color="FFFFFF", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
        _v1_set_cell(row.cells[1], value, fill="F7FAFC")

    document.add_paragraph()
    _v1_add_callout(
        document,
        "报告说明",
        "本报告基于平台采集容量样本自动生成，用于客户容量趋势复盘、风险沟通与扩容规划参考。预测结果应结合业务上线计划和实际资源治理策略共同判断。",
    )
    document.add_page_break()


def _v1_add_report_overview(document: Document, context: dict[str, Any]) -> None:
    clusters = context["clusters"]
    total_current = sum(float((cluster.get("forecast") or {}).get("current") or 0) for cluster in clusters)
    total_month = sum(_cluster_period_growth(cluster, 30) for cluster in clusters)
    total_quarter = sum(_cluster_period_growth(cluster, 90) for cluster in clusters)
    total_year = sum(_cluster_period_growth(cluster, 365) for cluster in clusters)
    risk_count = sum(1 for cluster in clusters if _risk_level(cluster)[0] != "正常")
    document.add_heading("报告摘要", level=1)
    table = document.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _v1_set_table_width(table, [1650, 1650, 1650, 1650, 1650])
    _v1_set_table_borders(table, BORDER)
    values = [
        ("当前已用", _bytes_label(total_current)),
        ("较上月增加", _bytes_label(total_month)),
        ("较上季度增加", _bytes_label(total_quarter)),
        ("较上一年增加", _bytes_label(total_year)),
        ("容量关注集群", f"{risk_count} 个"),
    ]
    for cell, (label, value) in zip(table.rows[0].cells, values):
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        _shade_cell(cell, ACCENT_SOFT)
        paragraph = cell.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run(label + "\n")
        _v1_apply_run_font(run)
        run.bold = True
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(91, 115, 139)
        run = paragraph.add_run(value)
        _v1_apply_run_font(run)
        run.bold = True
        run.font.size = Pt(13)
        run.font.color.rgb = RGBColor(23, 54, 93)
    _v1_add_callout(document, "结论摘要", _overview_sentence(clusters))


def _v1_add_cluster_directory(document: Document, clusters: list[dict[str, Any]]) -> None:
    document.add_heading("目录", level=1)
    if not clusters:
        document.add_paragraph("当前导出范围内暂无集群。")
        document.add_page_break()
        return

    table = document.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _v1_set_table_width(table, [900, 4300, 2500])
    _v1_set_docx_headers(table.rows[0].cells, ["序号", "集群", "章节"])
    _v1_set_table_borders(table, BORDER)
    for index, cluster in enumerate(clusters, start=1):
        labels = cluster.get("labels", {})
        row = table.add_row().cells
        _v1_set_docx_row(row, [str(index), "", f"2.{index}"])
        _v1_add_internal_link(row[1].paragraphs[0], _v1_cluster_bookmark(index), _v1_cluster_title(labels))
        if index % 2 == 0:
            _v1_shade_row(row, "FAFCFF")
    _v1_add_callout(document, "定位说明", "可通过本目录快速确认集群章节编号；Word 打开后也可使用导航窗格按标题跳转。")
    document.add_page_break()


def _v1_add_cluster_growth_chart(document: Document, clusters: list[dict[str, Any]]) -> None:
    trend_chart = _scope_trend_line_chart(clusters, "容量使用率趋势")
    if trend_chart is not None:
        _v1_add_figure(document, trend_chart, "图 1：容量使用趋势", width=6.6)
    else:
        document.add_paragraph("暂无足够历史数据生成容量趋势图。")
    top_chart = _cluster_top_growth_bar_chart(clusters, "Top 5 集群月增长量")
    if top_chart is not None:
        _v1_add_figure(document, top_chart, "图 2：Top 5 集群月增长量", width=6.8)


def _v1_add_cluster_summary_table(document: Document, clusters: list[dict[str, Any]]) -> None:
    headers = ["Tower", "集群", "当前容量", "较上月", "较上季度", "较上一年", "90天预测", "风险"]
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _v1_set_table_width(table, [1050, 1700, 1200, 1200, 1200, 1200, 1200, 850])
    _v1_set_docx_headers(table.rows[0].cells, headers)
    _v1_set_table_borders(table, BORDER)
    for cluster in clusters:
        labels = cluster.get("labels", {})
        forecast = cluster.get("forecast", {})
        risk, fill = _risk_level(cluster)
        row = table.add_row().cells
        values = [
            labels.get("tower") or labels.get("tower_id") or "-",
            labels.get("cluster") or labels.get("cluster_id") or "-",
            _bytes_label(forecast.get("current")),
            _bytes_label(_cluster_period_growth(cluster, 30)),
            _bytes_label(_cluster_period_growth(cluster, 90)),
            _bytes_label(_cluster_period_growth(cluster, 365)),
            _bytes_label(forecast.get("forecast_90d")),
            risk,
        ]
        _v1_set_docx_row(row, values)
        if len(table.rows) % 2 == 1:
            _v1_shade_row(row, "FAFCFF")
        _shade_cell(row[-1], fill)


def _v1_add_cluster_customer_summary(document: Document, cluster: dict[str, Any], vm_count: int) -> None:
    forecast = cluster.get("forecast", {})
    risk, fill = _risk_level(cluster)
    table = document.add_table(rows=2, cols=4)
    table.style = "Table Grid"
    _v1_set_table_width(table, [2100, 2100, 2100, 2100])
    items = [
        ("当前已用", _bytes_label(forecast.get("current"))),
        ("较上月增加", _bytes_label(_cluster_period_growth(cluster, 30))),
        ("较上季度增加", _bytes_label(_cluster_period_growth(cluster, 90))),
        ("较上一年增加", _bytes_label(_cluster_period_growth(cluster, 365))),
        ("90天预测", _bytes_label(forecast.get("forecast_90d"))),
        ("容量阈值", _bytes_label(cluster.get("warning"))),
        ("风险状态", risk),
        ("增长VM样本", f"{vm_count} 台"),
    ]
    for cell, (label, value) in zip([cell for row in table.rows for cell in row.cells], items):
        _shade_cell(cell, fill if label == "风险状态" else "F7FAFC")
        paragraph = cell.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run(label + "\n")
        _v1_apply_run_font(run)
        run.bold = True
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(91, 115, 139)
        run = paragraph.add_run(value)
        _v1_apply_run_font(run)
        run.bold = True
        run.font.size = Pt(11)
        run.font.color.rgb = RGBColor(23, 54, 93)
    document.add_paragraph(_v1_cluster_advice(cluster))


def _v1_cluster_advice(cluster: dict[str, Any]) -> str:
    risk, _ = _risk_level(cluster)
    month = _cluster_period_growth(cluster, 30)
    quarter = _cluster_period_growth(cluster, 90)
    if risk == "高风险":
        return "建议：当前容量已达到关注阈值，建议尽快确认可用容量、扩容周期和重点增长虚拟机。"
    if risk == "需关注":
        return "建议：90 天预测接近容量阈值，建议跟踪增长趋势并提前准备扩容或清理方案。"
    if quarter > month * 2.5 and quarter > 0:
        return "建议：季度增长明显高于月增长节奏，建议复核近期业务上线或批量数据写入情况。"
    return "建议：当前容量趋势相对平稳，建议持续观察 Top 增长虚拟机并保持月度复盘。"


def _v1_add_single_cluster_charts(document: Document, cluster: dict[str, Any], vms: list[dict[str, Any]], vm_chart_title: str = "Top 10 VM 增长量") -> None:
    trend_chart = _cluster_trend_line_chart(cluster, "集群容量使用趋势")
    if trend_chart is not None:
        _v1_add_figure(document, trend_chart, "容量使用趋势", width=5.9)
    top_chart = _vm_top_growth_bar_chart(vms, vm_chart_title)
    if top_chart is not None:
        _v1_add_figure(document, top_chart, vm_chart_title, width=6.4)


def _v1_add_vm_table(document: Document, vms: list[dict[str, Any]], sort_mode: str, include_cluster: bool = False, empty_text: str = "暂无增长数据") -> None:
    headers = _v1_vm_headers(include_cluster=include_cluster, sort_mode=sort_mode)
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    widths = [620, 1150, 1450, 2300, 1000, 1050, 1050, 1050, 800] if include_cluster else [650, 2500, 1050, 1100, 1100, 1100, 850]
    _v1_set_table_width(table, widths)
    _v1_set_docx_headers(table.rows[0].cells, headers)
    _v1_set_table_borders(table, BORDER)
    if not vms:
        _v1_set_docx_row(table.add_row().cells, [empty_text] + ["-"] * (len(headers) - 1))
        return
    for index, vm in enumerate(vms, start=1):
        row = table.add_row().cells
        _v1_set_docx_row(row, _v1_vm_row(vm, include_cluster=include_cluster, raw=False, rank=index))
        if _is_alert_vm(vm):
            _v1_shade_row(row, VM_ALERT_FILL)
        elif index % 2 == 0:
            _v1_shade_row(row, "FAFCFF")


def _v1_add_vm_window_note(document: Document, context: dict[str, Any], vms: list[dict[str, Any]] | None = None) -> None:
    note = document.add_paragraph(f"统计窗口：{_vm_sample_window_label(vms or [], context['report'])}")
    note.alignment = WD_ALIGN_PARAGRAPH.LEFT
    for run in note.runs:
        _v1_apply_run_font(run)
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(91, 115, 139)


def _v1_set_docx_headers(cells: Any, headers: list[str]) -> None:
    for cell, header in zip(cells, headers):
        _v1_set_cell(cell, header, fill=ACCENT, color="FFFFFF", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)


def _v1_set_docx_row(cells: Any, values: list[Any]) -> None:
    for cell, value in zip(cells, values):
        _v1_set_cell(cell, value)


def _v1_set_table_borders(table: Any, color: str) -> None:
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ["top", "left", "bottom", "right", "insideH", "insideV"]:
        tag = f"w:{edge}"
        element = borders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), "6")
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), color)


def _v1_shade_row(cells: Any, fill: str) -> None:
    for cell in cells:
        _shade_cell(cell, fill)


def _v1_set_cell(cell: Any, value: Any, fill: str | None = None, color: str = "1F1F1F", bold: bool = False, align: int | None = None) -> None:
    cell.text = ""
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    if fill:
        _shade_cell(cell, fill)
    paragraph = cell.paragraphs[0]
    paragraph.alignment = align if align is not None else WD_ALIGN_PARAGRAPH.LEFT
    run = paragraph.add_run(str(value))
    _v1_apply_run_font(run)
    run.bold = bold
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor.from_string(color)
    for margin in ["top", "start", "bottom", "end"]:
        _v1_set_cell_margin(cell, margin, 90)


def _v1_add_bookmarked_heading(document: Document, text: str, bookmark_name: str, level: int, bookmark_id: int) -> None:
    paragraph = document.add_heading(level=level)
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(bookmark_id))
    start.set(qn("w:name"), bookmark_name)
    paragraph._p.append(start)
    run = paragraph.add_run(text)
    _v1_apply_run_font(run)
    if level == 1:
        run.bold = True
        run.font.size = Pt(15)
        run.font.color.rgb = RGBColor(23, 54, 93)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), str(bookmark_id))
    paragraph._p.append(end)


def _v1_add_internal_link(paragraph: Any, bookmark_name: str, text: str) -> None:
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("w:anchor"), bookmark_name)
    run_element = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), ACCENT)
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    properties.append(color)
    properties.append(underline)
    run_element.append(properties)
    text_element = OxmlElement("w:t")
    text_element.text = text
    run_element.append(text_element)
    hyperlink.append(run_element)
    paragraph._p.append(hyperlink)
    for run in paragraph.runs:
        _v1_apply_run_font(run)


def _v1_set_cell_margin(cell: Any, margin: str, size: int) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    node = tc_mar.find(qn(f"w:{margin}"))
    if node is None:
        node = OxmlElement(f"w:{margin}")
        tc_mar.append(node)
    node.set(qn("w:w"), str(size))
    node.set(qn("w:type"), "dxa")


def _v1_set_table_width(table: Any, widths: list[int]) -> None:
    table.autofit = False
    for row in table.rows:
        for cell, width in zip(row.cells, widths):
            cell.width = Pt(width / 20)
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_w = tc_pr.first_child_found_in("w:tcW")
            if tc_w is None:
                tc_w = OxmlElement("w:tcW")
                tc_pr.append(tc_w)
            tc_w.set(qn("w:w"), str(width))
            tc_w.set(qn("w:type"), "dxa")


def _v1_vm_headers(include_cluster: bool, sort_mode: str) -> list[str]:
    headers = ["序号"]
    if include_cluster:
        headers.extend(["Tower", "集群"])
    headers.extend(["VM", "当前容量", "期初容量", "增长量", "增长率"])
    if sort_mode == "ratio":
        headers[-1] = "增长率（排序）"
    else:
        headers[-2] = "增长量（排序）"
    return headers


def _v1_vm_row(vm: dict[str, Any], include_cluster: bool, raw: bool = False, rank: int | None = None) -> list[Any]:
    labels = vm.get("labels", {})
    forecast = vm.get("forecast", {})
    current = forecast.get("current") or 0
    previous = vm.get("previous_value") or 0
    amount = vm.get("growth_amount") or 0
    ratio = vm.get("growth_ratio") or 0
    row: list[Any] = [rank or ""]
    if include_cluster:
        row.extend([labels.get("tower") or labels.get("tower_id") or "-", labels.get("cluster") or labels.get("cluster_id") or "-"])
    row.extend([
        labels.get("vm") or labels.get("vm_name") or labels.get("vm_id") or "-",
        current if raw else _bytes_label(current),
        previous if raw else _bytes_label(previous),
        amount if raw else _bytes_label(amount),
        ratio if raw else _percent_label(ratio),
    ])
    return row


def _v1_cluster_title(labels: dict[str, Any]) -> str:
    tower = labels.get("tower")
    cluster = labels.get("cluster") or labels.get("cluster_id") or "未知集群"
    return f"{tower} - {cluster}" if tower else str(cluster)


def _v1_cluster_footer_label(labels: dict[str, Any]) -> str:
    tower = labels.get("tower") or labels.get("tower_id") or "Tower"
    cluster = labels.get("cluster") or labels.get("cluster_id") or "集群"
    return f"{tower} - {cluster}"


def _v1_cluster_bookmark(index: int) -> str:
    return f"cluster_{index}"


def _v1_vm_window_label(context: dict[str, Any]) -> str:
    return f"统计窗口：{_period_window_label(context['report'])}"


def _vm_growth_bucket_label(report: dict[str, Any]) -> str:
    bucket = report.get("vm_growth_sample_bucket") or {}
    min_days = bucket.get("min_days")
    max_days = bucket.get("max_days")
    if min_days is not None and max_days is not None:
        return f"VM 增长样本跨度：{min_days} 天 <= 样本跨度 <= {max_days} 天"
    return f"VM 增长样本跨度：当前导出周期 {report.get('window_days') or 30} 天"
