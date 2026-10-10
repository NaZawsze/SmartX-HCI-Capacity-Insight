# 报表导出增强设计：所有者 / 虚拟机组 / 已分配 全量落位 —— Phase 73

- 状态：**设计定稿（2026-10-09），待用户批准开工**。
- 来源：2026-10-09 用户需求——「导出的 word 和 xlsx 需要有新增的虚拟机组、虚拟机所属者，还有已分配」。
- 前置事实：Phase 69 已给 Word/Excel 的 **VM 增长类表格**加了「所有者」「虚拟机组」两列，但导出物里还有
  多处 VM 表格和集群层信息**没有**这两列与「已分配」；本设计把它们补齐。
- 现状盘点基于 `.3`（v0.5.4，201 台 VM / 2 塔）真实导出样本（`/tmp/report-sample/sample.docx|sample.xlsx`，
  2026-10-09，period_days=30），逐表核对，见 §2。

## 1. 范围与交付物

| # | 交付物 | 说明 |
| --- | --- | --- |
| D1 | **已分配进集群层信息** | Word「范围基本信息」表 + 「集群增长表」、Excel「执行摘要」KPI 条 + 「容量趋势」表 + 每集群 Sheet 头部信息行，各加「已分配容量」（数据源 `clusters[].allocated`，接口已下发、前端报表页已在用） |
| D2 | **新建 VM 表加两列** | Excel「本日新建VM」「本月新建VM」两 Sheet 的 VM 行加「所有者」「虚拟机组」列（数据源 `labels.owner/folder_name`，`_new_vm_reports_from_series` 已带 `latest_label_by_vm` 标签，无需动采集） |
| D3 | **每集群 Sheet VM 表加两列** | Excel 每集群 Sheet 的「增长量/增长率全部虚拟机」两段（`_vm_xlsx_row`）加两列，与 TOP100/日/月增长详情口径一致 |
| D4 | **新建 VM 两列的 Word 缺口** | Word 正文没有新建 VM 章节（产品现状，Word 版本历来只做增长分析）——**不在本次补**，保持 Word/Excel 各自既有章节结构；新建 VM 信息以 Excel 两 Sheet 为准 |

不做：按所有者/虚拟机组筛选或分组统计（后续按需立项）；VM 页/概览页改动（Phase 69 已覆盖）；
Word 加新建 VM 章节（同 D4 口径）；历史数据回填（owner/folder 随采集自然更新）。

## 2. 现状盘点（真实导出样本逐表核对）

### 2.1 Word（`build_report_docx`，章节固定：摘要/集群概览/VM 增长分析/图表/风险建议）

| 表 | 现状列 | 缺口 |
| --- | --- | --- |
| §1 执行摘要 KPI 条（table1/2） | 已用/增长/预测/风险 | 不加（保持 KPI 4 格布局） |
| §2.1 范围基本信息（`_customer_cluster_info_table`） | Tower/集群数量、已用、总容量、风险、样本数 | **加「总已分配容量」一行**（Σ clusters[].allocated） |
| §2.2 集群增长表（`_customer_cluster_growth_table`） | Tower/集群/14/30/90 天增长/预测 | **加「已分配容量（占比）」一列** |
| §2.3 使用率条 | 当前/90 天预测 | 可选加「已分配率」条（见 §5 决策点） |
| §3.x VM 增长表（`_customer_vm_table`，增长量/增长率 Top20 ×N 集群） | 已含所有者/虚拟机组（Phase 69） | 无 |
| §5 风险矩阵表 | 集群/使用率/风险 | 不加（风险口径不含已分配，避免语义混淆） |

### 2.2 Excel（`build_report_xlsx`，11 个 Sheet）

| Sheet | 现状 | 缺口 |
| --- | --- | --- |
| 执行摘要 | KPI 4 格（已用/增长/预测/风险） | **加「已分配容量」格**（含占总容量百分比副行），KPI 4→5 格 |
| 容量趋势 | Tower/集群/已用/增长/预测/总容量/使用率/耗尽天数/风险 | **加「已分配容量」「已分配率」两列** |
| VM增长TOP100 | 已含两列（Phase 69） | 无 |
| 日/月增长详情 | 已含两列（Phase 69） | 无 |
| 本日/本月新建VM | Tower/集群/VM/当前容量/首次出现时间 | **加「所有者」「虚拟机组」两列**（`_write_simple_vm_sheet`） |
| 每集群 Sheet（SMARTX-TT-WW 等） | 头部 9 列信息行 + VM 表 5 列（VM/当前/期初/增长量/增长率） | **头部加「已分配容量」**；VM 两段各加两列（`_vm_xlsx_row`） |
| 封面/数据质量说明 | 与集群明细无关 | 不动 |

