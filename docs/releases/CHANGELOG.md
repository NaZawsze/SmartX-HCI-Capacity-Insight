# 更新说明

本文档记录 SmartX HCI Capacity Insight 各版本的主要变化。项目介绍、部署方式和基础使用说明仍以根目录 README 和 docs 文档为准。

## v0.5.1u2

发布日期：2026-06-28

### 更新摘要

v0.5.1u2 是平台过渡版本，用于把现有 v2 环境整理到统一部署和升级口径，为后续单独升级 `upgrade-runner v0.3.1` 做准备。本版本不升级 runner，也不包含 `upgrade-runner.tar`。

### 新增与优化

- 平台版本统一为 `v0.5.1u2`，平台三件套使用 `v0.5.1u2` 镜像 tag。
- README、部署文档、版本治理文档和升级包说明统一到 `v0.5.1u2`。
- 平台升级包说明写清兼容范围、必填文件、校验和、迁移边界和禁止包含的数据。
- 三份 compose 保持固定顶层 `name: smartx-hci-capacity-insight`，避免手动执行 `docker compose up -d` 时生成错误项目名。
- 打包器生成的 `release-notes.md` 改为中文说明，写清更新内容、修复内容和过渡版本边界。

### 修复内容

- 修复部分环境因 compose 项目名不一致导致服务管理、平台升级和观测组件状态读取不稳定的问题。
- 修复升级包说明过轻，用户难以确认 sha256、schema、兼容范围和迁移边界的问题。
- 修复无 SQLite schema 变化的平台包误带迁移脚本或 `script.sandbox.v1` 能力要求的问题。

### 升级策略

- 支持 `v0.5.0/v0.5.1/v0.5.1u1 -> v0.5.1u2`。
- 支持 `v0.5.1u2 -> v0.5.1u2` 同版本重同步。
- 不支持 v1 或 `v0.4.x` 原地升级，旧架构系统继续通过“新装 v2 + 数据迁移包导入”兼容。
- 后续如平台版本依赖 `upgrade-runner v0.3.1` 新能力，应先发布 runner 组件包并在平台升级预检查中校验 runner 版本或 capability。

## v0.5.0

发布日期：2026-06-06

### 更新摘要

v0.5.0 是 v2 受控重建版本，保持 v1 的业务能力和页面风格，同时重建后端模块边界、任务中心、数据迁移灾备、升级中心和服务管理。平台版本使用 `v0.5.0`，`upgrade-runner` 作为独立组件升级到 `v0.3.0`。

### 新增与优化

- 平台版本统一为 `v0.5.0`，平台三件套使用 `v0.5.0` 镜像 tag。
- `upgrade-runner` 组件版本统一为 `v0.3.0`，不跟随平台版本 tag。
- v2 后端重建认证、Tower、采集、Dashboard、VM、报表、迁移、升级和服务管理模块。
- Dashboard 容量风险按单集群使用率判断，任一集群超过 80% 即高风险。
- 日增长、本日新建 VM、月增长、本月新建 VM 使用稳定 VM UUID 口径，展示名称优先使用最新采集名称。
- 月增长 VM 要求样本跨度满 30 天；刚部署不足 30 天时月增长榜为空。
- Word/Excel 报表复用页面数据口径，保存到 `/data/exports/reports`，任务中心提供下载链接。
- 数据迁移导入前强制备份当前系统，迁出/迁入文件留存在 `/data/exports` 对应目录。
- 升级中心 manifest 支持 platform、runner、observability 组件类型，平台升级、runner 组件升级和 Prometheus 组件升级分离。
- 服务管理页包含数据迁移、服务重启、升级中心和空间清理。
- Docker Compose 平台 tag 与 runner tag 分离，离线和 release compose 默认使用明确版本，不再依赖 `latest`。
- 2026-06-11 内部修补：任务中心确认 warning/critical 告警时不再刷新 `updated_at`，避免历史任务确认后跳回列表顶部。
- 2026-06-11 内部修补：升级包构建器支持 v2 跨版本累计 SQLite migration；当前 `v0.5.0` 正式包无 schema 迁移时不包含迁移脚本，也不声明 `script.sandbox.v1`。
- 2026-06-11 内部修补：迁移注册表支持严格校验、幂等 SQL 和 `add_column_if_missing`，未来跨过 schema 变化版本时按 `source_version < step.version <= target_version` 选择并执行中间迁移步骤。

