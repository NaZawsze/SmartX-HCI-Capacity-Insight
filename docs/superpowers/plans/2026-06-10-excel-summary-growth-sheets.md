# Excel Summary And Growth Sheets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正 Excel 摘要 KPI 字体、日增长标题布局，并新增独立月增长详情 Sheet。

**Architecture:** 继续复用客户模板与 `openpyxl` 导出流程。日/月增长详情共用一个写入函数和同一份布局规则，月增长 Sheet 由日增长模板复制后填充 `month_fastest_growing_vms`，确保样式一致。

**Tech Stack:** Python 3.12、openpyxl、unittest、Docker Compose。

---

### Task 1: Add Excel Regression Tests

**Files:**
- Modify: `backend/tests/test_v2_report_exports.py`

- [ ] 断言摘要 KPI 表第 1、3 行，即第 4、6 行，所有非空单元格为黑色粗体。
- [ ] 断言 `日增长详情` 存在 `A1:I1` 合并范围。
- [ ] 断言 Sheet 顺序在 `日增长详情` 后包含 `月增长详情`，且月增长详情使用月增长 VM 数据。
- [ ] 运行目标测试，确认旧实现按预期失败。

### Task 2: Implement Shared Growth Detail Writer

**Files:**
- Modify: `backend/app/v2/reports/export.py`

- [ ] 将日增长详情写入函数扩展为可传入标题和增长量列名。
- [ ] 合并增长详情标题行 `A1:I1`，保留用户模板列宽、行高和冻结窗格。
- [ ] 从 `日增长详情` 复制生成 `月增长详情`，填入 `month_fastest_growing_vms`。
- [ ] 将摘要第 4、6 行字体改为 `Noto Sans CJK SC`、黑色、粗体。

### Task 3: Verify And Deploy

**Files:**
- Modify: `progress.md`

- [ ] 运行完整报表测试、`py_compile` 和 `git diff --check`。
- [ ] 同步到 `10.20.11.3:/opt/smartx-storage-forecast-v2`。
- [ ] 重建并 recreate `web-api`，运行容器报表测试。
- [ ] 用真实数据导出 14 天 Excel，检查摘要字体、标题合并、月增长 Sheet 和健康状态。
