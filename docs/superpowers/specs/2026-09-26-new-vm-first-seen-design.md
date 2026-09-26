# 新建 VM 口径修正：按 vm_id 全历史最早样本判定

- 日期：2026-09-26
- 状态：已实施并验证（2026-09-26，.3 后端 352 tests OK，概览与报表同源；提交待用户批准）
- 关联任务：task_plan.md Phase 49 第 42 条 + 第 43 条（概览同源）；pending-tasks #36（Tower 字段升级）
- 触发：用户追问「本月新增应该按日期来吧，9.1 到现在新增的 VM，这个查不出来吗」——报表「本月新建 VM」显示 199 台；随后又发现「概览与报表的本日新建 VM 数字不一致」

## 1. 背景与根因

1. 旧口径：`_new_vm_reports_from_series` 用「该 VM 的序列在**当前报表查询窗口**内首次出现」判"新建"；窗口为 `days=max(window_days,30)`（默认 30 天），周期取 今日 / 本月。
2. `.3` 实测：近 30 天窗口内 228 个 VM 序列，**203 个"首次出现"日期 = 2026-09-12**（08-21~09-11 采集断档后恢复采集的第一天），25 个 = 09-25（回收站 VM，已被 49-40 过滤）→ 「本月新建 VM」显示 **199 台**（假）。
3. 机制：序列"窗口内首次出现"受三件事污染——① 查询窗口截断（窗口外历史看不到）；② **采集断档**（恢复后首个样本成为"首见"，本次主因）；③ 改名/进回收站（label 变化生成新序列）。
4. 另有独立的"新建"误判来源：回收站 VM 改名（49-40 已按名称前缀排除）。

## 2. 口径（本次，平台首次纳管时间）

- 「新建 VM」= **该 vm_id 在全历史内最早样本的日期**落在 今日 / 本月窗口内。
  - 按 `vm_id` 聚合（不是按 label set）：VM 改名/换标签产生的序列变化不会造成假"新建"。
  - 全历史窗口取 `VM_FIRST_SEEN_WINDOW_DAYS = 400` 天（与 Prometheus 保留期一致），而不是报表的 30 天窗口。
- `.3` 结果：本日新增 **0** 台；本月（9.1~今）新增 **6** 台（虚拟化平台授权机、业支-蜜罐01~05，首见 09-12），回收站 VM 已排除。

### 2.1 边界与已知局限

- 这是**平台首次纳管时间**，不是 Tower 记录的 VM 真实创建时间：若 VM 在采集断档期间创建，只能归到"恢复采集当天"（上述 6 台即 09-12，真实创建日可能在 8 月下旬）。
- 真实创建时间需用 Tower `get-vms` 的 `local_created_at`（本地 API 文档 4.8.0 已确认字段），并可用 `Vm.in_recycle_bin` 做权威回收站过滤、`Vm.original_name` 显示回收前名字——**待 Tower `10.20.0.6` 可达后升级（pending-tasks #36）**。
- 不清理既有 SQLite/Prometheus 数据；不改看板 KPI。

## 3. 实施方案

`backend/app/v2/reports/service.py`：

1. 新增常量 `VM_FIRST_SEEN_WINDOW_DAYS = 400`。
2. 新增 `ReportService._vm_first_seen()`：一次 400 天 / step=1d 的 `smartx_vm_storage_used_bytes` range 查询，按 `vm_key`（tower_id/cluster_id/vm_id）聚合最早样本 `(ts, value)`；受 tower/cluster 过滤与启用范围约束。
3. `_new_vm_reports_from_series` 增参 `first_seen_by_vm`：命中则用全历史首见 `(first_ts, first_value)` 判定新建与计算 `previous_value`/`growth_amount`/`first_seen_at`/`age_days`；未命中（该 VM 无历史）则跳过。
4. `_latest_report` 计算一次并传给 `day_new_vms` / `month_new_vms`。

## 4. 测试计划