### 2.3 数据源核对（全部已存在，无需动采集/接口）

- `owner` / `folder_name`：`reports/service.py::_latest_vm_labels()` 已从 `vm_latest` 读出并放进每个
  VM item 的 `labels`；**新建 VM 列表也经 `latest_label_by_vm` 合并**（`_new_vm_reports_from_series` 签名已带
  该参数，Phase 69 同批接通），因此 Excel 新建 VM Sheet 直接读 `labels` 即可。
  `.3` 数据覆盖：201 台 VM 中 177 台有 owner、20 台有 folder_name（空值显示 `-`，与既有口径一致）。
- `allocated`：`reports/service.py` 的 `clusters[].allocated`（instant 指标
  `smartx_cluster_storage_allocated_bytes`，#75 口径 = Σ 卷供给 × 副本数，缺失按 0）已随
  `/api/reports/latest` 下发；前端报表页已显示。导出层目前**完全未消费**该字段（word.py/excel.py 0 处引用）。

## 3. 实施改动面（仅导出层，单文件为主）

| 文件 | 改动 |
| --- | --- |
| `backend/app/v2/reports/export/word.py` | ① `_customer_cluster_info_table`：rows 加 `("总已分配容量", _bytes_label(sum(allocated)))`（放「总容量」之后）；② `_customer_cluster_growth_table`：headers/widths/values 加「已分配（占比）」列，值 `_bytes_label(cluster.allocated)` + ` · {allocated/total:.2%}`（total 缺失只显示容量） |
| `backend/app/v2/reports/export/excel.py` | ① `_write_xlsx_template_summary`：KPI 条 4→5 格（新增列「已分配容量」= Σ allocated，副行 `已分配率 {allocated/total:.2%}`）；逐格写入循环改 enumerate 长度即可，merge 范围 1..6 不变；② `_write_xlsx_template_capacity_trend`：headers 与行值在「总容量」后插「已分配容量」「已分配率」两列；③ `_write_simple_vm_sheet`：headers 加「所有者」「虚拟机组」，行值从 `labels` 取（空 `-`），列宽 D/E 后移；④ `_write_cluster_vm_sheet`：头部信息行第 2 行 headers 与第 3 行值加「已分配容量」；`_vm_xlsx_row` 两列插入（`include_cluster` 与否两个分支都要对齐），`_apply_cluster_sheet_layout`/`_add_excel_table` 列数参数 5→7 同步 |
| `backend/tests/`（新增/扩展） | ① word：info 表含「总已分配容量」行、增长表 7 列含占比；② excel：摘要 KPI 5 格、容量趋势 11 列、新建 VM Sheet 7 列含 owner/folder、集群 Sheet VM 行 7 列；③ 空值与 total=0 的显示断言（`-` 与「-」副行） |

不改：`reports/service.py`（数据已齐）、`api/reports.py`、采集链路、前端页面。

## 4. 测试计划

1. **本地定向**：新增/修改的导出单测（假 report payload，覆盖多集群、单集群、allocated 缺失=0、
   owner/folder 空值四种形态）；现有导出测试全量回归（`python3 -m unittest discover backend/tests -p 'test_export*'`
   + 相关 reports 测试）。
2. **.3 真机导出比对**：部署后导出 Word/Excel（period_days=30），脚本逐项断言：
   Word info 表含「总已分配容量」且值 ≈ 343,597,383,680 B（Test 塔恢复后按当期实际值）；
   Excel 容量趋势含已分配两列；新建 VM Sheet 表头 7 列且 Test1–Test3 行 owner/folder 取自 `vm_latest`。
3. **前端无改动验证**：报表页/导出按钮回归（现有 vitest 用例）。
4. 验收记录按惯例写入 progress.md，导出样本留存 `/tmp/report-sample/`。

## 5. 决策点（默认值已选，用户可推翻）

| 点 | 默认 | 备选 |
| --- | --- | --- |
| Word 使用率可视化加「已分配率」条 | **不加**（2.3 节展示当前/预测两个比率已够，三条易混） | 加第三条 |
| Word 是否加新建 VM 章节 | **不加**（Word 历来只做增长分析，结构不动） | 对齐 Excel 加一节 |
| Excel 执行摘要 KPI 布局 4→5 格 | **接受**（merge 1..6 内均分，无版式风险） | 只在容量趋势加列、摘要不动 |

## 6. 风险与回滚

- 风险集中在 Excel 布局硬编码（合并区/列宽/`_add_excel_table` 列数）——由单测断言表头与列数锁定，
  真机导出后人工目视一次。
- 回滚：单提交还原即可（纯展示层，无数据/接口变更）。
- 兼容性：老版本 web-api 导出的报表不受影响；新导出物对下游无消费方（直接下载打开）。
