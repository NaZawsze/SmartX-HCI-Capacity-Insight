# P0 容量告警与总览时效修复设计

更新时间：2026-09-12
状态：已定稿，待实施
关联：task_plan.md Phase 49 第 8/9 项；findings.md「v0.5.2 风险链路审计补充」「风险链路补充审计」

## 1. 背景与目标

生产环境现象：单集群空间不足时集群页黄色告警正确，但数据中心/全部总览长期停留绿色；平台不存在任何主动容量告警；采集默认每天一次导致数据滞后。

目标：

1. 集群容量跨阈值时主动生成任务中心告警，不再依赖用户打开首页。
2. 总览页数据刷新失败/陈旧时用户可感知，且不再出现请求堆积和静默吞错。
3. 采集频率可配置并默认提高到小时级。
4. 修复 `_in_enabled_scope` 空集放行导致的停用集群不对称（三处复制粘贴统一修）。

非目标（后续 Phase）：

- 接入 Tower 原生告警事件（保留为可选增强，本设计只留口子）。
- summary 接口拆分、容量阈值 payload 下发、巨型文件拆分（Phase 49-9/10）。

## 2. 方案一：主动容量告警

### 2.1 模块

新增 `backend/app/v2/capacity_alerts/service.py`：

~~~python
class CapacityAlertService:
    def __init__(self, database, settings, *, prometheus=None, tasks=None, now_ts=None): ...
    def evaluate(self) -> dict  # 纯评估，不写任务
    def evaluate_and_alert(self) -> dict  # 评估 + 告警落库
~~~

依赖模式与 `DataQualityService` 一致（PrometheusService、TaskService 可注入，便于单测）。

### 2.2 评估口径

- 范围：`clusters` 表 `enabled=1` 的全部集群（停用集群不告警，避免遗留序列误报）。
- 数据：Prometheus instant `smartx_cluster_storage_used_bytes` / `smartx_cluster_storage_total_bytes`，按 tower_id/cluster_id 标签匹配启用范围；无 total 或 total<=0 的集群跳过。
- 阈值（env 可配）：

| 变量 | 默认 | 含义 |
| --- | --- | --- |
| `SMARTX_CAPACITY_ALERT_WARNING_RATIO` | 0.75 | 黄色阈值（使用率） |
| `SMARTX_CAPACITY_ALERT_CRITICAL_RATIO` | 0.80 | 红色阈值（使用率） |
| `SMARTX_CAPACITY_ALERT_MIN_FREE_BYTES` | 0（禁用） | 剩余绝对空间低于该值时至少判 warning |

- 分级：先按比率判 warning/critical；若配置了 `MIN_FREE_BYTES` 且剩余空间低于它，等级至少 warning（已有更高等级则保持）。
- Prometheus 查询异常：本周期跳过告警（数据质量告警已覆盖 Prometheus 故障场景），不崩溃。

### 2.3 告警落库与去重

- 任务 id 确定化：`capacity-alert-{critical|warning}-{tower_id}-{sha1(cluster_id)[:8]}`。
- `type=collection`，`status=failed`（沿用数据质量告警的任务形态），`progress=100`。
- 标题：`集群容量高风险：<集群名>` / `集群容量需关注：<集群名>`。
- message：使用率、已用/总容量、剩余空间、阈值、样本时间、评估时间。
- 去重与确认规则（与数据质量告警不同，需专门实现）：
  - 同一 (集群, 等级) 持续告警：仅更新 message/updated_at，**不重置 acknowledged_at/seen_at**——用户确认后同一持续条件不再反复弹。
  - 条件升级（warning → critical）：id 不同，新建 critical 告警。
  - 条件恢复：不自动关闭既有任务，由用户确认/清理（与现有告警语义一致）；恢复后再次越限视为新条件，因旧任务仍存在会被 REPLACE 更新——接受该取舍并在任务 message 中带评估时间以区分。
  - 实现上给 `TaskService` 增加一个内部方法 `upsert_alert(...)`：存在同 id 任务时 `UPDATE message, updated_at`（不动 acknowledged_at/seen_at/severity），不存在时 INSERT（acknowledged_at/seen_at 为 NULL）。

### 2.4 触发时机

- worker 新增 interval job `capacity-alert-check`，每 300 秒一次（与采集解耦，手动采集后也能及时评估）。
- 计划性采集完成路径不重复调用（interval job 已覆盖），避免双写竞争；任务写入幂等由确定化 id 保证。

## 3. 方案二：总览时效修复

### 3.1 后端

