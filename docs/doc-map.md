# 项目文档地图

本文件是 SmartX HCI Capacity Insight 全部文档的总索引（开发/维护用，项目对外简介见根目录 [README.md](../README.md)）。开始任何代码、升级包或远程环境操作前，先按 [AGENTS.md](../AGENTS.md) 的顺序阅读根目录工作文档，再按本地图定位专项文档。

当前版本边界：开发候选平台 `v0.5.3`（未发布；已正式发布 `v0.5.2`）、已发布 runner `v0.3.1`（开发线 `v0.3.2` 未交付）、分支 `dev2`。

## 1. 根目录工作文档（每次会话必读）

| 文档 | 说明 |
| --- | --- |
| [AGENTS.md](../AGENTS.md) | AI 协作标准：文档读取顺序、分支与提交规则、三台服务器操作边界、架构边界、升级链路、包门禁、失败报告标准。**该文件按 `.gitignore` 仅本地维护、未入库**，其硬规则的可核对副本见 [version-governance.md](version-governance.md)「Runner 能力与版本治理」与 [development-verification-process.md](development-verification-process.md) §4.4。 |
| [task_plan.md](../task_plan.md) | 工作计划：当前环境、各 Phase 目标与状态、Phase 与设计文档对照、常用验证命令。 |
| [findings.md](../findings.md) | 项目发现与接手笔记：服务职责、数据路径、网络、已知坑点、各 Phase 稳定结论。 |
| [progress.md](../progress.md) | 工作进度流水：按日期记录每轮执行、测试输出和失败证据（历史日志，不作为结论来源）。 |

## 2. 项目说明与架构

| 文档 | 说明 | 关联任务 |
| --- | --- | --- |
| [README.md](../README.md) / [README.zh-CN.md](../README.zh-CN.md) | 对外项目简介、快速启动和升级包格式。 | — |
| [project-guide-for-ai.md](project-guide-for-ai.md) | 面向 AI 的稳定背景：系统是什么、为什么这样设计、历史问题结论、推荐验证命令。 | — |
| [architecture.md](architecture.md) | 架构总览：5 容器职责、后端模块边界、数据职责、任务模型、升级/迁移包结构、安全边界。 | task_plan Phase 16 |
| [architecture-v2.md](architecture-v2.md) | v2 总体架构设计：容器职责、模块边界、前端信息架构、数据职责和关键规则。 | v2-rebuild Phase V2-0 |
| [functional-modules.md](functional-modules.md) | 功能模块归类：按功能域拆分，标注 v2 模块边界映射。 | v2-rebuild Phase V2-0 |
| [module-inventory.md](module-inventory.md) | 代码模块清单：后端/前端全部代码模块、部署与测试资产的结构索引（路径、规模、职责、所属容器）。 | — |
| [frontend-style-guide.md](frontend-style-guide.md) | 前端 UI 风格规范：设计变量、圆角/阴影、按钮/输入/分段开关规格、状态色语义、布局模式。AI 写任何 UI 前必读。 | 全部前端任务 |
| [api.md](api.md) | API Reference：对外接口说明。 | — |
| [usage.md](usage.md) | 使用说明。 | — |
| [deployment.md](deployment.md) | 部署指南：目标服务器 Compose 部署、目录、运行时配置和离线部署。 | v2-rebuild Phase V2-9 |
| [troubleshooting.md](troubleshooting.md) | 故障排查手册：健康分诊、挂载衰减（UPG-050）、数据库、采集/Tower、Prometheus 链路、升级失败取证的症状→检查→处理。 | 运维 |
| [backup-recovery.md](backup-recovery.md) | 备份与恢复手册：备份资产盘点、迁移包/.env 配对策略、手工冷备步骤、恢复步骤与验证清单。 | 运维 |

## 3. v2 受控重建任务与设计文档

v2 重建总任务文档是 [v2-rebuild-task-plan.md](v2-rebuild-task-plan.md)（Phase V2-0 ~ V2-9），其第 11 节列出细化设计文档清单：

