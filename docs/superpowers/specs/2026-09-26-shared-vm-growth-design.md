# 「增长最快 VM」统一：概览与报表共用同一实现

- 日期：2026-09-26
- 状态：已实施并验证（2026-09-26，.3 后端 356 tests OK / tsc 0 / vitest 107 passed / 线上 day 与 month 两页结果完全一致；提交待用户批准）
- 关联任务：task_plan.md Phase 49 第 45 条；pending-tasks #41
- 触发：49-44 审计发现「同 30 天窗口，概览增长最快 VM 返回 0 条、报表返回 66 条」；用户 2026-09-26 指示「2 要实现结果一样」

## 1. 背景与差异根因

两页各有独立实现，四处不同：

| 维度 | 概览 `DashboardService::_period_fastest_growing_vms` | 报表 `ReportService::_growth_reports_from_series` |
| --- | --- | --- |
| 查询窗口 | 日 `days=1, step=1h`；月 `days=30, step=1d` | 日 `days=2, step=1h`；月 `days=30, step=6h` |
| 当前值来源 | 仅窗口序列的 `points[-1]` | instant 查询（`_latest_vm_items`）∪ 序列 tail 兜底（`_latest_items_from_series_tail`） |
| 基线 | 同窗口 `points[0]` | 同窗口 `points[0]`，另算 `sample_span_days` |
| 回收站过滤 | 49-44 已补 | 49-44 在 tail 合并与增长计算两处补 |
| 附加字段 | 无 `sample_span_days` | 有 `sample_span_days`（前端用于样本跨度过滤） |
| 排序 | growth 降序，次键 `vm_name` | growth 降序，次键 `vm_name` |

实测（.3，同一 30 天窗口）：概览 **0 条**（1d 步长下窗口内首尾样本都是回填后的平坦值）、报表 **66 条**（6h 步长捕捉到 09-12 当日多次采集造成的真实变化）。

另外两页**前端**也不一致：报表页对日/月列表分别按 `hasSampleSpan(item, 1/30)` 过滤并 `slice(0, 50)`；概览页不过滤、不截断。

## 2. 目标与口径

1. **同一窗口、同一算法、同一数据源**：两页的「日/月增长最快 VM」由同一个后端函数产出，结果（含顺序）一致。
2. 窗口**沿用报表现有定义**（报表行为不变，概览向报表对齐）：
   - 日窗口：`days=2, step=1h`
   - 月窗口：`days=30, step=6h`
3. 算法（沿用报表）：基线 = 窗口序列最早样本；当前值 = instant ∪ 序列 tail 的最新值；`growth = current - baseline > 0`；`sample_span_days = (latest_ts - baseline_ts)/86400`；排序 growth 降序、次键 vm_name；回收站 VM 全程排除。
4. **展示规则也统一**：日列表按 `sample_span_days >= 1` 过滤、月列表 `>= 30` 过滤、均 `slice(0, 50)`，两页共用同一前端 helper。

### 2.1 边界（不做）

- 不改两页 payload 的字段与形状（概览 items 增补 `sample_span_days` 一个字段，向后兼容）。
- 不改 VM 趋势页、容量风险、预测/报表导出。
- 不做虚拟机 KPI 与已分配容量（pending #40/#42）。

## 3. 实施方案

### 3.1 后端共享模块 `backend/app/v2/vms/growth.py`

- `GrowthWindow`：`DAY = (days=2, step="1h")`、`MONTH = (days=30, step="6h")`。
- `latest_vm_items(prometheus, *, tower_id, cluster_id, enabled_scope)`：instant 查询 + 启用范围 + 回收站过滤（原 `reports::_latest_vm_items`）。
- `series_tail_items(series_list)`：序列尾部项 + 回收站过滤（原 `reports::_latest_items_from_series_tail`）。
- `merge_latest_items(primary, fallback)`：合并去重（回收站过滤保留在上面两步）。
- `compute_growth_vms(*, now_ts, tower_id, cluster_id, enabled_scope, window, latest_items, latest_label_by_vm) -> list[dict]`：返回中立记录（`vm_id/vm_name/tower_id/cluster_id/metric/value/previous_value/growth_amount/growth_ratio/sample_span_days/window_start_at/window_end_at/slope_per_day`），回收站过滤。

### 3.2 两侧接入

