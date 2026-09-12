# P0 容量告警与总览时效修复实施计划

设计依据：[docs/superpowers/specs/2026-09-12-capacity-alert-and-overview-freshness-design.md](../specs/2026-09-12-capacity-alert-and-overview-freshness-design.md)

## Step 1 后端：scope fail-closed 与公共函数

- [x] 新增 `backend/app/v2/scope.py::in_enabled_scope`（空集 False）。
- [x] dashboard/vms/reports 三个 service 替换并删除私有副本。
- [x] `DashboardService.summary` 增加 `scope.cluster_enabled`、`capacity_risk.evaluated_at`。
- [x] `DashboardService` 模块级 TTL 缓存（60s + 采集 run id 失效 + threading.Lock）。
- [x] 本地定向测试：`test_v2_dashboard`、`test_v2_reports`、`test_v2_inventory_metrics`、`test_v2_vms`（如存在）。

## Step 2 后端：容量告警服务

- [x] `TaskService` 增加 `upsert_alert`（保留 acknowledged_at/seen_at 的更新路径）。
- [x] 新增 `backend/app/v2/capacity_alerts/service.py`（阈值 env、评估、去重落库）。
- [x] 新增 `backend/tests/test_v2_capacity_alerts.py`（边界、去重、异常、fail-closed）。
- [x] 本地定向测试通过。

## Step 3 后端：worker 采集频率与告警调度

- [x] `SMARTX_COLLECTION_INTERVAL_MINUTES`（默认 60，<=0 回退每日 cron）。
- [x] `capacity-alert-check` interval job（300s）。
- [x] 本地语法/定向测试；`docs/deployment.md` 补 env 说明。

## Step 4 前端：超时、状态横幅、去重轮询

- [x] `request()` 增加 AbortController 30s 超时（可覆盖）。
- [x] `App.tsx` summaryFreshness 状态 + 单飞；`AppLayout` 数据状态横幅。
- [x] `DashboardPage` 移除重复 summary effect；cluster 未启用提示条。
- [x] `types.ts` 字段补充；前端目标测试与 build。

## Step 5 提交与远端验证（10.20.11.3）

- [x] `git diff --check`、本地全量后端快速回归。
- [x] 本地提交 dev2（单提交，便于 revert）。
- [x] 远端拉取 dev2，构建镜像并 recreate web-api/collector-worker/frontend。
- [x] 远端后端全量 `test_v2_*` 回归 + 前端目标测试。
- [x] 健康检查三端点；总览/集群页切换验证。
- [x] 低阈值 env 验证容量告警出现与去重，验证后恢复 env。
- [x] progress.md 记录证据；task_plan.md Phase 49 第 8/9 项勾选。

## 执行结果（2026-09-12）

- 全部 Step 完成。设计偏差两处：总览提速采用 TTL 缓存而非接口拆分（设计允许）；前端陈旧横幅实现为"仅刷新失败时显示 + 数据时间戳"，未做独立的 5 分钟陈旧变体。
- 后端 289 tests：除 10 个环境性错误（9 个 package_builders 需写 VERSION 撞只读挂载、1 个 test_deployment_config 缺 pytest）外全部通过，与本次改动无关。
- 前端 4 文件 71 tests 通过（含新增 2 个横幅断言）；三镜像构建成功；健康检查三端点通过。
- 容量告警功能验证：低阈值（5%）触发真实告警 `capacity-alert-warning-3-6076c104`（集群 16.18%），severity=warning；确认后重复评估不重置 acknowledged_at；验证数据已删除。
- 采集间隔验证：一次性 worker（1 分钟间隔）60s 后准时触发 scheduled 采集，失败后自动触发 retry；因临时容器缺少 Tower 凭据 key 采集失败属预期。验证产生的 2 条失败 run 已删除，任务中心无残留。