| 文档 | 说明 | 关联任务 |
| --- | --- | --- |
| [v2-rebuild-task-plan.md](v2-rebuild-task-plan.md) | dev2 受控重建任务文档：重建决策、模块任务、数据职责、实施阶段、测试计划。 | task_plan Phase 17 |
| [v2-implementation-sequence.md](v2-implementation-sequence.md) | v2 代码重建阶段顺序、交付物和验收命令。 | v2-rebuild Phase V2-0 |
| [v2-api-contracts.md](v2-api-contracts.md) | v2 前后端 API 和数据契约。 | v2-rebuild Phase V2-0 |
| [v2-frontend-design.md](v2-frontend-design.md) | v2 前端页面、组件、交互规则和 v1 风格继承要求。 | v2-rebuild Phase V2-0 |
| [v1-data-compatibility.md](v1-data-compatibility.md) | v1 现场数据迁入 v2 的兼容规则：merge/overwrite、导入前备份、Prometheus block、旧 VM 卷 payload 抽取、导入后健康验证。 | task_plan Phase 13/20，v2-rebuild Phase V2-6 |
| [v2-upgrade-center-design.md](v2-upgrade-center-design.md) | 统一升级入口设计：manifest、状态机、runner/Prometheus 组件升级、备份和回滚边界。 | task_plan Phase 12/18/22，v2-rebuild Phase V2-7 |

## 4. 任务计划与设计（superpowers）

