# 部署指南

简体中文 | [English](deployment.md)

版本：`v0.5.4`

本指南覆盖全新部署。已有部署的升级请看[升级指南](upgrade.md)；离线交付包内也自带 README，写明该包专属的升级步骤。

## 1. 前提条件

### 服务器

- Linux 服务器（已在 openEuler、Debian 13、CentOS/RHEL 8+ 验证）。
- `root` 或 `sudo` 权限。
- Docker Engine 20.10 及以上，且带 Compose V2 插件（`docker compose version` 能出版本号）。
- 建议：4 核 CPU、8 GiB 内存。
- 磁盘：至少 3 倍交付包体积 + 10 GiB 可用空间，且落在存放数据根目录的文件系统上。所有运行数据保存在 `/data/smartx-storage-forecast`。

### 网络与端口

- 端口 `8080`（Web 界面）、`8000`（API）、`9090`（Prometheus）必须空闲。
- 服务器必须能访问 CloudTower/Tower。
- 离线部署不需要外网：镜像全部在交付包里。在线部署需要能访问 Docker Hub。

### CloudTower

- 使用只读 CloudTower 账号或只读 API token。
- CloudTower 实例必须提供以下 v2 HTTP API：

```text
/v2/api/login
/v2/api/get-clusters
/v2/api/get-cluster-storage-info
/v2/api/get-vms
/v2/api/get-vm-volumes
```

- 对 CloudTower 具体小版本无要求，只要这些接口可达并返回预期数据即可。

## 2. 会装什么

平台在 Docker 网络 `smartx-hci-capacity-insight-net`（`10.249.251.0/24`，由 Compose 自动创建）中运行五个容器：

| 容器 | 镜像 | 职责 | 端口 |
| --- | --- | --- | --- |
| `web-api` | `nazawsze/smartx-hci-capacity-insight-web-api:v0.5.4` | FastAPI 后端：鉴权、业务查询、报表、数据迁移、升级入口。 | `8000` |
| `collector-worker` | `nazawsze/smartx-hci-capacity-insight-collector-worker:v0.5.4` | 定时/手动采集 Tower 数据；最新状态写 SQLite，并在网络内 `9108` 暴露指标。 | 不对外 |
| `frontend` | `nazawsze/smartx-hci-capacity-insight-frontend:v0.5.4` | React 界面，Nginx 静态服务。 | `8080` → `80` |
| `prometheus` | `prom/prometheus:v2.55.1` | 保存容量历史时序，支撑趋势、增长与预测报表。保留 400 天。 | `9090` |
| `upgrade-runner` | `nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.2` | 在 `web-api` 之外执行平台升级、组件升级、备份、健康检查与回滚。 | 不对外 |

runner tag 说明：`v0.3.2` 是仓库/在线安装形态的 tag。离线交付包的安装 compose 固定为该批次**已发布 runner 基线**（v0.5.4 批次 = `v0.3.1`），随后用 `upgrade/packages/` 里随包组件包升级；细节见交付包 README。

### 2.1 数据目录

所有持久化数据都在 `/data/smartx-storage-forecast` 下：

| 目录 | 内容 |
| --- | --- |
| `project/` | Compose 文件、Prometheus 配置和 `.env`。 |
| `app/` | SQLite 业务库（`smartx.db`）。 |
| `prometheus/` | Prometheus 历史时序。 |
| `upgrades/` | 上传的升级包和升级任务状态。 |
| `backups/` | 升级与导入备份。 |
| `exports/` | 报表导出与数据迁移文件。 |
| `compose-runtime/` | 升级中心生成的运行时 Compose 覆盖。 |

安装器（源码构建路径用 `pre_install.sh`）负责创建这些目录并设好属主。**容器运行期间不要删除或移动它们**——挂载载体附着在目录 inode 上，删/移会拆掉全机在用挂载。

## 3. 部署步骤

部署只有**一个安装入口：`install.sh`**。它自动判定来源形态与获取方式：

