# v2 升级中心设计

更新时间：2026-06-10

## 1. 目标

v2 升级中心重新设计，不兼容旧升级路径。目标是一次上传后，由 manifest 自动识别升级内容，完成预检查、备份、执行、健康检查、历史记录和回滚准备。

支持升级对象：

- `platform`：`web-api`、`collector-worker`、`frontend`
- `runner`：`upgrade-runner`
- `observability`：Prometheus

未在 manifest 中声明的组件一律不动。

## 2. 升级包结构

统一使用 `.tar.gz`。

### 2.1 平台升级包

平台升级包用于升级业务平台三件套：`web-api`、`collector-worker`、`frontend`。

```text
smartx-capacity-insight-platform-upgrade-v0.5.x.tar.gz
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
│   ├── pre_install.sh
│   ├── prometheus/
│   │   └── prometheus.yml
│   ├── docs/
│   │   └── ...
│   └── scripts/
│       └── ...
└── migrations/                         # 可选，仅 migration_steps 非空时包含
    └── run_migrations.py
```

说明：

- `images/` 中只包含平台三件套镜像。
- `project/` 包含允许同步到项目目录的白名单文件。
- `migrations/run_migrations.py` 仅在来源版本到目标版本之间存在已登记 SQLite 迁移步骤时包含并执行。
- 无 schema 变化的当前正式包或小修复包不包含迁移脚本，例如 `v0.5.0 -> v0.5.0`。
- 跨版本升级包必须是累计迁移包，例如 `v0.5.0 -> v0.5.3` 会包含并执行 `v0.5.2` 的 schema 迁移。
- 平台升级包不默认包含 `upgrade-runner.tar` 或 `prometheus.tar`。

执行者：`upgrade-runner`。

流程：

1. `web-api` 上传升级包。
2. `web-api` 解包并解析 `manifest.json`。
3. `web-api` 执行预检查并创建升级任务。
4. `web-api` 将任务提交给 `upgrade-runner`。
5. `upgrade-runner` 生成升级前备份。
6. `upgrade-runner` 加载平台三件套镜像。
7. `upgrade-runner` 同步 `project/` 白名单项目文件。
8. `upgrade-runner` 写入 `/data/compose-runtime/docker-compose.upgrade.yml`。
9. 如 manifest 中 `database_migration=true`，`upgrade-runner` 执行 `migrations/run_migrations.py`，脚本内部按版本顺序执行所有命中的迁移步骤。
10. `upgrade-runner` 重启 `web-api`、`collector-worker`、`frontend`。
11. `upgrade-runner` 执行健康检查。
12. `web-api` 展示任务状态、日志和历史。

### 2.2 升级中心组件包

升级中心组件包用于升级 `upgrade-runner` 本身。

```text
smartx-capacity-insight-component-upgrade-runner-v0.3.x.tar.gz
├── manifest.json
├── checksums.sha256
├── release-notes.md
└── images/
    └── upgrade-runner.tar
```

说明：

- runner 组件包只包含 `upgrade-runner.tar`。
- 通常不包含 `project/`。
- 通常不包含 `scripts/migrate.sh`。
- runner 版本独立于平台版本。

执行者：`web-api`。

流程：

1. `web-api` 上传组件升级包。
2. `web-api` 解包并解析 `manifest.json`，确认 `type=runner`、`service=upgrade-runner`。
3. `web-api` 执行预检查。
4. `web-api` 加载 `upgrade-runner.tar`。
5. `web-api` 写入 `/data/compose-runtime/docker-compose.runner-upgrade.yml`。
6. `web-api` 重启 `upgrade-runner`。
7. `web-api` 读取 runner 版本并做组件健康检查。
8. `web-api` 展示任务状态、日志和历史。

原因：

- `upgrade-runner` 不能执行自己的升级，否则会在任务中重启自身导致任务断链。

### 2.3 观测组件包

观测组件包用于升级 Prometheus。

```text
smartx-capacity-insight-component-upgrade-prometheus-v2.xx.x.tar.gz
├── manifest.json
├── checksums.sha256
├── release-notes.md
├── config/
│   └── prometheus.yml
└── health/
    └── queries.json
```

默认包不包含 Prometheus 镜像 tar，只在 manifest 中声明镜像仓库和 tag。如果现场无法访问镜像仓库，离线包可以额外包含：

```text
smartx-capacity-insight-component-upgrade-prometheus-v2.xx.x.tar.gz
├── manifest.json
├── checksums.sha256
├── release-notes.md
├── config/
│   └── prometheus.yml
├── health/
│   └── queries.json
└── images/
    └── prometheus.tar
```

如果 Prometheus 配置需要更新，使用 `file_sets` 白名单同步：