| 文档 | 说明 | 关联任务 |
| --- | --- | --- |
| [superpowers/plans/2026-06-10-excel-summary-growth-sheets.md](superpowers/plans/2026-06-10-excel-summary-growth-sheets.md) | Excel 摘要与增长 Sheet 实施计划。 | task_plan Phase 14/21 |
| [superpowers/plans/2026-07-10-post-upgrade-auto-collection.md](superpowers/plans/2026-07-10-post-upgrade-auto-collection.md) | 升级后自动采集实施计划。 | UPG-041 |
| [superpowers/specs/2026-07-10-post-upgrade-auto-collection-design.md](superpowers/specs/2026-07-10-post-upgrade-auto-collection-design.md) | 升级后自动采集设计。 | UPG-041 |
| [superpowers/plans/2026-07-15-upg044-verification-history.md](superpowers/plans/2026-07-15-upg044-verification-history.md) | UPG-044 verification 与历史查询实施计划。 | UPG-044 |
| [superpowers/specs/2026-07-15-upg044-verification-history-design.md](superpowers/specs/2026-07-15-upg044-verification-history-design.md) | UPG-044 verification 与历史查询无副作用设计。 | UPG-044 |
| [superpowers/plans/2026-07-15-upg045-released-u2-auto-collection-compatibility.md](superpowers/plans/2026-07-15-upg045-released-u2-auto-collection-compatibility.md) | UPG-045~048 已发布资产兼容计划：不改已发布 u2/runner 资产的前提下修复自动采集、任务终态和 .env 权限。 | UPG-045~048 |
| [superpowers/specs/2026-09-12-capacity-alert-and-overview-freshness-design.md](superpowers/specs/2026-09-12-capacity-alert-and-overview-freshness-design.md) | P0 容量告警与总览时效修复设计：主动容量告警、总览静默陈旧修复、采集频率可配置。 | task_plan Phase 49 第 8/9 项 |
| [superpowers/plans/2026-09-12-capacity-alert-and-overview-freshness.md](superpowers/plans/2026-09-12-capacity-alert-and-overview-freshness.md) | P0 容量告警与总览时效修复实施计划（5 个 Step：scope/告警/worker/前端/远端验证）。 | task_plan Phase 49 第 8/9 项 |
| [superpowers/specs/2026-09-12-tower-settings-ui-design.md](superpowers/specs/2026-09-12-tower-settings-ui-design.md) | Tower 设置页完整 UI 设计：添加/编辑分组表单、认证互斥、测试连接前置、集群分区、删除确认。 | task_plan Phase 49 第 11 项 |
| [superpowers/specs/2026-09-13-remove-v1-dead-code-design.md](superpowers/specs/2026-09-13-remove-v1-dead-code-design.md) | 移除 v1 死代码设计：删除集/保留集盘点（app.core.config 被构建脚本依赖）、迁移包兼容回归与镜像体积对比。 | task_plan Phase 49 第 12 项 |
| [superpowers/specs/2026-09-13-split-giant-files-design.md](superpowers/specs/2026-09-13-split-giant-files-design.md) | 拆分巨型文件设计：api.py 域路由包、export.py common/word/excel、upgrade/service Mixin、ServicePage 六域组件。✅ 已完成（2026-09-13，见 progress.md）。 | task_plan Phase 49 第 13 项 |
| [superpowers/specs/2026-09-13-api-response-models-design.md](superpowers/specs/2026-09-13-api-response-models-design.md) | API 响应模型分批落地设计：五批推进、模型描述现状、金样本对比与回滚。 | task_plan Phase 49 第 14 项 |
| [superpowers/specs/2026-09-13-compose-literal-tags-design.md](superpowers/specs/2026-09-13-compose-literal-tags-design.md) | 升级包 compose 字面量 tag 渲染设计：包构建时消除插值、反向断言防回退、runner 默认 env CORS 遗留清理。 | task_plan Phase 49 第 15 项 |
| [superpowers/specs/2026-09-13-contract-alignment-design.md](superpowers/specs/2026-09-13-contract-alignment-design.md) | 前后端契约对齐设计（49-14 批次 5）：后端补发 kpis/latest_run/metric/value 纯增量字段，前端删兼容 normalizer。 | task_plan Phase 49 第 16 项 |
| [superpowers/specs/2026-09-20-upg050-carrier-lock-and-prepare-skeleton-design.md](superpowers/specs/2026-09-20-upg050-carrier-lock-and-prepare-skeleton-design.md) | UPG-050 载体目录 chattr +i 物理锁方案（锁定范围/兼容性论证/脚本接口定稿/验证协议/风险回滚）。✅ 已实施并在 .12 完成六步协议验证；用户决策不采用常驻加锁，.12 已解锁恢复（2026-09-20，见 progress.md）；第二部分仅记录不修复。 | task_plan Phase 49 第 23 项 |
| [superpowers/plans/2026-09-20-upg050-carrier-lock-plan.md](superpowers/plans/2026-09-20-upg050-carrier-lock-plan.md) | UPG-050 载体目录锁实施计划：脚本改造清单、.12 六步验证协议、文档收尾、.3/生产机逐台确认与回滚。 | task_plan Phase 49 第 23 项 |
| [superpowers/plans/2026-09-27-runner-capability-alignment-plan.md](superpowers/plans/2026-09-27-runner-capability-alignment-plan.md) | **计划（A/B 已实施并验收，第四轮 `.12` 全绿）**：v0.5.3 与已发布 runner v0.3.1 能力对齐——方案 A（平台侧不再依赖旧 runner 动作，保 v0.5.2 直升）+ 方案 B（runner bump v0.3.2 交付 + 预检查动作级校验）；**v0.3.2 的 tag/镜像/资产交付待用户决策**。 | task_plan Phase 49 第 49/50 项 |
| [superpowers/plans/2026-09-27-v053-full-chain-acceptance-plan.md](superpowers/plans/2026-09-27-v053-full-chain-acceptance-plan.md) | **执行计划（严格照此测试）**：v0.5.3 完整链路 v0.5.1→u2→runner v0.3.1(已发布)→v0.5.2→runner v0.3.2→v0.5.3；含 A/B 验收断言、8 项验收、结果记录表与 B-b 下的 A5 口径修正。 | task_plan Phase 49 第 49/50 项 |
| [superpowers/specs/2026-09-20-source-compose-literal-tags-design.md](superpowers/specs/2026-09-20-source-compose-literal-tags-design.md) | 源码 compose 镜像 tag 字面量化设计（49-3 收尾）：三个源码 compose 全字面量化（prefix+tag）、check_versions 门禁适配、不重打 e940e07c。✅ 已实施并验证（2026-09-20，见 progress.md）。 | task_plan Phase 49 第 3 项 |
| [superpowers/specs/2026-09-20-migration-page-ux-review.md](superpowers/specs/2026-09-20-migration-page-ux-review.md) | 数据迁移页面梳理与 UI 优化输入：逐元素核对代码后的真实行为、迁移包/恢复密钥概念、两种导出两种导入的关系、现状问题清单与改版方向（供后续 UI 优化立项）。 | pending-tasks #26 |
| [superpowers/specs/2026-09-21-migration-page-three-zone-design.md](superpowers/specs/2026-09-21-migration-page-three-zone-design.md) | 数据迁移页三区结构重组设计（导出/导入/环境状态 + 健康检查常驻化），49-26p 已实施并验证。 | task_plan 第 33 项 |
| [superpowers/specs/2026-09-21-migration-page-key-flow-and-layout-revision.md](superpowers/specs/2026-09-21-migration-page-key-flow-and-layout-revision.md) | 数据迁移页三处修订设计：导出按钮回页头右侧、使用说明字体统一、导出后「需下载恢复密钥」确认框 + 密码门控；后端范围说明。49-26q 已实施并验证。 | task_plan 第 34 项 |
| [superpowers/specs/2026-09-25-collection-snapshot-merge-and-stale-annotation-design.md](superpowers/specs/2026-09-25-collection-snapshot-merge-and-stale-annotation-design.md) | 手动采集失败清空 `metric_snapshots` 的根因与合并修复 + 仪表盘数据过期「最后成功采集」标注设计。✅ 已实施并验证（2026-09-25，.3 343 tests / vitest 96 / 部署 health 全绿）。 | task_plan Phase 49 第 37 项（49-37） |
| [superpowers/specs/2026-09-25-allocated-capacity-bar-design.md](superpowers/specs/2026-09-25-allocated-capacity-bar-design.md) | 集群「已分配容量」（`perf_allocated_data_space`）采集链路、新指标 `smartx_cluster_storage_allocated_bytes`、三段容量条与数值区设计。✅ 已实施并验证（2026-09-25，.3 348 tests / vitest 100 / 部署 health 全绿；真实数值对账待 Tower 恢复）；§8 报表侧补已分配 49-46。 | task_plan Phase 49 第 36、46 项 |
| [superpowers/specs/2026-09-26-reports-growth-window-requires-successful-collection-design.md](superpowers/specs/2026-09-26-reports-growth-window-requires-successful-collection-design.md) | 报表容量增长速率窗口口径（窗口内需有真实成功采集，否则样本不足）+ 不足项显示「-/单位」与标题黄色「数据不足」。✅ 已实施并验证（2026-09-26，.3 349 tests / vitest 100 / 部署真实 payload 符合）。 | task_plan Phase 49 第 39 项（49-39） |
| [superpowers/specs/2026-09-26-recycle-bin-vm-exclusion-design.md](superpowers/specs/2026-09-26-recycle-bin-vm-exclusion-design.md) | 回收站 VM（`in-recycle-bin-<uuid>`）识别与排除：采集侧不入库、展示侧不计入新建/增长 VM；KPI 计数保留（用户 2026-09-26 决定：删除的 VM 也应记录）。✅ 已实施并验证（2026-09-26，.3 350 tests OK）。 | task_plan Phase 49 第 40 项（49-40） |
| [superpowers/specs/2026-09-26-cluster-chart-gap-break-design.md](superpowers/specs/2026-09-26-cluster-chart-gap-break-design.md) | 集群容量趋势图断档断开实际容量曲线（连续日 + null）+ 图表序列只取到最后一次成功采集。✅ 已实施并验证（2026-09-26，tsc 0 / vitest 103 / 后端 350 OK）。 | task_plan Phase 49 第 41 项（49-41） |
| [superpowers/specs/2026-09-26-new-vm-first-seen-design.md](superpowers/specs/2026-09-26-new-vm-first-seen-design.md) | 「新建 VM」口径修正：按 vm_id 全历史最早样本判定（断档恢复不再把老 VM 判成新建）。✅ 已实施并验证（2026-09-26，.3 352 tests OK，本月新建 199→6；§7 概览与报表同源 49-43）。 | task_plan Phase 49 第 42、43 项 |
| [superpowers/specs/2026-09-26-shared-vm-growth-design.md](superpowers/specs/2026-09-26-shared-vm-growth-design.md) | 「增长最快 VM」概览与报表共用实现（窗口/计算/展示规则统一，两页结果一致）。✅ 已实施并验证（2026-09-26，.3 356 tests / vitest 107 / 线上 day、month 均相等）。 | task_plan Phase 49 第 45 项（49-45） |
| [superpowers/specs/2026-09-26-recycle-lifecycle-sync-design.md](superpowers/specs/2026-09-26-recycle-lifecycle-sync-design.md) | 回收站 VM 生命周期同步：采集记录 `in_recycle_bin`/`original_name`/`deleted_at`，采集成功且 Tower 取不到即删除本地行。✅ 已实施并验证（2026-09-26，.3 362 tests / 真实库升级通过；端到端待 Tower）。 | task_plan Phase 49 第 47 项（49-47） |
| [superpowers/specs/2026-09-27-v053-platform-side-post-upgrade-collection-design.md](superpowers/specs/2026-09-27-v053-platform-side-post-upgrade-collection-design.md) | 49-49 设计：v0.5.3 升级后自动采集改平台侧调度（manifest `auto_collection=false` + 新键 `platform_collection` + compiler 不再下发动作；含「源端编译」关键约束）。 | task_plan Phase 49 第 49 项 |
| [superpowers/specs/2026-09-27-runner-v032-and-action-level-precheck-design.md](superpowers/specs/2026-09-27-runner-v032-and-action-level-precheck-design.md) | 49-50 设计：runner **v0.3.2** 交付（bump/打包/推 tag 三步）+ 升级预检查**动作级**校验（`RUNNER_ACTION_SUPPORT` 表 + `_check_runner_actions`）。 | task_plan Phase 49 第 50 项 |

