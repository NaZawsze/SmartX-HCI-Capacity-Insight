# v2 升级中心设计

更新时间：2026-06-06

## 1. 目标

v2 升级中心重新设计，不兼容旧升级路径。目标是一次上传后，由 manifest 自动识别升级内容，完成预检查、备份、执行、健康检查、历史记录和回滚准备。

支持升级对象：

- `platform`：`web-api`、`collector-worker`、`frontend`
- `runner`：`upgrade-runner`
- `observability`：Prometheus

未在 manifest 中声明的组件一律不动。

## 2. 升级包结构

统一使用 `.tar.gz`。

```text
manifest.json
release-notes.md
images/
  web-api.tar
  collector-worker.tar
  frontend.tar
  upgrade-runner.tar
  prometheus.tar
project/
  docker-compose.offline.yml
  docker-compose.release.yml
  docker-compose.yml
  prometheus/prometheus.yml
  pre_install.sh
  docs/**
  scripts/**
scripts/
  migrate.sh
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
  "schema_version": "2",
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
  "migration": {"required": false, "script": "scripts/migrate.sh"},
  "restart_services": ["web-api", "collector-worker", "frontend"],
  "compatibility": {"min_platform_version": "v2.0.0"},
  "notes": "release-notes.md"
}
```

规则：

- 平台版本和 runner 版本分开。
- 平台包不默认包含 runner。
- Prometheus 作为 `observability` 组件声明。
- 镜像名、tag、archive、sha256 必须闭环。
- `project_files=true` 时必须包含 `project/` 白名单文件。

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
- 查询状态、日志和历史。

upgrade-runner 负责：

- 数据备份。
- 加载镜像。
- 同步项目文件。
- 执行迁移脚本。
- 写 compose runtime override。
- 重启服务。
- 健康检查。
- 回滚。

runner 执行 Docker 操作时必须使用宿主机视角路径，不使用容器内 `/opt` 作为 Docker compose 工作目录。

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
- web-api 不直接执行复杂 Docker 升级动作，只创建任务。
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