### 升级策略

- 平台升级继续由 `upgrade-runner v0.3.0` 执行。
- 平台升级包只面向 v2 同架构后续升级；v1/v0.4.x 通过新装 v2 后导入数据迁移包兼容。
- 如果仅更新业务平台，不需要更新 runner。
- 如果升级流程、manifest、compose、volume、网络或 runner 自身能力变化，先发布 runner 组件包，再发布平台升级包。

## v0.4.1

发布日期：2026-06-05

### 更新摘要

v0.4.1 聚焦版本治理和升级边界收敛，将平台版本与 `upgrade-runner` 组件版本彻底拆分，避免 runner 被错误打上平台版本 tag。

### 新增与优化

- 平台版本统一为 `v0.4.1`，平台三件套使用 `v0.4.1` 镜像 tag。
- 新增根目录 `RUNNER_VERSION`，当前 runner 组件版本为 `v0.2.2`。
- `docker-compose.offline.yml` 和 `docker-compose.release.yml` 拆分 `SMARTX_IMAGE_TAG` 与 `SMARTX_RUNNER_IMAGE_TAG`。
- 平台升级包只包含 `web-api`、`collector-worker`、`frontend`，不再包含 `upgrade-runner.tar`。
- 后端镜像统一内置 `VERSION` 和 `RUNNER_VERSION`，平台版本与 runner 组件版本都优先读取镜像内文件。
- 修正部署文档，离线部署不再描述为 `latest` 默认 tag，并明确平台 tag 与 runner tag 分开配置。
- `scripts/build_runner_component_package.py` 默认读取 `RUNNER_VERSION`。
- GitHub Actions 拆分 runner 构建：平台 workflow 不再构建 runner，runner 仅通过 `runner-v*` tag 或手动 workflow 构建。
- 新增 `docs/version-governance.md`，记录版本模型、发版检查清单和 DockerHub 错误 tag 清理方法。

### 升级策略

- 平台升级继续由 `upgrade-runner v0.2.2` 执行。
- 如果仅更新业务平台，不需要更新 runner。
- 如果升级流程、manifest、compose、volume、网络或 runner 自身能力变化，先发布 runner 组件包，再发布平台升级包。

## v0.4.0

发布日期：2026-06-02

### 更新摘要

v0.4.0 聚焦首页容量风险展示、升级包生成规范和升级后核验能力，明确平台升级与 `upgrade-runner` 组件升级的边界。

### 新增与优化

- 首页顶部新增独立容量风险卡片，Tower 与集群卡片保持独立并对齐展示。
- 新增根目录 `VERSION`，作为版本号单一来源。
- 新增 `scripts/build_upgrade_package.py`，用于统一生成平台升级包、manifest、release-notes、镜像 tar 和 sha256 文件。
- 升级中心新增“平台状态”，展示当前软件版本、升级中心版本、运行服务镜像、服务状态、最近成功升级包版本和 SHA256。
- 新增 `docs/upgrade-runner-lifecycle.md`，说明 `upgrade-runner` 生命周期、组件升级策略和何时需要升级 runner。
- `docker-compose.release.yml` 默认镜像标签更新为 `v0.4.0`。

### 升级策略

- 平台升级包默认只升级 `web-api`、`collector-worker` 和 `frontend`。
- `upgrade-runner` 不随每个业务版本强制升级；只有升级流程、manifest 格式、compose/volume/network 模型或组件拓扑变化时，才通过组件升级单独更新。

## v0.3.3u2

发布日期：2026-06-01

### 更新摘要

v0.3.3u2 聚焦客户报表可读性、导出文档细节和升级可靠性，优化 Word/Excel 报表的目录、排序、高风险 VM 标识、时区显示和趋势图纵坐标，并修复升级前备份包含升级包自身导致备份阶段过慢的问题。

### 新增与优化

- Word 报表新增集群目录，支持按集群章节快速定位。
- Word/Excel 的 VM TOP100 表格新增排名列，并在表头标明增长量或增长率降序。
- Excel TOP100 区域改为表格结构，支持表头筛选和排序。
- 增长率超过 20% 且增长量大于 100 GiB 的 VM 在 Word/Excel 中使用红色底纹标识。
- 报表生成时间显式使用 `SMARTX_COLLECTION_TIMEZONE`，默认按 `Asia/Shanghai` 显示，避免容器 UTC 导致时间慢 8 小时。
- Word 报表容量趋势图纵坐标改为按数据范围自动留白，避免趋势线贴边。
- Word 集群章节页脚显示 `Tower-集群名称集群 · 生成时间`。
- 报表容量增长速率改为 7 天平均，并支持 7/30/90/365/720 天图表窗口切换。
- 数据迁移和升级前备份排除 `upgrades`、`backups` 运行目录，避免备份包含升级包自身。

