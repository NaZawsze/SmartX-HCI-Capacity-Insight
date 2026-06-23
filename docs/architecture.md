# SmartX HCI Capacity Insight 架构总览

更新时间：2026-06-06

本文件作为项目架构入口，记录 v2 当前交付形态、容器职责、数据职责、任务模型、升级包结构、迁移包结构和安全边界。更细的设计见：

- `docs/architecture-v2.md`
- `docs/v2-api-contracts.md`
- `docs/v2-upgrade-center-design.md`
- `docs/v1-data-compatibility.md`
- `docs/v2-frontend-design.md`

## 1. 交付形态

v2 保持 5 个容器，不拆成多个业务微服务，避免离线部署、升级包生成和现场排障复杂度上升。

| 容器 | 职责 | 对外暴露 |
| --- | --- | --- |
| `frontend` | Nginx 托管前端页面 | `8080 -> 80` |
| `web-api` | FastAPI API、鉴权、Dashboard、VM、报表、迁移、升级入口、任务查询 | 默认内部 |
| `collector-worker` | 周期采集 Tower 数据，更新 SQLite 最新状态，并向 Prometheus 暴露指标 | 内部 |
| `prometheus` | 保存容量历史时序，是趋势、增长、预测和迁移回归的数据源 | 内部 |
| `upgrade-runner` | 执行平台和 observability 升级任务，避免 `web-api` 自升级中断 | 内部 |

后续只有当报表、迁移、清理等后台任务明显影响 `web-api` 响应时，才评估新增第 6 个 `task-worker`。

## 2. 后端模块

| 模块 | 职责 |
| --- | --- |
| `auth` | 登录、token、当前用户、修改密码 |
| `inventory` | Tower、集群、VM 最新元数据、凭据加密、最新展示名称 |
| `collection` | CloudTower 连接、手动采集、定时采集、采集记录 |
| `metrics` | Prometheus 查询、指标身份、趋势和健康检查 |
| `dashboard` | 容量风险、摘要 KPI、日增长、本日新建 VM |
| `vms` | VM 列表、趋势、详情、卷信息 |
| `reports` | 预测报表、Word/Excel 导出、报表留存 |
| `migration` | 迁出、迁入、v1 兼容、导入前备份、导入后健康验证 |
| `upgrade` | 升级包解析、预检查、执行、回滚、历史 |
| `tasks` | 后台任务、步骤、日志、下载链接 |
| `system` | 服务重启、空间清理、运行目录和版本核验 |

API 层只做鉴权、参数解析和服务调用；业务规则应沉到对应模块里。

## 3. 数据职责

SQLite 保存业务元数据和最新状态：

- 用户、密码哈希。
- Tower 元数据和加密凭据。
- 集群启用状态。
- VM 最新元数据和最新展示名称。
- 结构化 VM 卷字段。
- 采集记录、任务记录、升级历史、迁移历史。

Prometheus 保存历史容量时序：

- 集群容量历史。
- VM 容量历史。
- VM 趋势、日增长、月增长、预测报表。
- 迁移导入后的历史指标回归。

VM 历史身份必须使用：

```text
tower_id + cluster_id + vm_id
```

VM 名称只用于展示。VM 改名后，页面和报表使用最新采集名称，但历史趋势仍按 UUID 维度连续。

## 4. 文件系统

运行目录统一放在宿主机 `/data` 下。

| 路径 | 用途 |
| --- | --- |
| `/data/smartx-capacity-insight-data/app` | SQLite 业务库和少量应用状态 |
| `/data/smartx-capacity-insight-data/prometheus` | Prometheus 历史 block |
| `/data/upgrades` | 升级包、解包目录、升级任务状态 |
| `/data/backups` | 升级前备份、导入前备份、项目文件备份 |
| `/data/exports/reports` | Word/Excel 报表留存 |
| `/data/exports/migrations` | 数据迁出包 |
| `/data/exports/imports` | 数据迁入上传包和解包目录 |
| `/data/exports/migration-tasks` | 数据迁出后台任务状态 |
| `/data/compose-runtime` | 升级中心生成的 compose override |

运行产物不得放回 app 业务库目录，避免备份、迁移和空间清理互相污染。

## 5. 任务模型

后台任务统一由 `tasks` 管理，覆盖：

- 报表导出。
- 数据迁出。
- 数据迁入。
- 平台升级。
- 组件升级。
- 空间清理。

