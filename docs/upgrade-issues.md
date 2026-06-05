# 升级模块问题台账

本文记录当前升级中心、组件升级、升级包和部署文件相关问题。后续修复升级模块时以本文为问题清单，逐项关闭，避免只修表象而遗漏根因。

更新时间：2026-06-04

## 问题状态说明

- `待修复`：已经确认问题存在，需要代码或流程修复。
- `已解决`：代码、镜像或包已经完成修复；如仍需现场完整链路验证，会在条目中单独说明。
- `修复包已生成`：已有临时/组件包修复，但仍需要现场验证或根修复。
- `需验证`：代码或包已调整，需要在真实升级流程验证。
- `设计约束`：当前设计刻意如此，但需要在文档和 UI 中解释清楚。

## UPG-001 旧 web-api 组件升级写入只读 /opt

状态：[已解决] 代码已修复，待随平台升级包部署后现场回归

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
- [待验证] 需要通过新的 web-api 镜像/平台升级包部署到现场后，再在 Web 页面执行组件升级验证。

验证记录：
- 已用最小复现证明旧逻辑会写 project path，不会写 `/data/compose-runtime`。
- 修改后同一复现通过：runtime override 存在，project override 不存在。
- 新增 `backend/tests/test_upgrade.py` 回归测试覆盖写入路径和 compose 命令引用路径。
- `docker compose build web-api` 通过。

## UPG-002 runner v0.2.0 升级前备份函数缺失

状态：[已解决] 已在 runner v0.2.1/v0.2.2 修复，10.20.11.12 已切换 v0.2.2

现象：平台升级卡在“升级前备份”，日志报错：

```text
name '_write_upgrade_backup_archive' is not defined
```

根因：`upgrade-runner v0.2.0` 调用了 `_write_upgrade_backup_archive()`，但镜像中的 `backend/app/services/upgrade.py` 缺少该函数定义。

影响：即使手动升级到 `v0.2.0`，平台升级仍会在备份阶段失败。

当前处理：已在 `10.20.11.3` 生成 `v0.2.1` runner 组件包：

```text
/data/upgrade-packages/components/smartx-upgrade-runner-v0.2.1.tar.gz
sha256: 1bc19ed95b615ca02503860a824a30a7d4f46906c34fd5e9bdbd1d3c97fcfc26
```

已验证镜像内：
- `_write_upgrade_backup_archive` 存在。
- `_docker_safe_project_path` 存在。
- `runner_version` 为 `v0.2.1`。

后续：需要在真实机器上完成组件升级或手动升级 runner 后，再验证平台升级是否能通过备份阶段。

## UPG-003 旧 runner 重启平台服务时会带起依赖服务

状态：[已解决] runner v0.2.2 使用 --no-deps 重启目标服务，10.20.11.12 已切换 v0.2.2

现象：平台升级重启阶段可能重新创建 Prometheus，触发错误的 bind mount 或网络冲突，导致升级后页面打不开。

根因：旧 runner 执行 compose 重启服务时没有使用 `--no-deps`，升级 `web-api`、`frontend`、`collector-worker` 时可能连带处理 `prometheus` 等依赖服务。

影响：
- 本不该动 Prometheus 的平台升级可能动到 Prometheus。
- 如果项目目录、compose 文件或网络名和当前部署不一致，重启阶段容易失败。

当前处理：runner `v0.2.0+` 设计上应使用 `--no-deps` 重启目标服务。`v0.2.1` 继承该方向，但仍需真实升级验证。

## UPG-004 Docker socket 视角下项目路径不一致

状态：[已解决] runner v0.2.2 已区分 Docker 视角 compose 路径和容器内 cwd，10.20.11.12 已验证

现象：容器内看到的项目路径是 `/opt/smartx-storage-forecast`，但 Docker daemon 真正需要宿主机路径，例如 `/data/SmartX-HCI-Capacity-Insight-main`。升级重启时 compose 里的相对 bind mount 可能解析到错误路径。

根因：runner 在容器内通过 Docker socket 调用宿主机 Docker，但 compose 文件里的相对路径需要按宿主机项目路径解释，而不是容器内路径。

影响：
- Prometheus 配置挂载可能找不到文件。
- 项目文件同步后 compose up 可能使用错误目录。

当前处理：runner `v0.2.0+` 增加 Docker socket 下的项目路径处理逻辑，`v0.2.1` 包中已验证 `_docker_safe_project_path` 存在。仍需真实升级验证。

