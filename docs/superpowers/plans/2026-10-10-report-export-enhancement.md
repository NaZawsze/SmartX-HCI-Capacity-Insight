# Phase 73 - 报表导出增强实施计划：所有者/虚拟机组/已分配全量落位与视觉优化

- 关联设计：[docs/superpowers/specs/2026-10-09-report-export-owner-folder-allocated-design.md](../../superpowers/specs/2026-10-09-report-export-owner-folder-allocated-design.md)
- 关联 Phase：Phase 73
- 状态：**已完成**

## 1. 目标

补齐 Word 和 Excel 导出报表中「已分配容量」、「虚拟机所属者」、「虚拟机组」在集群层与各 VM 详细表格中的全部缺口，并全面优化导出报表的视觉质感（排版、列宽、行高、卡片与表头层级）。

## 2. 决策点确定（采纳默认值）

1. Word 使用率可视化不加第三条「已分配率」条（保持双条精简）。
2. Word 不加新建 VM 章节（保持 Word 结构专注于容量增长分析）。
3. Excel 执行摘要 KPI 条从 4 格扩充为 5 格（已用 / 已分配 / 周期增长 / 90天预测 / 风险状态）。

## 3. 实施步骤

- [x] **步骤 1：Word 导出增强与视觉优化** (`backend/app/v2/reports/export/word.py`)
  - `_customer_cluster_info_table`：在「总容量」后添加「总已分配容量」行。
  - `_customer_cluster_growth_table`：增加「已分配（占比）」列（7列），对齐宽度与文本样式。
  - 视觉优化：核对表格边框、间距、表头字号与对齐。
- [x] **步骤 2：Excel 导出增强与视觉优化** (`backend/app/v2/reports/export/excel.py`)
  - `_write_xlsx_template_summary`：KPI 条扩充为 5 格（加入已分配容量与已分配率），优化 A~E 列宽与行高。
  - `_write_xlsx_template_capacity_trend`：在「总容量」后增加「已分配容量」与「已分配率」两列（11列），调整筛选范围与列宽。
  - `_write_simple_vm_sheet`：新建 VM Sheet 增加「所有者」与「虚拟机组」两列（7列），设置空值与合理列宽。
  - `_write_cluster_vm_sheet` / `_vm_xlsx_row`：头部信息行增加「已分配容量」（10列），VM 表格增加「所有者」与「虚拟机组」（7列），同步更新 `_style_vm_rows`、`_add_excel_table`、标题合并与列宽。
- [x] **步骤 3：单元测试覆盖与本地回归**
  - 在 `backend/tests/test_v2_report_exports.py` 中更新或新增断言：
    - Word 范围基本信息表包含「总已分配容量」，集群增长表 7 列含「已分配（占比）」。
    - Excel 执行摘要 KPI 5 格，容量趋势 11 列含已分配与已分配率。
    - Excel 本日/本月新建 VM Sheet 7 列包含所有者与虚拟机组。
    - Excel 每集群 Sheet 头部 10 列、VM 表格 7 列。
    - 针对 allocated 缺失/为 0、owner/folder 为空的情况做鲁棒性断言。
  - 运行本地测试全量通过（28 tests OK）。
- [x] **步骤 4：代码检查与本地提交**
  - 执行 `git diff --check`。
  - 提交至 `dev2` 分支（a52aefe）。
- [x] **步骤 5：远端部署与真机导出验证**
  - 同步代码至 `10.20.11.3`。
  - 在 `.3` 容器内运行导出测试 28 项全绿。
  - 部署并重启 web-api 服务。
  - 调用真实接口导出 Word（200KB）与 Excel（105KB），逐表断言与目视核对全部通过。
- [x] **步骤 6：收尾与记录**
  - 更新 `task_plan.md` 与 `progress.md`。
