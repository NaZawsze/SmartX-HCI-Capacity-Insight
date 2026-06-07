# SmartX HCI Capacity Insight - 工作计划

## 目标

为 SmartX HCI Capacity Insight 项目保存可恢复的工作上下文，方便后续 Codex 会话快速理解当前状态、部署方式、分支规则和近期改动。

## 当前环境

- 主要开发与验证机器：`10.20.11.3`
- v2 远端项目路径：`/opt/smartx-storage-forecast-v2`
- v2 当前工作分支：`feature/upgrade-v2`
- v2 平台版本：`v0.5.0`
- v2 runner 组件版本：`v0.3.0`
- v2 提交策略：当前重建工作只提交并推送到 `feature/upgrade-v2`；不要同步 `dev/main` 或打 tag，除非用户明确要求。
- v1/dev 维护策略：如果用户明确要求继续修 v1 小版本，再切回 `dev` 并按用户指令处理。

## 当前未提交变更

当前本地 `feature/upgrade-v2` 工作区应保持干净。继续前先执行：

```bash
git status --short --branch
```

不要提交 `.env`、SQLite、Prometheus 数据、升级包、迁移包、备份包、导出文件或 Tower 凭据。

## 阶段计划

### Phase 1 - 持久化项目上下文

状态：完成

- 创建 `task_plan.md`、`findings.md`、`progress.md`。
- 记录项目当前架构、部署方式、分支规则、已知坑点。
- 不记录任何账号密码或敏感 token。

### Phase 2 - v1 历史报表改动

状态：归档

该阶段是 v1/dev 旧上下文，已由 v2 报表重建覆盖。除非用户明确要求回到 v1/dev，不再作为当前 v2 待办。

### Phase 3 - v1 历史报表提交

状态：归档

该阶段是 v1/dev 旧上下文，当前 v2 工作不提交到 `dev/main`。

### Phase 4 - 导出报表可读性优化

状态：完成

- Word 增加集群目录，方便按集群定位章节。
- Word/Excel 的 VM TOP100 表格标明排序口径。
- Excel TOP100 区域使用表格结构，支持表头筛选/排序。
- 增长率超过 20% 且增长量大于 100 GiB 的 VM 行标红底纹。

## 常用验证命令

在 `10.20.11.3:/opt/smartx-storage-forecast-v2` 执行：

```bash
git status --short --branch
git diff --check
docker compose --project-name smartx-storage-forecast exec -T web-api sh -lc \
  'cd /opt/smartx-storage-forecast && PYTHONPATH=backend python -m unittest backend.tests.test_v2_reports backend.tests.test_v2_inventory_metrics backend.tests.test_v2_collection backend.tests.test_v2_dashboard_vm backend.tests.test_v2_migration backend.tests.test_v2_upgrade backend.tests.test_v2_package_builders'
docker run --rm -v /opt/smartx-storage-forecast-v2/frontend:/src:ro -w /tmp node:22-alpine sh -lc \
  'cp -a /src ./frontend-test && cd frontend-test && npm install --no-audit --no-fund && npm test -- --run AppLayout.test.tsx DashboardPage.test.tsx global.test.ts ServicePage.test.tsx'
curl -fsS http://127.0.0.1:8000/api/system/health
curl -fsSI http://127.0.0.1:8080 | head -n 1
curl -fsS http://127.0.0.1:9090/-/healthy
```

## 注意事项

- v2 实现可以先在本地 worktree 修改，再推送 `feature/upgrade-v2`，最后在 `10.20.11.3` 拉取并验证。
- 不要在本机运行应用验证，除非用户明确要求。
- 不要回滚用户或其他会话留下的未提交改动。
- 修改文档时不要写入密码、私钥、token。
- 数据相关功能需要同时关注 SQLite 业务库和 Prometheus 历史指标。

### Phase 5 - 版本治理

状态：完成

目标：

