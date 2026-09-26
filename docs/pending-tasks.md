# 未完成任务清单（按优先级）

快照时间：2026-09-13
维护规则：本文件是全项目未完成工作的合并视图；每完成一项同步更新本文件并在 task_plan.md 勾选；新任务立项时先加到 task_plan.md（关联设计文档），再登记到这里。详细口径以 task_plan.md 各 Phase 与 findings.md 为准，本文件只做队列索引。

**交给他 AI 实施？先读 [ai-handoff-guide.md](ai-handoff-guide.md)**（执行环境、提交策略、测试基线、陷阱清单、设计文档索引）。

## P0 — 发布流程（下一版发布前必须）

| # | 事项 | 来源 | 说明 |
| --- | --- | --- | --- |
| 1 | Release canary 发布验收闭环 | Phase 29 | ✅ 口径已闭环（2026-09-20 用户定发布节奏）：canary 环境结论 = 10.20.0.6 为 frp Tower 主机不作为 canary，生产等价验收由 .12 代行（Phase 30 部署验收 + 2026-09-19/09-20 两轮正规升级验收，v0.5.3 门禁全过）。剩余动作 = ①新候选包 `54aa8807…`（2026-09-27 重打包，dev2 0a41775，收编 49-36~49-48，包门禁全过）的 .12 正规升级验收 + v0.5.1 基线升级链路回归待执行（前者需用户授权连 .12，后者需先把测试机恢复成 v0.5.1 基线，属破坏性操作需确认）；②用户明确说「发布 v0.5.3」后执行发布动作链（推送 dev2/main、tag、GitHub Release 附包 54aa8807、状态翻转）+ 生产升级窗口（生产环境信息待用户提供）。发布节奏见 version-governance.md「发布节奏」节 |

## P1 — 数据正确性与产品缺口

