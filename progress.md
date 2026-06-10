# SmartX HCI Capacity Insight - 工作进度

## 2026-06-01

### 创建项目持久化上下文文档

状态：完成

已创建：

- `task_plan.md`
- `findings.md`
- `progress.md`

目的：

- 让后续会话可以快速恢复项目上下文。
- 记录远端路径、分支规则、部署方式和已知问题。
- 避免依赖本地 `planning-with-files` 插件 hook，降低 reconnect 风险。

### 当前远端状态

远端：

- 主机：`10.20.11.3`
- 项目路径：`/opt/smartx-storage-forecast`
- 分支：`dev`
- 当前基线：`ed3ed5f`，标签 `v0.3.3U1`

未提交应用变更：

- `backend/app/api/routes.py`
- `backend/app/services/dashboard.py`
- `frontend/src/components/ClusterCapacityChart.tsx`
- `frontend/src/pages/ReportsPage.tsx`
- `frontend/src/pages/VmsPage.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/types.ts`

这些变更属于最近的报表/图表优化：

- 已使用百分比文案。
- 报表容量增长速率固定按 7 天平均计算。
- 报表趋势图支持 7/30/90/365/720 天范围。
- 后端报表接口支持 `chart_days`。

### 已完成验证

近期报表/图表变更此前已验证：

- `python3 -m py_compile backend/app/services/dashboard.py backend/app/api/routes.py` 通过。
- `docker compose build frontend` 通过。
- `docker compose build web-api` 通过。
- 已重启 `web-api` 和 `frontend`。
- `frontend` 返回 `200`。
- `api_metrics` 返回 `200`。
- `chart_days=720` 直接检查返回了有效响应，包含 `growth_rate_window_days: 7`。

### 本次注意

- 本次只写文档，不提交代码。
- 文档不包含密码或敏感凭据。
- 后续如果用户要求提交，应先检查所有未提交变更，确认文档和应用改动是否一起提交。

### 导出报表可读性优化

状态：完成

本次需求：

- 导出报表中当前容量、上期容量、增长量、增长率相关 VM 表格需要增加排序能力或排序标识。
- 增长率超过 20% 且增长量大于 100 GiB 的虚拟机需要红色底纹标识。
- Word 增加按集群定位的目录栏。

已修改：

- `backend/app/services/report_export.py`

待验证：

- 后端语法检查。
- 容器内生成 Word 和 Excel 文件。
- 检查 Excel 包含目录 sheet、表格结构和高亮底纹。
- 检查 Word 包含目录和集群书签/跳转结构。

验证结果：

- `python3 -m py_compile backend/app/services/report_export.py` 通过。
- 已重建并重启 `web-api`。
- 容器内生成 `storage-forecast-all-20260601.docx`，大小约 150 KiB。
- 容器内生成 `storage-forecast-all-20260601.xlsx`，大小约 44 KiB。
- Excel 检查到 `目录` sheet、`VmAmountSummary` 和 `VmRatioSummary` 表格。
- Word 检查到目录、集群 bookmark、排序表头和排名列。
- 构造高风险 VM 样例验证：Word 和 Excel 均写入 `F4CCCC` 红色底纹。
- `/metrics` 返回 `200`。

### 修复导出报表生成时间时区

状态：完成

发现：

- `10.20.11.3` 宿主机当前时区是 `America/New_York`。
- `web-api` 容器当前时区是 `UTC`。
- 应用配置 `SMARTX_COLLECTION_TIMEZONE=Asia/Shanghai`。
- 报表导出原来使用 `datetime.now()`，依赖容器默认时区，所以生成时间慢 8 小时。

修复：

- `backend/app/services/report_export.py` 使用 `get_settings().collection_timezone` 和 `zoneinfo.ZoneInfo` 生成本地时间。
- Word/Excel 的生成时间显示增加时区名，例如 `2026-06-01 13:33:27 Asia/Shanghai`。

验证：

- 重建并重启 `web-api`。
- 重新生成 Word/Excel。
- Word 检查到生成时间为 `2026-06-01 13:33:27 Asia/Shanghai`。
- Excel 检查到生成时间为 `2026-06-01 13:33:37 Asia/Shanghai`。
- `/metrics` 返回 `200`。

### 版本治理

状态：进行中

已完成：

- 盘点仓库和 DockerHub 版本混乱问题。
- 临时隔离修复 `main` 的三份 compose 文件，并将 `v0.5.0` tag 指向该修复提交。
- 在 dev 中新增 `RUNNER_VERSION`。
- 将平台版本元数据改为 `v0.5.0`。
- 将 runner compose tag 拆为 `SMARTX_RUNNER_IMAGE_TAG:-v0.3.0`。
- 平台升级包脚本不再包含 `upgrade-runner.tar`。
- runner 组件包脚本默认读取 `RUNNER_VERSION`。
- GitHub Actions 拆分平台三件套和 runner 专用 workflow。
- 新增 `docs/version-governance.md` 记录版本规则和 DockerHub tag 清理方法。

待验证：

- Python 语法检查。
- `scripts/build_upgrade_package.py --check-version`。
- 关键测试断言。
- 敏感信息扫描。

验证记录：

- `python3 -m py_compile backend/app/services/upgrade.py backend/app/core/config.py scripts/build_upgrade_package.py scripts/build_runner_component_package.py backend/tests/test_deployment_config.py backend/tests/test_upgrade.py` 通过。
- `python3 scripts/build_upgrade_package.py --check-version` 通过，输出 `Version metadata OK: v0.5.0`。
- 直接导入 `backend/tests/test_upgrade.py` 时本地缺少 `pydantic`，需要在远端环境或容器内跑完整导入测试。

### 修复清理空间显示 0B

状态：完成

发现：

- 镜像扫描显示的是未被容器使用的镜像，但清理接口原来调用 Docker `/images/prune`，带 tag 的旧版本镜像经常不会被 prune 删除，所以 Docker 返回 `SpaceReclaimed=0`。
- 服务管理的空间清理成功后立即调用 `scanSpaceCleanup()`，清理后自然扫描为 `0B`，覆盖了本次清理释放结果。

修复：

- `backend/app/services/system_control.py` 镜像清理改为逐个删除扫描出的未使用镜像。
- 镜像清理结果返回候选逻辑大小、预计释放大小和删除失败列表。
- `frontend/src/pages/ServicePage.tsx` 保留本次清理结果，不再用清理后重扫覆盖为 `0B`。
- `docs/upgrade-issues.md` 将 UPG-013 标记为已解决。

### 升级预检查步骤化与网络检查

状态：完成

发现：

- 后端平台预检查已有 manifest、version、services、sha256、docker、upgrade-runner、volumes、image-names、project-files、compose-tag、disk、migration 等检查。
- 前端预检查步骤原来只有 5 个泛化步骤，结果返回后只在最后一步显示失败，无法看出是镜像名、compose、项目文件还是磁盘问题。
- 升级预检查还缺少 compose 网络检查，不能在上传阶段发现 172.16/172.17 或非 `10.249.249.0/24` 的配置。

修复：

- `backend/app/services/upgrade.py` 新增 `network` 检查，校验当前 compose 与升级包 `project/docker-compose.offline.yml`。
- `frontend/src/pages/ServicePage.tsx` 将平台和组件预检查步骤改为按后端检查项分组，并在步骤内展示聚合后的检查消息。
- `backend/tests/test_deployment_config.py` 增加文本断言覆盖网络检查和前端步骤映射。
- `docs/upgrade-issues.md` 将 UPG-011 标记为已解决，UPG-014 补充“已纳入升级预检查”。

### 升级前备份进度

状态：完成

发现：

- 平台升级由 `upgrade-runner` 轮询 pending 任务后执行 `_create_backup()`。
- 旧备份过程只在 `_run_step()` 开始和完成时保存 task，因此 tar/gzip 大目录时页面会长时间停在“生成升级前数据备份”。
- 前端已经能显示 step message 和 logs，缺的是后端备份过程中持续更新 task。

修复：

- `_create_backup()` 先扫描待备份文件总数和总字节数，写入 `backup_total_files`、`backup_total_bytes`。
- 新增 `_BackupProgress` 和进度 reader，备份写入时按字节统计，并按 5 秒或 10% 进度节流更新 `backup_processed_*`、step message 和日志。
- 任务中心 detail 改为使用当前 running step 的 message，能直接显示 `备份中 xx%`。
- `docs/upgrade-issues.md` 将 UPG-008 标记为已解决。

### 平台升级 UI 去重

状态：完成

发现：

- 平台升级顶部已经展示当前版本、目标版本、最近成功包等信息。
- 下方“服务运行核验”又作为独立区块展示刷新按钮和服务运行表，视觉上像二级框，用户需要在多个区域判断升级状态。

修复：

- 新增统一“平台状态”区域，集中展示版本、升级包、compose 和运行服务。
- `renderUpgradeRuntimeVerification()` 只返回运行服务表，刷新按钮移到平台状态标题行。
- `docs/upgrade-issues.md` 将 UPG-010 标记为已解决。

验证：

- 本地 `python3 -m py_compile backend/app/services/upgrade.py backend/tests/test_deployment_config.py` 通过。
- 本地 `python3 scripts/build_upgrade_package.py --check-version` 通过。
- 本地敏感信息 diff 扫描未发现密码、secret、credential。
- 10.20.11.3 已拉取 dev，`python3 -m py_compile`、`scripts/build_upgrade_package.py --check-version`、`docker compose build frontend` 通过。

### runner 生命周期文档版本来源

状态：完成

修复：

- `docs/upgrade-runner-lifecycle.md` 将“升级后核验”文案更新为“平台状态”。
- `docs/upgrade-issues.md` 将 UPG-017 标记为已解决。
- `docs/releases/CHANGELOG.md` 同步服务管理页命名，避免维护人员继续引用旧区域名。

### 当前状态汇总

状态：完成

最近提交：

- `df77a57 docs: update runner version source notes`
- `dcf328d fix: consolidate upgrade status UI`
- `7fd71b6 fix: report upgrade backup progress`
- `3d917c0 fix: make upgrade precheck steps actionable`
- `2cf9103 fix: report cleanup reclaimed space accurately`

已解决：

- Docker 镜像清理和空间清理显示 `0B`。
- 升级预检查步骤化，并覆盖镜像名/tag、compose、项目文件、敏感路径、volume、网络和磁盘空间。
- 升级前备份显示扫描总量、处理字节数、当前文件和小日志。
- 平台升级 UI 合并为“平台状态”，不再重复展示升级后核验。
- runner 生命周期文档已明确平台版本来自镜像内 `/app/VERSION`，runner 版本独立来自 `/data/upgrade-runner.version` 或 `RUNNER_VERSION`。

剩余：

- Prometheus 组件升级策略仍为设计待定。
- [已解决] 数据迁移后的 Prometheus 历史指标、日/月增长和趋势图已在 `10.20.11.3` 完成真实回归验证。
- 数据迁移导入前需要自动生成备份，备份成功后才继续导入。
- 需要根据历史升级问题重新设计全新的平台升级和组件升级模式。

### 新增报表与 VM 口径需求

状态：待处理

新增需求：

- 月增长最快 VM 必须排除历史数据不足 30 天的 VM；如果刚部署没有任何 VM 满足 30 天样本，月增长最快 VM 显示为空。
- Word/Excel 导出报表的月增长 TOP VM 使用同样过滤口径。
- Word/Excel 导出报表需要在“上期容量”表头或说明中直接标注统计窗口起止日期。
- 报表页在“日增长最快 VM”下新增“本日新建 VM”，在“月增长最快 VM”下新增“本月新建 VM”。
- 本日/本月新建 VM 支持点击跳转到虚拟机页面。
- 验证并必要时修复 VM 改名显示：历史数据以 UUID 绑定，最新一次采集后页面展示名称应与 Tower 最新名称同步。

初步口径建议：

- VM 身份继续使用 `tower_id + cluster_id + vm_id`。
- VM 名称只作为展示字段，不能作为历史数据绑定字段。
- “新建 VM”建议按该 VM 在 Prometheus 历史指标中首次出现时间判断。
- 月增长过滤建议按该 VM 指标最早样本与当前统计结束时间的跨度判断，跨度小于 30 天则排除。
- “上期容量”建议更名或注释为“统计窗口起始容量”，并显示具体日期范围，例如 `统计窗口：2026年05月01日-2026年05月31日`。

### 数据迁移导入前备份

状态：已解决

新增需求：

- [已完成] 数据迁移导入前自动生成当前系统备份，避免导入包异常、导入中断、Prometheus block 合并异常或权限问题导致难以回退。
- [已完成] 备份路径使用 `/data/backups/import-before-YYYYMMDDHHMMSS-任务前缀.tar.gz`。
- [已完成] 页面任务中心和导入完成提示显示备份路径。
- [已完成] 备份成功后才开始导入；备份失败默认阻止继续导入。
- [已完成] 导入完成结果中返回 `backup_path`。

### 2026-06-05 数据迁移备份、报表 VM 口径与历史指标回归

状态：已完成

实现：

- 数据迁移导入在写入业务库和 Prometheus 历史指标前生成导入前备份，跳过 `upgrades/backups/exports/compose-runtime` 和 Prometheus `wal/chunks_head/lock/queries.active` 等运行时目录。
- 报表月增长 VM 要求样本跨度满 30 天；不足 30 天不进入月增长榜，Word/Excel 导出复用同一口径。
- 报表接口增加 `day_new_vms`、`month_new_vms`、`period_window` 和 `month_growth_min_sample_days`。
- 报表页增加“本日新建 VM”和“本月新建 VM”，点击仍按 `vm_id` 跳转。
- VM 展示名称优先使用最新采集名称，历史趋势和增长计算继续按 `tower_id + cluster_id + vm_id` 绑定。
- Word/Excel VM 表头从“上期容量”改为“期初容量”，并显示统计窗口起止日期。
- 修复增长量/增长率双 TOP100 合并后可能超过 100 条的问题。

验证：

- 本地 `python3 -m py_compile backend/app/services/dashboard.py backend/app/services/data_migration.py backend/app/services/report_export.py backend/tests/test_dashboard.py backend/tests/test_data_migration.py` 通过。
- `10.20.11.3` 远端 `docker compose build web-api frontend` 通过，frontend `tsc -b && vite build` 通过；仅存在 Vite 大 chunk 提示。
- `10.20.11.3` 重启 `web-api/frontend` 后 `/metrics` 返回 200，`8080` 返回 200。
- `10.20.11.3` Prometheus 当前 `smartx_vm_storage_used_bytes` 查询返回 175 条 series。
- `10.20.11.3` 报表接口返回：`clusters=1`、`day_fastest_growing_vms=100`、`month_fastest_growing_vms=0`、`day_new_vms=0`、`month_new_vms=0`；月榜为空符合“样本满 30 天”新口径。
- `10.20.11.3` Word/Excel 导出均可生成；Word 和 Excel 均确认包含“统计窗口”和“期初容量”。
- `10.20.11.3` 容器内验证导入前备份 helper：备份包含 `smartx.db` 和 Prometheus block，跳过 app 运行时目录和 Prometheus runtime 目录。

### 2026-06-05 UPG-016 数据迁移历史指标回归

状态：已解决

验证链路：

- 迁移导出任务生成 `/data/exports/migrations/smartx-storage-migration-20260605113838.tar.gz`。
- 导出包包含 `smartx-data/smartx.db` 和 7 个 Prometheus block 的 `meta.json`。
- 导出包不包含 Prometheus `wal` 运行时目录，也不包含导入任务运行时目录。
- 使用 merge 模式导回当前系统，返回 `ok=True`，生成导入前备份 `/data/backups/import-before-20260605114014-0ac6678f.tar.gz`。
- 同包回导未覆盖现有数据：业务库已有记录跳过，Prometheus 已有 7 个 block 跳过。
- 重启 `web-api`、`collector-worker`、`prometheus` 后服务均正常运行。
- Prometheus 即时查询 `smartx_vm_storage_used_bytes` 返回 175 条 series。
- Prometheus `query_range` 最近 7 天返回 175 条 series，前 10 条 series 共 260 个历史点。
- 报表接口返回 `clusters=1`、`day_fastest_growing_vms=100`、集群趋势点数 13；月增长为空符合 30 天样本口径。

### 2026-06-05 Phase 5 版本治理执行

状态：已完成

实现：

- `backend/app/core/config.py` 增加 `read_runner_version()`，runner 组件版本优先读取镜像内 `/app/RUNNER_VERSION`，环境变量 `SMARTX_RUNNER_VERSION` 仅作为兜底覆盖。
- `backend/Dockerfile`、`backend/Dockerfile.worker`、`backend/Dockerfile.upgrade` 均复制根目录 `VERSION` 和 `RUNNER_VERSION`，避免平台版本和 runner 版本依赖 compose 默认值。
- `docs/deployment.md` 修正离线部署说明：平台三件套默认 `v0.5.0`，`upgrade-runner` 默认 `v0.3.0`，不再描述为 `latest`。
- `docs/deployment.md` 补充 `/data/upgrades`、`/data/backups`、`/data/exports`、`/data/compose-runtime` 运行产物目录说明，并修正密码修改入口为 admin 头像菜单。
- `docs/version-governance.md` 和 `docs/releases/CHANGELOG.md` 补充镜像内置版本文件规则。
- 增加测试断言，防止后续 Dockerfile 漏复制 `RUNNER_VERSION`、部署文档回退到 `latest/v0.3.1`、runner 版本不读镜像文件。

验证：

- `python3 scripts/build_upgrade_package.py --check-version --no-build` 通过，输出 `Version metadata OK: v0.5.0`。
- `python3 -m py_compile backend/app/core/config.py backend/tests/test_upgrade.py backend/tests/test_deployment_config.py scripts/build_upgrade_package.py scripts/build_runner_component_package.py` 通过。
- 自定义静态断言通过，确认 compose 拆分 `SMARTX_IMAGE_TAG:-v0.5.0` 与 `SMARTX_RUNNER_IMAGE_TAG:-v0.3.0`，Dockerfile 均复制 `VERSION/RUNNER_VERSION`，部署文档不再包含 `latest` 默认 tag 或 `SMARTX_IMAGE_TAG=v0.3.1`。
- `python3 -m pytest backend/tests/test_upgrade.py backend/tests/test_deployment_config.py` 未执行成功，原因是本机 Python 环境缺少 `pytest` 模块。

### 全新平台升级与组件升级模式设计

状态：待处理

新增需求：

- 基于之前遇到的升级失败、runner 自升级、compose tag 不闭环、项目文件未同步、路径只读、任务卡住、备份不透明等问题，重新设计平台升级和组件升级模式。
- 目标不是继续修补现有流程，而是形成新的升级架构、状态机、包格式和回滚策略。
- Prometheus 升级纳入该新模式设计，作为 `observability` 组件处理，不再单独作为零散待办。

设计范围：

- 统一升级包入口：上传后读取 `manifest.json`，自动识别平台三件套、runner、Prometheus 或组合包。
- 平台升级、组件升级、Prometheus/observability 升级的职责边界。
- web-api 与 upgrade-runner 的职责分工，尤其是 runner 自升级的安全路径。
- manifest、镜像名、tag、compose/project 文件同步和版本来源的统一规则。
- Prometheus 升级的强制备份、数据目录权限检查、版本兼容检查、健康检查和历史指标查询回归。
- 升级前备份、项目文件备份、运行配置备份和手动/自动回滚策略。
- 跨容器重启后的任务恢复、日志持久化、步骤状态和 UI 展示。
- 旧版本向新升级模式过渡的兼容或迁移方案。

### 2026-06-05 后续产品化待办归并

状态：已记录

归并结果：

- 升级体系相关建议已合并到 Phase 12：统一升级包入口、manifest 自动识别组件、runner 执行、Prometheus/observability 组件升级、备份验证、回滚和任务恢复。
- 数据迁移相关建议整理为 Phase 13：把导入/导出提升为灾备能力，覆盖 SQLite、Prometheus 历史指标、merge 规则、导入前备份和导入后健康验证。
- 报表相关建议整理为 Phase 14：客户交付型 Word/Excel 报表、风险摘要、统一图表风格、高风险 VM 前置、导出留存和任务中心下载。
- 首页风险相关建议整理为 Phase 15：容量风险驾驶舱，任一集群超过 80% 即提示风险，展示最危险集群、预计耗尽时间、7 天增长和主要增长 VM。
- 项目架构整理作为 Phase 16，优先级最低；当前不拆微服务容器，保持 5 容器，未来仅在必要时评估 `task-worker`。
- 版本治理不新建重复阶段，作为 Phase 5 的长期规则继续执行。

### 2026-06-05 SQLite latest_vm_volumes 存储体积分析

状态：已记录

发现：

- `10.20.11.3` 的 `smartx.db` 文件约 135M，其中 `latest_vm_volumes` 占约 94M。
- `latest_vm_volumes` 当前 523 行，但 `payload_json` 合计约 93M，最大单行约 268KB。
- 最大样本中单台 VM 的 `payload_json` 是 258 个虚拟卷对象列表，每个对象保存了较完整的 Tower 原始卷字段。
- 已将“优化 `latest_vm_volumes` 存储结构”和“兼容旧版本迁移包导入”加入 Phase 13。

要求：

- 新结构只保留页面、报表、导出和分析需要的字段。
- 旧版本迁移包导入时，从旧 `payload_json` 抽取所需字段写入新结构，其他原始字段丢弃。
- 需要配套旧数据迁移脚本，并验证 VM 页面、报表导出、迁移导入导出和历史指标分析。

### 2026-06-05 feature/upgrade-v2 受控重建任务文档

状态：已记录

新增文档：

- `docs/v2-rebuild-task-plan.md`

关键决策：

- `feature/upgrade-v2` 采用全新重写，但保留 v1 信息架构和核心功能口径。
- v2 必须支持 v1 现场数据迁入。
- v2 不兼容旧升级路径，升级中心、组件升级和 Prometheus 升级重新设计。
- 默认保持 5 个容器：`frontend`、`web-api`、`collector-worker`、`prometheus`、`upgrade-runner`。

同步更新：

- `task_plan.md` 新增 Phase 17，记录 v2 受控重建目标、产出文档和执行原则。

边界说明：

- 本次只写入任务文档和计划进度，不修改业务代码。

### 2026-06-06 v2 细化设计文档清单

状态：已记录

更新内容：

- 在 `docs/v2-rebuild-task-plan.md` 增加 `## 11. v2 细化设计文档清单`。
- 在 `task_plan.md` 的 Phase 17 补充 Phase V2-0 细化文档交付物。

Phase V2-0 计划产出：

- `docs/architecture-v2.md`
- `docs/v1-data-compatibility.md`
- `docs/v2-upgrade-center-design.md`
- `docs/v2-api-contracts.md`
- `docs/v2-frontend-design.md`
- `docs/v2-implementation-sequence.md`

边界说明：

- 本次只记录细化文档计划，还没有创建上述设计文档。
- 未修改业务代码。

### 2026-06-06 Phase V2-0 细化设计文档创建

状态：已完成第一批

新增文档：

- `docs/architecture-v2.md`
- `docs/v1-data-compatibility.md`
- `docs/v2-upgrade-center-design.md`
- `docs/v2-api-contracts.md`
- `docs/v2-frontend-design.md`
- `docs/v2-implementation-sequence.md`

同步更新：

- `docs/v2-rebuild-task-plan.md` 中 Phase V2-0 状态改为进行中，并勾选上述 6 个文档。
- `task_plan.md` 的 Phase 17 标记上述 6 个文档已创建。

边界说明：

- 本次只创建和更新文档。
- 未修改业务代码。
- Phase V2-0 仍需后续更新 `docs/functional-modules.md` 和 `docs/upgrade-issues.md`，把 v2 模块边界和旧升级问题规避策略映射进去。

