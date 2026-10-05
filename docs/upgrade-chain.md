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
| **Runner bootstrap** ⚠️ | **v0.5.1u2** | **v0.3.1** | 只有 runner 进入新 project | 新 runner network | **唯一的 runner 组件升级步骤**；不迁移平台三件套/Prometheus/旧目录 |
| Target | v0.5.2 | v0.3.1 | `smartx-hci-capacity-insight` | `smartx-hci-capacity-insight-net`（10.249.251.0/24） | 完成单根目录、网络、Prometheus 与旧环境清理 |
| Latest | v0.5.3 | v0.3.1 | 同上 | 同上 | 保持目标布局 |

> 为什么链路里的 runner 升级放在 **u2** 而不是更早：u2 的源端仍是**旧 project**（`smartx-storage-forecast`），组件包 bootstrap 要停的是旧 project 的 runner，新 runner 不会被误停

### 2.1 ⚠️ 每步必须用哪个 compose 文件（2026-10-04 实测踩坑后固定）

| 步 | 动作 | compose project 名 | compose 文件（`-f`） | 预期网络 | 网络来源 |
| --- | --- | --- | --- | --- | --- |
| 0 | 全新安装旧布局 | `smartx-storage-forecast` | `docker-compose.offline.yml` | `smartx-storage-forecast_smartx-net`（**由 project 名派生**，见 §2.1.1） | compose 内 `ipam` 10.249.249.0/24 **自动创建** |
| 1 | v0.5.1 → v0.5.1u2 | `smartx-storage-forecast` | `docker-compose.offline.yml` | 同上，不变 | 沿用 |
| 2 | **runner → v0.3.1**（**在 u2 节点做**，见 §2.2） | 走产品 API `/api/admin/component-upgrade/*`，**不要手工跑 compose** | — | 切换为 `smartx-hci-capacity-insight-net` | **由 runner bootstrap 自己创建**（`.12` 2026-10-04 实测失败，见 §2.2） |
| 3 | v0.5.1u2 → v0.5.2 | 升级过程内部切 project | 走产品 API `/api/admin/upgrade/*` | 沿用目标网络 | 沿用 |
| 4 | v0.5.2 → v0.5.3 | `smartx-hci-capacity-insight` | 走产品 API `/api/admin/upgrade/*` | 沿用目标网络，不变 | 沿用 |

> **步序依据**：v0.5.1u2 的 Release notes（本 Release 的两份包支持以下链路）明确写：
> `v0.5.1 + runner v0.3.0 → v0.5.1u2 平台升级 → runner v0.3.1 组件升级 → v0.5.2 平台升级`。
> **runner 组件升级就在 u2 节点**，这是已发布的客户契约，不可改动。
>
> ⚠️ 2026-10-04 我曾据 `.12` 一次失败把它改成「v0.5.2 之后」——**该改动是错的，已回滚**。
> 那次失败的真因是**用错了 v0.5.1u2 平台包**（用了本地副本而非 Release 资产），详见 §2.2。

**硬规则**：

1. **每一步的升级动作都走产品 API**（`upload` → `precheck` → `start`），
   **不要手工执行 `docker compose` 升级**。升级编排（切 project、换网络、备份、
   健康检查、post-cleanup）全部在产品流程内完成；手工 compose 绕过这些保护。
2. **`docker compose` 只用于「装环境」和「排障查看」**，不用于「升级」。
3. **链路包必须用 GitHub Release 资产**，并核对 SHA——本地副本不算数（见 §2.2 的踩坑记录）。
4. 排障时判断当前处于哪个 project，看容器的 compose 标签，不要靠猜：
   `docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' <容器>`

### 2.1.1 🔴 每个版本实际使用的 project 名与网络名（2026-10-04 从包内 compose 实测提取）

**这张表是查包内 `docker-compose.offline.yml` 得到的，不是推断。**
**它揭示了一个反直觉的事实**：compose 里的名称**在 v0.5.1u2 就已经改成目标布局的名字了**，
比网络真正切换到目标布局（v0.5.2）早了一个版本——这正是步 2 失败的根源。