- 平台版本统一为 `v0.5.0`。
- 平台三件套为 `web-api`、`collector-worker`、`frontend`。
- `upgrade-runner` 作为独立组件，版本为 `v0.3.0`。
- 平台升级包不包含 `upgrade-runner`。
- runner 只通过组件升级包和 runner 专用 GitHub Actions 构建。
- 每次版本提交必须更新 `docs/releases/CHANGELOG.md` 和相关版本治理文档。
- 后续版本治理作为长期规则执行：版本号、compose tag、升级包 manifest、DockerHub tag、changelog、验证记录必须保持一致。

待办：

- [已完成] 拆分 `SMARTX_IMAGE_TAG` 和 `SMARTX_RUNNER_IMAGE_TAG`。
- [已完成] 更新平台版本元数据到 `v0.5.0`。
- [已完成] 移除平台升级包中的 runner 镜像。
- [已完成] runner 组件包默认读取 `RUNNER_VERSION`。
- [已完成] GitHub Actions 拆分平台和 runner 构建。
- [已完成] 文档增加 DockerHub 错误 tag 清理方法。
- [已完成] 后端镜像内置 `VERSION` 和 `RUNNER_VERSION`，运行时优先读取镜像内版本文件。
- [已完成] 部署文档修正离线部署默认 tag，不再描述为 `latest`。
- [已完成] 本地验证后提交并推送到 `feature/upgrade-v2`。

### Phase 6 - 清理空间显示 0B 修复

状态：完成

目标：

- 修复 Docker 镜像清理点击“开始清理”后显示释放 `0B` 的问题。
- 修复服务管理“空间清理”点击清理后被清理后重扫结果覆盖为 `0B` 的问题。
- 在 `docs/upgrade-issues.md` 中更新 UPG-013 状态。

已完成：

- 后端镜像清理改为删除扫描候选镜像，而不是调用 Docker prune。
- 后端返回候选逻辑大小、预计释放大小和删除失败列表。
- 前端镜像清理弹窗区分“候选逻辑大小”和“实际释放”。
- 前端空间清理保留本次清理释放结果，不再清理后立刻重扫覆盖为 `0B`。

### Phase 7 - 升级预检查步骤化与网络检查

状态：完成

目标：

- 平台升级预检查显示真实检查步骤，而不是只显示泛化假进度。
- 步骤覆盖镜像名/tag、compose 文件、项目文件、敏感路径、volume、网络、磁盘空间。
- 后端校验当前 compose 和升级包 offline compose 使用 `10.249.249.0/24`，避免 172.16/172.17 网段进入升级包。

已完成：

- 后端新增 `network` 预检查。
- 前端预检查步骤按后端检查项分组展示。
- `docs/upgrade-issues.md` 将 UPG-011 标记为已解决，并补充 UPG-014 网络预检查说明。

### Phase 8 - 升级前备份进度

状态：完成

目标：

- 升级前备份不再只显示“正在备份”，而是展示扫描总量、处理字节数、当前文件和小日志。
- 任务中心能看到当前运行步骤详情，避免用户误以为卡住。

已完成：

- 后端备份前扫描候选文件数量和总字节。
- 备份写入过程中按进度或时间节流更新 task.json。
- 前端任务中心使用当前运行步骤 message 作为 detail。
- `docs/upgrade-issues.md` 将 UPG-008 标记为已解决。

### Phase 9 - 平台升级 UI 去重

状态：完成

目标：

- 合并平台升级和升级后核验内容，避免同一页面重复展示版本和运行状态。
- 平台升级区域减少二级框层级，保留清晰状态、升级包列表、操作按钮和日志。

已完成：

- 平台升级顶部新增统一“平台状态”区域。
- 当前版本、目标版本、升级中心版本、compose 项目、最近成功包、运行镜像表合并展示。
- 刷新核验改为“刷新状态”，放到平台状态标题行。
- `docs/upgrade-issues.md` 将 UPG-010 标记为已解决。

### Phase 10 - 当前剩余工作

状态：完成第一版

