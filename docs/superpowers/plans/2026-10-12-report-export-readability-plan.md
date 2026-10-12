# Phase 79 实施计划：报表导出可读性改造（Word 格式/配色 + 导出层口径统一）

- 关联设计：[docs/superpowers/specs/2026-10-12-report-export-readability-design.md](../../superpowers/specs/2026-10-12-report-export-readability-design.md)
- 关联 Phase：Phase 79（task_plan.md）
- 基线标记：`beforeworkbuddydf41f`
- 状态：**实施中**

## 1. 目标

按设计 D1–D10 提升 Word 报表可读性（标题层级、注记字号/对比度、字体、强调色、表格边框、使用率条、封面收尾），并统一导出层单位标签与风险色判定。

## 2. 步骤

- [ ] **步骤 1：`common.py` 常量与字体/单位**
  - 新增常量：`NOTE_TEXT="475569"`、`TABLE_BORDER="BFDBFE"`、`EMPHASIS=ACCENT_DARK`、`WORD_H1/H2/H3/BODY/NOTE/MICRO_SIZE`（18/14/12/10.5/10/9）。
  - 字体：`DOCX_FONT_ASCII`→`"Noto Sans"`；`DOCX_FONT_EAST_ASIA`→`"Noto Sans CJK SC"`；`CHART_FONT_FAMILY`→`"Noto Serif CJK SC"`。
  - `_bytes_label` 单位表改 `["B","KiB","MiB","GiB","TiB","PiB"]`。
  - 判据：`python3 -c "import ast;..."` 语法通过；`_bytes_label(1024**3)` 返回 `1.00 GiB`。

- [ ] **步骤 2：`word.py` 排版改动（D1/D2/D4/D5/D6/D7）**
  - D1：`_customer_setup_document` 的 `Heading 2/3` 默认字号 14/12；`_customer_subtitle` 按 level 取 14/12。
  - D2：注记类文字 `Pt(9)`→`WORD_NOTE_SIZE`、`Pt(8)`→`WORD_MICRO_SIZE`、`TEXT_MUTED`→`NOTE_TEXT`（逐处核对，约 12 处）。
  - D4：`_customer_add_emphasis_text` 的 highlight run 颜色改 `EMPHASIS`。
  - D5：每张 `table.style="Table Grid"` 的表补 `_docx_set_table_borders(table, TABLE_BORDER)`；info 表 `"000000"`→`TABLE_BORDER`；KPI 条 `"FFFFFF"` 保持。
  - D6：`_customer_usage_bar` 字符画改 1×20 无边框表格（`autofit=False`、单元格零边距、按比例填 `color`/浅灰）。
  - D7：`_customer_cover_meta` 空值行不渲染；目录提示行改注记样式。
  - 判据：本地导出可生成 docx 不抛异常。

- [ ] **步骤 3：`word.py` 口径/判定改动（D8 正则 / D9 风险色）**
  - D8：`_customer_is_numeric_segment` 与 `_customer_emphasis_segments` 的数值正则同步为 `(?:B|KiB|MiB|GiB|TiB|PiB)`。
  - D9：`_risk_word_color` 改显式等级映射（高→`RATIO_RED`、中/关注→`RATIO_ORANGE`、正常→`27AE60`、其余→`TEXT_DARK`）。
  - 判据：单测中强调段与风险色断言通过。

- [ ] **步骤 4：单测更新（`backend/tests/test_v2_report_exports.py`）**
  - 新增/更新断言：二级 14pt / 三级 12pt；注记 10pt 且色 `475569`；强调数字色 `1A3C6E`；表格边框色 `BFDBFE`（遍历全部表断言无 `000000`）；使用率条为表格且列数=20；Word 数值单位为 `GiB/TiB`；`_risk_word_color` 三档映射；封面不含「客户名称：」空行。
  - 判据：新增断言可独立失败（先红后绿）。

- [ ] **步骤 5：本地回归与提交**
  - `PYTHONPATH=backend python3 -m unittest backend/tests/test_v2_report_exports.py` 全绿。
  - `python3 -m unittest backend.tests.test_deployment_config` 通过。
  - `git diff --check` 无输出；本地单提交 `dev2`（不推送）。

- [ ] **步骤 6：`.3` 真机验证**
  - 同步改动文件至 `10.20.11.3` 源码目录与容器，容器内跑 `tests.test_v2_report_exports` 全绿。
  - 运行 `python3 scripts/verify_remote_exported_reports.py http://10.20.11.3:8000`，端到端断言通过并刷新桌面 Word/Excel。
  - 判据：容器测试 OK + 脚本 exit 0 + 桌面文件更新时间刷新。

- [ ] **步骤 7：收尾**
  - `progress.md` 记录证据（提交号、测试输出、远端结果）；`docs/doc-map.md` §5 登记设计与计划；`task_plan.md` Phase 79 勾选完成。

## 3. 回滚

- 单提交回滚：`git revert <commit>`（纯展示层，无数据/接口/存储变更）。
- 局部回退：D6 若不稳，按设计决策点备选回退为「字符画 + 放大字号」。
- 全量回退基线：`git reset --hard beforeworkbuddydf41f`（会丢弃之后提交，慎用）。
