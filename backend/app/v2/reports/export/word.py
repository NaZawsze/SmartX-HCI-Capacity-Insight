from __future__ import annotations

"""Word (docx) report builders: v1 template, customer template, and shared docx helpers."""

from io import BytesIO
from pathlib import Path
import re
from typing import Any
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from app.v2.config import V2Settings

from .common import (
    _bytes_label, _capacity_risk_summary, _cluster_full_name, _cluster_key, _cluster_name, _cluster_period_growth,
    _cluster_points, _cluster_scope_label, _cluster_used_ratio, _cluster_vm_count, _customer_growth_vms, _customer_key_findings, _customer_operation_advice,
    _customer_risk_matrix_rows, _customer_window_days, _data_quality_status_message, _data_quality_summary_rows, _export_context, _float_or_none, _growth_rate_method_lines, _horizontal_bar_chart_image,
    _is_alert_vm, _line_chart_image, _merge_growth_candidates, _overall_risk_status, _percent_label, _period_window_label, _persist_report, _report_cluster_vm_counts,
    _report_data_quality, _requested_report_window_label, _risk_level, _signed_bytes_label, _top_vms, _tower_scope_label,
    _vm_sample_window_label, _vms_by_cluster, ACCENT, ACCENT_DARK, ACCENT_LIGHT, ACCENT_SOFT, BORDER, DOCX_FONT_ASCII,
    DOCX_FONT_EAST_ASIA, EMPTY_MONTH_VM_TEXT, GROWTH_BLUE, RATIO_ORANGE, RATIO_RED, REPORT_COVER_SUBTITLE, REPORT_COVER_TITLE, REPORT_PRODUCT_NAME,
    TEXT_DARK, TEXT_MUTED, VM_ALERT_FILL,
)

def _risk_text_color(level: str) -> str:
    if level == "高":
        return RATIO_RED
    if level == "中":
        return RATIO_ORANGE
    return "27AE60"


def _risk_word_color(label: str) -> str:
    if "高" in label or "风险" in label and "正常" not in label:
        return RATIO_RED
    if "关注" in label or "中" in label:
        return RATIO_ORANGE
    if "正常" in label:
        return "27AE60"
    return TEXT_DARK


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


def _cluster_trend_line_chart(cluster: dict[str, Any], title: str) -> BytesIO | None:
    return _line_chart_image(_cluster_points(cluster), title=title, ylabel="容量 (TiB)")


def _vm_top_growth_bar_chart(vms: list[dict[str, Any]], title: str) -> BytesIO | None:
    items = []
    for vm in _top_vms(vms, "amount")[:10]:
        labels = vm.get("labels", {})
        value = float(vm.get("growth_amount") or 0)
        if value:
            items.append((str(labels.get("vm") or labels.get("vm_id") or "VM"), value))
    return _horizontal_bar_chart_image(items, title=title, unit="GB", limit=10, scale="gb")


def build_report_docx(report: dict[str, Any], settings: V2Settings, *, period_days: int) -> tuple[bytes, str, Path, str]:
    context = _export_context(report, settings, period_days, "docx")
    clusters = report.get("clusters") or []
    month_vms = report.get("month_fastest_growing_vms") or []
    window_vms = report.get("window_fastest_growing_vms") or []
    day_vms = report.get("day_fastest_growing_vms") or []
    growth_vms = _merge_growth_candidates(_customer_growth_vms(report), day_vms)
    document = Document()

    _customer_setup_document(document)
    _customer_add_cover(document, context, settings)
    document.add_page_break()
    _customer_add_native_toc(document)
    document.add_page_break()
    _customer_add_executive_summary(document, context, clusters, growth_vms)
    document.add_page_break()
    _customer_add_cluster_overview(document, context, clusters, _report_cluster_vm_counts(report))
    document.add_page_break()
    _customer_add_vm_growth_analysis(document, context, clusters, growth_vms)
    document.add_page_break()
    _customer_add_chart_section(document, context, clusters, growth_vms)
    document.add_page_break()
    _customer_add_risk_and_advice(document, context, clusters, growth_vms)

    content = _docx_bytes(document)
    return _persist_report(content, settings, context["filename"])


def _customer_setup_document(document: Document) -> None:
    section = document.sections[0]
    section.page_width = Inches(8.27)
    section.page_height = Inches(11.69)
    section.left_margin = Inches(0.72)
    section.right_margin = Inches(0.72)
    section.top_margin = Inches(0.78)
    section.bottom_margin = Inches(0.72)
    _v1_clear_paragraph(section.header.paragraphs[0])
    _v1_clear_paragraph(section.footer.paragraphs[0])
    _customer_add_page_number_footer(section)
    for style_name in ["Normal", "Heading 1", "Heading 2", "Heading 3"]:
        style = document.styles[style_name]
        _v1_apply_style_font(style)
    normal = document.styles["Normal"]
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = RGBColor.from_string(TEXT_DARK)
    for name, size in [("Heading 1", 18), ("Heading 2", 13), ("Heading 3", 11)]:
        style = document.styles[name]
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(ACCENT_DARK)
    _customer_enable_update_fields(document)


