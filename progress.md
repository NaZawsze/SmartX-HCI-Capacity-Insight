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

设计范围：

- 平台升级、组件升级、未来 Prometheus 升级的包类型和职责边界。
- web-api 与 upgrade-runner 的职责分工，尤其是 runner 自升级的安全路径。
- manifest、镜像名、tag、compose/project 文件同步和版本来源的统一规则。
- 升级前备份、项目文件备份、运行配置备份和手动/自动回滚策略。
- 跨容器重启后的任务恢复、日志持久化、步骤状态和 UI 展示。
- 旧版本向新升级模式过渡的兼容或迁移方案。
