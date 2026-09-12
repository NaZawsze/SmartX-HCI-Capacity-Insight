# 未完成任务清单（按优先级）

快照时间：2026-09-12
维护规则：本文件是全项目未完成工作的合并视图；每完成一项同步更新本文件并在 task_plan.md 勾选；新任务立项时先加到 task_plan.md（关联设计文档），再登记到这里。详细口径以 task_plan.md 各 Phase 与 findings.md 为准，本文件只做队列索引。

## P0 — 发布流程（下一版发布前必须）

| # | 事项 | 来源 | 说明 |
| --- | --- | --- | --- |
| 1 | Release canary 发布验收闭环 | Phase 29 | 验收清单 10 项全部未执行：canary 全新部署、前后端 smoke、数据契约验收、升级包验收。需用户决定发布节奏与 canary 环境 |

## P1 — 数据正确性与产品缺口

| # | 事项 | 来源 | 说明 |
| --- | --- | --- | --- |
| 2 | SQLite 索引 + WAL + busy_timeout | Phase 49-10 | 零索引 + web-api/worker 双进程并发写，`vm_volumes` 已 9 万行级；数据量增长后最先爆 |
| 3 | 容量阈值统一 + 时区统一 | Phase 49-9 | 75%/80% 前后端硬编码 7 处改由 capacity_risk payload 下发；`_day_bounds` 本地时区日界改 settings.timezone |
| 4 | 报表页容量增长速率算法优化 | Phase 31 | 已规划待实施，口径已定（日/月/季三窗口，负增长不压 0） |
| 5 | compose 镜像 tag 可被 .env 覆盖 | Phase 49-3 | 源码 compose 模板 `${SMARTX_IMAGE_TAG:-...}` 风险（升级包内已固定） |
| 6 | 预计存储耗尽算法增强 | Phase 15 待办 | 区分长期趋势与单日突增，避免迁移后耗尽天数被误读 |
| 7 | Tower 设置页完整 UI 改版 | Phase 49-11 | 设计已完成（分区式布局已落地为本次基线），剩：创建前测试连接、删除确认框、列表健康徽标、TowerForm 组件抽取、B1/B2 后端接口 |

## P2 — 运维与流程

| # | 事项 | 来源 | 说明 |
| --- | --- | --- | --- |
| 8 | Phase 30 部署/升级验收两项 | Phase 30 | canary 上验证固定 project/network 不产生第二套容器/网络 |
| 9 | 标准业务基线产物化 | Phase 49-7 | SQLite+配套 .env+Prometheus 固化为可校验 SHA 的基线，杜绝数据源选错 |
| 10 | 数据新鲜度链路告警联动 | Phase 49-10 | 采集→:9108 导出→Prometheus 抓取→summary 查询，任一环断裂纳入数据质量告警 |
| 11 | worker 采集重试改调度排期 | Phase 49-10 | 重试循环内 `time.sleep` 最长 45 分钟阻塞线程并推迟数据质量检查 |
| 12 | 生产现场只读定位 | Phase 49-8 残留 | 总览绿色现象复现时抓 `/api/dashboard/summary` 请求状态与 `capacity_risk.level` |
| 13 | Phase 24 采集重试/缺采收尾 | Phase 24 | 已实现，待一轮真实使用验证后关闭 |

## P3 — 工程健康度（不阻塞发布）

| # | 事项 | 来源 | 说明 |
| --- | --- | --- | --- |
| 14 | 移除 v1 死代码（约 4800 行） | Phase 49-10 | app/main.py、app/api/、app/services/ 等；删除前回归 v1 迁移包兼容 |
| 15 | 拆分巨型文件 | Phase 49-10 | export.py 3720 行、upgrade/service.py 1791 行、api.py 1112 行、ServicePage.tsx 2305 行 |
| 16 | 复制粘贴 helper 收敛 | Phase 49-10 | `_vm_key` x5、`_cluster_key` x6、`_int_or_none` 等收敛公共模块 |
| 17 | API 增加响应模型 | Phase 49-10 | Pydantic response_model，替代前端 normalize 兜底 |
| 18 | tasks 轮询等静默吞错清理 | Phase 49-9 残留 | summary 路径已完成；其余 `catch(() => undefined)` 路径改可感知提示 |
| 19 | v2 CORS 收紧回白名单 | Phase 49-10 | 去掉 `allow_origins=["*"]` + credentials 组合 |
| 20 | 低优增强 | Phase 13/14/16 | Excel 图表精修、AI 措辞层、task-worker 第 6 容器评估 |

## 已完成（2026-09-12，备查）

- 主动容量告警机制（采集后阈值检查 → 任务中心 warning/critical，确认去重）。
- 首页总览静默陈旧：前端 30s 超时/失败横幅/单飞、summary 60s TTL 缓存、`_in_enabled_scope` 三处 fail-closed、`cluster_enabled`/`evaluated_at` 字段。
- 采集频率：Tower 级"采集模式（每日定时/按间隔）"UI + worker 每 Tower 独立调度（含每日时间字段首次真正生效）。
- 前端风格规范文档化（frontend-style-guide.md）与新区块 token 统一。
