# 报表集群增长速率：窗口锚定最后一次成功采集 + 不足项「-/单位」与标题黄色「数据不足」

- 日期：2026-09-26
- 状态：已实施并验证（2026-09-26，.3 后端 349 tests OK / tsc 0 / vitest 100 passed / 部署后真实 payload 与前端产物均符合；提交待用户批准）
- 关联任务：task_plan.md Phase 49 第 39 条；pending-tasks #33
- 触发：用户反馈报表「容量增长速率」的「日」由 `数据不足 + 样本不足` 变成 `0 B/天`、且「月」也是 `0 B/月`（用户追问「那你月不也是 0B 吗」）；用户明确窗口口径：**日=1 天、月=30 天、季度=90 天**，不足的项显示 `-/天`、`-/月`、`-/季度`，标题旁黄色「数据不足」，逐项「样本不足」保留。

## 1. 背景与根因

1. 49-37 之后执行了 `.3` 指标快照回填：把 Prometheus 各序列最后真实样本（2026-09-12 最后成功采集值）重新写回 `metric_snapshots`，`collector-worker /metrics` 恢复输出、Prometheus 继续抓取。
2. 这些回填值以**当前时间**被 Prometheus 抓取，于是「近 1 天」「近 30 天」窗口里出现了一段同值样本。
3. `reports/service.py::_summed_window_rate` 对日窗口只要求 `len(points) >= 2` 且把分钟级跨度钳到 1 天 → 日算成 `0.0`；月窗口（趋势拟合）被这段平坦尾巴拉成 `0.0`。
4. 结果：`per_day` 由 `null` 变 `0.0`（还带 `sufficient=true`），`per_month` 长期为 `0.0`；前端于是显示 `0 B/天`、`0 B/月`（原版 UI 在 0 时也显示 0，与 49-38 的 UI「-」改动无关）。
5. 本质：**回填样本不是"新采集样本"**，不能参与按时间窗口计算的增长率。

`.3` 实测（修复前）：`{"per_day":0.0,"per_month":0.0,"per_quarter":13005856488632.03,"day_sample_sufficient":true,"month_sample_sufficient":true,...}`。

### 1.1 `.3` 真实样本分布（修复时取证）

`smartx_cluster_storage_used_bytes`（集群 `cm551tvrv029a0858up57q8qu`，step=1d，近 120 天）：

```text
2026-08-12 ~ 08-20  9 个真实样本（32.2 TB → 33.8 TB，真实增长）
2026-08-21 ~ 09-11  无样本（采集侧断档）
2026-09-12 ~ 09-18  最后一次成功采集后的平坦值（37.76 TB）
2026-09-26          回填写入（当前时间戳，37.76 TB）
```

## 2. 目标与口径

- 增长窗口长度固定为 **日 1 天 / 月 30 天 / 季度 90 天**（用户确认），并**锚定在最后一次成功采集上**：
  `窗口 = [last_success - N 天, last_success]`，N = 1 / 30 / 90。
  （用户 2026-09-26 明确：「月用最后一次成功采集往前 30 天来算」。）
- 窗口内**只用真实采集样本**：快照回填/暂停期的重复抓取值虽然带当前时间戳，但窗口右端已裁到 `last_success`，不会进入计算；窗口再无越界样本（`start <= ts <= end` 双端裁剪 + 查询边界）。
- 窗口内真实样本 < 2 个点 → 该窗口判样本不足：`per_* = null`、`*_sample_sufficient = false` → 前端 `-/单位`。
- 没有任何成功采集记录（`last_success_ts` 为空）→ 三个窗口直接空 → 全部样本不足。
- 图表/预测/VM 序列不受影响，仍按"现在"回算。

"真实成功采集"口径复用看板既有定义：`collection_runs` 中 `status IN ('success','partial_failed')` 且 `success_targets_json != '[]'` 的最新 `finished_at`（与 `dashboard/service.py::_latest_collection` 一致）。

本案结果（最后成功采集 2026-09-12 15:21、now 2026-09-26）：

| 窗口 | 窗口区间 | 真实样本 | 结果 |
| --- | --- | --- | --- |
| 日 | `[09-11, 09-12]` | 09-12 采集前后的抓取样本 | ≈`3.57 TiB/天`（含 09-12 采集把 08-20 旧值刷新为新值的跳变，见 §7） |
| 月 | `[08-13, 09-12]` | 08-13~08-20 + 09-12 | ≈`4.44 TiB/月`（真实） |
| 季度 | `[06-14, 09-12]` | 08-12~08-20 + 09-12 | ≈`13.55 TiB/季度`（真实） |

Tower 恢复采集后，窗口右端跟随最新成功采集，三项持续为真实数值。

### 2.1 边界（不做）

