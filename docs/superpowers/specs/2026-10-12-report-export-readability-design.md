# 报表导出可读性改造设计：Word 格式/配色治理 + 导出层口径统一 —— Phase 79

- 状态：**设计定稿（2026-10-12），实施中**。
- 来源：2026-10-12 用户审阅导出物后提出「文档我觉得人读起来不太容易，特别是格式和颜色方面」，并指示「按照 AGENTS.md 来做」。
- 基线标记：`beforeworkbuddydf41f`（改造前快照，仅本地 tag，未推送）。
- 现状盘点基于对 `/Users/nazawsze/Desktop/SmartX_存储容量分析报告_20261010.docx` 的**逐段实测**（用 python-docx 导出每段的字号、颜色、底色、对齐、列宽，证据见 §2）与导出层代码走查。

## 1. 范围与交付物

| # | 交付物 | 说明 |
| --- | --- | --- |
| D1 | **标题层级拉开** | 二级标题 13pt → **14pt**，三级标题 13pt → **12pt**（当前二者同为 13pt 粗体深蓝，层级消失）；`Heading 2/3` 样式默认值同步 |
| D2 | **注记文字可读化** | 说明/注记/声明类文字由 9pt `#999999`（对比度 **2.85:1**）改为 **10pt `#475569`**（对比度 **7.6:1**）；微标签/页脚由 8pt → 9pt |
| D3 | **正文字体改无衬线并与 Excel 统一** | `Noto Serif` → `Noto Sans`，`Noto Serif CJK SC` → `Noto Sans CJK SC`；图表字体 `Noto Serif CJK **JP**` → `Noto Serif CJK **SC**`（修正日文字形变体） |
| D4 | **关键数字强调补色** | 关键发现中的强调数字/名称由「同色加粗」改为 **品牌深蓝 `#1A3C6E` 加粗** |
| D5 | **表格边框软化** | 由黑色网格（`Table Grid` 默认 / `_docx_set_table_borders(..., "000000")`）改为**浅蓝细线 `#BFDBFE`**，与 Excel 卡片风格统一 |
| D6 | **使用率条改表格化比例条** | 由 8pt `█/░` 字符画（非等宽环境易错位）改为 **1×20 无边框表格**，按比例填色；跨字体/跨平台渲染稳定 |
| D7 | **封面与目录提示收尾** | 封面「客户名称：」当前值恒为空 → **空值行不渲染**；「请在 Word/WPS 中更新目录」提示行改用注记样式（10pt `#475569`） |
| D8 | **单位标签统一为二进制** | `_bytes_label` 单位名由十进制 `B/KB/MB/GB/TB/PB`（却按 1024 换算，属**错标**）改为二进制 `B/KiB/MiB/GiB/TiB/PiB`，与 Excel 的 `_xlsx_bytes_label` 一致 |
| D9 | **`_risk_word_color` 改显式等级映射** | 现为子串匹配 + `or/and` 混用（`"高" in label or "风险" in label and "正常" not in label`），改按明确等级枚举，消除优先级歧义与误判 |
| D10 | **排版常量抽取** | 新增/改动的字号、颜色抽为 `common.py` 常量，减少硬编码漂移 |

不做：Excel Sheet 结构/布局改动（Phase 73~78 已定稿）；Word 章节结构改动；采集/接口/前端改动；历史导出物回填。

## 2. 现状实测（问题清单与证据）

用 `python-docx` 对导出文档逐段/逐表实测，关键证据：