| 版本 | compose 顶层 `name:` | 实际网络 `name:` | 网络 subnet | 说明 |
| --- | --- | --- | --- | --- |
| **v0.5.1** | **（无顶层 name）** | **未显式命名** → 由 project 名派生 = **`smartx-storage-forecast_smartx-net`** | `10.249.249.0/24` | 旧布局。project 名由 `-p` 传入，故网络名随 project 变 |
| **v0.5.1u2** | **`smartx-hci-capacity-insight`** | 未显式命名 → 派生 = **`smartx-hci-capacity-insight_smartx-net`** | **无 subnet** | ⚠️ **顶层已改成目标名，但网络还没显式命名、也没 subnet**。此时若用顶层 name 起容器，网络名会变成 `smartx-hci-capacity-insight_smartx-net`，与旧布局的 `smartx-storage-forecast_smartx-net` **不是同一个网络** |
| **v0.5.2** | `smartx-hci-capacity-insight` | **显式 `smartx-hci-capacity-insight-net`** | `10.249.249.0/24` | 目标布局。网络名**显式固定**，不再随 project 派生 |
| v0.5.3 | `smartx-hci-capacity-insight` | 显式 `smartx-hci-capacity-insight-net` | 沿用 | 保持目标布局 |

**关键结论（务必记住）**：

1. **v0.5.1 的网络名是「派生」的**，因为 compose 里既没有顶层 `name:` 也没有网络 `name:`。
   实际网络名 = `<compose project 名>_smartx-net`。所以 §2.1 步 0 用
   `-p smartx-storage-forecast` 起容器时，网络自动叫 `smartx-storage-forecast_smartx-net`——
   **这不是配置，是派生的副产物**。换 `-p` 就换网络名。
2. **v0.5.1u2 起顶层 name 变成 `smartx-hci-capacity-insight`**，但**网络仍未显式命名**。
   这是一个「半迁移」状态：project 名已改、网络名靠派生、subnet 丢失。
3. **v0.5.2 才把网络名显式固定**为 `smartx-hci-capacity-insight-net` 并补回 subnet。
4. 因此**「旧布局」与「半迁移布局」的网络名不同**：
   - 旧布局（v0.5.1）：`smartx-storage-forecast_smartx-net`
   - v0.5.1u2 若按顶层 name 起：`smartx-hci-capacity-insight_smartx-net`

**排障时先确认这三样**（不要靠猜）：

```bash
# 1) 当前 compose project 名（看容器标签，比看文件可靠）
docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' <容器>
# 2) 当前实际网络名
docker network ls --format '{{.Name}}' | grep -i smartx
# 3) 某个 compose 声明的 project / 网络名
grep -nE '^name:|name:.*-net' <compose 文件>
```

### 2.2 🔴 已实测的阻塞：步 2 在旧布局上会失败（2026-10-04 `.12` 实测）

**现象**：`v0.5.1u2` 上执行 runner 组件升级 → **failed**。

```
[OK] backup  [OK] load_images  [OK] project_files  [OK] write_override
[FAIL] restart     → docker compose -f docker-compose.runner-upgrade.yml
                      --project-name smartx-hci-capacity-insight up -d upgrade-runner
[FAIL] healthcheck
error: network smartx-hci-capacity-insight-net declared as external, but could not be found
```

**根因**：v0.5.1u2 生成的 `/data/compose-runtime/docker-compose.runner-upgrade.yml` 里写死了

```yaml
networks:
  smartx-net:
    external: true
    name: smartx-hci-capacity-insight-net    # ← 目标布局的网络名
```

而旧布局下实际网络是 `smartx-storage-forecast_smartx-net`。
该文件声明为 `external: true`（**外部网络，必须已存在**），但此时它还不存在
——它要到 v0.5.2 的 `environment_transitions` 才创建。

**根因与 §2.1.1 的对应关系（这是关键）**：

| 事实 | 出处 |
| --- | --- |
| 旧布局实际网络是 `smartx-storage-forecast_smartx-net`（v0.5.1 网络名**由 project 名派生**） | §2.1.1 第 1 行 |
| v0.5.1u2 生成的 runner-upgrade compose 声明 `name: smartx-hci-capacity-insight-net` + `external: true` | §2.2 现象 |
| `smartx-hci-capacity-insight-net` 这个名字要到 **v0.5.2** 才被显式定义 | §2.1.1 第 3 行 |
| v0.5.1u2 的 compose **顶层 name 已经是** `smartx-hci-capacity-insight` | §2.1.1 第 2 行 |

即：**v0.5.1u2 处在「名字已改、网络未建」的半迁移状态**。
它的 runner-upgrade compose 按**目标布局**的名字去找网络，而那个网络此刻还不存在。

**⚠️ 结论修正（2026-10-04，用户以 Release notes 指出后）**：

我一度据此判定「步 2 不能在 u2 上做、应改到 v0.5.2 之后」——**这个结论是错的，已回滚**。
两个硬证据推翻它：