- 新增 `GapRecoveryVmPrometheus` + `test_new_vm_uses_full_history_first_seen_not_window_first_point`：老 VM 在近 30 天窗口内"首见=今天"（模拟断档恢复），全历史窗口里有 60 天前的旧样本 → 不得计入本日/本月新建；同时真正的新 VM 正常计入。
- 既有 `RecycledVmPrometheus`（回收站排除）与基础用例回归。
- 全量回归。

## 5. 回滚

撤销本条提交即回到"窗口内首见"口径（本月新建重新出现 199 台级的假值）。无 schema/数据变更。

## 6. 验收标准

- 采集断档恢复不再导致老 VM 被判成新建。
- `.3` 「本月新建 VM」从 199 台修正为 6 台（本日 0 台），明细为首见日期在 9 月的 VM。
- 后端全量测试通过。

## 7. 概览与报表同源（49-43）

用户反馈：「为什么概览里有本日新建 VM，但是报表里没有，这两个表不应该是一个东西吗」。

- 根因：**两边是两套独立实现**——报表用 `reports/service.py::_new_vm_reports_from_series`（49-42 已升级口径），概览用 `dashboard/service.py::_day_new_vms` 的旧口径（30 天窗口内首见、无回收站过滤）→ 同一时刻两个页面数字不同。
- 修复：把口径下沉到共享模块 `backend/app/v2/vms/new_vm.py`：
  - `collect_vm_first_seen()`：按 `vm_id` 聚合的全历史（400 天）最早样本；
  - `is_recycled_vm_name()` / `vm_display_name()`：回收站 VM 识别与名称解析；
  - `RECYCLE_BIN_VM_PREFIX` 仍定义在 `cloudtower/client.py`（Tower 命名约定的归属），由共享模块引用。
  - `ReportService` 与 `DashboardService` 都改为调用该模块，删掉各自的私有实现。
- 测试：新增 `GapAndRecycleVmPrometheus` + `test_dashboard_and_report_day_new_vms_share_first_seen_and_recycle_rules`（断档假新建 + 回收站假新建，两侧均只保留真正的新 VM，且 `dashboard_ids == report_ids`）→ .3 全量 **352 tests OK (skipped=1)**。
- 验收：线上 `dashboard_day_new = 0`、`report_day_new = 0`、`equal = True`（本月新建 6 台不变）。

## 8. 同源化扩展与审计修复（49-44）

1. **周期边界统一**：`period_bounds(now_ts, kind, tz_name)` 下沉到 `app/v2/vms/new_vm.py`；报表（原 `_period_bounds`，进程本地时区）与概览（原 `_day_bounds`，`settings.timezone`）都改为 `period_bounds(..., self.settings.timezone)`，两个私有 helper 删除。行为在生产环境等价（都为 Asia/Shanghai），实现彻底同源。
2. **概览「增长最快 VM」补回收站过滤**：`dashboard/service.py::_period_fastest_growing_vms` 此前不过滤（49-40 只修了新建与报表侧），现补 `is_recycled_vm_name`。
3. **报表增长列表泄漏修复（49-40 的漏洞）**：`_latest_items_from_series_tail` 把 series tail 兜底项合并进 `latest_vms` 时没过滤，回收站 VM 重新进入所有增长列表——实测「本月增长最快」第 3 名即 `in-recycle-bin-e3d8d755…`。修复：tail 合并处 + `_growth_reports_from_series`（解析最新名后）两处过滤。
4. 测试：新增 `test_v2_vms_new_vm.py`（周期边界时区/回退 + 回收站辅助函数）、`test_growth_vm_lists_exclude_recycle_bin_vms_from_series_tail`（tail 兜底路径）、扩展 49-43 一致性测试覆盖增长列表；`test_v2_p1_infra.test_day_bounds_timezone` 改指向共享实现。
5. 验证：.3 后端全量 **355 tests OK (skipped=1)**；线上 `month_fastest_growing_vms` 66 条、回收站 0 条（修复前 68 条含 2 条）、`day_new`/`report_day_new` 均 0 且相等。

