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
- 临时隔离修复 `main` 的三份 compose 文件，并将 `v0.4.1` tag 指向该修复提交。
- 在 dev 中新增 `RUNNER_VERSION`。
- 将平台版本元数据改为 `v0.4.1`。
- 将 runner compose tag 拆为 `SMARTX_RUNNER_IMAGE_TAG:-v0.2.2`。
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
- `python3 scripts/build_upgrade_package.py --check-version` 通过，输出 `Version metadata OK: v0.4.1`。
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
- `docs/deployment.md` 修正离线部署说明：平台三件套默认 `v0.4.1`，`upgrade-runner` 默认 `v0.2.2`，不再描述为 `latest`。
- `docs/deployment.md` 补充 `/data/upgrades`、`/data/backups`、`/data/exports`、`/data/compose-runtime` 运行产物目录说明，并修正密码修改入口为 admin 头像菜单。
- `docs/version-governance.md` 和 `docs/releases/CHANGELOG.md` 补充镜像内置版本文件规则。
- 增加测试断言，防止后续 Dockerfile 漏复制 `RUNNER_VERSION`、部署文档回退到 `latest/v0.3.1`、runner 版本不读镜像文件。

验证：

- `python3 scripts/build_upgrade_package.py --check-version --no-build` 通过，输出 `Version metadata OK: v0.4.1`。
- `python3 -m py_compile backend/app/core/config.py backend/tests/test_upgrade.py backend/tests/test_deployment_config.py scripts/build_upgrade_package.py scripts/build_runner_component_package.py` 通过。
- 自定义静态断言通过，确认 compose 拆分 `SMARTX_IMAGE_TAG:-v0.4.1` 与 `SMARTX_RUNNER_IMAGE_TAG:-v0.2.2`，Dockerfile 均复制 `VERSION/RUNNER_VERSION`，部署文档不再包含 `latest` 默认 tag 或 `SMARTX_IMAGE_TAG=v0.3.1`。
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
