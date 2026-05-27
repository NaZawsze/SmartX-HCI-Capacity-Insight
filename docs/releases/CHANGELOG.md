# 更新说明

本文档记录 SmartX HCI Capacity Insight 各版本的主要变化。项目介绍、部署方式和基础使用说明仍以根目录 README 和 docs 文档为准。

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