| 形态 | 判定依据 | 默认模式 |
| --- | --- | --- |
| 交付包 | 脚本旁存在 `images/` 与 `project/` | 离线（校验 SHA + 加载随包镜像） |
| 仓库 clone | 仓库根存在 `docker-compose.offline.yml` / `docker-compose.online.yml` | 在线（`docker pull` compose 声明的 tag） |
| 外部镜像目录 | `--images <tar 目录>` | `--mode offline` |

同一个真身脚本有三处入口：

| 拿到方式 | 命令 | 典型用户 |
| --- | --- | --- |
| 离线交付包 | `install/install.sh` | 无外网的客户现场 |
| 仓库 clone（根） | `install.sh` | 能访问 Docker Hub 的服务器 |
| `ops/install.sh`（仓库内） | 转发到根安装器 | 开发迭代场景 |

### 3.1 从离线交付包安装（客户现场推荐）

```bash
tar -xzf smartx-capacity-insight-v0.5.4-offline.tar.gz   # 若拿到的是已解开的目录则跳过
cd smartx-capacity-insight-v0.5.4-offline
sudo bash install/install.sh --yes
```

一条命令完成全部：root/Docker/端口/磁盘预检查、镜像 SHA 校验、加载五个镜像、创建数据目录、生成带两个随机密钥的 `.env`、启动栈、等待健康检查。

规则：

- 不要修改交付包内文件；安装器每次运行都会校验校验和。
- 装完的完成提示里就有两步升级提示——之后升级按它走（先 runner 组件、后平台），详见[升级指南](upgrade.md)。

安装时自定义初始管理员账号：

```bash
sudo bash install/install.sh \
  --admin-user admin \
  --admin-password '<初始密码>' \
  --yes
```

### 3.2 在线安装（能上网的服务器，无需交付包）

```bash
git clone https://github.com/NaZawsze/SmartX-HCI-Capacity-Insight.git
cd SmartX-HCI-Capacity-Insight
sudo bash install.sh --yes
```

`.env` 由安装器生成（两个随机密钥 + 初始管理员密码），不需要手工 `cp .env.example` 或跑 `pre_install.sh`。

安装器从 Docker Hub 拉取 compose 声明的镜像，逐个校验 tag 后启动。所需 tag：平台 `v0.5.4` 镜像（`web-api`/`collector-worker`/`frontend`）、runner `v0.3.2` 镜像和 `prom/prometheus:v2.55.1`。

在**不能访问 Docker Hub** 的目标机上安装时，先在任意联网机器上准备**这五个 tag** 的 tar：

```bash
for t in web-api:v0.5.4 collector-worker:v0.5.4 frontend:v0.5.4 upgrade-runner:v0.3.2; do
  docker pull "nazawsze/smartx-hci-capacity-insight-$t"
done
docker pull prom/prometheus:v2.55.1
docker save nazawsze/smartx-hci-capacity-insight-web-api:v0.5.4 > web-api.tar
docker save nazawsze/smartx-hci-capacity-insight-collector-worker:v0.5.4 > collector-worker.tar
docker save nazawsze/smartx-hci-capacity-insight-frontend:v0.5.4 > frontend.tar
docker save nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.2 > upgrade-runner.tar
docker save prom/prometheus:v2.55.1 > prometheus.tar
```

把五个 tar 加上仓库根 `install.sh`（或整个 clone 仓库）传到目标机后执行：

```bash
sudo bash install.sh --mode offline --images /path/to/tars --yes
```

### 3.3 源码构建（仅开发）

```bash
cp .env.example .env
# 编辑 .env 中的密钥
sudo ./pre_install.sh
docker compose -f docker-compose.dev.yml up -d --build
```

不要用于生产。

### 3.4 验证部署

检查 API 健康接口：

```bash
curl -s http://127.0.0.1:8000/api/system/health
```

