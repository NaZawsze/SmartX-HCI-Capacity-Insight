# 迁移执行者解耦设计（pending #90，目标 v0.5.5）

> **2026-10-21 状态更正**：本文是最初的局部方案，尚未实施。其“迁移由新版 web-api 启动时执行”、runner 零改动和 `v0.5.4 + runner v0.3.1` 验收基线不再作为实施依据；集中架构方案见 [v0.5.5 集中升级架构收口设计](2026-10-21-v055-upgrade-architecture-redesign.md)。本文保留作决策历史。

- 日期：2026-10-14
- 来源：用户追问「以后能不能不升 runner 就升平台」时发现的**设计意图 vs 实现差距**
- 状态：设计（待实施；**不改 runner ⇒ 不需要 runner 新版本**）

## 1. 背景与现状（含关键实测）

**设计意图**（`2026-10-05-upgrade-architecture-v054-design-v2.md` §2.1）：平台升级 = **七步常量流程**，
「全部用 v0.3.1 就有的动作表达」，第 5 步原文写「健康门（**schema 迁移由新 web-api 启动时自跑**，
expand-only）」——即平台升级计划**不含迁移动作**。

**实现现状**（与设计不一致）：
- 平台包把迁移做成 **runner 动作**：`impl-spec:261`「带 schema 迁移时额外 `script.run_sandboxed`」；
  `scripts/build_upgrade_package.py` 由 `migrations/registry.json` 生成 `database_migration=true` 并
  把 `run_migrations.py` 打进包 → r34 包计划 9 动作含 `run-migration`，由**当前运行的 runner** 执行。
- 老 runner（< r35，含已发布 v0.3.1）执行该动作撞 **US-40**（沙箱脚本挂载用容器内路径）必失败
  → 故 v0.5.4 定案「**先组件、后平台**」。

**关键实测（2026-10-14，代码级）**：**平台启动时已经在做同类 expand-only 变更**——
`backend/app/v2/database.py::initialize()` 内有大量 `_ensure_column(...)`（users/tasks/towers/vm_latest…），
且 registry 的 **4 条 v0.5.4 迁移**（`vm_latest.owner` / `vm_latest.folder_name` /
`towers.tower_version` / `clusters.os_version`）**在 `_ensure_column` 里也各有一份**。
⇒ 同一批 schema 变更**存在两份来源**，而 runner 那步 `run-migration` 对它们是**冗余的**。

## 2. 目标与口径

| 项 | 口径 |
| --- | --- |
| 单一来源 | `migrations/registry.json` 为 schema 变更的**唯一声明源**；启动期执行器由它驱动 |
| 执行时机 | **新版 web-api 启动时**自跑（幂等）；expand-only ⇒ 旧代码与新代码都能跑 |
| 计划瘦身 | 平台升级计划回到**七步常量流程**（无 `run-migration`） |
| 记账 | 每次应用写 `schema_migrations`（`id/version/description/script_sha256/applied_at`）——表已存在 |
| 纪律 | **只允许 expand-only**（加列/加表）；破坏性变更走 Expand–Contract 两步，禁止单步收缩 |
| 兼容 | 老包（v0.5.4 及更早）里的 `run-migration` 动作**实现保留**，旧计划照旧可执行 |

## 3. 方案

1. **平台侧执行器**：新增 `backend/app/v2/migrations.py`（或并入 `database.py`）——
   读 registry → 逐条按 `operations`（当前只有 `add_column_if_missing`）幂等执行 → 写 `schema_migrations`。
   在 `V2Database.initialize()` 中调用（**先于**任何业务读写）。
2. **来源归一**：把 `database.py` 里与 registry 重复的 `_ensure_column` 调用改为由注册表驱动
   （保留不在 registry 内的历史列，标注为 legacy 一次性补齐）。
3. **打包侧**：`build_upgrade_package.py` 不再把迁移作为**动作**下发（`database_migration` 退化为
   信息字段或直接去掉），包内不再需要 `run_migrations.py`。
4. **runner 侧**：**零改动**（`script.run_sandboxed` 保留给其他用途）。
5. **收益**：平台升级动作集 ⊆ 已发布 runner 能力 ⇒ **既有环境可「只升平台、不动 runner」**；
   US-40 顺序约束对未来版本**消失**（v0.5.4 本身的顺序约束不变，因其包已定稿）。

## 4. 边界与不做

- **不改 runner 代码/能力 ⇒ 不 bump `RUNNER_VERSION` ⇒ 不需要 runner 新版本**（AGENTS §6）；
- **不改 v0.5.4 已定稿的包**（候选包已三级验收，临时加结构性改动会作废验收）→ 本设计随 **v0.5.5**；
- 不做**破坏性**迁移的自动化（收缩/重命名仍需人工设计 + 两步发布）；
- 不把迁移挪进「新容器」（保持 5 容器边界，AGENTS §6）。

## 5. 测试计划

| 用例 | 断言 |
| --- | --- |
| 幂等 | 连续两次启动：第二次不再执行、`schema_migrations` 不新增行、无报错 |
| 单一来源 | registry 与启动期实际执行的变更集合一致（新增一致性测试，防两处漂移） |
| 计划瘦身 | 构建 v0.5.5 包：计划 = 七步常量流程、**不含** `run-migration`；动作集 ⊆ v0.3.1 能力 |
| 老包兼容 | v0.5.4 包（含 `run-migration`）在 v0.3.2 runner 上仍可执行（回归） |
| **真机（关键）** | `.14`：**v0.5.4 + 已发布 runner v0.3.1** → 直接升 v0.5.5 **succeeded（无需先升 runner）**；`schema_migrations` 落库；回滚可用 |
| 数据红线 | 升级前后业务计数逐位不变（沿用 8 项验收） |

## 6. 回滚

- 平台侧：执行器与 `_ensure_column` 均为幂等 expand-only，`git revert` 即可（列留在库里无害）；
- 打包侧：恢复下发 `run-migration` 即回到现状（老 runner 顺序约束随之回归）；
- 无数据破坏路径：本设计不引入任何收缩/删除操作。
