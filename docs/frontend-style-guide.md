# 前端 UI 风格规范（AI 写 UI 必读）

更新时间：2026-09-12
适用范围：SmartX HCI Capacity Insight 前端（`frontend/src/`）所有新增或修改的界面。
样式实现：所有规范落地在 `frontend/src/styles/global.css`；本文档是它的使用说明和约束。

## 1. 硬性规则（给 AI 的约束）

1. **颜色必须使用 `:root` 设计变量**（见 §2），禁止在组件里硬编码新的灰色/蓝色十六进制值。确需新增语义色（如警告底色）时，先加到 `:root` 再引用，并在本文档补一行说明。
2. **圆角只用 6px（输入框/按钮/小盒子/分段开关）和 8px（卡片）**，不要引入 10px/12px/全圆角。
3. **卡片、分区、开关都不加新阴影**；阴影只属于 `.card/.metric-card`（`0 6px 16px rgba(40,72,112,0.08)`）。
4. 表单字段统一**标签在上、输入在下、单列堆叠**；需要并排时用 `.form-pair`，并保证切换内容时其他字段不动（条件字段给固定最小高度）。
5. 功能分区用 `.tower-form-section` 模式：编号标题（① ② ③，`--blue-600` 小号粗体）+ 单列字段。功能块必须放进语义正确的分区（如失败重试属于采集计划，不属于连接凭据）。
6. 图标统一用 `lucide-react`，尺寸 14~18px。
7. 改完 UI 必须跑前端目标测试 + 构建（Dockerfile 内含 tsc/vite build），并在 10.20.11.3 部署后由用户目视验收。

## 2. 设计变量（`:root`）

| 变量 | 值 | 用途 |
| --- | --- | --- |
| `--blue` | `#1677ff` | 主操作色：主按钮、选中态、链接、激活分段 |
| `--blue-600` | `#0f66dd` | 主按钮 hover、分区/强调标题 |
| `--cyan` | `#16c7d3` | 品牌渐变辅助色 |
| `--green` | `#21c875` | 成功/健康 |
| `--orange` | `#ff9f1c` | 关注/警告 |
| `--red` | `#ff5a5f` | 失败/危险操作（删除按钮等） |
| `--ink` | `#102a56` | 标题文字（卡片标题、strong） |
| `--text` | `#26364f` | 正文 |
| `--muted` | `#7a8aa0` | 次要文字、说明、未选中项 |
| `--line` | `#dbe4f0` | 常规边框（卡片、分区、输入框） |
| `--line-soft` | `#edf2f7` | 弱分隔线（行分隔、内嵌块） |
| `--panel` | `#ffffff` | 卡片/面板底色 |
| `--background` | `#eef4fb` | 页面底色 |
| `--sidebar` | `#eaf1fa` | 侧栏底色 |

浅蓝填充 `#f8fbff` 和淡选中底 `#f0f6ff` 是本规范的扩展色，用于分区内的子块底色与悬停态，可直接使用。

`--blue-soft`（`#cfe3ff`）：ZBS 容量条「已分配」浅蓝段，表示已分配但未写入的数据量。

## 3. 组件规范

### 3.1 卡片与分区

- 卡片（`.card`）：白底、`1px solid #dbe5f1`、8px 圆角、柔和投影；标题 `--ink` 15px。
- 表单分区（`.tower-form-section`）：白底、`1px solid var(--line)`、6px 圆角、**无阴影**；标题 12px/700/`--blue-600`（如 `① 连接信息`）。
- 分区内子块（如采集模式盒子 `.schedule-fields`）：`--line` 边框、6px 圆角、`#f8fbff` 底。

### 3.2 按钮

| 类型 | 规格 |
| --- | --- |
| `.primary-button` | 高 38px、`--blue` 底白字、6px 圆角、hover `--blue-600`；主操作每屏一个 |
| `.secondary-button` | 高 32px、白底 `1px solid #cfd9e8`、文字 `#52647c`；取消/次要操作 |
| 危险操作（删除） | `--red`；必须配确认对话框 |

### 3.3 输入与表单

- 文本/数字输入：高 36px、`1px solid #cfd9e8`、6px 圆角；focus 为 `--blue` 边 + `0 0 0 2px rgba(22,119,255,0.12)` 光圈。
- checkbox：15~16px 原生样式，**不得继承文本输入的边框和高度**（表单作用域内已有覆盖，新增表单时注意带上 `.tower-form input[type="checkbox"]` 等价规则）。
- 标签：13px/700/`#52647c`，位于输入上方，间距 6px。
- 提示文案 `.form-hint`：12px/`--muted`；操作反馈 `.inline-message`：13px/`--muted`。
- 切换型选择（互斥模式）用分段开关 `.schedule-mode-switch`：胶囊分段，选中项 `--blue` 底白字，未选中 `--muted`。

### 3.4 状态色语义

| 语义 | 颜色 | 示例 |
| --- | --- | --- |
| 成功/正常 | `--green` | 采集成功徽标、"全部集群已连接" |
| 关注/警告 | `--orange`（文字用 `#8a5300` + `#fff7e6` 底） | 需关注告警、刷新失败横幅 |
| 失败/危险 | `--red` | 高风险、删除 |
| 中性/未知 | `--muted` | 未采集、数据不足 |

## 4. 布局模式

- 页面骨架：56px 顶栏 + 224px 侧栏 + 内容区；内容用 `.settings-grid` 这类两列 grid。
- 表单页：分区式单列（见 §1.5）；列表+详情双列时左窄右宽。
- 长列表加 `auto-scrollbar`；空状态用 `.empty-state`（`--muted` 居中）。

## 5. 参考实现

- 分区式表单：`SettingsPage.tsx`（Tower 新增/编辑）
- 分段开关：`SettingsPage.tsx` 的 `ScheduleModeFields`
- 状态徽标：`StatusPill.tsx`
- 卡片与指标卡：`Card.tsx`、`MetricCard.tsx`
