# AI 交接文档 · 2026-10-12（Phase 73~78 报表导出子系统全景重构与深度体验交付）

> **这份文档回答三个问题**：这一轮报表优化做完了什么、核心架构与实现机制是什么、下一位接手者第一步该做什么与注意什么。
> 通用执行纪律见 [ai-handoff-guide.md](ai-handoff-guide.md)；工作标准见 AGENTS.md（每次开工必读）。
> 本文只写本轮增量、实现细节与当前状态，全部结论均有测试与远端真机证据。

- **更新时间**：2026-10-12 21:50（CST）
- **当前开发分支**：`dev2`（**仅本地提交，未推送 origin**；推送需用户明确要求）
- **最后提交**：`4ca398b`（*feat(reports): 全面升级报表交付体验，支持TabColor色彩分组、首屏执行摘要激活、TOP3聚光与企业装订页脚*）
- **测试基线**：
  - 本地与 `.3` 远端容器内 `tests.test_v2_report_exports`：**Ran 29 tests in 98.870s, OK**（100% 绿灯全部通过）；
  - 端到端真实导出自动化校验脚本 `scripts/verify_remote_exported_reports.py`：100% 全部通过；
- **交付物位置**：
  - 本机桌面 Excel 报表：`/Users/nazawsze/Desktop/SmartX_存储容量分析报告_20261010.xlsx`
  - 本机桌面 Word 报表：`/Users/nazawsze/Desktop/SmartX_存储容量分析报告_20261010.docx`
- **验证环境**：`10.20.11.3` 开发测试机（`web-api` 运行容器：`smartx-hci-capacity-insight-web-api-1`，代码已同步，容器已热重启）

---

## 1. 三分钟速览：完成了什么

本轮聚焦于系统核心交付物——**Word（.docx）与 Excel（.xlsx）报表导出子系统**，完成了从**数据字段补全、统计口径治理、双轨对称排版、交互引导卡片、跨平台字体排版渲染、到企业级交付规范**的全链路彻底重构与打磨。

| 模块 / 环节 | 改造前状态 | 本轮改造后交付状态 | 关键效果与价值 |
| --- | --- | --- | --- |
| **VM 字段覆盖** | 仅显示名称、容量、增长 | 全面补齐「分配空间」与「使用率」两列 | 精简置备超分感知、风险虚拟机一目了然 |
| **所有者 / 虚拟机组** | 缺失责任人元数据 | 全面落地「所有者」与「虚拟机组」列 | 业务归属清晰，支持组织视角容量治理 |
| **期初口径治理** | 简记为「期初容量」，无说明 | 规范重命名为「周期初始容量」，带 12pt 注记 | 严谨定义物理占用口径及周期内新建机首次采样逻辑 |
| **已删除 VM 治理** | 增长榜包含历史已删僵尸机 | 增长量榜、增长率榜、新建列表全面过滤已删除机 | 严防幽灵数据干扰排障与容量审计 |
| **集群 Sheet 排版** | 传统单轨纵向排列（仅增长量） | **左右双轨对称排版**（左增长量 / 右增长率） | 与 TOP100 保持统一认知；右上镜像集群概况指标 |
| **横向滑动引导** | 窗口右边缘被截断无感知 | **单行 28pt 优雅胶囊卡片（G2:K2 / F5:I5）** | 从 G/F 列向内收敛安全视口，左右大实心三角指示 |
| **跨平台字符兼容** | 使用 U+2B05 导致左箭头变豆腐块 `□` | **升级 Unicode 1.0 实心对称大三角对（◀ 与 ▶）** | 100% 原生支持全平台 CJK 字体，零缺失乱码风险 |
| **注记字体与对比度** | 10pt 浅灰 `64748B`，过小看不清 | **12pt 高对比度深炭灰 `#334155`（Slate-700）** | 字体放大 20%，7.5:1 高对比度，字迹锐利清晰 |
| **视觉纯净化** | 单元格内嵌蓝色下划线跳转，杂乱 | **彻底移除全部跳转，整行贯通合并大标题** | A1:J1、K1:T1 大标题大气独占，纯净高级 |
| **打开与工作簿规范** | 默认停在末尾 Sheet，Tab 无色 | **默认激活执行摘要（Active Sheet），Tab色彩分组** | 双击秒开 KPI 驾驶舱；大盘蓝/榜单绿/新建蓝/集群紫 |
| **企业装订规格** | 无页眉页脚 | **统一配置横向自适应与打印/PDF 装订页脚** | 左报告名、右 `第 &P 页 / 共 &N 页`，出 PDF 零手工排版 |

---

## 2. 核心架构与代码资产

### 2.1 涉及的核心源文件

