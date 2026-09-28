# 升级架构备选方案调研与评估

> 2026-09-28 用户指令：「你想想还有什么更好的升级架构，市面上比较流行的」。
> **本文只做调研与评估，不含实施计划、不改代码。** 架构选型属产品/业务决策，需用户拍板。

## 0. 我们要解决什么（先把问题定义清楚）

从 `docs/upgrade-strategy-issues.md` §C2 的三类共性出发，本项目升级链路的结构性约束是：

| 约束 | 现状 | 后果 |
| --- | --- | --- |
| **执行者即被升级对象** | 编译计划/预检查/执行编排跑在**源端 web-api**；runner 既执行升级又是升级对象 | 包里的新逻辑对当次无效（US-01）；平台升级顺手降级 runner（US-26） |
| **状态归属不唯一** | runner tag 写在 3 个 compose 文件；版本号与能力不同源 | 静默漂移（US-26/US-02） |
| **执行期共享可变资源** | runner 与 web-api 共用一个 SQLite；同一文件两个路径视图 | 写锁互相阻塞（US-28）；自伤崩溃循环（US-24） |
| **交付环境不可控** | on-prem、客户现场、升级窗口有限、宿主不可随意操作 | 失败代价高，现场无法自救 |

**关键判断**：这四条同时存在时，**"就地自举升级"本身就是高风险模式**。行业里处理这类问题的主流思路不是"把自举做得更小心"，而是三条：**① 声明式收敛 ② 原子切换+可回滚 ③ 执行者与被升级对象解耦**。

---

## 0.5 先回答：我们的架构正常吗？业界标准是什么样？

**结论：正常。我们的「控制面/执行面分离」就是业界标准做法，三条缺陷都不是架构错误，是实现没贯彻分离。**

### 业界标准架构（逐个对照）

| 系统 | 升级时谁 orchestrate | 谁执行 | 关键机制 |
| --- | --- | --- | --- |
| **Kubernetes** | 控制面（apiserver）只存**期望状态** | kubelet 拉镜像重建 Pod | **声明式收敛**：只改 diff 掉的 Pod；`maxUnavailable` 控制爆炸半径 |
| **Helm** | Tiller/API 存 release revision | K8s 执行 | `--atomic`：失败自动 `rollback` 到上个 revision；`--wait` 等 ready 才算成功 |
| **Ansible** | 控制节点（**不是被管节点**） | 被管节点 agent | 幂等模块：同一状态重复执行无副作用 |
| **Puppet** | master 编译 catalog | agent 应用 | agent 自更新与 master 无关 |
| **rpm-ostree / OSTree** | 无（离线组装新树） | bootloader 原子切换 | **A/B 双份 + 原子换 + 随时回滚**：「拔电源也只有旧版或新版」 |
| **Windows / ChromeOS** | recovery / verified boot | A/B slot | BCD 分区槽位，更新失败回旧槽 |

**从这张表能提炼出三条共识，我们只做到第一条的一半：**

| 业界共识 | 我们的状态 |
| --- | --- |
| ① **执行者独立于被升级对象** | ✅ **做到了**（runner 独立容器，web-api 升级 runner、runner 升级平台）——这是对的 |
| ② **期望状态驱动、只动 diff** | ⚠️ **半做**：我们是**固定动作清单**（execution_plan），不是收敛。`compiler.py:53` 排除了 runner（对），但 handoff 那条路没排除（US-26） |
| ③ **可回滚**（原子切换/双份） | ❌ **没做**：回滚路径从未验证（US-17），也没有双份保留 |

### 需要更正我之前的一个说法

我之前把 **US-01（平台包的新校验对当次升级无效）** 说成「架构缺陷」。**这个定性不准确**——查证后应当更正：

- Kubernetes 明确支持**版本偏斜**（version skew）：v1.28 控制面管理 v1.26 kubelet，且**这是设计常态**
- 升级时执行任务的**就是旧版本组件**（旧 kubelet 拉新镜像），新版本逻辑当次不生效——**这在业界是正常的**
- 业界处理方式不是「把校验下沉」，而是两条：**① 明确的版本偏斜策略（写死支持矩阵）② N-2 兼容保证**

**所以 US-01 的正解不是重构，而是把「支持矩阵」写清楚并测出来**（我们现在有 `source_compatibility` 但覆盖面不足），而不是想办法让新逻辑在当次生效。

