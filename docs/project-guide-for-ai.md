# SmartX HCI Capacity Insight 项目说明（AI 参考）

本文档面向 Codex 和其他 AI 工程代理，提供理解本项目所需的稳定背景、架构、版本边界、目录约定和文档索引。执行规则以仓库根目录 [AGENTS.md](../AGENTS.md) 为准；本文件解释“系统是什么”和“为什么这样设计”。

## 1. 项目目标

SmartX HCI Capacity Insight 是面向 SmartX 超融合环境的容量监控与预测平台。它通过 CloudTower/Tower v2 HTTP API 读取数据中心、集群、虚拟机和虚拟卷的容量信息，写入本地业务库和 Prometheus，并提供：

- 多 Tower、多集群容量概览。
- 定时采集和手动采集。
- 虚拟机存储趋势、卷明细和增长排行。
- 集群容量预测、风险识别和趋势报表。
- Word/Excel 报表导出。
- Tower 配置、账号管理、数据迁移和离线升级。
- 升级任务中心、升级历史、备份、健康检查和旧环境清理。

当前平台版本是 v0.5.3，独立升级执行器是 runner v0.3.1。项目目前处于测试阶段，生产使用必须以真实业务数据链路验证为前提。

### 环境角色

| 地址 | 环境 | 用途和边界 |
| --- | --- | --- |
| `10.20.11.3` | 开发/主测试机 | 默认执行所有测试、依赖安装、Docker 构建、升级包构建和完整升级链路。 |
| `10.20.11.12` | 升级演练机 | 用于经用户明确授权的升级演练；升级前必须记录版本、镜像、包 SHA、数据库和 Prometheus 状态。 |
| `10.20.0.6` | release canary/生产等价环境 | 用正式 tag 镜像做发布验收；默认只读诊断，不在现场热修或直接清理。 |

地址不是登录凭据。密码、Token、私钥和 Tower 凭据不得写入文档、提交或命令日志。

## 2. 技术结构

~~~text
CloudTower / Tower
        |
        v
collector-worker ----> SQLite 最新业务状态
        |                    |
        v                    v
Prometheus 历史时序 <---- web-api (FastAPI)
                             |
                             v
                     frontend (React + TypeScript)

upgrade-runner：独立执行升级任务，避免 web-api 在升级自己时中断任务
~~~

### 容器职责

| 容器 | 主要职责 | 关键事实 |
| --- | --- | --- |
| web-api | API、鉴权、业务查询、报表、迁移、升级入口 | 不直接执行自身镜像替换 |
| collector-worker | 调用 Tower、更新 SQLite、写入 Prometheus | 负责定时和手动采集 |
| frontend | 页面和服务管理界面 | 通过 API 查询任务和业务数据 |
| prometheus | 历史容量时序 | 趋势、增长和预测依赖它 |
| upgrade-runner | 备份、镜像加载、文件同步、Compose、健康检查、回滚 | 由旧 web-api 负责切换 runner |

后端是模块化单体。核心模块位于 backend/app/v2/：

| 模块 | 职责 |
| --- | --- |
| auth | 登录、Token、用户和密码 |
| inventory | Tower、集群、VM 最新元数据 |
| collection | Tower 采集、采集记录和采集触发 |
| metrics | Prometheus 写入、查询和趋势数据 |
| forecast / reports | 增长、预测、报表和导出 |
| migration | SQLite/Prometheus 数据迁入迁出 |
| upgrade | 升级包、预检查、执行计划、状态、历史和回滚 |
| tasks | 所有后台任务、步骤、日志和状态恢复 |
| system | 健康、重启、版本和运行时目录控制 |

## 3. 数据职责

### SQLite

SQLite 保存业务元数据和当前状态，包括用户、Tower 加密凭据、集群、VM 最新信息、VM 卷、采集记录、任务、报表历史、迁移历史和升级历史。

SQLite 不负责保存完整历史容量时序，也不替代 Prometheus。迁移和升级时必须检查 SQLite 完整性，并保留与 .env 配套的加密密钥。

### Prometheus

Prometheus 保存集群和 VM 的历史容量指标，用于趋势图、日/月增长和容量预测。VM 历史身份使用 tower_id + cluster_id + vm_id，VM 名称只用于展示，不能作为历史时序主键。

### Tower 凭据

