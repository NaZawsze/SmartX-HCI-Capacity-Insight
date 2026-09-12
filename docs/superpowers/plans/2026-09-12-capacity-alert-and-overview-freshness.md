# P0 容量告警与总览时效修复实施计划

设计依据：[docs/superpowers/specs/2026-09-12-capacity-alert-and-overview-freshness-design.md](../specs/2026-09-12-capacity-alert-and-overview-freshness-design.md)

## Step 1 后端：scope fail-closed 与公共函数

- [ ] 新增 `backend/app/v2/scope.py::in_enabled_scope`（空集 False）。
- [ ] dashboard/vms/reports 三个 service 替换并删除私有副本。
- [ ] `DashboardService.summary` 增加 `scope.cluster_enabled`、`capacity_risk.evaluated_at`。
- [ ] `DashboardService` 模块级 TTL 缓存（60s + 采集 run id 失效 + threading.Lock）。
- [ ] 本地定向测试：`test_v2_dashboard`、`test_v2_reports`、`test_v2_inventory_metrics`、`test_v2_vms`（如存在）。

## Step 2 后端：容量告警服务

- [ ] `TaskService` 增加 `upsert_alert`（保留 acknowledged_at/seen_at 的更新路径）。
- [ ] 新增 `backend/app/v2/capacity_alerts/service.py`（阈值 env、评估、去重落库）。
- [ ] 新增 `backend/tests/test_v2_capacity_alerts.py`（边界、去重、异常、fail-closed）。
- [ ] 本地定向测试通过。

## Step 3 后端：worker 采集频率与告警调度

- [ ] `SMARTX_COLLECTION_INTERVAL_MINUTES`（默认 60，<=0 回退每日 cron）。
- [ ] `capacity-alert-check` interval job（300s）。
- [ ] 本地语法/定向测试；`docs/deployment.md` 补 env 说明。

## Step 4 前端：超时、状态横幅、去重轮询

- [ ] `request()` 增加 AbortController 30s 超时（可覆盖）。
- [ ] `App.tsx` summaryFreshness 状态 + 单飞；`AppLayout` 数据状态横幅。
- [ ] `DashboardPage` 移除重复 summary effect；cluster 未启用提示条。
- [ ] `types.ts` 字段补充；前端目标测试与 build。

## Step 5 提交与远端验证（10.20.11.3）

- [ ] `git diff --check`、本地全量后端快速回归。
- [ ] 本地提交 dev2（单提交，便于 revert）。
- [ ] 远端拉取 dev2，构建镜像并 recreate web-api/collector-worker/frontend。
- [ ] 远端后端全量 `test_v2_*` 回归 + 前端目标测试。
- [ ] 健康检查三端点；总览/集群页切换验证。
- [ ] 低阈值 env 验证容量告警出现与去重，验证后恢复 env。
- [ ] progress.md 记录证据；task_plan.md Phase 49 第 8/9 项勾选。
