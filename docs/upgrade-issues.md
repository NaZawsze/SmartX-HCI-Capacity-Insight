# 升级模块问题台账

本文记录当前升级中心、组件升级、升级包和部署文件相关问题。后续修复升级模块时以本文为问题清单，逐项关闭，避免只修表象而遗漏根因。

更新时间：2026-06-06

## 问题状态说明

- `待修复`：已经确认问题存在，需要代码或流程修复。
- `已解决`：代码、镜像或包已经完成修复；如仍需现场完整链路验证，会在条目中单独说明。
- `修复包已生成`：已有临时/组件包修复，但仍需要现场验证或根修复。
- `需验证`：代码或包已调整，需要在真实升级流程验证。
- `设计约束`：当前设计刻意如此，但需要在文档和 UI 中解释清楚。

## UPG-001 旧 web-api 组件升级写入只读 /opt

状态：[已解决] v2 已改为 `/data/compose-runtime`，runner-only 组件升级已在 `10.20.11.3` 真实验证

现象：从 `upgrade-runner v0.1.0` 升级到 `v0.2.0` 时，页面组件升级失败，报错：

```text
[Errno 30] Read-only file system: '/opt/smartx-storage-forecast/docker-compose.runner-upgrade.yml'
```

根因：旧 `web-api` 的组件升级逻辑把 runner override 写到项目目录 `/opt/smartx-storage-forecast`。实际部署中该目录可能是只读挂载，或者不是运行时文件应该写入的位置。

影响：
- web 页面无法完成 runner 组件升级。
- runner 坏了时，无法通过页面升级 runner 来破局。
- 这不是 `v0.2.0` runner 镜像本体的问题，而是旧 `web-api` 执行组件升级的路径设计问题。

根修方向：
- [已完成代码修改] 组件升级运行时文件写到 `/data/compose-runtime/docker-compose.runner-upgrade.yml`。
- [已完成代码修改] `docker compose -f` 读取同一个 `/data/compose-runtime/docker-compose.runner-upgrade.yml`。
- [已完成代码修改] 不再向 `/opt/smartx-storage-forecast` 写运行时 compose override。

验证记录：
- 已用最小复现证明旧逻辑会写 project path，不会写 `/data/compose-runtime`。
- 修改后同一复现通过：runtime override 存在，project override 不存在。
- 新增 `backend/tests/test_upgrade.py` 回归测试覆盖写入路径和 compose 命令引用路径。
- `docker compose build web-api` 通过。
- v2 在 `10.20.11.3` 使用 runner 组件包 `smartx-upgrade-runner-v0.3.0.tar.gz` 真实执行成功，写入 `/data/compose-runtime/docker-compose.runner-upgrade.yml`，runner 容器切换到 `nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.0`。

## UPG-002 runner v0.2.0 升级前备份函数缺失

状态：[已解决] 历史 v0.2.x 问题已修复；v2 当前 runner 为 `v0.3.0`

现象：平台升级卡在“升级前备份”，日志报错：

```text
name '_write_upgrade_backup_archive' is not defined
```

根因：`upgrade-runner v0.2.0` 调用了 `_write_upgrade_backup_archive()`，但镜像中的 `backend/app/services/upgrade.py` 缺少该函数定义。

影响：即使手动升级到 `v0.2.0`，平台升级仍会在备份阶段失败。

当前处理：
- v2 使用独立 `RUNNER_VERSION=v0.3.0`。
- runner 组件包由 `scripts/build_runner_component_package.py` 生成，manifest 类型为 `runner`，只包含 `images/upgrade-runner.tar`。
- `10.20.11.3` 已真实执行 runner 组件升级并验证成功。

## UPG-003 旧 runner 重启平台服务时会带起依赖服务

状态：[已解决] v2 升级执行链按 manifest 服务集合重启，平台升级不会带起未声明组件

现象：平台升级重启阶段可能重新创建 Prometheus，触发错误的 bind mount 或网络冲突，导致升级后页面打不开。