def _customer_add_cover(document: Document, context: dict[str, Any], settings: V2Settings) -> None:
    for _ in range(6):
        document.add_paragraph()
    _customer_centered_text(document, REPORT_PRODUCT_NAME, 16, GROWTH_BLUE)
    _customer_centered_text(document, REPORT_COVER_TITLE, 28, ACCENT_DARK, bold=True, before=10)
    _customer_centered_text(document, REPORT_COVER_SUBTITLE, 13, TEXT_MUTED, before=8)
    document.add_paragraph()
    _customer_center_rule(document, width=4100)
    for _ in range(2):
        document.add_paragraph()
    meta = _customer_cover_meta(context, settings)
    for label, value in meta:
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_after = Pt(10)
        label_run = paragraph.add_run(f"{label}：")
        _v1_apply_run_font(label_run)
        label_run.font.size = Pt(11)
        label_run.font.color.rgb = RGBColor.from_string(TEXT_MUTED)
        value_run = paragraph.add_run(value)
        _v1_apply_run_font(value_run)
        value_run.bold = True
        value_run.font.size = Pt(11)
        value_run.font.color.rgb = RGBColor.from_string(TEXT_DARK)
    for _ in range(2):
        document.add_paragraph()
    _customer_centered_text(document, f"本报告由 {REPORT_PRODUCT_NAME} {settings.app_version} 自动生成", 9, TEXT_MUTED)


def _customer_add_native_toc(document: Document) -> None:
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(8)
    paragraph.paragraph_format.space_after = Pt(14)
    run = paragraph.add_run("目录")
    _v1_apply_run_font(run)
    run.bold = True
    run.font.size = Pt(18)
    run.font.color.rgb = RGBColor.from_string(ACCENT_DARK)
    _customer_left_rule(paragraph)

    toc_paragraph = document.add_paragraph()
    toc_paragraph.paragraph_format.space_after = Pt(8)
    _customer_append_toc_field(toc_paragraph)


def _customer_append_toc_field(paragraph: Any) -> None:
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")

    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = 'TOC \\o "1-3" \\h \\z \\u'

    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")

    placeholder = OxmlElement("w:t")
    placeholder.text = "请在 Word/WPS 中更新目录"

    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")

    for element in [begin, instruction, separate, placeholder, end]:
        run = OxmlElement("w:r")
        run.append(element)
        paragraph._p.append(run)


def _customer_add_page_number_footer(section: Any) -> None:
    paragraph = section.footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _customer_footer_text(paragraph, "第 ")
    _customer_append_field(paragraph, "PAGE", "1")
    _customer_footer_text(paragraph, " 页 / 共 ")
    _customer_append_field(paragraph, "NUMPAGES", "1")
    _customer_footer_text(paragraph, " 页")


def _customer_footer_text(paragraph: Any, text: str) -> None:
    run = paragraph.add_run(text)
    _v1_apply_run_font(run)
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor.from_string(TEXT_MUTED)


def _customer_append_field(paragraph: Any, instruction_text: str, placeholder_text: str) -> None:
    begin_run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    begin_run._r.append(begin)

    instruction_run = paragraph.add_run()
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = instruction_text
    instruction_run._r.append(instruction)

    separate_run = paragraph.add_run()
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    separate_run._r.append(separate)

    _customer_footer_text(paragraph, placeholder_text)

    end_run = paragraph.add_run()
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    end_run._r.append(end)

    for run in [begin_run, instruction_run, separate_run, end_run]:
        _v1_apply_run_font(run)
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor.from_string(TEXT_MUTED)


def _customer_enable_update_fields(document: Document) -> None:
    settings = document.settings.element
    update_fields = settings.find(qn("w:updateFields"))
    if update_fields is None:
        update_fields = OxmlElement("w:updateFields")
        settings.append(update_fields)
    update_fields.set(qn("w:val"), "true")


def _customer_add_executive_summary(document: Document, context: dict[str, Any], clusters: list[dict[str, Any]], growth_vms: list[dict[str, Any]]) -> None:
    _customer_section_title(document, "一", "摘要")
    summary = _customer_summary_text(context, clusters)
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(18)
    _customer_add_emphasis_text(paragraph, summary, base_size=11)

    _customer_kpi_strip(document, context, clusters)
    _customer_table_note(document, context["profile"].focus_note)
    _customer_subtitle(document, "关键发现")
    for finding in _customer_key_findings(clusters, growth_vms, _overall_risk_status(clusters)[2], context):
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.left_indent = Inches(0.24)
        paragraph.paragraph_format.space_after = Pt(7)
        _customer_add_emphasis_text(paragraph, finding)
    _customer_add_growth_rate_method(document, context["report"])
    _customer_add_data_quality_summary(document, context["report"])


def _customer_add_cluster_overview(document: Document, context: dict[str, Any], clusters: list[dict[str, Any]], vm_counts: dict[tuple[str, str], int]) -> None:
    _customer_section_title(document, "二", "集群容量概览")
    primary = clusters[0] if clusters else {}
    _customer_subtitle(document, "2.1  范围基本信息")
    _customer_cluster_info_table(document, context, primary, clusters, vm_counts)
    document.add_paragraph()
    _customer_subtitle(document, "2.2  容量增长趋势")
    _customer_cluster_growth_table(document, context, clusters)
    document.add_paragraph()
    _customer_subtitle(document, "2.3  容量使用率可视化")
    _customer_usage_bars(document, clusters)