## 5. 升级链路专项文档

固定升级链路：`v0.5.1 + runner v0.3.0 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2 -> v0.5.3`。

| 文档 | 说明 | 关联任务 |
| --- | --- | --- |
| [v0.5.0-to-v0.5.2-upgrade-plan.md](v0.5.0-to-v0.5.2-upgrade-plan.md) | 总体升级计划（source of truth）。 | — |
| [v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md](v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md) | u2 -> v0.5.2 段修复规划：修复方案、实施顺序、包版本策略、验收标准。 | 根 Phase 32~48 |
| [v0.5.1u2-to-v0.5.2-upgrade-issues.md](v0.5.1u2-to-v0.5.2-upgrade-issues.md) | u2 -> v0.5.2 段问题现象与现场证据。 | 根 Phase 32~48 |
| [v0.5.1-to-v0.5.2-upgrade-chain-worklog.md](v0.5.1-to-v0.5.2-upgrade-chain-worklog.md) | 链路执行记录：详细过程、失败证据、task ID、包 SHA、验证结果。 | UPG-031~048 |
| [v0.5.1-to-v0.5.2-upgrade-chain-task-findings.md](v0.5.1-to-v0.5.2-upgrade-chain-task-findings.md) | 链路任务计划与发现归档：原 task_plan/findings 中的 Phase 32~48 详情迁至此。 | 根 Phase 32~48 |
| [upgrade-runner-lifecycle.md](upgrade-runner-lifecycle.md) | upgrade-runner 生命周期：平台包与 runner 组件包边界、runner 自升级策略。 | task_plan Phase 22 |
| [upgrade-issues.md](upgrade-issues.md) | 升级模块问题台账（UPG-001 起）：问题清单、根因和关闭状态。 | task_plan Phase 6~9 等 |
| [upgrade-strategy-issues.md](upgrade-strategy-issues.md) | **升级策略问题细分清单（2026-09-27 复查）**：架构/契约、流程断言、已修复回归项、验收矩阵缺口共 23 条，每条含根因/证据/修复方向/状态。 | pending-tasks #47、验收计划 |
| [upgrade-audit-matrix.md](upgrade-audit-matrix.md) | **升级功能完整性审计矩阵**：M1 状态机 182 / M2 动作失败注入 78 / M3 场景端到端 84 / M4 数据红线 504 断言 / M5 历史事故 38 / M6 静态审计 8 = **894 格**，含 MVP 子集 42 格。除 M3-07 已跑外均未执行、不改代码。 | pending-tasks #47 |
| [superpowers/specs/2026-09-27-us05-us23-release-blocking-fix-design.md](superpowers/specs/2026-09-27-us05-us23-release-blocking-fix-design.md) | **设计（已实施，`.12` MVP 待授权）**：US-05 `required_health` 移除 runner_version（顺序无关）+ US-23 `start()` 单飞守卫（平台/组件共用入口）；含测试计划、重打包与 MVP 验收格、回滚。实施证据：progress.md 2026-09-27 49-52、候选包 `b9560eee…`。 | task_plan Phase 49 第 52 项 |
| [superpowers/specs/2026-09-27-runner-delivery-consistency-gate-design.md](superpowers/specs/2026-09-27-runner-delivery-consistency-gate-design.md) | **设计（已实施并验证）**：runner 交付一致性硬门禁（#47② / US-02）——`scripts/verify_runner_delivery_consistency.py` 把「仓库 `RUNNER_VERSION`+动作表 ｜ 组件包 ｜ DockerHub tag」三处同源核对做成命令；核心是比对镜像内 `/app/RUNNER_VERSION` 与 `actions.py` md5。 | task_plan Phase 49 第 54 项 |
| [upgrade-package-ledger.md](upgrade-package-ledger.md) | 升级包台账：包路径、SHA256、状态和废弃原因。 | UPG-031~048 |