根因：旧 runner 执行 compose 重启服务时没有使用 `--no-deps`，升级 `web-api`、`frontend`、`collector-worker` 时可能连带处理 `prometheus` 等依赖服务。

影响：
- 本不该动 Prometheus 的平台升级可能动到 Prometheus。
- 如果项目目录、compose 文件或网络名和当前部署不一致，重启阶段容易失败。

当前处理：
- v2 平台升级只重启 `web-api`、`collector-worker`、`frontend`。
- runner-only 组件升级只重启 `upgrade-runner`。
- Prometheus/observability 组件升级只重启 `prometheus`。
- `10.20.11.3` 已分别真实执行平台包、runner 组件包和 Prometheus 组件包验证。

## UPG-004 Docker socket 视角下项目路径不一致

状态：[已解决] v2 runner 已区分 Docker 视角 compose 路径和容器内 cwd，远端验证通过

现象：容器内看到的项目路径是 `/opt/smartx-storage-forecast`，但 Docker daemon 真正需要宿主机路径，例如 `/data/SmartX-HCI-Capacity-Insight-main`。升级重启时 compose 里的相对 bind mount 可能解析到错误路径。

根因：runner 在容器内通过 Docker socket 调用宿主机 Docker，但 compose 文件里的相对路径需要按宿主机项目路径解释，而不是容器内路径。

影响：
- Prometheus 配置挂载可能找不到文件。
- 项目文件同步后 compose up 可能使用错误目录。

当前处理：v2 runner 通过 `/data/compose-runtime/*.yml` 写入 Docker daemon 可见的 compose override，同时使用容器内存在的项目路径作为 `cwd`。`10.20.11.3` 的平台、runner、Prometheus 升级任务均已验证该路径模型可用。

## UPG-005 升级包镜像名与 compose 镜像名不闭环

状态：[已解决] v2/v0.5.0 升级包、compose、GitHub Actions 和 manifest 已统一镜像名

现象：用户现场遇到过升级包导入的是 `smartx-storage-forecast-*` 或本地 tag，但 compose 里写的是 `nazawsze/smartx-hci-capacity-insight-*`，导致镜像加载成功但服务启动找不到对应镜像。

根因：历史版本中升级包 manifest、打包脚本、compose 文件、GitHub Actions 使用过不同镜像名前缀和 tag 策略。

影响：
- 升级后容器无法启动。
- 页面打不开，只能进后台排查镜像名和 compose。

根修方向：
- 平台镜像统一为 `nazawsze/smartx-hci-capacity-insight-<service>:<version>`。
- `docker-compose.offline.yml`、`docker-compose.release.yml`、升级包 manifest、GitHub Actions、打包脚本必须使用同一套镜像名。
- 预检查必须校验 manifest 镜像名与目标 compose 一致。

验证记录：
- `10.20.11.3` 已生成并执行平台升级包 `smartx-capacity-insight-upgrade-v0.5.0.tar.gz`。
- 平台包 manifest 只包含 `web-api`、`collector-worker`、`frontend` 三个 `nazawsze/smartx-hci-capacity-insight-*:<version>` 镜像，不包含 runner。
- 升级任务加载镜像、写入 runtime override、重启平台三件套后健康检查通过。

## UPG-006 offline compose 仍可能使用 latest 或旧 tag

状态：[已解决] v2 离线/release compose 使用明确版本，不再使用 `latest` 作为默认部署 tag

现象：升级包加载了 `v0.4.0` 镜像，但 `docker-compose.offline.yml` 里仍是 `latest` 或旧版本，升级后重新 `docker compose up -d` 会回退到旧镜像或继续使用 `latest`。

根因：历史升级流程只写 `docker-compose.upgrade.yml`，不会同步项目目录里的 `docker-compose.offline.yml`、`docker-compose.release.yml` 等项目文件。

影响：
- 升级页面显示版本和实际 compose 文件不一致。
- 后续手工重启可能回退版本。
- 离线部署无法保证明确版本。

