# 升级链路（权威版）

本文档是**升级链路、平台↔runner 配对、升级顺序规则的唯一权威出处**。AGENTS.md §7、[docs/deployment.md](deployment.md) §10.1、[docs/version-governance.md](version-governance.md) 只保留摘要并指向本文；如有冲突以本文为准。

最后核对：2026-09-27（用户逐条复核链路后定稿）。

---

## 0. 一句话口径

- **已发布的平台版本是 `v0.5.2`**，它配套的 runner 是**已发布 `v0.3.1`**。
- **现场（v0.5.2）的下一次升级就是 `v0.5.2 → v0.5.3` 一步直升，不带 runner 步骤。**
- `v0.5.3` 目前是**候选、未发布**（当前候选包第五轮 `b9560eee…`）。
- `runner v0.3.2` **不在链路里**：它只是"平台升到 v0.5.3 **之后**的可选组件升级"。**用户 2026-09-28 决定：不随本次发布交付，改与下一个版本一起发**（开发线 `v0.3.2`，含 US-24 修复；因此本次不补 tag/镜像/资产；源码 compose 里的 `v0.3.3` 属开发线状态）。

---

## 1. 现场主路径（客户现场就是这条）

```text
v0.5.2  + runner v0.3.1     （已发布；客户的现状）
   └─ 平台升级 ─────────────▶  v0.5.3 + runner v0.3.1   （候选包，一步到位）
```

依据：

1. v0.5.3 升级包的 `source_compatibility` 覆盖 `v0.5.0 / v0.5.1 / v0.5.1u1 / v0.5.1u2 / v0.5.2 / v0.5.3`，manifest 含 `environment_transitions` / `directory_transition` / `legacy_cleanup`。
2. 平台包的 **runner 基线固定为已发布 `v0.3.1`**（`build_upgrade_package.py::_expected_web_api_runner_baseline()`，按发布事实、不随仓库 `RUNNER_VERSION` 漂移）→ 现场**不需要**动 runner。
3. 现场**也不能**先动 runner：v0.5.2 的 web-api 在执行 runner 组件升级时会无条件 `docker compose --project-name <当前 project> stop upgrade-runner`，目标布局下停的是**刚启动的新 runner**（`.12` 两轮实测：约 10s `SIGKILL`、`exit=137`、心跳过期）。同 project 守卫只存在于 v0.5.3 起的镜像。
4. 该路径已在 `.12` 验证过两次：2026-09-20（包 `6accea95…`）与 2026-09-27 第四轮（包 `e1c0fde8…`，task `upgrade-666284beec04cc87`），主任务 + post-cleanup 均 succeeded、8 项验收全过。

---

## 2. 完整链路（仍停在 v0.5.1 / 旧布局的老客户 + 升级演练）

```text
v0.5.1 + runner v0.3.0
  -> v0.5.1u2            (桥接包：runner 仍 v0.3.0，保持旧 project/network)
  -> runner v0.3.1       (★ 整条链路唯一一次 runner 组件升级：在 u2 上做，用**已发布**资产 d10e15cf…)
  -> v0.5.2              (Target：平台三件套迁移到单根目录 / 新 network / Prometheus / legacy cleanup)
  -> v0.5.3              (Latest：保持 v0.5.2 目标布局，无新增迁移)
```

节点表（平台 ↔ runner ↔ project ↔ network）：

| 节点 | 平台 | Runner | Compose project | Network | 这一步做什么 |
| --- | --- | --- | --- | --- | --- |
| Source | v0.5.1 | v0.3.0 | `smartx-storage-forecast` | `smartx-storage-forecast_smartx-net`（10.249.249.0/24） | 旧 project、旧运行目录 |
| Bridge | v0.5.1u2 | v0.3.0 | 保持旧 | 保持旧 | 只提供桥接能力（可被 v0.3.0 runner 执行），不提前迁移平台 |
| **Runner bootstrap** | **v0.5.1u2** | **v0.3.1** | 只有 runner 进入新 project | 新 runner network | **唯一的 runner 组件升级步骤**；不迁移平台三件套/Prometheus/旧目录 |
| Target | v0.5.2 | v0.3.1 | `smartx-hci-capacity-insight` | `smartx-hci-capacity-insight-net`（10.249.251.0/24） | 完成单根目录、网络、Prometheus 与旧环境清理 |
| Latest | v0.5.3 | v0.3.1 | 同上 | 同上 | 保持目标布局 |

> 为什么链路里的 runner 升级放在 **u2** 而不是更早：u2 的源端仍是**旧 project**（`smartx-storage-forecast`），组件包 bootstrap 要停的是旧 project 的 runner，新 runner 不会被误停；一旦迁到目标布局（v0.5.2）就不行了（见 §1 第 3 条）。

---

## 3. 平台 ↔ runner 配对表