| # | 事项 | 来源 | 说明 |
| --- | --- | --- | --- |
| 30 | 手动采集失败清空指标快照 + 看板数据过期标注（49-37） | 2026-09-25 用户反馈「没获取到数据就把整个看板停了，应标注最后更新时间」+ 看板归零截图 | **已实施并验证（2026-09-25，.3 部署完成）**：根因取证——`run_manual_collection` 对 `metric_snapshots` 整体替换、API 手动采集路径缺 worker 侧 `_merge_metrics_text` 合并保护，2026-09-18 17:43 全失败手动采集把快照抹成 357 字节表头 → `/metrics` 无样本 → Prometheus instant 空 → 看板归零（虚拟机读 SQLite 故仍 244）。修复：合并下沉 `run_manual_collection`（`merge_metrics_text` 进 `metrics/formatter.py`）+ 看板「最后成功采集」标注（stale 顶部提示条/徽标）。验证：.3 后端 **343 tests OK**、tsc 0、vitest **96 passed**、三镜像重建 health 全绿、真实 payload `data_freshness=stale`、真实失败采集后快照 357 字节未变。设计：docs/superpowers/specs/2026-09-25-collection-snapshot-merge-and-stale-annotation-design.md；根因：findings.md 2026-09-25 条。**余**：提交（待用户批准）、UI 目视 |
| 31 | 仪表盘「已分配容量」展示（49-36） | 2026-09-25 用户需求 | **已实施并验证（2026-09-25，.3 部署完成）**：`get-clusters.perf_allocated_data_space`（含副本+精简按厚制备，可超总容量，缺失按 0）→ 每塔一次采集（`id_in` 过滤）→ `ClusterCapacitySample.allocated_bytes` → 新指标 `smartx_cluster_storage_allocated_bytes` → dashboard `allocated_bytes/allocated_ratio`（分母总容量）→ `StorageBar` 三段（浅蓝封顶 100%）+ 「已使用 X · p% ｜ 总容量 Y ｜ 已分配 Z · q%」。验证：.3 后端 **348 tests OK (skipped=1)**、tsc 0、vitest **100 passed**、三镜像重建 health 全绿、真实 payload `allocated_bytes=0.0`（Tower 不可达属预期）、前端 bundle 含「已分配」。设计：docs/superpowers/specs/2026-09-25-allocated-capacity-bar-design.md。**余**：真实数据对账（待 Tower 恢复）、提交（待批准）、UI 目视 |
| 32 | `.3` 指标快照回填（一次性运维动作） | 49-37 附带 | **已执行并验证（2026-09-25）**：从 Prometheus 各序列最后真实样本（`last_over_time[400d]`：1 集群 used/total + 233 VM）重建 metrics 文本写回 `metric_snapshots`（357 字节表头 → 37639 字节 / 235 样本行），只动展示用快照表；回填后 worker `/metrics` 恢复输出、Prometheus instant 恢复样本、看板恢复 `cluster_count=1 / used 37.76 TB / 16.18%`（虚拟机 244 不变）。值全部来自真实采集，非伪造。**副作用（已由 49-39 修复）**：回填值以当前时间进入 Prometheus，曾被报表增长速率当作当日新样本 |
| 33 | 报表容量增长率口径 + 「-/单位」与标题黄色「数据不足」（49-39） | 2026-09-26 用户反馈（回填后日报表「日」变 0 B/天、「月」也是假的 0 B/月） | **已实施并验证（2026-09-26，.3 部署完成）**：窗口长度固定 日 1 / 月 30 / 季度 90 天并锚定最后一次成功采集，且窗口内成功采集需覆盖两端（最早一次距末尾 ≥ 窗口的 50%）+ 真实样本 ≥ 2 点；不足项显示 `-/天`、`-/月`、`-/季度`，标题旁黄色「数据不足」，逐项「样本不足」保留。验证：.3 后端 **350 tests OK (skipped=1)**、tsc 0、vitest 103 passed；真实显示 日=`-/天`（4 次采集但跨度 0.2 天）、月/季度为真实值。设计：docs/superpowers/specs/2026-09-26-reports-growth-window-requires-successful-collection-design.md。**余**：UI 目视、提交（待批准） |
| 34 | 回收站 VM 排除（本日/本月新建与增长 VM 统计）（49-40） | 2026-09-26 用户反馈（新建 VM 列表出现一堆 `in-recycle-bin-<uuid>`） | **已实施并验证（2026-09-26）**：采集侧 `_normalize_vm` 丢弃 `in-recycle-bin-` 前缀 VM；展示侧 `_latest_vm_items`/`_new_vm_reports_from_series` 过滤。验证：.3 后端全量 **350 tests OK (skipped=1)**（新增 RecycledVmPrometheus 用例）。设计：docs/superpowers/specs/2026-09-26-recycle-bin-vm-exclusion-design.md。**余**：UI 目视、提交（待批准）；看板「虚拟机」KPI 未改（仍含回收站 VM） |
| 35 | 集群容量趋势图断档断开 + 只画真实采集数据（49-41） | 2026-09-26 用户反馈（没采集到数据时实际容量应断开） | **已实施并验证（2026-09-26）**：前端 `buildDailyGrid` 连续日 + null 断开；后端图表序列截到最后一次成功采集。验证：tsc 0、vitest **103 passed**、后端全量 **350 OK**。设计：docs/superpowers/specs/2026-09-26-cluster-chart-gap-break-design.md。**余**：UI 目视、提交（待批准） |
| 36 | VM 真实性口径升级：`in_recycle_bin` / `local_created_at` / `original_name`（新建 VM 与回收站判定） | 49-40/49-41 部署后复盘发现「本月新建 VM 199 台」误判 | **部分已实施（49-42 折中口径，2026-09-26）/ Tower 字段升级待恢复后**：现状口径「序列在查询窗口内首次出现」会把采集断档（`.3` 实测 228 个 VM 序列中 203 个首见日期 = 09-12 恢复采集当天）、改名、序列重建误判为新建。本地 CloudTower API 文档已确认可用字段：`Vm.in_recycle_bin`（权威回收站标记，`VmWhereInput` 可服务端过滤）、`Vm.local_created_at`（VM 真实创建时间）、`Vm.original_name`（回收前名字）。计划：①新建 VM 按 `local_created_at` 落到今日/本月判定；②回收站过滤改用 `in_recycle_bin`（替代 49-40 的名称前缀权宜口径）；③回收站 VM 显示 `original_name` 而非 `in-recycle-bin-<uuid>`。需 10.20.0.6 可达以核对字段与 `where` 过滤行为 |
| 37 | 「新建 VM」口径升级为 Tower 真实创建时间（`local_created_at`）+ `in_recycle_bin`/`original_name` | 49-42 局限 | **保留待办（2026-09-26 用户确认「37 先保留」），待 Tower `10.20.0.6` 可达**：49-42 已用「平台全历史最早样本」折中（`.3` 本月新建 199→6），但断档期间创建的 VM 只能归到恢复采集当天；升级后用 `local_created_at` 判真实创建日、`in_recycle_bin` 做权威回收站过滤（替代名称前缀）、`original_name` 显示回收前名字。字段已由本地 CloudTower API 4.8.0 文档确认 |
| 38 | 概览与报表「本日新建 VM」同源（49-43） | 2026-09-26 用户质疑两页数字不一致 | **已实施并验证（2026-09-26，.3 部署完成）**：口径下沉共享模块 `app/v2/vms/new_vm.py`，概览 `_day_new_vms` 与报表 `_new_vm_reports_from_series` 同源（vm_id 全历史首见 + 排除回收站）。验证：.3 后端全量 **352 tests OK (skipped=1)**、线上 `dashboard=0/report=0/equal=True`。设计见 docs/superpowers/specs/2026-09-26-new-vm-first-seen-design.md §7。**余**：UI 目视、提交（待批准） |
| 39 | 同名口径审计修复（49-44）：周期边界同源 + 概览增长过滤 + 报表增长泄漏 | 2026-09-26 用户「统一，你看看还有什么问题」 | **已实施并验证（2026-09-26，.3 部署完成）**：`period_bounds` 下沉共享模块；概览增长列表补回收站过滤；报表增长列表修复 series tail 泄漏（49-40 漏洞）。验证：.3 全量 **355 tests OK**、线上月增长 66 条回收站 0 条。设计见 new-vm-first-seen §8。**余**：提交（待批准） |
| 40 | 虚拟机 KPI 是否排除回收站 VM | 49-44 审计 | **已决定（2026-09-26 用户）：不改**。用户口径：删除/回收站的虚拟机**也应该记录**（数据保留优先），只是暂时没有「显示删除虚拟机」的需求。因此：KPI `vm_count` 继续为 **244（含 29 台回收站 VM）**；`vm_latest` 只增不删（含历史 tower_id 的 346 行遗留）；新建/增长列表继续按 49-40 排除展示。将来若需要「查看/筛选已删除 VM」的功能，再单独立项 |
| 41 | 「增长最快 VM」两套实现统一（49-45） | 49-44 审计（同 30 天窗口 概览 0 条 vs 报表 66 条） | **已实施并验证（2026-09-26，.3 部署完成）**：共享模块 `app/v2/vms/growth.py` 统一窗口与计算；前端共用 `hasSampleSpan`/`TOP_GROWTH_VM_LIMIT`。口径变化：月窗口固定 30 天、当前值取 instant∪序列尾部、概览项新增 `sample_span_days`。验证：.3 全量 **356 tests OK**、tsc 0、vitest **107 passed**、线上 `day_equal=True`/`month_equal=True`（66=66）。设计：docs/superpowers/specs/2026-09-26-shared-vm-growth-design.md。**余**：UI 目视、提交（待批准） |
| 42 | 报表补「已分配容量」展示（49-46） | 49-36 只做了概览 | **已实施并部署（2026-09-26）**：`report.clusters[i].allocated`（instant，缺失按 0）+ 报表行显示 `已分配 {值} · {比例}%`（分母 total，可 >100%）。测试：后端 `test_report_clusters_expose_allocated_capacity`、前端断言 `已分配 2700 B · 270.00%`。设计：49-36 设计文档 §8。**余**：UI 目视、提交（待批准）；趋势图已分配线为可选后续 |
| 43 | 回收站 VM 生命周期同步（49-47）：记录 + 彻底删除后本地删除 | 2026-09-26 用户设计（in_recycle 对应本地 uuid / 每天采集核对 / 取不到即删） | **已实施并部署（2026-09-26）**：`vm_latest` 加 `in_recycle_bin`/`original_name`/`deleted_at`；采集记录回收站 VM；采集成功且 Tower 不再返回 → 删本地行（失败不核对、普通行不删）。验证：.3 后端 **362 tests OK**、tsc 0、vitest **107 passed**、真实库 `columns_ok=True`。设计：docs/superpowers/specs/2026-09-26-recycle-lifecycle-sync-design.md。**余**：UI 目视、提交（待批准）、Tower 恢复后端到端验证 |
| 44 | 趋势图「实际容量 / 已分配容量」颜色互换（49-48） | 2026-09-27 用户建议（图表里两色互换） | **已实施并部署（2026-09-27，含 49-48b 撞色修复）**：实际容量换主蓝 `--blue`、已分配换青 `#0f9fbf`；**六个系列全部显式给色**（ECharts 调色板按「未显式配色的系列」顺序发色，只改一个会让后续错位——首版曾把历史预测挤成与已分配同为青色，findings.md 2026-09-27）。最终：实际蓝 / 历史预测 `#8792a2` / 未来预测 `#29354d` / 告警阈值 `#f59e0b` / 有效容量 `#ef4444` / 已分配青。验证：.3 `tsc -b` 0、vitest **107 passed**、frontend 重建 web 200、产物逐系列取证六色互不相同。**余**：UI 目视、提交（待批准） |
P1 全部完成（2026-09-13）：compose tag 覆盖风险经读码核实为「升级包管线已渲染字面量 tag」，收尾项（runner 默认 env CORS 清理、check_versions 防呆、文档、双版本渲染取证）已实施并验证。