def _customer_add_vm_growth_analysis(document: Document, context: dict[str, Any], clusters: list[dict[str, Any]], growth_vms: list[dict[str, Any]]) -> None:
    _customer_section_title(document, "三", "集群虚拟机增长分析")
    profile = context["profile"]
    grouped = _vms_by_cluster(growth_vms)
    if not clusters:
        _customer_table_note(document, "当前范围暂无集群，无法按集群生成 VM 增长分析。")
        return
    for index, cluster in enumerate(clusters, start=1):
        if index > 1:
            document.add_page_break()
        labels = cluster.get("labels") or {}
        cluster_vms = grouped.get(_cluster_key(labels), [])
        _customer_subtitle(document, f"3.{index}  {_cluster_full_name(cluster)}")
        _customer_subtitle(document, f"{profile.vm_growth_title}（增长量 Top 20）", level=3)
        top_amount_vms = _top_vms(cluster_vms, "amount")[:20]
        _customer_vm_window_note(document, context, top_amount_vms, "单位：GB")
        _customer_vm_table(document, top_amount_vms, "amount", empty_text=profile.vm_empty_text)
        _customer_table_note(document, f"注：以上为该集群增长量 Top 20，完整清单共 {len(cluster_vms)} 台 VM。")
        _customer_subtitle(document, f"{profile.vm_growth_title}（增长率 Top 20）", level=3)
        top_ratio_vms = _top_vms(cluster_vms, "ratio")[:20]
        _customer_vm_window_note(document, context, top_ratio_vms, "按增长率降序排列")
        _customer_vm_table(document, top_ratio_vms, "ratio", empty_text=profile.vm_empty_text)


def _customer_add_chart_section(document: Document, context: dict[str, Any], clusters: list[dict[str, Any]], growth_vms: list[dict[str, Any]]) -> None:
    _customer_section_title(document, "四", "集群容量趋势图表")
    profile = context["profile"]
    grouped = _vms_by_cluster(growth_vms)
    if not clusters:
        _customer_table_note(document, "当前范围暂无集群，无法生成集群容量趋势图表。")
        return
    for index, cluster in enumerate(clusters, start=1):
        if index > 1:
            document.add_page_break()
        labels = cluster.get("labels") or {}
        cluster_vms = grouped.get(_cluster_key(labels), [])
        _customer_subtitle(document, f"4.{index}  {_cluster_full_name(cluster)}")
        trend_chart = _cluster_trend_line_chart(cluster, f"{_cluster_full_name(cluster)} 容量使用趋势")
        if trend_chart is not None:
            _customer_add_figure(document, trend_chart, f"图：{_cluster_full_name(cluster)} 容量使用趋势", width=5.9)
        else:
            _customer_table_note(document, "暂无足够历史数据生成该集群容量使用趋势图。")
        top_chart = _vm_top_growth_bar_chart(_top_vms(cluster_vms, "amount")[:10], f"{profile.vm_growth_title} Top 10 VM 增长量")
        if top_chart is not None:
            _customer_add_figure(document, top_chart, f"图：{_cluster_full_name(cluster)} {profile.vm_growth_title} Top 10 VM 增长量", width=6.1)
        else:
            _customer_table_note(document, f"暂无足够 VM 增长数据生成该集群 {profile.vm_growth_title} Top 10 VM 增长量图表。")


def _customer_add_risk_and_advice(document: Document, context: dict[str, Any], clusters: list[dict[str, Any]], growth_vms: list[dict[str, Any]]) -> None:
    _customer_section_title(document, "五", "全集群汇总报告")
    _customer_subtitle(document, "5.1  容量风险评估矩阵")
    _customer_risk_matrix_table(document, clusters, growth_vms)
    document.add_paragraph()
    _customer_subtitle(document, "5.2  运维建议")
    for title, items in _customer_operation_advice(clusters, growth_vms, context["profile"]):
        _customer_advice_title(document, title)
        for item in items:
            body = document.add_paragraph()
            body.paragraph_format.left_indent = Inches(0.24)
            body.paragraph_format.space_after = Pt(5)
            _customer_add_emphasis_text(body, item, base_size=10)
    _customer_table_note(document, "声明：本报告基于平台采集容量数据自动生成，预测结果基于历史增长趋势推算，仅供容量规划参考。")


def _customer_add_data_quality_summary(document: Document, report: dict[str, Any]) -> None:
    quality = _report_data_quality(report)
    _customer_subtitle(document, "数据质量说明")
    _customer_table_note(document, _data_quality_status_message(quality))
    rows = _data_quality_summary_rows(report, quality)
    table = document.add_table(rows=1, cols=2)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _v1_set_table_width(table, [3000, 5200])
    _customer_set_blue_headers(table.rows[0].cells, ["项目", "说明"])
    for index, (label, value) in enumerate(rows, start=1):
        row = table.add_row().cells
        _v1_set_cell(row[0], label, fill=ACCENT_LIGHT, color=ACCENT_DARK, bold=True, font_size=9)
        _v1_set_cell(row[1], value, color=TEXT_DARK, font_size=9)
        if index % 2 == 0:
            _v1_shade_row(row, ACCENT_SOFT)
        _prevent_row_split(table.rows[-1])

    incomplete_clusters = quality.get("incomplete_clusters") or []
    if incomplete_clusters:
        cluster_rows = []
        for item in incomplete_clusters[:10]:
            cluster_rows.append(
                f"{item.get('tower') or item.get('tower_id') or '-'} / "
                f"{item.get('cluster') or item.get('cluster_id') or '-'}：{item.get('reason') or '-'}"
            )
        if len(incomplete_clusters) > 10:
            cluster_rows.append(f"其余 {len(incomplete_clusters) - 10} 个集群请在报表页数据质量说明中查看。")
        _customer_table_note(document, "数据不完整集群：" + "；".join(cluster_rows))


