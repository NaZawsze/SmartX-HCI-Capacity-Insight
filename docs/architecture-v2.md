# v2 总体架构设计

更新时间：2026-06-06

## 1. 目标

v2 的目标不是在 v1 上继续零散修补，而是保留 v1 的业务能力，重新建立清晰、可验证、可迁移、可升级的系统边界。

核心目标：

- 现场可交付：部署步骤稳定，页面首屏能看懂容量风险。
- 数据可迁移：v1 现场数据可以迁入 v2，不能只迁 SQLite，必须迁 Prometheus 历史指标。
- 系统可升级：平台、runner、Prometheus 组件升级由统一升级中心处理。
- 问题可排障：后台任务、日志、进度、备份、回滚路径都有明确记录。
- 架构不膨胀：保持模块化单体，不拆成多个业务微服务。

## 2. 容器职责

v2 默认保持 5 个容器。

| 容器 | 职责 | 对外暴露 |
| --- | --- | --- |
| `frontend` | React/Vite 构建后的静态页面，由 Nginx 提供访问 | `8080 -> 80` |
| `web-api` | FastAPI API、鉴权、查询、报表、迁移控制、任务查询、升级控制入口 | 默认仅内部/调试 |
| `collector-worker` | 定时采集 Tower/CloudTower 数据，写入 SQLite 和 Prometheus 指标源 | 内部 |
| `prometheus` | 保存历史容量时序，供趋势、增长、预测和迁移使用 | 内部 |
| `upgrade-runner` | 执行升级任务，避免 web-api 自己升级自己导致任务中断 | 内部 |

未来只有在报表、迁移、升级等后台任务明显影响 web-api 响应时，才评估新增第 6 个 `task-worker`。v2 第一阶段不新增。

## 3. 后端模块边界

后端按业务域拆模块，API 层只做鉴权、参数解析和调用领域服务。

| 模块 | 职责 |
| --- | --- |
| `auth` | 登录、token、当前用户、修改密码、管理员鉴权 |
| `inventory` | Tower、集群、VM 最新元数据、VM 最新展示名称 |
| `collection` | CloudTower 客户端、手动采集、定时采集、采集记录 |
| `metrics` | Prometheus 指标写入、查询、趋势、健康检查 |
| `forecast` | 容量风险、增长速率、90 天预测、日/月增长口径 |
| `reports` | Word/Excel 导出、报表留存、报表任务 |
| `migration` | 数据迁出、数据迁入、v1 数据兼容、导入前备份 |
| `upgrade` | 升级包解析、预检查、升级状态机、回滚、历史 |
| `tasks` | 统一后台任务、步骤、日志、下载链接、状态恢复 |
| `system` | 服务重启、空间清理、目录/权限检查、版本核验 |

关键约束：

- `metrics` 是历史数据唯一来源，不用 SQLite 代替 Prometheus 历史趋势。
- `reports`、`dashboard`、`VM trend` 都复用同一套增长和预测口径。
- `upgrade` 的执行动作由 `upgrade-runner` 完成，`web-api` 不直接升级自己。
- `tasks` 是横切模块，迁移、报表、升级、清理都必须接入。

## 4. 前端信息架构

v2 保留 v1 主导航，降低用户学习成本。

| 页面 | 职责 |
| --- | --- |
| Dashboard | 容量风险、Tower/集群/VM 摘要、采集状态、日增长、本日新建 VM |
| VM | VM 列表、趋势、详情、卷信息 |
| Reports | 集群预测、趋势窗口、日/月增长、本日/本月新建 VM、Word/Excel 导出 |
| Settings | Tower 配置、集群启用、账号入口 |
| Service Management | 数据迁移、服务重启、升级中心、空间清理、任务中心 |

全局规则：

- scope 支持全部、Tower、单集群。
- Dashboard、VM、Reports 都必须使用同一 scope。
- admin 头像下拉保留修改密码和登出。
- 任务中心位于右上角，显示上传、导出、导入、升级、清理等后台任务。