任务需要记录状态、进度、步骤、小日志和下载链接。长任务必须能在页面任务中心看到当前阶段；导出类任务完成后提供服务器留存文件下载链接。

## 6. 升级包结构

v2 升级包使用统一 `.tar.gz` 格式，由 `manifest.json` 自动识别组件。平台、Runner、Prometheus 和组合包分别交付，避免一次升级误动不相关组件。

平台升级包：

```text
smartx-capacity-insight-v0.5.1-upgrade.tar.gz
├── manifest.json
├── checksums.sha256
├── release-notes.md
├── images/
│   ├── web-api.tar
│   ├── collector-worker.tar
│   └── frontend.tar
├── project/
│   ├── docker-compose.yml
│   ├── docker-compose.offline.yml
│   ├── docker-compose.release.yml
│   ├── prometheus/
│   ├── docs/
│   └── scripts/
└── migrations/
    └── run_migrations.py  # 可选，仅 migration_steps 非空时包含
```

平台包默认不带迁移脚本。若来源版本到目标版本之间存在 SQLite schema migration，manifest 会包含 `migration_steps[]`，包内只生成一个兼容 Runner v0.3.0 的 `migrations/run_migrations.py` 编排脚本。

Runner 组件包：

```text
smartx-upgrade-runner-v0.3.0.tar.gz
├── manifest.json
├── checksums.sha256
├── release-notes.md
└── images/
    └── upgrade-runner.tar
```

Prometheus 观测组件包默认是轻量包：

```text
smartx-prometheus-v2.55.1.tar.gz
├── manifest.json
├── checksums.sha256
├── release-notes.md
├── config/
│   └── prometheus.yml
└── health/
    └── queries.json
```

离线环境才额外包含：

```text
images/
└── prometheus.tar
```

平台和观测组合包：

```text
smartx-capacity-insight-bundle-v0.5.1.tar.gz
├── manifest.json
├── checksums.sha256
├── platform/
│   ├── images/
│   ├── project/
│   └── migrations/  # 可选，仅 migration_steps 非空时包含
└── observability/
    ├── config/
    ├── health/
    └── images/  # 可选，仅离线 Prometheus 镜像包包含
```

平台包和组合包默认不包含 Runner；Prometheus 历史数据不进入升级包，只在完整数据迁移包中导出。

组件类型：

- `platform`：`web-api`、`collector-worker`、`frontend`。
- `runner`：`upgrade-runner`，使用独立 runner 版本。
- `observability`：Prometheus。

未在 manifest 中声明的组件一律不动。

## 7. 数据迁移包结构

迁移包必须包含业务库和 Prometheus 历史指标，不能只迁 SQLite。

```text
manifest.json
smartx-data/smartx.db
prometheus-data/<block_id>/meta.json
prometheus-data/<block_id>/chunks/*
prometheus-data/<block_id>/index
```

导入默认使用 merge：

- 已有 Tower、集群、VM 不直接覆盖。
- 缺失业务数据补齐。
- 已存在 Prometheus block 跳过，缺失 block 补齐。
- 导入前必须生成当前系统备份，备份失败阻止导入。

overwrite 只用于明确恢复场景，并要求用户显式确认。

## 8. 安全边界

禁止提交或打包：

- `.env`
- `*.db`
- Prometheus 历史数据。
- Tower 明文密码或 API Token。
- 升级包、迁移包、备份包。
- `/data/upgrades`
- `/data/backups`
- `/data/exports`
- `/data/compose-runtime`
- 包含 `password`、`token`、`secret` 的敏感路径。

运行规则：

- 不执行 `docker compose down -v`。
- 不覆盖 `.env`。
- 不使用 `latest` 作为离线部署默认 tag。
- 平台版本、runner 版本、Prometheus 版本分开治理。
- 平台升级包不默认包含 runner。
- Prometheus 作为 `observability` 组件独立升级。

## 9. 当前版本边界

- 平台版本：`v0.5.1`
- runner 组件版本：`v0.3.0`
- Prometheus 镜像版本：`prom/prometheus:v2.55.1`
- 当前重建分支：`dev2`

`v0.5.1` 平台升级包只面向 v2 同架构后续升级。v1/v0.4.x 现场通过“全新部署 v2 + 数据迁移包导入”兼容，不走原地升级。