- [已合并到 Phase 12] 定义 Prometheus 组件升级策略。
- [已验证] 在 `10.20.11.3` 查询 Prometheus 当前 VM 指标，`smartx_vm_storage_used_bytes` 返回 175 条 series；报表接口可返回集群、日增长和统计窗口字段。
- [已解决] 在 `10.20.11.3` 完成迁移导出、merge 导入、导入前备份、服务重启和 Prometheus `query_range` 回归验证，确认历史指标、日增长和趋势图数据链路正常。
- [已解决] 数据迁移导入前自动生成当前系统备份；备份成功后才允许继续导入，备份失败默认阻止导入。

说明：

- 该阶段原本是 v1/v2 混合待办集合，当前阻塞项已经分别落入 Phase 12、Phase 13 和后续 v2 阶段处理。
- 后续如继续优化迁移大数据量进度、报表自然语言摘要或风险卡片点击链路，应作为增强项单独开阶段，不再作为当前 v2 第一版阻塞项。

### Phase 11 - 报表与虚拟机口径新增需求

状态：完成

目标：

- [已解决] 月增长最快 VM 只展示历史数据满足 30 天的虚拟机；不足 30 天不进入月增长榜，刚部署且没有满足条件时月增长榜为空。
- [已解决] 报表导出的 Word/Excel 使用同样口径，不导出不足 30 天的月增长 VM。
- [已解决] 报表导出的“上期容量”改为“期初容量”，并在表格说明/标题中标注统计窗口起止日期。
- [已解决] 在报表页“日增长最快 VM”下新增“本日新建 VM”，在“月增长最快 VM”下新增“本月新建 VM”。
- [已解决] 新建 VM 列表项支持点击跳转到虚拟机页面，并定位/过滤到对应 VM。
- [已解决] VM 改名展示使用最新采集名称覆盖历史 Prometheus label；历史趋势仍按 `tower_id + cluster_id + vm_id` 绑定。

待确认/实现要点：

- 增长榜按每台 VM 最早样本到当前样本的跨度判断是否满 30 天。
- “本日新建 VM / 本月新建 VM”按 Prometheus 历史指标首次出现时间判断，不按 VM 名称判断。
- 导出报表 VM 表头使用“期初容量”，并显示统计窗口，例如 `统计窗口：2026年05月06日-2026年06月05日`。
- VM 跳转继续使用 UUID 口径，避免同名 VM 或改名 VM 混淆。
- 最新名称映射来自最新采集样本，同一个 `vm_id` 改名后页面和导出展示最新名称。

### Phase 12 - 全新升级模式设计

状态：完成第一版

目标：

- 基于之前平台升级和组件升级遇到的问题，重新设计一套更稳定的升级架构，而不是继续在旧流程上打补丁。
- 平台升级、组件升级、Prometheus 升级、项目文件同步、数据备份、回滚、健康检查、任务状态都要形成闭环。
- Prometheus 升级并入全新升级模式，不再作为零散待办单独处理。

设计重点：

- 平台升级和组件升级的职责边界重新定义：哪些由 web-api 执行，哪些必须由独立 runner 执行。

### Phase 18 - 任务中心状态机与残留任务治理

状态：完成第一版，已提交

目标：

- 修复任务中心里“执行系统升级”pending 残留任务删不掉、清空后又恢复的问题。
- 明确任务中心清理语义，避免“清空”和“取消/移除”混用。
- 修复完成任务仍显示执行中、进度未正确落到完成状态的问题。

已完成：

- 后端 `UpgradeService.cancel()` 支持处理“任务表中存在 pending 记录，但 `/data/upgrades/<task_id>/task.json` 已不存在”的孤儿升级任务；这类任务可被标记为 `cancelled`，不再永久挂在 pending。
- 后端任务清理语义调整：
  - `DELETE /api/tasks/finished` 只清理 `success` 成功完成任务。
  - `failed`、`cancelled` 等异常/失败/已取消任务不会被“清空”删除。
  - 新增 `DELETE /api/tasks/{task_id}`，仅允许手动删除非 active 任务；`pending/running` 不能被直接删除。