返回必须包含 `"ok": true`、`"version": "v0.5.4"`、`"runner_version": "v0.3.1"`（离线交付包首装），且 `checks` 下的 `directories`、`database`、`prometheus` 三项均为 `true`。离线交付包全新安装时 runner 以**已发布基线 `v0.3.1`** 运行；任何平台升级之前，先用 `upgrade/packages/` 里随包的 runner 组件包在 Web 界面完成一次组件升级（服务管理 → 组件升级），完成后 health 返回 `"runner_version": "v0.3.2"`。

检查容器：

```bash
docker ps --filter name=smartx-hci
```

五个容器必须全部 `Up`，其中 `upgrade-runner` 是 `(healthy)`。

### 3.5 首次配置

1. 打开 `http://<服务器IP>:8080`，用 `admin` / 初始密码登录，**立即修改管理员口令**（默认口令是公开的）。
2. 「设置」里添加 Tower：名称、URL、凭据或 API token，勾选 TLS 校验后测试连接。
3. 选择要采集的集群并保存配置。
4. 在仪表盘触发一次手动采集并确认成功。
5. 在仪表盘和虚拟机页面确认出现集群容量与虚拟机数据。

定时采集跟随每个 Tower 自己的间隔，默认 60 分钟。

## 4. 安装常见失败

| 现象 | 原因 | 处置 |
| --- | --- | --- |
| 提示「无法识别安装环境」 | 脚本被单独拷出交付包/仓库上下文 | 在解包后的 `install/` 内运行，或从仓库 clone 根运行 |
| 镜像 SHA256 校验未通过 | 包内文件被改动或传输截断 | 重新传输交付包，并对 SHA256SUMS |
| 磁盘空间不足 | `--install-root` 所在文件系统（默认 `/`）容量不够 | 腾空间，或用 `--install-root` 指到更大文件系统 |
| 端口被占用 | `8080`/`8000`/`9090` 被其它服务占用 | 释放端口或停掉占用服务 |
| docker 守护未运行 | Docker 未启动或无权限 | 启动 Docker / 以 root 运行 |
| 复跑提示存在已装环境、不做改动 | 幂等保护：已有现存安装 | 正常行为；保留现有 `.env` 与运行栈 |

## 5. 升级

平台批次延续离线交付包的方式：若该批次附带新 runner 组件包，则**先组件升级、后平台升级**，顺序不能颠倒。完整流程、支持的源版本、升级后检查与回滚见[升级指南](upgrade.md)。

交付包内 README 也带该包专属升级步骤与随包 `upgrade/packages/` 里的组件包/平台包清单。

## 6. 大操作前先备份

升级或大改布局之前，先做可校验备份；至少冷拷贝 `/data/smartx-storage-forecast/app/smartx.db` 加配对 `.env`。**成对保存**最关键：迁移/导出包没有配对 `.env` 时，加密的 Tower 凭据无法恢复。详见[备份与恢复](backup-recovery.md)。

## 7. OVA 部署

> OVA 尚未正式发布。以下流程以待发布后为准。

OVA 是开箱即用的虚拟机模板，用于全新部署和演示环境；它不是升级包，不允许上传到服务管理的升级页。

1. 把 OVA 导入 Tower 并开机。
2. 镜像预装 SmartXTools；虚拟机启动后直接在 Tower 设置 IP 地址与系统口令，无需控制台登录。
3. 打开 `http://<虚拟机IP>:8080`，用初始管理员账号（`admin` / `password`）登录，**立即修改密码**。
4. 「设置」里添加 Tower/CloudTower 连接并触发一次手动采集确认可采。

## 8. 卸载

卸载会删除全部业务数据与历史。有任何需要保留的东西先备份。

```bash
cd /data/smartx-storage-forecast/project
docker compose -f docker-compose.offline.yml --env-file .env down   # 不要 down -v
rm -rf /data/smartx-storage-forecast        # 仅在栈已停止后执行
```

禁止 `docker compose down -v`。
