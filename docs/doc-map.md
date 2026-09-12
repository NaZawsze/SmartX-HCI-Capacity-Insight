# 项目文档地图

本文件是 SmartX HCI Capacity Insight 全部文档的总索引（开发/维护用，项目对外简介见根目录 [README.md](../README.md)）。开始任何代码、升级包或远程环境操作前，先按 [AGENTS.md](../AGENTS.md) 的顺序阅读根目录工作文档，再按本地图定位专项文档。

当前版本边界：平台 `v0.5.2`、runner `v0.3.1`、分支 `dev2`。

## 1. 根目录工作文档（每次会话必读）

| 文档 | 说明 |
| --- | --- |
| [AGENTS.md](../AGENTS.md) | AI 协作标准：文档读取顺序、分支与提交规则、三台服务器操作边界、架构边界、升级链路、包门禁、失败报告标准。 |
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
| [frontend-style-guide.md](frontend-style-guide.md) | 前端 UI 风格规范：设计变量、圆角/阴影、按钮/输入/分段开关规格、状态色语义、布局模式。AI 写任何 UI 前必读。 | 全部前端任务 |
| [api.md](api.md) | API Reference：对外接口说明。 | — |
| [usage.md](usage.md) | 使用说明。 | — |
| [deployment.md](deployment.md) | 部署指南：目标服务器 Compose 部署、目录、运行时配置和离线部署。 | v2-rebuild Phase V2-9 |

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

## 5. 升级链路专项文档

固定升级链路：`v0.5.1 + runner v0.3.0 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2`。

| 文档 | 说明 | 关联任务 |
| --- | --- | --- |
| [v0.5.0-to-v0.5.2-upgrade-plan.md](v0.5.0-to-v0.5.2-upgrade-plan.md) | 总体升级计划（source of truth）。 | — |
| [v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md](v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md) | u2 -> v0.5.2 段修复规划：修复方案、实施顺序、包版本策略、验收标准。 | 根 Phase 32~48 |
| [v0.5.1u2-to-v0.5.2-upgrade-issues.md](v0.5.1u2-to-v0.5.2-upgrade-issues.md) | u2 -> v0.5.2 段问题现象与现场证据。 | 根 Phase 32~48 |
| [v0.5.1-to-v0.5.2-upgrade-chain-worklog.md](v0.5.1-to-v0.5.2-upgrade-chain-worklog.md) | 链路执行记录：详细过程、失败证据、task ID、包 SHA、验证结果。 | UPG-031~048 |
| [v0.5.1-to-v0.5.2-upgrade-chain-task-findings.md](v0.5.1-to-v0.5.2-upgrade-chain-task-findings.md) | 链路任务计划与发现归档：原 task_plan/findings 中的 Phase 32~48 详情迁至此。 | 根 Phase 32~48 |
| [upgrade-runner-lifecycle.md](upgrade-runner-lifecycle.md) | upgrade-runner 生命周期：平台包与 runner 组件包边界、runner 自升级策略。 | task_plan Phase 22 |
| [upgrade-issues.md](upgrade-issues.md) | 升级模块问题台账（UPG-001 起）：问题清单、根因和关闭状态。 | task_plan Phase 6~9 等 |
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

## 8. 编号体系说明

项目存在三套并行编号，查阅时注意区分：

- **根 Phase（task_plan.md）**：Phase 1~31 为 v2 重建与产品化阶段；Phase 32~48 是升级链路专项阶段，详情归档在 [v0.5.1-to-v0.5.2-upgrade-chain-task-findings.md](v0.5.1-to-v0.5.2-upgrade-chain-task-findings.md)（fix10 并入 Phase 32，无独立 Phase 33）；Phase 49 为 v0.5.2 后治理待办。逐项对照见 [task_plan.md](../task_plan.md) 的「Phase 与任务设计文档对照」。
- **UPG-xxx（升级问题/修复编号）**：UPG-001 起记录在 [upgrade-issues.md](upgrade-issues.md)；UPG-031~048 为升级链路修复，记录在 [upgrade-chain-worklog.md](v0.5.1-to-v0.5.2-upgrade-chain-worklog.md)。
- **Phase V2-x（v2 重建子阶段）**：定义在 [v2-rebuild-task-plan.md](v2-rebuild-task-plan.md)（V2-0 ~ V2-9）。

## 9. 资产

`docs/assets/` 保存 README 使用的界面截图（dashboard-overview、forecast-report、tower-settings、vm-storage-trend）。