- 前端任务中心语义调整：
  - `清空` 只移除前端本地 `succeeded` 任务，并调用后端成功任务清理接口。
  - pending 的“执行系统升级 / 执行组件升级”右侧 X 表示取消等待任务。
  - failed/cancelled 右侧 X 表示从任务中心手动移除。
  - 普通 pending/running 任务不允许清除。
- 前端 `startUpgrade()` 和 `startComponentUpgrade()` 创建任务中心记录时使用后端真实 `task_id`，不再使用 `upgrade-start-*` 或 `component-start-*` 临时 id。
- 前端 `addTask()` 改为同 id upsert，避免重复任务堆叠。
- 前端任务合并逻辑修复：后端 `success/failed/cancelled` 可以覆盖本地 active 状态，避免完成任务继续显示执行中。
- 已在 `10.20.11.3` 直接清理现场任务表 `tasks`，清理前 19 条、清理后 0 条；只删除任务中心记录，未动业务数据、升级包目录、Prometheus 历史指标。

验证：

- 本地后端目标测试：
  - `backend.tests.test_v2_upgrade.V2UpgradeServiceTest.test_cancel_orphaned_pending_upgrade_task_marks_task_cancelled`
  - `backend.tests.test_v2_upgrade.V2UpgradeServiceTest.test_cancel_pending_upgrade_prevents_runner_execution_and_marks_task_cancelled`
  - `backend.tests.test_v2_tasks_api.V2TaskServiceTest.test_task_service_persists_lists_updates_and_clears_finished_tasks`
- 远端 `10.20.11.3` 后端目标测试通过。
- 远端前端测试 `AppLayout.test.tsx ServicePage.test.tsx` 通过，17 个测试通过。
- 远端前端 build 通过。
- 远端已重建并重启 `web-api`、`frontend`，`/api/system/health=200`、`8080=200`。

后续注意：

- 如果任务中心仍出现历史升级任务，先查 SQLite `tasks` 表，不要只看 `/data/upgrades` 目录。
- 任务中心状态来源有两层：SQLite `tasks` 表用于全局任务中心，`/data/upgrades/<task_id>/task.json` 用于升级包历史和升级任务详情；二者可能因测试或旧逻辑产生不一致。
- 现场直接清空任务中心记录可执行 `DELETE FROM tasks`，但只能在用户明确要求“直接清理”时操作。
- runner 自升级不能依赖旧 web-api 写只读路径，也不能在执行任务中重启自己导致任务断链。
- 升级包采用统一入口，由 `manifest.json` 自动识别平台服务、runner 组件和 Prometheus/observability 组件；包类型和目标组件由 manifest 声明，不再依赖用户手动选择。
- Prometheus 作为 `observability` 组件升级，必须包含独立预检查、强制数据备份、数据目录权限检查、版本兼容检查、健康检查和历史指标查询回归。
- compose/project 文件、镜像 tag、镜像名、版本来源必须由同一套规则生成和校验。
- 所有升级动作前必须有可验证备份，回滚要覆盖镜像 override、项目文件和必要的运行配置。
- 任务日志和步骤状态要能跨服务重启恢复，避免页面显示“等待执行”但后台已经卡住。
- 统一包需要支持只升级平台三件套、只升级 runner、只升级 Prometheus，或组合升级；未在 manifest 中声明的组件一律不动。
- 新模式需要输出设计文档、接口草案、升级包目录结构、状态机和迁移路线。

当前证据：

- `docs/v2-upgrade-center-design.md` 已定义统一 manifest、状态机、runner/Prometheus 组件升级、备份和回滚边界。
- v2 代码已实现平台、runner-only、Prometheus/observability 三类包识别和第一版执行链。
- `10.20.11.3` 已真实执行平台升级包、runner 组件包和 Prometheus 组件包，历史指标回归通过。

### Phase 19 - 任务中心分级通知与角标治理

状态：完成第一版

目标：

- 将任务中心从“后台任务列表”升级为可处理的通知中心，避免短任务检查时角标瞬间出现又消失。
- 角标表示未处理通知数量，不再表示 pending/running 任务数量。
- 任务结果按 `info`、`warning`、`critical` 三类展示和处理。