def _customer_add_growth_rate_method(document: Document, report: dict[str, Any]) -> None:
    _customer_subtitle(document, "容量增长速率口径")
    for line in _growth_rate_method_lines(report):
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.left_indent = Inches(0.24)
        paragraph.paragraph_format.space_after = Pt(5)
        run = paragraph.add_run(line)
        _v1_apply_run_font(run)
        run.font.size = Pt(10)
        run.font.color.rgb = RGBColor.from_string(TEXT_DARK)


def _customer_advice_title(document: Document, title: str) -> None:
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(3)
    paragraph.paragraph_format.space_after = Pt(3)
    paragraph.paragraph_format.keep_with_next = True
    # A lightweight marker keeps these compact recommendation group titles
    # visually distinct from body text in Word and LibreOffice renderers.
    run = paragraph.add_run(f"· {title}")
    _v1_apply_run_font(run)
    run.bold = True
    run.font.size = Pt(11)
    run.font.color.rgb = RGBColor.from_string(GROWTH_BLUE)


def _customer_centered_text(document: Document, text: str, size: int, color: str, *, bold: bool = False, before: int = 0) -> None:
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(before)
    paragraph.paragraph_format.space_after = Pt(0)
    run = paragraph.add_run(text)
    _v1_apply_run_font(run)
    run.bold = bold
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(color)


def _customer_center_rule(document: Document, *, width: int) -> None:
    table = document.add_table(rows=1, cols=3)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    side = max(1, int((8200 - width) / 2))
    _v1_set_table_width(table, [side, width, side])
    _v1_set_table_borders(table, "FFFFFF")
    for index, cell in enumerate(table.rows[0].cells):
        _shade_cell(cell, GROWTH_BLUE if index == 1 else "FFFFFF")
        _customer_set_cell_height(cell, 28)
        for margin in ["top", "bottom", "start", "end"]:
            _v1_set_cell_margin(cell, margin, 0)


def _customer_set_cell_height(cell: Any, height: int) -> None:
    tr_pr = cell._tc.getparent().get_or_add_trPr()
    tr_height = tr_pr.find(qn("w:trHeight"))
    if tr_height is None:
        tr_height = OxmlElement("w:trHeight")
        tr_pr.append(tr_height)
    tr_height.set(qn("w:val"), str(height))
    tr_height.set(qn("w:hRule"), "exact")


def _customer_section_title(document: Document, order: str, title: str) -> None:
    paragraph = document.add_paragraph(style="Heading 1")
    paragraph.paragraph_format.space_before = Pt(8)
    paragraph.paragraph_format.space_after = Pt(14)
    run = paragraph.add_run(f"{order}  {title}")
    _v1_apply_run_font(run)
    run.bold = True
    run.font.size = Pt(18)
    run.font.color.rgb = RGBColor.from_string(ACCENT_DARK)
    _customer_left_rule(paragraph)


def _customer_left_rule(paragraph: Any) -> None:
    paragraph.paragraph_format.space_after = Pt(12)
    p_pr = paragraph._p.get_or_add_pPr()
    border = p_pr.find(qn("w:pBdr"))
    if border is None:
        border = OxmlElement("w:pBdr")
        p_pr.append(border)
    bottom = border.find(qn("w:bottom"))
    if bottom is None:
        bottom = OxmlElement("w:bottom")
        border.append(bottom)
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "8")
    bottom.set(qn("w:space"), "8")
    bottom.set(qn("w:color"), GROWTH_BLUE)


def _customer_subtitle(document: Document, text: str, *, level: int = 2) -> None:
    style_name = "Heading 3" if level >= 3 else "Heading 2"
    paragraph = document.add_paragraph(style=style_name)
    paragraph.paragraph_format.space_before = Pt(8)
    paragraph.paragraph_format.space_after = Pt(8)
    paragraph.paragraph_format.keep_with_next = True
    run = paragraph.add_run(text)
    _v1_apply_run_font(run)
    run.bold = True
    run.font.size = Pt(13)
    run.font.color.rgb = RGBColor.from_string(ACCENT_DARK)


def _customer_cover_meta(context: dict[str, Any], settings: V2Settings) -> list[tuple[str, str]]:
    clusters = context["clusters"]
    generated_date = str(context["generated_at"]).split(" ")[0]
    return [
        ("客户名称", ""),
        ("Tower范围", _tower_scope_label(clusters, context["scope_label"]).upper()),
        ("集群范围", _cluster_scope_label(clusters, context["scope_label"]).upper()),
        ("统计窗口", _period_window_label(context["report"])),
        ("本报表统计窗口", _requested_report_window_label(context["report"])),
        ("预测窗口", f"{context['report'].get('forecast_days') or 90} 天"),
        ("生成日期", generated_date),
    ]


def _customer_summary_text(context: dict[str, Any], clusters: list[dict[str, Any]]) -> str:
    clusters_label = "、".join(_cluster_full_name(cluster) for cluster in clusters[:3]) or context["scope_label"]
    if len(clusters) > 3:
        clusters_label += f" 等 {len(clusters)} 个集群"
    risk = _overall_risk_status(clusters)[0]
    return (
        f"本报告基于 {REPORT_PRODUCT_NAME} 在 {_period_window_label(context['report'])} "
        f"期间采集的容量数据，对集群 {clusters_label} 的存储使用情况进行分析与趋势预测。"
        f"当前容量风险状态为{risk}。"
    )