### 2026-06-06 v2 远端测试约定

状态：已记录

约定：

- v2 后续构建、部署和现场验证可以使用 `10.20.11.3`。
- 远端执行 v2 验证前，必须确认仓库分支为 `feature/upgrade-v2`。

同步更新：

- `docs/v2-rebuild-task-plan.md`
- `docs/v2-implementation-sequence.md`
- `task_plan.md`

### 2026-06-06 Phase V2-0 文档收口与前端风格约束

状态：已完成

用户要求：

- 严格按照开发文档实施。
- 前端风格和 v1 保持一致。

更新内容：

- `docs/v2-frontend-design.md` 增加 v1 风格继承硬约束。
- `docs/functional-modules.md` 增加 v2 模块边界映射。
- `docs/upgrade-issues.md` 增加 v2 升级中心规避历史问题策略。
- `docs/v2-rebuild-task-plan.md` 标记 Phase V2-0 文档项完成，并记录前端风格边界。
- `task_plan.md` 同步前端风格要求和文档收口状态。

边界说明：

- 本次仍只更新文档。
- 后续代码实施必须按 v2 文档执行。
- 前端允许重构组件，但不能改变 v1 的整体视觉语言、导航结构、主要操作位置和业务术语。

验证记录：

- 文档敏感词检查未发现真实密码或 token。
- 固定字符串检查确认 `docs/functional-modules.md` 和 `docs/upgrade-issues.md` 的 Phase V2-0 待办没有遗留未勾选项。
- 固定字符串检查确认“前端风格必须和 v1 保持一致”已写入 `docs/v2-rebuild-task-plan.md`、`docs/functional-modules.md` 和 `task_plan.md`。

错误记录：

- 曾使用包含反引号的 `rg` 命令检查 markdown checkbox，zsh 将反引号解释为命令替换导致报错；已改用 `rg -F` 固定字符串重新检查。

### 2026-06-06 Phase V2-1 项目骨架启动

状态：进行中

实施内容：

- 新增 `backend/app/v2/` 命名空间。
- 新增 v2 后端模块占位：`auth`、`inventory`、`collection`、`metrics`、`forecast`、`reports`、`migration`、`upgrade`、`tasks`、`system`。
- 新增 `backend/app/v2/registry.py`，声明 v2 后端模块清单。
- 新增前端 v2 目录骨架：`frontend/src/v2/components`、`frontend/src/v2/pages`、`frontend/src/v2/services`、`frontend/src/v2/types`。
- 新增 `backend/tests/test_v2_skeleton.py`，用 Python 标准库 `unittest` 验证 v2 后端模块可导入和前端 v2 目录存在。

TDD 验证：

- RED：`PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_skeleton -v` 先失败，原因是 `app.v2` 和 `frontend/src/v2/*` 不存在。
- GREEN：新增最小骨架后，同一命令通过，2 个测试全部 OK。

本地验证：

- `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_skeleton -v` 通过。
- `python3 -m py_compile` 检查新增 v2 模块和测试文件通过。

限制：

- 本机缺少 `pytest`，暂不能跑 pytest 全量测试。
- 本机缺少 `npm`，暂不能跑前端构建。
- 完整 pytest、frontend build 和远端容器验证需要后续在 `10.20.11.3` 的 `feature/upgrade-v2` 分支执行。

### 2026-06-06 Phase V2-1 统一任务模型

状态：已完成本地最小验证

实施内容：

- 新增 `backend/app/v2/tasks/models.py`。
- 定义 `TaskStatus`：`pending`、`running`、`success`、`failed`、`cancelled`。
- 定义 `TaskType`：`report`、`migration_export`、`migration_import`、`upgrade`、`cleanup`、`collection`。
- 定义 `TaskSnapshot`，用于统一任务列表和任务详情的基础状态。
- 定义 `ErrorSnapshot`，用于返回安全的公开错误码和错误消息。

TDD 验证：

- RED：`PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_task_models -v` 先失败，原因是 `app.v2.tasks.models` 不存在。
- GREEN：新增最小模型后，同一命令通过，3 个测试全部 OK。

本地验证：

- `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_task_models -v` 通过。
- `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_skeleton -v` 通过。
- `python3 -m py_compile backend/app/v2/tasks/models.py backend/tests/test_v2_task_models.py` 通过。

### 2026-06-06 Phase V2-1 远端构建验证收口

状态：完成

远端验证位置：

- 主机：`10.20.11.3`
- v2 独立 worktree：`/opt/smartx-storage-forecast-v2`
- 分支来源：`origin/feature/upgrade-v2`
- 提交：`2894378`

注意：

- 原 `/opt/smartx-storage-forecast` 仍在 `dev` 且存在未提交变更，没有直接切换。
- v2 验证使用独立 worktree，避免影响现有 dev 环境。
- 远端构建前临时从 `.env.example` 复制 `.env`，仅用于 Docker compose build，不纳入提交。

远端验证：

- `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models -v` 通过，5 个测试 OK。
- `python3 -m py_compile backend/app/v2/__init__.py backend/app/v2/registry.py backend/app/v2/tasks/models.py backend/tests/test_v2_skeleton.py backend/tests/test_v2_task_models.py` 通过。
- `docker compose build web-api frontend` 通过。
- Docker 内 frontend 执行 `npm run build` 通过，仅保留 Vite 大 chunk 提示。

结论：

- Phase V2-1 项目骨架满足“后端语法检查通过、前端构建通过、空壳应用可构建”的阶段验收。
- `docs/v2-rebuild-task-plan.md` 已将 Phase V2-1 标记为完成。

### 2026-06-06 Phase V2-2 基础平台与认证

状态：进行中，本地核心验证完成

实施内容：

- 新增 `backend/app/v2/config.py`，定义 v2 版本读取、运行目录和环境配置。
- 新增 `backend/app/v2/security.py`，使用标准库实现密码哈希、密码校验、token 签发和 token 校验。
- 新增 `backend/app/v2/database.py`，实现 v2 SQLite 初始化、默认管理员创建和基础任务表。
- 新增 `backend/app/v2/auth/service.py`，实现登录、当前用户和修改密码核心服务。
- 新增 `backend/app/v2/system/health.py`，实现数据库和运行目录健康检查。
- 新增 `backend/app/v2/api.py` 和 `backend/app/v2/main.py`，提供独立 v2 FastAPI 应用壳：`/api/auth/login`、`/api/me`、`/api/me/password`、`/api/system/health`。
- 新增 `frontend/src/v2/services/auth.ts`，定义 v2 登录、当前用户、改密 API 客户端。
- 新增 `frontend/src/v2/components/AccountMenu.tsx`，保留 v1 风格的 admin 头像菜单：设置密码、登出。
- 新增 `frontend/src/v2/types/tasks.ts`，同步 v2 后台任务基础类型。

TDD 记录：

- RED：`PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_foundation -v` 先失败，原因是 `app.v2.config`、`app.v2.auth.service` 等模块不存在。
- GREEN：新增 v2 配置、数据库、认证、安全和健康检查模块后，`backend.tests.test_v2_foundation` 通过。
- RED：新增 `test_settings_from_environment_reads_current_environment` 后先失败，原因是 `V2Settings` 默认值在模块导入时读取环境变量。
- GREEN：将环境变量默认值改为 `default_factory` 后，该测试通过。
- 新增 `backend/tests/test_v2_auth_api.py`；本机缺少 FastAPI 依赖时跳过，远端/Docker 环境用于实际验证 API 链路。

本地验证：

- `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_auth_api -v` 通过：10 个测试 OK，1 个 FastAPI 集成测试因本机缺依赖跳过。
- `python3 -m py_compile backend/app/v2/api.py backend/app/v2/main.py backend/app/v2/config.py backend/app/v2/security.py backend/app/v2/database.py backend/app/v2/auth/service.py backend/app/v2/system/health.py backend/tests/test_v2_foundation.py backend/tests/test_v2_auth_api.py` 通过。

待验证：

- 在 `10.20.11.3` 的 `/opt/smartx-storage-forecast-v2` 拉取 `feature/upgrade-v2` 后运行 v2 unittest，确认 FastAPI 集成测试实际通过。
- 在远端执行 `docker compose build web-api frontend`，确认后端和前端构建均通过。
- 如后续决定将 Docker 入口切到 `app.v2.main:app`，需要另起阶段处理，因为 Phase V2-2 当前只提供独立 v2 应用壳，不覆盖 v1 主入口。

远端验证中发现：

- `docker compose build web-api frontend` 已通过，frontend `tsc -b && vite build` 通过，仅保留原有 Vite 大 chunk 提示。
- 第一次在 Docker 中运行 v2 unittest 时只挂载了 `backend`，导致 `test_frontend_v2_skeleton_directories_exist` 看不到 `frontend/src/v2/*`，这是测试运行方式问题，后续改为挂载仓库根目录。
- Docker 镜像内存在 `/app/VERSION`，因此 `settings_from_environment()` 返回镜像自带版本是正确行为；测试已改为单独验证 `read_version()` 在版本文件缺失时才使用 `SMARTX_APP_VERSION` 兜底。
- 修正测试后已推送到 `origin/feature/upgrade-v2`，最新提交 `837d49a`。
- 继续在 `10.20.11.3` 拉取最新并补跑 Docker 内 API 集成测试时，SSH 连接超时断开；随后本机到 `10.20.11.3` 的 ping 和 22/tcp 均显示 network unreachable。该远端验证项暂未完成，待网络恢复后继续。
- 本机创建临时 venv `/tmp/smartx-v2-venv` 安装后端依赖后，FastAPI API 集成测试真实执行通过：未登录 `/api/me` 返回 401、默认 admin 登录成功、`/api/me` 返回当前用户、密码不一致返回 400、改密成功、旧密码失效、新密码可登录。
- API 集成测试曾在 Python 3.9 venv 下暴露 `HTTPAuthorizationCredentials | None` 注解兼容问题，已改为 `Optional[HTTPAuthorizationCredentials]`，兼容 Python 3.9/3.12。

### 2026-06-06 Phase V2-2 远端验证收口

状态：完成

远端验证位置：

- 主机：`10.20.11.3`
- v2 worktree：`/opt/smartx-storage-forecast-v2`
- 分支：`feature/upgrade-v2`
- 提交：`bb2f156`

验证记录：

- `git pull --ff-only origin feature/upgrade-v2` 成功拉到 `bb2f156`。
- `docker compose build web-api frontend` 通过。
- `docker run --rm -v /opt/smartx-storage-forecast-v2:/src -e PYTHONPATH=/src/backend -w /src smartx-storage-forecast-web-api:local python -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_auth_api -v` 通过：12 个测试 OK。
- FastAPI 集成测试在 Python 3.12 容器内真实执行，覆盖未登录 401、登录、`/api/me`、密码不一致、改密、旧密码失效、新密码登录。

结论：

- Phase V2-2 基础平台与认证满足阶段验收。
- `docs/v2-rebuild-task-plan.md` 已将 Phase V2-2 标记为完成。

### 2026-06-06 Phase V2-3 Tower/Cluster 与指标格式基础

状态：进行中，第一薄片完成本地验证

实施内容：

- `backend/app/v2/database.py` 增加 v2 `towers`、`clusters`、`vm_latest` 表。
- 新增 `backend/app/v2/inventory/models.py`，定义 Tower/Cluster 输入和安全响应记录。
- 新增 `backend/app/v2/inventory/service.py`，实现 Tower 创建、列表、更新、删除、集群同步、集群启用/改名。
- 新增 `backend/app/v2/inventory/scope.py`，统一 all/Tower/cluster scope 解析，并禁止只传 cluster_id 不传 tower_id。
- 新增 `backend/app/v2/metrics/formatter.py`，生成 `smartx_cluster_storage_used_bytes`、`smartx_cluster_storage_total_bytes`、`smartx_vm_storage_used_bytes` 指标文本，VM 指标使用 `tower_id + cluster_id + vm_id` 稳定身份，`vm_name` 仅展示。
- `backend/app/v2/api.py` 增加 v2 Tower CRUD、集群同步和集群更新接口，所有接口复用 `require_user` 鉴权，不返回 password/api_token。

TDD 记录：

- RED：`PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_inventory_metrics -v` 先失败，原因是 `inventory.models`、`inventory.scope`、`metrics.formatter` 不存在。
- GREEN：新增 inventory service/scope 和 metrics formatter 后，该测试通过。
- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_inventory_api -v` 先返回 `/api/towers` 404，说明 v2 API 未接 Tower。
- GREEN：新增 v2 Tower/Cluster API 后，inventory API 测试通过。
- 修复：Python 3.9 + Pydantic 对 `bool | None` 注解不兼容，API 层 Pydantic 模型改为 `Optional[...]`。

本地验证：

- `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v` 通过：14 个测试 OK，2 个 FastAPI 集成测试因本机基础 Python 缺依赖跳过。
- `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v` 通过：16 个测试 OK。
- `python3 -m py_compile backend/app/v2/api.py backend/app/v2/database.py backend/app/v2/security.py backend/app/v2/inventory/models.py backend/app/v2/inventory/service.py backend/app/v2/inventory/scope.py backend/app/v2/metrics/formatter.py backend/tests/test_v2_inventory_metrics.py backend/tests/test_v2_inventory_api.py` 通过。

待处理：

- Phase V2-3 后续还需要 CloudTower 客户端、连接测试、手动采集、collector-worker 定时采集、Prometheus 写入和查询服务。
- 当前只完成 Tower/Cluster 存储与 API、指标文本格式基础，尚未打通真实采集链路。

### 2026-06-06 Phase V2-3 手动采集基础链路

状态：进行中，fake client 驱动的采集基础完成本地验证

实施内容：

- `backend/app/v2/database.py` 增加 `collection_runs` 表。
- 新增 `backend/app/v2/collection/service.py`。
- `CollectionService.run_manual_collection()` 读取已启用 Tower 和已启用集群，调用注入的 CloudTower collector，更新 `vm_latest`，生成 Prometheus 指标文本，并记录 collection run 状态。
- 采集失败时根据 Tower 凭据做错误摘要脱敏，避免 password/api_token 出现在返回 message 中。

TDD 记录：

- RED：`PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_collection -v` 先失败，原因是 `app.v2.collection.service` 不存在。
- GREEN：新增 `CollectionService` 后测试通过。

本地验证：

- `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_collection backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v` 通过：16 个测试 OK，2 个 FastAPI 集成测试因本机基础 Python 缺依赖跳过。
- `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_collection backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v` 通过：18 个测试 OK。
- `python3 -m py_compile backend/app/v2/collection/service.py backend/app/v2/database.py backend/tests/test_v2_collection.py` 通过。

限制：

- 当前采集测试使用 fake CloudTower collector，尚未实现真实 CloudTower HTTP 客户端。
- 当前仅生成 Prometheus exposition 文本，尚未接入 Prometheus 写入/查询服务。

### 2026-06-06 Phase V2-3 远端 Docker 验证

状态：完成

远端验证位置：

- 主机：`10.20.11.3`
- v2 worktree：`/opt/smartx-storage-forecast-v2`
- 分支：`feature/upgrade-v2`
- 提交：`d38ae2b`

验证记录：

- `git pull --ff-only origin feature/upgrade-v2` 成功拉到 `d38ae2b`。
- `docker compose build web-api frontend` 通过。
- `docker run --rm -v /opt/smartx-storage-forecast-v2:/src -e PYTHONPATH=/src/backend -w /src smartx-storage-forecast-web-api:local python -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_collection backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v` 通过：18 个测试 OK。

结论：

- V2-3 已完成 Tower/Cluster 存储与 API、指标文本格式、fake client 手动采集基础链路的远端容器验证。
- 后续继续实现真实 CloudTower HTTP 客户端、连接测试接口、Prometheus 查询/健康服务和 collector-worker 定时采集。

### 2026-06-06 Phase V2-3 CloudTower 客户端与 Prometheus 查询基础

状态：进行中，真实客户端与查询基础完成本地验证

实施内容：

- 新增 `backend/app/v2/cloudtower/client.py` 和 `backend/app/v2/cloudtower/service.py`。
- v2 CloudTower 客户端支持用户名密码登录、API token、分页请求、集群列表归一化、集群容量和 VM 容量归一化。
- `POST /api/towers/{tower_id}/test` 接入 v2 API，连接成功后同步集群，连接失败返回脱敏后的错误摘要。
- `POST /api/collection/run` 接入 v2 API，复用 `CollectionService` 和真实 CloudTower service 执行手动采集。
- 新增 `backend/app/v2/metrics/prometheus.py`，提供 Prometheus `/-/ready` 健康检查、instant query 和 query_range 解析。
- v2 系统健康检查增加 Prometheus 检查项。

TDD 记录：

- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_cloudtower_client backend.tests.test_v2_inventory_api -v` 先失败，原因是 `app.v2.cloudtower` 和 `get_cloudtower_service` 不存在。
- GREEN：新增 CloudTower client/service 和 API 连接测试入口后，目标测试通过。
- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_prometheus_service -v` 先失败，原因是 `app.v2.metrics.prometheus` 不存在。
- GREEN：新增 PrometheusService 后，Prometheus 目标测试通过。
- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_foundation -v` 先失败，原因是健康检查不支持 Prometheus 注入。
- GREEN：健康检查接入 Prometheus 后，基础测试通过。

本地验证：

- `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_cloudtower_client backend.tests.test_v2_prometheus_service backend.tests.test_v2_collection backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v` 通过：25 个测试 OK。
- `python3 -m py_compile backend/app/v2/api.py backend/app/v2/cloudtower/client.py backend/app/v2/cloudtower/service.py backend/app/v2/collection/service.py backend/app/v2/inventory/service.py backend/app/v2/metrics/prometheus.py backend/app/v2/system/health.py backend/tests/test_v2_cloudtower_client.py backend/tests/test_v2_prometheus_service.py backend/tests/test_v2_inventory_api.py backend/tests/test_v2_foundation.py` 通过。

限制：

- 当前 Prometheus 已有查询/健康服务，但采集数据仍只返回 exposition 文本，尚未完成 collector-worker 暴露 `/metrics` 或写入式闭环。
- collector-worker 定时采集仍未实现。

### 2026-06-06 Phase V2-3 collector-worker 与 Prometheus scrape 基础

状态：完成本地验证，待远端 Docker 验证

实施内容：

- v2 schema 增加 `metric_snapshots`，采集成功后保存最近一次 Prometheus exposition 文本。
- `CollectionService.latest_metrics_text()` 可读取最近指标文本，供 worker 暴露 `/metrics`。
- 新增 `backend/app/v2/worker.py`：
  - 提供 `/metrics` HTTP handler。
  - 使用 `BackgroundScheduler` 按 `SMARTX_COLLECTION_HOUR` 和 `SMARTX_COLLECTION_MINUTE` 定时执行采集。
  - 定时采集复用 v2 `CloudTowerService` 和 `CollectionService`。
- v2 运行入口切换：
  - `backend/Dockerfile` 从 `app.main:app` 切到 `app.v2.main:app`。
  - `backend/Dockerfile.worker` 从 `app.collector.worker` 切到 `app.v2.worker`。
  - `docker-compose.yml`、`docker-compose.offline.yml`、`docker-compose.release.yml` 的 collector-worker 命令切到 `app.v2.worker`。
- `docs/v2-rebuild-task-plan.md` 将 V2-3 的 collector-worker、Prometheus 查询/健康、Prometheus scrape 基础标记为完成。

TDD 记录：

- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_collection -v` 先失败，原因是 `CollectionService.latest_metrics_text()` 不存在。
- GREEN：新增 `metric_snapshots` 和读取/保存逻辑后测试通过。
- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_worker -v` 先失败，原因是 `app.v2.worker` 不存在。
- GREEN：新增 v2 worker 后测试通过。
- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_skeleton -v` 先失败，原因是 Dockerfile/compose 仍指向 v1 入口。
- GREEN：切换 v2 运行入口后 skeleton 测试通过。

本地验证：

- `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_cloudtower_client backend.tests.test_v2_prometheus_service backend.tests.test_v2_collection backend.tests.test_v2_worker backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v` 通过：28 个测试 OK。
- `python3 -m py_compile backend/app/v2/api.py backend/app/v2/cloudtower/client.py backend/app/v2/cloudtower/service.py backend/app/v2/collection/service.py backend/app/v2/database.py backend/app/v2/inventory/service.py backend/app/v2/metrics/prometheus.py backend/app/v2/system/health.py backend/app/v2/worker.py backend/tests/test_v2_skeleton.py backend/tests/test_v2_cloudtower_client.py backend/tests/test_v2_prometheus_service.py backend/tests/test_v2_collection.py backend/tests/test_v2_worker.py backend/tests/test_v2_inventory_api.py backend/tests/test_v2_foundation.py` 通过。

限制：

- 本机没有 Docker CLI，`docker compose build web-api collector-worker frontend` 无法本地执行，错误为 `zsh:1: command not found: docker`。
- 需要在 `10.20.11.3` 上拉取 `feature/upgrade-v2` 后执行 Docker 构建和容器内测试。
- Phase V2-3 的采集和指标基础链路已具备，但 Dashboard/VM/报表展示仍属于后续 V2-4/V2-5。

### 2026-06-06 Phase V2-3 远端 Docker 验证补充

状态：完成

远端验证位置：

- 主机：`10.20.11.3`
- v2 worktree：`/opt/smartx-storage-forecast-v2`
- 分支：`feature/upgrade-v2`
- 提交：`38a5af1`

验证记录：

- `git pull --ff-only origin feature/upgrade-v2` 成功拉到 `38a5af1`。
- `docker compose build web-api collector-worker frontend` 通过，确认 v2 `web-api`、v2 `collector-worker` 和前端镜像可构建。
- `docker run --rm -v /opt/smartx-storage-forecast-v2:/src -e PYTHONPATH=/src/backend -w /src smartx-storage-forecast-web-api:local python -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_cloudtower_client backend.tests.test_v2_prometheus_service backend.tests.test_v2_collection backend.tests.test_v2_worker backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v` 通过：28 个测试 OK。

结论：

- Phase V2-3 的 Tower、真实 CloudTower 客户端、连接测试、手动采集、collector-worker 定时采集基础、Prometheus `/metrics` scrape 基础、Prometheus 查询和健康检查基础已完成本地与远端容器验证。
- 后续进入 Phase V2-4：Dashboard 和 VM 页面，重点把 Prometheus 历史查询结果接入容量风险、日增长、本日新建 VM、VM 列表和趋势。

### 2026-06-06 Phase V2-4 Dashboard/VM 后端第一薄片

状态：完成本地验证，待远端 Docker 验证

实施内容：

- 新增 `backend/app/v2/dashboard/service.py`：
  - 汇总 Tower/集群/VM 数量。
  - 从 Prometheus 集群 used/total 指标计算容量使用率。
  - 任一集群使用率 `>= 80%` 返回 high 风险；`>= 75%` 返回 warning；否则返回 `当前所有集群暂无明显容量风险`。
  - 日增长最快 VM 根据 24 小时 Prometheus range 数据计算增长量和增长率。
  - 本日新建 VM 按 24 小时 range 是否缺少历史样本判断。
  - VM 展示名称优先使用 SQLite `vm_latest` 最新采集名称。
- 新增 `backend/app/v2/vms/service.py`：
  - VM 列表按 scope 查询 Prometheus 即时值。
  - VM 趋势强制使用 `tower_id + cluster_id + vm_id` 查询，避免跨 Tower/集群混合。
  - VM 改名后趋势展示仍使用 SQLite 最新名称。
- 新增 `backend/app/v2/metrics/series.py`，统一解析 Prometheus instant/range 数据和构造带 label 的查询。
- v2 API 增加：
  - `GET /api/dashboard/summary`
  - `GET /api/vms`
  - `GET /api/vms/{vm_id}/trend`
- `backend/app/v2/registry.py` 增加 `dashboard` 和 `vms` 模块。
- `docs/v2-rebuild-task-plan.md` 将 Phase V2-4 标记为进行中，并标出后端基础已完成。

TDD 记录：

- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_dashboard_vm -v` 先失败，原因是 `app.v2.dashboard` 和 `app.v2.vms` 不存在。
- GREEN：新增 Dashboard/VM service 后，Dashboard/VM 服务测试通过。
- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_dashboard_vm_api -v` 先失败，原因是 API 未提供 `get_dashboard_service` 和 `get_vm_service`。
- GREEN：接入 v2 API 后，Dashboard/VM API 测试通过。

本地验证：

- `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_cloudtower_client backend.tests.test_v2_prometheus_service backend.tests.test_v2_collection backend.tests.test_v2_worker backend.tests.test_v2_dashboard_vm backend.tests.test_v2_dashboard_vm_api backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v` 通过：31 个测试 OK。
- `python3 -m py_compile backend/app/v2/api.py backend/app/v2/dashboard/service.py backend/app/v2/vms/service.py backend/app/v2/metrics/series.py backend/app/v2/registry.py backend/tests/test_v2_dashboard_vm.py backend/tests/test_v2_dashboard_vm_api.py backend/tests/test_v2_skeleton.py` 通过。

限制：

- 本次只完成 Dashboard/VM 后端第一薄片。
- VM 详情和卷信息仍待实现。
- 前端 Dashboard/VM 页面仍待接入 v2 API。

### 2026-06-06 Phase V2-4 VM 详情和卷信息后端

状态：完成本地验证，待远端 Docker 验证

实施内容：

- v2 schema 增加 `vm_volumes` 结构化卷表。
- CloudTower client 在采集 VM 时同步获取 VM volumes，并归一化为：
  - `volume_id`
  - `name`
  - `path`
  - `size_bytes`
  - `used_bytes`
  - `storage_policy`
  - `replica_num`
  - `thin_provision`
  - `ec_k`
  - `ec_m`
- `CollectionService` 采集成功后按 `tower_id + cluster_id + vm_id` 替换该 VM 最新卷信息，避免旧卷残留。
- `VmService` 增加：
  - `detail(vm_id, tower_id, cluster_id)`
  - `volumes(vm_id, tower_id, cluster_id)`
- v2 API 增加：
  - `GET /api/vms/{vm_id}`
  - `GET /api/vms/{vm_id}/volumes`
- 详情和卷接口均强制要求 `tower_id` 和 `cluster_id`，避免跨 Tower/集群混合。
- `docs/v2-rebuild-task-plan.md` 将 VM 详情和卷信息后端基础标记为完成。

TDD 记录：

- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_collection backend.tests.test_v2_dashboard_vm -v` 先失败，原因是 `vm_volumes` 表不存在。
- GREEN：新增 `vm_volumes` schema、采集保存逻辑、VM detail/volumes service 后，目标测试通过。
- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_cloudtower_client -v` 先失败，原因是 CloudTower client 未返回 `volumes`。
- GREEN：新增 CloudTower 卷归一化和每 VM 获取卷后，目标测试通过。
- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_dashboard_vm_api -v` 先失败，原因是 VM detail API 404。
- GREEN：新增 VM detail 和 volumes API 后，API 测试通过。