## 5. 数据职责

### SQLite

SQLite 保存业务元数据和最新状态。

必须保存：

- 用户和密码哈希。
- Tower、加密凭据、TLS 配置。
- 集群元数据和启用状态。
- VM 最新元数据和最新展示名称。
- 结构化 VM 卷字段。
- 采集运行记录。
- 后台任务和任务步骤。
- 报表导出历史。
- 数据迁移历史。
- 升级历史和回滚信息。

不再保存：

- 完整 Tower 原始 VM 卷 JSON。
- Prometheus 历史时序。
- 升级包、迁移包、报表文件本体。
- 明文凭据。

### Prometheus

Prometheus 保存历史容量时序。

必须支持：

- 集群容量历史。
- VM 容量历史。
- VM 趋势图。
- 日增长和月增长计算。
- 集群预测报表。
- 数据迁入后的历史指标回归。

VM 指标身份口径必须包含：

```text
tower_id + cluster_id + vm_id
```

VM 名称只做展示，不作为历史数据绑定身份。

### `/data` 文件系统

运行产物统一放在 `/data` 下。

| 路径 | 用途 |
| --- | --- |
| `/data/smartx-capacity-insight-data/app` | SQLite 业务库 |
| `/data/smartx-capacity-insight-data/prometheus` | Prometheus 历史 block |
| `/data/upgrades` | 升级包、解包目录、升级任务状态 |
| `/data/backups` | 升级前备份、导入前备份、项目文件备份 |
| `/data/exports/reports` | Word/Excel 报表留存 |
| `/data/exports/migrations` | 数据迁出包 |
| `/data/exports/imports` | 数据迁入包和解包目录 |
| `/data/exports/migration-tasks` | 数据迁移任务状态 |
| `/data/compose-runtime` | 升级中心生成的运行时 compose override |

## 6. 核心数据流

### 采集流

1. `collector-worker` 或手动采集触发。
2. 读取启用的 Tower 和集群。
3. 调用 CloudTower 获取集群容量、VM、VM 卷。
4. 更新 SQLite 中最新 Tower/集群/VM/卷元数据。
5. 写入 Prometheus 指标源。
6. Dashboard、VM、Reports 读取 SQLite 最新状态和 Prometheus 历史指标。

### 报表流

1. 前端选择 scope 和统计窗口。
2. `web-api` 查询 SQLite 获取 Tower/集群/VM 最新信息。
3. `metrics` 查询 Prometheus 历史数据。
4. `forecast` 计算风险、增长、预测、新建 VM。
5. 页面展示或 `reports` 生成 Word/Excel。
6. 导出文件保存到 `/data/exports/reports`，任务中心提供下载链接。

### 迁移流

1. 迁出读取 SQLite 必要数据和 Prometheus 历史 block。
2. 生成迁移包和 manifest。
3. 迁入前先备份当前 SQLite 和 Prometheus。
4. merge 或 overwrite 写入业务数据。
5. 补全 Prometheus 历史 block。
6. 导入后执行健康验证。

### 升级流

1. 上传升级包。
2. 解析 manifest 并识别组件。
3. 预检查 Docker、compose、镜像、磁盘、网络、volume、权限。
4. 备份数据和项目文件。
5. `upgrade-runner` 加载镜像、同步项目文件、执行迁移、重启服务。
6. 健康检查。
7. 成功记录历史；失败保留回滚入口。

## 7. 架构约束

- 不执行 `docker compose down -v`。
- 不覆盖 `.env`。
- 不把 Tower 凭据写入日志、导出包或升级包。
- 不使用 `latest` 作为离线部署默认 tag。
- 不把 Prometheus 历史指标视为可选数据。
- 不通过 VM 名称绑定历史趋势。
- 不让平台升级默认升级 runner，runner 是独立组件。
- 不让平台升级默认升级 Prometheus，Prometheus 是 observability 组件。
