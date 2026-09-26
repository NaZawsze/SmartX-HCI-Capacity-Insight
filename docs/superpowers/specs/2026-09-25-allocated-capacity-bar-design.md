# 49-36 集群「已分配容量」展示（ZBS 容量条浅蓝段 + 数值区）

- 日期：2026-09-25
- 状态：已实施并验证（2026-09-25，.3 后端全量 348 tests OK / tsc 0 / vitest 100 passed / 三镜像重建 health 全绿；提交待用户批准；真实数值对账待 Tower 恢复）
- 关联任务：task_plan.md 49-36；口径来源：2026-09-25 用户逐项确认（字段、语义、画法、分母、缺失兜底、采集链路）
- 前置：49-37（快照合并）已实施，看板数据靠一次性回填恢复（pending-tasks #32）

## 1. 背景与需求

用户希望 ZBS 概览卡不只显示「已使用 / 总容量」，还要显示**已分配容量**（Tower 侧集群的 `perf_allocated_data_space`），并直观看到"分配超过物理总量"的情况（精简置备 + 多副本会使已分配远大于总容量）。

### 1.1 字段口径（三处文档一致，已核对）

- 字段名：`perf_allocated_data_space`，位于 `POST /v2/api/get-clusters` 响应 `Cluster`，int64、optional。
  - 本地 skill 文档 `.codex/skills/cloudtower-api/references/schemas/Cluster/Cluster.md:69`；
  - GitHub cloudtower-python-sdk master；PyPI cloudtower-sdk 2.22.1 `models/cluster.py:89`。
- `get-cluster-storage-info` **不含**该字段；该接口里的 `allocable_storage_capacity` 是「可分配」，不是已分配，不能用。
- 语义：已分配 = 含所有副本、精简盘按厚制备计算的预分配量，**可超总容量**（例如 270%）。
- 缺失 / null → 按 **0** 处理（不报错、不显示"数据不足"）。

### 1.2 展示口径（用户确认）

- 容量条改为三段堆叠：
  - 深蓝（现有渐变）= 已使用；
  - 浅蓝 = `min(已分配, 总容量) - 已使用`，**浅蓝封顶在 100%**，即深蓝+浅蓝总宽不超过整条；
  - 灰色（轨道底色）= 剩余。
- 数值区同一行：「已使用 X · 70% ｜ 总容量 Y ｜ 已分配 Z · 270%」。
- **两个比例分母都是总容量**（已使用% = 已使用/总容量；已分配% = 已分配/总容量），因此已分配% 可 > 100%。

## 2. 边界（不做）

- 不改风险提示、预测、报表口径；已分配不参与容量风险判定。
- 不改集群容量明细行 `ClusterCapacityRow`（本次只改 ZBS 概览卡容量条与数值区）。
- 不新增硬编码色值：浅蓝复用 `:root` 变量（`--cyan` / `--blue` 系），符合 frontend-style-guide。
- 不做 `get-clusters` 的跨集群共享缓存等性能改造（本环境每 Tower 1 集群）。

## 3. 实施方案

### 3.1 采集链路（后端）

1. `cloudtower/client.py`
   - 新增 `get_cluster_allocations(cluster_ids: list[str]) -> dict[str, int]`：`paged_post("/v2/api/get-clusters", {"where": {"id_in": [...]}})`，取 `perf_allocated_data_space`（`_number(...) or 0`），返回 `{cluster_id: allocated_bytes}`；空列表直接返回 `{}`。
2. `cloudtower/service.py`
   - 新增 `cluster_allocations(tower) -> dict[str, int]`：用 tower 凭据建 client，传 `[c.cluster_id for c in tower.clusters]`，finally close。
3. `collection/service.py::run_manual_collection`
   - 每个 tower **一次** `allocations = self._cluster_allocations(tower)`（best-effort：异常 → 空 dict，不阻断采集，真正的失败由随后 `collect_cluster` 暴露）；
   - `ClusterCapacitySample(..., allocated_bytes=allocations.get(cluster.cluster_id, 0))`；
   - `CloudTowerCollector` Protocol 增加 `cluster_allocations(tower) -> dict[str, int]`，测试 fake 同步实现（返回 `{}` 或给定值）。
4. `metrics/formatter.py`
   - `ClusterCapacitySample` 加 `allocated_bytes: int = 0`；
   - 渲染新增指标 `smartx_cluster_storage_allocated_bytes`（含 HELP/TYPE，标签同 used/total）；`merge_metrics_text` 按 sample key 天然兼容。

### 3.2 看板与 API（后端）

- `dashboard/service.py`
  - `CLUSTER_ALLOCATED_METRIC = "smartx_cluster_storage_allocated_bytes"`；
  - `_cluster_capacity` 用 `_cluster_metric_map` 取 `allocated_bytes`（缺失记 0），并对 `set(used) | set(total) | set(allocated)` 求并集；
  - `_storage` / `kpis` 增加 `allocated_bytes` 与 `allocated_ratio`（分母 total，total=0 → 0.0）。
- `api/models.py`：`DashboardStorageModel` 加 `allocated_bytes: float = 0.0`、`allocated_ratio: float = 0.0`；`DashboardClusterModel` 加 `allocated_bytes: float = 0.0`。

### 3.3 前端

