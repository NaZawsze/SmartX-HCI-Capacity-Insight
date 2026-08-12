# upgrade-runner 生命周期与组件升级策略

本文档说明平台升级包与 `upgrade-runner` 的关系，避免把业务平台升级和升级执行器升级混在一起。

## 角色说明

- `web-api`：提供 API、报表导出、数据迁移、平台升级入口和组件升级入口。
- `frontend`：提供 Web 页面。
- `collector-worker`：执行 Tower、集群、虚拟机和虚拟卷容量采集。
- `prometheus`：保存历史指标。
- `upgrade-runner`：执行平台升级任务，包括加载镜像、写入覆盖配置、重启平台服务和健康检查。

## 平台升级

平台升级默认更新以下服务：

```text
web-api
collector-worker
frontend
```

平台升级包通常不包含 `upgrade-runner`。这样做的原因是平台升级正在由 `upgrade-runner` 执行，如果在同一次任务中重启执行器，可能导致升级任务中断或日志状态不完整。

平台升级适合处理：

- 页面和 API 功能更新。
- 报表、预测、数据迁移等业务逻辑更新。
- 采集逻辑更新。
- 平台服务镜像版本更新。

## 组件升级

组件升级用于单独更新 `upgrade-runner`。第一版组件升级只支持 `upgrade-runner`，不修改业务库、不修改 Prometheus 历史指标、不替换平台数据卷。

组件升级包结构：

```text
manifest.json
checksums.sha256
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
```

## 什么时候升级 upgrade-runner

只有涉及升级执行能力本身时，才需要升级 `upgrade-runner`：

- 升级流程变化，例如新增步骤、回滚策略或健康检查方式。
- `manifest.json` 格式变化。
- Compose 覆盖文件写入规则变化。
- volume、网络、挂载路径或容器拓扑变化。
- 需要支持新的被升级组件或新的升级包类型。
- `upgrade-runner` 自身依赖或安全修复。

以下场景通常不需要升级 `upgrade-runner`：

- 只更新前端页面。
- 只更新 API 或报表逻辑。
- 只更新采集逻辑。
- 只更新业务版本号。
- 只修复普通业务 bug。

## 版本显示

- 平台版本优先来自镜像内 `/app/VERSION`，由根目录 `VERSION` 在镜像构建时写入；`SMARTX_APP_VERSION` 只作为版本文件缺失时的兜底。
- 升级中心组件版本来自 `/data/upgrade-runner.version`；没有该文件时使用默认 runner 版本，默认值由根目录 `RUNNER_VERSION` 维护。
- 服务管理页的“平台状态”会显示当前运行镜像、平台版本、runner 版本和最近一次成功升级包信息。

## 发布建议

- 每个版本先判断是否需要 runner 能力变化。
- 如果不需要 runner 能力变化，只制作平台升级包。
- 如果需要 runner 能力变化，先制作并验证组件升级包，再制作平台升级包。
- 不要为了让版本号一致而强制升级 `upgrade-runner`；runner 是升级执行组件，不是每个业务版本都必须同步更新的业务服务。

## v0.3.0 稳定执行协议

`upgrade-runner v0.3.0` 提供以下稳定能力：

- 原子任务文件、revision、Action checkpoint。
- Runner 心跳和 SQLite 任务租约。
- 备份、镜像加载、白名单文件同步、Compose override/apply。
- 无网络、只读根文件系统、无 Docker Socket 的迁移脚本沙箱。
- HTTP 与 Prometheus 健康检查。
- 自动回滚一次和人工恢复操作。

后续平台升级包通过 `minimum_runner_protocol` 和 `required_capabilities` 判断兼容性。只要当前 Runner 已具备升级包要求的能力，就不需要先升级 Runner。

## v0.3.1 通用执行能力

`upgrade-runner v0.3.1` 在 v0.3.0 基线之上改为上报大类能力：`backup.v1`、`image.v1`、`files.v1`、`compose.v1`、`compose.project.v1`、`health.v1`、`rollback.v1`、`task.recovery.v1` 和 `script.sandbox.v1`。旧升级包中声明的 `backup.create`、`compose.apply`、`compose.project_migrate.v1` 等细粒度能力由协议层映射到这些大类能力，避免后续每新增一个 compose 小动作都必须升级 Runner。

`compose.project.v1` 用于处理 `v0.5.0/v0.5.1 -> v0.5.2` 时 Compose project/network 从旧名迁移到新名的场景。该能力会在 `compose.apply` 前停止并删除旧 project 容器；旧网络为空时删除旧网络。如果旧网络仍连接外部容器，升级会失败并保留人工处理线索，避免直接破坏非平台容器。

需要该能力的 `v0.5.2` 平台升级包会在 manifest 中声明 `required_capabilities=["compose.project.v1", ...]` 和 `minimum_runner_version="v0.3.1"`，因此 `upgrade-runner v0.3.0` 会在预检查阶段被拦截，不会执行到网络冲突才失败。

Runner 组件包由旧 `web-api` 直接加载镜像、写入 `/data/smartx-storage-forecast/compose-runtime/docker-compose.runner-upgrade.yml` 并 recreate Runner。Runner 不执行自己的升级。