本地验证：

- `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_cloudtower_client backend.tests.test_v2_prometheus_service backend.tests.test_v2_collection backend.tests.test_v2_worker backend.tests.test_v2_dashboard_vm backend.tests.test_v2_dashboard_vm_api backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v` 通过：32 个测试 OK。
- `python3 -m py_compile backend/app/v2/api.py backend/app/v2/cloudtower/client.py backend/app/v2/collection/service.py backend/app/v2/database.py backend/app/v2/vms/service.py backend/tests/test_v2_cloudtower_client.py backend/tests/test_v2_collection.py backend/tests/test_v2_dashboard_vm.py backend/tests/test_v2_dashboard_vm_api.py` 通过。

限制：

- 本次只完成 VM 详情和卷信息后端。
- Dashboard/VM 前端页面仍待接入 v2 API。

远端验证：

- 2026-06-06 09:19 CST，在 `10.20.11.3:/opt/smartx-storage-forecast-v2` 使用 `smartx-storage-forecast-web-api:local` 容器执行完整 v2 后端测试集。
- 命令：`docker run --rm -v /opt/smartx-storage-forecast-v2:/src -e PYTHONPATH=/src/backend -w /src smartx-storage-forecast-web-api:local python -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_cloudtower_client backend.tests.test_v2_prometheus_service backend.tests.test_v2_collection backend.tests.test_v2_worker backend.tests.test_v2_dashboard_vm backend.tests.test_v2_dashboard_vm_api backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v`
- 结果：32 个测试通过，`OK`。

### 2026-06-06 Phase V2-4 Dashboard/VM 前端接入

状态：完成临时远端容器验证，待正式远端仓库构建验证

实施内容：

- 前端 API 层兼容 v2 Dashboard 响应：
  - `totals` 归一到旧页面使用的 `kpis`。
  - `storage` 归一到容量使用数据。
  - `day_fastest_growing_vms` 和 `day_new_vms` 归一为页面 `MetricItem`。
  - `capacity_risk.level=high` 归一为页面 danger tone。
- Dashboard 页面改为优先展示 v2 `day_fastest_growing_vms`。
- Dashboard 在“日增长最快 VM”下面新增独立“本日新建 VM”卡片，VM 项点击仍跳转到虚拟机页面。
- VM 页面移除旧的全量 `/api/vm-volumes` 依赖，改为选中 VM 后调用：
  - `GET /api/vms/{vm_id}`
  - `GET /api/vms/{vm_id}/volumes`
  - `GET /api/vms/{vm_id}/trend`
- VM 趋势点兼容 v2 `{timestamp, used_bytes}` 格式并转换为图表需要的 `[timestamp, value]`。
- 前端测试增加自动 cleanup，避免多个 render 残留造成误报。
- `docs/v2-rebuild-task-plan.md` 将 Dashboard/VM 前端接入标记完成。

TDD 记录：

- RED：新增 `frontend/src/pages/VmsPage.test.tsx` 后，在远端临时目录运行前端测试失败，原因是 `VmsPage` 仍调用 `api.vmVolumesAll(scope).then(...)`，测试明确要求单 VM 卷接口。
- RED：新增 Dashboard v2 日增长/新建 VM 测试后，页面没有显示 v2 `day_fastest_growing_vms` 数据，也没有“本日新建 VM”独立卡片。
- GREEN：改 API 归一化和 Dashboard/VM 页面后，目标前端测试通过。

验证：

- 远端临时目录 `/tmp/smartx-v2-redcheck`：
  - `npm test -- --run src/pages/DashboardPage.test.tsx src/pages/VmsPage.test.tsx` 通过：2 个测试文件，4 个测试。
  - `npm run build` 通过，Vite 成功生成 `dist`。
- 干净 staged 树 `/tmp/smartx-v2-staged`：
  - 前端目标测试通过：2 个测试文件，4 个测试。
  - `npm run build` 通过。
  - 后端完整 v2 测试集通过：32 个测试 OK。
- 正式远端仓库 `10.20.11.3:/opt/smartx-storage-forecast-v2` 已拉取到 `b64ec7a`。
- 正式远端仓库执行 `docker compose build web-api frontend` 通过。

限制：

- 本阶段只完成 Dashboard/VM 前端接入。
- 报表页跳转到 VM、月增长、本月新建 VM 属于后续 V2-5 报表阶段。

### 2026-06-06 Phase V2-5 报表 latest_report 第一切片

状态：完成本地和远端验证，待提交

实施内容：

- 新增 `backend/app/v2/reports/service.py`。
- `ReportService.latest_report()` 支持：
  - 集群 90 天预测。
  - 最近 7 天平均容量增长速率。
  - 7/14/30/90/180/365 天统计窗口归一。
  - 7/30/90/365/720 天趋势窗口归一。
  - 日增长 VM、月增长 VM。
  - 月增长 VM 样本跨度不足 30 天时过滤。
  - 本日新建 VM、本月新建 VM。
  - VM 展示名称优先使用 `vm_latest` 最新名称。
- v2 API 新增 `GET /api/reports/latest`，支持全部、Tower、集群 scope。
- 报表页已有结构接入 v2 合同：
  - 显示 90 天预测文案和值。
  - 显示 7 天平均增长速率。
  - 显示日/月增长 VM 和本日/本月新建 VM。
  - VM 项点击可跳转虚拟机页面。
- 新增测试：
  - `backend/tests/test_v2_reports.py`
  - `backend/tests/test_v2_reports_api.py`
  - `frontend/src/pages/ReportsPage.test.tsx`
- `docs/v2-rebuild-task-plan.md` 将 Phase V2-5 第一切片标记为进行中/部分完成。

TDD 记录：

- RED：报表后端测试先失败，原因是 `app.v2.reports.service` 不存在。
- GREEN：新增 `ReportService` 后，报表服务测试通过。
- RED：报表 API 测试先失败，原因是 `get_report_service` 和 `/api/reports/latest` 不存在。
- GREEN：接入 API 后，鉴权、scope、period/chart 参数测试通过。
- 前端新增报表页面测试，验证 v2 合同内容和 VM 跳转。

兼容性修复：

- 当前本地测试环境为 Python 3.9，`dataclass(slots=True)` 和 `zip(..., strict=True)` 不兼容，已改为 Python 3.9 兼容写法。
- “本日新建 VM”测试假数据改为自然日内首次出现，保持业务定义为平台自然日。

验证：

- 本地：
  - `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_reports backend.tests.test_v2_reports_api -v` 通过。
  - v2 后端完整测试集 34 个测试通过。
  - `python3 -m py_compile backend/app/v2/api.py backend/app/v2/reports/service.py backend/tests/test_v2_reports.py backend/tests/test_v2_reports_api.py` 通过。
- 远端 `10.20.11.3:/opt/smartx-storage-forecast-v2`：
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行报表后端测试通过。
  - 使用临时 `node:22-alpine` 容器安装前端依赖并执行 `npm test -- --run src/pages/ReportsPage.test.tsx` 通过。

限制：

- 本切片尚未实现 v2 Word/Excel 导出、报表文件留存和任务中心下载链接。

### 2026-06-06 Phase V2-5 报表导出与留存第一版

状态：完成本地和远端验证，待提交

实施内容：

- 新增 `backend/app/v2/reports/export.py`。
- v2 API 新增：
  - `GET /api/reports/export/word`
  - `GET /api/reports/export/excel`
  - `GET /api/admin/exports/reports/{filename}`
- Word/Excel 导出复用 `ReportService.latest_report()` 输出，确保与页面口径一致。
- 导出文件保存到 `settings.reports_dir`，即 `/data/exports/reports`。
- 下载响应头提供：
  - `Content-Disposition`
  - `X-SmartX-Export-Path`
  - `X-SmartX-Export-Url`
- 文件名格式使用 `storage-forecast-<scope>-YYYYMMDD-HHmmss-<days>d.docx/xlsx`。
- Word 首页包含导出范围、生成时间、统计窗口、预测窗口、集群数量、当前软件版本。
- Excel `汇总` sheet 包含同样基础信息，`VM_TOP100_汇总` sheet 标注统计窗口。
- 高风险 VM 底纹逻辑第一版已接入：增长率超过 20% 且增长量大于 100G 时标红。
- `docs/v2-rebuild-task-plan.md` 将 Word/Excel 导出和留存第一版标记完成。

TDD 记录：

- RED：新增 `backend/tests/test_v2_report_exports.py` 后，未登录访问 `/api/reports/export/word` 返回 404，证明 v2 导出路由缺失。
- GREEN：新增导出模块和 API 路由后，导出鉴权、文件保存、响应头、下载链接测试通过。

验证：

- 本地：
  - `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_report_exports -v` 通过。
  - v2 后端完整测试集 35 个测试通过。
  - `python3 -m py_compile backend/app/v2/api.py backend/app/v2/reports/service.py backend/app/v2/reports/export.py backend/tests/test_v2_report_exports.py` 通过。
- 远端 `10.20.11.3:/opt/smartx-storage-forecast-v2`：
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_reports backend.tests.test_v2_reports_api backend.tests.test_v2_report_exports` 通过。

限制：

- 当前是导出第一版，文档视觉仍是轻量客户报表，不是 v1 已打磨的完整美化版。
- 报表导出任务中心目前使用前端现有同步下载任务入口，尚未接入 v2 统一后台任务状态持久化。

### 2026-06-06 Phase V2-11 统一任务中心基础

状态：完成本地和远端验证，待提交

实施内容：

- 新增 `backend/app/v2/tasks/service.py`。
- 扩展 `tasks` 表，增加 `links_json` 和 `logs_json`，并为旧库提供 `_ensure_column` 兼容。
- `TaskService` 支持：
  - 创建任务。
  - 更新状态、进度、消息、日志、下载链接。
  - 列出最近任务。
  - 清理已完成任务。
- v2 API 新增：
  - `GET /api/tasks`
  - `DELETE /api/tasks/finished`
- `V2Settings` 增加 `__post_init__`，确保 `data_root` 即使传入字符串也会转为 `Path`。
- 前端 App 登录后轮询 `/api/tasks`，将服务端任务合并到右上角任务菜单。
- 前端清空任务按钮调用 `/api/tasks/finished`，并保留本地运行中任务。
- 报表导出成功后写入 `report` 任务，包含 Word/Excel 下载链接，刷新后仍可在任务菜单看到。

TDD 记录：

- RED：新增 `backend/tests/test_v2_tasks_api.py` 后，`app.v2.tasks.service` 缺失。
- GREEN：新增 `TaskService`、tasks API 后，持久化、列表、清理测试通过。
- RED：扩展 `backend/tests/test_v2_report_exports.py` 要求导出后写入任务表，初始返回 0 个 report 任务。
- GREEN：导出路由写入成功任务和下载链接后测试通过。

验证：

- 本地：
  - `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_report_exports backend.tests.test_v2_tasks_api -v` 通过。
  - v2 后端完整测试集 37 个测试通过。
  - `python3 -m py_compile backend/app/v2/api.py backend/app/v2/config.py backend/app/v2/database.py backend/app/v2/tasks/service.py backend/tests/test_v2_tasks_api.py` 通过。
- 远端 `10.20.11.3:/opt/smartx-storage-forecast-v2`：
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_report_exports backend.tests.test_v2_tasks_api` 通过。
  - `docker compose build frontend` 通过。

限制：

- 当前任务中心还没有独立步骤表，步骤化进度会在迁移/升级/清理模块接入时继续扩展。

### 2026-06-06 Phase V2-6 数据迁移灾备第一版

状态：完成本地和远端验证，待提交

实施内容：

- 新增 `backend/app/v2/migration/service.py`。
- v2 迁移包格式第一版：
  - `manifest.json`
  - `app/smartx.db`
  - `prometheus/**`
- 迁出：
  - 生成 `.tar.gz` 迁移包。
  - 跳过 Prometheus 运行时目录：`chunks_head`、`lock`、`queries.active`、`wal`。
  - 保存到 `/data/exports/migrations`。
  - 写入 `migration_export` 任务并提供下载链接。
- 迁入：
  - 上传文件保存到 `/data/exports/imports/{task_id}/`。
  - 解压前校验 tar 成员路径，拒绝绝对路径和 `..`。
  - 写入前强制生成 `/data/backups/import-before-*.tar.gz`。
  - 备份包含当前 `app/smartx.db` 和 Prometheus 历史目录。
  - merge 模式使用 `INSERT OR IGNORE`，不覆盖已有 Tower、集群、VM 最新元数据、卷、采集记录和 metrics snapshot。
  - Prometheus 历史目录只补齐缺失文件。
- v2 API 新增：
  - `GET /api/admin/migration/export`
  - `POST /api/admin/migration/import`
  - `/api/admin/exports/migrations/{filename}` 下载分类。
- `docs/v2-rebuild-task-plan.md` 将迁出、迁入、导入前备份、任务中心链接第一版标记完成。

TDD 记录：

- RED：新增 `backend/tests/test_v2_migration.py` 后，`app.v2.migration.service` 缺失。
- GREEN：新增 `MigrationService` 后，迁出包含 SQLite/Prometheus、任务链接、导入前备份、merge 不覆盖已有集群测试通过。
- RED：新增迁移 API 测试后，未登录访问 `/api/admin/migration/export` 返回 404。
- GREEN：接入 v2 migration API 后，鉴权、导出、下载、导入备份测试通过。

验证：

- 本地：
  - `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_migration -v` 通过。
  - v2 后端完整测试集 40 个测试通过。
  - `python3 -m py_compile backend/app/v2/api.py backend/app/v2/migration/service.py backend/tests/test_v2_migration.py` 通过。
- 远端 `10.20.11.3:/opt/smartx-storage-forecast-v2`：
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_migration` 通过。

### 2026-06-06 Phase V2-7 升级开始前数据备份第一版

状态：完成本地和远端验证，待提交

实施内容：

- `UpgradeService` 增加 `start(task_id)`。
- `POST /api/admin/upgrade/start/{task_id}` 接入。
- start 前要求任务状态为 `precheck_passed`。
- start 阶段生成升级前数据备份：
  - 路径：`/data/backups/upgrade-<version>-before-<YYYYMMDDHHMMSS>.tar.gz`
  - 内容：`manifest.json`、`app/smartx.db`、Prometheus 历史目录。
  - 跳过 Prometheus 运行时目录：`chunks_head`、`lock`、`queries.active`、`wal`。
- 任务状态更新为 `backup_completed`，统一任务中心记录“升级前备份已完成，等待 runner 执行后续步骤”。
- `docs/v2-rebuild-task-plan.md` 将“升级前强制备份数据第一版”标记完成。

TDD 记录：

- RED：扩展 `backend/tests/test_v2_upgrade.py` 后，`UpgradeService.start()` 缺失，`/api/admin/upgrade/start/{task_id}` 返回 404。
- GREEN：新增 start 备份阶段和 API 路由后，服务和 API 测试通过。

验证：

- 本地：
  - `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade -v` 通过。
  - v2 后端完整测试集 46 个测试通过。
  - `python3 -m py_compile backend/app/v2/api.py backend/app/v2/upgrade/service.py backend/tests/test_v2_upgrade.py` 通过。
- 远端 `10.20.11.3:/opt/smartx-storage-forecast-v2`：
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_upgrade` 通过。

限制：

- start 当前只完成强制备份，不执行 Docker load、项目文件同步、服务重启和健康检查；这些仍需由 runner 执行链路继续实现。

限制：

- 当前是 v2 迁移第一版，v1 旧迁移包和旧 `latest_vm_volumes.payload_json` 到 v2 结构化卷表的深度兼容仍待实现。
- 迁移任务已有任务中心记录，但尚未拆分为持久化步骤表。

### 2026-06-06 Phase V2-8 空间清理第一版

状态：完成本地和远端验证，待提交

实施内容：

- 新增 `backend/app/v2/cleanup/service.py`。
- v2 API 新增：
  - `GET /api/admin/system/cleanup-artifacts/scan`
  - `POST /api/admin/system/cleanup-artifacts`
- 清理范围第一版：
  - `/data/upgrades`
  - `/data/exports/reports`
  - `/data/exports/migrations`
  - `/data/exports/imports`
- 清理明确不碰 `/data/backups`。
- 扫描返回每项：
  - key、label、path、count、size、size_label。
  - total_count、total_size、space_reclaimable。
- 清理按真实文件大小统计释放空间，并写入 `cleanup` 任务日志。
- `docs/v2-rebuild-task-plan.md` 将空间扫描和清理第一版标记完成。

TDD 记录：

- RED：新增 `backend/tests/test_v2_cleanup.py` 后，`app.v2.cleanup` 缺失。
- GREEN：新增 `CleanupService` 后，扫描/清理真实大小、不删除 backups、任务记录测试通过。
- 扩展 API 测试后，清理接口鉴权、扫描和执行测试通过。

验证：

- 本地：
  - `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_cleanup -v` 通过。
  - v2 后端完整测试集 42 个测试通过。
  - `python3 -m py_compile backend/app/v2/api.py backend/app/v2/cleanup/service.py backend/tests/test_v2_cleanup.py` 通过。
- 远端 `10.20.11.3:/opt/smartx-storage-forecast-v2`：
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_cleanup` 通过。

限制：

- 旧 Docker 镜像扫描/清理尚未接入 v2；本阶段只完成运行文件产物清理。

### 2026-06-06 Phase V2-7 升级中心 manifest/预检查第一版

状态：完成本地和远端验证，待提交

实施内容：

- 新增 `backend/app/v2/upgrade/service.py`。
- v2 升级包上传第一版：
  - 保存上传包到 `/data/upgrades/{task_id}`。
  - 解压到 `/data/upgrades/{task_id}/package`。
  - 解析 `manifest.json`。
  - 自动识别 `components[*].type`，支持 `platform`、`runner`、`observability` 等组件类型。
  - 拦截绝对路径、`..`、`.env`、`smartx.db`、`backups`、`exports`、`compose-runtime`、`password`、`token`、`secret` 等敏感路径。
- v2 升级预检查第一版：
  - manifest 基础字段。
  - 包内路径安全。
  - 镜像 archive 是否存在。
  - 镜像 sha256 是否匹配。
  - `project_files=true` 时校验 `project/docker-compose.offline.yml`。
- v2 API 新增：
  - `POST /api/admin/upgrade/upload`
  - `POST /api/admin/upgrade/precheck/{task_id}`
- 上传和预检查结果写入统一任务中心。
- `docs/v2-rebuild-task-plan.md` 将统一 manifest、组件识别、预检查第一版标记完成。

TDD 记录：

- RED：新增 `backend/tests/test_v2_upgrade.py` 后，`app.v2.upgrade.service` 缺失。
- GREEN：新增 `UpgradeService` 后，上传解析组件、sha256/project_files 预检查、敏感路径拒绝测试通过。
- 扩展 API 测试后，升级上传/预检查接口鉴权和返回测试通过。

验证：

- 本地：
  - `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade -v` 通过。
  - v2 后端完整测试集 45 个测试通过。
  - `python3 -m py_compile backend/app/v2/api.py backend/app/v2/upgrade/service.py backend/tests/test_v2_upgrade.py` 通过。
- 远端 `10.20.11.3:/opt/smartx-storage-forecast-v2`：
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_upgrade` 通过。

限制：

- 本阶段只实现上传和预检查薄片，不执行 Docker load、项目文件同步、备份、重启、健康检查和回滚。

### 2026-06-06 Phase V2-3 采集记录 API

状态：完成本地和远端验证，待提交

实施内容：

- `CollectionService` 增加：
  - `list_runs(limit=30)`
  - `run_detail(run_id)`
- v2 API 新增：
  - `GET /api/collection/runs`
  - `GET /api/collection/runs/{run_id}`
- 手动采集路由改为复用 `get_collection_service` 依赖，便于测试和后续扩展。
- `docs/v2-rebuild-task-plan.md` 将采集状态写入 SQLite、采集记录列表和详情 API 标记完成。

TDD 记录：

- RED：新增 `backend/tests/test_v2_collection_runs_api.py` 后，未登录访问 `/api/collection/runs` 返回 404。
- GREEN：新增 CollectionService 查询方法和 API 路由后，鉴权、列表倒序、详情、404 测试通过。

验证：