def _customer_kpi_strip(document: Document, context: dict[str, Any], clusters: list[dict[str, Any]]) -> None:
    if len(clusters) <= 1:
        _customer_kpi_table(document, context, clusters)
        return

    risk_priority = {"高风险": 2, "需关注": 1, "正常": 0, "数据不足": -1}
    ordered = sorted(
        clusters,
        key=lambda cluster: (risk_priority.get(_overall_risk_status([cluster])[0], -1), _cluster_used_ratio(cluster)),
        reverse=True,
    )
    for index, cluster in enumerate(ordered):
        title = document.add_paragraph()
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title.paragraph_format.space_before = Pt(8 if index else 0)
        title.paragraph_format.space_after = Pt(5)
        title.paragraph_format.keep_with_next = True
        run = title.add_run(_cluster_full_name(cluster))
        _v1_apply_run_font(run)
        run.bold = True
        run.font.size = Pt(11)
        run.font.color.rgb = RGBColor.from_string(TEXT_DARK)
        _customer_kpi_table(document, context, [cluster])


def _customer_kpi_table(document: Document, context: dict[str, Any], clusters: list[dict[str, Any]]) -> None:
    profile = context["profile"]
    total_current = sum(float((cluster.get("forecast") or {}).get("current") or 0) for cluster in clusters)
    total_window = sum(_cluster_period_growth(cluster, _customer_window_days(context["report"])) for cluster in clusters)
    total_forecast_90 = sum(float((cluster.get("forecast") or {}).get("forecast_90d") or 0) for cluster in clusters)
    total_capacity = sum(float(cluster.get("total") or 0) for cluster in clusters)
    risk_label = _overall_risk_status(clusters)[0]
    risk_note = "无容量风险集群" if risk_label == "正常" else "存在容量风险集群"
    values = [
        ("当前已用容量", _bytes_label(total_current), f"总容量 {_bytes_label(total_capacity)}\n使用率 {_percent_label(total_current / total_capacity) if total_capacity > 0 else '-'}"),
        (profile.window_growth_label, _signed_bytes_label(total_window), _period_window_label(context["report"])),
        ("90 天预测容量", _bytes_label(total_forecast_90), f"使用率 {_percent_label(total_forecast_90 / total_capacity) if total_capacity > 0 else '-'}"),
        ("风险状态", risk_label, risk_note),
    ]
    table = document.add_table(rows=1, cols=4)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    _v1_set_table_width(table, [2050, 2050, 2050, 2050])
    _v1_set_table_borders(table, "FFFFFF")
    _prevent_row_split(table.rows[0])
    for cell, (label, value, note) in zip(table.rows[0].cells, values):
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        _shade_cell(cell, ACCENT_LIGHT)
        paragraph = cell.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        label_run = paragraph.add_run(label + "\n")
        _v1_apply_run_font(label_run)
        label_run.font.size = Pt(9)
        label_run.font.color.rgb = RGBColor.from_string(TEXT_MUTED)
        value_run = paragraph.add_run(value)
        _v1_apply_run_font(value_run)
        value_run.bold = True
        value_run.font.size = Pt(18)
        value_run.font.color.rgb = RGBColor.from_string(_risk_word_color(risk_label) if label == "风险状态" else ACCENT_DARK)
        if note:
            note_run = paragraph.add_run("\n" + note)
            _v1_apply_run_font(note_run)
            note_run.font.size = Pt(8)
            note_run.font.color.rgb = RGBColor.from_string(TEXT_MUTED)
        for margin in ["top", "bottom", "start", "end"]:
            _v1_set_cell_margin(cell, margin, 170)


def _customer_cluster_info_table(
    document: Document,
    context: dict[str, Any],
    cluster: dict[str, Any],
    clusters: list[dict[str, Any]],
    vm_counts: dict[tuple[str, str], int],
) -> None:
    total_current = sum(float((item.get("forecast") or {}).get("current") or 0) for item in clusters)
    total_capacity = sum(float(item.get("total") or 0) for item in clusters)
    risk_clusters = [item for item in clusters if _risk_level(item)[0] != "正常"]
    vm_total = sum(_cluster_vm_count(item, vm_counts.get(_cluster_key(item.get("labels") or {}))) for item in clusters)
    risk = _overall_risk_status(clusters)[0] if clusters else "数据不足"
    tower_count = _tower_count(clusters)
    rows = [
        ("Tower范围", _tower_scope_label(clusters, context["scope_label"])),
        ("Tower数量", f"{tower_count} 个"),
        ("集群范围", _cluster_scope_label(clusters, context["scope_label"])),
        ("集群数量", f"{len(clusters)} 个"),
        ("当前已用容量", _bytes_label(total_current)),
        ("总容量", _bytes_label(total_capacity)),
        ("风险状态", risk),
        ("风险集群数", f"{len(risk_clusters)} 个"),
        ("增长 VM 样本数", f"{vm_total} 台"),
    ]
    table = document.add_table(rows=len(rows), cols=2)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _v1_set_table_width(table, [3900, 4300])
    _v1_set_table_borders(table, "000000")
    for table_row, (label, value) in zip(table.rows, rows):
        _v1_set_cell(table_row.cells[0], label, fill=ACCENT_LIGHT, color=ACCENT_DARK, bold=True, font_size=10)
        _v1_set_cell(table_row.cells[1], value, color=_risk_word_color(str(value)) if label == "风险状态" else TEXT_DARK, bold=label == "风险状态", font_size=10)