## UPG-005 升级包镜像名与 compose 镜像名不闭环

状态：[已解决] v0.4.0 升级包已统一 nazawsze/smartx-hci-capacity-insight-* 镜像名，待完整升级回归

现象：用户现场遇到过升级包导入的是 `smartx-storage-forecast-*` 或本地 tag，但 compose 里写的是 `nazawsze/smartx-hci-capacity-insight-*`，导致镜像加载成功但服务启动找不到对应镜像。

根因：历史版本中升级包 manifest、打包脚本、compose 文件、GitHub Actions 使用过不同镜像名前缀和 tag 策略。

影响：
- 升级后容器无法启动。
- 页面打不开，只能进后台排查镜像名和 compose。

根修方向：
- 平台镜像统一为 `nazawsze/smartx-hci-capacity-insight-<service>:<version>`。
- `docker-compose.offline.yml`、`docker-compose.release.yml`、升级包 manifest、GitHub Actions、打包脚本必须使用同一套镜像名。
- 预检查必须校验 manifest 镜像名与目标 compose 一致。

## UPG-006 offline compose 仍可能使用 latest 或旧 tag

状态：[已解决] v0.4.0 升级包内 offline/release compose 默认 tag 已固定为 v0.4.0，待完整升级回归

现象：升级包加载了 `v0.4.0` 镜像，但 `docker-compose.offline.yml` 里仍是 `latest` 或旧版本，升级后重新 `docker compose up -d` 会回退到旧镜像或继续使用 `latest`。

根因：历史升级流程只写 `docker-compose.upgrade.yml`，不会同步项目目录里的 `docker-compose.offline.yml`、`docker-compose.release.yml` 等项目文件。

影响：
- 升级页面显示版本和实际 compose 文件不一致。
- 后续手工重启可能回退版本。
- 离线部署无法保证明确版本。

根修方向：
- 升级包包含 `project/` 白名单项目文件。
- 升级流程增加“同步项目文件”步骤。
- 后续平台升级以 `upgrade-runner v0.2.2` 为执行基线，`scripts/migrate.sh` 只负责白名单项目文件同步。
- 打包脚本生成包时自动把 compose 默认 tag 替换为目标 `VERSION`。

## UPG-007 平台升级不会自动更新项目文件

状态：[已解决] v0.4.0 升级包已包含 project/ 白名单文件并执行项目文件同步，待完整升级回归

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

## UPG-008 升级前备份进度不透明且可能卡住

状态：待修复

现象：升级任务卡在“升级前备份”，页面缺少精确进度和小日志，用户只能看到步骤长时间不动。

根因：备份过程是大文件 tar/gzip 操作，历史实现没有按文件或字节上报进度；旧实现还可能把 `/data/upgrades`、`/data/backups`、`/data/exports` 等运行时目录打进备份，导致备份变大甚至递归式膨胀。

影响：
- 大数据量现场用户无法判断是正常压缩还是失败。
- 升级包、报表导出、数据迁出留档可能显著放大备份体积。

当前处理：runner `v0.2.1` 的备份写包函数会跳过 `upgrades`、`backups`、`exports` 等运行时目录。仍需增加页面进度和日志。

根修方向：
- 备份前扫描需要备份的文件总数和总字节数。
- 备份时按已处理字节数更新百分比、当前文件、小日志。
- 页面“升级前备份”步骤显示真实进度，而不是只显示步骤状态。

## UPG-009 升级包上传 95% 后看似卡住

状态：[已解决] 前端上传进度已区分 uploading/processing/done 并显示上传速度，待大包回归

现象：上传大升级包时页面到 95% 会停一段时间。

根因：浏览器上传完成后，后端仍在保存、解压、读取 manifest、校验包结构和 sha256。前端历史上仍显示“上传中 95%”，没有切换到“服务器处理中”。

影响：用户会误以为上传卡死。

根修方向：
- 上传阶段显示速度，例如 `上传中 95% · 12.4 MB/s`。
- XHR 上传完成后到接口返回前显示 `上传完成，正在保存、解压并校验升级包...`。
- 平台升级包和组件升级包共用同一套上传进度状态。

## UPG-010 平台升级和升级后核验内容重复

状态：待修复

现象：服务管理页“平台升级”的内容和“升级后核验”内容重复，页面层级和信息密度不佳。

根因：升级状态、当前版本、目标版本、运行镜像、核验结果分散在多个二级框里。

影响：用户难以判断当前应该看哪里，也增加 UI 维护成本。