- 本地：
  - `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_collection_runs_api backend.tests.test_v2_collection -v` 通过。
  - v2 后端完整测试集 46 个测试通过。
  - `python3 -m py_compile backend/app/v2/api.py backend/app/v2/collection/service.py backend/tests/test_v2_collection_runs_api.py` 通过。
- 远端 `10.20.11.3:/opt/smartx-storage-forecast-v2`：
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_collection_runs_api` 通过。

### 2026-06-06 Phase V2-6 迁移校验和导入健康检查

状态：完成本地和远端验证，待提交

实施内容：

- v2 迁移包 `manifest.json` 增加 `files` 字段。
- 每个导出的 SQLite/Prometheus 文件记录：
  - `size`
  - `sha256`
- 导入完成后返回 `health`：
  - SQLite 是否存在。
  - Prometheus 目录是否存在。
  - Prometheus block 数量和部分 block 名称。
  - `complete` 标识业务库和 Prometheus 历史指标是否完整。
- 如果迁移包只包含业务库、没有 Prometheus 历史 block，`health.complete=false` 并返回提示信息。
- `docs/v2-rebuild-task-plan.md` 将“迁移包校验信息”和“导入后 Prometheus 历史指标回归检查第一版”标记完成。

TDD 记录：

- RED：扩展 `backend/tests/test_v2_migration.py` 后，manifest 缺少 `files`，导入结果缺少 `health`。
- GREEN：新增文件 sha256/size manifest 和 `MigrationService.health_check()` 后测试通过。

验证：

- 本地：
  - `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_migration -v` 通过。
  - v2 后端完整测试集 46 个测试通过。
  - `python3 -m py_compile backend/app/v2/migration/service.py backend/tests/test_v2_migration.py` 通过。
- 远端 `10.20.11.3:/opt/smartx-storage-forecast-v2`：
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_migration` 通过。

### 2026-06-06 Phase V2-1 部署目录与健康检查写权限

状态：完成本地验证，待远端验证和提交

实施内容：

- v2 健康检查从“目录存在”升级为“目录存在且可写”。
- 对每个 required directory 写入并删除 `.smartx-healthcheck` marker，能发现 Prometheus 数据目录权限错误、只读挂载或目录被占用为不可写路径等问题。
- 新增回归测试覆盖目录存在但 marker 无法写入时 `directories=false`。
- `docs/v2-rebuild-task-plan.md` 将 v2 配置模型、版本文件、运行目录、健康检查和 pre_install 初始化标记完成。

TDD 记录：

- RED：新增 `test_health_check_reports_required_directory_writeability` 后，旧健康检查仍返回 `ok=True`，测试按预期失败。
- GREEN：新增 `_directory_ready()` 写入 marker 判断后，v2 foundation 和 deployment config 测试通过。

验证：

- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_foundation -v` 通过。
- 本地：临时安装 pytest 到 `/tmp/smartx-v2-venv` 后，`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m pytest backend/tests/test_deployment_config.py -q` 通过，15 个部署约束测试通过。
- 本地：v2 后端完整 unittest 集 47 个测试通过。
- 远端 `10.20.11.3:/opt/smartx-storage-forecast-v2`：
  - 拉取前发现远端存在旧验证留下的未提交 v2 改动，已用 `git stash push -u -m remote-pre-pull-20260606110431` 保存后快进到 `b9bc271`。
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_foundation` 通过。
  - 执行 `./pre_install.sh` 成功，目录完整；Prometheus 数据目录为 `nobody:nogroup`，对应 `65534:65534`。
  - `docker compose build web-api frontend` 通过。

### 2026-06-06 Phase V2-6 迁移导出精确进度与任务步骤

状态：完成本地验证，待远端验证和提交

实施内容：

- v2 `tasks` 表新增 `steps_json`，`TaskService` 支持创建、更新、列表返回结构化步骤。
- v2 新增迁移导出后台任务 API：
  - `POST /api/admin/migration/export/start`
  - `GET /api/admin/migration/export/status/{task_id}`
- 迁移导出任务保存 `steps`、`logs`、`processed_bytes`、`total_bytes`、下载链接和服务器留档路径。
- 迁移包文件名增加随机后缀，避免同一秒多次导出覆盖留档文件。
- 导出打包时逐文件记录“当前文件”和已处理/总字节数，解决大数据迁出时看起来卡在固定百分比的问题第一版。
- 前端任务中心类型新增 `steps`，任务菜单显示最近步骤摘要；迁移导出任务 patch 保留后端 steps。
- `docs/v2-rebuild-task-plan.md` 将迁出精确进度和统一任务步骤标记完成第一版。

TDD 记录：

- RED：TaskService 测试新增 `steps` 后，`create_task()` 不接受 `steps` 参数。
- GREEN：tasks schema 增加 `steps_json`，TaskService create/update/list 支持 steps。
- RED：v2 迁移 API 测试调用 `/api/admin/migration/export/start` 返回 404。
- GREEN：新增 start/status API 和迁移导出任务状态转换。
- RED：同秒连续导出导致下载文件被覆盖，测试发现 download content 和原始 export content 不一致。
- GREEN：迁移包文件名增加随机后缀，并避免 start 任务内部重复创建独立完成任务。
- RED：任务状态日志没有“当前文件”。
- GREEN：导出按候选文件逐项打包并更新日志、字节进度。

验证：

- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_tasks_api backend.tests.test_v2_migration -v` 通过。
- 本地：v2 后端完整 unittest 集 47 个测试通过。
- 本地：`python3 -m py_compile backend/app/v2/api.py backend/app/v2/database.py backend/app/v2/migration/service.py backend/app/v2/tasks/service.py backend/app/v2/system/health.py backend/tests/test_v2_migration.py backend/tests/test_v2_tasks_api.py` 通过。
- 本机无 `npm` 可执行文件，前端构建将在远端 Docker build 中验证。
- 远端 `10.20.11.3:/opt/smartx-storage-forecast-v2`：
  - 快进拉取到 `8300d47`。
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_tasks_api backend.tests.test_v2_migration` 通过。
  - `docker compose build web-api frontend` 通过，前端 Vite 构建成功；仅有 bundle 大小警告。

### 2026-06-06 Phase V2-10 v1 迁移包与旧 VM 卷 payload 兼容

状态：完成本地验证，待远端验证和提交

实施内容：

- v2 数据迁入兼容 v1 迁移包路径：
  - v2：`app/smartx.db`、`prometheus/`
  - v1：`smartx-data/smartx.db`、`prometheus-data/`
- v2 merge 导入时，如果 incoming SQLite 不存在 v2 `vm_volumes` 表，但存在 v1 `latest_vm_volumes.payload_json`，会抽取必要字段写入 v2 `vm_volumes`。
- 抽取字段包含卷 ID、名称、path、容量、已用容量、存储策略、副本数、thin provision、EC k/m、采集时间。
- 原始 Tower 嵌套对象、vm_disks 等大 payload 不写入 v2 结构表。
- `docs/v2-rebuild-task-plan.md` 将 v1 迁移包导入和旧 VM 卷 payload 抽取标记为第一版完成。

TDD 记录：

- RED：构造 v1 风格迁移包 `smartx-data/smartx.db`，导入后 `restored` 为空，说明 v2 未识别 v1 路径。
- GREEN：新增 v1/v2 数据目录兼容路径，新增 `_merge_v1_latest_vm_volume_payloads()`，测试通过。

验证：

- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_migration -v` 通过。
- 本地：v2 后端完整 unittest 集 48 个测试通过。
- 远端 `10.20.11.3:/opt/smartx-storage-forecast-v2`：
  - 快进拉取到 `fa4c2f3`。
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_migration` 通过。

### 2026-06-06 Phase V2-12 升级执行链第一版

状态：完成本地验证，待远端验证和提交

实施内容：

- v2 `UpgradeService.start()` 从“备份后等待 runner”升级为第一版可执行链：
  - 生成升级前备份。
  - 加载 manifest 中声明的 platform 镜像。
  - 同步 `project/` 白名单项目文件，并先备份目标项目文件到 `/data/backups/project-files-before-版本-时间/`。
  - 写入 `/data/compose-runtime/docker-compose.upgrade.yml`。
  - 通过 `docker compose -f docker-compose.offline.yml -f <override> up -d --no-deps ...` 重启 platform 服务。
  - 写入结构化 steps、logs、backup_path、project_backup_path、override_path。
- 平台升级只处理 `web-api`、`collector-worker`、`frontend`；manifest 里的 runner 镜像不会写入平台 override。
- 新增 `UpgradeCommandExecutor`，生产默认执行真实命令；测试可注入 fake executor。
- API 测试通过 `SMARTX_UPGRADE_DRY_RUN=1` 避免本地/CI 无 Docker CLI 时失败，生产不设置该变量。
- `docs/v2-rebuild-task-plan.md` 将平台三件套升级、项目文件备份同步、升级历史第一版标记完成；真正由 upgrade-runner 接管仍保留待办。

TDD 记录：

- RED：升级测试导入 `UpgradeCommandExecutor` 失败。
- GREEN：新增 executor 抽象，start 执行 Docker load、项目同步、override 写入和 compose up。
- 回归：API 测试本地无 Docker CLI 失败，增加显式 dry-run 环境变量用于测试环境。

验证：

- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade -v` 通过。
- 本地：v2 后端完整 unittest 集 48 个测试通过。
- 远端 `10.20.11.3:/opt/smartx-storage-forecast-v2`：
  - 快进拉取到 `a671e6c`。
  - 使用 `SMARTX_UPGRADE_DRY_RUN=1` 执行 `backend.tests.test_v2_upgrade` 通过。
  - `docker compose build web-api frontend` 通过。

### 2026-06-06 Phase V2-12 upgrade-runner 接管第一版

状态：完成本地验证，待远端验证和提交

实施内容：

- 新增 `app.v2.upgrade.runner`：
  - `run_pending_once(settings, tasks, executor, project_path)` 扫描 `/data/upgrades/*/task.json`。
  - 遇到 `status=pending` 且 `runner_requested=true` 的升级任务，调用 v2 `UpgradeService.execute_task()` 执行。
  - `main()` 循环每 3 秒扫描一次，支持 SIGTERM/SIGINT 退出。
- `UpgradeService.start(task_id, submit_to_runner=True)` 支持只提交任务给 runner，不在 web-api 内执行 Docker 操作。
- compose 和 `backend/Dockerfile.upgrade` 的 runner 入口统一改为 `python -m app.v2.upgrade.runner`。
- 部署测试新增校验，防止 runner 入口回退到旧 `app.upgrade.runner`。
- `docs/v2-rebuild-task-plan.md` 将“升级任务由 upgrade-runner 执行”标记为第一版完成。

TDD 记录：

- RED：新增 runner 接管测试后，`app.v2.upgrade.runner` 模块不存在。
- GREEN：新增 runner 模块、start 提交模式和 execute_task 复用执行链。
- 回归：compose/Dockerfile 仍指向旧 runner，更新入口并补部署测试。

验证：

- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade -v` 通过。
- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m pytest backend/tests/test_deployment_config.py -q` 通过，16 个测试通过。
- 本地：v2 后端完整 unittest 集 49 个测试通过。

### 2026-06-06 Phase V2-15 upgrade-runner 依赖瘦身

状态：完成本地验证，待远端验证和提交

实施内容：

- `backend/requirements-upgrade.txt` 不再安装 FastAPI/Pydantic/python-multipart 等 web-api 依赖，runner 镜像构建不再因为 PyPI 拉取 FastAPI 失败而中断。
- `app.v2.upgrade.service` 对 FastAPI 依赖使用兼容 shim：web-api 环境仍使用 FastAPI `HTTPException`/`UploadFile`，runner 环境无 FastAPI 时仍可 import 并执行任务。
- 部署测试新增 runner 依赖约束，防止后续重新把 web-api 依赖塞回 runner 镜像。

TDD 记录：

- RED：新增部署测试后，`requirements-upgrade.txt` 包含 `fastapi` 导致失败。
- GREEN：移除 runner 第三方依赖，并让 upgrade service 不硬依赖 FastAPI。

验证：

- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m pytest backend/tests/test_deployment_config.py -q` 通过，17 个测试通过。
- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade -v` 通过。
- 本地：v2 后端完整 unittest 集 49 个测试通过。

远端验证补充：

- 远端 `10.20.11.3:/opt/smartx-storage-forecast-v2`：
  - 快进拉取到 `c16c078`。
  - `docker compose build upgrade-runner` 通过。
  - 验证此前失败的 runner pip 安装问题已解除；空 `requirements-upgrade.txt` 可正常构建镜像。

### 2026-06-06 Phase V2-12 Prometheus observability 组件升级第一版

状态：完成本地与远端验证

实施内容：

- v2 升级 manifest 支持 `type=observability` 的 Prometheus 组件。
- 平台升级、observability 升级的镜像和服务集合拆分计算：
  - platform 只处理 `web-api`、`collector-worker`、`frontend`。
  - observability 只处理 `prometheus`。
- Prometheus 组件预检查增加数据目录写入检查，并统计历史 block 数量。
- Prometheus 组件升级只写入 `prometheus` 镜像 override，只重启 Prometheus，不误重启平台三件套。
- `docs/v2-rebuild-task-plan.md` 将 Prometheus 组件升级第一版和 Prometheus 权限预检查第一版标记完成。

TDD 记录：

- RED：新增 `test_observability_upgrade_only_restarts_prometheus_and_checks_permissions` 后，升级服务不会识别 observability 组件，也不会检查 Prometheus 数据目录权限。
- GREEN：新增 observability 镜像/服务解析、Prometheus 权限预检查、统一 upgrade override 写入和按 manifest 服务重启。

验证：

- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade -v` 通过，5 个测试通过。
- 本地：v2 后端完整 unittest 集 50 个测试通过。
- 本地：`python3 -m py_compile backend/app/v2/upgrade/service.py backend/tests/test_v2_upgrade.py` 通过。
- 远端 `10.20.11.3:/opt/smartx-storage-forecast-v2`：
  - 快进拉取到 `24a8ea8`。
  - `docker run --rm -v /opt/smartx-storage-forecast-v2:/src -e PYTHONPATH=/src/backend -e SMARTX_UPGRADE_DRY_RUN=1 -w /src smartx-storage-forecast-web-api:local python -m unittest backend.tests.test_v2_upgrade -v` 通过，5 个测试通过。
  - `docker compose build web-api frontend upgrade-runner` 通过。

### 2026-06-06 Phase V2-12 runner 组件升级第一版

状态：完成本地验证，待远端验证和提交

实施内容：

- v2 升级执行链支持纯 `runner` 组件包。
- runner 组件升级只加载 `upgrade-runner` 镜像，只重启 `upgrade-runner`。
- runner 组件升级运行时 override 写入 `/data/compose-runtime/docker-compose.runner-upgrade.yml`，不再写项目目录或只读 `/opt`。
- 平台升级和 Prometheus 升级继续使用 `/data/compose-runtime/docker-compose.upgrade.yml`，runner 组件升级独立隔离。
- runner 自升级采用两阶段恢复：重启自身前写入 `runner_restarting` 和 `runner_resume_pending`，新 runner 启动后扫描该状态并完成健康检查收尾，避免任务卡死在执行中。
- `docs/v2-rebuild-task-plan.md` 将 runner 组件升级第一版和 runner 自升级不中断链第一版标记完成。

TDD 记录：

- RED：新增 `test_runner_component_upgrade_writes_runtime_override_and_only_restarts_runner` 后，服务不会生成 `docker-compose.runner-upgrade.yml`，测试因文件不存在失败；补充 runner 重启中断模拟后，`SystemExit` 直接冒出导致任务无法恢复。
- GREEN：新增 runner 镜像/服务解析、runner-only 判断、runner 专用 override 写入，以及 `runner_restarting` 状态的恢复收尾逻辑。

验证：

- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade.V2UpgradeServiceTest.test_runner_component_upgrade_writes_runtime_override_and_only_restarts_runner -v` 通过。
- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade -v` 通过，6 个测试通过。
- 本地：v2 后端完整 unittest 集 51 个测试通过。
- 本地：`python3 -m py_compile backend/app/v2/upgrade/service.py backend/tests/test_v2_upgrade.py` 通过。

### 2026-06-06 Phase V2-12 升级 API 与回滚闭环第一版

状态：完成本地验证，待远端验证和提交

实施内容：

- 后端补齐前端服务管理页已调用的 v2 升级接口：
  - `/api/admin/upgrade/status/{task_id}`
  - `/api/admin/upgrade/history`
  - `/api/admin/upgrade/package/{task_id}`
  - `/api/admin/upgrade/version`
  - `/api/admin/upgrade/verification`
  - `/api/admin/component-upgrade/*` 上传、预检查、开始、状态、历史、删除和版本别名。
- 升级 service 返回前端公共状态：`succeeded`、`running`、`prechecked` 等，同时 task 文件内部仍保留执行状态。
- 回滚第一版支持恢复项目文件备份、移除运行时 override、重启 manifest 声明服务，并写入 rollback steps/logs。
- `docs/v2-rebuild-task-plan.md` 将回滚和历史记录第一版标记完成。

TDD 记录：

- RED：API 测试新增 status/history/version/verification/component alias 后，`/api/admin/upgrade/status/{task_id}` 返回 404。
- GREEN：补齐 UpgradeService 公共任务响应和 API 路由别名。
- RED：回滚测试调用 `service.rollback()` 失败，因为方法不存在。
- GREEN：实现项目文件恢复、override 删除、服务重启和 rollback 状态写入。

验证：

- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade.V2UpgradeApiTest.test_upgrade_api_requires_auth_uploads_and_prechecks_package -v` 通过。
- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade.V2UpgradeServiceTest.test_rollback_restores_project_files_and_removes_runtime_override -v` 通过。
- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade -v` 通过，7 个测试通过。
- 本地：v2 后端完整 unittest 集 52 个测试通过。
- 本地：`python3 -m py_compile backend/app/v2/api.py backend/app/v2/upgrade/service.py backend/app/v2/upgrade/runner.py backend/tests/test_v2_upgrade.py` 通过。

### 2026-06-06 Phase V2-8 服务重启与旧镜像清理接口第一版

状态：完成本地验证，待远端验证和提交

实施内容：

- 新增 v2 系统控制服务 `app.v2.system.control`。
- 后端新增 `/api/admin/system/restart`，按 v2 设计提交重启 `web-api`、`collector-worker`、`prometheus`。
- 后端补齐前端服务管理页已调用的 Docker 镜像接口：
  - `/api/admin/system/cleanup-images/scan`
  - `/api/admin/system/cleanup-images`
- 旧镜像清理支持先扫描再清理，返回镜像列表、每个镜像大小、预计可释放空间、实际释放空间和日志。
- 测试和 API 支持 `SMARTX_UPGRADE_DRY_RUN=1`，避免本地/CI 没有 Docker CLI 时误清理真实镜像。
- `docs/v2-rebuild-task-plan.md` 将服务重启第一版和未使用 Docker 镜像扫描清理第一版标记完成。

TDD 记录：

- RED：新增镜像清理 service 测试后，`CleanupService` 不支持 executor，也没有 `scan_unused_images()`。
- GREEN：新增 Docker image 扫描/inspect/rm 执行链，兼容 Docker 按行 JSON 和测试 JSON 数组输出。
- RED：API 测试要求 cleanup-images 和 restart 接口后，`/api/admin/system/cleanup-images/scan` 返回 404。
- GREEN：新增系统控制服务和三个后端 API 路由。

验证：

- 本地：`PYTHONPATH=backend SMARTX_UPGRADE_DRY_RUN=1 /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_cleanup -v` 通过，3 个测试通过。
- 本地：v2 后端完整 unittest 集 53 个测试通过。
- 本地：`python3 -m py_compile backend/app/v2/api.py backend/app/v2/cleanup/service.py backend/app/v2/system/control.py backend/tests/test_v2_cleanup.py` 通过。

### 2026-06-06 Phase V2-9 升级包与组件包 v2 manifest 闭环

状态：完成本地验证，待远端验证和提交

实施内容：

- 平台升级包脚本改为输出 v2 manifest：
  - `schema_version: "2"`
  - `package_id`
  - `components[0].type = platform`
  - `components[0].images[].archive`
  - `project_files: true`
  - `project_file_list` 白名单明细
  - `migration.script = scripts/migrate.sh`
  - `compatibility.min_platform_version`
- runner 组件包脚本改为输出 v2 manifest：
  - `schema_version: "2"`
  - `components[0].type = runner`
  - `project_files: false`
  - `compatibility.min_runner_version`
- 平台包继续不包含 `upgrade-runner.tar`，runner 包继续只包含 `upgrade-runner`。
- migrate 脚本从 `project_file_list` 读取白名单，并从 `components[].images[]` 写平台服务 override。
- `docs/v2-rebuild-task-plan.md` 将 Phase V2-9 “升级包和组件包打包第一版”标记完成。

TDD 记录：

- RED：新增 `backend/tests/test_v2_package_builders.py` 后，两个包构建器测试因 manifest 缺少 `schema_version` 失败。
- GREEN：调整两个打包脚本输出 v2 manifest，并更新旧部署配置断言。

验证：

- 本地：`PYTHONPATH=backend SMARTX_UPGRADE_DRY_RUN=1 /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_package_builders -v` 通过，2 个测试通过。
- 本地：`/tmp/smartx-v2-venv/bin/python -m pytest backend/tests/test_deployment_config.py backend/tests/test_v2_package_builders.py -q` 通过，19 个测试通过。
- 本地：`PYTHONPATH=backend SMARTX_UPGRADE_DRY_RUN=1 /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade -v` 通过，7 个测试通过。
- 本地：`python3 -m py_compile scripts/build_upgrade_package.py scripts/build_runner_component_package.py` 通过。

### 2026-06-06 Phase V2-14 顶部菜单点击空白处收起验证

状态：完成远端验证，待提交

实施内容：

- 新增 `frontend/src/components/AppLayout.test.tsx`，覆盖：
  - 账号头像菜单打开后点击内容区会自动收起。
  - 任务菜单打开后点击内容区会自动收起。
- 当前 `AppLayout` 已有 `pointerdown` 外部点击关闭逻辑，本次只补自动化测试和任务文档勾选。
- `docs/v2-rebuild-task-plan.md` 将“点击空白处可收起任务菜单”和“下拉菜单点击空白处自动收起”标记完成。

验证：

- 远端 `10.20.11.3`：`npm test -- AppLayout.test.tsx` 通过，1 个测试文件、2 个测试通过。

### 2026-06-06 Phase V2-11 失败任务展示验证

状态：完成远端验证，待提交

实施内容：

- 扩展 `frontend/src/components/AppLayout.test.tsx`，覆盖失败任务在任务中心中展示：
  - 失败任务标题和错误摘要。
  - 失败步骤，如 `失败 校验镜像`。
  - 错误日志摘要，如镜像 sha256 不匹配。
- 当前 `AppLayout` 已渲染 `task.detail`、`task.steps` 和 `task.logs`，本次补测试和文档勾选。
- `docs/v2-rebuild-task-plan.md` 将“失败任务展示失败步骤和错误摘要”标记完成。

验证：

- 远端 `10.20.11.3`：`npm test -- AppLayout.test.tsx` 通过，1 个测试文件、3 个测试通过。

### 2026-06-06 Phase V2-6 overwrite 导入显式确认验证

状态：完成本地和远端验证，待提交

实施内容：

- 后端 API 测试补充 `mode=overwrite` 且 `confirmed=false` 时返回 `400`，错误明确提示覆盖导入会清空当前系统数据。
- 前端 `ServicePage` 测试覆盖：
  - 选择覆盖导入后，未勾选确认时“导入迁移包”按钮禁用。
  - 勾选“我确认覆盖当前系统数据”后才调用 `api.importMigration(file, "overwrite", true, ...)`。
- 修复 `ServicePage` 滚动重置在不支持 `HTMLElement.scrollTo` 的环境中抛错的问题，回退到设置 `scrollTop = 0`。
- 测试环境 `frontend/src/test/setup.ts` 增加 `window.scrollTo` stub。
- `docs/v2-rebuild-task-plan.md` 将 “overwrite 模式必须显式选择” 标记完成。

验证：

- 本地：`PYTHONPATH=backend SMARTX_UPGRADE_DRY_RUN=1 /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_migration -v` 通过，4 个测试通过。
- 远端 `10.20.11.3`：`npm test -- ServicePage.test.tsx` 通过，1 个测试文件、4 个测试通过。

### 2026-06-06 Phase V2-7 升级中心预检查与平台状态验证

状态：完成远端验证，待提交

实施内容：

- 扩展 `frontend/src/pages/ServicePage.test.tsx`，覆盖平台升级页：
  - “平台状态”区域集中展示当前版本、目标版本、升级中心版本、Compose 项目、最近成功包、SHA256 和服务运行表。
  - 页面不再出现单独的“服务运行核验”二级区块。
  - 点击“预检查”后立即显示步骤化进度，包括执行中和未执行状态。
- 当前 `ServicePage` 已具备平台状态合并和预检查步骤化 UI，本次补自动化测试和任务文档勾选。
- `docs/v2-rebuild-task-plan.md` 将“预检查显示步骤化进度”和“页面合并平台状态和升级后核验”标记完成。

验证：

- 远端 `10.20.11.3`：`npm test -- ServicePage.test.tsx` 通过，1 个测试文件、6 个测试通过。

### 2026-06-06 Phase V2-8 服务管理页面结构验证

状态：完成远端验证，待提交

实施内容：

- 扩展 `frontend/src/components/AppLayout.test.tsx`，覆盖“服务管理”作为主导航项位于“设置”后，并点击后触发 `onNavigate("service")`。
- 扩展 `frontend/src/pages/ServicePage.test.tsx`，覆盖服务管理二级菜单包含：
  - 数据迁移
  - 服务重启
  - 空间清理
  - 平台升级
  - 组件升级
  - 升级历史
- 新增 `frontend/src/pages/SettingsPage.test.tsx`，确认设置页只保留 Tower 配置，不出现服务管理、系统升级、数据迁移内容。
- 修复 `AppLayout` 滚动重置在不支持 `HTMLElement.scrollTo` 的环境中抛错的问题，回退到设置 `scrollTop = 0`。
- `docs/v2-rebuild-task-plan.md` 将服务管理独立页、二级菜单、设置页清理和对应前端 UI 项标记完成。

验证：

- 远端 `10.20.11.3`：`npm test -- AppLayout.test.tsx ServicePage.test.tsx SettingsPage.test.tsx` 通过，3 个测试文件、12 个测试通过。

### 2026-06-06 Phase V2-8 空间清理按钮色彩验证

状态：完成远端红绿验证，待提交

实施内容：

- 扩展 `frontend/src/pages/ServicePage.test.tsx`，覆盖“空间清理”页：
  - “扫描”按钮使用 `primary-button service-header-button`。
  - “一键清理”按钮使用 `danger-button service-header-button`。
- 修复 `frontend/src/pages/ServicePage.tsx` 中空间清理扫描按钮仍使用次级按钮的问题，改为主色按钮。
- `docs/v2-rebuild-task-plan.md` 将“清理按钮使用危险色，扫描按钮使用主色”标记完成。

TDD 记录：

- RED：远端 `10.20.11.3` 执行 `npm test -- ServicePage.test.tsx`，新增测试失败，收到 `secondary-button service-header-button`，符合预期。
- GREEN：改为 `primary-button service-header-button` 后，远端同一测试通过，1 个测试文件、8 个测试通过。

### 2026-06-06 Phase V2 文档状态治理

状态：完成远端验证，待提交

实施内容：

- 按现有 v2 源码和测试覆盖，对 `docs/v2-rebuild-task-plan.md` 中已完成但未勾选的任务做状态对齐。
- 本次只标记已有测试证据的第一版能力：
  - 认证、登录、token、`/api/me`、改密、管理接口鉴权。
  - Tower CRUD、连接测试、集群同步、集群启用和 scope 参数。
  - CloudTower 客户端、采集入口、定时采集、启用集群过滤、指标写入、VM 最新名称和卷数据。
  - Prometheus 指标 label、查询服务、趋势身份过滤、健康检查。
  - v2 schema、结构化 VM 卷、任务状态、导出留档、升级历史第一版。
  - 报表 90 天预测、7 天平均、图表窗口、30 天样本过滤、新建 VM、导出留存和任务链接第一版。
  - v1 信息架构、统一布局、Dashboard/VM/报表页面第一版。
- 未标记仍缺实现或缺专门验证的项，例如 Word 目录、Word 页脚、部署发版现场验证。

验证计划：

- 远端 `10.20.11.3`：使用 `smartx-storage-forecast-web-api:local` 容器运行 15 个 v2 后端测试模块，40 个测试通过。
- 远端 `10.20.11.3`：使用 `node:22-alpine` 运行核心前端测试 `AppLayout/Dashboard/Vms/Reports/Service/Settings`，6 个测试文件、18 个测试通过。
- 注意：第一次前端测试发现远端存在 macOS 资源叉垃圾文件 `frontend/src/pages/._ReportsPage.test.tsx` 导致 Vitest 误读；已删除 `frontend/src/**/._*` 后重跑通过。

### 2026-06-06 Phase V2-5 报表 Word 目录页脚与高风险底纹

状态：完成远端红绿验证，待提交

实施内容：

- 扩展 `backend/tests/test_v2_report_exports.py`，验证：
  - Word 文档包含“目录”以及每个集群名称。
  - Word 页脚包含 Tower、集群和生成时间。
  - Word 高风险 VM 行写入红色底纹 `F4CCCC`。
  - Excel 高风险 VM 样式仍包含 `F4CCCC`。
- 修改 `backend/app/v2/reports/export.py`：
  - 首页信息表后新增集群目录段。
  - Word 页脚输出 `Tower - 集群 - 生成时间`。
  - Word VM 表格对增长率超过 20% 且增长量大于 100G 的 VM 行设置红色底纹。
- `docs/v2-rebuild-task-plan.md` 将 Word 目录、Word 页脚、高风险 VM 底纹标红标记完成。

TDD 记录：

- RED：远端 `10.20.11.3` 运行 `python -m unittest backend.tests.test_v2_report_exports -v`，失败于 Word XML 不包含“目录”，符合预期。
- GREEN：实现目录、页脚和 Word 底纹后，远端同一测试通过。

### 2026-06-06 Phase V2-9 部署发版状态治理

状态：完成远端验证，待提交

实施内容：

- 根据 `backend/tests/test_deployment_config.py` 和 `backend/tests/test_v2_package_builders.py` 的验证结果，更新 `docs/v2-rebuild-task-plan.md`：
  - 平台镜像使用平台版本 tag。
  - runner 镜像使用 runner 版本 tag。
  - 平台 GitHub Actions 与 runner GitHub Actions 分离。
  - offline/release compose 使用明确版本，且不包含 build。
  - 平台升级包不包含 `.env`、数据库、Prometheus 数据、凭据，也不包含 runner 镜像。
  - 打包脚本自动校验版本一致性。
  - README 已写明升级包目录结构，changelog 第一版已存在。

验证：

- 远端 `10.20.11.3`：容器内临时安装 `backend/requirements-dev.txt` 后执行 `python -m pytest backend/tests/test_deployment_config.py backend/tests/test_v2_package_builders.py -q`，19 个测试通过。

### 2026-06-06 Phase V2 测试计划状态治理

状态：完成远端验证，待提交

实施内容：

- 根据已通过的自动化测试结果，对 `docs/v2-rebuild-task-plan.md` 的阶段项和测试计划项做状态对齐。
- 标记完成的范围仅限已有自动化测试覆盖的第一版能力：
  - v1 数据兼容迁入、导入后健康验证、平台升级、项目文件同步。
  - 数据迁移页面、服务重启、compose/Dockerfile、GitHub Actions、pre_install。
  - 后端测试计划中的认证、Tower、采集、Prometheus、Dashboard、VM 改名、月增长过滤、报表、迁入备份、v1 兼容、升级预检查、空间清理。
  - 前端测试计划中的登录/token 过期第一版、scope 切换第一版、Dashboard 风险、新建 VM 卡片、VM 跳转、报表/迁移/升级/清理任务。
- 保留现场端到端项未完成，包括新部署采集、真实 v1 迁入后趋势回归、平台/runner/Prometheus 真实升级包执行。

验证依据：

- 远端 v2 后端 40 个 unittest 通过。
- 远端核心前端 18 个 Vitest 通过。
- 远端部署配置和打包脚本 19 个 pytest 通过。

### 2026-06-06 Phase V2 前端布局与滚动条回归

状态：完成远端验证，待提交

实施内容：

- 新增 `frontend/src/components/AppLayout.test.tsx` 用例，验证 `.workspace.auto-scrollbar` 默认隐藏滚动条、滚动时添加 `is-scrolling`、900ms 后自动移除。
- 新增 `frontend/src/pages/DashboardPage.test.tsx` 用例，验证首页容量风险、Tower、集群是 `dashboard-metrics-row` 下三个独立指标卡，不互相嵌套。
- 新增 `frontend/src/styles/global.test.ts`，验证关键响应式 CSS：
  - 桌面 Dashboard 指标行保持容量风险小列、Tower/集群中列的受控列宽。
  - 960px 移动端 Dashboard/metrics 切单列，workspace 不遮挡滚动。
  - 服务管理二级导航在移动端横向换行，service-focus 主内容移动端左右边距收缩。
- `docs/v2-rebuild-task-plan.md` 标记 Dashboard 独立卡片、移动端第一版布局、隐藏滚动条三项完成。

验证：

- 远端 `10.20.11.3`：`npm test -- AppLayout.test.tsx DashboardPage.test.tsx`，2 个测试文件、9 个测试通过。
- 远端 `10.20.11.3`：`npm test -- global.test.ts`，1 个测试文件、3 个测试通过。

### 2026-06-06 Phase V2 远端现场验证与旧库兼容修复

状态：完成本轮修复和远端 smoke，待继续升级/迁移端到端验证

发现的问题：

- `10.20.11.3` 的 v2 工作目录已在 `feature/upgrade-v2`，但运行容器最初仍是旧入口：`uvicorn app.main:app`、`python -m app.collector...`。
- v2 镜像启动后，默认数据路径指向 `/data/smartx-capacity-insight-data/app/smartx.db`；当前 compose 将业务库目录挂载到容器 `/data`，真实业务库是 `/data/smartx.db`，导致 API 读到空库。
- 旧库中已有 `latest_vm_volumes` 和 `latest_vm_volume_items`，但 v2 新表 `vm_latest`、`vm_volumes` 初始为空，切到 v2 后 VM 页面和 Dashboard 容易空。
- Prometheus 当前 instant 查询为空时，`/api/vms` 只依赖 Prometheus 会返回 0 台 VM；但 SQLite 中有最新 VM 和卷数据，趋势 query_range 仍可查到历史点。
- 远端当前 compose 实际 project name 是 `smartx-storage-forecast`；使用不匹配的 project name 执行 `docker compose ps` 会显示空表。
- 现场库里存在历史导入残留的 tower_id 1/2/3 数据，而当前启用 Tower/集群只有 tower_id 3；默认 Dashboard、VM、报表必须按当前启用集群过滤，否则会显示旧残留 VM 和没有趋势的历史记录。

实施内容：

- `backend/app/v2/config.py` 支持 `SMARTX_DB_PATH` 和 `SMARTX_PROMETHEUS_DATA_PATH` 覆盖，compose 明确传入 `/data/smartx.db` 与 `/prometheus-data`。
- `docker-compose.yml`、`docker-compose.offline.yml`、`docker-compose.release.yml` 同步补齐 v2 数据路径环境变量。
- `backend/app/v2/database.py` 初始化时兼容旧 `latest_vm_volumes`，自动 backfill 到 `vm_latest` 和 `vm_volumes`。
- `backend/app/v2/api.py` 的 VM 趋势接口兼容前端使用的 `period_days` 参数。
- `backend/app/v2/dashboard/service.py` 返回 Tower 树，支持前端 scope 选择；Prometheus instant 为空时从 SQLite `vm_latest` 兜底 VM 概览，且不会把兜底数据误算为“本日新建 VM”。
- `backend/app/v2/vms/service.py` 在 Prometheus instant 为空时从 SQLite `vm_latest` 返回 VM 列表。
- `backend/app/v2/dashboard/service.py`、`backend/app/v2/vms/service.py`、`backend/app/v2/reports/service.py` 默认只统计当前启用集群下的数据；选择 Tower/集群时使用对应启用范围过滤。

验证：

- 远端 `10.20.11.3` 执行 `./pre_install.sh`，目录和 Prometheus 权限检查通过。
- 远端重建并启动 v2 compose 后，容器入口确认：`uvicorn app.v2.main:app`、`python -m app.v2.worker`、`python -m app.v2.upgrade.runner`。
- 远端受影响后端测试：`test_v2_foundation`、`test_v2_dashboard_vm`、`test_v2_dashboard_vm_api`、`test_v2_migration` 共 18 个测试通过。
- 远端完整 v2 后端测试曾扩展至 43 个测试并通过。
- 远端 smoke：登录成功；Dashboard 读取到 1 个 Tower、1 个集群；启用范围过滤修复后 Dashboard VM 数和 `/api/vms` 均为 177 台；Word/Excel 报表保存到 `/data/exports/reports`；迁移导出任务成功并返回下载 URL；空间清理扫描返回可清理项；compose 五个容器均运行。
- 远端运行容器内复核：`backend.tests.test_v2_foundation`、`backend.tests.test_v2_dashboard_vm`、`backend.tests.test_v2_dashboard_vm_api`、`backend.tests.test_v2_migration` 共 18 个测试通过。
- 远端运行容器内复核：新增 orphan 指标/SQLite 残留过滤测试后，`backend.tests.test_v2_dashboard_vm`、`backend.tests.test_v2_reports` 共 6 个测试通过。

仍未完成：

- 真实“新增 Tower 并采集”未在本轮执行，避免覆盖现场已有 Tower 凭据和数据。
- 平台升级包、runner 组件包、Prometheus 组件包未实际执行。
- 迁出数据导入独立验证环境未执行。
- 日/月增长是否非空仍取决于 Prometheus 历史样本窗口和当前 scrape 状态，本轮只验证趋势、VM 列表、报表和迁移导出恢复。

### 2026-06-06 Phase V2 v0.5.0 / runner v0.3.0 版本治理与远端验证

状态：完成本轮版本治理、远端构建、运行 smoke 和升级包生成，待继续真实升级包执行

实施内容：

- 平台版本统一为 `v0.5.0`，根目录 `VERSION`、compose 默认平台 tag、README、部署文档、版本治理文档和测试断言同步更新。
- `upgrade-runner` 组件版本统一为 `v0.3.0`，根目录 `RUNNER_VERSION`、compose `SMARTX_RUNNER_IMAGE_TAG`、runner 组件包脚本和测试断言同步更新。
- 明确 `v0.5.0` 平台升级包只面向 v2 同架构后续升级；v1/v0.4.x 不走原地升级，只通过“新装 v2 + 数据迁移包导入”兼容。
- README 中升级包结构更新为 v2 manifest：`schema_version=2`、`components`、`project_files`、`scripts/migrate.sh`、`project/**`。
- 三个后端 Dockerfile 增加 `PIP_DEFAULT_TIMEOUT=120` 和 `PIP_RETRIES=10`，缓解现场 pip 下载超时导致构建失败。
- 远端 `10.20.11.3` 已删除旧平台、runner 和 Prometheus 容器/镜像后重新构建 v2。

远端验证：

- `python3 scripts/build_upgrade_package.py --check-version --no-build` 通过，输出 `Version metadata OK: v0.5.0`。
- `docker compose build web-api collector-worker frontend upgrade-runner` 通过。
- 镜像内版本检查：`web-api` 与 `upgrade-runner` 均显示 `/app/VERSION=v0.5.0`、`/app/RUNNER_VERSION=v0.3.0`。
- 容器内测试通过：`backend.tests.test_deployment_config`、`backend.tests.test_v2_package_builders`、`backend.tests.test_v2_upgrade` 共 9 个测试通过。
- 容器内测试通过：`backend.tests.test_v2_dashboard_vm`、`backend.tests.test_v2_reports`、`backend.tests.test_v2_migration` 共 10 个测试通过。
- `bash pre_install.sh` 通过，确认 `/data/upgrades`、`/data/backups`、`/data/exports`、`/data/compose-runtime` 和 Prometheus 权限准备完成。
- `docker compose --project-name smartx-storage-forecast up -d` 启动五个容器成功。
- HTTP 验证通过：`/api/system/health` 返回 `version=v0.5.0`、`runner_version=v0.3.0`；`/api/admin/upgrade/version` 返回 `v0.5.0`；`/api/admin/component-upgrade/version` 返回 `v0.3.0`；前端 `8080` 返回 200；Prometheus `/-/healthy` 正常。
- 登录后接口验证通过：Dashboard、报表接口均返回数据；Dashboard 风险文案为 `当前所有集群暂无明显容量风险`。

升级包：

- 平台升级包：`/data/upgrade-packages/smartx-capacity-insight-upgrade-v0.5.0.tar.gz`，大小约 342 MB，SHA256 `6924766cb52a67b9562c2894300ec7eddd09d397b37ec79203c84c2b3e83a53b`。
- runner 组件包：`/data/upgrade-packages/components/smartx-upgrade-runner-v0.3.0.tar.gz`，大小约 81 MB，SHA256 `6c44e1d09a15573e06d15f247ea7ef438a6cf8a24d48e54cf5925dba7b57a748`。
- 平台包 manifest：`version=v0.5.0`、`min_version=v0.5.0`、`package_type=platform`、只包含 `web-api`、`collector-worker`、`frontend`，不包含 `images/upgrade-runner.tar`。
- runner 包 manifest：`version=v0.3.0`、`package_type=component`、只包含 `images/upgrade-runner.tar`。
- 两个包检查均未发现 `.env`、`smartx.db`、Prometheus 数据或凭据类内容。

注意：

- 使用 `docker compose run` 时必须显式 `--project-name smartx-storage-forecast`，否则目录名 `smartx-storage-forecast-v2` 会尝试创建同样 `10.249.249.0/24` 的网络并与正式网络冲突。
- 本轮没有执行真实平台升级包、runner 组件包和 Prometheus 组件包升级流程；这些仍保留为后续端到端验证项。

### 2026-06-06 Phase V2-7 真实平台升级与 runner 组件升级验证

状态：完成平台升级包和 runner 组件包真实执行验证，修复 runner-only 组件升级执行者问题

现场验证：

- 在 `10.20.11.3` 通过 API 上传并执行 `/data/upgrade-packages/smartx-capacity-insight-upgrade-v0.5.0.tar.gz`。
- 平台升级任务 `upgrade-9c1b8ce0fb6f7b47` 成功：
  - 生成升级前备份 `/data/backups/upgrade-v0.5.0-before-20260606085950.tar.gz`。
  - 加载 `web-api`、`collector-worker`、`frontend` 三个 `v0.5.0` 镜像。
  - 同步项目文件并备份到 `/data/backups/project-files-before-v0.5.0-20260606090010`。
  - 写入 `/data/compose-runtime/docker-compose.upgrade.yml`。
  - 平台三件套重启后容器均运行，`/api/system/health` 返回 `version=v0.5.0`、`runner_version=v0.3.0`。
- 首次真实执行 runner 组件包 `/data/upgrade-packages/components/smartx-upgrade-runner-v0.3.0.tar.gz` 时发现现场问题：
  - 任务 `upgrade-aa714bd774e894a3` 完成备份、加载镜像和写 runner override 后停在 `restart running`。
  - Docker 状态显示旧 runner 退出，新 runner 容器一度只处于 Created，说明 runner 自己执行 `docker compose up -d --no-deps upgrade-runner` 会被自身重启打断。

修复内容：

- 新增 API 回归测试：runner-only 组件升级通过 `/api/admin/component-upgrade/start/{task_id}` 启动后不再返回 `pending + runner_requested`，而是由 web-api 直接执行。
- RED：远端容器内执行 `backend.tests.test_v2_upgrade.V2UpgradeApiTest.test_upgrade_api_requires_auth_uploads_and_prechecks_package`，新断言失败，实际返回 `pending`。
- GREEN：`backend/app/v2/api.py` 将组件升级 start 改为 `upgrade.start(..., submit_to_runner=False)`。
- 清理成功路径：`backend/app/v2/upgrade/service.py` 在任务成功时清空 `runner_resume_pending=False`，并将日志文案改为“升级服务已提交重启”。

修复后验证：

- 远端容器内同一 API 回归测试通过。
- 重建并重启远端 `web-api` 后，再次通过 API 执行 runner 组件包，任务 `upgrade-99f319a07635fcb1` 成功：
  - 生成备份 `/data/backups/upgrade-v0.3.0-before-20260606091212.tar.gz`。
  - 加载 `nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.0`。
  - 写入 `/data/compose-runtime/docker-compose.runner-upgrade.yml`。
  - runner 容器成功切换为 `nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.0` 并运行。

仍未完成：

- Prometheus 组件包真实执行和历史指标回归仍未跑。
- 新部署添加 Tower 并采集、v1 迁移包导入独立验证环境仍未跑。

补充验证产物：

- 修复后重新生成平台升级包：`/data/upgrade-packages/smartx-capacity-insight-upgrade-v0.5.0.tar.gz`，大小 `342339041` bytes，SHA256 `0958b9aa592ef528aabd489d1e979104d3878e1a0978a467d1a6735c96f195c5`。
- 修复后重新生成 runner 组件包：`/data/upgrade-packages/components/smartx-upgrade-runner-v0.3.0.tar.gz`，大小 `81373272` bytes，SHA256 `6567f7ec135b550e690ecc41bb468e45e798d37fdcb80f38b589532d5fb4c023`。
- 平台包 manifest 仍为 `version=v0.5.0`、components `platform`，不包含 `images/upgrade-runner.tar`。
- runner 组件包 manifest 仍为 `version=v0.3.0`、components `runner`，只包含 `images/upgrade-runner.tar`。
- 包内检查未发现 `.env`、`smartx.db`、Prometheus 历史数据或凭据；`project/prometheus/prometheus.yml` 是 Prometheus 配置文件，属于预期项目文件。

### 2026-06-06 Phase V2 前端版本断言与远端测试清理

状态：完成

发现与修复：

- 远端用 Docker `node:22-alpine` 跑 Vitest 时，`frontend/src` 内残留 macOS `._*` AppleDouble 文件导致 Vite 尝试解析二进制文件失败。
- `frontend/src/pages/ServicePage.test.tsx` 中平台状态测试仍断言旧包名 `smartx-capacity-insight-upgrade-v0.4.1`，已修正为 `v0.5.0`。

验证：

- 删除远端 `frontend/src/**/._*` 运行产物后，执行 `docker run --rm -v /opt/smartx-storage-forecast-v2/frontend:/app -w /app node:22-alpine npm test -- AppLayout.test.tsx DashboardPage.test.tsx global.test.ts ServicePage.test.tsx` 通过。
- 前端结果：4 个测试文件、20 个测试通过。

### 2026-06-06 Phase V2 Prometheus observability 组件包与真实升级验证

状态：完成

实施内容：

- 新增 `scripts/build_prometheus_component_package.py`，用于生成 Prometheus/observability 组件升级包。
- Prometheus 组件包 manifest 使用 `schema_version=2`，组件类型为 `observability`，服务只包含 `prometheus`，镜像只包含 `images/prometheus.tar`。
- 修复升级任务公开字段：`components=["observability"]` 时返回 `kind=component`、`component=prometheus`。
- 修复组件升级启动逻辑：只有 runner-only 包由 web-api 直接执行；Prometheus/observability 组件包提交给 upgrade-runner 执行。

TDD 记录：

- RED：新增 `test_prometheus_component_builder_emits_observability_manifest` 后，脚本不存在导致测试失败。
- GREEN：新增 Prometheus 组件包构建脚本，测试通过。
- RED：新增 API 断言后，Prometheus 组件包被错误返回为 `kind=platform`。
- GREEN：修复 `_public_task()` 分类和 component-upgrade start 执行者选择，远端容器内 API 测试通过。

远端验证：

- 在 `10.20.11.3` 生成真实组件包：`/data/upgrade-packages/components/smartx-prometheus-v2.55.1.tar.gz`。
- 包大小：`121243325` bytes。
- SHA256：`c01bd4d9753751b2e1e75acb7f171055c8740770c05c034f8a9cf43bd24801db`。
- 包结构检查：只包含 `manifest.json`、`release-notes.md`、`images/prometheus.tar`；不包含平台镜像或 runner 镜像。
- 首次真实执行 Prometheus 组件包任务 `upgrade-8e38afe4ac520146` 成功，验证 Prometheus 重启后 healthy，历史 `query_range` 返回 175 条 series。
- 修复分类/执行者后，再次真实执行 Prometheus 组件包任务 `upgrade-91593ac4799312d2` 成功：
  - upload 返回 `kind=component`、`component=prometheus`、`components=["observability"]`。
  - start 返回 `pending` 且 `runner_requested=true`，由 upgrade-runner 执行。
  - 升级前备份：`/data/backups/upgrade-v2.55.1-before-20260606093851.tar.gz`。
  - Prometheus 容器重启后 healthy。
  - `smartx_vm_storage_used_bytes` 最近 2 天 `query_range` 返回 175 条 series。

仍未完成：

- 新部署添加 Tower 并采集未执行，避免覆盖现场已有 Tower 凭据和采集状态。
- v1 迁移包导入独立验证环境仍未执行。

### 2026-06-06 Phase V2 数据迁移隔离回归与报表历史尾点回退

状态：完成一轮不影响正式数据的隔离迁移回归，并修复报表 instant 为空时的增长榜空白问题

发现：

- 在 `10.20.11.3` 使用最新迁移包 `/data/exports/migrations/smartx-capacity-insight-migration-20260606075715-438dc55b.tar.gz` 导入隔离目录 `/data/v2-migration-verify`。
- 隔离导入结果：SQLite 中 `towers=1`、`clusters=1`、`vm_latest=523`、`vm_volumes=89530`；Prometheus 历史 block 为 `7` 个，迁移健康检查 `complete=true`。
- 隔离 Prometheus 直接查询历史 block：`smartx_vm_storage_used_bytes` 90 天窗口返回 `525` 条历史 series，最大样本时间为 `2026-06-06 13:07:52`。
- 单独只有历史 block、还没有当前 scrape 样本时，Prometheus 当前 instant 可能为空；旧报表逻辑依赖 instant 作为 VM 当前值，会导致日/月增长榜暂时为空。

修复：

- `backend/app/v2/reports/service.py` 中 VM 增长榜当前值优先使用 Prometheus instant；instant 为空或缺少部分 VM 时，用历史窗口每条 VM series 的最后一个样本回退。
- 集群总容量优先使用 `smartx_cluster_storage_total_bytes` instant；instant 为空时，用历史窗口尾点回退，避免预测报表缺少容量阈值。
- 新增 `backend/tests/test_v2_reports.py` 覆盖 Prometheus instant 为空但 range 有历史样本时，日增长、月增长和集群总容量仍可恢复。

验证：

- 本地 `python3 -m py_compile backend/app/v2/reports/service.py backend/tests/test_v2_reports.py` 通过。
- 远端容器内 `backend.tests.test_v2_reports backend.tests.test_v2_migration backend.tests.test_v2_dashboard_vm` 共 11 个测试通过。
- 远端隔离 Prometheus + 迁移目录验证：修复后报表返回 `clusters=1`、`cluster_points=15`、`day_growth=100`。
- 隔离包 `month_growth=0` 符合 v2 口径：该迁移包历史跨度约 15 天，不满足月增长榜固定 `>=30` 天样本跨度要求。

仍未完成：

- 新部署后添加 Tower 并真实采集的现场验证未执行，避免擅自修改现有 Tower 配置和凭据。

### 2026-06-06 Phase V2 真实 Tower 采集闭环与凭据兼容

状态：完成真实采集验证，修复 v1 Tower 凭据兼容和报表重复集群问题

发现：

- `10.20.11.3` 的 v2 环境已有启用 Tower `CHINATOWER` 和启用集群 `SMARTX-TT-WW`，但首次手动采集失败，提示 `Tower requires either an API token or username/password.`。
- 只读检查确认 Tower 用户名存在，但旧密码/API Token 无法被 v2 当前凭据格式解密。
- 根因是 v1/v0.4.x Tower 凭据使用 Fernet 加密，密钥种子来自 `SMARTX_CREDENTIAL_KEY` 或 `SMARTX_SECRET_KEY`；v2 第一版只支持新凭据格式。
- 用户重新录入 Tower 密码后，远端布尔检查显示 `password_decrypts=true`。
- 真实采集后发现报表里同一集群被拆成两条 series：历史指标带 `cluster/tower` label，新指标不带，Prometheus 按完整 label set 生成多条 series。

修复：

- `V2Settings` 增加 `credential_key`。
- `InventoryService.get_tower_secret_material()` 优先按 v2 格式解密；失败后按 v1 Fernet 格式兼容解密，密钥种子优先 `SMARTX_CREDENTIAL_KEY`，其次 `SMARTX_SECRET_KEY`。
- 新增 `backend/tests/test_v2_inventory_metrics.py` 覆盖 v1 Fernet 凭据可由 v2 读取。
- `ReportService.latest_report()` 按 `(tower_id, cluster_id)` 合并集群 series，避免旧 label 和新 label 导致同一集群重复显示。
- 新增 `backend/tests/test_v2_reports.py` 覆盖同集群多 label series 合并。

现场验证：

- 手动采集成功：`采集完成：1 个集群，172 台虚拟机。`
- collector-worker `/metrics` 有约 `27608` bytes，VM 指标行 `174`，集群 used 指标行 `3`。
- Prometheus target `smartx-collector` 状态 `up`，当前 VM instant 样本 `172` 条，最近 2 小时 series `172` 条。
- Dashboard：`towers=1`、`clusters=1`、`vms=177`、`day_growth=69`、采集状态 success。
- VM：列表 `172` 台，首个 VM 7 天趋势点 `146`。
- Report：`clusters=1`、`cluster_points=14`、`forecast_days=90`。

验证命令：

- 本地 `python3 -m py_compile backend/app/v2/config.py backend/app/v2/security.py backend/app/v2/inventory/service.py backend/app/v2/reports/service.py backend/tests/test_v2_inventory_metrics.py backend/tests/test_v2_reports.py` 通过。
- 本地 `git diff --check` 通过。
- 远端容器内后端组合测试 `backend.tests.test_v2_reports backend.tests.test_v2_inventory_metrics backend.tests.test_v2_collection backend.tests.test_v2_dashboard_vm backend.tests.test_v2_migration backend.tests.test_v2_upgrade backend.tests.test_v2_package_builders` 共 28 个测试通过。
- 远端前端关键测试 `AppLayout.test.tsx DashboardPage.test.tsx global.test.ts ServicePage.test.tsx` 共 20 个测试通过。
- 远端健康检查：`/api/system/health` 返回 ok，前端 8080 返回 200，Prometheus healthy。

### 2026-06-06 Phase V2 任务文档状态治理

状态：完成一轮 v2 任务文档对齐

发现：

- 根目录 `task_plan.md` 顶部仍保留 v1/dev 旧上下文：默认分支 `dev`、路径 `/opt/smartx-storage-forecast`、基线 `v0.3.3U1` 和一批旧报表未提交变更。
- `docs/v2-rebuild-task-plan.md` 中 Phase V2-3 到 V2-9 的 checklist 已全部完成，但阶段状态仍写“进行中”或“待处理”。
- `docs/upgrade-issues.md` 和 `docs/functional-modules.md` 仍把 Prometheus 组件升级策略、全新升级模式、runner 自升级标为“设计待定/待处理”，与当前 v2 代码和远端真实验证不一致。

处理：

- `task_plan.md` 当前环境改为 v2 事实：`feature/upgrade-v2`、`/opt/smartx-storage-forecast-v2`、平台 `v0.5.0`、runner `v0.3.0`。
- `task_plan.md` 将 v1/dev 旧报表提交阶段标记为归档，不再作为当前 v2 待办。
- `task_plan.md` 将 Phase 12 全新升级模式和 Phase 13 数据迁移灾备标记为“完成第一版”，并补充当前证据和后续增强边界。
- `docs/v2-rebuild-task-plan.md` 将 Phase V2-3 到 V2-9 状态统一改为“完成第一版”。
- `docs/upgrade-issues.md` 将 Prometheus/observability 组件升级策略和 v2 全新升级模式标记为已解决第一版。
- `docs/functional-modules.md` 将升级模式、runner-only 组件升级和 Prometheus observability 组件升级标记为已解决。

验证：

- 本轮是文档状态治理，没有修改代码。
- 已计划执行 `git diff --check` 和状态检查后提交。

### 2026-06-06 Phase V2-15 首页容量风险 API 第一版

状态：完成 Dashboard 容量风险结构增强

目标：

- 首页打开后能一眼看到容量风险。
- 风险判断必须以单集群为准：任一集群使用率 `>=80%` 即高风险，不被整体平均容量掩盖。
- API 返回足够结构化的信息，前端风险卡片和风险提示不再只依赖前端兜底文案。

TDD 记录：

- RED：在 `backend/tests/test_v2_dashboard_vm.py` 增加断言，要求 `capacity_risk` 返回 `title`、`danger_count`、`warning_count` 和 `top_clusters`；远端容器内测试因缺少 `title` 失败。
- GREEN：`DashboardService._capacity_risk()` 返回完整结构：`level/title/message/description/cluster_count/warning_count/danger_count/top_clusters`。

验证：

- 远端容器内单测 `backend.tests.test_v2_dashboard_vm.V2DashboardVmTest.test_dashboard_summary_uses_single_cluster_risk_and_latest_vm_names` 通过。
- 远端容器内 `backend.tests.test_v2_dashboard_vm` 共 5 个测试通过。
- 远端临时 Node 容器内 `DashboardPage.test.tsx` 共 4 个测试通过。
- 本地 `python3 -m py_compile backend/app/v2/dashboard/service.py backend/tests/test_v2_dashboard_vm.py` 通过。
- 本地 `git diff --check` 通过。
- 在 `10.20.11.3` 重建并重启 `web-api` 后，真实 `/api/dashboard/summary` 返回完整容量风险字段：`level/title/description/cluster_count/warning_count/danger_count`，且 `top_clusters=1`。

### 2026-06-06 Phase V2-14 报表容量风险摘要

状态：完成 Word/Excel 首页容量风险摘要第一版

目标：

- 报表不只导出数据表，还要在首页把客户最关心的容量风险前置展示。
- 风险摘要复用集群当前容量/总容量口径，任一集群达到阈值即可提示。

TDD 记录：

- RED：扩展 `backend/tests/test_v2_report_exports.py`，要求 Word XML 和 Excel 汇总页包含“容量风险摘要”以及 `Cluster A 使用率超过 80%`。
- GREEN：`backend/app/v2/reports/export.py` 在 Word 首页基础信息表和 Excel `汇总` sheet 增加“容量风险摘要”。
- 测试样例调整为 Cluster A 当前容量 `810/1000`，确保测试真实覆盖高风险路径。

验证：

- 远端容器内 `backend.tests.test_v2_report_exports.V2ReportExportApiTest.test_report_exports_require_auth_save_files_and_expose_download_link` 通过。
- Excel 断言改为 `openpyxl.load_workbook` 读取汇总页单元格，避免依赖 `sharedStrings.xml` 是否存在。

### 2026-06-06 Phase V2-16 项目架构总览

状态：完成项目架构总览文档第一版

目标：

- 给 v2 重建后项目提供一个统一架构入口，方便后续接手、排障和继续开发。
- 把容器职责、数据职责、任务模型、升级包结构、迁移包结构和安全边界集中记录，避免只散落在多个细节文档里。

处理：

- 新增 `docs/architecture.md`。
- 文档记录 5 容器交付形态：`frontend`、`web-api`、`collector-worker`、`prometheus`、`upgrade-runner`。
- 文档记录后端模块边界、SQLite/Prometheus/`/data` 职责、任务模型、升级包结构、迁移包结构、安全边界和当前版本边界。
- `task_plan.md` 将 Phase 16 标记为完成第一版。
- `docs/v2-rebuild-task-plan.md` 补充 `docs/architecture.md` 作为架构总览交付物。

验证：

- 本轮为文档架构整理，无代码改动。

### 2026-06-06 Phase V2-17 远端完整回归与测试隔离修复

状态：完成 v2 第一版远端回归验证

目标：

- 继续完成 `feature/upgrade-v2` 受控重建收口。
- 在 `10.20.11.3` 重新验证远端 v2 分支、容器状态、后端测试、前端测试和健康检查。
- 修复回归过程中发现的测试隔离和旧 schema 兼容问题。

发现：

- 远端 `test_v2_cleanup` 的 API 测试调用 `/api/admin/system/restart` 时没有 mock 系统重启服务，在带 Docker socket 的容器里会真实执行 `docker compose up -d`，导致在线验证环境容器被重建。
- 远端容器环境包含 `SMARTX_DB_PATH=/data/smartx.db`。部分 API 测试只设置 `SMARTX_DATA_ROOT`，仍会被 `SMARTX_DB_PATH` 覆盖到真实业务库，导致采集记录测试读到现场历史记录。
- 旧库如果已存在 `users` 表但缺少 `updated_at` 列，修改密码会执行 `UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP ...` 并报 `sqlite3.OperationalError: no such column: updated_at`。

修复：

- `backend/tests/test_v2_cleanup.py` 使用 FastAPI `dependency_overrides` 替换 `get_system_control_service`，重启接口测试改为 fake service，不再真实执行 Docker 重启。
- `backend/app/v2/config.py` 在 `SMARTX_DATA_ROOT` 被显式改为非 `/data` 且 `SMARTX_DB_PATH` 仍为 compose 默认 `/data/smartx.db` 时，忽略该默认 DB path，避免测试或临时实例污染真实库。
- `backend/app/v2/database.py` 初始化时为旧 `users` schema 补 `updated_at` 列，并回填当前时间；新建 schema 仍保留原来的 `DEFAULT CURRENT_TIMESTAMP`。
- `backend/tests/test_v2_foundation.py` 增加上述两个回归测试。

验证：

- 本地目标测试 `backend.tests.test_v2_foundation.V2FoundationTest.test_settings_ignore_default_compose_db_path_when_data_root_is_overridden`、`test_database_adds_users_updated_at_for_existing_schema`、`test_settings_respect_compose_mounted_data_paths` 通过。
- 本地 `python3 -m py_compile backend/app/v2/config.py backend/app/v2/database.py backend/tests/test_v2_foundation.py backend/tests/test_v2_cleanup.py` 通过。
- `10.20.11.3` 受影响后端组合测试 `backend.tests.test_v2_auth_api backend.tests.test_v2_collection_runs_api backend.tests.test_v2_cleanup backend.tests.test_v2_foundation` 共 16 个通过。
- `10.20.11.3` 完整 v2 后端测试 `test_v2_*` 共 65 个通过。
- `10.20.11.3` 前端关键测试 `AppLayout.test.tsx DashboardPage.test.tsx global.test.ts ServicePage.test.tsx` 共 20 个通过。
- `10.20.11.3` 健康检查：`/api/system/health` 返回 `version=v0.5.0`、`runner_version=v0.3.0`，前端 `8080` 返回 `200`，Prometheus `/-/healthy` 返回 healthy。

注意：

- 旧 v1 测试和非 v2 测试中仍有会操作 Docker 或依赖旧服务的用例，不适合作为远端在线环境全量回归命令。当前 v2 远端回归以 `backend/tests/test_v2_*.py` 为准。

### 2026-06-06 升级问题台账 v2 口径收口

状态：完成文档口径治理

发现：

- `docs/upgrade-issues.md` 仍保留多处 v1/v0.4 或 runner v0.2.x 时代的“待验证、待完整回归、v0.4.0 升级包、v0.2.2 基线”描述。
- `docs/v2-upgrade-center-design.md` 仍写着 web-api 不直接执行复杂 Docker 升级动作，但真实 v2 方案已经根据 runner-only 自升级断链问题调整为：runner-only 组件升级由 web-api 直接执行，平台和 Prometheus/observability 升级继续交给 upgrade-runner。

处理：

- `docs/upgrade-issues.md` 更新时间改为 2026-06-06。
- 将 UPG-001、UPG-002、UPG-003、UPG-004、UPG-005、UPG-006、UPG-007、UPG-008、UPG-009、UPG-011、UPG-014、UPG-015、UPG-019 的状态描述对齐到 v2 当前事实。
- 补充 `10.20.11.3` 已真实执行平台升级包、runner 组件包和 Prometheus/observability 组件包的验证记录。
- `docs/v2-upgrade-center-design.md` 明确 runner-only 组件升级由 web-api 直接执行，平台升级和 Prometheus/observability 升级由 upgrade-runner 执行。

验证：

- 本轮只修改文档。

### 2026-06-07 v2 任务中心通知与配置迁移决策记录

状态：文档已记录，代码待实施

处理：

- 用户确认数据迁移优先采用“配置迁移包”方案。
- 配置迁移包只迁移 SQLite 中的 `towers` 和 `clusters`，用于新机器快速恢复 Tower 纳管关系。
- 完整迁移包继续用于无缝搬家，保留 SQLite 必要数据和 Prometheus 历史指标。
- 暂不拆分 SQLite 双 DB；`config.db + runtime.db` 作为后续低优先级架构治理项。
- 用户确认任务中心需要 `info`、`warning`、`critical` 三类通知。
- 任务中心角标应代表未处理通知数量，不代表 pending/running 任务数量。
- 告警和严重告警需要确认或删除后才消除角标；一键清空只清除已读信息和已确认告警。

修改文件：

- `task_plan.md`
- `findings.md`
- `docs/v2-rebuild-task-plan.md`
- `progress.md`

验证：

- `git diff --check` 通过。
- `git status --short` 确认本轮只包含文档变更。
- 敏感词扫描未发现新增真实密码、token 或私钥；命中项均为通用字段说明或历史文档规则。
- `rg` 检查当前任务文档和升级台账不再保留未收口的 v2 待验证项；剩余 v0.2.x/v0.4.0 文本仅作为历史现象或历史验证记录保留。

### 2026-06-07 Phase 18 任务中心状态机与残留任务清理

状态：完成第一版并已部署到 `10.20.11.3`

问题：

- 任务中心出现多条 `执行系统升级`，进度 1%，点 X 后显示“升级任务不存在”或“已从等待队列移除”，但点“清空”后又恢复。
- 用户要求：清空只能清成功完成任务；异常/失败任务不能被清空，需要手动点 X 消除。
- 用户最后明确要求“直接清理掉”现场残留任务。

根因：

- 前端开始升级时曾使用 `upgrade-start-*` 临时 id 创建任务中心记录，取消接口需要真实后端升级 `task_id`，因此取消会找不到升级任务。
- SQLite `tasks` 表中残留了大量 `pending` 升级任务，但对应 `/data/upgrades/<task_id>/task.json` 已不存在；`/api/tasks` 会继续返回这些记录，而“清空”不会删除 pending。
- 前端任务合并逻辑曾让本地 active 状态压过后端完成态，导致完成任务可能继续显示执行中。

代码修复：

- `backend/app/v2/upgrade/service.py`
  - `cancel()` 支持 task.json 缺失时回退读取 SQLite `tasks` pending 记录，把孤儿升级任务标记为 `cancelled`。
- `backend/app/v2/tasks/service.py`
  - `clear_finished()` 改为只删除 `success`。
  - 新增 `delete_inactive()`，仅允许删除非 `pending/running` 任务。
- `backend/app/v2/api.py`
  - 新增 `DELETE /api/tasks/{task_id}` 手动移除非 active 任务。
- `frontend/src/App.tsx`
  - `clearTasks()` 只移除 `succeeded`。
  - 新增任务 X 处理逻辑：pending 升级走取消；failed/cancelled 走手动删除。
  - `addTask()` 改为同 id upsert。
  - `mergeTasks()` 允许后端完成态覆盖本地 active。
- `frontend/src/pages/ServicePage.tsx`
  - `startUpgrade()` / `startComponentUpgrade()` 使用真实 `task_id` 创建任务中心任务。
- `frontend/src/components/AppLayout.tsx`
  - failed/cancelled 显示“从任务中心移除”的 X。
  - pending 的系统/组件升级显示“取消等待任务”的 X。

测试：

- 本地通过：
  - `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_upgrade.V2UpgradeServiceTest.test_cancel_orphaned_pending_upgrade_task_marks_task_cancelled backend.tests.test_v2_upgrade.V2UpgradeServiceTest.test_cancel_pending_upgrade_prevents_runner_execution_and_marks_task_cancelled`
  - `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_tasks_api.V2TaskServiceTest.test_task_service_persists_lists_updates_and_clears_finished_tasks`
  - `python3 -m py_compile backend/app/v2/upgrade/service.py backend/app/v2/tasks/service.py backend/app/v2/api.py`
- 远端 `10.20.11.3` 通过：
  - 后端目标测试 2 个通过。
  - 前端 `AppLayout.test.tsx ServicePage.test.tsx` 17 个测试通过。
  - 前端 build 通过。
  - 重建并启动 `web-api`、`frontend` 后，`/api/system/health=200`、`8080=200`。

现场清理：

- 在 `10.20.11.3` 的 `web-api` 容器内连接 `/data/smartx.db`。
- 清理前 `tasks` 表 19 条记录，大部分为 `pending` 的 `执行系统升级` 且 `task.json` 已缺失。
- 用户明确要求直接清理后，执行 `DELETE FROM tasks`。
- 清理后确认 `tasks_count=0`。

注意：

- 本次直接清理只删除任务中心记录，未删除业务库数据、升级包目录、Prometheus 历史指标或备份。
- 后续如果用户没有明确要求，不要直接 `DELETE FROM tasks`；优先使用页面 X 或 API。

### 2026-06-07 Phase 19 数据迁移进度、SQLite 瘦身与升级文档增强

状态：完成第一版并已在 `10.20.11.3` 验证

目标：

- 执行 v2 待办 3、5、4，顺序为数据迁移大数据量进度优化、SQLite/虚拟卷存储结构瘦身、升级中心 v2 后续增强文档补齐。

实现：

- 数据迁移导入新增后台任务接口：
  - `POST /api/admin/migration/import/start`
  - `GET /api/admin/migration/import/status/{task_id}`
  - 前端数据迁移页默认使用后台任务，任务中心展示上传保存、解压校验、导入前备份、SQLite 导入、Prometheus 历史指标导入、健康检查。
- 数据迁移导出继续使用后台任务，并保留扫描、打包、保存、下载链接和服务器留档路径。
- 迁入上传包保存到 `/data/exports/imports/<task_id>/`。
- 导入前备份保存到 `/data/backups/import-before-*.tar.gz`，备份成功后才继续写入业务库和 Prometheus 历史 block。
- 导入健康检查返回 SQLite 表计数、数据库大小和 Prometheus block 摘要。
- v2 正式数据源只使用 `vm_volumes`：
  - 初始化旧库时从 `latest_vm_volumes.payload_json` 抽取必要字段写入 `vm_volumes`。
  - 抽取完成后删除旧 `latest_vm_volumes` 表。
  - `schema_migrations` 记录 `drop_legacy_latest_vm_volumes`。
  - 覆盖导入旧库后也会执行 v2 初始化迁移。
- 空间清理新增 SQLite 空间整理：
  - `GET /api/admin/system/sqlite-vacuum/scan`
  - `POST /api/admin/system/sqlite-vacuum`
  - 执行前备份 `smartx.db` 到 `/data/backups/sqlite-before-vacuum-*.db`。
- 升级中心文档增强：
  - `docs/v2-upgrade-center-design.md` 补充 manifest 组件声明、执行边界、组合升级顺序、Prometheus 历史指标回归、失败恢复和 v2 兼容边界。
  - `docs/v2-api-contracts.md` 补充迁移后台任务和 SQLite VACUUM API。
  - `docs/v1-data-compatibility.md` 补充旧 VM 卷 payload 抽取后删除规则。

本地验证：

- `python3 -m py_compile backend/app/v2/migration/service.py backend/app/v2/database.py backend/app/v2/cleanup/service.py backend/app/v2/api.py` 通过。
- 本地 `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_migration backend.tests.test_v2_foundation backend.tests.test_v2_cleanup` 因本机不安装依赖，仍停在缺少 `fastapi/httpx`，需在 `10.20.11.3` 容器内完成完整验证。

远端验证：

- `10.20.11.3:/opt/smartx-storage-forecast-v2` 后端容器内测试通过：
  - `backend.tests.test_v2_migration`
  - `backend.tests.test_v2_foundation`
  - `backend.tests.test_v2_cleanup`
  - 共 22 个测试通过。
- 远端 `node:22-alpine` 容器内前端测试通过：
  - `ServicePage.test.tsx` 共 10 个测试通过。
- 远端 `docker compose --project-name smartx-storage-forecast build web-api frontend` 通过。
- 重建 `web-api` 和 `frontend` 后：
  - `/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
  - `8080` 返回 `HTTP/1.1 200 OK`。
  - Prometheus `/-/healthy` 返回 healthy。
