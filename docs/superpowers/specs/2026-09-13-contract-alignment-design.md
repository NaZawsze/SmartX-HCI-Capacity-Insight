# 前后端契约对齐设计（49-14 批次 5 修正案，任务 49-16）

更新时间：2026-09-13
状态：已定稿，待实施
关联：task_plan.md Phase 49 第 16 项；api-response-models-design.md 批次 5

## 1. 现状与决策

后端 wire 格式（summary 无 kpis/latest_run/top_vms/tower_runs；item 无 metric/value 嵌套）与前端消费形状（MetricItem.metric 扁平字典、kpis 卡片、latest_run 采集状态）不同，`api.ts` 的 normalizer 是两者的兼容层。

**决策：后端补发前端消费的字段（纯增量，不删不改既有字段），前端删除兼容 normalizer。** 理由：新增字段对旧前端无影响（忽略未知键），goldens 变化为"契约增量"（记录即可）；前端删除 normalizer 后 `api.ts` 直接返回类型化响应。

## 2. 后端变更（纯增量）

1. **summary 顶层新增**（`DashboardService._build_summary`）：
   - `kpis`: `{tower_count, cluster_count, vm_count, used_bytes, total_bytes, used_ratio}`（源自 totals+storage）；
   - `latest_run`: `{id: 0, started_at: "", finished_at: <collection.last_success_at>, status: <collection.status>, message: <collection.message>}`（collection 存在时）；
   - `top_vms`: = `day_fastest_growing_vms`；
   - `tower_runs`: `[]`（现无 per-tower 运行态数据，前端已有 latest_run 回退）。
2. **item 新增 `metric` 与 `value`**（dashboard 与 reports 的 growth/new/latest item 构建器、summary clusters）：
   - `metric`: `{tower_id, cluster_id, vm_id?, vm?, vm_name?, cluster?, cluster_name?}`（字符串化，等价于 normalizer 现在构建的形状）；
   - `value`: 字节数（= current_bytes/used_bytes）。

## 3. 前端变更

- `api.ts`：删除 `normalizeDashboardSummary`/`normalizeCapacityRisk`/`normalizeMetricItem`/`numberish` 等仅服务于兼容层的函数；`summary()`/相关方法直接返回类型化响应（`as DashboardSummary`）。
- `types.ts` 不变（前端类型即对齐后的契约）。
- 前端测试断言若依赖 normalizer 补的键，更新为后端真实形状。

## 4. 验证

- 后端：全量回归 + .3 金样本对比（改前/改后：既有键全等 + 新增 kpis/latest_run/top_vms/metric/value）。
- 前端：全套目标测试 + tsc + 部署。
- 兼容：新增字段为契约增量，旧前端忽略未知键不受影响。

## 5. 回滚

单提交 revert（后端新增字段 + 前端 normalizer 恢复同 revert 即可）。