根修方向：
- 合并平台升级与升级后核验展示。
- 平台升级下面不要再套过多二级框。
- 当前版本、目标版本、最近成功包、运行镜像放在同一个清晰区域。

## UPG-011 预检查没有步骤化进度

状态：待修复

现象：预检查只显示结果，不像开始升级那样展示逐项检查流程。

根因：预检查接口和 UI 没有按检查项返回/展示阶段状态。

影响：预检查耗时时用户不知道正在检查什么；失败时定位不够直观。

根修方向：
- 预检查显示类似升级步骤的流程：版本、sha256、磁盘、Docker、compose、volume、项目文件、敏感路径。
- 正在检查用 loading，成功用绿色勾，失败用红色 X，未执行为空心圆。

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

状态：[已解决] compose 网络使用 10.249.249.0/24，Docker daemon 可配置 10.249.0.0/16；待不同现场回归

现象：升级或 runner 重启时可能遇到网络名称被占用、旧网络残留、172.16/172.17 网段冲突。

根因：不同部署目录、不同 compose project name、历史网络未清理或 Docker daemon 默认 `bip`/address pools 与客户网络冲突。

影响：容器启动失败或网络不可达。

当前处理：项目网络规划使用 `10.249.249.0/24`，Docker daemon 可使用 `10.249.0.0/16`。仍需在升级预检查中明确检查当前网络和目标网络。

## UPG-015 Prometheus 组件升级策略未定义

状态：设计约束

现状：第一版平台升级主要更新 `web-api`、`collector-worker`、`frontend`，组件升级第一版只支持 `upgrade-runner`。

问题：如果未来需要升级 Prometheus 镜像或配置，当前升级包能力不够完整。

设计建议：
- Prometheus 镜像升级应作为独立组件升级类型处理。
- 升级前必须备份 Prometheus 数据目录。
- 重启 Prometheus 需要额外健康检查和数据目录权限检查。
- 默认平台升级不应随意重启或替换 Prometheus，避免影响历史指标。

## UPG-016 数据迁移后增长和趋势为空

状态：需验证

现象：新部署导入迁移数据后，日增长、月增长、集群预测报表、趋势图为空。

已知原因：这些页面依赖 Prometheus 历史指标，不只依赖业务库 `smartx.db`。如果迁移包只包含业务库，或者 Prometheus 数据目录权限错误，增长和趋势会为空。

当前处理：数据迁移包应包含业务库和 Prometheus 历史指标；`pre_install.sh` 负责修正 Prometheus 数据目录权限。

后续：需要验证导出包确实包含 Prometheus blocks，导入后 Prometheus 正常启动并能查询 `smartx_vm_storage_used_bytes`。

## UPG-017 文档中 runner 版本来源描述陈旧

状态：待修复

现象：`docs/upgrade-runner-lifecycle.md` 仍描述平台版本来自 `SMARTX_APP_VERSION`，但当前目标设计是平台版本优先来自镜像内置 `VERSION`。

影响：维护人员会误以为 compose 里还必须写 `SMARTX_APP_VERSION`。

根修方向：
- 更新 runner 生命周期文档：平台版本来自镜像内 `/app/VERSION`，`SMARTX_APP_VERSION` 只作为兜底覆盖。
- runner 组件版本仍独立来自 `/data/upgrade-runner.version` 或 runner 自身默认版本。

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
2. [已解决] runner 升级到 `v0.2.2`，解决备份函数缺失、备份排除目录、`--no-deps` 和容器内 `cwd` 问题。
3. [已解决] 修复平台升级闭环：镜像名、compose tag、project 文件同步；后续升级以 runner v0.2.2 为基线。
4. [待修复] 增强预检查：镜像名/tag、compose 文件、项目文件、敏感路径、volume、网络、磁盘空间的步骤化进度。
5. [待修复] 增强升级前备份精确进度和小日志。
6. [待修复] 清理升级 UI：合并平台升级与升级后核验，预检查步骤化。
7. [设计待定] 定义 Prometheus 组件升级策略。
8. [需验证] 回归验证数据迁移后的 Prometheus 历史指标、日/月增长和趋势图。

## UPG-019 运行产物落在 app 数据目录导致备份和迁移膨胀

状态：[已解决] 目录结构和 compose 挂载已调整，待随升级包现场回归

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
- 后续平台升级以 `upgrade-runner v0.2.2` 为基线，不再在平台升级包里自动整理旧 `app/upgrades/backups/exports/compose-runtime` 目录。
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