Tower 凭据以加密形式进入 SQLite，解密所需的 SMARTX_CREDENTIAL_KEY 来自 .env。迁移数据库时，必须同时验证 .env 是否与数据库配套；不能留下旧数据库配新密钥，也不能因为密钥不兼容就悄悄生成默认密钥。

## 4. 目录标准

### v0.5.2 目标目录

~~~text
/data/smartx-storage-forecast/
├── project/
│   ├── docker-compose.yml
│   ├── docker-compose.offline.yml
│   ├── docker-compose.release.yml
│   ├── .env
│   ├── prometheus/
│   ├── scripts/
│   └── docs/
├── app/
│   └── smartx.db
├── prometheus/
├── upgrades/
├── backups/
├── exports/
└── compose-runtime/
~~~

目标运行配置：

~~~text
PROJECT_PATH=/data/smartx-storage-forecast/project
DATA_ROOT=/data/smartx-storage-forecast/app
COMPOSE_RUNTIME=/data/smartx-storage-forecast/compose-runtime
BACKUPS=/data/smartx-storage-forecast/backups
UPGRADES=/data/smartx-storage-forecast/upgrades
EXPORTS=/data/smartx-storage-forecast/exports
PROMETHEUS_DATA=/data/smartx-storage-forecast/prometheus
COMPOSE_PROJECT_NAME=smartx-hci-capacity-insight
NETWORK_NAME=smartx-hci-capacity-insight-net
SUBNET=10.249.251.0/24
~~~

### v0.5.1 及 v0.5.1u2 旧目录

桥包不能提前切换到 v0.5.2 目录。源环境和桥接环境仍使用旧 project/network/目录：

~~~text
PROJECT_PATH=/opt/smartx-storage-forecast
APP_DATA=/data/smartx-capacity-insight-data/app
COMPOSE_RUNTIME=/data/compose-runtime
UPGRADES=/data/upgrades
BACKUPS=/data/backups
EXPORTS=/data/exports
PROMETHEUS_DATA=/prometheus-data
COMPOSE_PROJECT_NAME=smartx-storage-forecast
NETWORK_NAME=smartx-storage-forecast_smartx-net
SUBNET=10.249.249.0/24
~~~

目录切换只属于 v0.5.2 的正式升级动作。旧路径只能在目标健康检查和数据迁移确认成功后清理。

## 5. 正常升级链路

~~~text
v0.5.1 + runner v0.3.0
  -> v0.5.1u2
  -> runner v0.3.1
  -> v0.5.2
  -> v0.5.3
~~~

### 节点职责

| 节点 | 做什么 | 明确不做什么 |
| --- | --- | --- |
| v0.5.1 | 提供旧平台和旧 runner 基线 | 不假设已经有 v0.5.2 目录 |
| v0.5.1u2 | 桥接旧平台，使旧 runner 能提交/编译后续升级任务，并兼容来源版本 | 不切平台 project/network，不清理旧目录，不升级 runner 自身 |
| runner v0.3.1 | 切换 runner 执行环境，提供 project migration、handoff、路径归一化和恢复能力 | 不迁移平台三件套，不删除旧平台目录 |
| v0.5.2 | 迁移平台目录、Compose project/network、SQLite、Prometheus，重建五个容器，健康后清理旧环境 | 不跳过数据门禁，不用手工覆盖 Compose 模拟成功 |
| v0.5.3 | 保持 v0.5.2 目标布局（project/network/目录不变），仅更新平台镜像与项目文件 | 无新增迁移，不重复目录切换 |

v0.5.1u2 + runner v0.3.1 也可以用 v0.5.3 包一步直升最新版本：v0.5.3 manifest 的 `source_compatibility` 覆盖 v0.5.0~v0.5.3，并携带 `environment_transitions`/`directory_transition`/`legacy_cleanup`（2026-09-15/2026-09-19 验证）。

### 状态变化

runner bootstrap 期间允许出现过渡状态：旧 project 继续运行平台三件套，新 project 临时运行 runner。v0.5.2 完成后，五个容器必须全部属于：

~~~text
project=smartx-hci-capacity-insight
network=smartx-hci-capacity-insight-net
~~~

v0.5.2 执行计划的逻辑顺序是：备份、加载镜像、准备文件系统、同步项目文件、迁移任务运行态、写运行时覆盖、迁移旧 project/network、启动目标服务、健康检查、同步任务状态、清理旧环境、触发升级后自动采集。

## 6. 升级执行模型