### 成熟方案对照我们缺什么

| 成熟机制 | 业界怎么做 | 我们 | 差距 |
| --- | --- | --- | --- |
| **期望状态收敛** | K8s 只重建 diff 掉的 Pod | 固定动作清单 + 盲目 force-recreate | **US-26 的根因**；改造量最小（compose_apply 改 diff） |
| **原子回滚** | OSTree A/B、Helm `--atomic` | 无双份、回滚未验 | US-17 空白格；这是客户最关心的能力 |
| **版本偏斜策略** | K8s 公开 skew policy | `source_compatibility` 覆盖不全 | 需补齐 + 实测 |
| **N-2 兼容** | 滚动升级前提 | 无 | 长期 |
| **执行者状态隔离** | kubelet 与 apiserver **不共享数据库** | **runner 与 web-api 共用一个 SQLite** | **US-28 的根因；我们最大的架构偏差** |

**一句话总结**：架构方向是对的（①完全正确），缺的是 ②收敛、③回滚、以及「执行者不共享业务数据」这一条。**不需要推倒重来。**

## 1. 业界主流方案（按与本项目的贴合度排序）

### 方案 A：声明式期望状态 + 收敛（Declarative Reconciliation）— **最推荐**

**代表**：Kubernetes / Helm / Ansible / Terraform

**核心思想**：不写"一步步做什么"，而是声明"最终应该长什么样"，由控制器不断比较 **期望状态 vs 实际状态** 并收敛。

```text
期望状态（compose 文件 / manifest）  ←── 唯一事实源
        ↓ 比较差异
实际状态（运行中的容器 / 目录 / 数据库）
        ↓ 只对差异项动作
收敛
```

**业界怎么保证不误伤**：
- Kubernetes：只改 `image` tag → 只重建该 Pod；未变的不动
- Helm `upgrade --atomic`：失败自动 `--rollback` 到上一个 revision；`--wait` 等所有资源 ready 才算成功
- Ansible：模块幂等，同一状态重复执行无副作用

**对本项目的价值（直接命中三条共性）**：

| 共性 | 声明式如何解决 |
| --- | --- |
| ② 状态归属不唯一 | **compose 文件就是唯一事实源**。runner tag 只在 compose 里写一次，收敛逻辑读它算 diff——US-26 那种"三个文件三个 tag"在结构上不可能发生 |
| ① 执行者即被升级对象 | 控制器只动 **diff 里的服务**。`compose.up` 只传需要变更的 service，runner 不在 diff 里就绝不会被碰 |
| ③ 共享可变资源 | 收敛是**逐项**的，可以把"数据库迁移"作为独立于容器切换的一步，先做完再切流量 |

**改造量**：**最小**。现在的 `compose_apply` 已经在做 `docker compose up -d --no-deps <services>`——把 `<services>` 从"包内 manifest 写死的列表"改成"**实际 diff 出来的列表**"，就是声明式收敛的核心。US-26 顺带被根治。

**代价**：需要定义"期望状态"的完整表达（compose 已经基本够用）；控制器要有 diff 能力（`docker compose config` 对比实际）。

---

### 方案 B：原子切换 + 自动回滚（Atomic with Rollback）

**代表**：OSTree / rpm-ostree（Fedora CoreOS、RHEL CoreOS/OpenShift、Oracle Linux）、Helm `--atomic`、Windows A/B 分区

**核心思想**（OSTree 官方表述）：
> "You can turn off the power anytime you want… you will have either the old system, or the new one."

- 新版本装到**另一个位置**（A/B 分区 / 另一棵文件树 / 另一个 deployment）
- 装完**原子切换**（bootloader 条目、符号链接、容器 tag）
- **回滚 = 切回去**，不是"反向执行一遍升级"

**为什么这是趋势**：传统包管理（dpkg/rpm）**在正在运行的系统上就地改**——这是所有"升到一半坏了"的根源。OSTree 的做法是"算出一棵新树 → 原子换 → 旧的还留着"。

**对本项目的价值**：
- **回滚成本从"天"降到"分钟"**：现在 `rollback` 路径**从来没验过**（审计矩阵 US-17 空白格），因为反向升级的复杂度极高
- 升级失败不再需要"逃生门 + 人工判断残留"（US-27 的根因就是"没有回滚，只能硬着头皮收尾"）
- 客户现场敢升级的心理门槛大幅降低

