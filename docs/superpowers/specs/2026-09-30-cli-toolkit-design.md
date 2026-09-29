# CLI 工具链设计：安装 / 升级 / 打包三件套

- 日期：2026-09-30
- 关联：task_plan 第 58 项、pending-tasks #58
- 前置：#56（离线交付，已实施并 `.14` 实测）、#57 阶段 A（v0.5.2 → v0.5.3 主路径，2026-09-30 verified）
- 状态：设计定稿，待实施

## 1. 背景与问题

用户需求（2026-09-30）：

> 「cli 下的安装、升级脚本和文件夹放在合适的位置，方便别人找到，然后确保安装、升级链路在 cli 下没问题。
> 同时希望在 cli 下升级打包功能也做一个脚本，升级包也放在一个文件夹内。我个人觉得这 3 个 cli 功能放在一个文件夹下比较好，
> 但我不懂程序设计，依你为准。希望打包脚本是这样的，他直接 git clone 我的项目，会自动增量项目文件，然后他 clone 后，
> 直接执行打包脚本就可以进行打包，当然如果缺少工具和依赖也要给提示。目前主力就是命令行下的项目安装和更新能力。」

### 1.1 现状核实（2026-09-30）

| 能力 | 现有位置 | 实测状态 | 真实缺口 |
| --- | --- | --- | --- |
| 一键安装 | `delivery/install/install.sh` | `.14` 断网安装通过 | **不在仓库开发入口位置**，clone 后无从发现 |
| 一键升级 | `delivery/upgrade/upgrade.sh` | `.14` 断网升级通过 | 同上 |
| 打包 | `scripts/build_release_delivery.sh` + `scripts/build_offline_delivery.py` | `.3` 上可用 | **是开发机内部编排**：假定人在 `.3`、仓库已在本地、三镜像已构建。**换一台干净机器 clone 完不能直接打包** |
| 升级包归档 | `.3:/data/upgrade-packages/<日期目录>/` | 可用 | **散落无索引**，靠人记路径，无 `latest` 概念 |

结论：三个能力**都存在**，缺的是「**入口可达**」与「**打包可独立**」。

### 1.2 两个必须分清的「位置」语义

现有脚本在 `delivery/` 下，但 `scripts/build_offline_delivery.py:48` 的 `SCRIPT_SOURCES` 表明
**`delivery/install/install.sh` 是被复制进交付目录的源文件**。因此存在两份：

- **仓库开发态**：`delivery/` 里的脚本 + 仓库其余部分（可一起测试、可改）
- **交付态**：交付目录里的 `install/` + `upgrade/`（**必须自包含**，客户手上只有这一份，不能依赖仓库）

本设计的 `cli/` 属于**仓库开发态**，是「怎么用这些能力」的统一入口，不改变交付态的自包含性。

## 2. 目标与非目标

### 2.1 目标

1. **入口可达**：clone 仓库后，`cli/README.md` 让没接触过本项目的人在 5 分钟内选对脚本。
2. **打包可独立**：干净 Linux 机器上 `git clone` → `bash cli/package.sh` 即出包，缺依赖给**可执行**的修复指引。
3. **产物归置**：平台包与 runner 组件包集中到 `cli/packages/`，有 `latest` 与 `archive/`。
4. **不破坏已验证链路**：`delivery/` 的安装/升级逻辑**一行不改**，`cli/` 只做薄封装。

### 2.2 非目标

- 不重写 `install.sh` / `upgrade.sh` 的业务逻辑（`.14` 已实测通过）。
- 不做自动安装系统依赖（见 Q5 决策）。
- 不做 CI（打包是人工触发的命令行动作，产物是 Release 资产的**输入**而非输出）。
- 不把 `cli/` 放进交付目录（见 Q6 决策）。

## 3. 目录结构（定稿）