def _customer_cluster_growth_table(document: Document, context: dict[str, Any], clusters: list[dict[str, Any]]) -> None:
    headers = ["Tower", "集群", "近 14 天样本增长", "近 30 天样本增长", "近 90 天样本增长", "90 天预测容量"]
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _v1_set_table_width(table, [1400, 1700, 1500, 1500, 1500, 1500])
    _customer_set_blue_headers(table.rows[0].cells, headers)
    if not clusters:
        _v1_set_docx_row(table.add_row().cells, ["当前范围暂无集群容量数据"] + ["-"] * (len(headers) - 1))
        return
    for index, cluster in enumerate(clusters[:8], start=1):
        row = table.add_row().cells
        forecast = cluster.get("forecast") or {}
        labels = cluster.get("labels") or {}
        values = [
            labels.get("tower") or labels.get("tower_id") or "-",
            _cluster_name(cluster),
            _cluster_growth_window_label(cluster, 14),
            _cluster_growth_window_label(cluster, 30),
            _cluster_growth_window_label(cluster, 90),
            _bytes_label(forecast.get("forecast_90d")),
        ]
        _v1_set_docx_row(row, values)
        if index % 2 == 0:
            _v1_shade_row(row, ACCENT_SOFT)
        for cell in row[2:5]:
            _v1_set_cell_text_style(cell, GROWTH_BLUE, align=WD_ALIGN_PARAGRAPH.CENTER)
    _customer_table_note(document, "说明：近 14/30/90 天样本增长按对应周期内采集样本计算；采集历史不足对应天数时显示数据不足。")


def _cluster_growth_window_label(cluster: dict[str, Any], days: int) -> str:
    growth = _cluster_period_growth_with_min_span(cluster, days)
    return "数据不足" if growth is None else _signed_bytes_label(growth)


def _cluster_period_growth_with_min_span(cluster: dict[str, Any], days: int) -> float | None:
    points = _cluster_points(cluster)
    if len(points) < 2:
        return None
    sample_span_seconds = points[-1][0] - points[0][0]
    if sample_span_seconds < days * 86_400:
        return None
    return _cluster_period_growth(cluster, days)


def _tower_count(clusters: list[dict[str, Any]]) -> int:
    tower_ids: set[str] = set()
    tower_names: set[str] = set()
    for cluster in clusters:
        labels = cluster.get("labels") or {}
        tower_id = str(labels.get("tower_id") or "")
        tower_name = str(labels.get("tower") or "")
        if tower_id:
            tower_ids.add(tower_id)
        elif tower_name:
            tower_names.add(tower_name)
    return len(tower_ids or tower_names)


def _customer_usage_bars(document: Document, clusters: list[dict[str, Any]]) -> None:
    if not clusters:
        _customer_table_note(document, "当前范围暂无集群容量数据。")
        return
    cluster = max(clusters, key=_cluster_used_ratio)
    total = _float_or_none(cluster.get("total"))
    if total is None or total <= 0:
        _customer_table_note(document, f"{_cluster_full_name(cluster)} 暂无总容量数据，无法生成容量使用率可视化。")
        return
    current_ratio = _cluster_used_ratio(cluster)
    future = _float_or_none((cluster.get("forecast") or {}).get("forecast_90d"))
    current = _float_or_none((cluster.get("forecast") or {}).get("current"))
    future_ratio = (future if future is not None else current or 0) / total
    threshold = _float_or_none(cluster.get("warning")) or total
    _customer_table_note(document, f"展示对象：{_cluster_full_name(cluster)}。多集群范围下默认展示当前使用率最高的集群。")
    _customer_usage_bar(document, "当前使用率", current_ratio, ACCENT_DARK, threshold)
    _customer_usage_bar(document, "90 天预测使用率", future_ratio, GROWTH_BLUE, threshold)
    _customer_table_note(document, _customer_usage_summary(cluster, current_ratio, future_ratio))


def _customer_usage_bar(document: Document, label: str, ratio: float, color: str, threshold: float) -> None:
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(4)
    paragraph.paragraph_format.space_after = Pt(2)
    paragraph.paragraph_format.keep_with_next = True
    run = paragraph.add_run(f"{label}   {_percent_label(ratio)}")
    _v1_apply_run_font(run)
    run.bold = True
    run.font.size = Pt(13)
    run.font.color.rgb = RGBColor.from_string(TEXT_DARK)

    bar = document.add_paragraph()
    bar.paragraph_format.space_before = Pt(0)
    bar.paragraph_format.space_after = Pt(4)
    bar.paragraph_format.keep_with_next = True
    normalized = max(0.0, min(ratio, 1.0))
    width = 50
    used = max(0, min(width, round(normalized * width)))
    blocks = "█" * used + "░" * (width - used)
    bar_run = bar.add_run(f"  {blocks}")
    _v1_apply_run_font(bar_run)
    bar_run.font.size = Pt(8)
    bar_run.font.color.rgb = RGBColor.from_string(color)
    threshold_run = bar.add_run(f"   | 容量阈值   {_bytes_label(threshold)}")
    _v1_apply_run_font(threshold_run)
    threshold_run.font.size = Pt(9)
    threshold_run.font.color.rgb = RGBColor.from_string(TEXT_MUTED)