| 证据 | 实测值 | 问题 |
| --- | --- | --- |
| 二级标题 run | `sz=13.0 b=True c=1A3C6E` | 与三级标题**完全同字号同色** |
| 三级标题 run | `sz=13.0 b=True c=1A3C6E` | 层级消失（代码根因：`_customer_subtitle` 对 level≥3 也强制 `Pt(13)`） |
| 注记/说明 run | `sz=9.0 c=999999` | 对比度 2.85:1，低于 WCAG AA 4.5:1；且 9pt 偏小。出现在：封面副标题、封面元信息、生成说明、数据质量说明、口径说明、统计窗口行、图表说明、声明、表注 |
| 关键发现强调 run | `sz=11.5 b=True c=333333` | 与正文同色，仅加粗+1pt，强调感弱 |
| 使用率条 run | `sz=8.0 c=1A3C6E`，文本 `████████░░░░…` | 字符画 + 8pt，非等宽环境易错位 |
| 表格 | `style=Table Grid`；info 表 `_docx_set_table_borders(..., "000000")` | 黑色网格线，与 Excel 浅蓝细线风格冲突 |
| 封面 | `P012 客户名称：`（值为空） | 交付物出现空占位行 |
| 字体 | 全篇 `font=Noto Serif`（eastAsia=`Noto Serif CJK SC`） | 衬线体，与 Excel 的 `Noto Sans CJK SC` 不一致 |
| 单位 | Word `500.00 GB` / `219.18 TB`；Excel `500.00 GiB` / `219.18 TiB` | 同数据两交付物写法不一致，且 Word 把 TiB 标成 TB |

代码侧：`_bytes_label`（`common.py:751`，十进制单位名 + 1024 换算）与 `_xlsx_bytes_label`（`excel.py:839`，二进制单位名）为**两份实现**；`_customer_is_numeric_segment` / `_customer_emphasis_segments`（`word.py:873/893`）的强调正则以 `(?:B|KB|MB|GB|TB|PB)` 匹配数值 —— **D8 改单位名后必须同步该正则**，否则强调失效。

## 3. 目标取值（口径）

### 3.1 字号

| 用途 | 现状 | 目标 |
| --- | --- | --- |
| 一级标题（章） | 18pt | 18pt（不变） |
| 二级标题（节） | 13pt | **14pt** |
| 三级标题（小节） | 13pt | **12pt** |
| 正文 / 关键发现 | 10.5pt | 10.5pt（不变） |
| 注记 / 说明 / 声明 | 9pt | **10pt** |
| 微标签 / 页脚 | 8pt | **9pt** |
| 封面主标题 / 副标题 | 28 / 13pt | 28 / 13pt（不变） |

### 3.2 颜色（白底对比度）

| 用途 | 现状 | 目标 | 对比度 |
| --- | --- | --- | --- |
| 正文 | `#333333` | 不变 | 12.6:1 |
| 注记 / 说明 | `#999999` | **`#475569`**（Slate-600） | 2.85:1 → **7.6:1** |
| 标题 / 强调数字 | `#1A3C6E` | 强调数字也用 `#1A3C6E` | 11.0:1 |
| 表格细线 | `#000000` | **`#BFDBFE`**（浅蓝） | — |
| 卡片底 / 斑马纹 | `#F0F4FA` / `#F7F9FC` | 不变 | — |

### 3.3 新增常量（`common.py`）

```python
NOTE_TEXT = "475569"        # 注记文字色（替代 TEXT_MUTED 的 999999 用途）
TABLE_BORDER = "BFDBFE"     # 表格细线
EMPHASIS = ACCENT_DARK      # 关键数字强调色（1A3C6E）
WORD_H1_SIZE = 18
WORD_H2_SIZE = 14
WORD_H3_SIZE = 12
WORD_BODY_SIZE = 10.5
WORD_NOTE_SIZE = 10
WORD_MICRO_SIZE = 9
```

`TEXT_MUTED`（`999999`）保留常量定义以免外部引用断裂，但 Word 侧**不再用于正文可读文本**（仅保留给极其次要的元素，若有）。

## 4. 逐文件改动面