根修方向：
- 升级包包含 `project/` 白名单项目文件。
- 升级流程增加“同步项目文件”步骤。
- v2 平台升级以当前 `upgrade-runner v0.3.0` 和 `project/` 白名单同步为执行基线。
- 打包脚本生成包时自动把 compose 默认 tag 替换为目标 `VERSION`。

## UPG-007 平台升级不会自动更新项目文件

状态：[已解决] v2 平台升级包包含 `project/` 白名单文件，并已真实执行项目文件同步

现象：Web 升级只加载镜像和写覆盖配置，不会更新项目目录内的 compose、脚本、Prometheus 配置、README、docs。

根因：早期升级包没有携带项目文件，runner 也没有“项目文件同步”步骤。

影响：
- docker-compose 文件和实际镜像版本漂移。
- 新的 `pre_install.sh`、`prometheus.yml`、文档和打包脚本无法通过 Web 升级下发。
- 后续部署和回滚判断依据不一致。

根修方向：
- 升级包新增 `project/` 目录，仅包含白名单文件。
- 同步前备份旧项目文件到 `/data/backups/project-files-before-版本-时间/`。
- 回滚时同时恢复项目文件。
- 禁止覆盖 `.env`、数据库、Prometheus 数据、Tower 凭据和任何 secret/token/password 文件。

验证记录：
- `10.20.11.3` 平台升级任务 `upgrade-9c1b8ce0fb6f7b47` 成功同步项目文件。
- 同步前备份路径为 `/data/backups/project-files-before-v0.5.0-20260606090010`。

## UPG-008 升级前备份进度不透明且可能卡住

状态：[已解决] 备份扫描和写入过程已上报进度、小日志和当前文件

现象：升级任务卡在“升级前备份”，页面缺少精确进度和小日志，用户只能看到步骤长时间不动。

根因：备份过程是大文件 tar/gzip 操作，历史实现没有按文件或字节上报进度；旧实现还可能把 `/data/upgrades`、`/data/backups`、`/data/exports` 等运行时目录打进备份，导致备份变大甚至递归式膨胀。

影响：
- 大数据量现场用户无法判断是正常压缩还是失败。
- 升级包、报表导出、数据迁出留档可能显著放大备份体积。

当前处理：v2 备份写包会跳过 `upgrades`、`backups`、`exports` 等运行时目录，并在任务步骤中更新扫描总量、字节进度、当前文件和小日志。

修复：
- 备份前扫描需要备份的文件总数和总字节数。
- 备份时按已处理字节数更新百分比、当前文件、小日志；即使单个大文件也会按读取进度刷新。
- 页面“升级前备份”步骤显示真实进度，而不是只显示步骤状态。
- 任务中心会展示当前运行步骤详情，备份期间可直接看到 `备份中 xx%`。

## UPG-009 升级包上传 95% 后看似卡住

状态：[已解决] 前端上传进度已区分 uploading/processing/done 并显示上传速度

现象：上传大升级包时页面到 95% 会停一段时间。

根因：浏览器上传完成后，后端仍在保存、解压、读取 manifest、校验包结构和 sha256。前端历史上仍显示“上传中 95%”，没有切换到“服务器处理中”。

影响：用户会误以为上传卡死。

根修方向：
- 上传阶段显示速度，例如 `上传中 95% · 12.4 MB/s`。
- XHR 上传完成后到接口返回前显示 `上传完成，正在保存、解压并校验升级包...`。
- 平台升级包和组件升级包共用同一套上传进度状态。

## UPG-010 平台升级和升级后核验内容重复

状态：[已解决] 平台升级顶部已合并版本、升级包和服务运行核验

现象：服务管理页“平台升级”的内容和“升级后核验”内容重复，页面层级和信息密度不佳。

根因：升级状态、当前版本、目标版本、运行镜像、核验结果分散在多个二级框里。

影响：用户难以判断当前应该看哪里，也增加 UI 维护成本。

修复：
- 合并平台升级与升级后核验展示。
- 平台升级顶部改为“平台状态”，集中显示当前版本、目标版本、最近成功包、升级中心版本、compose 项目和运行镜像表。
- 刷新核验改为“刷新状态”，放在同一行操作区，不再单独形成二级框。