### 升级包目录结构

```text
manifest.json
release-notes.md
images/
  web-api.tar
  collector-worker.tar
  frontend.tar
```

`manifest.json` 关键字段：

```text
product: smartx-storage-forecast
version: 0.3.3u2
min_version: 0.3.2
database_migration: false
images: web-api、collector-worker、frontend 镜像 tar 的 service、image、file、sha256
restart_services: web-api、collector-worker、frontend
```

### 验证说明

- 已在 `10.20.11.3` 使用本地升级包完成一次平台升级验证。
- 升级任务完成后 `web-api`、`collector-worker`、`frontend` 均正常 recreate/start。
- `web-api`、`frontend`、`prometheus` HTTP 健康检查均返回 200。

## v0.3.3

发布日期：2026-05-27

### 更新摘要

v0.3.3 聚焦升级中心体验和 upgrade-runner 组件独立升级能力，将平台升级与组件升级拆分，避免升级执行器在平台升级过程中重启自身。

### 新增与优化

- 将服务管理中的“系统升级”改为“升级中心”，下设平台升级、组件升级和升级历史。
- 保留平台升级能力，用于升级 `web-api`、`frontend`、`collector-worker` 等平台服务。
- 新增组件升级能力，第一版只支持单独升级 `upgrade-runner`。
- 新增组件升级接口，支持上传组件包、预检查、开始升级、状态查询、历史和删除未执行包。
- `upgrade-runner` 当前版本默认显示为 `v0.1.0`，升级成功后会记录到 `/data/upgrade-runner.version`。
- 组件升级由 `web-api` 直接执行 Docker 操作，只重启 `upgrade-runner`，不修改业务库、历史指标和数据卷。
- 平台升级与组件升级历史合并展示，并接入右上角任务中心进度。
- 优化升级执行步骤展示：升级开始后即展示完整步骤，运行中显示 loading，成功显示绿色勾，未执行显示空心圆。

### 组件升级包目录结构

```text
manifest.json
release-notes.md
images/
  upgrade-runner.tar
```

`manifest.json` 关键字段：

```text
product: smartx-upgrade-runner
component: upgrade-runner
version: 目标组件版本
min_version: 最低兼容组件版本
images: upgrade-runner 镜像 tar 的 service、image、file、sha256
restart_services: upgrade-runner
release_notes: 页面展示的组件升级说明
```

### 兼容说明

- 平台升级包默认仍不包含 `upgrade-runner`，避免平台升级任务过程中中断执行器。
- 组件升级不生成业务数据备份，因为它不修改业务数据库、Prometheus 历史指标和持久化 volume。
- 组件升级会在平台升级任务运行中被拦截，防止并发重启冲突。

## v0.3.2

发布日期：2026-05-27

### 更新摘要

v0.3.2 聚焦离线部署、/data 持久化目录和数据迁移可靠性，修复迁移到新系统后历史指标可能没有随业务库完整恢复的问题。

### 新增与优化

- 新增 `docker-compose.release.yml`，用于直接运行 GitHub Actions 构建好的远端镜像。
- 新增 `docker-compose.offline.yml`，默认使用本地 `latest` 镜像并设置 `pull_policy: never`，适合无外网或不允许拉取镜像的环境。
- 持久化数据统一迁移到宿主机 `/data/smartx-capacity-insight-data`：业务库位于 `app`，Prometheus 指标位于 `prometheus`。
- 系统升级预检查改为校验新的 `/data/smartx-capacity-insight-data` 绑定挂载，并按当前 `SMARTX_COMPOSE_FILE` 读取实际 compose 文件。
- 数据迁移补全导入优化：当目标 Prometheus 目录没有历史 block 时，会完整导入迁移包中的历史指标数据；已有历史 block 时只补充缺失 block，不覆盖现有指标。
- 更新平台版本号到 `0.3.2`，确保系统升级页显示和预检查版本判断准确。

