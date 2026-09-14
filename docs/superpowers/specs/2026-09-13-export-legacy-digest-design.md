# export legacy 消化设计（49-13 后续维护）

更新时间：2026-09-13
状态：设计完成，待实施
关联：task_plan.md Phase 49 第 13 项后续维护；docs/pending-tasks.md P3

## 1. 背景

49-13 拆分 export.py 时，`legacy.py` 作为"其余未归类函数（逐步消化）"的占位。拆分后 export/ 包（common/word/excel）里残留了一批**不可达死代码**（v1 模板遗留），本次消化。

## 2. 原则

- **纯结构重构**：不改任何行为、不改对外接口。
- 死代码判定：从有效入口（`build_report_docx` customer 版、`build_report_xlsx`）出发做可达性分析，不可达即死代码。
- 验收：全量 308 测试回基线；Word/Excel 导出真实验证。

## 3. 死代码清单（ast 可达性分析，共 60 个函数）

- **word.py（46）**：v1 版 `build_report_docx`（被 customer 版遮蔽的死入口）+ 其 14 个助手（`_setup_document`/`_add_cover`/`_add_callout`/`_add_paragraph_table`/`_add_cluster_directory`/`_add_cluster_table`/`_add_vm_table`/`_add_new_vm_table`/`_setup_footer`/`_footer_label`/`_overview_sentence`/`_add_single_cluster_summary`/`_add_single_cluster_charts`）+ 31 个 `_v1_*` + `_vm_growth_bucket_label`。
- **excel.py（7）**：`_add_xlsx_growth_chart`/`_autosize`/`_style_sheet`/`_write_cluster_summary_sheet`/`_write_directory_sheet`/`_write_scope_detail_sheet`/`_write_vm_top_sheet`。
- **common.py（7）**：`_add_cluster_growth_chart`/`_add_figure`/`_chart_color`/`_cluster_top_growth_bar_chart`/`_merged_cluster_points`/`_report_vm_count`/`_scope_trend_line_chart`。

## 4. 处理方式

- **直接删除**死代码（不可达，删除行为不变），并清理各文件 `from .common import (...)` 中对死函数的引用。
- 保留活跃函数（`_shade_cell`/`_docx_bytes`/`_risk_text_color`/`_risk_word_color`/`_repeat_table_header`/`_prevent_row_split`/`_cluster_trend_line_chart`/`_vm_top_growth_bar_chart` 等，被 customer 版使用）。
- `legacy.py` 保持占位（后续如有新未归类函数再填充）。

## 5. 验收

- 全量 308 测试回基线。
- Word/Excel 导出真实验证（.3 产物抽查）。
- 死函数残留引用为空。

## 6. 不做范围

- 不改任何函数逻辑、命名、payload 字段。
- 不搬移 common.py 中"仅一方消费"的活跃函数（可选优化，非本项）。