设计重点：

- 任务中心通知状态持久化在 SQLite `tasks` 表，避免刷新页面或轮询后状态丢失。
- `info`：报表导出成功、数据迁移导出成功、普通成功任务；图标使用蓝色圆圈 `i`。
- `warning`：空间清理失败/取消、旧版本镜像清理失败/取消、数据迁移失败/取消、报表导出失败/取消、采集失败/取消；图标使用黄色三角感叹号。
- `critical`：服务重启失败、平台升级失败、组件升级失败、回滚失败；图标使用红色圆圈感叹号。
- 信息类任务在打开任务中心并点击空白处关闭后标记已读，角标清除。
- 告警和严重告警必须点击“确认”或 X 删除任务记录后才清除角标。
- 任务中心右侧失败/取消任务增加“确认”按钮，放在 X 左边并排。
- 一键清空只能清理信息类已读任务，以及已确认的告警/严重告警任务；未确认告警不能被一键清空。

已完成：

- SQLite `tasks` 表增加 `severity`、`seen_at`、`acknowledged_at` 持久字段。
- 后端任务接口返回 `severity`、`clearable`、`unhandled`。
- 新增任务已读、确认和可清理任务清空 API。
- 前端任务角标改为统计未处理通知。
- 信息类任务在任务菜单打开后点击空白处关闭时标记已读。
- 告警/严重告警任务增加“确认”按钮；X 仍用于手动删除非 active 任务。
- 一键清空只清理已读信息任务和已确认告警/严重告警任务。

验证：

- `10.20.11.3` 容器内 `backend.tests.test_v2_tasks_api` 通过。
- `10.20.11.3` Node 容器内 `AppLayout.test.tsx ServicePage.test.tsx` 通过。
- `10.20.11.3` 已重建并 recreate `web-api/frontend`，`/api/system/health` 和 `8080` 均返回 200。

### Phase 13 - 数据迁移灾备闭环

状态：完成第一版

目标：

- 将数据迁移从“导入/导出工具”提升为可用于现场迁移、故障恢复和版本升级前保护的灾备能力。
- 明确导出包、导入前备份、merge 规则、Prometheus 历史指标校验和导入后验证标准。

设计重点：

- 数据迁移导出包必须明确包含 SQLite 业务库、Prometheus 历史 block、导出 manifest 和校验信息。
- 导入前备份必须可验证，备份失败阻止导入；导入结果要展示备份路径、导入摘要和跳过/补全明细。
- merge 规则需要文档化：已有 Tower、集群、VM、采集记录和 Prometheus block 如何匹配、补全、跳过或冲突提示。
- 导入后提供一键健康验证：业务库记录、Prometheus series、`query_range`、趋势图、日增长、月增长和集群预测报表。
- 大数据量导出/导入需要精确进度、小日志和任务中心下载/查看入口。
- 优化 SQLite 中 `latest_vm_volumes` 的存储结构，避免继续保存 Tower 返回的完整虚拟卷原始 JSON。
- 新结构只保留页面、报表、导出和增长分析真正需要的虚拟卷字段；旧版本迁移包导入时需要兼容旧 `payload_json`，从旧 JSON 中抽取所需字段写入新结构，其他不需要的原始字段直接丢弃。
- 存储结构优化后需要提供旧数据迁移脚本，并验证迁移后 VM 页面、报表导出、数据迁移导入导出和历史指标分析不受影响。

当前证据：

- `docs/v1-data-compatibility.md` 已定义 v1 迁入、merge/overwrite、导入前备份、Prometheus 历史指标和健康验证规则。
- v2 已实现迁出、迁入、导入前备份、v1 迁移包兼容、旧 VM 卷 payload 抽取和导入后健康验证第一版。
- `10.20.11.3` 已完成迁移导出、隔离导入、Prometheus 历史 block 查询、日增长和报表历史尾点回退验证。
- 完整迁移包导出已改为真正后台任务：`/api/admin/migration/export/start` 立即返回 `task_id`，后台线程执行扫描、打包、保存，前端通过状态接口轮询进度和下载链接。