| 平台版本 | 配套 runner | 说明 |
| --- | --- | --- |
| v0.5.1 | v0.3.0 | 旧布局起点 |
| v0.5.1u2 | v0.3.0 →（组件升级后）v0.3.1 | 桥接；链路中唯一一次 runner 组件升级发生在这里 |
| **v0.5.2** | **v0.3.1** | **已发布**；客户现状；不需要也不能动 runner |
| v0.5.3 | v0.3.1（基线）→（可选、之后）runner 组件（开发线 v0.3.2） | 候选；平台包声明基线是已发布 v0.3.1 |
| （v0.5.3 之后） | runner 组件（开发线 **v0.3.2**，含 US-24 修复） | **可选组件升级**；未交付（无 tag、DockerHub 无镜像、无组件包资产）——**随下一版一起发** |

交付物出处（易踩）：`smartx-upgrade-runner-v0.3.1.tar.gz`（SHA `d10e15cf…`）是挂在 **v0.5.1u2 那个 Release** 上的资产，不在 v0.5.2 Release 里（v0.5.2 Release 只有平台包）；DockerHub 的 `v0.3.1` 镜像是 2026-09-27 手工补推的。

---

## 4. 顺序铁律（必须遵循）

1. **默认先升平台、后升 runner 组件**——runner 不是每版都更新：**只有当平台新增了旧 runner 无法执行的能力/动作（平台包 `minimum_runner_version` 高于现场 runner）时，才先升 runner、再升平台**。若现场 runner 已满足要求，**runner 完全不需要动**（`minimum_runner_version` 是「最低」而非精确版本，预检查按 ≥ 判定）。
   - **推论（US-26）**：现场 runner 已够用时，平台升级**不得改动 runner**（当前实现会按包内基线 tag `--force-recreate`，把更高的现场版本降级，见 issues US-26）。
2. **演练/验收用的例外顺序**：源端仍是旧 project（如 v0.5.1u2）时，"先 runner 后平台"在技术上可行（stop 打的是旧 project 的 runner）。这只用于演练/验收，**不适用于已迁到目标布局的现场**（那里应走第 1 条的条件判定）。
3. **同时只允许一个升级任务**：已有 pending/running/runner_restarting/recovery_required/rollback_* 时，start / 重试 / 恢复 / 回滚一律拒绝（400）。
4. **禁止**用"把 runner 组件升级提前"来规避包内的 runner 版本要求（但第 1 条的「平台确需更高 runner」情形不属于规避——那是唯一应当先升 runner 的场景）——包内 runner 基线由平台包按发布事实指定；源码 compose 写的 `v0.3.2` 只是开发线状态（见 version-governance 的交付缺口条目）。
5. **症状速查**：升级后 runner 容器消失 / 心跳过期 / 预检查报「未检测到 upgrade-runner 心跳」→ 先查是不是把 runner 组件升级做在了平台升级**之前**。

---

## 5. 与验收/审计矩阵的对应

| 验收项 | 可执行性 | 说明 |
| --- | --- | --- |
| v0.5.2 → v0.5.3 直升 + 8 项验收（矩阵 M3-09 的"平台先"） | ✅ 可执行 | **现场主路径**，需要 `.12` 授权 |
| 重复 start → 400（US-23） | ✅ 可执行，**不需要 `.12`** | web-api 逻辑，`.3` 上用两个预检查通过的包连点即可 |
| M3-08：v0.5.1u2 × **先 runner 后平台**（验 US-05「post-cleanup 顺序无关」） | ⛔ **不做（N/A，用户 2026-09-28）** | 支持链路只有「先平台、后 runner」，runner-first 不是受支持路径；且该断言只在"现场 runner ≠ 包基线 v0.3.1"时出现，需要不随本次发布的 runner 组件（开发线 v0.3.2）。US-05 按"代码 + manifest 实证的防御性修复"记录，不得写"顺序无关已实测" |
| M3-10：v0.5.2 × **先 runner 后平台** | ❌ **N/A** | v0.5.2 源端装不住活的 v0.3.2 runner（§1 第 3 条），该顺序在目标布局上不存在 |
| M3-12：v0.5.3 × 先 runner 后平台 | 可执行但价值低 | v0.5.3 已有同 project 守卫；它验证的是"修好之后"的版本 |

---

## 6. 待决与依赖

| 待决 | 影响 |
| --- | --- |
| ~~runner v0.3.2 是否交付~~ | **已决（2026-09-28 用户）**：**不随本次发布交付，与下一个版本一起发**。本次发布只发平台包（runner 基线 = 已发布 v0.3.1）；M3-08 因此不做；US-24 的 runner 修复也随之归到下一版的 runner 交付里（届时 bump v0.3.3）。发布材料不得把 v0.3.2 写成本次交付物。 |
| **`.12` 验收授权**（AGENTS §5：只有用户明确授权才可连/可升级） | 决定"v0.5.2 → v0.5.3 直升 + 8 项验收"能否执行；若 `.12` 现状不是 v0.5.2，还需单独批准是否重走 §2 链路恢复基线（破坏性） |
| runner 侧"执行期也刷新实例心跳" | 需改 runner 代码 → 必须事先经用户同意 + bump 版本（v0.3.3）+ 重交付组件包；登记在 pending-tasks #47 |
