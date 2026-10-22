# 部署指南

简体中文 | [English](deployment.md)

版本：`v0.5.4`

本指南说明 SmartX HCI Capacity Insight 的全新部署。版本升级使用离线交付包中的 `upgrade/upgrade.sh`，升级流程见交付包内的 README。

## 1. 环境要求

### 服务器

- Linux 服务器（已在 openEuler、Debian 13、CentOS/RHEL 8+ 系列验证）。
- `root` 或 `sudo` 权限。
- Docker Engine 20.10 及以上，并安装 Compose V2 插件（`docker compose version` 必须有输出）。
- 建议 4 核 CPU、8 GiB 内存。
- 磁盘：至少为交付包大小的 3 倍，并额外预留 10 GiB。运行数据存储在 `/data/smartx-storage-forecast`。

### 网络与端口

- 端口 `8080`（Web 界面）、`8000`（API）、`9090`（Prometheus）必须空闲。
- 服务器必须能够访问 CloudTower/Tower。
- 离线部署不需要外网：镜像全部包含在交付包中。在线部署需要能够访问 Docker Hub。

### CloudTower

- 请使用只读的 CloudTower 账号或只读 API Token。
- CloudTower 必须提供以下 v2 HTTP API：

```text
/v2/api/login
/v2/api/get-clusters
/v2/api/get-cluster-storage-info
/v2/api/get-vms
/v2/api/get-vm-volumes
```

- 只要这些接口可用且返回结构符合预期，不要求特定的 CloudTower 小版本。

## 2. 容器说明

平台在 Docker 网络 `smartx-hci-capacity-insight-net`（`10.249.251.0/24`）中运行五个容器。

| 容器 | 镜像 | 作用 | 端口 |
| --- | --- | --- | --- |
| `web-api` | `nazawsze/smartx-hci-capacity-insight-web-api:v0.5.4` | FastAPI 后端：登录鉴权、业务查询、报表、数据迁移和升级入口。 | `8000` |
| `collector-worker` | `nazawsze/smartx-hci-capacity-insight-collector-worker:v0.5.4` | 定时及手动从 Tower 采集数据，将最新状态写入 SQLite，并在 Docker 网络内通过 `9108` 暴露指标。 | 不对外发布 |
| `frontend` | `nazawsze/smartx-hci-capacity-insight-frontend:v0.5.4` | React Web 界面，由 Nginx 提供静态服务。 | `8080` → `80` |
| `prometheus` | `prom/prometheus:v2.55.1` | 保存容量历史时序，供趋势、增长和预测报表使用。数据保留 400 天。 | `9090` |
| `upgrade-runner` | `nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.2` | 在 `web-api` 之外执行平台升级、组件升级、备份、健康检查和回滚。 | 不对外发布 |

### 2.1 数据目录

所有持久化数据都存放在 `/data/smartx-storage-forecast`：

| 目录 | 内容 |
| --- | --- |
| `project/` | Compose 文件、Prometheus 配置和 `.env`。 |
| `app/` | SQLite 业务数据库（`smartx.db`）。 |
| `prometheus/` | Prometheus 时序数据块。 |
| `upgrades/` | 上传的升级包和升级任务状态。 |
| `backups/` | 升级和导入产生的备份。 |
| `exports/` | 报表导出和数据迁移文件。 |
| `compose-runtime/` | 升级中心生成的运行时 Compose 覆盖文件。 |

`pre_install.sh` 会创建这些目录并设置所需属主。容器运行期间不要删除或移动这些目录。

## 3. 部署步骤

### 3.1 离线交付包安装（推荐）

解压交付包并以 root 运行安装脚本：

```bash
tar -xzf smartx-capacity-insight-v0.5.4-offline.tar.gz
cd smartx-capacity-insight-v0.5.4-offline
sudo bash install/install.sh
```

安装脚本会依次检查 root 权限、Docker、磁盘空间和端口，校验镜像 SHA256，加载五个镜像，创建数据目录，生成包含两把随机密钥的 `.env`，启动服务，并等待健康检查通过。

不要修改交付包内的文件；安装脚本每次运行都会校验其 SHA256。

安装时指定初始管理员账号：

```bash
sudo bash install/install.sh \
  --admin-user admin \
  --admin-password '<初始口令>' \
  --yes
```

### 3.2 在线安装

创建环境配置文件：

```bash
cp .env.example .env
```

至少修改以下配置：

```text
SMARTX_SECRET_KEY=<长随机密钥>
SMARTX_CREDENTIAL_KEY=<另一把长随机密钥>
SMARTX_ADMIN_PASSWORD=<初始口令>
```

然后初始化数据目录并启动服务：

```bash
chmod 600 .env
sudo ./pre_install.sh
docker compose -f docker-compose.online.yml up -d
```

该方式会从 Docker Hub 拉取平台镜像 `v0.5.4`、执行器镜像 `v0.3.2` 和 `prom/prometheus:v2.55.1`。

### 3.3 源码构建（仅开发环境）

```bash
cp .env.example .env
# 修改 .env 中的密钥和口令
sudo ./pre_install.sh
docker compose -f docker-compose.dev.yml up -d --build
```

不要在生产环境使用该方式。

### 3.4 验证部署

检查 API 健康状态：

```bash
curl -s http://127.0.0.1:8000/api/system/health
```

返回内容必须包含 `"ok": true`、`"version": "v0.5.4"`、`"runner_version": "v0.3.2"`，且 `checks` 下的 `directories`、`database`、`prometheus` 三项均为 `true`。

检查容器：

```bash
docker ps --filter name=smartx-hci
```

五个容器必须全部为 `Up`。

打开 `http://<服务器IP>:8080`，使用 `admin` 和初始口令登录，并立即修改口令。

完成首次配置：

1. 进入“设置”，添加 Tower：填写名称、地址、账号口令或 API Token，保持 TLS 校验开启，并测试连接。
2. 选择需要采集的集群并保存。
3. 在仪表盘手动触发一次采集，确认采集成功。
4. 确认仪表盘和虚拟机页面已显示集群容量与虚拟机数据。

定时采集按每个 Tower 自身的采集间隔执行，默认 60 分钟一次。

## 4. OVA 部署

> OVA 尚未发布，以下步骤在 OVA 正式发布后适用。

OVA 是用于全新部署和演示环境的整机虚拟机模板，不是升级包，不能上传到服务管理页的升级中心。

1. 在 Tower 中导入 OVA，并启动虚拟机。
2. 镜像已预装 SmartXTools。虚拟机启动后，可直接在 Tower 平台修改虚拟机 IP 地址和系统账号密码，无需登录控制台。
3. 打开 `http://<虚拟机IP>:8080`，使用初始管理员账号（`admin` / `password`）登录，并立即修改平台管理员口令。
4. 进入“设置”，添加 Tower/CloudTower 连接，然后手动触发一次采集，确认数据正常。

OVA 不包含生产 `.env`、SQLite 业务库、Prometheus 历史数据、备份、导出文件或 Tower 凭据。导入前请校验随 OVA 提供的 SHA256。