- API 轻量真实验证通过：
  - 迁移导出后台任务 `status=succeeded`、`progress=100`，且返回下载链接。
  - SQLite VACUUM scan 返回 `size=141012992`、`estimated_reclaimable=67407872`。
  - 迁移健康检查返回“业务库和 Prometheus 历史指标完整”，Prometheus block 数 `9`，SQLite 表数 `13`。

注意：

- 本轮真实验证只执行 SQLite VACUUM 扫描，没有执行真实 VACUUM，避免无必要改动现场业务库；VACUUM 代码路径已由后端单测覆盖备份后整理。

### 2026-06-07 v2 升级包类型文档补齐

状态：文档完成

处理：

- `docs/v2-upgrade-center-design.md` 将升级包结构拆分为三类：
  - 平台升级包：`web-api`、`collector-worker`、`frontend`，执行者为 `upgrade-runner`。
  - 升级中心组件包：`upgrade-runner`，执行者为 `web-api`。
  - 观测组件包：Prometheus，执行者为 `upgrade-runner`。
- 文档分别写明三类包的树形目录、是否允许 `project/`、是否需要迁移脚本、版本独立性和执行流程。

验证：

- 本轮只修改文档。

### 2026-06-07 任务中心通知与配置迁移实现

状态：完成第一版并已在 `10.20.11.3` 验证