1. 用户上传平台包或组件包。
2. web-api 解析 manifest 并创建任务。
3. 预检查校验来源版本、runner 协议/能力、镜像、路径、磁盘、网络、Compose 和敏感文件。
4. upgrade-runner 取得任务租约，按 execution plan 执行动作。
5. 每个 action 写入 checkpoint、日志和任务步骤，支持恢复和幂等。
6. 平台服务重启可能使 API 短暂不可访问；前端升级轮询应允许重启窗口，但超时后必须显示真实错误。
7. 目标健康检查成功后，才允许将平台任务置为成功并执行旧环境清理。
8. v0.5.2 完成后由 worker 触发独立的“升级后自动采集”任务。该任务失败只产生采集告警，不回滚已经成功的平台升级。

组件升级与平台升级必须分开：

- runner 组件包只更新 upgrade-runner。
- 平台包不包含正在执行它的 runner 镜像。
- Prometheus 作为目标平台 Compose 服务启动和健康检查，不额外制造一个新的业务组件概念。

## 7. 版本来源和 .env 规则

版本身份不能由 web-api 的固定基线或任意 .env 值单独决定：

- 平台当前版本：运行镜像内 /app/VERSION，并与 Compose 镜像 tag、manifest 和健康接口一致。
- Runner 当前版本：运行 runner 的 /app/RUNNER_VERSION、heartbeat、实际运行容器镜像 tag 和组件接口一致。
- .env 保存密钥、管理员配置、数据库路径、Prometheus URL、采集时间等运行参数；不是版本真相源。
- 目标 Compose 文件必须能独立说明应该运行哪个镜像版本；发布包不能依赖现场随意修改 .env 来改变版本。

如果版本接口、Compose tag、镜像内版本文件和任务 manifest 不一致，先停止发布或升级，记录证据并查明来源，不能通过改显示值掩盖问题。

## 8. 关键历史问题结论

以下问题曾在升级链路中出现，后续设计必须避开：

- 用 web-api 内置 runner 版本显示活动 runner，导致 runner 已升级但页面仍显示旧版本。修复原则是以 heartbeat/容器实际状态为准。
- v0.5.1u2 错误携带 v0.5.2 project files 或新 runner 能力，导致桥包无法由 runner v0.3.0 执行。修复原则是桥包按目标版本选择旧 project files 和旧能力。
- web-api 使用新任务目录而旧 runner 仍扫描旧目录，导致任务提交后不可见。修复原则是 cutover 前双路径/任务运行态迁移，handoff 后统一到目标目录。
- 旧 runner 仍挂载待删除目录，导致 Device or resource busy。修复原则是先 handoff 到不挂载旧目录的目标 runner，再执行 cleanup。
- 只看到目标 smartx.db 存在就认为数据迁移成功，可能覆盖或丢失真实业务库。修复原则是比较来源/目标业务计数、SQLite 完整性和配套 .env，不满足条件就 fail closed。
- v0.5.2 只按平台三件套执行 Compose，旧 Prometheus 被删除后没有新 Prometheus。修复原则是目标 Compose 必须声明 Prometheus，并将其纳入平台服务启动和健康检查。
- 升级后没有自动采集，导致恢复的数据和当前 VM 名称不刷新。修复原则是生成独立的 post-upgrade-collection-<task_id> 任务并验证结果。
- 任务历史按文件 mtime 排序或读取时触发清理，导致顺序错乱和读取副作用。修复原则是使用任务内时间字段排序，查询接口必须只读。
- runner 容器把宿主机 app 目录挂载在 `/data`，`filesystem.prepare` 用容器内路径扫描 legacy 候选时会命中在线数据自身（UPG-049）。修复原则是 legacy 候选解析结果与 `SMARTX_DB_PATH`/`SMARTX_PROMETHEUS_DATA_PATH` 指向同一文件时跳过，凭据配对守卫语义不变。
- `app/{upgrades,backups,exports,compose-runtime,smartx-storage-forecast}` 是 dockerd 经 app bind 补建的挂载点载体：容器运行期 `rm`/`mv` 会拆掉共享该 bind 的全部容器的对应挂载（UPG-050）。修复原则是这些目录只保留不清理；衰减后用全服务 `docker compose up -d --force-recreate` 恢复，并以容器内 `/proc/mounts`（而非 docker inspect）验证，工具见 `scripts/bind-mount-recover.sh`。