```
cli/
├── README.md                 # 三入口索引与选择指引（首要产物）
├── install.sh                # 入口 1：薄封装 → delivery/install/install.sh
├── upgrade.sh                # 入口 2：薄封装 → delivery/upgrade/upgrade.sh
├── package.sh                # 入口 3：一键打包（新增主体）
├── check-deps.sh             # 依赖自检（新增，被 package.sh 调用，可单独跑）
├── lib/
│   └── common.sh             # 共用：日志/颜色/错误处理/确认提示
└── packages/                 # 产物归档（.gitignore 内容）
    ├── latest/               # 最新可用：平台包 + runner 组件包
    └── archive/YYYYMMDD/     # 历史包按日期
```

### 3.1 为什么「入口归置、产物分离」

采纳用户「三个功能放一个文件夹」的倾向（脚本同源、共享依赖自检与口径，好找、不会走散），
但**产物必须分离**：

| 产物 | 体积（实测） | 生命周期 | 变更频率 |
| --- | --- | --- | --- |
| 安装物料（镜像 tar） | ~1.1 GB | 跟一次发布 | 低 |
| 升级包（版本单元 tar.gz） | ~235 MB | 跟一次发布 | 低 |
| 打包输出（构建中间产物） | 临时 | 一次性 | 高 |

混在一个目录会让 `latest` 语义含混（到底是最新镜像还是最新包）、清理策略无法制定
（删构建产物会误删交付物）。这延续 task_plan #56 用户已定口径 Q2：
**「安装交付运行物料、升级交付版本单元」**。

### 3.2 为什么不把 `cli/` 放进交付目录

交付目录必须**自包含**（客户手上只有 `install/` + `upgrade/` + 镜像 + 升级包）。
`cli/` 是仓库开发态入口，依赖 git、依赖 `scripts/` 下的一堆构建脚本，放进交付物只会
增加体积与困惑。`cli/install.sh` 与 `cli/upgrade.sh` 的存在恰好**反证**了交付目录不需要它们。

## 4. 待决问题的决策

| # | 问题 | 决策 | 理由 |
| --- | --- | --- | --- |
| **Q1** | git 增量策略与分支 | **默认分支 `main`，必须显式可用 `--branch` 覆盖；用 `git fetch --prune` + `git checkout <branch>` + `git reset --hard origin/<branch>`，且 `reset --hard` 前必须交互确认（`--yes` 可跳过）。不设「静默默认」** | 本项目 `dev2` 是开发线、`main` 是发布线（核实：`origin/HEAD -> origin/main`）。**打包必须显式指定分支**，否则会打出开发线包发给客户。破坏性操作必须让用户知情 |
| **Q2** | 打包机预检 | **非 Linux 或缺 Docker / docker compose 时立即拒绝并退出（exit 2），不做中途失败** | 镜像构建必须 Linux + Docker。提前拒绝比构建到一半失败省时间、错误更清楚 |
| **Q3** | `latest` 语义 | **副本（非软链）+ `archive/` 保留最近 5 份，超出按日期删最旧** | 软链在拷贝目录/换机器时会断（`.3 → .14` 转移就依赖实体文件）。副本代价是 ~470MB 重复占用，但可预测。历史包保留 5 份足够回溯，超出无价值 |
| **Q4** | 入口与 `delivery/` 关系 | **薄封装：`cli/install.sh` 用 `exec` 调 `delivery/install/install.sh`，参数透传** | 交付目录必须自包含（不能依赖仓库），所以**逻辑必须留在 `delivery/`**。`cli/` 只做「入口可达」。已实测逻辑一行不改，`.14` 验证结论继续有效 |
| **Q5** | 依赖缺失的修复边界 | **只检测 + 给可执行指引（含具体安装命令），不提供 `--auto-install`** | 在客户机器上自动装系统包是危险动作；AGENTS §5 亦禁止未经确认的宿主变更。给对命令让人自己执行，既安全又够用 |
| **Q6** | `cli/` 是否进交付目录 | **不进** | 见 §3.2 |

## 5. `package.sh` 设计

### 5.1 执行流程