实现：

- 任务中心通知状态持久化到 SQLite `tasks` 表：新增 `severity`、`seen_at`、`acknowledged_at`。
- 后端任务返回 `severity`、`unhandled`、`clearable`，并新增：
  - `POST /api/tasks/seen`
  - `POST /api/tasks/{task_id}/ack`
  - `DELETE /api/tasks/clearable`
- 前端任务角标改为未处理通知数量，不再统计 running/pending。
- 信息类成功任务打开任务中心并点击空白关闭后标记已读。
- 告警/严重告警失败任务显示“确认”按钮，确认或 X 删除后才清除角标。
- 一键清空只清理已读信息任务和已确认告警/严重告警任务。
- 新增配置迁移包：
  - `GET /api/admin/migration/config/export`
  - 包名 `smartx-config-migration-YYYYMMDDHHMMSS-*.tar.gz`
  - manifest 标记 `migration_scope=config`
  - 包内只包含 `towers/clusters` 的轻量 SQLite，不包含 Prometheus 历史指标。
- 数据迁移导入自动识别 `config` 与 `full` 包；配置导入前仍生成备份，只 merge `towers/clusters`。
- 前端数据迁移页新增“导出配置迁移包”，与完整“导出迁移包”区分。

验证：

- `10.20.11.3` 后端容器内通过：
  - `backend.tests.test_v2_tasks_api`
  - `backend.tests.test_v2_migration`
  - 共 11 个测试通过。
- `10.20.11.3` Node 容器内通过：
  - `AppLayout.test.tsx`
  - `ServicePage.test.tsx`
  - 共 22 个测试通过。
- `10.20.11.3` 完成 `docker compose --project-name smartx-storage-forecast build web-api frontend`。
- `10.20.11.3` 完成 `web-api/frontend` recreate。
- 远端健康检查通过：
  - `/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
  - `8080` 返回 `HTTP/1.1 200 OK`。

注意：

- 配置迁移包适合新机器快速恢复 Tower 纳管和集群配置；不保留趋势、日增长、月增长和预测历史。
- 需要保留历史趋势和预测时继续使用完整迁移包，完整迁移包仍包含 SQLite 业务库和 Prometheus 历史 block。

### 2026-06-07 Phase V2-15.3 首页风险链路增强

状态：完成并通过目标测试

实现：

- Dashboard API `capacity_risk.top_clusters[]` 增加 `top_growth_vms`，复用已有日增长最快 VM 结果，不新增 Prometheus 查询。
- 每个风险或关注集群最多返回 3 台主要增长 VM，字段包含 `tower_id`、`cluster_id`、`vm_id`、`vm_name`、`current_bytes`、`growth_amount`、`growth_ratio`。
- 首页顶部“容量风险”小卡行为保持不变，继续跳转风险集群报表。
- 首页底部“风险提示”从单个大按钮改为信息面板，展示风险摘要、查看风险报表入口和主要增长 VM。
- 点击主要增长 VM 行复用 `onSelectVm(vm_id, vm_name)`，直接进入虚拟机页面。
- 风险集群无增长 VM 时显示 `风险集群暂无明显 VM 增长来源`。

验证：

- 本地通过 `python3 -m py_compile backend/app/v2/dashboard/service.py backend/tests/test_v2_dashboard_vm.py`。
- 本地通过 `git diff --check`。
- `10.20.11.3` 后端容器内通过 `backend.tests.test_v2_dashboard_vm`，共 6 个测试通过。
- `10.20.11.3` Node 容器内通过 `DashboardPage.test.tsx`，共 9 个测试通过。

### 2026-06-08 Phase 14 Word 报表产品化优化

状态：完成并已在 `10.20.11.3` 验证

实现：

- v2 Word 导出继续使用 v2 `latest_report()` 数据口径和现有导出 API，不回退 v1 查询逻辑。
- Word 报表恢复接近 v1 的客户交付版式：封面品牌条、英文副标题、蓝色分隔线、报告说明卡片、页眉页脚、目录表格和集群书签。
- 参考客户版模板补充执行摘要、关键发现、容量风险评估矩阵和短/中/长期运维建议。
- Word 表格不再沿用旧红底高风险行风格，改为直接参考客户版模板：深蓝表头、浅色摘要/斑马纹、增长量蓝色、增长率橙/红色。
- 保留 v2 生成的趋势图、Top 10 VM 增长图、TOP100 数据口径，并在摘要和集群汇总/章节中增加虚拟机数量。
- 运维建议不依赖 AI 服务，使用本地规则模板生成：按集群使用率、预计耗尽天数、Top 增长 VM、单 VM 容量和增长率输出确定性建议。
- 报告摘要增加 v1 风格 KPI 卡片，并前置“容量风险摘要”，正常/高风险文案按当前集群容量口径生成。
- 集群章节保留客户化 KPI 网格、风险建议、容量趋势图、Top 10 VM 增长量图、增长量 TOP100 和增长率 TOP100。
- 月增长为空时继续展示日增长数据和明确空状态文案，避免 Word 看起来像导出失败。
- Word VM 表格排序列使用箭头标识：`增长量 ↓`、`增长率 ↓`。
- 集群章节 TOP100 候选改为合并“本次统计窗口增长 VM”和“月增长 VM”，按 `tower_id + cluster_id + vm_id` 去重，避免 7/14/30 天导出时 TOP100 不全。
- Word 目录补充小标题，包含报告摘要、集群容量增长概览、本次统计窗口增长 VM、每个集群的 Top 10 VM 增长量、增长量 TOP100 和增长率 TOP100。

验证：

- 本地通过 `python3 -m py_compile backend/app/v2/reports/export.py backend/tests/test_v2_report_exports.py`。
- 本地通过 `git diff --check`。
- `10.20.11.3` 后端容器内通过 `backend.tests.test_v2_report_exports`，共 8 个测试通过。
- `10.20.11.3` 完成 `docker compose --project-name smartx-storage-forecast build web-api` 和 `web-api` recreate。
- `10.20.11.3` `/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 真实调用 `/api/reports/export/bundle?period_days=30` 成功，任务中心只生成 1 个“导出预测报表”任务，links 为 `Word`、`Excel`。
- 抽取生成的 Word XML，确认包含客户模板色值 `1A3C6E` / `F0F4FA` / `007ACC`、`Storage Capacity Forecast Report`、`执行摘要`、`报告摘要`、`关键发现`、`风险评估与建议`、`容量风险评估矩阵`、`短期（本月）`、`中期（1-3 个月）`、`长期（3 个月以上）`、`增长量 TOP100 虚拟机` 和 `增长率 TOP100 虚拟机`；旧版曾包含 `SmartX 超融合平台`，二次优化后已要求移除该官方平台表述。
- 抽取生成的 Word 包含 `word/media/*` 4 个图表资源，确认 v2 图表仍保留。

### 2026-06-08 Phase 14 Word 客户版模板二次优化

状态：完成并已在 `10.20.11.3` 验证

实现：

- 封面品牌名统一为 `存储容量预测平台`，不再使用 `SmartX 超融合平台` 作为项目名。
- DOCX 字体统一使用开源 `Noto Serif` / `Noto Serif CJK SC`，不依赖 `微软雅黑` / `Microsoft YaHei`。
- 封面元信息改为 `Tower范围`、`集群范围`；单 Tower/集群显示具体名称，多 Tower/多集群显示 `全部 Tower（N 个）`、`全部集群（N 个）`。
- 统计窗口改为选择窗口与实际采集窗口的交集；选择窗口超过采集历史时，Word 显示实际样本窗口。
- 关键发现和运维建议改为 run 级重点强调：VM 名称、Tower/集群、容量值、增长值、百分比和天数前后保留空格，并加粗放大。
- `2.2` 容量增长趋势表新增 `Tower` 列，避免多 Tower 场景只显示集群名。
- `2.3` 容量使用率可视化改为 Top 10 集群容量使用率图表说明和图表，风格向 Top 10 VM 增长图靠齐；图表生成失败时仍保留明确说明。

本地验证：

- `python3 -m py_compile backend/app/v2/reports/export.py backend/tests/test_v2_report_exports.py` 通过。
- `PYTHONPATH=backend /Users/nazawsze/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest backend.tests.test_v2_report_exports` 通过，8 个测试中 2 个按原条件跳过。
- `git diff --check` 通过。

远端验证：

- `10.20.11.3:/opt/smartx-storage-forecast-v2` 已同步本轮修改并重建 `web-api`。
- `docker compose --project-name smartx-storage-forecast build web-api` 通过，随后 `web-api` recreate 成功。
- `/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 容器内 `PYTHONPATH=backend python -m unittest backend.tests.test_v2_report_exports` 通过，共 8 个测试。
- 发现并修复图表字体细节：DOCX 正文使用 `Noto Serif CJK SC`；matplotlib 对保留的 `NotoSerifCJK-Regular.ttc` 识别为 `Noto Serif CJK JP`，因此图表字体使用同一个开源 TTC 的 `Noto Serif CJK JP` family，避免中文图表掉字。
- 真实数据导出 14 天和 365 天 Word 均成功；选择窗口超过采集历史时，两个文件都显示实际样本窗口 `2026-05-25 - 2026-06-08`。
- 已用 Documents 渲染工具把真实 Word 渲染为 PNG 检查：封面、执行摘要、2.2、2.3、5.2 页面无明显空白或错位；2.2 包含 Tower 列，2.3 为 Top 10 集群容量使用率图表，5.2 重点值加粗放大。
- 抽取 14 天和 365 天 Word XML 确认：包含 `存储容量预测平台`、`Tower范围`、`集群范围`、`Top 10 集群容量使用率`；不包含 `SmartX 超融合平台`、`微软雅黑`、`Microsoft YaHei`；包内均包含 3 个图表媒体资源。

### 2026-06-08 预计存储耗尽算法增强待办

状态：已记录，代码待实施

结论：

- 当前预计存储耗尽基于最近窗口的线性趋势：`(总容量 - 当前已用) / slope_per_day`。
- 如果某天发生一次性大数据量写入，线性趋势会被拉陡，第二天预计耗尽天数可能突然变短。
- 已在 Phase 15 后续增强中新增待办：后续需要区分长期趋势预测和单日大数据量冲击，建议展示 30/90 天平滑趋势、近 24 小时异常增长提示，以及排除单日突增后的稳健预测口径。

### 2026-06-08 Word 客户版模板细节纠正

状态：完成并已在 `10.20.11.3` 验证

实现：

- 封面在 `Tower范围` 上方新增空白 `客户名称` 字段，避免把 Tower 名称误当客户名称。
- 关键发现和运维建议的重点强调规则调整：VM 名称前后只加 1 个空格并加粗放大；容量、增长量、百分比和天数只加粗放大，不额外插入左右空格。
- 风险矩阵去掉 `单 VM 容量异常`，改为更中性的 `重点 VM 容量`。

本地验证：

- `python3 -m py_compile backend/app/v2/reports/export.py backend/tests/test_v2_report_exports.py` 通过。
- `PYTHONPATH=backend /Users/nazawsze/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest backend.tests.test_v2_report_exports` 通过，8 个测试中 2 个按原条件跳过。
- `git diff --check` 通过。

远端验证：

- `10.20.11.3:/opt/smartx-storage-forecast-v2` 已同步本轮修改。
- 容器内 `PYTHONPATH=backend python -m unittest backend.tests.test_v2_report_exports` 通过，共 8 个测试。
- 已重建并 recreate `web-api`，`/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 真实数据导出 14 天和 365 天 Word 均成功，统计窗口显示实际样本窗口 `2026-05-22 - 2026-06-08`。
- 抽取真实 Word XML 确认：包含 `客户名称`、`重点 VM 容量`、`存储容量预测平台`；不包含 `单 VM 容量异常`、`SmartX 超融合平台`；容量值/增长值没有左右双空格。
- 已用 Documents 渲染工具检查 14 天 Word：封面客户名称为空且位于 `Tower范围` 上方；风险矩阵和运维建议页无明显错位，VM 名称加粗放大并有单空格视觉分隔，数据值只加粗放大。

### 2026-06-08 Word 客户版增长口径与范围信息修正

状态：完成并已在 `10.20.11.3` 验证

实现：

- 执行摘要和 KPI 卡片不再使用 `较上月增长`，改为 `统计窗口增长`，并显示实际统计窗口。
- `2.2 容量增长趋势` 表头改为 `统计窗口增长`、`近 90 天样本增长`、`近 365 天样本增长`、`90 天预测`，避免把短采集窗口误读为自然月/季度/年度环比。
- `2.1 范围基本信息` 增加 `Tower范围`、`Tower数量`，多 Tower/多集群时显示聚合范围摘要。
- 执行摘要、关键发现和运维建议正文中的 Tower/集群名称加粗放大。

本地验证：

- `python3 -m py_compile backend/app/v2/reports/export.py backend/tests/test_v2_report_exports.py` 通过。
- `PYTHONPATH=backend /Users/nazawsze/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest backend.tests.test_v2_report_exports` 通过，9 个测试中 2 个按原条件跳过。
- `git diff --check` 通过。

远端验证：

- `10.20.11.3:/opt/smartx-storage-forecast-v2` 已同步本轮修改。
- 容器内 `PYTHONPATH=backend python -m unittest backend.tests.test_v2_report_exports` 通过，共 9 个测试。
- 已重建并 recreate `web-api`，`/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 真实数据导出 14 天和 365 天 Word 均成功，统计窗口显示实际样本窗口 `2026-05-22 - 2026-06-08`。
- 抽取真实 Word XML 确认：包含 `统计窗口增长`、`近 90 天样本增长`、`近 365 天样本增长`、`Tower数量`；不包含 `较上月`、`较上季度`、`较上一年`。
- 已用 Documents 渲染工具检查 14 天 Word：执行摘要 KPI 显示 `统计窗口增长` 并附实际窗口，`2.1` 范围基本信息包含 Tower 范围/数量和集群范围/数量，`2.2` 表头改为统计窗口与近 90/365 天口径。

### 2026-06-08 Word 客户版自查与预测 current 修复

状态：完成并已在 `10.20.11.3` 验证

自查结论：

- 14 天真实导出显示统计窗口 `2026-05-25 - 2026-06-08`，符合选择 14 天窗口。
- 365 天真实导出显示统计窗口 `2026-05-22 - 2026-06-08`，符合“选择窗口超过采集历史时，以实际采集窗口为准”。
- 封面和执行摘要中的 `Tower范围`、`集群范围` 与真实数据一致；多 Tower/多集群逻辑继续使用聚合范围摘要。
- 真实 Word XML 不包含 `较上月`、`较上季度`、`较上一年`、`SmartX 超融合平台`。

发现并修复：

- `forecast_series()` 原先用去离群后的最后一个点作为 `current`。当最新真实增长点被趋势过滤视为离群点时，365 天导出的 `当前已用容量` 和 `90 天容量` 会回退到旧值，出现“统计窗口增长有 1.39 TB，但 90 天预测仍等于当前容量”的不合理现象。
- 修复后 `current` 固定使用最新原始观测点；趋势斜率仍优先使用去离群样本，并在斜率为 0 但原始窗口存在正增长时使用原始窗口斜率兜底。
- `2.2 容量增长趋势` 表头进一步改为 `近 90 天样本增长`、`近 365 天样本增长`，并增加说明：采集历史不足 90/365 天时按可用样本窗口计算，避免刚部署环境误读。

验证：

- 本地 `py_compile` 通过。
- 本地 `backend.tests.test_v2_report_exports` 通过，9 个测试中 2 个按原条件跳过。
- 本地 `git diff --check` 通过。
- 远端容器内 `backend.tests.test_v2_reports backend.tests.test_v2_report_exports` 通过，共 15 个测试。
- 远端已重建并 recreate `web-api`，`/api/system/health` 返回 `ok=true`。
- 远端真实 365 天导出：`current=24507238580224.0`、`forecast_90d=32623814971151.06`、统计窗口 `2026-05-22 - 2026-06-08`；Word 文本显示 `90 天容量29.67 TB`、`统计窗口：2026-05-22 - 2026-06-08`。

### 2026-06-08 报表导出 6 种时间区间 Profile 化计划记录

状态：完成第一版，并已在 `10.20.11.3` 验证

结论：

- 用户提出导出报表有 `7/14/30/90/180/365` 六种时间区间，希望降低不同窗口下文案和口径出错概率。
- 对比后选择“1 套客户版渲染系统 + 6 个时间区间 Profile”，不做 6 份完整模板，也不做 6 套替换脚本。
- Profile 已统一驱动 Word 和 Excel 的窗口名称、增长指标标题、VM 榜单标题、样本不足说明和运维建议语气。
- 前端 6 个按钮和 API 入参 `period_days` 保持不变；后端新增内部 Profile 层完成。

实现：

- 新增 `ReportPeriodProfile` 和 `report_period_profile()`。
- 六个 Profile 固定为 `7/14/30/90/180/365`，分别对应短期突增、近两周、月度、季度、中长期和年度巡检语义。
- Word 客户版 KPI、关键发现、VM 增长章节、Top 10 VM 图表、集群增长表和运维建议短期标题均读取 Profile。
- Excel 汇总、`VM_TOP100_汇总` 和各集群 Sheet 均读取同一个 Profile。
- 选择窗口大于实际采集历史时，样本说明显示 `已按当前可用样本窗口计算`，统计窗口继续使用选择窗口与实际采集窗口的交集。

验证：

- 本地 `py_compile` 通过。
- 本地 `backend.tests.test_v2_report_exports` 通过，12 个测试中 2 个按原条件跳过。
- 本地 `git diff --check` 通过。
- 本地 `backend.tests.test_v2_reports` 因本机未安装 `httpx` 无法运行；按约束未在本机安装依赖，改在远端容器验证。
- `10.20.11.3` 容器内 `backend.tests.test_v2_report_exports backend.tests.test_v2_reports` 通过，共 18 个测试。
- `10.20.11.3` 已重建并 recreate `web-api`，`/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 真实数据导出 `7d/30d/365d` Word 和 Excel 均成功；三组文件都确认包含对应 Profile 标题和 VM 榜单标题。
- 真实 `365d` 导出在采集历史不足一年时，仍按实际数据窗口生成说明和统计窗口。

### 2026-06-09 Word 客户版封面标题与渲染细节修正

状态：完成并已在 `10.20.11.3` 验证

实现：

- Word 客户版封面标题改为 `SMARTX超融合存储容量分析报告`。
- 英文副标题改为 `SMARTX HCI Storage Capacity Analysis Report`。
- 旧标题 `存储容量预测分析报告` 和旧英文副标题 `Storage Capacity Forecast Report` 不再出现在 Word 正文 XML。
- 客户版封面适当减少空段落，降低封面后出现异常大空白的概率。
- 运维建议第三段标题从 `长期（3 个月以上）` 调整为 `三个月以上`，规避 LibreOffice 渲染时特定中文字符在蓝色加粗小标题中被裁切的问题；含义保持为三个月以上的长期治理建议。
- 运维建议分组标题统一使用轻量项目符号样式，和正文区分更清楚。
- VM Top 20 表格增加分页控制：标题和统计窗口跟随表格，表头跨页重复，数据行禁止跨页拆分。
- `3.2` 增长率 Top 20 表格前主动分页，避免出现表头留在上一页、数据行从下一页开始的断裂。

验证：