1. **v0.5.1u2 的 Release notes**（已发布的客户契约）明确写：
   `v0.5.1 + runner v0.3.0 → v0.5.1u2 平台升级 → runner v0.3.1 组件升级 → v0.5.2 平台升级`
   ——**runner 组件升级就在 u2 节点**，产品本就该能在这里建好新网络。
2. **ledger 有 `VALIDATED / CHAIN OK` 记录**：`runner-v0.3.1-upg032-historyfix`
   （即 Release 资产 `d10e15cf…`）历史上跑通过整条链路。

**真因是我用错了包**：本次 `.12` 演练的 v0.5.1u2 平台包取自
`.3:/data/upgrade-packages/`（SHA `2b5688b5…`），**那是本地副本，未核对是否为 Release 资产**。
而 Release 权威 SHA 是：

| 包 | Release 权威 SHA | 本次实际用的 | 对否 |
| --- | --- | --- | --- |
| v0.5.1u2 平台包 | `d5f277167445e7636ddfba16b4f780b40d59952467bb1c8e72d2469b43ee0a49` | `2b5688b5…` | ❌ **用错** |
| runner v0.3.1 | `d10e15cf7b516d172ebe2f1bc37621f9cf32d8ab3abd548f808ae5c5de151d2c` | `d10e15cf…` | ✅ 正确 |

即：runner 包用对了，**平台包用错了**。AGENTS 早就记着这条教训
（§10 交付一致性门禁）：「用开发镜像过的验收，换回 Release 资产立刻在 cutover 后失败」。
本次是同一个教训的另一个形态——**用本地副本过的验收，换回 Release 资产才暴露问题**。

**因此本节结论作废，保留上文仅作为「用错包会导致什么」的记录。**
正确做法：链路包一律从 GitHub Release 下载并核对 SHA（§2.1 硬规则第 3 条）。

**待做**：用 Release 资产 `d5f27716…` 重做 `.12` 的步 1–2，验证官方链路确实跑通。

### 2.3 完整测试流程（固定版，照此执行，不得跳步）

每一轮链路测试**必须**按此顺序，每步留证据：

| # | 步骤 | 动作 | 必须留的证据 |
| --- | --- | --- | --- |
| 0 | 固化基线 | `capture_baseline.py capture` + `verify` | verify EXIT=0、counts、SHA256SUMS |
| 1 | 清空环境 | 停容器 → 删旧布局目录 → **保留基线目录** | 删除清单 + 基线仍可 verify |
| 2 | 装旧布局 | `pre_install.sh` → 造 `.env` → 按 §2.1 步 0 的 project/文件起容器 | 容器标签里的 project 名、web-api/VERSION、runner/RUNNER_VERSION |
| 3 | 导入数据 | 从基线恢复 `smartx.db` + Prometheus | **Prometheus 目录必须 `chown 65534:65534`**（否则 prometheus panic 重启） |
| 4 | 起点确认 | `/api/system/health` + 前端可访问 + 数据行数 | health ok、三项 checks、VM/卷行数与基线一致 |
| 5 | 逐节点升级 | **按 §2.1 的步序（步 1→4）**，**每步都走产品 API**，每步做完立刻验收再进下一步。**注意步 3（runner 组件升级）必须在步 2 之后** | 每步的 task_id、precheck 结果、status、升级后 health/版本/行数 |
| 6 | 终态验收 | 8 项验收（见 release-acceptance） | 逐项结论 |

**每步升级后的即时验收项（缺一不可）**：

```
health.ok=true 且 checks 三项全 true
version / runner_version 与该步预期一致
数据行数与升级前一致（VM/卷）
容器数与 project 名符合 §2.1
post-cleanup = succeeded（v0.5.2 起才有该接口）
```

**中断规则**：任一步失败 → **停下、报告、记录根因**，不手工绕过、不跳步继续。
（本次即在步 2 停下。）

**包来源纪律**：每步用的包必须记录 SHA 与来源。
runner v0.3.1 必须用**已发布资产** `d10e15cf…`
（`.3:/home/user1/codex-build/packages-upg032-historyfix/02-runner-v0.3.1-historyfix/`），
不得用本地重建镜像充当基线（2026-09-27 `.12` 实测教训：用开发镜像过的验收，
换回 Release 资产立刻失败）。；一旦迁到目标布局（v0.5.2）就不行了（见 §1 第 3 条）。

---

## 3. 平台 ↔ runner 配对表