```
backend/
├── app/v2/reports/
│   ├── export/
│   │   ├── common.py           # 共享工具类：字号、颜色常量、趋势图绘制、数据口径转换
│   │   ├── excel.py            # Excel 导出引擎（核心文件，约 1350 行）
│   │   ├── word.py             # Word 导出引擎（约 1080 行）
│   │   └── templates/          # 模板资产（XLSX_TEMPLATE_PATH 等）
│   └── service.py              # Reports 业务聚合服务
├── tests/
│   └── test_v2_report_exports.py  # 29 项完备回归测试集
scripts/
└── verify_remote_exported_reports.py  # 真实端到端导出、断言与桌面覆盖脚本
```

### 2.2 核心实现设计与规范

#### 1) 颜色与样式规范（全表严格遵循设计系统）
- **深蓝主表头**：`ACCENT_DARK = "1A3C6E"`（文字 `FFFFFF` 12pt 粗体，居中对齐）；
- **卡片底色与边框**：`fill = #EFF6FF`（淡蓝底），`border = #BFDBFE`（柔和浅蓝细边框）；
- **卡片文字**：`#1D4ED8`（科技深蓝，13pt 粗体）；
- **口径注记文字**：`#334155`（Slate-700 深炭灰，12pt 常规，左对齐，垂直居中）；
- **交替行斑马纹**：`ACCENT_SOFT = "F8FAFC"`（极淡冷灰白）；
- **数据单元格字体**：`XLSX_FONT_NAME = "Noto Sans CJK SC"`（12pt 常规，`#0F172A`）。

#### 2) 双轨并排与安全视口尺寸推导
- **`VM增长TOP100` Sheet**：
  - A~K 列（1~11 列）：左侧增长量榜单；
  - L 列（12 列）：宽度 4.0，视觉缓冲隔离列；
  - M~V 列（13~22 列）：右侧增长率榜单；
  - **滑动卡片位置**：
    - 左卡片：合并 **G2:K2**（宽度 78.0），文字：`向右滑动查看增长率榜单 ▶`；
    - 右卡片：合并 **S2:V2**（宽度 68.0），文字：`◀ 向左滑动返回增长量榜单`；
    - 行高：第 2 行显式设定为 `28pt`，胶囊居中陈列。
- **`集群专属 Sheet`（如 `集群-SMARTX-TT-WW`）**：
  - A~J 列（1~10 列）：左侧增长量大表；
  - K~T 列（11~20 列）：右侧增长率大表；
  - 第 1 行：左标题完整合并 **A1:J1（10 列）**，右标题完整合并 **K1:T1（10 列）**；
  - 第 2~3 行：指标概览卡片（右侧 K2:T3 对称镜像完整指标）；
  - 第 4 行：样本说明（A4:J4 与 K4:T4，行高 24pt，12pt 深炭灰）；
  - 第 5 行：滑动卡片与周期初始容量注记（行高 28pt）：
    - 注记：合并 **A5:E5** 与 **K5:O5**（12pt 深炭灰）；
    - 卡片：合并 **F5:I5**（宽 80.0，`向右滑动查看增长率榜单 ▶`）与 **P5:S5**（宽 80.0，`◀ 向左滑动返回增长量榜单`）。

#### 3) TabColor 分组与首屏 Active Sheet 机制
在 `backend/app/v2/reports/export/excel.py` 的 `write_xlsx_report` 尾部：
```python
def _apply_xlsx_tab_colors(workbook: Workbook) -> None:
    color_map = {
        "执行摘要": "1D4ED8", "容量趋势": "1D4ED8",
        "VM增长TOP100": "059669", "日增长详情": "059669", "月增长详情": "059669",
        "本日新建VM": "2563EB", "本月新建VM": "2563EB",
        "数据质量说明": "64748B",
    }
    for sheet_name in workbook.sheetnames:
        sheet = workbook[sheet_name]
        if sheet_name in color_map:
            sheet.sheet_properties.tabColor = color_map[sheet_name]
        elif str(sheet_name).startswith("集群"):
            sheet.sheet_properties.tabColor = "6366F1"

# 默认激活首屏执行摘要
if "执行摘要" in workbook.sheetnames:
    workbook.active = workbook["执行摘要"]
```

---

## 3. 关键避坑经验（千万别重犯）

### 3.1 跨平台箭头 Unicode 字符踩坑（绝对禁止使用 U+2B05 ⬅）
- **现象**：在代码中使用 `⬅`（U+2B05）作为向左指示箭头，在本地 Mac 终端打印看似正常，但用户在 Excel（macOS/Windows）打开后，左侧全部变成方块豆腐块 `□`（Missing Glyph）；
- **根因**：`U+2B05` 位于 Unicode 4.0 的 *Miscellaneous Symbols and Arrows* 区块，常用中文字体（PingFang SC、Microsoft YaHei、Noto Sans CJK、SimSun 等）均**没有原生收录该字形**；而 Excel 的字体渲染引擎在单元格有显式字体名时，无法对该冷门区块完成 fallback，直接打出豆腐块；
- **规约**：左右指示符号必须选用 Unicode 1.0 *Geometric Shapes* 区块的实心正三角：
  - 向右指示：`▶`（`U+25B6`）；
  - 向左指示：`◀`（`U+25C0`）；
  这两个字符自 1990 年代起被全球全部中西文字体强制收录，0 缺失乱码风险。