**代价（要诚实说）**：
- 需要**双份空间**（镜像/文件树），磁盘需求翻倍
- **数据迁移不可回滚**——这是 expand-contract 要解决的问题（见方案 C）
- OSTree 那套是 OS 级的，对我们来说过重；**但"原子切换"这个思想可以只借鉴**：例如容器 compose 用两个 project（blue/green）而不是就地改

---

### 方案 C：Expand–Contract（渐进式数据迁移）

**代表**：Martin Fowler《Parallel Change》、Prisma Data Guide、pgroll、PGConf 2024 最佳实践

**核心思想**（Fowler 原文）：把不兼容变更拆成**三个阶段**，中间存在一个**新旧共存的兼容窗口**：

```text
Expand    改代码用新结构，但**继续双写旧结构**     ← 兼容窗口
Migrate   后台回填历史数据
Contract  确认全部走新路径后，才删旧结构
```

**为什么有效**：
- 每个阶段**独立可部署、可回滚**（回滚时旧结构还在、数据还在）
- "big bang 迁移"是万恶之源：一步改完，回滚等于灾难

**对本项目的价值**：
- 直接解决**数据迁移不可回滚**这个死结（方案 B 解决不了的部分）
- 契合我们已经在做的事：`US-09` 产物自动清理（延后清理）、`legacy_cleanup` 延后到健康检查后——**思路本来就是对的，只是没有成体系**
- 具体可借用的：SQLite 加列而非改列；新旧字段并存期间用 feature flag 控制读写路径；清理延后到确认稳定后

**代价**：需要**接受"N 个版本之后才清理干净"**这个现实，产品侧要认同；需要写迁移状态机（哪个环境处于 expand/migrate/contract 哪一阶段）。

---

### 方案 D：执行者与被升级对象解耦（外部编排）

**代表**：Chromium Updater（独立更新器进程，**应用不能自己更新自己**）、Oracle Private Cloud Appliance Upgrader（**独立应用、独立发布计划**）、K8s Operator（控制器与应用分离）

**核心思想**（Chromium Updater 设计文档）：
> Updater 是独立进程；"应用只能更新自己拥有的应用"；**旧版本 updater 自我淘汰**（新版本激活后，旧的卸载或让位）。

**对本项目的价值**：
- **对 US-01 是锦上添花而非必需**：US-01 的正解是写死版本偏斜策略 + 补齐兼容矩阵（业界常态），执行者解耦能进一步降低耦合但不是唯一解
- 我们其实**已经半只脚在这条路上了**——`upgrade-runner` 就是独立容器。问题是它和 web-api **共用同一个 SQLite**（US-28），且 web-api 还负责编译计划

**代价**：
- 编排逻辑要能跨版本存活（旧 runner 必须能执行新平台的升级动作）→ **协议要真正稳定化**
- 现场若要"救砖"，需要一条**与平台完全无关的**通路

---

### 方案 E：受控的分步升级（Staged / N-2 兼容）

**代表**：BeyondTrust B Series（Fast Track / Standard Track / Enterprise Track，**Enterprise Track 落后 2 个版本**）、Kubernetes 滚动升级的 `maxSurge/maxUnavailable`

**核心思想**：永远保持 **N-2 兼容**——新版本能读旧数据，旧版本能读新数据。这样任意中间状态都可运行，升级顺序就不敏感。

**对本项目的价值**：
- **让"升级顺序"这个老大难问题消失**：因为两个方向都兼容，谁先谁后都行
- 客户可以滞后 2 个版本再升，运维压力小

**代价**：schema/协议要维持向后兼容，**不能随意重构数据模型**——长期有"兼容债"成本。

---

## 2. 对比总表

| 方案 | 解决①执行者即对象 | 解决②单一事实源 | 解决③共享资源 | 提供回滚 | 改造量 | 适配 on-prem 单机 |
| --- | --- | --- | --- | --- | --- | --- |
| **A 声明式收敛** | ✅ 部分（只动 diff） | ✅ 根治 | ⚠️ 部分 | ❌ | **小** | ✅ 最佳 |
| **B 原子切换** | ❌ | ❌ | ❌ | ✅ 强 | 中大 | ⚠️ 需双份空间 |
| **C Expand-Contract** | ❌ | ❌ | ✅ 数据层 | ✅ 数据层 | 中 | ✅ |
| **D 执行者解耦** | ✅ 根治 | ⚠️ | ✅ 根治 | ⚠️ | **大** | ⚠️ 需外部通路 |
| **E N-2 兼容** | ⚠️ | ❌ | ❌ | ⚠️ | 中大（长期） | ✅ |