| 平台版本 | 配套 runner | 说明 |
| --- | --- | --- |
| v0.5.1 | v0.3.0 | 旧布局起点 |
| v0.5.1u2 | v0.3.0 →（组件升级后）v0.3.1 | 桥接；链路中唯一一次 runner 组件升级发生在这里 |
| **v0.5.2** | **v0.3.1** | **已发布**；客户现状；不需要也不能动 runner |
| v0.5.3 | v0.3.1（基线）→（可选、之后）runner 组件（开发线 v0.3.2） | 候选；平台包声明基线是已发布 v0.3.1 |
| （v0.5.3 之后） | runner 组件（开发线 **v0.3.2**，含 US-24 修复） | **可选组件升级**；未交付（无 tag、DockerHub 无镜像、无组件包资产）——**随下一版一起发** |
| v0.5.4 | v0.3.1（基线）或现场更高的 v0.3.2 | 开发线；**只支持目标布局源（v0.5.2+）**，偏斜矩阵见 §7 |

交付物出处（易踩）：`smartx-upgrade-runner-v0.3.1.tar.gz`（SHA `d10e15cf…`）是挂在 **v0.5.1u2 那个 Release** 上的资产，不在 v0.5.2 Release 里（v0.5.2 Release 只有平台包）；DockerHub 的 `v0.3.1` 镜像是 2026-09-27 手工补推的。

---

## 3.1 已发布事实的核对方法（2026-10-04 补充，避免再凭印象判断）

判断「某 runner 版本是否已发布、能不能改」时，**先查这三处，不要凭印象**：

| 查什么 | 怎么看 | 2026-10-04 实测结果 |
| --- | --- | --- |
| DockerHub 有哪些 tag | `curl -s "https://hub.docker.com/v2/repositories/nazawsze/smartx-hci-capacity-insight-upgrade-runner/tags?page_size=50"` | 仅 `v0.3.0` / **`v0.3.1`** / `latest` / `runner-sha-31a1209`——**无 v0.3.2** |
| 仓库声明的版本 | 根目录 `RUNNER_VERSION` | `v0.3.2`（**开发线**，≠ 已发布） |
| 已发布资产 | 本文 §3 配对表 + `docs/upgrade-package-ledger.md` | 最后一条配对是 `v0.5.2 + runner v0.3.1` |

**结论（截至 2026-10-04）**：**runner v0.3.2 从未发布、从未推送、未生成组件包交付资产**，
只在 `.3` 本地有镜像。因此：

- v0.3.2 的代码可以**直接修改，不需要 bump `RUNNER_VERSION`**——
  AGENTS §6 的 bump 要求是为防止「**已发布版本**同号不同能力」，对未发布版本不适用。
- 现场基线是 **v0.5.2 + runner v0.3.1**（§3 表格第 3 行）。

## 3.2 ⚠️ 测试机已偏离客户基线（发布前必须恢复）

`.12` 与 `.14` 当前跑的 runner 是 **v0.3.2**，**不是**客户现场的 v0.3.1——
那是 2026-10-04 做 r15/r16/r17 候选包升级验收时装上去的。

**影响**：后续做「v0.5.2 → v0.5.3 直升 + 8 项验收」（§5 矩阵 M3-09，现场主路径）时，
起点不对——真实客户是 v0.5.2 + v0.3.1，测试机却已是 v0.5.3 + v0.3.2。

**发布前必须把 `.12`/`.14` 的 runner 恢复到 v0.3.1 基线**（或重走 §2 完整链路恢复整机基线；
后者为破坏性操作，需用户单独批准）。在此之前，这两台**不能**作为
「客户现场主路径」的验收证据。

## 3.3 我的一次误判（记录以免重犯）

2026-10-04 我在讨论 #82（runner 心跳遇 SQLite 锁崩溃）时，先两次误判：

1. 套用「改 runner 必须 bump `RUNNER_VERSION`」，把 #82 判为"需等用户批准"而挂起；
   实际 v0.3.2 未发布，**可直接修**。
2. 修完后称「DockerHub 的 `runner-v0.3.2` tag 与新代码不一致，需重推」——
   **该 tag 根本不存在**，且本文 §3 第 9 行早已写明「无 tag、DockerHub 无镜像」。

**两条都是同一个毛病：结论前没有查既有事实**（一次查文档、一次查远端 API），
而是先形成印象再找依据支撑。

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

---

## 7. v0.5.4 偏斜矩阵（2026-10-06 定案，权威）

### 7.1 支持矩阵