```
bash cli/package.sh [--branch main] [--yes] [--output-dir cli/packages] [--skip-checks]
  1. 调 lib/common.sh 装载日志与错误处理
  2. 调 check-deps.sh —— 缺什么给什么指引，缺则 exit 2
  3. git fetch --prune origin
  4. git checkout <branch> && git reset --hard origin/<branch>
     （有本地改动时提示将被丢弃；--yes 跳过确认）
  5. 重新执行 check-deps.sh（checkout 后 scripts/ 可能变了）
  6. 校验版本一致性：VERSION / RUNNER_VERSION / 三个 compose 的 runner tag
     不一致 → 报错并指出（这是交付一致性门禁 C1/C3 的前置）
  7. 构建平台包：python3 scripts/build_upgrade_package.py --output-dir <tmp>
  8. 构建 runner 组件包：python3 scripts/build_runner_component_package.py --output-dir <tmp>
  9. 跑门禁：
     - verify_upgrade_package_identity.py <平台包>
     - verify_runner_delivery_consistency.py --package <runner 包>
     - 包内敏感文件扫描
 10. 构建离线交付目录：build_offline_delivery.py（需要基线 runner 镜像，见 5.3）
 11. 归档：产物复制到 cli/packages/archive/<日期>/，更新 cli/packages/latest/
 12. 打印产物清单 + SHA256 + 后续动作提示
```

### 5.2 为什么第 6 步（版本一致性预检）必要

本项目已发生过真实事故：**平台包基线必须落在已发布 runner v0.3.1**，而源码 compose 写 v0.3.2。
`verify_runner_delivery_consistency.py` 的 C1/C3 能查出来，但它在第 9 步才跑——
**在跑完整门禁前就失败，比跑完再失败快**。预检只查最基础的三项，给早期反馈。

### 5.3 一个已知限制：基线 runner 镜像（必须如实告知用户）

`build_offline_delivery.py` 需要 `--runner-baseline`（已发布 runner 的镜像 tar），
它**不在仓库里**（是发布产物）。`package.sh` 的处理：

- 若本机 `docker images` 已有该基线镜像 → `docker save` 临时导出，用完清理；
- 若没有 → **明确报错并给三条可选路径**（从 Release 资产下载 / 从 `.3` 已有导出目录复制 /
  跳过离线交付只出平台包与组件包），不静默失败、不自动去公网下载。

理由：静默去公网拉取是 AGENTS 明令禁止的行为（凭据与外网均需用户确认）。

## 6. `check-deps.sh` 设计

### 6.1 体检项与提示规范

每项输出三态：`OK` / `MISSING` / `WARN`，`MISSING` 必须给出**可直接粘贴执行的命令**：

| 项 | 检查方式 | 缺失提示（示例） |
| --- | --- | --- |
| 操作系统 | `uname -s` = Linux | `打包镜像需要 Linux；当前是 <X>。macOS 请用 Docker Desktop 的 Linux 容器或在 Linux 机器上执行。` |
| Docker | `docker version` | `未检测到 Docker。安装：curl -fsSL https://get.docker.com \| sh` |
| docker compose | `docker compose version` | `未检测到 docker compose（v2 插件）。安装：见 https://docs.docker.com/compose/install/` |
| Docker 守护进程 | `docker info` | `Docker 守护进程未运行。启动：sudo systemctl start docker` |
| Python 3 | `python3 --version` ≥ 3.11 | `需要 Python 3.11+；当前 <X>。安装：sudo yum install -y python3`（按发行版给） |
| git | `git --version` | `未检测到 git。安装：sudo yum install -y git` |
| 磁盘空间 | 可用 ≥ 20 GB | `可用空间 <X> GB，不足。构建需约 20 GB。清理：docker system prune`（**提示而非自动执行**） |
| 仓库状态 | `.git` 存在 | `当前目录不是 git 仓库。克隆：git clone <url>` |
| 基线 runner 镜像 | `docker images` | 见 §5.3 |

**文案规范**：中文、给命令、不用行话、不说「请确保」这种无法执行的表述。

### 6.2 退出码约定