## 6. 发布、验收与治理

| 文档 | 说明 | 关联任务 |
| --- | --- | --- |
| [release-acceptance.md](release-acceptance.md) | 发布验收门禁：环境矩阵、固定验收用例、反污染规则。 | task_plan Phase 29 |
| [version-governance.md](version-governance.md) | 版本治理：平台/runner 版本来源、镜像 tag、tag 与 VERSION 一致性规则。 | task_plan Phase 5、Phase 49 |
| [releases/CHANGELOG.md](releases/CHANGELOG.md) | 发布变更记录。 | — |
| [releases/v0.2.md](releases/v0.2.md) | v0.2 历史发布说明。 | — |
| [ova-delivery.md](ova-delivery.md) | OVA 交付说明：OVA 模板与升级包、迁移包的边界。 | — |
| [project-progress-2026-08-12.md](project-progress-2026-08-12.md) | 阶段性项目进度摘要（对外可读）。 | — |

## 7. 未完成任务队列

| 文档 | 说明 |
| --- | --- |
| [pending-tasks.md](pending-tasks.md) | 全项目未完成任务清单（按 P0~P3 优先级），快照式索引；逐项口径以 task_plan.md 各 Phase 为准。 |
| [ai-handoff-guide.md](ai-handoff-guide.md) | AI 交接执行手册：.3 操作、提交策略、测试基线、陷阱清单、待实施设计索引。交接实施前必读。 |
| [development-verification-process.md](development-verification-process.md) | 开发/打包/功能测试验证标准流程：环境机器、开发流程、打包流程、后端/前端测试、部署健康检查、升级链路验证。AI 实施前必读。 |
| [task-worker-evaluation.md](task-worker-evaluation.md) | task-worker 第 6 容器评估报告：实测后台任务对 web-api 响应影响，结论保持 5 容器。 |