- 本地 `py_compile` 通过。
- 本地 `backend.tests.test_v2_report_exports` 通过，12 个测试中 2 个按原条件跳过。
- 本地 `git diff --check` 通过。
- `10.20.11.3` 容器内 `backend.tests.test_v2_report_exports backend.tests.test_v2_reports` 通过，共 18 个测试。
- `10.20.11.3` 已重建并 recreate `web-api`，`/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 真实数据导出 14 天 Word 成功，最新验证文件路径：`/data/exports/reports/storage-forecast-all-20260609-113141-14d.docx`。
- 抽取真实 Word XML 确认：包含新封面标题和新英文副标题，不包含旧标题；统计窗口包含 `2026-05-26 - 2026-06-09`；包含 `三个月以上`。
- 抽取真实 Word XML 确认：包含 `w:tblHeader`、`w:cantSplit` 和分页符；不包含 `Hyperconverged`。
- 已用 Documents 渲染工具检查真实 14 天 Word：封面标题显示正常，运维建议页 `短期（两周内）`、`中期（1-3 个月）`、`三个月以上` 均完整显示，无明显空白页或错位；`3.2` 增长率 Top 20 表格标题、统计窗口、表头和数据行位于同一页。

### 2026-06-09 Excel 客户版模板化计划记录

状态：完成第一版，并已在 `10.20.11.3` 验证

结论：

- 用户提供 `存储容量预测分析报表_客户版.xlsx`，希望 v2 Excel 直接学习该模板，最好以模板为母版填充真实数据，并注意容量单位。
- 已检查模板结构：包含 `封面`、`执行摘要`、`容量趋势`、`VM增长TOP20`、`日增长详情`；其中 `VM增长TOP20` 和 `日增长详情` 已有冻结窗格，整体适合作为客户版 Excel 样式基底。
- 已将模板纳入 `backend/app/v2/reports/templates/customer_report.xlsx`，`build_report_xlsx()` 加载模板后填充 v2 数据；保留现有 Excel 导出 API、bundle 任务和下载路径。
- 模板内硬编码内容需要清理：`SmartX 超融合平台`、错误客户名、固定 Tower/集群、固定统计窗口和样例容量数据都不能进入真实导出。
- Excel 多 Tower/多集群展示规则已落地：封面显示范围摘要，正文新增 `范围明细` Sheet，每行一个 `Tower + 集群`；容量趋势、集群汇总和每集群 Sheet 保留 Tower 归属。

实现：

- `封面`、`执行摘要`、`容量趋势`、`VM增长TOP20`、`日增长详情` 复用客户版模板结构和基础样式。
- 新增/保留 `目录`、`范围明细`、`集群汇总`、`VM_TOP100_汇总`、`本日新建VM`、`本月新建VM` 和每集群独立 Sheet。
- Excel 客户可读 Sheet 使用格式化容量单位；完整 Top100 Sheet 继续保留筛选/排序结构。

验证：

- TDD RED：新增 `test_xlsx_uses_customer_template_with_v2_scope_and_units` 后，旧实现因缺少模板 Sheet 失败。
- 本地 `backend.tests.test_v2_report_exports` 通过，13 个测试中 2 个按原条件跳过。
- 本地 `py_compile` 和 `git diff --check` 通过。
- 本地 `backend.tests.test_v2_reports` 因本机缺少 `httpx` 无法运行；按用户约束未在本机安装依赖，改在远端容器验证。
- `10.20.11.3` 容器内 `backend.tests.test_v2_report_exports backend.tests.test_v2_reports` 通过，共 19 个测试。
- `10.20.11.3` 已重建并 recreate `web-api`，`/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 真实接口导出 14 天 bundle 成功，Excel 文件：`/data/exports/reports/storage-forecast-all-20260609-133224-14d.xlsx`。
- 真实 Excel 验证通过：包含 `封面`、`执行摘要`、`容量趋势`、`VM增长TOP20`、`日增长详情`、`目录`、`范围明细`、`集群汇总`、`VM_TOP100_汇总`、`本日新建VM`、`本月新建VM` 和现场集群 Sheet；包含新封面标题、HCI 英文副标题、`近 14 天样本增长` 和容量单位；不包含 `SmartX 超融合平台`。

### 2026-06-09 清理测试注入的 Prometheus 异常容量点

状态：完成现场清理，未改代码

现象：

- 用户发现 7 天 Word 报表中 `当前已用容量 22.27 TB`、`近 7 天样本增长 569.98 GB`，但 `90 天预测容量` 被算成 `945.41 TB`，使用率 `431.35%`。
- 排查确认该值来自 `forecast_series()` 对集群历史点做线性趋势预测；不是由 `近 7 天样本增长` 直接外推。

根因：

- `10.20.11.3` Prometheus 中存在测试注入异常点：
  - metric：`smartx_cluster_storage_used_bytes`
  - labels：`tower_id="3"`、`cluster_id="cm551tvrv029a0858up57q8qu"`
  - 异常值：`212069600408371` bytes
  - 异常时间范围约：`1780894329 - 1780903929`
- 该异常点把线性回归斜率拉到约 `10.26 TB/天`，导致 90 天预测被拉高到约 `945 TB`。

处理：

- 临时使用 compose override 给 Prometheus 增加 `--web.enable-admin-api`，重启 Prometheus。
- 通过 `delete_series` 删除该 metric 在 `1780893600 - 1780904600` 的测试样本。
- 执行 `clean_tombstones`。
- 恢复原 compose 启动参数并 recreate Prometheus，确认 `web.enable-admin-api=false`。

验证：

- 重新查询 report：异常点数量为 `0`。
- `current=22.27 TB`，`period_growth_7=569.98 GB`。
- `forecast_90d` 从约 `945 TB` 恢复为约 `32.03 TB`。
- `slope_per_day` 恢复为约 `111.08 GB/天`。
- 真实导出 7 天 bundle 成功，Word `/data/exports/reports/storage-forecast-all-20260609-141020-7d.docx` 不再包含 `945.41` 或 `431.35`，包含约 `32.03` 的 90 天预测值。

### 2026-06-09 Word 章节重排计划记录

状态：已记录计划，尚未实施代码

用户要求：

- `执行摘要` 改成 `摘要`。
- `三`、`四` 开始按照集群分开汇报。
- `五` 进行所有集群汇总报告。
- 报告第二页插入目录，且 `三`、`四` 要按集群分目录项。

计划结论：

- Word 结构调整为：封面、目录、`一  摘要`、`二  集群容量概览`、`三  集群虚拟机增长分析`、`四  集群容量趋势图表`、`五  全集群汇总报告`。
- `三` 按集群拆分 Top 20 增长量 VM 和 Top 20 增长率 VM。
- `四` 按集群拆分容量趋势图和 Top 10 VM 增长图。
- `五` 只放全局风险矩阵、全局建议和声明。
- 目录页必须紧跟封面，并按每个集群生成 `三.x`、`四.x` 目录项。

未执行：

- 本轮只更新计划文件，没有修改 `backend/app/v2/reports/export.py`，没有同步远端，也没有重建容器。

### 2026-06-09 Word 封面统计窗口与 2.2 增长周期修复

状态：本地实现并通过本地目标测试，待远端验证

用户要求：

- 封面 `统计窗口` 下方新增 `本报表统计窗口`。
- Word 章节 `2.2 容量增长趋势` 不再展示 `近 365 天样本增长`。
- `2.2` 固定展示 `近 14 天样本增长`、`近 30 天样本增长`、`近 90 天样本增长`。
- 对 14/30/90 天周期，如果采集历史不足对应天数则显示 `数据不足`，避免把短历史样本误当完整周期增长。

实现：

- `backend/app/v2/reports/export.py`：
  - `_customer_cover_meta()` 新增 `本报表统计窗口`。
  - `_customer_cluster_growth_table()` 表头改为 14/30/90 天样本增长和 90 天预测容量。
  - 新增 `_cluster_growth_window_label()` / `_cluster_period_growth_with_min_span()`，采集跨度不足目标周期时返回 `数据不足`。
  - 2.2 表格说明更新为 14/30/90 天口径。
- `backend/tests/test_v2_report_exports.py`：
  - 覆盖封面新增 `本报表统计窗口`。
  - 覆盖 2.2 不再包含 `近 365 天样本增长`。
  - 覆盖短历史场景下 30/90 天显示 `数据不足`。

本地验证：

- `backend.tests.test_v2_report_exports`：14 个测试通过，2 个因本机缺 FastAPI 依赖跳过。
- `py_compile backend/app/v2/reports/export.py backend/tests/test_v2_report_exports.py` 通过。
- `git diff --check` 通过。

远端验证：

- 已同步 `backend/app/v2/reports/export.py` 和 `backend/tests/test_v2_report_exports.py` 到 `10.20.11.3:/opt/smartx-storage-forecast-v2`。
- 容器内 `backend.tests.test_v2_report_exports backend.tests.test_v2_reports` 通过，共 20 个测试。
- 已重建并 recreate `web-api`。
- `/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 真实导出 90 天 Word：`/data/exports/reports/storage-forecast-all-20260609-143412-90d.docx`。
- 真实 Word XML 验证：包含 `本报表统计窗口`、`近 14 天样本增长`、`近 30 天样本增长`、`近 90 天样本增长`、`数据不足`，不包含 `近 365 天样本增长`。

### 2026-06-09 Word 目录、章节重排与报表窗口拆分实施

状态：已在 `10.20.11.3` 验证完成

用户要求：

- `执行摘要` 改成 `摘要`。
- 报告第二页插入目录，并且 `三`、`四` 要按集群分目录项。
- `三`、`四` 开始按照集群分开汇报。
- `五` 进行所有集群汇总报告。
- `本报表统计窗口` 应显示用户选择的 7/14/30/90/180/365 天窗口；`统计窗口` 继续显示真实有效采集窗口。

实现：

- `backend/app/v2/reports/export.py`：
  - Word 构建顺序调整为封面、目录、`一  摘要`、`二  集群容量概览`、`三  集群虚拟机增长分析`、`四  集群容量趋势图表`、`五  全集群汇总报告`。
  - 新增 `_customer_add_directory()`，用可见目录表格列出 `2.1/2.2/2.3`、每个集群的 `三.x`、每个集群的 `四.x` 和第五章。
  - `三` 章按集群拆分增长量 Top 20 和增长率 Top 20，VM 数据只来自该集群。
  - `四` 章按集群拆分容量趋势图和 Top 10 VM 增长量图；图表不可生成时写完整空态标题。
  - 新增 `_requested_report_window_label()`，`本报表统计窗口` 使用用户选择窗口，`统计窗口` 使用实际有效采集窗口。
- `backend/tests/test_v2_report_exports.py`：
  - 增加/更新 Word XML 测试，覆盖目录顺序、集群章节拆分、报表窗口拆分和旧章节名移除。

本地验证：

- `backend.tests.test_v2_report_exports`：17 个测试通过，2 个因本机缺 FastAPI 依赖跳过。
- `py_compile backend/app/v2/reports/export.py backend/tests/test_v2_report_exports.py` 通过。
- `git diff --check` 通过。
- `backend.tests.test_v2_reports` 在本机因缺 `httpx` 无法导入 Prometheus 客户端，需在 `10.20.11.3` 容器内验证。

远端验证：

- 已同步本轮文件到 `10.20.11.3:/opt/smartx-storage-forecast-v2`，远端原文件备份为 `/tmp/smartx-v2-report-files-20260609150430.tar.gz`。
- 容器内执行 `backend.tests.test_v2_report_exports backend.tests.test_v2_reports`，23 个测试通过。
- 已重建并 recreate `web-api`。
- `/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 真实导出 90 天 Word：`/data/exports/reports/storage-forecast-all-20260609-151000-90d.docx`。
- 真实 Word XML 验证：包含 `目录`、`一  摘要`、`三  集群虚拟机增长分析`、`四  集群容量趋势图表`、`五  全集群汇总报告`、`本报表统计窗口` 和 `近 90 天（`；不包含旧章节 `一  执行摘要`、`三  虚拟机增长分析`、`四  容量趋势图表`、`五  风险评估与建议`。

### 2026-06-09 Excel Sheet 精简与单元格显示修复

状态：已在 `10.20.11.3` 验证完成

用户要求：

- 检查真实导出的 Excel，修复单元格文字/数值显示不全。
- 删除 `目录`、`范围明细`、`集群汇总`、`VM_TOP100_汇总`。
- 将 `VM增长TOP20` 改为 `VM增长TOP100`。
- 每个集群独立 Sheet 模仿 TOP100 表格式，并避免容量 bytes 原始值导致 `########` 或科学计数法。

实现：

- `backend/app/v2/reports/export.py`：
  - `build_report_xlsx()` 不再创建四个冗余 Sheet，并在导出前兜底删除。
  - 模板 Sheet `VM增长TOP20` 在导出时重命名为 `VM增长TOP100`，左右表均输出 TOP100。
  - 每集群 Sheet 顶部概览改为 Tower、集群、当前容量、统计窗口增长、90 天预测容量、总容量、使用率、预计耗尽天数和风险。
  - VM 表、日增长和新建 VM Sheet 均使用 `GiB/TiB/%/天` 可读文本，不再输出原始 bytes。
  - 增加固定列宽、标题合并、换行和行高，保证 VM 名称、容量和说明文本可读。
- `backend/tests/test_v2_report_exports.py`：
  - 覆盖 Sheet 列表、`VM增长TOP100`、集群 Sheet 可读容量、关键列宽和冗余 Sheet 移除。

验证：

- 本地 `backend.tests.test_v2_report_exports`：17 个测试通过，2 个因本机缺 FastAPI 依赖跳过。
- 本地 `py_compile backend/app/v2/reports/export.py backend/tests/test_v2_report_exports.py` 通过。
- 本地 `git diff --check` 通过。
- 已同步 `backend/app/v2/reports/export.py` 和 `backend/tests/test_v2_report_exports.py` 到 `10.20.11.3:/opt/smartx-storage-forecast-v2`，远端原文件备份为 `/tmp/smartx-v2-excel-report-files-20260609155444.tar.gz`。
- 容器内执行 `backend.tests.test_v2_report_exports backend.tests.test_v2_reports`，23 个测试通过。
- 已重建并 recreate `web-api`，`/api/system/health` 返回 `ok=true`。
- 真实导出 14 天 Excel：`/data/exports/reports/storage-forecast-all-20260609-160108-14d.xlsx`。
- 真实 Excel 验证：Sheet 为 `封面`、`执行摘要`、`容量趋势`、`VM增长TOP100`、`日增长详情`、`本日新建VM`、`本月新建VM`、`SMARTX-TT-WW`；没有 `目录`、`范围明细`、`集群汇总`、`VM_TOP100_汇总`、`VM增长TOP20`；未发现大整数容量值。

### 2026-06-09 Word 原生目录与标题样式修复

状态：已在 `10.20.11.3` 验证完成

用户要求：

- Word 不再手写目录表格，应使用真实标题样式和 Word 普通目录。
- 五个主章节使用标题一；集群章节使用标题二；小标题可进入标题三。
- 文档打开时应自动更新目录。

实现：

- `backend/app/v2/reports/export.py`：
  - 将客户版 Word 目录页从 `_customer_add_directory()` 手写表格改为 `_customer_add_native_toc()` 原生 TOC 字段。
  - TOC 字段使用 `TOC \\o "1-3" \\h \\z \\u`，覆盖 `Heading 1/2/3`。
  - 在 `settings.xml` 写入 `w:updateFields=true`，让 Word/WPS 打开文件时更新目录。
  - `一/二/三/四/五` 主章节改为真实 `Heading 1`。
  - `2.1/2.2/2.3`、`三.x`、`四.x`、`5.1/5.2` 改为真实 `Heading 2`。
  - 集群内 `增长量 Top 20` / `增长率 Top 20` 表标题改为真实 `Heading 3`，可进入三级目录。
- `backend/tests/test_v2_report_exports.py`：
  - 新增 `test_docx_uses_native_toc_and_real_heading_styles`，覆盖 TOC 字段、`updateFields`、移除旧目录表头、主章节 `Heading1` 和集群章节 `Heading2`。

本地验证：

- RED：新增测试在旧实现上失败，原因是 DOCX XML 不包含 `TOC`，且目录仍是 `章节/内容` 手写表格。
- GREEN：实现后该测试通过。
- `backend.tests.test_v2_report_exports`：18 个测试通过，2 个因本机缺 FastAPI 依赖跳过。

远端验证：

- 已同步本轮文件到 `10.20.11.3:/opt/smartx-storage-forecast-v2`。
- 容器内执行 `backend.tests.test_v2_report_exports backend.tests.test_v2_reports`，24 个测试通过。
- 已重建并 recreate `web-api`。
- `/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 真实导出 14 天 Word：`/data/exports/reports/storage-forecast-all-20260609-163003-14d.docx`。
- 真实 Word XML 验证：包含 `TOC` 和 `1-3`、`w:updateFields w:val="true"`、`Heading1`、`Heading2`、`Heading3`；不包含旧手写目录表头 `章节` / `内容`。

### 2026-06-09 Word 2.3 容量使用率可视化纯文本块化

状态：已在 `10.20.11.3` 验证完成

用户要求：

- 参考客户版截图和用户补充代码，`2.3 容量使用率可视化` 使用 DOCX 纯文本块实现，不再用图片型 Top10 集群容量使用率图。

实现：

- `backend/app/v2/reports/export.py`：
  - `2.3` 从 `_customer_usage_chart()` 改为 `_customer_usage_bars()`。
  - 多集群范围默认选择当前使用率最高的集群，并在说明中写明 Tower/集群名称。
  - 展示两条 DOCX 原生进度条：`当前使用率` 和 `90 天预测使用率`。
  - 进度条使用 `█/░` 纯文本块：`█` 表示已用比例，`░` 补足剩余比例，当前使用率为深蓝，90 天预测为亮蓝。
  - 每条进度条右侧展示 `容量阈值` 和阈值容量。
  - 下方补充容量安全边际说明，高风险时写明安全边际不足。
- `backend/tests/test_v2_report_exports.py`：
  - 扩展 Word XML 测试，覆盖 `当前使用率`、`90 天预测使用率`、`容量阈值`、`容量安全边际`、`█/░` 文本块和深蓝/亮蓝文字颜色，并断言 `2.3` 区段不再出现旧 `Top 10 集群容量使用率`。

验证：

- RED：新增测试在旧实现上失败，原因是 `2.3` 仍为旧 Top10 图表，缺少 `90 天预测使用率`。
- GREEN：实现后目标测试通过。
- 本地 `backend.tests.test_v2_report_exports`：18 个测试通过，2 个因本机缺 FastAPI 依赖跳过。
- 本地 `py_compile backend/app/v2/reports/export.py backend/tests/test_v2_report_exports.py` 通过。
- 本地 `git diff --check` 通过。
- 已同步本轮文件到 `10.20.11.3:/opt/smartx-storage-forecast-v2`，远端原文件备份为 `/tmp/smartx-v2-docx-text-bars-before-*.tar.gz`。
- 容器内执行 `backend.tests.test_v2_report_exports backend.tests.test_v2_reports`，24 个测试通过。
- 已重建并 recreate `web-api`，`/api/system/health` 返回 `ok=true`。
- 真实导出 14 天 Word：`/data/exports/reports/storage-forecast-all-20260609-171217-14d.docx`。
- 真实 Word XML 验证：`2.3` 区段包含 `当前使用率`、`90 天预测使用率`、`容量阈值`、`容量安全边际`、`█/░` 文本块、深蓝 `1A3C6E` 和亮蓝 `007ACC` 文字颜色；不包含旧 `Top 10 集群容量使用率`。
- 已将真实导出的 Word 拉回本机渲染为 PNG，确认 `2.3` 视觉为纯文本块进度条，10.16% 显示 10 个深色块，右侧紧跟容量阈值。
- 字体继续使用开源 `Noto Serif` / `Noto Serif CJK SC`，不使用 `微软雅黑`。

### 2026-06-10 Excel 客户模板固化

状态：已同步 `10.20.11.3`，容器回归验证完成

- 已以用户修改的 `storage-forecast-optimized_1.xlsx` 重建并净化仓库 Excel 模板。
- 已清除模板中的 Tower、集群、VM 和容量数据，保留列宽、行高、样式、合并范围和冻结窗格。
- 已增加隐藏集群模板 Sheet，实际导出按集群复制，输出文件不保留模板 Sheet。
- 已新增精确布局回归测试，覆盖固定 Sheet 顺序、关键列宽、关键行高、合并范围和字体。
- 本地 `backend.tests.test_v2_report_exports` 20 个测试通过，2 个因本机缺 FastAPI 依赖跳过。
- 已同步到 `10.20.11.3:/opt/smartx-storage-forecast-v2`，重建并 recreate `web-api`。
- 测试机容器内 `backend.tests.test_v2_report_exports backend.tests.test_v2_reports` 共 26 个测试通过。
- `/api/system/health` 返回 `ok=true`，数据库和 Prometheus 检查正常。
- 测试机真实数据导出：`/data/exports/reports/storage-forecast-all-20260610-193153-14d.xlsx`。
- 真实导出包含 7 个固定 Sheet 和 `SMARTX-TT-WW` 集群 Sheet；TOP100 为 101 行，关键列宽与用户模板一致，全部字体为 `Noto Sans CJK SC`，输出中不包含隐藏模板 Sheet。

### 2026-06-10 Excel 摘要与增长详情补充

状态：测试机真实数据验证完成

- 执行摘要 KPI 表第 4、6 行全部改为黑色粗体。
- `日增长详情` 标题合并为 `A1:I1`，避免标题文字显示不全。
- 在 `日增长详情` 后新增 `月增长详情`，使用 `month_fastest_growing_vms`，列结构和布局与日增长详情一致。
- 本地目标测试完成 RED/GREEN 验证；完整 `backend.tests.test_v2_report_exports` 共 21 个测试通过，2 个因本机缺 FastAPI 依赖跳过。
- 已同步到 `10.20.11.3`，重建并 recreate `web-api`；容器内报表测试共 27 个通过。
- 真实导出：`/data/exports/reports/storage-forecast-all-20260610-201601-14d.xlsx`。
- 真实文件确认摘要第 4、6 行均为黑色粗体，日/月增长标题均合并 `A1:I1`，`月增长详情` 位于 `日增长详情` 后，全部字体为 `Noto Sans CJK SC`。
- 当前现场历史窗口不足 30 天，因此月增长详情保留 Sheet 并显示明确空状态；满 30 天后按既有月增长口径填充 VM。

### 2026-06-10 Excel TOP100 初始视口修复

状态：测试机真实数据验证完成

- 根因是客户模板的 `VM增长TOP100` Sheet 保存了 `topLeftCell=C1` 和活动单元格 `H15`，导出文件继承后默认从 C 列打开。
- 导出时保留 `A5` 冻结窗格，同时强制将初始视口重置为 `A1`，活动单元格重置为 `A5`。
- 新增回归断言，确保后续模板更新不会再次把默认视口带回 C 列。
- 本地 `backend.tests.test_v2_report_exports` 共 21 个测试通过，2 个因本机缺 FastAPI 依赖跳过；`py_compile` 与 `git diff --check` 通过。
- 已同步到 `10.20.11.3`，容器内报表测试共 27 个通过，并重建、recreate `web-api`；健康检查返回 `ok=true`。
- 真实导出：`/data/exports/reports/storage-forecast-all-20260610-203302-14d.xlsx`，确认 `VM增长TOP100` 的 `topLeftCell=A1`、冻结窗格 `A5`、活动单元格 `A5`。

### 2026-06-10 Excel 日增长标签色清理

状态：测试机真实数据验证完成

- 清除 `日增长详情` Sheet 从客户模板继承的紫色标签色，表格内容、字体、列宽和内部配色保持不变。
- 导出代码显式设置 `日增长详情.sheet_properties.tabColor=None`，避免后续替换模板时再次带回标签颜色。
- 新增回归断言；本地完整报表测试 21 个通过、2 个因本机缺 FastAPI 依赖跳过，`py_compile` 与 `git diff --check` 通过。
- 已同步到 `10.20.11.3`，容器内报表测试 27 个通过，重建并 recreate `web-api`，健康检查返回 `ok=true`。
- 真实导出：`/data/exports/reports/storage-forecast-all-20260610-223344-14d.xlsx`，确认 `日增长详情` 的 `tabColor=None`。
