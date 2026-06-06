# SmartX HCI Capacity Insight - 项目发现与接手笔记

## 项目概览

SmartX HCI Capacity Insight 是一个面向 SmartX/HCI 容量趋势、虚拟机增长和存储预测的离线部署平台。

主要能力：

- Tower/集群配置与采集。
- 容量趋势、日增长、月增长、虚拟机 Top 列表。
- 集群预测报表和 Word/Excel 导出。
- 数据迁移导入导出。
- 服务管理、服务重启。
- 离线升级中心和组件升级。

## 服务与职责

- `frontend`：Nginx 托管的前端页面，默认对外端口 `8080`。
- `web-api`：FastAPI 后端，负责接口、鉴权、报表、数据迁移、升级控制。
- `collector-worker`：采集任务 worker，负责周期采集并写入指标。
- `prometheus`：保存历史时序指标，是趋势图、日增长、月增长、预测报表的重要数据来源。
- `upgrade-runner`：执行系统升级任务，避免 `web-api` 自己升级自己时任务中断。

## 数据路径

当前推荐持久化路径放在 `/data` 下：

- 应用业务库：`/data/smartx-capacity-insight-data/app`
- Prometheus 指标：`/data/smartx-capacity-insight-data/prometheus`
- 业务库文件：`/data/smartx-capacity-insight-data/app/smartx.db`
- 升级包和任务：容器内 `/data/upgrades`
- 升级前备份：容器内 `/data/backups`

## Docker 网络

为避免和用户环境常见网段冲突，`10.20.11.3` Docker 地址池已调整：

```json
{
  "bip": "10.249.0.1/24",
  "default-address-pools": [
    {
      "base": "10.249.0.0/16",
      "size": 24
    }
  ]
}
```

项目网络期望使用 `10.249.249.0/24`。

## Prometheus 权限坑

如果实际部署后趋势图、日增长、月增长、报表为空，先检查 Prometheus 是否在反复重启。

典型日志：

```text
Error opening query log file file=/prometheus/queries.active err="open /prometheus/queries.active: permission denied"
panic: Unable to create mmap-ed active query log
```

根因通常是宿主机 Prometheus 数据目录权限不对。`prom/prometheus` 容器通常需要 `65534:65534` 写权限。

已新增并提交 `pre_install.sh`，部署前应执行：

```bash
./pre_install.sh
```

它会创建并修复：

- `/data/smartx-capacity-insight-data/app`
- `/data/smartx-capacity-insight-data/prometheus`

## SELinux 与防火墙

部分部署机 SELinux 会影响 bind mount 写入。用户曾要求在测试机永久关闭 SELinux。

防火墙原则：

- 对外只需要开放 `8080/tcp`。
- 其他服务端口除调试场景外不建议对外暴露。

## 数据迁移注意事项

数据迁移不能只迁移 SQLite 业务库，否则新环境会出现：

- 趋势图为空。
- 日增长/月增长为空。
- 集群预测报表为空。

原因是这些能力依赖 Prometheus 历史指标。完整迁移需要同时包含：

- 业务库 `smartx.db`
- Prometheus 历史数据块

导入策略应尽量补全缺失数据，不覆盖现有系统已有数据。业务库导入应避免按整库覆盖；对于已存在集群，需要谨慎处理 cluster/tower 映射，避免导入后过滤条件不匹配导致历史指标查不到。

## 升级中心注意事项

第一版系统升级设计为离线 `.tar.gz` 升级包：

- `manifest.json`
- `images/*.tar`
- 可选 `scripts/migrate.sh`
- 可选 `release-notes.md`

平台升级和 Prometheus/observability 升级由 `upgrade-runner` 执行。`upgrade-runner` 不能可靠地执行“重启自己”的任务，因为 Docker 停掉旧 runner 后，正在执行 compose 的进程也可能被杀掉，导致新 runner 只创建不启动、任务停在 `restart running`。v2 当前策略是：runner-only 组件升级由 `web-api` 直接执行 Docker 操作，平台升级仍提交给 `upgrade-runner`。