```text
file_sets:
  source: config
  target: prometheus
  files:
    - prometheus.yml
```

说明：

- Prometheus 属于 `observability`，不属于平台三件套。
- Prometheus 版本独立于平台版本和 runner 版本。
- 观测组件包不包含 `web-api.tar`、`collector-worker.tar`、`frontend.tar` 或 `upgrade-runner.tar`。
- 观测组件包不包含 Prometheus 历史数据；升级前备份是服务器本机回滚材料，不是升级包内容。
- Prometheus 历史指标导出只属于完整数据迁移包，不属于平台升级或组件升级。
- 默认包只引用镜像仓库 tag；离线包才包含 `images/prometheus.tar`。

执行者：`upgrade-runner`。

流程：

1. `web-api` 上传观测组件升级包。
2. `web-api` 解包并解析 `manifest.json`，确认 `type=observability`、`service=prometheus`。
3. `web-api` 执行预检查并创建升级任务。
4. `web-api` 将任务提交给 `upgrade-runner`。
5. `upgrade-runner` 强制备份 Prometheus 历史指标目录到 `/data/backups/...`，用于失败回滚。
6. `upgrade-runner` 检查 Prometheus 数据目录权限和磁盘空间。
7. 如果离线包包含 `images/prometheus.tar`，`upgrade-runner` 加载镜像；否则使用 manifest 中声明的仓库镜像。
8. 如果 manifest 声明 `file_sets`，`upgrade-runner` 先备份再同步配置白名单文件。
9. `upgrade-runner` 写入 `/data/compose-runtime/docker-compose.prometheus-upgrade.yml`。
10. `upgrade-runner` 重启 Prometheus。
11. `upgrade-runner` 检查 `/-/healthy` 或 `/-/ready`。
12. `upgrade-runner` 验证历史指标 `query_range`。
13. `web-api` 展示任务状态、日志和历史。
```

包内禁止包含：

```text
.env
*.db
prometheus data blocks
backups/
upgrades/
exports/
compose-runtime/
password
token
secret
Tower credentials
```

## 3. manifest 关键字段

示例结构：

```json
{
  "schema_version": "3",
  "minimum_runner_protocol": 1,
  "required_capabilities": [
    "backup.create",
    "image.load",
    "files.sync",
    "compose.override",
    "compose.apply",
    "health.http",
    "rollback.restore"
  ],
  "package_id": "smartx-capacity-insight-v2.0.0",
  "version": "v2.0.0",
  "components": [
    {
      "type": "platform",
      "services": ["web-api", "collector-worker", "frontend"],
      "images": [
        {"service": "web-api", "image": "nazawsze/smartx-hci-capacity-insight-web-api:v2.0.0", "archive": "images/web-api.tar", "sha256": "..."}
      ]
    }
  ],
  "project_files": true,
  "database_migration": false,
  "restart_services": ["web-api", "collector-worker", "frontend"],
  "compatibility": {"min_platform_version": "v2.0.0"},
  "notes": "release-notes.md"
}
```

规则：

- 平台版本和 runner 版本分开。
- 平台包不默认包含 runner。
- Prometheus 作为 `observability` 组件声明。
- 镜像必须声明 `service` 和 `image`；离线镜像 tar 还必须声明 `archive` 和 `sha256`。
- `project_files=true` 时必须包含 `project/` 白名单文件。
- schema 3 必须包含 `checksums.sha256`，并通过完整包内文件校验。
- `minimum_runner_protocol` 与 `required_capabilities` 用于能力协商；普通平台版本变化不要求同步升级 runner。
- 平台升级包默认不包含 `migration`；只有 `migration_steps` 非空时才设置 `database_migration=true`、追加 `script.sandbox.v1` 并声明 legacy `migration.script=migrations/run_migrations.py`。
- 迁移选择规则为 `source_version < migration_steps[].version <= target_version`；已存在于 SQLite `schema_migrations` 表的步骤必须跳过。
- `schema_migrations` 字段为 `id`、`version`、`description`、`script_sha256`、`applied_at`，所有未来 SQLite schema 变化必须新增 migration step，不能只改初始化逻辑；普通 schema 变化可在 registry step 中声明幂等 `sql` 列表。

### 3.1 组件声明规则

`components[]` 是升级中心识别升级对象的唯一来源。

组件类型：

- `platform`：平台三件套，只允许包含 `web-api`、`collector-worker`、`frontend`。
- `runner`：升级中心执行器，只允许包含 `upgrade-runner`。
- `observability`：观测组件，当前只允许包含 `prometheus`。
- `bundle`：组合包，不是具体服务；必须展开为上述具体组件。

校验规则：

- manifest 中声明的组件才允许执行升级；未声明组件不能因为 compose 中存在而被重启。
- 每个 image 必须声明 `service`、`image`；离线 image archive 必须额外声明 `archive`、`sha256`。
- `image` 的仓库名、服务名和 tag 必须与目标 compose/override 规则一致。
- Prometheus 版本不跟随平台版本；runner 版本不跟随平台版本。
- 组合包必须给出组件升级顺序和每个组件的健康检查规则。

### 3.2 Phase 22 执行协议

- `web-api` 只负责解包、预检查并把 manifest 编译为 `execution_plan`。
- `upgrade-runner v0.3.0` 只执行版本化 Action，不导入平台 `UpgradeService`。
- `task.json` 是执行状态权威记录，使用原子写入、单调递增 revision 和逐 Action checkpoint。
- SQLite `upgrade_runner_state` 保存 Runner 心跳、协议和能力；`upgrade_task_leases` 防止多个 Runner 重复执行同一任务。
- 幂等动作可自动恢复；结果不明确的迁移脚本进入 `recovery_required`，由管理员选择继续、回滚或标记失败。
- 升级后健康检查失败时自动回滚一次；回滚失败形成严重告警，不无限重试。

### 3.3 组合包

```text
smartx-capacity-insight-bundle-v0.5.0.tar.gz
├── manifest.json
├── checksums.sha256
├── platform/
│   ├── images/
│   ├── project/
│   ├── overrides/
│   └── migrations/                    # 可选，仅 migration_steps 非空时包含
└── observability/
    ├── config/
    ├── health/
    └── images/        # 可选，仅离线 Prometheus 镜像包包含
