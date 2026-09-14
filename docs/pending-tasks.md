# 未完成任务清单（按优先级）

快照时间：2026-09-13
维护规则：本文件是全项目未完成工作的合并视图；每完成一项同步更新本文件并在 task_plan.md 勾选；新任务立项时先加到 task_plan.md（关联设计文档），再登记到这里。详细口径以 task_plan.md 各 Phase 与 findings.md 为准，本文件只做队列索引。

**交给他 AI 实施？先读 [ai-handoff-guide.md](ai-handoff-guide.md)**（执行环境、提交策略、测试基线、陷阱清单、设计文档索引）。

## P0 — 发布流程（下一版发布前必须）

| # | 事项 | 来源 | 说明 |
| --- | --- | --- | --- |
| 1 | Release canary 发布验收闭环 | Phase 29 | 验收清单 10 项全部未执行：canary 全新部署、前后端 smoke、数据契约验收、升级包验收。需用户决定发布节奏与 canary 环境 |

## P1 — 数据正确性与产品缺口

| # | 事项 | 来源 | 说明 |
| --- | --- | --- | --- |
P1 全部完成（2026-09-13）：compose tag 覆盖风险经读码核实为「升级包管线已渲染字面量 tag」，收尾项（runner 默认 env CORS 清理、check_versions 防呆、文档、双版本渲染取证）已实施并验证。

P1 其余项（增长速率算法 Phase 31、预计耗尽算法增强、SQLite 治理、阈值/时区统一、Tower UI 改版含 TowerForm 抽取）已于 2026-09-12 完成并验证，见文末"已完成"与 progress.md。

## P2 — 运维与流程

| # | 事项 | 来源 | 说明 |
| --- | --- | --- | --- |
| 8 | Phase 30 部署/升级验收两项 | Phase 30 | release-acceptance.md 过期值已修正（2026-09-13）；canary 部署/升级验收待用户提供 canary 环境（10.20.0.6 只读，需批准具体命令）与发布节奏 |
| 9 | 生产现场只读定位 | Phase 49-8 残留 | 总览绿色现象复现时抓 `/api/dashboard/summary` 请求状态与 `capacity_risk.level`；待生产现象复现 |
| 13 | Phase 24 采集重试/缺采收尾 | Phase 24 | 已实现，待一轮真实使用验证后关闭 |

## P3 — 工程健康度（不阻塞发布）

| # | 事项 | 来源 | 说明 |
| --- | --- | --- | --- |
| 14 | 拆分巨型文件 | Phase 49-13 | ✅ 已完成（2026-09-13）：api.py 域路由包、ServicePage 六域组件、export.py common/word/excel 包、upgrade/service Mixin 包，四文件独立提交部署，全量回归零新增 |
| 15 | API 增加响应模型 | Phase 49-14/49-16 | 全部完成（批次 1-4 响应模型 + 49-16 契约对齐：后端补发 kpis/latest_run/top_vms/tower_runs 与 item metric/value，前端删兼容 normalizer；金样本契约增量、55 前端测试、全量回归零新增） |
| 16 | 低优增强 | Phase 13/14/16 | ✅ 已完成（2026-09-13）：Excel 图表精修（容量趋势图+打印版式+横坐标优化）、task-worker 第 6 容器评估（实测不新增，见 docs/task-worker-evaluation.md）、AI 措辞层（接口+离线回退） |

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