后续已引入“组件升级”概念：

- 平台升级：升级业务服务。
- 组件升级：用于升级 `upgrade-runner` 等基础组件；runner-only 包由 `web-api` 直接执行，不能提交给 runner 自己执行。
- Prometheus 升级应并入全新升级模式，作为 `observability` 组件由 manifest 自动识别；不能混在普通平台升级里默认执行。

一般原则：

- 不执行 `docker compose down -v`。
- 不覆盖 `.env`。
- 不完整替换 `docker-compose.yml`。
- 不替换或清空核心数据目录。
- 上传升级包后应由 `manifest.json` 自动识别包含的组件：平台三件套、`upgrade-runner`、Prometheus 或组合包。
- Prometheus 组件升级必须由 `upgrade-runner` 执行，并在升级前强制备份 `/data/smartx-capacity-insight-data/prometheus`，检查 `65534:65534` 写权限、磁盘空间、版本兼容性和历史 block 状态。
- Prometheus 升级后必须验证 `/-/ready`、`/api/v1/query`、`/api/v1/query_range`，并查询 `smartx_vm_storage_used_bytes`，确认趋势图、日增长、月增长和报表数据链路仍可用。

## 离线部署注意事项

源码包内普通 `docker-compose.yml` 可能包含 `build`，在无外网环境会尝试拉取基础镜像并失败。

离线环境应使用 release/offline compose，并确保目标镜像已存在本机，例如：

```bash
docker compose -f docker-compose.offline.yml --project-name smartx-capacity-insight up -d
```

如果镜像只有 `latest` 标签，而 compose 指向 `v0.x.x` 标签，会触发拉取。需要统一镜像标签或先 `docker tag`。

## 报表与增长率口径

报表页容量增长速率当前需求：

- 按最近 7 天平均增长速率计算。
- 卡片提示显示 `7 天平均`。
- 趋势图窗口可以切换 `7 / 30 / 90 / 365 / 720` 天。
- 图表横坐标需要根据窗口大小调整显示间隔。

## 后续产品化方向

项目已经从“功能可用”进入“现场可交付、可运维、可升级”的阶段。后续待办需要合并为几个清晰主线，避免零散堆功能：

- 升级体系：统一升级包入口，manifest 自动识别平台、runner、Prometheus/observability 组件，升级任务由 runner 执行并支持可恢复状态、备份验证和回滚。
- 数据迁移灾备：导出/导入必须覆盖 SQLite 业务库和 Prometheus 历史指标，导入前备份、merge 规则、导入后健康验证需要形成闭环。
- 报表产品化：Word/Excel 报表要面向客户交付，风险摘要、统计窗口、图表风格、高风险 VM 和导出留存需要更清晰。
- 首页风险驾驶舱：首页需要一眼看到任一集群容量风险、最危险集群、预计耗尽时间、7 天增长和主要增长来源。
- 版本治理：平台版本、runner 版本、Prometheus 版本、compose tag、升级包 manifest、DockerHub tag、changelog 和验证记录必须保持一致。

## SQLite 存储体积发现

`10.20.11.3` 当前 SQLite 文件 `/data/smartx-capacity-insight-data/app/smartx.db` 约 135M，其中估算实际使用约 90M、空闲页约 45M。主要空间来自 `latest_vm_volumes`：

- `latest_vm_volumes` 约 94M，523 行。
- `payload_json` 合计约 93M。
- 最大单行 `payload_json` 约 268KB，顶层是虚拟卷列表，单台 VM 可包含 258 个卷对象。
- 每个卷对象包含 Tower 返回的较完整原始字段，例如 `cluster`、`lun`、`vm_disks`、`path`、`labels`、storage policy、size、used_size 等。

后续应优化 `latest_vm_volumes` 存储结构：只保存页面、报表、导出和分析真正需要的字段。旧版本迁移包导入时必须兼容旧 `payload_json`，从旧 JSON 抽取所需字段写入新结构，其他 Tower 原始字段直接丢弃。

