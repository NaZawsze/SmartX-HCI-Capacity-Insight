# SmartX HCI Capacity Insight

简体中文 | [English](README.md)

版本：`v0.5.4`

> 状态：项目处于测试阶段，生产使用前请先在目标环境中完成验证。

SmartX HCI Capacity Insight 是面向 SmartX 超融合基础设施的存储容量监控与预测平台。它从 CloudTower/Tower 只读采集数据中心、集群、虚拟机和虚拟卷的容量数据，提供容量总览、虚拟机存储趋势、增长榜和集群预测报表。

> 本项目在 AI 辅助下开发。

## 功能特性

- 多 Tower、多集群容量总览。
- 定时采集与手动采集。
- 虚拟机存储趋势支持 7、14、30、90、180、365 天，展示当前卷和全部卷详情。
- 日/月增长榜，可按增长量或增长比例排序。
- 集群预测报表，联动集群容量趋势图。
- Word 和 Excel 报表导出，支持全部集群、单个 Tower 或单个集群，历史窗口可选 7、14、30、90、180、365 天。
- 报表页和导出文件包含数据质量说明：实际采集窗口、缺失日期、样本充足度和不完整集群。
- Tower 级采集状态，只读接入 CloudTower。

## 界面预览

### 概览页

![概览页](docs/assets/dashboard-overview.png)

### 虚拟机存储趋势

![虚拟机存储趋势](docs/assets/vm-storage-trend.png)

### 预测报表

![预测报表](docs/assets/forecast-report.png)

### Tower 设置

![Tower 设置](docs/assets/tower-settings.png)

## 架构

```text
CloudTower/Tower
      |
      v
collector-worker ----> SQLite (/data/smartx.db)
      |                    |
      v                    v
Prometheus <---------- web-api (FastAPI)
                           |
                           v
frontend (React + TypeScript + ECharts)
```

平台运行五个容器：`web-api`、`collector-worker`、`frontend`、`prometheus` 和 `upgrade-runner`。各容器的职责、端口和数据目录见[部署指南](docs/deployment.zh-CN.md)。

## 快速开始

安装**只有一个入口：`install.sh`**（自动判定形态与在线/离线模式）。按你的场景任选其一：

| 你的场景 | 做法 |
| --- | --- |
| **服务器可联网**，从源码装 | `git clone` 本仓库 → 仓库根执行 `sudo bash install.sh --yes`（在线模式，自动 pull 镜像） |
| **离线服务器**，已有交付包 | 校验交付包 SHA256 后 `tar -xzf smartx-capacity-insight-v0.5.4-offline.tar.gz` → 进入目录执行 `sudo bash install/install.sh --yes`（离线模式，自带镜像） |
| **只有镜像 tar**、没有交付包 | 镜像 tar 与本仓库同处一目录 → `sudo bash install.sh --mode offline --images <tar 目录> --yes`。tar 必须覆盖 compose 声明的 tag：`web-api`/`collector-worker`/`frontend` `v0.5.4`、`upgrade-runner` `v0.3.2`、`prom/prometheus` `v2.55.1` |

然后打开 `http://<服务器IP>:8080`，使用 `admin` / `password` 登录，并立即修改口令。

端口：Web 界面 `8080`，API `8000`，Prometheus `9090`。

环境要求、镜像说明和验证步骤见[部署指南](docs/deployment.zh-CN.md)；交付包的组成与升级见[离线交付说明](delivery/README.md)。

开发环境从源码构建并启动（仅用于开发，不用于部署）：

```bash
cp .env.example .env
# 设置 SMARTX_SECRET_KEY、SMARTX_CREDENTIAL_KEY 和 SMARTX_ADMIN_PASSWORD
sudo ./pre_install.sh
docker compose -f docker-compose.dev.yml up -d --build
```

## 升级

使用离线交付包中的 `upgrade/upgrade.sh`，不要手工加载镜像或重启服务。

v0.5.4 的升级分两步，顺序固定：**先升级 runner 组件，再升级平台**。完整流程和支持的源版本见[离线交付说明](delivery/README.md)。

## 文档

- [部署指南](docs/deployment.zh-CN.md) / [English](docs/deployment.md)
- [运维操作脚本](ops/README.md) —— 开发用 `install.sh` 转发、`upgrade.sh`、`package.sh`
- [离线交付说明](delivery/README.md) —— 安装、升级、自检和常见失败处理
- [使用说明](docs/usage.md)
- [API 参考](docs/api.md)
- [故障排查](docs/troubleshooting.md)
- [备份与恢复](docs/backup-recovery.md) —— 备份资产、恢复步骤和红线
- [OVA 交付说明](docs/ova-delivery.md)
- [版本更新说明](docs/releases/CHANGELOG.md)
- [upgrade-runner 生命周期](docs/upgrade-runner-lifecycle.md)

数据迁移包必须与恢复密钥（`.env`）成对保存。缺少密钥时，已加密的 Tower 凭据无法恢复。详见使用说明第 11 节。

## CloudTower 兼容范围与权限

- 请使用只读的 CloudTower 账号或只读 API Token。
- CloudTower 必须提供以下 v2 HTTP API：

```text
POST /v2/api/login
GET  /v2/api/get-version
POST /v2/api/get-clusters
POST /v2/api/get-cluster-storage-info
POST /v2/api/get-vms
POST /v2/api/get-vm-volumes
```

- 要求 CloudTower/Tower 4.4.0 及以上。CloudTower 4.4.x 不提供 `get-cluster-storage-info`，平台会回退读取 `get-clusters` 中的容量字段。

## 重置密码

在目标服务器上执行：

```bash
cd /data/smartx-storage-forecast/project
docker compose exec web-api python -m app.cli reset-password --username admin
```

如需非交互执行，追加 `--password <新口令>`。重置后使用新口令重新登录。

## 安全说明

- 不要将 `.env`、SQLite 数据库、Prometheus 数据、备份、导出文件和 Tower 凭据提交到 Git。
- 使用只读的 CloudTower 凭据。
- 生产网络应限制对 `8000`、`8080`、`9090` 端口的访问。
- 生产使用前替换默认密钥和管理员口令。

## 开发

```text
backend/       FastAPI API、采集器、CloudTower 客户端、预测逻辑和 CLI
frontend/      React + TypeScript 前端
prometheus/    Prometheus 抓取配置
install.sh     统一安装入口（在线/离线自动判定）
ops/           开发用打包与运维入口
scripts/       构建与校验工具
delivery/      离线交付物料源文件
docs/          部署、使用、API 和运维文档
```

运行测试：

```bash
cd backend && pytest
```

```bash
cd frontend && npm test
```

## 许可证

MIT License.