## UPG-011 预检查没有步骤化进度

状态：[已解决] 预检查已按真实检查项分组展示步骤

现象：预检查只显示结果，不像开始升级那样展示逐项检查流程。

根因：预检查接口和 UI 没有按检查项返回/展示阶段状态。

影响：预检查耗时时用户不知道正在检查什么；失败时定位不够直观。

修复：
- 预检查显示类似升级步骤的流程：版本、sha256、磁盘、Docker、compose、volume、项目文件、敏感路径。
- 正在检查用 loading，成功用绿色勾，失败用红色 X，未执行为空心圆。
- 后端平台预检查增加 `network` 检查，同时校验当前 compose 和升级包 offline compose 使用 `10.249.249.0/24`，并拦截 `172.16/172.17` 网段。
- 前端预检查步骤按后端检查项分组：升级包结构、版本兼容、镜像名/Tag/SHA256、Docker/runner、compose/数据卷/网络、项目文件/敏感路径、磁盘/迁移脚本。
- 步骤失败时直接显示对应检查项信息，详细检查列表仍保留在步骤下方。

## UPG-012 组件升级版本显示仍为 v0.1.0

状态：[已解决] 组件升级/手动切换后写入 /data/upgrade-runner.version，10.20.11.12 已显示 runner v0.2.2 行为

现象：用户反馈页面上的组件版本仍显示 `v0.1.0`。

可能原因：
- 组件升级本身失败，`upgrade-runner` 没有实际升级。
- 手动更新镜像或容器后，没有写 `/data/upgrade-runner.version`。
- web-api 读取 runner 版本来源和实际容器镜像版本没有打通。

影响：用户无法确认 runner 是否真正升级。

根修方向：
- 组件升级成功后写 `/data/upgrade-runner.version`。
- 版本接口同时返回版本文件、运行镜像 tag、容器创建时间，避免只看单一字段。
- 手动升级文档中补充如何同步版本文件。

## UPG-013 清理旧镜像显示可释放 0B

状态：[已解决] 清理逻辑改为删除扫描出的未使用镜像，空间清理不再用清理后重扫结果覆盖本次释放量

现象：清理旧版本镜像时，页面显示可清理空间为 `0B`。

根因：
- Docker image size 和 shared layer reclaimable size 没有区分。
- 后端扫描列出了未被容器使用的带 tag 旧镜像，但执行清理时调用的是 Docker `/images/prune`；prune 对带 tag 镜像常常不会删除，返回 `SpaceReclaimed=0`。
- 服务管理的“空间清理”成功后立刻重新扫描，清理后的扫描结果自然是 `0B`，覆盖了本次“已释放 X”的结果。

影响：用户无法判断清理价值，也不敢执行清理。

修复：
- 镜像清理先复用扫描候选列表，再逐个调用 Docker `DELETE /images/{id}` 删除未被容器使用的镜像。
- 返回 `space_reclaimable_before`、`space_reclaimable_before_label`、`space_reclaimed_label` 和删除失败 `errors`。
- 前端弹窗区分显示“候选逻辑大小”和“实际/预计释放”，并保留清理结果。
- 服务管理“空间清理”清理完成后显示 `space_reclaimed_label`，不再立刻重扫覆盖为 `0B`。

## UPG-014 Docker 网络名称或网段冲突

状态：[已解决] compose 网络使用 10.249.249.0/24，升级预检查已校验当前 compose 和升级包网络

现象：升级或 runner 重启时可能遇到网络名称被占用、旧网络残留、172.16/172.17 网段冲突。

根因：不同部署目录、不同 compose project name、历史网络未清理或 Docker daemon 默认 `bip`/address pools 与客户网络冲突。

影响：容器启动失败或网络不可达。

当前处理：项目网络规划使用 `10.249.249.0/24`，Docker daemon 可使用 `10.249.0.0/16`。升级预检查会检查当前 compose 和升级包 `project/docker-compose.offline.yml` 是否包含目标网段，并拒绝包含 `172.16/172.17` 的 compose。

