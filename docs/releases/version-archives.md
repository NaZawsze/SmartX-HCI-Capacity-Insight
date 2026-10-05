# 版本档案（按版本归纳的文档索引）

> 本文件是「**按版本找文档**」的唯一入口：每个版本一节，归纳该版本的发布事实、设计文档（按主题分组）、
> 关联问题与记录锚点。文件本身不搬家（specs/plans 按日期命名、链接不失效），归纳在这里维护。
> 新版本发布时在顶部追加一节；设计文档与版本的对应关系以 task_plan「Phase 与任务设计文档对照」+ doc-map 为准，
> 本文件是它们的**版本视图**。维护纪律：新增设计文档时在对应版本的「设计文档」小节补一行。

---

## v0.5.4（开发中，Phase 68）

- **状态**：设计中（2026-10-05 立项）。主题 = 升级架构重构为业界三层形态。
- 设计：[架构设计 v2](../superpowers/specs/2026-10-05-upgrade-architecture-v054-design-v2.md)（取代 v1）
  ｜ [实施级规格](../superpowers/specs/2026-10-05-upgrade-architecture-v054-impl-spec.md)（W1–W8/M1–M7/T1–T12）
  ｜ [实施计划](../superpowers/plans/2026-10-05-upgrade-architecture-v054-plan.md)
  ｜ 被取代的 v1：[2026-10-05-upgrade-architecture-v054-design](../superpowers/specs/2026-10-05-upgrade-architecture-v054-design.md)
- 关联：pending #62/#53/#83；AGENTS §6 自换规则修订（2026-10-05）。

---

## v0.5.3（已发布 2026-10-05）

- **发布事实**：tag `v0.5.3`；平台包 `ef3fab9f…`（r17，源码 dev2 `ebcbeae`）+ `.sha256`，GitHub Release 资产；
  runner 基线 = 已发布 **v0.3.1**（不随发，`v0.3.2` 随 v0.5.4 火车）；镜像 web-api `6747dc1bf418` / collector `8393442f2bd7` / frontend `d4d70803b432`。
- **验收**：`.12` 老客户整链路（v0.5.1+v0.3.0 → u2 → runner v0.3.1 → v0.5.2 → v0.5.3，全程 Release 资产）8 项全过；
  `.14` 干净机全流程；`.3` 门禁 816 tests + 前端 tsc 0 / vitest 108。构建轮次 r1–r17 全记录见 [upgrade-package-ledger.md](upgrade-package-ledger.md)。

### 设计文档（按主题分组，59 个 specs 中属本火车的 48 个）

**升级链路与 runner（15）**
[2026-09-13-compose-literal-tags](../superpowers/specs/2026-09-13-compose-literal-tags-design.md) ·
[2026-09-19-v053-repackage-and-v052-regression-upgrade-test](../superpowers/specs/2026-09-19-v053-repackage-and-v052-regression-upgrade-test-design.md) ·
[2026-09-20-source-compose-literal-tags](../superpowers/specs/2026-09-20-source-compose-literal-tags-design.md) ·
[2026-09-27-runner-delivery-consistency-gate](../superpowers/specs/2026-09-27-runner-delivery-consistency-gate-design.md) ·
[2026-09-27-runner-presence-during-execution](../superpowers/specs/2026-09-27-runner-presence-during-execution-design.md) ·
[2026-09-27-runner-v032-and-action-level-precheck](../superpowers/specs/2026-09-27-runner-v032-and-action-level-precheck-design.md) ·
[2026-09-27-us05-us23-release-blocking-fix](../superpowers/specs/2026-09-27-us05-us23-release-blocking-fix-design.md) ·
[2026-09-27-v053-platform-side-post-upgrade-collection](../superpowers/specs/2026-09-27-v053-platform-side-post-upgrade-collection-design.md) ·
[2026-09-27-upgrade-artifact-housekeeping](../superpowers/specs/2026-09-27-upgrade-artifact-housekeeping-design.md) ·
[2026-09-27-upgrade-disk-space-precheck](../superpowers/specs/2026-09-27-upgrade-disk-space-precheck-design.md) ·
[2026-09-28-offline-one-click-install-upgrade](../superpowers/specs/2026-09-28-offline-one-click-install-upgrade-design.md) ·
[2026-09-28-upgrade-settlement-fallback](../superpowers/specs/2026-09-28-upgrade-settlement-fallback-design.md) ·
[2026-09-28-us26-runner-declaration-not-instruction](../superpowers/specs/2026-09-28-us26-runner-declaration-not-instruction-design.md) ·
[2026-09-30-delivery-compose-runner-baseline](../superpowers/specs/2026-09-30-delivery-compose-runner-baseline-design.md) ·
[2026-09-30-us37-compose-variant-guard](../superpowers/specs/2026-09-30-us37-compose-variant-guard-design.md)