## 9. AI 应查阅的文档地图

全部文档的完整索引（含每份文档的用途和关联任务）见 [docs/doc-map.md](doc-map.md)。以下为常用入口。

### 项目和架构

- [README.md](../README.md)：对外项目简介、快速启动和升级包格式。
- [docs/architecture-v2.md](architecture-v2.md)：v2 架构、容器和数据职责。
- [docs/deployment.md](deployment.md)：部署、目录、Compose 和运行时配置。
- [docs/functional-modules.md](functional-modules.md)：功能模块说明。
- [docs/v2-api-contracts.md](v2-api-contracts.md)：API 契约。
- [docs/version-governance.md](version-governance.md)：版本治理。

### 升级计划和实现

- [docs/v0.5.0-to-v0.5.2-upgrade-plan.md](v0.5.0-to-v0.5.2-upgrade-plan.md)：总体升级计划。
- [docs/v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md](v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md)：u2 到 v0.5.2 的专项修复计划。
- [docs/v0.5.1-to-v0.5.2-upgrade-chain-worklog.md](v0.5.1-to-v0.5.2-upgrade-chain-worklog.md)：执行记录、失败证据、任务 ID 和验证结果。
- [docs/v0.5.1-to-v0.5.2-upgrade-chain-task-findings.md](v0.5.1-to-v0.5.2-upgrade-chain-task-findings.md)：链路任务和发现归档。
- [docs/upgrade-runner-lifecycle.md](upgrade-runner-lifecycle.md)：web-api、runner 和平台包边界。
- [docs/superpowers/plans/2026-07-10-post-upgrade-auto-collection.md](superpowers/plans/2026-07-10-post-upgrade-auto-collection.md)：升级后自动采集计划。
- [docs/superpowers/specs/2026-07-10-post-upgrade-auto-collection-design.md](superpowers/specs/2026-07-10-post-upgrade-auto-collection-design.md)：自动采集设计。

### 问题和包台账

- [docs/upgrade-issues.md](upgrade-issues.md)：全部升级问题和根因。
- [docs/v0.5.1u2-to-v0.5.2-upgrade-issues.md](v0.5.1u2-to-v0.5.2-upgrade-issues.md)：u2 到 v0.5.2 专项问题。
- [docs/upgrade-package-ledger.md](upgrade-package-ledger.md)：包路径、SHA、状态和废弃原因。
- [docs/releases/CHANGELOG.md](releases/CHANGELOG.md)：发布变更。
- [docs/project-progress-2026-08-12.md](project-progress-2026-08-12.md)：阶段性项目进度摘要。

## 10. 推荐验证命令

在测试机 10.20.11.3 的项目目录执行，具体命令以当前 Compose project 和文档为准：

~~~bash
git status --short --branch
git diff --check
curl -fsS http://127.0.0.1:8000/api/system/health
curl -fsSI http://127.0.0.1:8080 | head -n 1
curl -fsS http://127.0.0.1:9090/-/healthy
~~~

升级包验证至少包括：

- manifest.json 版本、来源兼容、最低 runner 能力和包类型。
- checksums.sha256 和外部 .sha256。
- 镜像 tar 的实际 RepoTag 和镜像内 VERSION/RUNNER_VERSION。
- project 文件中的 project/network、目录挂载、服务列表和敏感路径。
- 是否错误打包 runner、Prometheus、.env、SQLite、Prometheus 数据或其他秘密。
- 正常 API/UI 链路的预检查、执行、重启窗口、任务终态、清理和自动采集。

## 11. 当前状态摘要

截至本项目进度文档记录的最近一次闭环：

- 正常升级链路已在测试环境完成：v0.5.1 + runner v0.3.0 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2 -> v0.5.3（2026-09-19，v0.5.1u2 + runner v0.3.1 直升路径同样已验证）。
- 目标健康检查包含目录、数据库和 Prometheus，最终 runner 为 v0.3.1。
- v0.5.2 目标 project/network 为 smartx-hci-capacity-insight / smartx-hci-capacity-insight-net。
- 升级后清理和升级后自动采集均属于验收范围。
- 具体包 SHA、最新 fix 编号和某次验证的业务计数，以 [docs/upgrade-package-ledger.md](upgrade-package-ledger.md)、[task_plan.md](../task_plan.md) 和升级 worklog 的最新记录为准；旧 fix 包不能因为出现在历史文档中就当作当前可交付包。
