# 运维操作工具

命令行下的**安装、升级、打包**。三个入口都在这里。

## ⚠ 先看这条：客户用哪个，开发用哪个

两套脚本，**不是一回事**，用错会失败：

| 你是谁 | 用哪个 | 为什么 |
| --- | --- | --- |
| **客户 / 离线环境** | 交付目录里的 `install/install.sh`、`upgrade/upgrade.sh` | 交付目录**自包含**：带 `images/`、`project/`、`packages/`。客户手上只有这份，不需要仓库 |
| **本项目开发者 / 运维** | 本目录的 `install.sh`、`upgrade.sh` | 只有仓库、没交付目录时用。它会先定位（或提示你打包出）交付物料，再转发 |

**关键**：`delivery/install/` 在仓库里**只有 `install.sh` 一个文件**，没有 `images/` 和 `project/`。
那些是 `ops/package.sh` 打包时生成的产物（1.1 GB），不可能进 git。
所以在仓库里直接跑 `delivery/install/install.sh` **必然失败**（报「找不到镜像目录」）。

三个脚本都能 `--help`。不确定选哪个就看下表。

| 我要做的事 | 跑哪个 | 前置 |
| --- | --- | --- |
| **打包**（出交付物给客户/发布用） | [`package.sh`](#3-打包packagesh) | Linux + Docker + Python 3.11+ + git |
| 在**本机**装一套环境（开发者） | [`install.sh`](#1-安装installsh) | Linux + Docker + root；无交付物料时需先打包 |
| 把**本机已有环境**升级（开发者） | [`upgrade.sh`](#2-升级upgradesh) | 同上 |
| **客户安装** | 交付目录的 `install/install.sh` | 交付目录（自包含） |
| **客户升级** | 交付目录的 `upgrade/upgrade.sh` | 交付目录（自包含） |

---

## 前置条件

所有脚本都需要：

- **Linux**（macOS/Windows 需在 Linux 机器或 Docker 的 Linux 容器里跑）
- **Docker** 且 **docker compose v2**（`docker compose`，不是已废弃的 `docker-compose`）
- 安装/升级需要 **root** 或 `sudo`

打包额外需要：**Python 3.11+**、**git**、**约 20 GB 可用磁盘**。

不确定环境是否满足？先跑体检：

```bash
bash ops/check-deps.sh
```

它会逐项告诉你缺什么、**以及怎么装**。它**不会替你装任何东西**——在客户机器上自动装系统包太危险，这个决定留给你自己。

---

## 1. 安装（`install.sh`）

**开发者/运维**在开发机装一套环境。客户请用交付目录的 `install/install.sh`（见文首表格）。

```bash
git clone https://github.com/NaZawsze/SmartX-HCI-Capacity-Insight.git
cd SmartX-HCI-Capacity-Insight
# 若还没有交付物料，先打包一个（见第 3 节）
bash ops/package.sh
sudo bash ops/install.sh
```

脚本会依次尝试 `delivery/install/`、`ops/packages/latest/offline-delivery/install/`，
找到含 `images/` 与 `project/` 的那个就转发过去；都没有则明确告诉你先打包。

装完检查：

```bash
curl -s http://127.0.0.1:8000/api/system/health
docker ps --filter name=smartx-hci   # 应有 5 个容器
```

浏览器打开 `http://<本机IP>:8080`，用 `admin` / `password` 登录。

幂等：重复执行不会覆盖已有 `.env`、不会重建容器。

## 2. 升级（`upgrade.sh`）

**开发者/运维**升级本机环境。客户请用交付目录的 `upgrade/upgrade.sh`。

```bash
sudo bash ops/upgrade.sh --yes
# 或指定包 + 连带升级 runner
sudo bash ops/upgrade.sh --yes \
  --package <平台包路径> \
  --with-runner <runner 组件包路径>
```

**升级顺序：先平台，后 runner。** 顺序颠倒（旧平台的 web-api 会停掉刚启动的新 runner）会导致升级中断。只有平台明确要求更高 runner 能力时才例外。

`--with-runner` 会**先等升级后清理（post-cleanup）收敛**再升级 runner，避免被"同一时刻只允许一个升级任务"的守卫拒绝。

升级**只走平台自己的 API**——不直接改 Docker、不手工改文件。

## 2.1 升级取证（`evidence.sh`）

矩阵验证（`.12` / `.14`）用的**一键取证**：升级前后各跑一次，自动生成可比对的证据包与判定表。

```bash
# 升级前（用户执行升级动作之前）
sudo bash ops/evidence.sh c1 before

# 升级后（用户执行完升级之后）
sudo bash ops/evidence.sh c1 after --task-id <upgrade-xxxx> --token <access_token>
```

| 参数 | 说明 |
| --- | --- |
| `<cell>` | `c1`（`.14` 平台直升）| `c2`（`.12` 组件升级）| `c3`（`.14` 场景 B 手动回滚）| `c4`（`.12` 平台直升） |
| `before` / `after` | 基线快照 / 采集 + **逐条判定表** |
| `--task-id` | 升级任务 ID（`after` 用来取差异清单、锚点、回滚记录、precheck remediation） |
| `--token` | 管理员 access_token（`c3` 取可回滚性判定用） |

输出：`/data/evidence/<cell>/{before,after}/`（10 个文本证据 + `SHA256SUMS`）与
`/data/evidence/<cell>/judgement.txt`（判定表：容器 ID 是否不变【T3】、计数是否一致、
版本是否到位、`.env` 指纹、US-37 标记、legacy 路径、SQLite 完整性、差异清单/锚点）。

纪律：**只读**，唯一写路径是它自己的证据目录；容器只按已知服务名拼出的**显式名字**枚举，
不做过滤扫描（`.3` 两次容器误删事故的形态）；离线可用，root 直登。
判据表见 [docs/superpowers/plans/2026-10-06-upgrade-matrix-runbook.md](../docs/superpowers/plans/2026-10-06-upgrade-matrix-runbook.md)。

## 3. 打包（`package.sh`）

出一份可交付的升级包。

```bash
git clone https://github.com/NaZawsze/SmartX-HCI-Capacity-Insight.git
cd SmartX-HCI-Capacity-Insight
bash ops/package.sh                    # 打包 main（发布线）
bash ops/package.sh --branch dev2      # 打包开发线
```

它会：同步代码 → 体检依赖 → 版本一致性预检 → 构建平台包 + runner 组件包 → 跑三道门禁 → 归档。

> ### ⚠️ 分支要选对
> 本项目 **`main` 是发布线**（客户用的版本），**`dev2` 是开发线**（可能有问题）。
> 默认是 `main`。**打开发线包发给客户是事故**——显式确认分支。

### 产物在哪

```
ops/packages/
├── latest/                 ← 最新可用（推荐交付这个）
│   ├── smartx-capacity-insight-upgrade-v0.5.3.tar.gz
│   ├── smartx-upgrade-runner-v0.3.2.tar.gz
│   ├── SHA256SUMS
│   └── offline-delivery/   ← 完整离线交付目录（有基线 runner 镜像时才有）
│       ├── install/        # 安装物料（镜像归档 + install.sh）
│       ├── upgrade/        # 离线升级物料（升级包 + upgrade.sh）
│       └── README.md
└── archive/YYYYMMDD-HHMMSS/   ← 历史归档，保留最近 5 份
```

`ops/packages/` **不入 git**，产物靠本机留存。换机器要自己传。

### 打包之后：怎么交给客户

> 完整流程（含打给客户前的自检、交付话术、禁发清单、客户怎么用）见
> **[交付手册 `docs/delivery-handover-guide.md`](../docs/delivery-handover-guide.md)**。

一句话版：

```bash
# 1. 打给客户前自检（三项，详见交付手册）
cd ops/packages/latest/offline-delivery
(cd install/images && sha256sum -c SHA256SUMS)          # 镜像完整
grep -A6 'upgrade-runner:' install/project/docker-compose*.yml | grep image:  # tag 必须是已发布基线
find . -name ".env" -o -name "*.db"                     # 应无输出

# 2. 只把这一个目录给客户（自包含），压缩并生成校验值
cd ops/packages/latest
tar -czf smartx-capacity-insight-offline-20260930.tar.gz offline-delivery/
sha256sum smartx-capacity-insight-offline-20260930.tar.gz

# 3. 把 SHA256 值单独发给客户，并让他先读 offline-delivery/README.md
```

**不要给客户**：整个仓库、`ops/` 目录、任何真实数据（`.env` / 业务库）。

### 关于离线交付目录

`offline-delivery/` 需要**已发布的基线 runner 镜像**（如 `upgrade-runner:v0.3.1`）——它是**发布产物，不在仓库里**。缺镜像时脚本会明确告诉你，并给三条路径：

1. 从 GitHub Release 下载已发布组件包后 `docker load`
2. 从已有导出目录复制
3. 加 `--skip-offline`，只出平台包和 runner 组件包

脚本**不会**自动联网下载——凭据和外网访问都需要你自己确认。

---

## 常见失败

| 现象 | 原因与处理 |
| --- | --- |
| `Precheck` 报「另有升级任务正在执行」 | 单飞守卫：同时只能有一个升级任务。等前一个收敛，或对卡死的任务用「标记失败」 |
| 预检查报 `database is locked` / 503 | runner 刚升级完还在释放 SQLite 写锁，等约 10 秒重试即可 |
| prometheus 容器反复重启，日志 `permission denied` | `prometheus/` 目录属主不对（容器以 uid 65534 运行）：`chown 65534:65534 /data/smartx-storage-forecast/prometheus` |
| `.env` 权限不是 600 | `chmod 600 /data/smartx-storage-forecast/project/.env`（它含 Tower 凭据加密密钥） |
| runner 消失 / 预检查报「未检测到 upgrade-runner 心跳」 | 多半是把 runner 组件升级做在了平台升级**之前**。见上文「升级顺序」 |
| 任务卡在「执行中」，且 runner 已不在 | 升级中心对该任务选「标记失败」，然后重跑升级（旧环境残留由升级后清理收尾） |

更细的排查见 [`docs/troubleshooting.md`](../docs/troubleshooting.md)。

---

## 目录结构

```
ops/                     ← 本目录：只放**可执行脚本**，手册一律在 docs/
├── README.md            本文件（脚本用法）
├── install.sh           入口：安装（薄封装）
├── upgrade.sh           入口：升级（薄封装）
├── package.sh           入口：打包
├── check-deps.sh        依赖体检（可单独跑）
├── lib/common.sh        共用：日志、错误处理、确认提示
└── packages/            产物（不入 git）
```

## 相关手册（都在 `docs/`）

| 文档 | 给谁 | 什么时候看 |
| --- | --- | --- |
| [**交付手册 `delivery-handover-guide.md`**](../docs/delivery-handover-guide.md) | 交付负责人 | **打包完要交给客户时**——产物在哪、自检、交付话术、禁发清单、客户怎么用 |
| [排障手册 `troubleshooting.md`](../docs/troubleshooting.md) | 运维 | 脚本报错、服务异常、升级失败时 |
| [发版构建指南 `release-build-guide.md`](../docs/release-build-guide.md) | 开发者 | 正式发版时的构建与门禁流程 |
| [部署文档 `deployment.md`](../docs/deployment.md) | 开发者 | 架构、目录布局、升级链路设计 |
| [交付制品边界 `ova-delivery.md`](../docs/ova-delivery.md) | 开发者 | 交付物该含什么、禁含什么 |
| [开发验证流程 `development-verification-process.md`](../docs/development-verification-process.md) | 开发者 | 在测试机上跑验证时的标准做法 |

设计文档：[`docs/superpowers/specs/2026-09-30-cli-toolkit-design.md`](../docs/superpowers/specs/2026-09-30-cli-toolkit-design.md)
（该文档成文时目录名还是 `cli/`，现已改名为 `ops/`，内容与决策仍然有效）