## Git 规则

- 当前 v2 受控重建默认分支：`feature/upgrade-v2`。
- v2 工作默认提交并推送到 `feature/upgrade-v2`。
- 不要把 v2 工作同步到 `dev/main` 或打 tag，除非用户明确要求。
- 如果用户明确要求继续维护 v1 小版本，再切回 `dev` 并按用户指令处理。
- 推送 `main` 和 tag 前，要再次确认用户要求的 tag 名，避免版本号和分支再次漂移。

## 安全规则

- 不把 SSH 密码、平台密码、token 写入仓库文档。
- 不在文档中保存真实凭据。
- 不执行破坏性命令，例如 `git reset --hard`、删除 volumes、删除数据目录，除非用户明确要求。

## 版本治理发现

- DockerHub 已有平台镜像 tag `v0.5.0`，但仓库 dev 曾仍停留在 `v0.4.0` 元数据。
- `docker-compose.offline.yml` 和 `docker-compose.release.yml` 曾用同一个 `SMARTX_IMAGE_TAG` 控制平台服务和 `upgrade-runner`，会导致 runner 被平台版本牵引。
- runner 应作为独立组件，当前目标版本为 `v0.3.0`。
- 平台升级包不应包含 `upgrade-runner.tar`。
- `scripts/build_runner_component_package.py` 曾默认 `v0.2.0`，需要改为读取根目录 `RUNNER_VERSION`。
- GitHub Actions 曾在平台镜像矩阵中构建 `upgrade-runner`，导致 runner 仓库出现 `v0.4.0`、`v0.5.0`、`main`、`latest` 等平台语义 tag。
- 后续 DockerHub 错误 tag 清理方法记录在 `docs/version-governance.md`。

## v2 任务中心状态机发现

任务中心的数据来源不是 `/data/upgrades` 目录本身，而是 SQLite `tasks` 表：

- `tasks` 表记录全局任务中心列表。
- `/data/upgrades/<task_id>/task.json` 记录升级包/升级任务详情。
- 如果 `tasks` 表存在 `pending` 升级任务，但对应 `task.json` 已丢失，前端会一直从 `/api/tasks` 拉回这条 pending 任务；用户点“清空”不会删除 pending，因此看起来“删不掉”。

2026-06-07 在 `10.20.11.3` 现场确认：

- `tasks` 表有 19 条任务中心记录。
- 多数为 `status=pending`、`title=执行系统升级`、`progress=1`。
- 多数记录对应 `/data/upgrades/<task_id>/task.json` 已不存在。
- 直接清理 `tasks` 表后 `tasks_count=0`，任务中心不再拉回这些残留项。

当前 v2 任务中心语义：

- `清空` 只清理成功完成任务，即后端 `status=success` / 前端 `succeeded`。
- `failed`、`cancelled`、异常任务需要手动点任务右侧 X 删除。
- `pending` / `running` 不能通过清空删除。
- pending 的“执行系统升级 / 执行组件升级”右侧 X 是取消等待任务，不是普通删除。
- failed/cancelled 右侧 X 是从任务中心移除。

后端修复点：

- `UpgradeService.cancel()` 若读不到 `/data/upgrades/<task_id>/task.json`，会回退检查 SQLite `tasks` 表。
- 只有当 `tasks.status == pending` 时，才允许把孤儿升级任务标记为 `cancelled`。
- 新增单条任务删除 API：`DELETE /api/tasks/{task_id}`，只允许删除非 active 任务。

前端修复点：

- `startUpgrade()` / `startComponentUpgrade()` 使用后端真实 `task_id` 创建任务中心记录，避免 `upgrade-start-*` 临时 id 导致取消接口找不到任务。
- `addTask()` 同 id upsert，避免重复任务堆叠。
- `mergeTasks()` 允许后端完成态覆盖本地 active 状态，避免完成任务继续显示执行中。