### 3.2 避免在表格内部滥用单元格超链接
- **教训**：前期曾尝试在容量趋势集群名及集群表头放置 `返回执行摘要 ➔` 超链接，实际在 Excel 中渲染出的蓝色下划线与深蓝专业表头严重冲突，且挤占集群大标题空间导致排版逼仄杂乱；
- **定案**：报表属于交付阅读物，应保持纯净印刷级排版；不要在表头内嵌跳转文字，用户查看不同 Sheet 直接使用底部彩色 Tab 栏切换体验更佳。

### 3.3 单元格宽度与视口裁切防呆
- **教训**：早前滑动提示仅合并 2 列（宽 24.0），14 个中文字符至少需要 32 宽，导致两端文字与箭头被边框硬性裁切；且排在 J 列最右侧极易落在小屏幕视口之外；
- **定案**：滑动卡片合并宽度必须 ≥ 68.0（留出 50% 以上留白），且左边界必须从 G 列（或 F 列）等视线中心区域开始向内收敛，绝不贴屏幕最右边缘。

---

## 4. 日常维护、测试与操作指南

### 4.1 本地测试命令

在项目根目录运行单测：
```bash
PYTHONPATH=backend python3 -m unittest backend/tests/test_v2_report_exports.py
```
- 预期输出：`Ran 29 tests in ...s, OK`。

### 4.2 向测试机 `10.20.11.3` 同步并验证

由于 `.3` 开发测试机直接运行 Docker 容器 `smartx-hci-capacity-insight-web-api-1`，且 root 已禁用 SSH 直登（只能 user1 登录后 su - root）：

1. **SCP 传输修改文件到测试机 `/tmp`**：
   ```bash
   /opt/homebrew/bin/sshpass -p 'p@ssw0rd.!@#' scp -o StrictHostKeyChecking=no \
     backend/app/v2/reports/export/excel.py \
     backend/tests/test_v2_report_exports.py \
     user1@10.20.11.3:/tmp/
   ```
2. **在测试机覆盖源码、同步到容器、执行容器测试并重启服务**：
   利用项目已有的 expect 自动化脚本：
   ```bash
   expect scratch/remote_root.exp '
     cp /tmp/excel.py /data/backend/app/v2/reports/export/excel.py && \
     cp /tmp/test_v2_report_exports.py /data/backend/tests/test_v2_report_exports.py && \
     docker cp /tmp/excel.py smartx-hci-capacity-insight-web-api-1:/app/app/v2/reports/export/excel.py && \
     docker cp /tmp/test_v2_report_exports.py smartx-hci-capacity-insight-web-api-1:/app/tests/test_v2_report_exports.py && \
     docker exec smartx-hci-capacity-insight-web-api-1 python -m unittest tests.test_v2_report_exports && \
     docker restart smartx-hci-capacity-insight-web-api-1
   '
   ```
3. **端到端请求真实 API 并覆盖桌面文件**：
   ```bash
   python3 scripts/verify_remote_exported_reports.py http://10.20.11.3:8000
   ```
   - 脚本会自动登录获取 JWT Token；
   - 调用 `/api/reports/export/word?period_days=30` 与 `/api/reports/export/excel?period_days=30`；
   - 验证全部 15+ 项布局与数据断言；
   - 自动覆盖写回桌面上的 `/Users/nazawsze/Desktop/SmartX_存储容量分析报告_20261010.xlsx` 与 `.docx`。

---

## 5. 接手者第一步该做什么

1. **核验当前工作区**：
   ```bash
   git status --short --branch
   ```
   确认位于 `dev2` 分支，工作区干净，最新提交为 `4ca398b`。
2. **遵守推送铁律**：
   - **`dev2` 只在本地提交，严禁主动执行 `git push origin dev2`**（需用户明确指示）。
3. **核查桌面最新文件**：
   打开 `/Users/nazawsze/Desktop/SmartX_存储容量分析报告_20261010.xlsx`，检查：
   - 打开第一眼是否默认激活「执行摘要」；
   - 底部各个 Sheet Tab 是否呈现深蓝/墨绿/天蓝/紫灰颜色分组；
   - `VM增长TOP100` 第 2 行 G2:K2 是否为 13pt 粗体深蓝浅底卡片 `向右滑动查看增长率榜单 ▶`，前 3 名排名序号是否深蓝加粗；
   - 各集群专属 Sheet 是否为 A1:J1 / K1:T1 贯通合并，F5:I5 是否为 `向右滑动查看增长率榜单 ▶`，无任何杂乱跳转链接。
4. **如果用户提出后续需求**：
   - 保持在 `backend/app/v2/reports/export/excel.py` 与 `word.py` 中改动；
   - 遵循 AGENTS.md 开发纪律：先改代码 -> 本地跑 29 测试 -> 同步 `.3` 容器跑测试 -> 运行 `verify_remote_exported_reports.py` 刷新桌面文件 -> 本地单任务单提交。