## UPG-015 Prometheus 组件升级策略未定义

状态：[已解决] v2 已支持 Prometheus/observability 组件升级并在 `10.20.11.3` 真实验证

历史现状：早期平台升级主要更新 `web-api`、`collector-worker`、`frontend`，组件升级第一版只支持 `upgrade-runner`。

问题：如果未来需要升级 Prometheus 镜像或配置，当前升级包能力不够完整。

修复：
- 新增 `scripts/build_prometheus_component_package.py`。
- Prometheus 组件包 manifest 使用 `components[0].type = observability`，只包含 `images/prometheus.tar`。
- component-upgrade 上传后返回 `kind=component`、`component=prometheus`。
- Prometheus/observability 组件包提交给 `upgrade-runner` 执行，runner 负责备份、加载镜像、写 override、重启 Prometheus 和健康检查。
- 默认平台升级仍不包含 Prometheus，避免误动历史指标。

验证记录：
- `10.20.11.3` 已生成 `/data/upgrade-packages/components/smartx-prometheus-v2.55.1.tar.gz`。
- 真实执行 Prometheus 组件包任务 `upgrade-91593ac4799312d2` 成功。
- 升级前备份路径为 `/data/backups/upgrade-v2.55.1-before-20260606093851.tar.gz`。
- Prometheus 重启后 healthy，`smartx_vm_storage_used_bytes` 最近 2 天 `query_range` 返回 175 条 series。

## UPG-016 数据迁移后增长和趋势为空

状态：[已解决] 已在 10.20.11.3 完成导出、隔离导入和 Prometheus 历史指标回归验证

现象：新部署导入迁移数据后，日增长、月增长、集群预测报表、趋势图为空。

已知原因：这些页面依赖 Prometheus 历史指标，不只依赖业务库 `smartx.db`。如果迁移包只包含业务库，或者 Prometheus 数据目录权限错误，增长和趋势会为空。

当前处理：数据迁移包包含业务库和 Prometheus 历史指标；`pre_install.sh` 负责修正 Prometheus 数据目录权限；导入前会自动生成当前系统备份，备份成功后才执行 merge/overwrite。v2 报表服务在 Prometheus 当前 instant 样本为空时，会用历史窗口内每条 series 的最后一个样本回退计算 VM 增长和集群总容量，避免刚导入后页面空白。

验证记录：
- 2026-06-05 在 `10.20.11.3` 通过后台迁移导出任务生成 `/data/exports/migrations/smartx-storage-migration-20260605113838.tar.gz`。
- 导出包检查：包含 `smartx-data/smartx.db`，包含 7 个 Prometheus block 的 `meta.json`，不包含 Prometheus `wal` 运行时目录。
- 使用 merge 模式导回当前系统，导入成功并生成导入前备份 `/data/backups/import-before-20260605114014-0ac6678f.tar.gz`。
- 同包回导时业务库已有数据被跳过，Prometheus 7 个已有 block 被跳过，未覆盖现有数据。
- 重启 `web-api`、`collector-worker`、`prometheus` 后，`smartx_vm_storage_used_bytes` 即时查询返回 175 条 series。
- `query_range` 最近 7 天返回 175 条 series，前 10 条 series 共 260 个历史点。
- 报表接口返回 `clusters=1`、`day_fastest_growing_vms=100`，集群趋势点数为 13；`month_fastest_growing_vms=0` 符合当前“样本满 30 天”新口径。
- 2026-06-06 使用 `/data/exports/migrations/smartx-capacity-insight-migration-20260606075715-438dc55b.tar.gz` 在 `/data/v2-migration-verify` 做隔离导入验证：导入后 SQLite 有 `towers=1`、`clusters=1`、`vm_latest=523`、`vm_volumes=89530`，Prometheus 历史 block `7` 个，健康检查 `complete=true`。
- 2026-06-06 用隔离 Prometheus 查询历史 block，`smartx_vm_storage_used_bytes` 90 天窗口返回 `525` 条历史 series，最大样本时间 `2026-06-06 13:07:52`；修复后报表在 instant 为空时以历史尾点回退，返回 `clusters=1`、`cluster_points=15`、`day_growth=100`。
- 同一隔离包 `month_growth=0` 是符合规则的结果：迁移包历史跨度约 15 天，不满足月增长榜固定 `>=30` 天样本跨度要求。