| 源端平台 | 源端 runner | → v0.5.4 | 计划动作集 | 验证状态 |
| --- | --- | --- | --- | --- |
| v0.5.2 | v0.3.1 | ✅ | 常量 6 类（见 7.2） | **静态已验证**（已发布 v0.5.2 镜像内编译器实测 8 个动作）；真机待 C1 |
| v0.5.2 | v0.3.2 | ✅ | 同上 | 静态同（计划与 runner 版本无关）；真机待 C1（**US-26 判别格**：runner 不得被降级） |
| v0.5.3 | v0.3.1 | ✅ | 同上 | **静态已验证**（v0.5.3 镜像内编译器实测 8 个动作）；真机待 C1 |
| v0.5.3 | v0.3.2 | ✅ | 同上 | 静态同；真机待 C2（自换时代最后一次旧编排） |
| v0.5.4 | v0.3.1 / v0.3.2 | ✅ 同版本重装 | 同上 | 待 C1 |
| v0.5.1u2 / v0.5.1u1 / v0.5.1 / v0.5.0 | 任意 | ⛔ **不支持** | — | precheck 拒绝 + 引导「先升 v0.5.3」 |

⛔ 行的口径（用户 2026-10-06 定案）：**v0.5.4 只支持目标布局**。仍在旧布局的现场必须先升
`v0.5.3`（该链路已验证：v0.5.1u2 → v0.5.3 直升、`v0.5.2 → v0.5.3` 直升都有真机记录），
再升 `v0.5.4`。理由与实现见 impl-spec §W6.1：`directory_transition` / `legacy_cleanup`
非空时计划必然长出迁移·交接·legacy 动作（实测 10 步），而这些正是 US-26 一类事故的高发区。
v0.5.3 及更早的平台包**不受此收窄影响**，仍支持 v0.5.0–v0.5.1u2 直升。

### 7.2 每一格的动作集（常量，断言锁在 impl-spec §W6.2）

```text
backup.create → image.load ×3 → files.sync → compose.override → compose.apply → health.http
```

- bundle 包（声明 observability 组件）额外 `health.prometheus`；
- 有 SQLite schema 迁移时额外 `script.run_sandboxed`；
- **不发射**：`compose.project_migrate` / `filesystem.prepare` / `task.migrate_runtime_state` /
  `task.sync_runtime_state` / `runner.handoff_target_runtime` /
  `runner.schedule_target_runtime_handoff` / `runner.stop_legacy_runtime` / `legacy.cleanup` /
  `compose.stop_legacy_project` / `network.remove_legacy` / `filesystem.cleanup_*` /
  `post_cleanup.*` / `post_upgrade.schedule_cleanup` / `post_upgrade.schedule_collection`。
  这些动作的**实现仍保留**（v0.5.3 及更早的包编译出的计划还会下发它们），退役的是
  「v0.5.4 默认计划模板里的位置」，登记见 impl-spec §W6.3。

### 7.3 谁编译计划（偏斜的真正含义）

计划由**源端 web-api 的编译器**生成，runner 只执行。因此每格的动作集取决于**源端版本**的编译器：

- v0.5.2 / v0.5.3 的编译器对 v0.5.4 manifest 的输出，已在**已发布镜像内**实测：
  两者的动作集与候选编译器完全一致（各 8 个动作 / 6 个类型）。
- 构建门禁 `scripts/verify_upgrade_plan_vocabulary.py` 只证明**候选包编译器**的输出
  （它会对此打 WARN，见该脚本 `plan_source_compiled_downstream`），老编译器的行为由本节
  的静态实测 + 批次 C 的真机矩阵共同覆盖。

### 7.4 顺序铁律在 v0.5.4 上的应用

- **默认先平台、后 runner**：v0.5.4 平台包对 runner 只有基线声明（`deploy:false`），
  现场 runner ≥ 基线时不动它（US-26）。
- runner v0.3.2 的自换是**平台升级之后**的可选组件升级（自换时代）；顺序颠倒会让
  目标布局源端（v0.5.2/v0.5.3）的 web-api 无条件 stop 掉刚启动的新 runner（US-04 根因）。
- 同一时刻只允许一个升级任务（US-23 单飞守卫）。

### 7.5 本节未验证项（不得当作已验证）

| 项 | 归属 |
| --- | --- |
| `.14` 全新安装 + v0.5.3 → v0.5.4 直升（T3：prometheus/runner 容器 ID 不变 + 差异清单） | 批次 C1 |
| 组件升级 v0.3.1 → v0.3.2（兼容矩阵「v0.5.4 + v0.3.2」格，旧编排最后一次） | 批次 C2 |
| r18 真包形态（含 W7 全门禁、守卫脚本落现场 project 目录） | 批次 C5 |
| ⛔ 行的 precheck 拒绝与引导文案 | 批次 B3 |