```

组合包默认不包含 `upgrade-runner`，也不包含 Prometheus 历史数据。只有 manifest 声明了当前 Runner 不具备的能力时，才先使用独立 Runner 组件包。

### 3.4 数据与备份边界

- 平台升级、Prometheus 组件升级和组合升级都不导出 Prometheus 历史数据。
- 升级前 Prometheus 备份只保存在服务器 `/data/backups/...`，用于失败回滚或人工恢复。
- Prometheus 历史 block 的导出/导入只属于完整数据迁移包。
- 配置迁移包只迁移 Tower/Cluster 配置，不包含 Prometheus 历史指标。

## 4. 状态机

升级任务状态：

```text
uploaded
parsed
precheck_running
precheck_passed
precheck_failed
backup_running
images_loading
project_syncing
migration_running
services_restarting
health_checking
success
failed
rollback_ready
rollback_running
rollback_success
rollback_failed
```

每个状态必须记录：

- 开始时间。
- 结束时间。
- 当前进度。
- 当前文件或服务。
- 小日志。
- 错误摘要。

任务状态必须持久化到 `/data/upgrades/<task_id>/task.json`，web-api 重启后能恢复展示。

## 5. 预检查

预检查必须步骤化展示。

检查项：

- manifest schema。
- 包内路径安全。
- 镜像 archive 存在。
- sha256 匹配。
- 镜像名和目标 compose 匹配。
- Docker socket 可用。
- Docker compose 可用。
- 当前项目名和 compose 文件可识别。
- 网络不使用 `172.16.0.0/16` 或 `172.17.0.0/16`。
- 数据 volume 或 bind mount 不会被替换。
- 磁盘空间足够保存备份和加载镜像。
- project 文件包不包含敏感路径。
- Prometheus 升级时检查数据目录权限。

预检查失败时不允许开始升级。

## 6. 执行职责

web-api 负责：

- 上传。
- 解包。
- 解析 manifest。
- 展示预检查结果。
- 创建升级任务。
- 直接执行 runner-only 组件升级任务，避免 upgrade-runner 重启自身导致任务断链。
- 查询状态、日志和历史。

upgrade-runner 负责：

- 平台升级和 observability 升级的数据备份。
- 平台升级和 observability 升级的镜像加载。
- 平台升级的项目文件同步。
- 平台升级和 observability 升级的迁移脚本执行。
- 平台升级和 observability 升级的 compose runtime override 写入。
- 平台升级和 observability 升级的服务重启。
- 平台升级和 observability 升级的健康检查。
- 平台升级和 observability 升级的回滚。

runner 执行 Docker 操作时必须使用宿主机视角路径，不使用容器内 `/opt` 作为 Docker compose 工作目录。

执行边界：

- web-api 不执行平台三件套和 Prometheus 的长流程升级，只负责提交任务和恢复展示。
- upgrade-runner 不执行 runner 自升级，避免升级执行器杀掉自身导致任务断链。
- Prometheus 升级必须独立记录 observability 子任务，不能混在平台服务重启里静默完成。

## 7. 备份

平台升级前备份：

- SQLite。
- Prometheus 历史 block。
- 当前 compose runtime override。
- 将被覆盖的项目文件。

备份路径：

```text
/data/backups/upgrade-<version>-before-<timestamp>.tar.gz
/data/backups/project-files-before-<version>-<timestamp>/
```

备份必须有进度：

- 扫描文件数。
- 扫描字节数。
- 当前文件。
- 已写入字节。

## 8. 项目文件同步

允许同步：

- compose 文件。
- Prometheus 配置。
- `pre_install.sh`。
- docs。
- scripts。

禁止同步：

- `.env`
- 数据库。
- Prometheus 数据。
- 备份。
- 升级包。
- 迁移包。
- 凭据。

同步前先备份旧项目文件。

## 9. runner 自升级

runner 是升级执行器，不能在执行任务中直接杀掉自己导致任务断链。

设计规则：

- runner 组件升级是独立任务。
- 组件升级 override 写到 `/data/compose-runtime`。
- 不写只读 `/opt`。
- runner-only 组件升级由 web-api 直接执行，只加载 `upgrade-runner` 镜像、写 `docker-compose.runner-upgrade.yml` 并重启 `upgrade-runner`。
- 平台升级和 Prometheus/observability 升级仍提交给 upgrade-runner 执行。
- runner 升级后写入 runner 版本记录。
- 页面显示 runner 版本、镜像 tag 和容器创建时间。

## 10. Prometheus 升级

Prometheus 属于 `observability` 组件。

升级前：

- 强制备份 Prometheus 数据目录。
- 检查数据目录 owner 可写。
- 检查历史 block 存在。
- 检查目标版本兼容说明。

升级时：

- 不删除 Prometheus 数据目录。
- 不执行 `down -v`。
- 只重启 Prometheus 服务。

升级后：

- 检查 `/-/ready`。
- 检查 `smartx_vm_storage_used_bytes` 即时查询。
- 检查最近 7 天 `query_range`。
- 检查 Dashboard、VM 趋势、报表数据链路。

Prometheus 历史指标回归要求：

- 升级前备份必须包含历史 block 和 `meta.json`。
- 升级后必须确认历史 block 数不减少。
- 升级后必须确认 `query_range` 在最近 7 天有返回；如果现场刚迁入且当前 instant 为空，允许用历史尾点回退计算页面数据，但必须在任务日志说明。
- 健康检查失败时不删除新 Prometheus 数据目录，保留备份路径供人工恢复。

## 11. 回滚

回滚范围：

- compose runtime override。
- 项目文件。
- 服务镜像 tag。
- 运行配置。

不自动回滚：

- 用户业务数据。
- Prometheus 历史数据。

数据恢复由导入前/升级前备份提供人工恢复路径。

回滚完成后必须重新做健康检查。

## 12. 组合升级顺序

组合包执行顺序：

1. 解析 manifest 并展开组件。
2. 预检查所有组件、镜像、compose、路径、磁盘空间和数据目录权限。
3. 生成升级前备份。
4. 加载镜像。
5. 同步项目文件。
6. 写入 `/data/compose-runtime` 下的 runtime override。
7. 执行迁移脚本。
8. 按组件边界重启服务。
9. 分组件健康检查。
10. 汇总任务结果并写入历史。

推荐重启顺序：

- `platform`：`web-api`、`collector-worker`、`frontend`。
- `observability`：`prometheus` 单独重启，重启后再验证历史指标。
- `runner`：由 web-api 单独执行 runner-only 升级，不与平台/Prometheus 同任务执行。

## 13. 失败恢复

任务恢复：

- 任务状态持久化到 SQLite `tasks` 和 `/data/upgrades/<task_id>/task.json`。
- web-api 重启后必须能恢复任务中心展示。
- 如果 task.json 缺失但 SQLite 仍有 pending/running 任务，任务中心允许标记为 cancelled 或 failed，避免永久卡住。

手动回滚：

- 恢复 compose runtime override。
- 恢复项目文件备份。
- 重新加载旧镜像 tag。
- 重启受影响服务。
- 重新执行健康检查。

边界：

- 不自动覆盖用户业务数据。
- 不自动删除 Prometheus 历史数据。
- `/data/backups` 是人工恢复来源，空间清理默认不删除。

## 14. 版本兼容边界

v2 升级中心只支持 v2 同架构后续升级。

- v1/v0.4.x 不走原地升级。
- 旧版本进入 v2 的路径是：全新部署 v2，导入数据迁移包。
- v2 数据迁移包兼容旧 SQLite、Prometheus 历史 block 和旧 `latest_vm_volumes.payload_json`。