## UPG-017 文档中 runner 版本来源描述陈旧

状态：[已解决] runner 生命周期文档已按镜像内置平台版本和独立 runner 版本更新

现象：`docs/upgrade-runner-lifecycle.md` 仍描述平台版本来自 `SMARTX_APP_VERSION`，但当前目标设计是平台版本优先来自镜像内置 `VERSION`。

影响：维护人员会误以为 compose 里还必须写 `SMARTX_APP_VERSION`。

修复：
- 更新 runner 生命周期文档：平台版本来自镜像内 `/app/VERSION`，`SMARTX_APP_VERSION` 只作为兜底覆盖。
- runner 组件版本仍独立来自 `/data/upgrade-runner.version` 或 runner 自身默认版本。
- 服务管理页文案统一为“平台状态”，不再沿用“升级后核验”作为独立区域。

## UPG-018 runner 使用宿主机路径作为容器内 cwd

状态：[已解决] runner v0.2.2 已修复，10.20.11.12 已导入并切换

现象：平台升级执行到“重启升级服务”时报错：

```text
[Errno 2] No such file or directory: '/data/SmartX-HCI-Capacity-Insight-main'
```

根因：runner 通过 Docker socket 解析出了宿主机项目目录 `/data/SmartX-HCI-Capacity-Insight-main`，但该路径在 runner 容器内不存在；旧逻辑把它作为 `subprocess.run(..., cwd=...)` 的工作目录，导致重启阶段失败。

修复：
- `docker compose -f` 仍使用 `/data/compose-runtime/*.yml`，保证 compose 文件和 bind mount 路径对 Docker daemon 可见。
- `cwd` 改为 runner 容器内存在的 `/opt/smartx-storage-forecast`，不存在时再兜底 `/data` 或 `/`。
- 已生成 `/data/upgrade-packages/components/smartx-upgrade-runner-v0.2.2.tar.gz`。
- 已在 `10.20.11.12` 导入并切换到 `nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.2.2`。

验证记录：

```text
runner_version v0.2.2
compose_cwd /opt/smartx-storage-forecast True
compose_command docker compose -p smartx-capacity-insight -f /data/compose-runtime/docker-compose.offline.yml -f /data/compose-runtime/docker-compose.upgrade.yml
```

## 当前建议修复顺序

1. [已解决] 修复旧 web-api 组件升级写 `/opt` 的问题，改为 `/data/compose-runtime`。
2. [已解决] runner 独立治理到 v2 当前 `v0.3.0`，解决备份、排除目录、`--no-deps`、容器内 `cwd` 和 runner-only 自升级执行者问题。
3. [已解决] 修复平台升级闭环：镜像名、compose tag、project 文件同步；后续升级以 v2 当前 runner `v0.3.0` 为基线。
4. [已解决] 增强预检查：镜像名/tag、compose 文件、项目文件、敏感路径、volume、网络、磁盘空间的步骤化进度。
5. [已解决] 增强升级前备份精确进度和小日志。
6. [已解决] 清理升级 UI：合并平台升级与升级后核验，预检查步骤化。
7. [已解决] 定义并验证 Prometheus/observability 组件升级策略。
8. [已解决] 回归验证数据迁移后的 Prometheus 历史指标、日/月增长和趋势图。
9. [已解决] 基于历史问题重新设计 v2 平台升级与组件升级模式，覆盖包格式、runner 自升级、状态机、备份和回滚闭环第一版。

## UPG-019 运行产物落在 app 数据目录导致备份和迁移膨胀

状态：[已解决] v2 目录结构和 compose 挂载已调整，并在远端运行验证通过