- 报表：`_latest_vm_items`/`_latest_items_from_series_tail`/`_merge_latest_items`/`_growth_reports_from_series` 全部改为调用共享实现，`_growth_reports_from_series` 仅保留映射（补 `labels`、`forecast`、`period_days`、`window_start_at/window_end_at` 等报表字段）。
- 概览：`_period_fastest_growing_vms` 改为按 `days` 选窗口（≤2 → 日窗口，否则月窗口），取 latest items（instant ∪ tail）+ DB 最新名，调用共享实现并映射到既有形状（新增 `sample_span_days`）。

### 3.3 前端展示规则共用

- 新增 `frontend/src/services/growth.ts`：`hasSampleSpan(item, minDays)`、`TOP_GROWTH_VM_LIMIT = 50`。
- 报表页改用该 helper（删除本地实现），概览页对增长列表加同样的 `hasSampleSpan(...,1)` 过滤与 `.slice(0, 50)`。
- 两页排序函数语义本就一致（growth 降序 / 比例降序），保持各自实现。

## 4. 测试计划

后端（.3 执行）：

1. 一致性测试（核心）：同一 fake 数据下
   - `summary["day_fastest_growing_vms"]` 的 `vm_id` 列表（含顺序、含 `growth_amount`）**等于** `report["day_fastest_growing_vms"]`；
   - `_period_fastest_growing_vms(days=30)` **等于** `report["month_fastest_growing_vms"]`；
   - 回收站 VM 在两边都不存在。
2. 既有报表/概览增长用例回归（payload 形状不变）。

前端（.3 执行）：

1. `services/growth.test.ts`：`hasSampleSpan` 边界（null 放行、小于阈值过滤、等于阈值放行）。
2. `DashboardPage.test.tsx`：增长项 `sample_span_days < 1` 时不渲染（与报表同规则）。
3. `tsc -b` 0 错误、vitest 全量通过。

## 5. 回滚

撤销本条提交即回到两套实现；无 schema/数据变更，payload 新增字段被 `extra=allow` 兼容。

## 6. 验收标准

- 同一份数据下，概览与报表的日/月增长最快 VM 列表（vm_id、顺序、增长值）完全一致。
- 报表页原有显示行为不变（窗口沿用、样本跨度过滤、slice 50）。
- 两页前端对样本跨度的过滤规则一致。
- 后端全量测试通过、`tsc` 0 错误、vitest 通过。

## 7. 实施结果（2026-09-26）

- 后端：新增 `app/v2/vms/growth.py`（`GrowthWindow`/`DAY_GROWTH`/`MONTH_GROWTH`/`latest_vm_items`/`series_tail_items`/`merge_latest_items`/`points_by_vm`/`labels_with_latest_name`/`compute_growth_vms`）；`ReportService::_growth_reports_from_series` 与 `DashboardService::_period_fastest_growing_vms` 都改为调用 `compute_growth_vms`；报表侧只保留 `min/max_sample_days`（月列表按所选周期截断）与 `forecast`/`period_days` 等报表字段映射。
- 口径变化（有意为之，已随代码注释）：
  1. 月窗口固定 30 天/6h（不再随 `period_days` 放大到 90 天）——"月"应恒为 30 天，同时保证与概览一致；
  2. 当前值统一取 **instant ∪ 序列尾部**（原概览只取序列末端）——报表口径为准；
  3. 概览增长列表新增 `sample_span_days` 字段（`MetricItem` 类型已补）。
- 前端：新增 `services/growth.ts`（`hasSampleSpan`、`TOP_GROWTH_VM_LIMIT=50`）；报表页删本地实现、概览页补同样过滤与截断。
- 测试：后端新增 `test_dashboard_and_report_growth_vms_share_same_implementation`（日/月列表 vm_id+增长值完全相等、两侧无回收站 VM），并按新口径更新概览风险面板 `top_growth_vms` 预期（vm-2 的 instant 与基线相同 → 增长 0 不入列）→ .3 全量 **356 tests OK (skipped=1)**；前端 `growth.test.ts` 4 例 → `tsc -b` exit 0、vitest **107 passed（11 files）**。
- 线上（已部署）：`day_equal=True`、`month_equal=True`（概览=报表=**66 条**，修复前 0 vs 66），Top3 逐条一致；`health=200`、`web=200`。