def _customer_usage_summary(cluster: dict[str, Any], current_ratio: float, future_ratio: float) -> str:
    cluster_name = _cluster_full_name(cluster)
    if current_ratio >= 0.8:
        return f"{cluster_name} 当前使用率已达到高风险阈值，容量安全边际不足，建议优先确认扩容周期和可清理空间。"
    if future_ratio >= 0.8:
        return f"{cluster_name} 当前使用率尚未超过高风险阈值，但 90 天预测接近或超过 80%，容量安全边际收窄，建议进入容量跟踪。"
    if future_ratio >= 0.75:
        return f"{cluster_name} 90 天预测使用率接近关注阈值，容量安全边际需持续观察。"
    return f"{cluster_name} 使用率较低，预测趋势线与当前基线接近，容量安全边际较充裕。"


def _customer_vm_window_note(document: Document, context: dict[str, Any], vms: list[dict[str, Any]], suffix: str) -> None:
    paragraph = document.add_paragraph(f"统计窗口：{_vm_sample_window_label(vms, context['report'])} | {suffix}")
    paragraph.paragraph_format.space_after = Pt(4)
    paragraph.paragraph_format.keep_with_next = True
    for run in paragraph.runs:
        _v1_apply_run_font(run)
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor.from_string(TEXT_MUTED)


def _customer_vm_table(document: Document, vms: list[dict[str, Any]], sort_mode: str, *, empty_text: str) -> None:
    headers = ["排名", "虚拟机名称", "当前容量", "期初容量", "增长量", "增长率"]
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _v1_set_table_width(table, [900, 2200, 1500, 1500, 1500, 1300])
    _customer_set_blue_headers(table.rows[0].cells, headers)
    _repeat_table_header(table.rows[0])
    if not vms:
        row = table.add_row().cells
        _v1_set_docx_row(row, [empty_text] + ["-"] * (len(headers) - 1))
        _prevent_row_split(table.rows[-1])
        return
    for index, vm in enumerate(vms, start=1):
        row = table.add_row().cells
        labels = vm.get("labels") or {}
        values = [
            index,
            labels.get("vm") or labels.get("vm_name") or labels.get("vm_id") or "-",
            _bytes_label((vm.get("forecast") or {}).get("current")),
            _bytes_label(vm.get("previous_value")),
            _bytes_label(vm.get("growth_amount")),
            _percent_label(vm.get("growth_ratio")),
        ]
        _v1_set_docx_row(row, values)
        if index % 2 == 0:
            _v1_shade_row(row, ACCENT_SOFT)
        _v1_set_cell_text_style(row[0], TEXT_MUTED, align=WD_ALIGN_PARAGRAPH.CENTER)
        _v1_set_cell_text_style(row[4], GROWTH_BLUE, align=WD_ALIGN_PARAGRAPH.CENTER)
        ratio = float(vm.get("growth_ratio") or 0)
        ratio_color = RATIO_RED if ratio >= 0.5 else RATIO_ORANGE if ratio >= 0.2 else TEXT_DARK
        _v1_set_cell_text_style(row[5], ratio_color, align=WD_ALIGN_PARAGRAPH.CENTER)
        _prevent_row_split(table.rows[-1])


def _customer_set_blue_headers(cells: Any, headers: list[str]) -> None:
    for cell, header in zip(cells, headers):
        _v1_set_cell(cell, header, fill=ACCENT, color="FFFFFF", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, font_size=9)
        for paragraph in cell.paragraphs:
            paragraph.paragraph_format.keep_with_next = True


def _customer_table_note(document: Document, text: str) -> None:
    paragraph = document.add_paragraph(text)
    paragraph.paragraph_format.space_after = Pt(8)
    for run in paragraph.runs:
        _v1_apply_run_font(run)
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor.from_string(TEXT_MUTED)


def _customer_add_emphasis_text(paragraph: Any, text: str, *, base_size: float = 10.5) -> None:
    for segment, highlight in _customer_emphasis_segments(text):
        run = paragraph.add_run(_customer_emphasis_text(segment, highlight))
        _v1_apply_run_font(run)
        run.font.size = Pt(base_size + 1 if highlight else base_size)
        run.font.color.rgb = RGBColor.from_string(TEXT_DARK)
        run.bold = bool(highlight)


def _customer_emphasis_text(segment: str, highlight: bool) -> str:
    if highlight and _customer_is_vm_name_segment(segment):
        return f" {segment} "
    return segment


def _customer_is_vm_name_segment(segment: str) -> bool:
    if _customer_is_numeric_segment(segment) or _customer_is_scope_segment(segment):
        return False
    vm_patterns = [
        r"[^，。！？（）]+?(?=\s*(?:增长|当前容量|在统计窗口|（))",
        r"Window\s+VM\s+[A-Za-z0-9_-]+",
        r"Day\s+VM",
        r"VM\s+[A-Za-z0-9_-]+",
    ]
    return any(re.fullmatch(pattern, segment) for pattern in vm_patterns) or bool(segment.strip())


def _customer_is_numeric_segment(segment: str) -> bool:
    numeric_patterns = [
        r"[+-]?\d+(?:\.\d+)?\s*(?:B|KB|MB|GB|TB|PB)",
        r"\d+(?:\.\d+)?%",
        r"\d+\s*天",
    ]
    return any(re.fullmatch(pattern, segment) for pattern in numeric_patterns)