P1 其余项（增长速率算法 Phase 31、预计耗尽算法增强、SQLite 治理、阈值/时区统一、Tower UI 改版含 TowerForm 抽取）已于 2026-09-12 完成并验证，见文末"已完成"与 progress.md。

## P2 — 运维与流程

| # | 事项 | 来源 | 说明 |
| --- | --- | --- | --- |
| 8 | Phase 30 部署/升级验收两项 | Phase 30 | ✅ 已完成（2026-09-15，10.20.11.12）：部署验收（任意目录名部署，project/network 固定）+ 升级验收（v0.5.2→v0.5.3 无第二套容器/网络） |
| 9 | 生产现场只读定位 | Phase 49-8 残留 | 总览绿色现象复现时抓 `/api/dashboard/summary` 请求状态与 `capacity_risk.level`；待生产现象复现 |
| 13 | Phase 24 采集重试/缺采收尾 | Phase 24 | 已实现，待一轮真实使用验证后关闭 |
| 17 | UPG-049 残留卫生项治理 | 2026-09-19 findings.md | ✅ 已完成（2026-09-19）：Prometheus legacy 扫描守卫（beb36d5+回归测试）、.12/.3 app/ 残留清理（各约 3G）、容器挂载与 .3 线上核对一致、runner 镜像 0aca32511008 更新至 .3/.12。交付包 ef10a7c8… 维持不变（prometheus 守卫随下次打包纳入） |
| 18 | UPG-050 app/ 挂载点目录误删致挂载消失 | 2026-09-19 findings.md | ✅ 已定案（2026-09-19）：app/{upgrades,…,smartx-storage-forecast} 为 dockerd 补建的挂载点载体（容器内被真实 bind 遮蔽），运行期 rm/mv 会拆掉全机对应挂载（当日多次"衰减"均为清理操作自伤）。已部署 `scripts/bind-mount-recover.sh`（check/recover）至 .3/.12，两机 recover 后挂载齐全、health 全绿。规则：容器运行期禁删/禁改该组目录 |
| 19 | Prometheus 400d retention 与报表 720 天图表窗口冲突 | 2026-09-19 findings.md | ✅ 已完成（2026-09-19，用户决策去 720 档）：`_normalize_chart_days` 集合删 720（传 720 回退 365，向后兼容）、前端窗口选项/类型同步、文档同步；导出链路核实不受影响（只收 period_days）。.3 全量 315 tests OK、vitest 86/86、真实 API 冒烟 chart_days=720→365 |
| 22 | UPG-050 载体目录物理锁（chattr +i） | task_plan 49-23 | ✅ 已实施并验证，**用户决策不采用常驻加锁（2026-09-20），.12 已解锁恢复原状**：bind-mount-recover.sh 增 lock/unlock + recover 自动解锁/复锁（127c31c+84d5c2f），.12 六步验证协议全部通过后按用户决策解锁；脚本能力保留备查，单台机器需要时可单独 `lock`（10.20.0.6 为 frp Tower 主机，不在范围） |
| 25 | 源码 compose 镜像 tag 字面量化（49-3 收尾） | task_plan Phase 49 第 3 项 | ✅ 已实施并验证（2026-09-20，提交 556a85f）：三源码 compose 全字面量化、check_versions 字面量断言+模板禁令、bridge 打包渲染修复并验证；.3 门禁 + build_tests 26 OK + 全量 330 OK；不重打交付包，e940e07c 冻结产物不受影响（随下次打包纳入） |
| 23 | .3 Tower 可达性恢复（环境） | 2026-09-19 findings.md | **待用户侧处理**：CHINATOWER/SMARTX-TT-WW 自 2026-09-12 网络不可达，采集连续失败，测试环境数据停在 09-12；`collection-freshness-stale` critical 告警挂起（探针端到端验证完成）。恢复可达后趋势自然恢复，告警按设计保留 |
| 26 | 数据迁移页 UI/文案优化 | 2026-09-20 用户反馈「界面不明所以，我自己都忘了做什么用的」 | **第一批已实施并验证（2026-09-20，提交 ff7c553）**：术语客户化（「导出配置迁移包→仅导出 Tower 配置」「下载当前 .env→下载恢复密钥」「补全缺失数据/覆盖导入→合并数据/整库替换」+动态后果提示行）、页底新增「使用说明」卡（五条大白话，含包+密钥成对保存与忘记密钥补救路径）、导出成功引导成对保存、后端任务标题/链接标签同步、UI 层 .env 字样退场（.env 不进包/0600/需登录边界不变）；.3 验证 tsc 0 / vitest 89 / 后端 335 OK（progress.md 49-26）。**追加（2026-09-20，f893d2c+287af58）**：升级页 Runner 状态拆分 + 整页三区重构——「当前状态」（现场事实+服务表格）／「升级包」三步动线（上传选择→核对包信息与 Runner 要求→预检查后升级，包需求跟包走）／「维护」（清理旧版本降级低频危险操作），消除状态混排与 '-' 空态误判。**追加二（2026-09-20）**：迁移页两个导出按钮归组相邻、「下载恢复密钥」移入使用说明卡并新增下载前风险确认弹窗（密钥等同全部 Tower 凭据的钥匙+保管安全提示）；升级页「升级中心组件版本+Runner 当前状态」合并为一行「Runner 版本 v0.3.x（满足/不满足平台要求）」满足绿/不满足红、「目标版本」升级为「升级路径 v0.5.2 → v0.5.3」绿色箭头展示。**追加三（2026-09-20）**：下载恢复密钥需重新输入平台密码——env-file 接口 GET 改 POST、后端校验当前用户密码（错误 403），弹窗加密码输入与行内错误提示，按钮尺寸统一（progress.md 49-26f）。**追加四（2026-09-20）**：报表趋势图四档切换双画/加载反馈/形变动画/档位缓存系列优化（task_plan 第 30 条，提交 2b7868c/93ca2ee/2fdafc2/c84aae5）。**追加五（2026-09-20，progress.md 49-26l）**：集群容量趋势图四档均显示当日节点——新增「当日容量」黄色散点（实际序列末点 + 顶部黄色加粗数值标签），图例/tooltip 排除；.3 四档截图目视验证（task_plan 第 31 条）；后续 49-26n 横轴日期标签自适应（实际类目数 ≤12 全显否则约 10 个、365 天档跨度 <180 天显示月-日），四档均约 10 个日期标签。**追加六（2026-09-21，收尾批次，progress.md 49-26p）**：三区结构重组（导出迁移包主卡+配置导出次要入口+包与密钥成对保存常驻引导；导入方式可选卡片、整库替换红色危险态、去服务重启直达）+ 健康检查常驻化（环境状态卡进入页面自动只读体检：业务库/历史指标/完整性，降级为重新检查）。**追加七（2026-09-21，49-26p 用户反馈，progress.md 49-26q）**：①导出两按钮移回页头右侧（PageHeader action，修正重组后落卡内左侧）；②「使用说明」卡头与其它三区统一（标题 16px+分隔线）；③去掉「导出即自动生成/可下载恢复密钥」表述，改为导出成功后弹「还需下载恢复密钥」确认框（[下载恢复密钥]/[取消]），点「下载恢复密钥」须输平台登录密码才真正下载（密码门控对密钥下载真实生效）；服务器配对 .env 留档与 env-file 密码接口不变。设计：docs/superpowers/specs/2026-09-21-migration-page-key-flow-and-layout-revision.md。**#26 全部批次完成**。梳理稿：docs/superpowers/specs/2026-09-20-migration-page-ux-review.md |
| 24 | 数据库定期自动备份能力 | 2026-09-20 用户问答；用户「我要终态」立项 49-25；同日用户决策「自动备份暂时不做，只做记录」 | **自动备份：暂不启用（2026-09-20 用户决策）**——能力已完成设计、实现与验证后按决策撤下代码（设计/验证记录保留：docs/superpowers/specs/2026-09-20-auto-backup-and-env-pairing-design.md、progress.md 49-25 两轮证据；方案：web-api 守护线程 SQLite VACUUM INTO 快照 + 同代 .env 成对滚动保管，`SMARTX_AUTO_BACKUP_*` 可调），后续需要时按设计文档恢复即可。**导出 .env 配对：已实现并验证（保留交付）**——迁移导出（全量/配置、同步/异步）自动生成同名 .env 快照（0600）+任务中心「配对 .env」下载链接，新增「下载当前 .env」入口与 `GET /api/admin/migration/env-file`，消除 SSH 手工拷贝。.3 验证：撤下后全量 335 tests OK；导出配对 live 下载 200（progress.md 49-25/49-25a）。边界：.env 不打进导出包的安全规则不变；异地备份仍为迁移包人工转存 |
| 27 | 升级大包支持（平台+Runner 合一包，由包声明升级顺序） | 2026-09-20 用户提出「要支持升级大包，大包里包含 runner，根据升级包的关系由升级包选择先升级 runner 还是其他组件」 | **现状查证（2026-09-20）**：平台当前不支持，且为显式拒绝——混合包可上传、预检查可通过，但「开始升级」编译执行计划时 `compiler.py` 对含 runner 组件的包抛 `UpgradeCompilationError("upgrade-runner 组件必须由 web-api 直接升级。")`（HTTP 400）。根因：平台升级执行计划由 upgrade-runner 自身执行，runner 无法在任务执行中重建自身容器，故协议规定 runner 组件只能走 web-api 直执行路径（`_runner_only` override + 新 runner 心跳接续 `_resume_runner_upgrade`）。**可行方向（待用户确认后立项设计，暂不实施）**：协议扩展两阶段任务链——web-api 先执行包内 runner 阶段（复用现有 web-api 直执行流程），新 runner 心跳就绪后再把剩余平台阶段编译成执行计划交给新 runner；manifest 声明组件构成与升级顺序（runner 先行为默认）。注意：涉及 AGENTS §6「不能在同一个正在执行升级的平台包中重启 runner」边界的修订，属架构变更，需设计文档 + 完整链路重验证。**用户决策（2026-09-20「不支持就先不动吧」）：暂不实施，本条仅记录查证结论与可行方向；后续如需支持再按上述方向立项设计** |
| 28 | 报表接口耗时/payload 优化（后端治本项） | 2026-09-20 基线测量（progress.md 49-26k）；此前结论「慢了先优化后端」 | **第一阶段已完成（2026-09-20，progress.md 49-26m）**：profile 定位构成（Prometheus 471ms/15 次调用，其中三条相同 VM 6h/30d 查询占 395ms）；`_MemoPrometheus` 请求内查询去重落地（设计 docs/superpowers/specs/2026-09-20-report-latency-optimization-design.md，零行为变化），.3 同进程 A/B 实测无 memo 555ms → memo 288ms（-48%），Prometheus 调用 15→10；reports 42 + 全量 337 tests OK。**第二阶段待排期**：payload 瘦身（month_new_vms 277KB 占 63%，为全量新建 VM 列表，Word/Excel 导出依赖全列表，需服务级 limit 契约参数）；可选：剩余 ~45ms 小查询并行化 |