后续增强：

- 大规模现场数据下的迁移导出/导入耗时仍可继续压测和优化；当前 start 接口不再等待完整打包结束。
- SQLite 存储结构可继续瘦身，但当前 v2 已不把该项作为交付阻塞。

### Phase 20 - 配置迁移包优化

状态：完成第一版

目标：

- 为迁移到新机器的场景新增“配置迁移包”，只迁移 Tower 和集群配置。
- SQLite 迁新机器时默认不迁 `users`、`tasks`、`vm_latest`、`vm_volumes`、`collection_runs`、`metric_snapshots`。
- 不拆分 SQLite 双 DB，先用配置迁移包解决迁移速度和范围问题。

设计重点：

- 配置迁移包只包含 `towers` 和 `clusters`，用于快速恢复纳管关系。
- 平台管理员账号密码不随配置迁移，目标系统继续使用本机初始化账号。
- Tower 凭据如果依赖加密 key，目标系统 key 不一致时需要重新录入 Tower 密码或 token。
- 完整迁移包继续包含 SQLite 必要数据和 Prometheus 历史指标，用于无缝搬家和保留趋势、日增长、月增长和预测。
- Prometheus 历史指标仍是趋势图、日增长、月增长和预测报表的核心数据来源。
- 双 DB 方案作为低优先级架构治理项保留，当前不进入实现。

已完成：

- 导出配置迁移包：生成 `smartx-config-migration-YYYYMMDDHHMMSS-*.tar.gz`，manifest 标记 `migration_scope=config`。
- 配置迁移包只包含 `app/smartx.db` 中的 `towers` 和 `clusters`，不包含 Prometheus 历史指标。
- 导入时自动识别 `config` 与 `full` 两类迁移包。
- 配置导入前仍生成当前系统备份。
- 配置导入只 merge `towers/clusters`，不影响用户、任务、VM/卷缓存和历史指标。
- 前端数据迁移页区分“导出配置迁移包”和“导出迁移包”。

验证：

- `10.20.11.3` 容器内 `backend.tests.test_v2_migration` 通过。
- `10.20.11.3` Node 容器内 `ServicePage.test.tsx` 覆盖配置迁移包导出入口。
- `10.20.11.3` 已重建并 recreate `web-api/frontend`，`/api/system/health` 和 `8080` 均返回 200。

### Phase 14 - 报表产品化与客户交付

状态：完成第一版

目标：

- 将 Word/Excel 报表从“数据导出”进一步优化为客户可直接阅读和交付的容量分析报告。

设计重点：

- 首页摘要突出容量风险、风险集群、预计耗尽时间、7 天增长异常和主要增长来源。
- Word/Excel 图表风格统一，统计窗口、期初容量、当前容量、增长量、增长率和排序口径清晰标注。
- 高风险 VM、增长异常 VM、容量接近阈值集群需要在报告中前置展示，并给出解释性摘要。
- 报表导出文件需要服务端留存，任务中心提供历史下载链接和生成状态。
- 报表导出前后需要校验数据是否足够，避免客户看到空表但不知道原因。

当前证据：

- Word/Excel 首页基础信息区已增加“容量风险摘要”，优先前置展示高风险或需关注集群。
- 风险摘要按集群当前容量/总容量计算：任一集群使用率 `>=80%` 标记容量风险较高，`>=75%` 标记需要关注。
- Word/Excel 已保留统计窗口、期初容量、当前容量、增长量、增长率、排序口径、高风险 VM 底纹和服务端留存下载链接。

后续增强：

- 报表图表风格和解释性自然语言摘要仍可继续打磨，但当前第一版已能把客户最关心的容量风险放到首页。

### Phase 15 - 首页容量风险驾驶舱

状态：完成第一版

目标：

- 首页打开后能一眼判断当前环境是否存在容量风险，而不是需要下钻或翻页。

设计重点：