**没有单一方案能全覆盖**——这与业界共识一致：Kubernetes 自己也是"声明式 + 滚动 + 兼容窗口 + 回滚"组合使用。

## 3. 我的建议（分三层，按投入产出排序）

### 立刻做（已在计划里，49-55）
- US-26/27/28 修复 = **方案 A 的局部实现**（只动 diff、不静默降级、状态可见）
- 它们本身就是往声明式收敛迈的步子

### 下一版规划（中等投入，收益最大）
1. **把 `compose_apply` 改成真声明式**：实际 diff 决定重建哪些服务 → **US-26 类问题结构性消失**
2. **单一事实源收口**：runner tag / 版本 / 能力只在一处声明，其余全部从它派生 → 对应 US-02/US-26
3. **数据迁移走 expand-contract**：加列不删列、延后清理、清理前有确认门 → 解决 US-17（回滚没验过）与 US-27
4. **回滚路径补齐并实测**：至少保证"平台镜像回退 + 兼容窗口内数据可读"

### 长期（需产品决策，收益大但要立项）
- **方案 D：执行者解耦**。让升级编排真正独立于被升级的 web-api（现在 runner 只是"半独立"，因为计划和状态还在 web-api + 共用 DB）
- 这直接回答你的判断："这种升级模式就是有问题的"——**问题的解法就是别让被升级的对象负责升级自己**

## 4. 与本项目约束的匹配性检查

| 本项目硬约束 | 方案适配 |
| --- | --- |
| on-prem 现场、宿主不可控 | A / C / E 友好；B 需双份空间（要客户预留）；D 需外部通路 |
| 升级窗口有限 | A 快；B 切换快但准备慢；C 分多次；D 中等 |
| SQLite 单机 | C 的双写/回填完全适用；B 对数据层无效（要靠 C） |
| 不能频繁改客户环境 | A 幂等友好；E 允许滞后 |
| 客户自助升级、无工程师现场 | **A + B 的价值最高**（收敛 + 能回滚）；C 需要产品侧长期配合 |

## 5. 结论

1. **短期**（49-55 已计划）：US-26/27/28，都是方案 A 的局部落地，先把已知缺陷收掉。
2. **中期**：走方案 A（声明式收敛）+ C（expand-contract），这两条**不改变交付形态、客户几乎无感**，但能结构性消除"静默降级""回滚不可用""数据迁移不可逆"三类问题。
3. **长期**：你指出的"升级模式本身有问题"，正解是**方案 D（执行者解耦）**——但这是架构级投入，需要产品层面判断是否值得。**本 plan 不推进，只登记判断**（task_plan 第 54 项）。

## 参考

- OSTree 原子升级与回滚：<https://ostreedev.github.io/ostree/atomic-upgrades>、<https://github.com/ostreedev/ostree/blob/main/docs/atomic-rollbacks.md>
- rpm-ostree（Fedora CoreOS / RHEL CoreOS / Oracle Linux）：<https://coreos.github.io/rpm-ostree>
- Helm `--atomic` / `--rollback-on-failure`：<https://docs.helm.sh/docs/helm/helm_upgrade>
- Martin Fowler《Parallel Change》（Expand and Contract）：<https://martinfowler.com/bliki/ParallelChange.html>
- Prisma Expand-and-Contract：<https://www.prisma.io/dataguide/types/relational/expand-and-contract-pattern>
- pgroll（PGConf EU 2024）：<https://www.postgresql.eu/events/pgconfeu2024/sessions/session/5871/>
- Chromium Updater 设计（独立更新进程）：<https://chromium.googlesource.com/chromium/src/+/main/docs/updater/design_doc.md>
- Oracle Private Cloud Appliance Upgrader（独立于平台的升级器）：<https://docs.oracle.com/en/engineered-systems/private-cloud-appliance/2.4/admin-2.4.2/admin-pca-update-upgradertool.html>
- BeyondTrust B Series 分级更新通道：<https://docs.beyondtrust.com/rs/docs/on-prem-appliance-updates>