现象：升级包上传目录、升级历史任务、自动备份、报表导出、数据迁出、数据迁入留档等运行产物历史上都可能落在容器 `/data` 下。由于 `/data` 映射到宿主机 `/data/smartx-capacity-insight-data/app`，这些运行产物实际会进入业务库目录旁边，例如 `app/upgrades`、`app/backups`、`app/exports`。

根因：配置默认使用 `/data/upgrades`、`/data/backups`、`/data/exports`、`/data/compose-runtime`，但 compose 只挂载了 `/data/smartx-capacity-insight-data/app:/data`，没有为运行产物目录提供独立 bind mount。

影响：
- 升级前备份可能把旧升级包、报表、迁移包一起打进去，体积变大甚至看起来卡住。
- 数据迁移导出如果扫描整个 `/data`，也会被运行产物拖慢。
- 业务库目录职责不清，排查时容易误把缓存和核心数据混在一起。

修复：
- 保留核心业务数据在 `/data/smartx-capacity-insight-data/app`，例如 `smartx.db` 和 `upgrade-runner.version`。
- 新增独立宿主机目录：`/data/upgrades`、`/data/backups`、`/data/exports`、`/data/compose-runtime`。
- `docker-compose.yml`、`docker-compose.offline.yml`、`docker-compose.release.yml` 对 web-api、collector-worker、upgrade-runner 增加独立挂载。
- `pre_install.sh` 创建并授权上述目录。
- runner override 写入路径改为 `SMARTX_RUNTIME_PATH`，默认 `/data/compose-runtime`。
- 后续平台升级以 v2 当前 `upgrade-runner v0.3.0` 为基线，不再在平台升级包里自动整理旧 `app/upgrades/backups/exports/compose-runtime` 目录。
- `scripts/migrate.sh` 只负责白名单项目文件同步和平台服务镜像 override 写入。

目录归属：

```text
/data/smartx-capacity-insight-data/app/smartx.db                 # 业务库
/data/smartx-capacity-insight-data/app/upgrade-runner.version    # runner 版本记录
/data/smartx-capacity-insight-data/prometheus                    # Prometheus 历史指标
/data/upgrades                                                   # 上传升级包、解包目录、升级任务记录
/data/backups                                                    # 升级前备份、项目文件备份
/data/exports                                                    # 导出/导入留档总目录
/data/exports/reports                                            # Word/Excel 报表导出文件
/data/exports/migrations                                         # 数据迁移导出包
/data/exports/imports                                            # 数据迁移导入上传包、解压目录、task.json
/data/exports/migration-tasks                                    # 数据迁移导出后台任务状态
/data/compose-runtime                                            # 运行时 compose override
```

取舍：已取消“数据迁移导出跳过 Prometheus 历史指标”的优化方向。历史指标是日增长、月增长和趋势图的数据来源，不能为了导出速度跳过；真正优化方向是目录职责拆开，并给导出/导入/备份增加精确进度和可清理留档。

## UPG-020 v1 Tower 凭据迁入后无法采集

状态：[已解决] v2 已兼容 v1 Fernet 凭据解密，并在 `10.20.11.3` 完成真实采集验证

现象：v1/v0.4.x 数据迁入 v2 后，Tower 用户名存在，但手动采集失败，提示 `Tower requires either an API token or username/password.`。

原因：v1 Tower 密码/API Token 使用 Fernet 加密，密钥种子来自 `SMARTX_CREDENTIAL_KEY` 或 `SMARTX_SECRET_KEY`；v2 第一版只支持新的轻量凭据格式，导致旧 `password_encrypted` 无法被解出。

修复：

- `V2Settings` 增加 `credential_key`。
- `InventoryService.get_tower_secret_material()` 优先按 v2 格式解密；失败后按 v1 Fernet 格式兼容解密。
- 新增测试覆盖 v1 Fernet 密文可被 v2 读取。
- 凭据只用于连接，不在 API、日志或测试输出中打印明文。

验证：