- `0` = 全部 OK（可能有 WARN）
- `2` = 有 MISSING（阻断）
- 与 `package.sh` 共用，便于单独诊断

## 7. `cli/README.md` 设计

结构（面向「刚 clone 的人」）：

1. **一句话**：这是什么、干什么用。
2. **选哪个脚本**：三行表格（我想装 / 我想升级 / 我想打包 → 对应命令）。
3. **前置条件**：Docker、Linux、权限（都要 root 或 sudo）。
4. **三个脚本的完整用法与参数**。
5. **常见失败与处理**（从既有 findings 提炼：`.env` 权限、prometheus 目录权限、只读挂载、单飞守卫 400、
   US-28 锁窗口、`database is locked` 503）。
6. **产物在哪**：`cli/packages/` 结构说明。

## 8. 测试计划

| # | 用例 | 环境 | 通过判据 |
| --- | --- | --- | --- |
| T1 | `check-deps.sh` 在**缺依赖的裸机**上运行 | 干净 VM（无 Docker） | 退出码 2，且每项 MISSING 都带可执行命令 |
| T2 | `package.sh --branch dev2` 端到端 | `.3` | 出平台包 + runner 包 + 交付目录；门禁全 PASS；产物落 `cli/packages/latest/` |
| T3 | 分支保护 | `.3` | 不带 `--branch` 默认 `main`；`--branch dev2` 能打出开发线包并在输出中标明分支 |
| T4 | 破坏性确认 | `.3` | 有本地改动时不给 `--yes` 会中止并提示 |
| T5 | `cli/install.sh` 薄封装 | `.14` 干净 VM | 与 `delivery/install/install.sh` 行为一致（同一份逻辑） |
| T6 | `cli/upgrade.sh` 薄封装 | `.14` | 断网升级通过 + 8 项验收全过 |
| T7 | 依赖缺失不自动装 | T1 | 全程无 `yum/apt install` 等安装动作 |
| T8 | 幂等 | `.14` | 重复 `cli/install.sh` 不覆盖 `.env`、不重建容器 |

**不可省的实测**：T5/T6 必须在**干净 VM 形态**上跑（`.14` 满足），因为它们直接决定客户路径。

## 9. 边界与回滚

- **改动范围**：新增 `cli/` 目录（6 个文件 + 1 个 lib）；**不改** `delivery/` 任何文件；
  不改 `scripts/build_*.py`（若需适配，只允许加**可选参数**，默认行为不变）。
- **回滚**：`git revert` 序 4 的提交即可，`cli/` 是纯新增目录，删掉不影响任何既有链路。
- **风险**：`cli/install.sh` 薄封装若写错路径会**遮蔽**已验证的 `delivery/` 脚本 →
  用 T5 兜底，且薄封装只做「定位 + exec + 参数透传」三件事，不加逻辑。

## 10. 与既有治理的一致性

- 交付物 compose 必须落**已发布 runner 基线**（`docs/version-governance.md`）：`package.sh` 第 6 步预检 +
  第 9 步门禁双重保证。
- 脚本不得包含 `.env` / 凭据 / 数据库（`docs/ova-delivery.md`、`verify_release_docs_safe.py`）：
  `cli/` 只做编排，不新增任何密钥。
- 升级**只走 API**（task_plan #56 用户已定 Q1 = 走 API）：`cli/upgrade.sh` 薄封装透传，不改路线。
- 依赖缺失**只提示不自动装**（Q5）：与 AGENTS §5「宿主不做未经确认的变更」一致。

## 11. 实施顺序

1. `cli/lib/common.sh` + `cli/check-deps.sh` → 立即可测（T1、T7）
2. `cli/package.sh` → T2、T3、T4
3. `cli/install.sh` + `cli/upgrade.sh` 薄封装 → T5、T6、T8
4. `cli/README.md` + `cli/packages/` 与 `.gitignore`
5. 全部进 `.3` 门禁；更新 `pending-tasks` #58、`progress.md`、`docs/doc-map.md`