- `types.ts`：`DashboardSummary.kpis` / `storage` 加 `allocated_bytes`、`allocated_ratio`；`MetricItem` 加 `allocated_bytes?`。
- `components/StorageBar.tsx`：props 加 `allocated`；三段渲染（`.storage-fill`、新增 `.storage-fill-allocated`）；数值区三列，每列「标签在上（灰 12px）/ 数值在下（ink 15px 加粗）」，内容分别为「已使用 X · p%」「总容量 Y」「已分配 Z · q%」，p/q 分母均为 total（2026-09-26 用户反馈一行三段灰字难看，改为该层次化布局）。
- `styles/global.css`：`.storage-track` 内浅蓝段（`--blue-soft`，新增 `:root` 设计变量并补入 frontend-style-guide §2，无其他硬编码色值）；`.storage-meta` 三列 + 列间 `var(--line)` 分隔线（`.storage-meta-item` / `.storage-meta-label` / `.storage-meta-value`），移动端单列去线。
- `DashboardPage.tsx`：`<StorageBar used={...} total={...} allocated={storage?.allocated_bytes ?? kpis?.allocated_bytes ?? 0} />`。

## 4. 测试计划

后端（.3 执行）：

1. `test_v2_cloudtower_client.py`：`get_cluster_allocations` 解析 `perf_allocated_data_space`、缺字段记 0、空列表不请求。
2. `test_v2_collection.py`：采集写入 `smartx_cluster_storage_allocated_bytes`；`cluster_allocations` 抛异常时不中断采集且 allocated 记 0。
3. `test_v2_dashboard_vm.py`：`storage`/`kpis` 的 `allocated_bytes`、`allocated_ratio`（含 allocated > total 时 ratio > 1）。
4. 全量回归（基线 343 OK）。

前端（.3 执行）：

1. 新增 `StorageBar.test.tsx`：三段宽度（used/allocated 封顶/total）、数值区含两个比例且分母为 total、allocated=0 时浅蓝段宽 0。
2. `tsc -b --force` 0 错误；vitest 全量通过（基线 96 passed）。
3. `.3` 部署后目视：Tower 不可达期间 allocated 显示 0（属预期），容量条与数值区布局正确。

## 5. 回滚

- 全部为新增字段/指标/展示段：撤销提交即回到 used/total 两段展示；`merge_metrics_text`/Prometheus 对多出的指标序列向下兼容（旧前端忽略、旧 API `extra="allow"`）。
- 无 schema 变更、无迁移、无历史数据改写；已分配序列在 Prometheus 中自然过期。

## 6. 验收标准

- `.3` 全量后端测试通过、`tsc` 0 错误、vitest 通过。
- 采集成功后 `smartx_cluster_storage_allocated_bytes` 出现在快照与 Prometheus（Tower 可达时）；Tower 不可达时 allocated=0 且不影响其余指标。
- 看板 ZBS 卡容量条为三段、数值区含「已分配 Z · q%」，q 以总容量为分母。

## 7. 已知限制

- Tower `10.20.0.6` 当前不可达（.3 与本地均 ping 不通），无法做真实 `perf_allocated_data_space` 对账；真实数值验收待网络恢复。
- 口径提到"每塔一次 get-clusters"，本实现按 tower 预取一次（`id_in` 过滤），但在 `CloudTowerService` 内每 cluster 仍独立建 client（既有结构），未做连接复用改造。

## 8. 报表侧补「已分配容量」（49-46，2026-09-26）

用户指令：「报表补『已分配容量』，先做这个吧」。

- 数据：`ReportService::_cluster_allocated()` 取 `smartx_cluster_storage_allocated_bytes` 的 instant（与概览 49-36 同指标、同 scope 过滤；**缺失按 0**，不做 range 回退）。
- payload：`report.clusters[i].allocated`（新增字段，`ForecastPayload` 类型已补 `allocated?: number | null`）。
- 展示：报表「集群预测报表」每行新增一行 `已分配 {值} · {比例}%`，比例分母 = `total`（与概览「两个比例分母都是总容量」口径一致，可 >100%）。
- 不做（可选后续）：趋势图里加「已分配」水平线（现有图已有 5 条线 + 预测带，新增线需先定颜色口径）。
- 测试：后端 `test_report_clusters_expose_allocated_capacity`（instant 返回 2700/total 1000 → 断言 `allocated==2700`）；前端 `ReportsPage.test` 断言行渲染 `已分配 2700 B · 270.00%`（270% 演示超总容量的显示）。

## 9. 趋势图「已分配容量」线（49-46b，2026-09-26）

- 用户要求：图表里**加**已分配容量线 → **命名为「已分配容量」** → **默认不显示**（图例可手动打开）。
- 实现（`ClusterCapacityChart.tsx`）：
  - `ChartModel.allocated` = 单集群取 `cluster.allocated`，多集群求和（与 total/warning 同聚合口径）
  - series：2px **虚线**，颜色经 `cssVar("--blue", "#1677ff")` 从 `:root` 设计变量取（frontend-style-guide 不引入新硬编码色值）——选深蓝而非概览用的浅蓝 `--blue-soft`，是因为浅蓝做细线在白底对比度仅约 1.4:1（概览是色块所以可用）
  - `legend.data` 含「已分配容量」且 `selected: { 已分配容量: false }` **默认关闭**
  - y 轴上限仅在该系列打开时计入（否则「已分配 > 总容量」会把实际容量曲线压扁）；通过 `onEvents.legendselectchanged` 同步可见性状态
- 验证：`tsc -b` 0、vitest 107 passed、前端产物含「已分配容量」；默认关闭与打开后的 y 轴行为待用户 UI 目视。