- 用户在 `10.20.11.3` 重新录入 Tower 密码后，v2 解密状态为 `password_decrypts=true`。
- 手动采集成功：`采集完成：1 个集群，172 台虚拟机。`
- Prometheus 当前 VM 样本 `172` 条，最近 2 小时 series `172` 条。
- Dashboard 返回 `towers=1`、`clusters=1`、`vms=177`，采集状态为 success。
- VM 列表返回 `172` 台，首个 VM 7 天趋势点 `146`。
- 报表返回 `clusters=1`、趋势点 `14`、预测窗口 `90` 天。

## v2 升级中心规避策略

v2 不继续兼容旧升级路径，而是在 `feature/upgrade-v2` 上重新设计升级中心。历史问题在 v2 中按下面方式规避。

| 历史问题 | v2 规避策略 | 设计文档 |
| --- | --- | --- |
| UPG-001 写只读 `/opt` | runner 和 web-api 的运行时 compose override 统一写 `/data/compose-runtime` | `docs/v2-upgrade-center-design.md` |
| UPG-002 runner 函数缺失 | runner 独立组件包、独立版本、独立验证，不跟随平台包混发 | `docs/v2-upgrade-center-design.md` |
| UPG-003 重启平台服务带起依赖 | 平台升级只重启 manifest 声明服务，未声明组件一律不动 | `docs/v2-upgrade-center-design.md` |
| UPG-004 Docker socket 路径不一致 | runner 区分宿主机 Docker 视角路径和容器内 cwd | `docs/v2-upgrade-center-design.md` |
| UPG-005 镜像名不闭环 | manifest 校验镜像名、tag、archive、sha256 与 compose 目标一致 | `docs/v2-upgrade-center-design.md` |
| UPG-006 offline compose 使用 latest | v2 离线 compose 默认明确版本，不使用 `latest` 作为部署默认 tag | `docs/architecture-v2.md` |
| UPG-007 项目文件不同步 | 升级包支持 `project/` 白名单同步，同步前备份项目文件 | `docs/v2-upgrade-center-design.md` |
| UPG-008 备份卡住不透明 | 备份任务记录扫描总量、当前文件、字节进度和小日志 | `docs/v2-upgrade-center-design.md` |
| UPG-009 上传 95% 卡住 | 前端上传显示速度，上传结束后切换为服务器处理中 | `docs/v2-frontend-design.md` |
| UPG-010 UI 内容重复 | v2 升级中心合并平台状态、包信息和运行核验 | `docs/v2-frontend-design.md` |
| UPG-011 预检查无步骤 | 预检查统一使用步骤状态机和页面内状态图标 | `docs/v2-upgrade-center-design.md` |
| UPG-012 runner 版本显示不准 | runner 版本、镜像 tag、容器创建时间一起展示 | `docs/v2-upgrade-center-design.md` |
| UPG-013 清理 0B | 空间清理先扫描候选，再按候选删除并保留本次释放结果 | `docs/v2-frontend-design.md` |
| UPG-014 网络冲突 | 预检查校验 compose 网络，继续规避 172.16/172.17 常见冲突段 | `docs/v2-upgrade-center-design.md` |
| UPG-015 Prometheus 升级未定义 | Prometheus 作为 `observability` 组件独立升级，强制备份和健康检查 | `docs/v2-upgrade-center-design.md` |
| UPG-016 迁移后趋势为空 | v2 数据迁移必须包含 Prometheus 历史 block，并有导入后健康验证 | `docs/v1-data-compatibility.md` |
| UPG-019 运行产物污染 app 目录 | v2 明确 `/data/upgrades`、`/data/backups`、`/data/exports`、`/data/compose-runtime` 独立职责 | `docs/architecture-v2.md` |

v2 升级中心实施前必须先完成：

- `docs/v2-upgrade-center-design.md`
- `docs/v2-api-contracts.md`
- `docs/v2-frontend-design.md`
- `docs/v2-implementation-sequence.md`

前端要求：

- 升级中心页面风格和 v1 服务管理页保持一致。
- 保留 CloudTower 风格大面板、左侧二级菜单、右侧内容区。
- 上传、预检查、升级、回滚、空间清理都使用页面内弹窗和步骤进度，不使用浏览器原生提示。