def _customer_is_scope_segment(segment: str) -> bool:
    scope_patterns = [
        r"全部\s*Tower（\d+\s*个）",
        r"全部集群（\d+\s*个）",
        r"Tower\s+[A-Za-z0-9_-]+",
        r"Cluster\s+[A-Za-z0-9_-]+",
        r"[A-Za-z0-9_-]+(?:\s*/\s*[A-Za-z0-9_-]+)+",
    ]
    return any(re.fullmatch(pattern, segment) for pattern in scope_patterns)


def _customer_emphasis_segments(text: str) -> list[tuple[str, bool]]:
    patterns = [
        r"[+-]\d+(?:\.\d+)?\s*(?:B|KB|MB|GB|TB|PB)",
        r"\d+(?:\.\d+)?\s*(?:B|KB|MB|GB|TB|PB)",
        r"\d+(?:\.\d+)?%",
        r"\d+\s*天",
        r"全部\s*Tower（\d+\s*个）",
        r"全部集群（\d+\s*个）",
        r"[A-Z0-9][A-Za-z0-9_-]+(?:\s*/\s*[A-Z0-9][A-Za-z0-9_-]+)+",
        r"Tower\s+[A-Za-z0-9_-]+",
        r"Cluster\s+[A-Za-z0-9_-]+",
        r"(?<=下的 )[^，。！？（）]+?(?=\s*(?:增长|当前容量|在统计窗口|（))",
        r"Window\s+VM\s+[A-Za-z0-9_-]+",
        r"Day\s+VM",
        r"VM\s+[A-Za-z0-9_-]+",
    ]
    combined = re.compile("|".join(f"({pattern})" for pattern in patterns))
    segments: list[tuple[str, bool]] = []
    cursor = 0
    for match in combined.finditer(text):
        if match.start() > cursor:
            segments.append((text[cursor:match.start()], False))
        segments.append((match.group(0), True))
        cursor = match.end()
    if cursor < len(text):
        segments.append((text[cursor:], False))
    return segments or [(text, False)]


def _customer_add_figure(document: Document, image: BytesIO, caption: str, width: float) -> None:
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_after = Pt(3)
    run = paragraph.add_run(caption)
    _v1_apply_run_font(run)
    run.bold = True
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor.from_string(ACCENT_DARK)
    picture = document.add_paragraph()
    picture.alignment = WD_ALIGN_PARAGRAPH.CENTER
    picture.add_run().add_picture(image, width=Inches(width))


def _customer_risk_matrix_table(document: Document, clusters: list[dict[str, Any]], top_vms: list[dict[str, Any]]) -> None:
    headers = ["风险项", "当前状态", "风险等级", "评估说明"]
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _v1_set_table_width(table, [1600, 1500, 1200, 4400])
    _customer_set_blue_headers(table.rows[0].cells, headers)
    for index, row_data in enumerate(_customer_risk_matrix_rows(clusters, top_vms), start=1):
        row = table.add_row().cells
        _v1_set_docx_row(row, [row_data["item"], row_data["status"], row_data["level"], row_data["description"]])
        if index % 2 == 0:
            _v1_shade_row(row, ACCENT_SOFT)
        _v1_set_cell_text_style(row[2], _risk_text_color(row_data["level"]), bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)


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


def _v1_clear_paragraph(paragraph: Any) -> None:
    for run in paragraph.runs:
        run._element.getparent().remove(run._element)


def _v1_set_docx_row(cells: Any, values: list[Any]) -> None:
    for cell, value in zip(cells, values):
        _v1_set_cell(cell, value)


def _v1_set_cell_text_style(cell: Any, color: str, *, bold: bool | None = None, align: int | None = None) -> None:
    for paragraph in cell.paragraphs:
        if align is not None:
            paragraph.alignment = align
        for run in paragraph.runs:
            run.font.color.rgb = RGBColor.from_string(color)
            if bold is not None:
                run.bold = bold


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


def _repeat_table_header(row: Any) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    header = tr_pr.find(qn("w:tblHeader"))
    if header is None:
        header = OxmlElement("w:tblHeader")
        tr_pr.append(header)
    header.set(qn("w:val"), "true")


def _prevent_row_split(row: Any) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    cant_split = tr_pr.find(qn("w:cantSplit"))
    if cant_split is None:
        cant_split = OxmlElement("w:cantSplit")
        tr_pr.append(cant_split)


def _v1_shade_row(cells: Any, fill: str) -> None:
    for cell in cells:
        _shade_cell(cell, fill)


def _v1_set_cell(
    cell: Any,
    value: Any,
    fill: str | None = None,
    color: str = TEXT_DARK,
    bold: bool = False,
    align: int | None = None,
    font_size: int = 8,
) -> None:
    cell.text = ""
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    if fill:
        _shade_cell(cell, fill)
    paragraph = cell.paragraphs[0]
    paragraph.alignment = align if align is not None else WD_ALIGN_PARAGRAPH.LEFT
    run = paragraph.add_run(str(value))
    _v1_apply_run_font(run)
    run.bold = bold
    run.font.size = Pt(font_size)
    run.font.color.rgb = RGBColor.from_string(color)
    for margin in ["top", "start", "bottom", "end"]:
        _v1_set_cell_margin(cell, margin, 110)


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