### 升级包目录结构

v0.3.2 离线升级包生成路径示例：

```text
/data/upgrade-packages/smartx-capacity-insight-upgrade-v0.3.2.tar.gz
```

压缩包内部结构：

```text
manifest.json
release-notes.md
images/
  web-api.tar
  collector-worker.tar
  frontend.tar
scripts/
  migrate.sh              # 可选，仅当 manifest.database_migration=true 时需要
```

`manifest.json` 关键字段：

```text
product: smartx-storage-forecast
version: v0.3.2
min_version: 0.2.0
database_migration: false
images: 每个服务镜像 tar 的 service、image、file、sha256
restart_services: web-api、collector-worker、frontend
release_notes: 页面展示的升级说明
```

说明：v0.3.2 升级包为了兼容旧版本预检查，只在 `manifest.images` 中放入 `web-api`、`collector-worker` 和 `frontend`。`upgrade-runner` 镜像仍会随 `v0.3.2` tag 由 GitHub Actions 自动构建发布；升级到 v0.3.2 后，后续升级包可以包含 `upgrade-runner` 镜像，但默认不在同一次升级任务里重启执行器，避免任务过程中中断自身。

### 兼容说明

- 默认补全导入仍不覆盖当前业务库已有 Tower、集群和采集记录。
- 覆盖导入仍会整体替换当前业务库和 Prometheus 指标目录，执行前需要确认。
- 从旧 named volume 部署切换到 `/data/smartx-capacity-insight-data` 前，需要先迁移旧 volume 数据。

## v0.3.0

发布日期：2026-05-27

### 更新摘要

v0.3.0 聚焦平台运维能力，新增独立的服务管理页面、数据迁移导入导出、数据服务手动重启，以及第一版离线在线升级能力。升级功能采用“上传升级包、预检查、选中包后执行升级”的模式，避免直接覆盖数据卷或环境配置。

### 新增功能

- 新增“服务管理”独立页面，入口位于主导航“设置”之后。
- 服务管理页按平台运维场景分为：数据迁移、服务重启、系统升级、升级历史。
- 数据迁移支持导出迁移包，用于在同套系统之间迁移采集数据。
- 数据迁移支持补全导入，默认只补齐缺失数据，保留当前系统已有数据。
- 数据迁移支持覆盖导入，但需要显式确认。
- 服务重启页支持手动重启 `web-api`、`collector-worker` 和 `prometheus`，用于迁移导入后让数据完全生效。
- 新增离线升级包上传能力，升级包上传后保存到系统目录 `/data/upgrades/{task_id}`。
- 系统升级页新增“可升级版本”区域，可选中某个升级包后执行预检查、开始升级、取消选择或删除未开始升级的包。
- 新增升级历史页，展示目标版本、状态、上传时间、完成时间和备份路径。
- 新增 `upgrade-runner` 服务，负责执行升级任务，避免 `web-api` 升级自身时中断任务。
- 升级前会自动生成数据迁移备份包，路径形如 `/data/backups/upgrade-<version>-before-<time>.tar.gz`。
- 支持手动回滚到升级前镜像配置。

### 优化与修复

- 设置页移除数据迁移和服务管理相关内容，只保留 Tower 配置。
- 服务管理页进入后会收起集群侧栏，使平台运维页面居中展示。
- 优化服务管理页切换动画和滚动行为，避免切换数据迁移、系统升级、升级历史时页面显示不全。
- 优化上传控件样式，用统一上传面板替代浏览器原生文件选择控件。
- 优化预检查结果样式，成功项使用绿色勾，失败项使用红色 X。
- 统一系统升级操作按钮尺寸和对齐方式。

### 接口变更

新增鉴权接口：

```http
POST /api/admin/upgrade/upload
POST /api/admin/upgrade/precheck/{task_id}
POST /api/admin/upgrade/start/{task_id}
GET  /api/admin/upgrade/status/{task_id}
POST /api/admin/upgrade/rollback/{task_id}
DELETE /api/admin/upgrade/package/{task_id}
GET  /api/admin/upgrade/history
GET  /api/admin/upgrade/version
POST /api/admin/system/restart
GET  /api/admin/migration/export
POST /api/admin/migration/import
```

### 升级包格式

第一版离线升级包使用 `.tar.gz` 格式，包含：