- 首页优先展示是否有集群使用率超过 80%，任一集群超过即触发风险提示。
- 展示最危险集群、当前使用率、预计耗尽时间、最近 7 天增长速率和主要增长 VM。
- 容量风险正常时使用明确文案，例如 `当前所有集群暂无明显容量风险`。
- 风险卡片点击应跳转到对应集群报表或 VM 增长来源，形成可追踪链路。
- 该阶段只优化首页风险认知，不和报表导出、升级体系混在一起实现。

当前证据：

- Dashboard API `capacity_risk` 已返回 `title`、`description`、`cluster_count`、`warning_count`、`danger_count` 和按使用率排序的 `top_clusters`。
- 任一集群使用率 `>=80%` 返回高风险；`>=75%` 返回需关注；无风险时返回 `当前所有集群暂无明显容量风险`。
- 首页已在第一行显示容量风险卡片，并在下方风险提示区展示同一风险摘要。
- 容量风险卡片和风险提示支持点击跳转到报表页；如存在风险集群，优先跳转到使用率最高的集群报表。
- `SmartX ZBS` 卡片已增加集群容量明细，展示每个集群的已使用、总容量、使用率和风险颜色，并支持点击集群行跳转到对应集群报表。

后续增强：

- 风险链路后续可继续扩展到 VM 增长来源，例如从风险集群直接定位主要增长 VM。

### Phase 16 - 项目架构整理

状态：完成第一版

目标：

- 在业务功能和升级/迁移稳定后，再整理项目整体架构边界，提升长期维护性。
- 该阶段不优先做，也不作为当前发版阻塞项。

设计重点：

- 保持当前约 5 个容器：`frontend`、`web-api`、`collector-worker`、`prometheus`、`upgrade-runner`。
- 不按领域拆成多个微服务容器，避免离线部署、升级包、现场排障复杂度上升。
- 优先在代码内部整理领域边界：Tower/cluster/VM、collection、metrics、reports、migration、upgrade、system。
- 明确 SQLite、Prometheus 和 `/data` 文件系统的职责分层。
- 后续如果后台耗时任务明显影响 `web-api`，再评估新增第 6 个容器 `task-worker`，用于报表生成、迁移导入导出、空间清理和批量健康检查。
- 输出 `docs/architecture.md`，记录数据职责、容器职责、任务模型、升级包结构、迁移包结构和安全边界。

当前证据：

- 已新增 `docs/architecture.md` 作为项目架构总览入口。
- 文档明确 5 容器职责、后端模块边界、SQLite/Prometheus/`/data` 职责、任务模型、升级包结构、迁移包结构和安全边界。
- 文档记录当前版本边界：平台 `v0.5.0`、runner `v0.3.0`、Prometheus `v2.55.1`、分支 `feature/upgrade-v2`。

### Phase 17 - feature/upgrade-v2 受控重建

状态：完成第一版

目标：

- 在 `feature/upgrade-v2` 上进行 v2 全新重写，但保留 v1 信息架构和核心功能口径。
- v2 不兼容旧升级路径；升级中心、组件升级和 Prometheus 升级重新设计。
- v2 必须兼容 v1 现场数据迁入，尤其是 SQLite 业务数据、Prometheus 历史指标和旧 VM 卷 payload。
- 控制部署复杂度，默认保持 5 个容器：`frontend`、`web-api`、`collector-worker`、`prometheus`、`upgrade-runner`。
- v2 后续构建、部署和现场验证可以使用 `10.20.11.3`，远端仓库必须切换到 `feature/upgrade-v2` 分支。
- v2 前端风格必须和 v1 保持一致，保留现有蓝白业务风格、导航结构、主要操作位置和客户交付感。

已产出：

- `docs/v2-rebuild-task-plan.md`：v2 受控重建任务文档，覆盖基础平台、认证、Tower/集群、采集、Prometheus、SQLite、Dashboard、VM、报表、数据迁移、任务中心、升级中心、服务管理、前端 UI、部署构建和现场验证。
- 已在 `docs/v2-rebuild-task-plan.md` 追加 Phase V2-0 细化设计文档清单。
- 已创建 Phase V2-0 的 6 个细化设计文档。