**容量口径 / 采集 / 报表（15）**
[2026-09-12-capacity-alert-and-overview-freshness](../superpowers/specs/2026-09-12-capacity-alert-and-overview-freshness-design.md) ·
[2026-09-12-exhaustion-robust-forecast](../superpowers/specs/2026-09-12-exhaustion-robust-forecast-design.md) ·
[2026-09-19-collection-freshness-probe](../superpowers/specs/2026-09-19-collection-freshness-probe-design.md) ·
[2026-09-19-forecast-band](../superpowers/specs/2026-09-19-forecast-band-design.md) ·
[2026-09-19-vm-scale-and-chart-window](../superpowers/specs/2026-09-19-vm-scale-and-chart-window-design.md) ·
[2026-09-20-report-latency-optimization](../superpowers/specs/2026-09-20-report-latency-optimization-design.md) ·
[2026-09-25-allocated-capacity-bar](../superpowers/specs/2026-09-25-allocated-capacity-bar-design.md) ·
[2026-09-25-collection-snapshot-merge-and-stale-annotation](../superpowers/specs/2026-09-25-collection-snapshot-merge-and-stale-annotation-design.md) ·
[2026-09-26-cluster-chart-gap-break](../superpowers/specs/2026-09-26-cluster-chart-gap-break-design.md) ·
[2026-09-26-new-vm-first-seen](../superpowers/specs/2026-09-26-new-vm-first-seen-design.md) ·
[2026-09-26-recycle-bin-vm-exclusion](../superpowers/specs/2026-09-26-recycle-bin-vm-exclusion-design.md) ·
[2026-09-26-recycle-lifecycle-sync](../superpowers/specs/2026-09-26-recycle-lifecycle-sync-design.md) ·
[2026-09-26-reports-growth-window-requires-successful-collection](../superpowers/specs/2026-09-26-reports-growth-window-requires-successful-collection-design.md) ·
[2026-09-26-shared-vm-growth](../superpowers/specs/2026-09-26-shared-vm-growth-design.md) ·
[2026-10-03-allocation-caliber-and-vm-purge](../superpowers/specs/2026-10-03-allocation-caliber-and-vm-purge-design.md)

**数据迁移（7）**
[2026-09-20-migration-page-ux-review](../superpowers/specs/2026-09-20-migration-page-ux-review.md) ·
[2026-09-21-migration-page-key-flow-and-layout-revision](../superpowers/specs/2026-09-21-migration-page-key-flow-and-layout-revision.md) ·
[2026-09-21-migration-page-three-zone](../superpowers/specs/2026-09-21-migration-page-three-zone-design.md) ·
[2026-09-30-migration-data-only-package](../superpowers/specs/2026-09-30-migration-data-only-package-design.md) ·
[2026-10-01-full-export-complete](../superpowers/specs/2026-10-01-full-export-complete-design.md) ·
[2026-10-01-merge-import-tower-remap](../superpowers/specs/2026-10-01-merge-import-tower-remap-design.md) ·
[2026-10-02-dashboard-migration-five-issues](../superpowers/specs/2026-10-02-dashboard-migration-five-issues-design.md)

**工程健康度与运维工具（11）**
[2026-09-12-p1-infra-batch](../superpowers/specs/2026-09-12-p1-infra-batch-design.md) ·
[2026-09-12-p2-ops-batch](../superpowers/specs/2026-09-12-p2-ops-batch-design.md) ·
[2026-09-12-p3-hygiene-batch](../superpowers/specs/2026-09-12-p3-hygiene-batch-design.md) ·
[2026-09-13-admin-split](../superpowers/specs/2026-09-13-admin-split-design.md) ·
[2026-09-13-ai-wording-layer](../superpowers/specs/2026-09-13-ai-wording-layer-design.md) ·
[2026-09-13-api-response-models](../superpowers/specs/2026-09-13-api-response-models-design.md) ·
[2026-09-13-contract-alignment](../superpowers/specs/2026-09-13-contract-alignment-design.md) ·
[2026-09-13-excel-chart-polish](../superpowers/specs/2026-09-13-excel-chart-polish-design.md) ·
[2026-09-13-export-legacy-digest](../superpowers/specs/2026-09-13-export-legacy-digest-design.md) ·
[2026-09-13-remove-v1-dead-code](../superpowers/specs/2026-09-13-remove-v1-dead-code-design.md) ·
[2026-09-13-split-giant-files](../superpowers/specs/2026-09-13-split-giant-files-design.md)