```text
manifest.json
images/web-api.tar
images/frontend.tar
images/collector-worker.tar
scripts/migrate.sh      # 可选
release-notes.md        # 可选
```

`manifest.json` 需要包含版本、最低兼容版本、镜像列表、sha256、是否需要数据库迁移和重启服务列表。

### 数据保护策略

- 不覆盖 `.env`。
- 不替换业务数据卷和 Prometheus 数据卷。
- 不执行 `docker compose down -v`。
- 禁止修改核心 volume 挂载：`smartx-data:/data` 和 `prometheus-data:/prometheus`。
- 已开始升级的包不允许从页面删除，避免破坏回滚记录。

### 部署说明

升级到 v0.3.0 后需要重新构建并启动后端、前端和 upgrade-runner：

```bash
docker compose build web-api frontend collector-worker
docker compose up -d web-api frontend collector-worker upgrade-runner
```

## v0.2

发布日期：2026-05-25

### 更新摘要

v0.2 聚焦完善存储预测报表能力，新增 Word 和 Excel 导出，导出范围与页面当前选择保持一致，并修复月增长数据在部分环境下为空的问题。同时调整账号与页面交互，让平台密码修改入口回到管理员头像菜单。

### 新增功能

- 报表页新增统一 `导出` 按钮，点击后先选择历史时间区间，再自动下载 Word 和 Excel 两个文件。
- 导出范围跟随当前报表选择：全部集群、单个 Tower 或单个集群。
- 支持 7 天、14 天、30 天、90 天、180 天和 365 天历史窗口。
- Word 导出包含导出范围、生成时间、预测窗口、集群数量、集群预测汇总，以及每个集群的月增长 Top 100 VM 总结。
- Word 中每个集群分别提供按增长量排序和按增长率排序的 Top 100 表。
- Excel 导出包含 `汇总`、`VM_TOP100_汇总` 和每个集群独立 sheet。
- Excel VM 明细包含 Tower、集群、VM、当前容量、上期容量、月增长量和增长率。

### 优化与修复

- 修复报表容量增长速率可能为空的问题：当 Prometheus `offset` 查询缺少对应历史点时，会回退使用所选窗口内最早样本计算增长。
- 导出文件名按范围生成：全部导出使用 `storage-forecast-all-YYYYMMDD`，Tower 导出使用 Tower 名称加随机后缀，集群导出使用集群名称。
- 增长量/增长率切换按钮增加居中样式，避免紧凑宽度下文字偏移。
- 移除页面顶部的 `CHINATOWER` 范围栏，报表和虚拟机页面继续按当前集群树选择联动。
- 平台密码修改入口从设置页移动到右上角管理员头像菜单。头像菜单提供 `设置密码` 和 `登出`。

### 接口变更

新增鉴权接口：

```http
GET /api/reports/export/word?tower_id=&cluster_id=&period_days=30
GET /api/reports/export/excel?tower_id=&cluster_id=&period_days=30
```

### 依赖变更

后端新增文档导出依赖：

- `python-docx==1.1.2`
- `openpyxl==3.1.5`

## v0.1

发布日期：2026-05-23

### 更新摘要

v0.1 是项目第一版可用能力，提供 SmartX/CloudTower 容量采集、容量概览、虚拟机趋势、集群预测报表和基础平台管理能力。

### 新增功能

- 支持配置 CloudTower/Tower 连接信息，并通过连接测试发现集群。
- 支持多 Tower、多集群容量概览。
- 支持按全部、Tower、单集群范围查看容量数据。
- 支持每日定时采集和手动触发采集。
- 支持 Tower 级采集状态展示。
- 支持虚拟机列表、搜索和容量排序。
- 支持虚拟机存储趋势图，提供 7 天、14 天、30 天、90 天、180 天和 365 天时间范围。
- 支持当前虚拟机卷明细和所有虚拟卷明细展示。
- 支持日增长最快 VM 和月增长最快 VM 榜单。
- 支持按增长量和增长率切换排序。
- 支持集群容量预测报表，展示预测窗口、容量增长速率和容量风险。
- 支持平台登录、JWT 鉴权和管理员密码管理。

### 基础架构

- 后端使用 FastAPI。
- 前端使用 React、TypeScript 和 ECharts。
- 运行时数据存储在 SQLite 和 Prometheus 中。
- 使用 Docker Compose 部署 `web-api`、`collector-worker`、`frontend` 和 `prometheus`。