## 8. 编号体系说明

项目存在三套并行编号，查阅时注意区分：

- **根 Phase（task_plan.md）**：Phase 1~31 为 v2 重建与产品化阶段；Phase 32~48 是升级链路专项阶段，详情归档在 [v0.5.1-to-v0.5.2-upgrade-chain-task-findings.md](v0.5.1-to-v0.5.2-upgrade-chain-task-findings.md)（fix10 并入 Phase 32，无独立 Phase 33）；Phase 49 为 v0.5.2 后治理待办。逐项对照见 [task_plan.md](../task_plan.md) 的「Phase 与任务设计文档对照」。
- **UPG-xxx（升级问题/修复编号）**：UPG-001 起记录在 [upgrade-issues.md](upgrade-issues.md)；UPG-031~048 为升级链路修复，记录在 [upgrade-chain-worklog.md](v0.5.1-to-v0.5.2-upgrade-chain-worklog.md)；UPG-049/050（2026-09-19）记录在 [upgrade-issues.md](upgrade-issues.md)，详细证据在 [findings.md](../findings.md) 与 progress.md。
- **Phase V2-x（v2 重建子阶段）**：定义在 [v2-rebuild-task-plan.md](v2-rebuild-task-plan.md)（V2-0 ~ V2-9）。

## 9. 资产

`docs/assets/` 保存 README 使用的界面截图（dashboard-overview、forecast-report、tower-settings、vm-storage-trend）。