## P3 — 工程健康度（不阻塞发布）

| # | 事项 | 来源 | 说明 |
| --- | --- | --- | --- |
| 14 | 拆分巨型文件 | Phase 49-13 | ✅ 已完成（2026-09-13）：api.py 域路由包、ServicePage 六域组件、export.py common/word/excel 包、upgrade/service Mixin 包，四文件独立提交部署，全量回归零新增 |
| 15 | API 增加响应模型 | Phase 49-14/49-16 | 全部完成（批次 1-4 响应模型 + 49-16 契约对齐：后端补发 kpis/latest_run/top_vms/tower_runs 与 item metric/value，前端删兼容 normalizer；金样本契约增量、55 前端测试、全量回归零新增） |
| 16 | 低优增强 | Phase 13/14/16 | ✅ 已完成（2026-09-13）：Excel 图表精修（容量趋势图+打印版式+横坐标优化）、task-worker 第 6 容器评估（实测不新增，见 docs/task-worker-evaluation.md）、AI 措辞层（接口+离线回退） |
| 20 | runner prepare 升级期在 app/ 下生成空骨架目录 | 2026-09-20 用户记录指令 | **仅记录，不排期修复（2026-09-20 用户决策）**：`filesystem_prepare` mkdir 循环在升级期会于 app/ 下生成空骨架目录（畸变路径、无数据复制、不阻塞升级，见 findings.md 619）。挂载健康时 mkdir 经真实挂载穿透到真实目录，无宿主可见副作用；危害仅限挂载已衰减场景下的目录噪音。若未来主动治理，方向为 mkdir 目标过滤挂载点同源候选 |
| 21 | 测试机环境卫生低优项（2026-09-20 盘点，能力已产品化） | 2026-09-20 progress 盘点；49-24 能力扩展（de77cef） | ✅ ① .12 已走产品「空间清理」功能完成（2026-09-20 用户明确口径：清理必须走正常功能，不做宿主手工运维）：运行产物清理释放 8.45G（16 项升级任务目录）+ 悬空镜像清理释放 12.88G（60 个 dangling），磁盘 57%→约 30%，健康全绿。③ 备份权限已修正。**剩余②**：.12 的 4 个旧项目名 tag 镜像（`nazawsze/smartx-storage-forecast-*`）当前产品功能覆盖不到（v0.5.3 在跑包只清 dangling），等 49-24 随下次发版火车交付后走产品「清理未使用镜像」完成；.3 同类清理已在 49-24 验证中做掉 |