| 文件 | 改动 |
| --- | --- |
| `backend/app/v2/reports/export/common.py` | ① 字体常量：`DOCX_FONT_ASCII`→`Noto Sans`、`DOCX_FONT_EAST_ASIA`→`Noto Sans CJK SC`、`CHART_FONT_FAMILY`→`Noto Serif CJK SC`；② `_bytes_label` 单位表改二进制（`B/KiB/MiB/GiB/TiB/PiB`）；③ 新增 §3.3 常量 |
| `backend/app/v2/reports/export/word.py` | ① `_customer_setup_document`：`Heading 2/3` 默认字号改 14/12；② `_customer_subtitle`：字号按 level 取 14/12；③ `_customer_add_emphasis_text`：highlight run 颜色改 `EMPHASIS`；④ 注记类 `Pt(9)`→`WORD_NOTE_SIZE`、`Pt(8)`→`WORD_MICRO_SIZE`、颜色 `TEXT_MUTED`→`NOTE_TEXT`（约 12 处）；⑤ 各 `table.style="Table Grid"` 后补 `_docx_set_table_borders(table, TABLE_BORDER)`；info 表 `"000000"`→`TABLE_BORDER`；⑥ `_customer_usage_bar`：字符画改 1×20 无边框表格按比例填色；⑦ `_customer_cover_meta`：空值行不渲染；目录提示行改注记样式；⑧ `_customer_is_numeric_segment` / `_customer_emphasis_segments` 正则同步二进制单位名；⑨ `_risk_word_color` 改显式等级映射 |
| `backend/app/v2/reports/export/excel.py` | 不改结构；仅核对 `_xlsx_bytes_label` 已是二进制单位名（无需改） |
| `backend/tests/test_v2_report_exports.py` | 新增/更新断言：二级 14pt / 三级 12pt、注记 10pt 且颜色 `475569`、强调数字色 `1A3C6E`、表格边框色 `BFDBFE`、使用率条为表格且单元格数=20、Word 数值单位为 `GiB/TiB`、`_risk_word_color` 各等级映射、封面无空值行 |

不改：`reports/service.py`、`api/reports.py`、采集链路、前端页面、Excel 布局。

## 5. 决策点（默认值已选，用户可推翻）

| 点 | 默认 | 备选 |
| --- | --- | --- |
| D8 单位标签 | **改为 GiB/TiB**（技术正确 + 与 Excel 一致） | 保持 TB/GB（客户习惯口径） |
| D3 正文字体 | **改为无衬线 Noto Sans**（与 Excel 统一） | 保持衬线 Noto Serif |
| D6 使用率条 | **改表格化比例条** | 保留字符画（仅放大字号） |
| D7 封面空「客户名称」 | **空值不渲染** | 保留空占位行 |
| 图表字体（Serif→Sans） | **本轮不做**（改 Sans 需同步容器字体路径与 `test_deployment_config` 夹具，避免 CJK 字形丢失） | 下一轮单列 |

## 6. 测试计划

1. **本地定向**：`PYTHONPATH=backend python3 -m unittest backend/tests/test_v2_report_exports.py`（现有 29 项 + 新增断言）全绿。
2. **相关回归**：`test_deployment_config.py`（图表字体相关断言）、`test_report*` 相关用例。
3. **`.3` 真机**：同步代码 → 容器内跑 `tests.test_v2_report_exports` 全绿 → `scripts/verify_remote_exported_reports.py http://10.20.11.3:8000` 端到端断言通过 → 刷新桌面 Word/Excel。
4. **桌面 Word 实测断言**（脚本逐项）：二级 14pt / 三级 12pt；注记 10pt 且颜色 `475569`；正文 eastAsia 为 `Noto Sans CJK SC`；表格边框 `BFDBFE`；使用率条为 1×20 表格；数值单位为 `GiB/TiB`；封面无「客户名称：」空行。
5. 验收记录写入 `progress.md`，样本留存 `/tmp/report-sample/`。

## 7. 风险与回滚

- **风险 1（中）**：D6 表格化比例条涉及 docx 表格宽度/边距控制，可能在不同 Word 版本下宽度自适应差异 → 用单测断言表格存在且为 20 列，真机导出后人工目视一次；若不稳定，回退为「仅放大字号」的字符画方案（决策点备选）。
- **风险 2（中）**：D8 改单位名影响强调正则 → 已列入改动面 ⑧，单测覆盖「强调段仍被识别」。
- **风险 3（低）**：D5 表格边框逐表补色，遗漏某张表 → 单测遍历全部表格断言无黑色边框。
- **回滚**：纯展示层单提交，`git revert <commit>` 即可；无数据/接口/存储变更，对老版本 web-api 与既有导出物无影响。

## 8. 后续待办（不进本 Phase）

- 图表字体 Serif→Sans（需核实容器内 `NotoSansCJK-Regular.ttc` 存在 + 同步 `CHART_FONT_PATH` 与 `test_deployment_config.py` 夹具）。
- 字体可移植性（客户机缺 Noto 时的回退链设计）。
- Word/Excel 摘要口径对齐（Word KPI 4 格 vs Excel 5 格含已分配）—— 属产品口径决策，单列。