- 不改 VM 增长、图表、预测、数据质量、导出结构。
- 不删除/回滚 Prometheus 或 `metric_snapshots` 中的回填样本（看板容量数据依赖它们）。
- 不改窗口长度、倍率（30/90）与趋势算法本身。
- 不改逐项「样本不足」的既有逻辑与文案（用户明确要求保留）。

## 3. 实施方案

### 3.1 后端 `backend/app/v2/reports/service.py`

1. 新增 `ReportService._last_success_collection_ts() -> int | None`：查询 `collection_runs` 最新成功（口径同上），用 `freshness.parse_db_time` 按 UTC 解析；无记录/解析失败返回 `None`。
2. `_cluster_series` 新增 `end_ts` 参数：
   - `end_ts is None`（图表/预测）：`start = now - days`、`end = now`；
   - 给定 `end_ts`（增长速度）：`end = min(end_ts, now)`、`start = end - days`（**锚定**）；
   - `end < start` 直接返回 `[]`；给定 `end_ts` 时再按 `start <= ts <= end` 裁剪序列，裁空则丢弃（防实现/测试替身返回越界点）。
3. `_latest_report`：`last_success_ts is None` 时三个增长序列直接置空；否则三个窗口都以 `end_ts=last_success_ts` 取数。
4. 增长率计算函数保持原样（`_summed_window_rate` 仍按"点数 ≥ 2 + 现有算法"判定样本是否充足）。

### 3.2 前端（按用户口径，按项粒度）`frontend/src/pages/ReportsPage.tsx`

1. `GrowthRateItem`：`value == null` 时内容为 `-{unit}`（即 `-/天`、`-/月`、`-/季度`）并加 `growth-rate-missing` 类（`--muted` + 600）；有值时照常 `formatBytes(value) + unit`，不受其他项影响。
2. 「容量增长速率」卡标题旁：三个窗口**任一** `*_sample_sufficient === false` 时渲染黄色 `数据不足`（`Card` 的 `notice` + `.growth-rate-insufficient-notice`，`color: var(--orange)`，与 49-37 的 `.stale-title-notice` 同风格，无新增色值）。
3. 逐项 `<small>样本不足</small>` 逻辑与样式保持不变。

`frontend/src/styles/global.css`：新增 `.growth-rate-item strong.growth-rate-missing` 与 `.card-title h2 .growth-rate-insufficient-notice`。

## 4. 测试计划

后端（.3 执行）：

1. `test_v2_reports.py`：`_seed_inventory` 增加可选 `last_success_at`；断言增长速率数值的两条既有用例改为写入与 `now_ts` 对齐的成功采集。
2. 新增 `test_cluster_growth_rate_ignores_backfilled_flat_tail_after_last_success`：真实样本止于 14 天前 + 其后平坦回填值 → 日样本不足、月/季度用真实样本得出**非 0** 值；配套 `StaleBackfillPrometheus`。
3. 既有「单点样本 → 三窗口样本不足」用例保持不变（无成功采集 → 窗口直接空）。
4. 全量回归。

前端（.3 执行）：

1. `ReportsPage.test.tsx`：季度不足时渲染 `-/季度`（含 `growth-rate-missing`）、标题旁 `数据不足`（`growth-rate-insufficient-notice`）、逐项「样本不足」仍为 2 处；`tsc -b` 0 错误、vitest 全量通过。

## 5. 回滚

- 撤销本条提交即回到"不裁剪、直接看样本点数"的旧判定；无 schema/数据变更、无迁移。

## 6. 验收标准

- 窗口锚定 `[last_success - N 天, last_success]`；窗口内真实样本 < 2 时：后端 `per_* = null`、`*_sample_sufficient = false`，前端该项 `-/单位`；样本充足的窗口照常显示数值。
- 回填/断档造成的平坦尾巴不得再产生 `0 B/天`、`0 B/月` 之类的假值。
- 三个窗口中任一不足时，「容量增长速率」标题旁出现黄色「数据不足」；全部充足时不出现。
- 逐项「样本不足」保持原样。
- 后端全量测试通过、`tsc` 0 错误、vitest 通过。

## 7. 已知限制

- `.3` 最后一次成功采集是 2026-09-12，且 08-21~09-11 采集断档、期间快照一直提供 08-20 的旧值（33.84 TB），09-12 采集才刷新为 37.76 TB。因此**日窗口**（`[09-11, 09-12]`）内含这次"旧值→新值"的刷新跳变，得出 ≈`3.57 TiB/天`；它来自真实抓取样本，但反映的是三周累计的增长，不是单日增长。月/季度为正常趋势拟合值。
- 采集恢复日常节奏后，日窗口会取到相邻两天的真实样本，日增长率回归正常。
- `metric_snapshots` 回填值仍在，看板容量/集群数继续依赖它；本条只把它排除在**增长窗口计算**之外。