Phase V2-0 细化文档：

- [已创建] `docs/architecture-v2.md`：v2 总体架构、容器职责、模块边界和数据职责。
- [已创建] `docs/v1-data-compatibility.md`：v1 现场数据迁入 v2 的兼容规则。
- [已创建] `docs/v2-upgrade-center-design.md`：统一升级入口、manifest、状态机、runner/Prometheus 升级和回滚。
- [已创建] `docs/v2-api-contracts.md`：v2 前后端 API 和数据契约。
- [已创建] `docs/v2-frontend-design.md`：v2 前端页面、组件、交互规则和 v1 风格继承要求。
- [已创建] `docs/v2-implementation-sequence.md`：v2 代码重建阶段顺序、交付物和验收命令。
- [已更新] `docs/functional-modules.md`：标注 v2 模块边界映射。
- [已更新] `docs/upgrade-issues.md`：标注 v2 升级中心对历史问题的规避策略。

执行原则：

- 先补齐 v2 架构、v1 数据兼容和 v2 升级中心设计文档，再开始代码层面重建。
- 只在 `feature/upgrade-v2` 上推进，不影响 `dev/main`。
- 在 `10.20.11.3` 执行 v2 验证前，先确认远端仓库位于 `feature/upgrade-v2`。
- 不提交 `.env`、SQLite、Prometheus 数据、Tower 凭据、升级包、迁移包、备份包。

最新验证摘要：

- 平台版本已切换为 `v0.5.0`，runner 组件版本已切换为 `v0.3.0`。
- `10.20.11.3:/opt/smartx-storage-forecast-v2` 已在 `feature/upgrade-v2` 构建并启动五个容器。
- 健康接口返回 `version=v0.5.0`、`runner_version=v0.3.0`。
- 平台升级包仅面向 v2 同架构后续升级；v1/v0.4.x 只通过数据迁移包兼容。
- `10.20.11.3` 远端 `test_v2_*` 后端测试 65 个通过。
- `10.20.11.3` 远端前端关键测试 20 个通过。
- 远端健康检查确认 web-api、frontend、Prometheus 正常。

后续增强：

- [已解决] Dashboard 风险卡片点击跳转到具体集群报表，并在 `SmartX ZBS` 卡片内补充集群容量明细。
- 报表图表风格和自然语言摘要继续产品化。
- [已解决] 大规模现场数据迁移导出/导入进度继续细化：迁出任务记录扫描、打包、保存、下载链接，完整迁移包导出 start 接口已真正后台化；迁入改为后台任务，展示上传保存、解压校验、导入前备份、SQLite、Prometheus 和健康检查步骤。
- [已解决] SQLite / 虚拟卷存储结构瘦身：v2 正式使用 `vm_volumes`，旧 `latest_vm_volumes.payload_json` 抽取后删除并记录 schema migration；旧 `latest_vm_volume_items` 迁入 `vm_volumes` 后删除，`10.20.11.3` 执行 VACUUM 后 SQLite 从约 68.34MB 降到 32.29MB；空间清理新增 SQLite VACUUM 扫描和整理能力。
- [已解决] SQLite 运行态缓存治理第一版：`metric_snapshots` 最多保留 1 条，`collection_runs` 保留最近 7 天，`tasks` 保留最近 30 天且未确认告警/严重告警继续保留；SQLite 清理前备份并执行 VACUUM；导出文件被清理后任务中心下载链接显示“已失效”。
- [已解决] SQLite 备份清理第一版：空间清理页在“SQLite 清理并整理”下方新增独立框体，可扫描 `/data/backups` 顶层 SQLite 数据库备份，勾选后删除；不会清理升级前备份、导入前备份、Prometheus 备份或 `.tar.gz` 文件。
- [已解决] 升级中心 v2 后续增强文档补齐：`docs/v2-upgrade-center-design.md` 已补 manifest 组件声明、执行边界、组合升级顺序、Prometheus 回归和失败恢复策略。