1. **公共 fail-closed scope 判断**：新增 `backend/app/v2/scope.py::in_enabled_scope(key, enabled_scope)`——`enabled_scope` 为空集时返回 `False`。替换 dashboard/vms/reports 三处私有副本后删除副本。
   - 行为变化：目标集群停用/移除后，单集群页不再用遗留 Prometheus 序列渲染数据与告警（clusters 为空、容量风险 normal）。
   - 风险控制：跑全量 `test_v2_*` 回归，确认无用例依赖旧行为。
2. **summary 附加字段**：
   - `scope.cluster_enabled`：cluster scope 时查询该集群 `enabled` 值（`true/false`，查无此集群为 `false`；非 cluster scope 为 `null`）。
   - `capacity_risk.evaluated_at`：UTC ISO 评估时间。
3. **summary TTL 缓存**（不改 API 形状，解决 15s 轮询全量重算）：
   - `dashboard/service.py` 模块级缓存 `{'key': (tower_id, cluster_id), 'expires': ts, 'run_id': 最近采集 run id, 'payload': ...}` + `threading.Lock`（FastAPI sync 端点跑线程池）。
   - 命中条件：未过期（TTL 60s）且 `collection_runs` 最新 run id 未变化（一次轻量 SELECT）。
   - 手动采集/升级后采集会改变 run id，缓存自然失效，下轮轮询即拿到新数据。

### 3.2 前端

1. `request()` 统一超时：`AbortController` 默认 30s（可按调用覆盖），超时文案"请求超时"。`upload()`（XHR 带进度）不动。
2. `App.tsx`：
   - 新增 `summaryFreshness` 状态 `{ lastSuccessAt, lastError }`；成功记录时间并清错误，失败记录错误并**保留旧数据**。
   - `refreshSummary` 单飞：请求在途时跳过本次触发，配合超时杜绝堆积。
   - 移除 DashboardPage 内两处重复 summary effect（App 的 scope 依赖 effect + 15s 轮询已覆盖）；保留"立即采集"动作后的手动刷新。
3. `AppLayout` 顶栏下渲染数据状态横幅：
   - 刷新失败：`数据刷新失败（{原因}），当前显示 {时间} 的数据，正在自动重试`。
   - 距上次成功超过 5 分钟：`数据更新于 {时间}，比预期慢，正在重试`。
4. `DashboardPage`：cluster scope 且 `summary.scope.cluster_enabled === false` 时显示提示条"该集群未启用采集，暂不展示容量数据"。
5. `types.ts`：`scope.cluster_enabled?: boolean | null`、`capacity_risk.evaluated_at?: string`。

## 4. 方案三：采集频率可配置

- 新 env `SMARTX_COLLECTION_INTERVAL_MINUTES`，**默认 60**（分钟）。
- `>0`：APScheduler interval 触发器（`max_instances=1`、`coalesce=True`、`misfire_grace_time=300`）；
- `<=0`：回退现有每日 cron（`SMARTX_COLLECTION_HOUR`/`SMARTX_COLLECTION_MINUTE`），兼容旧部署。
- 手动采集与失败重试逻辑不变；容量告警 job 独立 300s interval。
- `docs/deployment.md` 补充三个新 env 说明（含容量告警阈值）。

## 5. 测试计划

后端新增 `backend/tests/test_v2_capacity_alerts.py`：

- 阈值边界：74.9% 不告警 / 75% warning / 79.9% warning / 80% critical；`MIN_FREE_BYTES` 生效；total 缺失跳过。
- 去重：持续告警不重置 acknowledged_at；warning→critical 新建；停用集群不告警。
- Prometheus 异常不崩溃、本周期跳过。
- fail-closed：空 enabled_scope 不产出任何 cluster/vm 条目（dashboard/vms/reports 共用行为）。
- summary 缓存：TTL 内命中；采集 run id 变化后失效；`cluster_enabled`/`evaluated_at` 字段正确。

前端：

- 现有目标测试回归（AppLayout/DashboardPage/ServicePage/ReportsPage）+ 新增数据状态横幅断言。

远端 `10.20.11.3` 验收：

1. 后端全量 `test_v2_*` 回归通过。
2. 前端目标测试 + build 通过。
3. 重建 web-api/collector-worker/frontend，健康检查三端点 200。
4. 功能验证：临时以低阈值 env 启动 collector-worker，任务中心出现容量告警，确认后再确认去重（重复评估不重置已确认状态），最后恢复正常 env。
5. 总览与集群页来回切换，确认无报错横幅误显示。

## 6. 交付与回滚

- 单次提交到 `dev2`（本地提交，按用户指令后续推送与否由用户决定）；不改动 VERSION/不发布升级包。
- 回滚方式：`git revert` 单提交。
- 完成后在 task_plan.md Phase 49 第 8/9 项勾选对应子项并记录验证证据到 progress.md。