**运维工具与交付 CLI（4）**
[2026-09-20-auto-backup-and-env-pairing](../superpowers/specs/2026-09-20-auto-backup-and-env-pairing-design.md) ·
[2026-09-20-cleanup-capability-extension](../superpowers/specs/2026-09-20-cleanup-capability-extension-design.md) ·
[2026-09-20-upg050-carrier-lock-and-prepare-skeleton](../superpowers/specs/2026-09-20-upg050-carrier-lock-and-prepare-skeleton-design.md) ·
[2026-09-30-cli-toolkit](../superpowers/specs/2026-09-30-cli-toolkit-design.md)

**Tower 设置页与杂项（1）**
[2026-09-12-tower-settings-ui](../superpowers/specs/2026-09-12-tower-settings-ui-design.md)

### 关联问题（本火车关闭/处置）
US-05/07/08/09/23/24(修入 v0.3.2)/25/26/28(缓解)/32/37/38/39(登记待下版)；UPG-049/050；
pending #56–#66、#71–#82 大部分关闭（逐条状态见 [pending-tasks.md](pending-tasks.md)）。

### 记录锚点
[progress.md](../../progress.md)「2026-09-12」起各节；[task_plan.md](../../task_plan.md) Phase 49–67；
[findings.md](../../findings.md) 2026-09-12 起各节；实施流水 2026-09 前的部分已归档至 [docs/archive/](../archive/)。

---

## v0.5.2（已发布 2026-09-20）

- 包 `6accea95…`（dev2 `ff1bd52`）；runner 配对 v0.3.1（首次交付，Release 资产 `d10e15cf…`）。
- 主题：Compose project/network 固定化（`smartx-hci-capacity-insight`）、单根目录 `/data/smartx-storage-forecast`、
  legacy 清理、升级任务跨重启恢复（Phase 22）、平台自检与升级后验收（Phase 25）、P1 数据正确性（Phase 26）。
- 关键文档：[upgrade-chain.md](upgrade-chain.md)（链路权威口径）、
  [v0.5.1-to-v0.5.2-upgrade-chain-worklog.md](v0.5.1-to-v0.5.2-upgrade-chain-worklog.md)（执行流水）、
  [upgrade-issues.md](upgrade-issues.md)（UPG-031~050 问题台账）、[task_plan.md](../../task_plan.md) Phase 21–49 前段。

## v0.5.1u2（桥接包，2026-08）

- 用途：桥接 v0.5.1 → runner v0.3.1 → v0.5.2 的中间版本（只提供桥接能力，不迁移平台）。
- 包 `d5f27716…`；Release 说明含 runner v0.3.1 组件包 `d10e15cf…`。
- 关联：[2026-07-10-post-upgrade-auto-collection](../superpowers/specs/2026-07-10-post-upgrade-auto-collection-design.md)、
  [v0.5.1u2-to-v0.5.2-upgrade-issues.md](v0.5.1u2-to-v0.5.2-upgrade-issues.md)。

## v0.5.1 / v0.5.0（历史）

- 见 [CHANGELOG.md](CHANGELOG.md) 对应节与 [architecture-v2.md](architecture-v2.md)（v2 重构背景：
  项目曾因"升级升不上去"做过一次大重构）。

---

## 维护说明

- 本文件由发布动作链维护：发版时新增一节（发布事实 + 该火车设计文档分组 + 问题关闭清单）。
- 设计文档文件本身**不搬家**（按日期命名、历史链接不失效）；版本 ↔ 设计的映射以本文件 + doc-map 为准。
- 历史归档（实施流水 2026-09 之前）在 [docs/archive/](../archive/)，索引在 progress.md 顶部。