P3 其余项（v1 死代码移除、helper 收敛、静默吞错清理、CORS 收紧）已于 2026-09-12/13 完成并验证，见文末"已完成"与 progress.md。

## 已完成（2026-09-12，备查）

- SQLite 治理：WAL + busy_timeout 5s + `tasks.updated_at`/`collection_runs.started_at/finished_at` 索引（.3 实库验证）。
- 容量阈值统一：`capacity_risk.thresholds` 由后端下发，DashboardPage 三处改读后端值（旧后端回退 0.75/0.8）。
- 日界时区统一：`_day_bounds` 按 settings.timezone 计算零点（Asia/Shanghai 与 UTC 断言覆盖）。

- 主动容量告警机制（采集后阈值检查 → 任务中心 warning/critical，确认去重）。
- 首页总览静默陈旧：前端 30s 超时/失败横幅/单飞、summary 60s TTL 缓存、`_in_enabled_scope` 三处 fail-closed、`cluster_enabled`/`evaluated_at` 字段。
- 采集频率：Tower 级"采集模式（每日定时/按间隔）"UI + worker 每 Tower 独立调度（含每日时间字段首次真正生效）。
- 前端风格规范文档化（frontend-style-guide.md）与新区块 token 统一。
- Phase 31 增长速率算法：核对确认后端三窗口（日/月/季）、前端三行卡片、Word/Excel 口径、单测均已落地（历史实现未更新状态）；findings 旧口径已修正；.3 真实数据验证三窗口输出与样本标记。
- 预计耗尽算法增强：`forecast_series` 新增 smoothed_slope_per_day / exhaustion_days_30d / recent_day_delta / spike_detected；Dashboard 风险行与报表预测行优先 30d 稳健口径并提示"近 24 小时增长异常"；.3 真实数据验证（spike=True 正确识别当日突增）。
- TowerForm 组件抽取：创建/编辑表单共用 TowerForm.tsx（表单状态类型、分区、采集/重试字段、payload 归一化），SettingsPage 收敛到 190 行；DashboardPage fallback 类型补齐新字段后 tsc 通过、16 tests 通过、容器强制重建。
- P3 卫生批次（commit d12028c，设计 p3-hygiene-batch-design.md）：
  - helper 收敛：series.py 规范 cluster_key/vm_key（四处副本删除）；parsing.int_or_none（database/migration 合并，语义不同者保留并注释）；export.py 字符串键变体保留。
  - 静默吞错：任务列表刷新失败进数据状态横幅（App tasksError 状态）；即发即忘类保留。
  - CORS：默认不挂中间件（同源部署无需），SMARTX_CORS_ORIGINS 显式白名单才启用；.3 的 .env 遗留 `SMARTX_CORS_ORIGINS=*` 已清理，实测 0 个 access-control 头、同源代理正常。
- P2 批次（commit 235f905+82e31c5，设计 p2-ops-batch-design.md）：
  - 基线产物化：`scripts/capture_baseline.py` capture/verify 闭环；.3 真机验证（vm_volumes 89636 行、SHA/integrity/counts 全过；错误路径防御拦截旧残留 /data/smartx.db）。
  - 数据新鲜度告警：DataQualityService 自适应阈值（2×最小采集周期，env 可覆盖）+ Prometheus 样本滞后 >15 分钟检查，进入既有"数据质量需关注"通道。
  - worker 重试调度化：统一采集结果管道（保存 metrics→数据质量→失败重试排期），三条采集路径（全局/每 Tower/升级后）共用；修复 per-tower 与升级后路径漏存 metrics 的回归（.3 实测 run 63 成功后 metric_snapshots 同步更新）；重试从 time.sleep 循环改为一次性 DateTrigger job。
  - 防御教训：/data/smartx.db 是 v0.5.1 时代旧残留，业务库在 /data/smartx-storage-forecast/app/smartx.db；脚本已加"无业务表即失败"防御。
