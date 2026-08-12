# SmartX HCI Capacity Insight - 工作计划

## 目标

为 SmartX HCI Capacity Insight 项目保存可恢复的工作上下文，方便后续 Codex 会话快速理解当前状态、部署方式、分支规则和近期改动。

## 当前环境

- 主要开发与验证机器：`10.20.11.3`
- v2 远端项目路径：`/data/smartx-storage-forecast/project`
- v2 当前工作分支：`dev2`
- v2 平台版本：`v0.5.2`
- v2 runner 组件版本：`v0.3.1`
- v2 提交策略：当前重建工作只提交并推送到 `dev2`；不要同步 `dev/main` 或打 tag，除非用户明确要求。
- v1/dev 维护策略：如果用户明确要求继续修 v1 小版本，再切回 `dev` 并按用户指令处理。

## 当前未提交变更

当前本地 `dev2` 工作区应保持干净。继续前先执行：

```bash
git status --short --branch
```

不要提交 `.env`、SQLite、Prometheus 数据、升级包、迁移包、备份包、导出文件或 Tower 凭据。

## 专项升级链路文档

`v0.5.1 + runner v0.3.0 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2` 的详细修复、任务计划、失败证据、包路径/SHA、任务 ID 和完整链路验证，统一维护在：

```text
docs/v0.5.1-to-v0.5.2-upgrade-chain-worklog.md
```

本文件只保留最终阶段摘要。详细过程、失败记录和中间包仍查专项 worklog。

## 当前执行项 - UPG-036 / UPG-037 / UPG-038 / UPG-039 v0.5.2 final chain

状态：UPG-039 已在 `10.20.11.3` 完整链路验证通过。此前 UPG-038 follow-up 的 post-cleanup 失败根因是 handoff 后 runner 容器内路径视角变化，cleanup guard 把 host target DB 路径读错，并把容器 `/data/smartx.db` 误当 legacy DB。现已修复 runner v0.3.1 `data_migration_guard` host/container 路径归一化，v0.5.2 主升级和 post-cleanup 均成功。

目标：

- 修复 runner 组件升级实际成功但 start API 因 task revision 竞争误返回 HTTP 409 的问题。
- 保留 UPG-035 `upgrade.verification.latest_package` 只指向真实平台包的修复。
- 重打包含最新修复的 `v0.5.1u2` 和 `v0.5.2` 升级包。
- 验证完整链路：
  `v0.5.1 + runner v0.3.0 -> v0.5.1u2-upg036 -> runner-v0.3.1-upg032-historyfix -> v0.5.2-upg035-upg036`

最终包：

```text
v0.5.1u2-upg036-runner-start-conflict
path=/home/user1/codex-build/packages-upg036-runner-start-conflict/01-v0.5.1u2-runner-start-conflict/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz
sha256=d5f277167445e7636ddfba16b4f780b40d59952467bb1c8e72d2469b43ee0a49

runner-v0.3.1-upg032-historyfix
path=/home/user1/codex-build/packages-upg032-historyfix/02-runner-v0.3.1-historyfix/smartx-upgrade-runner-v0.3.1.tar.gz
sha256=d10e15cf7b516d172ebe2f1bc37621f9cf32d8ab3abd548f808ae5c5de151d2c

v0.5.2-upg035-upg036
path=/home/user1/codex-build/packages-upg036-runner-start-conflict/03-v0.5.2-upg035-upg036/smartx-capacity-insight-upgrade-v0.5.2.tar.gz
sha256=5ab9d41d1192efb794c9a43db4d340ef86bbeb0e5a4755118e517f715cdca2cc
```

验收：

- [已通过] 本地回归：`Ran 144 tests in 5.735s, OK (skipped=1)`。
- [已通过] 远端依赖完整回归：`Ran 175 tests in 186.825s, OK`。
- [已通过] 镜像身份闸门：`v0.5.1u2` 包内 web-api `/app/VERSION=v0.5.1u2`、`/app/RUNNER_VERSION=v0.3.0`；`v0.5.2` 包内 web-api `/app/VERSION=v0.5.2`、`/app/RUNNER_VERSION=v0.3.1`。
- [已通过] 两个平台包内 compose 不含 `SMARTX_IMAGE_TAG`、`SMARTX_RUNNER_IMAGE_TAG`、`SMARTX_APP_VERSION`、`SMARTX_RUNNER_VERSION`。
- [已通过] 完整链路 task：
  - `v0.5.1u2=upgrade-1e3345094fc9c4dc`
  - `runner=upgrade-a31572ffb4d37e54`
  - `v0.5.2=upgrade-f3e7160e4397acf0`
  - `post-cleanup=post-cleanup-upgrade-f3e7160e4397acf0`

后续计划：

- UPG-037 已记录到专项升级文档：升级期间前端对 web-api 重启窗口做 5 分钟容错；`/api/admin/upgrade/verification` runner version 对齐 health/component fallback。
- UPG-037 只计划重打 v0.5.2；不修改已验证的 `v0.5.1u2` 和 `runner v0.3.1` 核心链路包。
- UPG-037 详细执行边界已补充：前端容错只限升级相关轮询，5 分钟后必须显示原始错误或 `Internal Server Error`；后端 verification runner fallback 只用于展示，不能放宽 runner_protocol 预检查。
- UPG-037 验证要求：在 `10.20.11.3` 恢复 `v0.5.1 + runner v0.3.0` 后重新走正常链路，失败时先记录根因并停止，不继续静默修复。
- UPG-038 已记录到专项升级文档：v0.5.2 `filesystem.prepare` 不能只用“目标 smartx.db 存在”判断数据有效；必须比较旧库/目标库业务计数，空目标库可被旧业务库替换，双业务库冲突必须硬失败，cleanup 必须在数据迁移有效后才能删除旧目录。
- [已通过] runner 组件升级 start 返回 HTTP 200，不再出现“任务已成功但 API 返回 409”的假失败。
- [已通过] 最终健康：`version=v0.5.2`、`runner_version=v0.3.1`、`prometheus=true`。
- [已通过] `upgrade.verification.latest_package` 指向真实 v0.5.2 平台任务 `upgrade-f3e7160e4397acf0`，SHA 非空且不是 post-cleanup。
- [已通过] 旧 network 和 legacy 目录已清理，目标目录均存在。
- [已通过] release smoke：`critical_count=0`、`warning_count=0`。
- [未通过] UPG-038 链路复测：
  - `v0.5.1u2=upgrade-0d944fd29242c0fb`
  - `runner=upgrade-b3b5f205f14f451b`
  - `v0.5.2=upgrade-c5510018291d4656`
  - `post-cleanup=post-cleanup-upgrade-c5510018291d4656`
  - health/version/docker/project/network 均达到目标，但目标 DB `/data/smartx-storage-forecast/app/smartx.db` 只有 96K，`towers=0`、`clusters=0`、`vm_latest=0`、`vm_volumes=0`。
  - v0.5.2 task checkpoint 显示 `copied_app_sources=[]`，post-cleanup 随后删除旧 `/data/smartx-capacity-insight-data`。
  - 下一步：修复 runner v0.3.1 `filesystem.prepare` 数据迁移策略和 v0.5.2 cleanup 门禁，重打 runner/v0.5.2 包，在 `10.20.11.3` 重新完整链路验证。
- [未通过] UPG-038 follow-up 链路复测：
  - `v0.5.1u2=upgrade-60dd4ec8163e1df0`
  - `runner=upgrade-a272344cdbf0ed85`
  - `v0.5.2=upgrade-14d79d309b95ff76`
  - `post-cleanup=post-cleanup-upgrade-14d79d309b95ff76`
  - v0.5.2 主任务成功，最终业务库实际已迁移到 host `/data/smartx-storage-forecast/app/smartx.db`，计数为 `towers=1`、`clusters=1`、`vm_latest=523`、`vm_volumes=89530`。
  - post-cleanup 失败原因不是数据未迁移，而是 target runner 容器内路径视角变化：host `/data/smartx-storage-forecast/app` 挂载为容器 `/data`，cleanup guard 仍按 host 路径 `/data/smartx-storage-forecast/app/smartx.db` 检查目标库，并把容器 `/data/smartx.db` 误当 legacy 库。
  - 已由 UPG-039 修复：runner v0.3.1 `data_migration_guard` 会把 host target DB 映射到容器 `/data/smartx.db`，解析后等于 target 的 legacy 路径会剔除，避免误判。
- [已通过] UPG-039 完整链路复测：
  - `v0.5.1u2=upgrade-528d1f42aa5b62dd`
  - `runner=upgrade-4b1c542232cce245`
  - `v0.5.2=upgrade-37fbd66390f39880`
  - `post-cleanup=post-cleanup-upgrade-37fbd66390f39880`
  - 最终健康：`version=v0.5.2`、`runner_version=v0.3.1`、`checks.prometheus=true`。
  - 最终业务库：`/data/smartx-storage-forecast/app/smartx.db`，`users=1`、`towers=1`、`clusters=1`、`collection_runs=37`、`vm_latest=523`、`vm_volumes=89530`。
  - 旧目录 `/opt/smartx-storage-forecast`、`/data/smartx-capacity-insight-data`、`/data/upgrades`、`/data/backups`、`/data/exports`、`/data/compose-runtime`、`/prometheus-data` 均已清理。
- [已通过] UPG-040 空业务库完整链路复测：
  - 修复 post-cleanup 对空来源业务库的误拦截：仅当父任务 `filesystem.prepare.source_db_counts` 明确无业务数据且 target DB 有效时，才以 `parent_source_had_no_business_data` 放行。
  - 10.20.11.3 空业务库链路：`upgrade-891334c5ac85007b -> upgrade-52f6c7c53b89ad53 -> upgrade-a3734551cbbaff02`，post-cleanup success。
  - 10.20.11.12 空业务库链路：`upgrade-79cae85f494677a2 -> upgrade-3ec9762ff81c5101 -> upgrade-5a22d9f11248f7f3`，post-cleanup success。
  - 最终两台机器均为 `v0.5.2 + runner v0.3.1 + prometheus=true`；legacy `/opt`、`/data/*` runtime、`/data/smartx-capacity-insight-data`、`/prometheus-data` 均已清理。

## 当前执行项 - UPG-031 / fix20

状态：已在 `10.20.11.3` 完整链路验证通过。

目标：

- 解决 fix19 链路中 `target_app_residual_paths` 删除 final runtime 活动挂载点的问题。
- `target_app_residual_paths` 不再生成；旧包传入这些路径时 runner 必须识别并跳过活动挂载点。
- 生成并验证：
  - `v0.5.1u2-fix20-skip-active-target-mountpoints`
  - `runner-v0.3.1-postcleanupfix7-skip-active-target-mountpoints`
  - `v0.5.2-postcleanupfix7-skip-active-target-mountpoints`

已完成：

- v0.5.2 manifest 的 `legacy_cleanup.target_app_residual_paths` 改为空列表。
- runner cleanup 对 `/data/smartx-storage-forecast/app/upgrades`、`app/backups`、`app/exports`、`app/compose-runtime` 这类 final runtime mountpoint 返回 skipped。
- 本地 123 个升级相关单测通过。
- `10.20.11.3` 远端 123 个升级相关单测通过。
- 已生成并静态验证三个候选包：
  - `v0.5.1u2-fix20-skip-active-target-mountpoints`
  - `runner-v0.3.1-postcleanupfix7-skip-active-target-mountpoints`
  - `v0.5.2-postcleanupfix7-skip-active-target-mountpoints`
- 完整链路已通过：
  `v0.5.1 + runner v0.3.0 -> v0.5.1u2-fix20 -> runner-v0.3.1-postcleanupfix7 -> v0.5.2-postcleanupfix7`
- post-cleanup 成功，旧 `/opt/smartx-storage-forecast` 和 legacy `/data/upgrades`、`/data/backups`、`/data/exports`、`/data/compose-runtime`、`/data/smartx-capacity-insight-data`、`/prometheus-data` 均已清理。

验收：

- [已通过] `10.20.11.3` 完整链路：
  `v0.5.1 + runner v0.3.0 -> v0.5.1u2-fix20 -> runner-v0.3.1-postcleanupfix7 -> v0.5.2-postcleanupfix7`
- [已通过] 主 v0.5.2 task 和 post-cleanup task 都保留在 `/data/smartx-storage-forecast/upgrades`。
- [已通过] 旧宿主机路径清理成功或明确显示 missing。
- [已通过] 最终健康：`version=v0.5.2`、`runner_version=v0.3.1`、`prometheus=true`。

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

在 `10.20.11.3:/data/smartx-storage-forecast/project` 执行：

```bash
git status --short --branch
git diff --check
docker compose --project-name smartx-storage-forecast exec -T web-api sh -lc \
  'cd /data/smartx-storage-forecast/project && PYTHONPATH=backend python -m unittest backend.tests.test_v2_reports backend.tests.test_v2_inventory_metrics backend.tests.test_v2_collection backend.tests.test_v2_dashboard_vm backend.tests.test_v2_migration backend.tests.test_v2_upgrade backend.tests.test_v2_package_builders'
docker run --rm -v /data/smartx-storage-forecast/project/frontend:/src:ro -w /tmp node:22-alpine sh -lc \
  'cp -a /src ./frontend-test && cd frontend-test && npm install --no-audit --no-fund && npm test -- --run AppLayout.test.tsx DashboardPage.test.tsx global.test.ts ServicePage.test.tsx'
curl -fsS http://127.0.0.1:8000/api/system/health
curl -fsSI http://127.0.0.1:8080 | head -n 1
curl -fsS http://127.0.0.1:9090/-/healthy
```

## 注意事项

- v2 实现可以先在本地 worktree 修改，再推送 `dev2`，最后在 `10.20.11.3` 拉取并验证。
- 不要在本机运行应用验证，除非用户明确要求。
- 不要回滚用户或其他会话留下的未提交改动。
- 修改文档时不要写入密码、私钥、token。
- 数据相关功能需要同时关注 SQLite 业务库和 Prometheus 历史指标。

### Phase 5 - 版本治理

状态：完成

目标：

- 平台版本统一为 `v0.5.2`。
- 平台三件套为 `web-api`、`collector-worker`、`frontend`。
- `upgrade-runner` 作为独立组件，版本为 `v0.3.1`。
- 平台升级包不包含 `upgrade-runner`。
- runner 只通过组件升级包和 runner 专用 GitHub Actions 构建。
- 每次版本提交必须更新 `docs/releases/CHANGELOG.md` 和相关版本治理文档。
- 后续版本治理作为长期规则执行：版本号、compose tag、升级包 manifest、DockerHub tag、changelog、验证记录必须保持一致。

待办：

- [已完成] 拆分 `SMARTX_IMAGE_TAG` 和 `SMARTX_RUNNER_IMAGE_TAG`。
- [已完成] 更新平台版本元数据到 `v0.5.2`。
- [已完成] 移除平台升级包中的 runner 镜像。
- [已完成] runner 组件包默认读取 `RUNNER_VERSION`。
- [已完成] GitHub Actions 拆分平台和 runner 构建。
- [已完成] 文档增加 DockerHub 错误 tag 清理方法。
- [已完成] 后端镜像内置 `VERSION` 和 `RUNNER_VERSION`，运行时优先读取镜像内版本文件。
- [已完成] 部署文档修正离线部署默认 tag，不再描述为 `latest`。
- [已完成] 本地验证后提交并推送到 `dev2`。

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

状态：完成风险链路增强版

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

- 后端 `UpgradeService.cancel()` 支持处理“任务表中存在 pending 记录，但 `/data/smartx-storage-forecast/upgrades/<task_id>/task.json` 已不存在”的孤儿升级任务；这类任务可被标记为 `cancelled`，不再永久挂在 pending。
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

- 如果任务中心仍出现历史升级任务，先查 SQLite `tasks` 表，不要只看 `/data/smartx-storage-forecast/upgrades` 目录。
- 任务中心状态来源有两层：SQLite `tasks` 表用于全局任务中心，`/data/smartx-storage-forecast/upgrades/<task_id>/task.json` 用于升级包历史和升级任务详情；二者可能因测试或旧逻辑产生不一致。
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
- Word 导出已恢复接近 v1 的客户交付版式：封面品牌条、英文副标题、页眉页脚、Word 原生目录、KPI 摘要卡片、容量风险摘要、集群建议、集群趋势图和 Top 10 VM 增长图。
- Word VM 表格排序列已用 `增长量 ↓` / `增长率 ↓` 标识。
- Word 集群章节 TOP100 已合并统计窗口增长 VM 和月增长 VM，避免 TOP100 因单一口径不完整。
- Word 目录已补充小标题，覆盖报告摘要、集群概览、统计窗口 VM、Top 10 VM 和 TOP100 表格。
- Word 目录已切换为 Word 原生 TOC 域：正文使用真实 `Heading 1/2/3`，并在 `settings.xml` 开启打开文档时更新目录。
- Word 已参考客户版模板补充执行摘要、关键发现、容量风险评估矩阵和短/中/长期运维建议。
- Word VM/集群表格已改为直接参考客户版模板表格风格：深蓝表头、浅色摘要/斑马纹、增长量蓝色、增长率橙/红色；同时保留 v2 图表、v2 数据口径和虚拟机数量。
- 运维建议采用本地确定性规则模板生成，不接入 AI：规则基于集群使用率、预计耗尽天数、Top 增长 VM、单 VM 容量和增长率等字段。
- Word 客户版模板二次优化已进入实施：封面项目名统一为 `存储容量预测平台`，不再使用官方平台表述；字体统一为开源 `Noto Serif` / `Noto Serif CJK SC`；封面增加空白 `客户名称` 字段，范围改为 `Tower范围` / `集群范围`，多 Tower/多集群显示聚合范围；统计窗口按选择窗口与实际采集窗口交集显示；关键发现和运维建议中的 VM 名称前后只保留 1 个空格并加粗放大，容量值、增长值、百分比和天数只加粗放大不额外加空格；`2.2` 增加 Tower 列；`2.3` 改为 DOCX 纯文本块容量使用率可视化，用 `█/░` 展示当前使用率、90 天预测使用率和容量阈值；风险矩阵去掉 `单 VM 容量异常`，改为更中性的 `重点 VM 容量`。
- Word 客户版模板第三轮口径修正已完成：执行摘要和 `2.2` 不再使用 `较上月/较上季度/较上一年` 这类自然周期标签，改为 `统计窗口增长`、`近 90 天样本增长`、`近 365 天样本增长`；范围基本信息补充 `Tower数量`，多 Tower/多集群时显示聚合范围；正文叙述中的 Tower/集群范围名称加粗放大。
- 报表导出 6 种时间区间 Profile 化已完成第一版：后端新增 `7/14/30/90/180/365` 六个 Profile，统一驱动 Word 和 Excel 的窗口名称、增长指标标题、VM 榜单标题、样本不足说明和运维建议短期标题；选择窗口大于实际采集历史时，继续按选择窗口与实际采集窗口交集显示统计窗口。
- Excel 客户版模板化已完成第一版：使用用户提供的 `存储容量预测分析报表_客户版.xlsx` 作为样式母版，后端导出时加载模板并填充 v2 数据；保留现有 API、bundle 任务和下载路径，不再从空 Workbook 手搓客户版样式。
- Excel 模板化保留核心 Sheet：`封面`、`执行摘要`、`容量趋势`、`VM增长TOP100`、`日增长详情`、`本日新建VM`、`本月新建VM` 和每集群独立 Sheet。
- Excel Sheet 精简已落地：删除 `目录`、`范围明细`、`集群汇总`、`VM_TOP100_汇总`，每集群独立 Sheet 改为 TOP100 风格，并统一使用 `GiB/TiB/%/天` 可读文本，避免 raw bytes、`########` 和科学计数法。

后续增强：

- [已解决] Word 章节重排：`一  执行摘要` 改为 `一  摘要`；封面后第二页插入目录；`三`、`四` 按集群拆分汇报并在目录中按集群列出；`五` 改为所有集群汇总报告，承载全局风险矩阵、全局运维建议和声明。
- [已解决] Word 原生目录：五个主章节使用 `Heading 1`，集群章节使用 `Heading 2`，集群内 TOP 表标题使用 `Heading 3`；目录页使用 `TOC \\o "1-3" \\h \\z \\u`，打开 Word/WPS 时自动更新目录。
- [已解决] Word 封面窗口口径拆分：`统计窗口` 显示实际可用采集窗口，`本报表统计窗口` 显示用户选择的导出窗口，例如 `近 90 天（2026-03-11 - 2026-06-09）`。
- Excel 后续可继续精修图表和打印版式；当前“模板母版 + 数据填充”第一版已完成，并已在 `10.20.11.3` 真实导出验证。
- 如果后续引入 AI，可作为可选增强层，仅用于改写建议措辞；基础报告必须保持离线规则可用。
- Profile 默认口径：`7d` 强调短期突增、本日新建 VM 和日增长来源；`14d` 强调近两周增长变化；`30d` 强调月度运营窗口、容量增长和 VM TOP；`90d` 强调季度趋势、预测可信度和容量风险；`180d` 强调中长期增长趋势和容量治理；`365d` 强调年度容量规划，采集不足一年时明确说明按可用样本窗口计算。

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
- Dashboard API `capacity_risk.top_clusters[]` 已附加 `top_growth_vms`，复用日增长最快 VM 口径，每个风险集群最多返回 3 台主要增长 VM。
- 首页底部“风险提示”已增强为风险摘要面板：顶部容量风险小卡仍跳风险集群报表，底部面板额外展示“查看风险报表”和“主要增长 VM”，点击 VM 可直接进入虚拟机页面。

后续增强：

- 后续可继续补充预计耗尽时间、7 天平均增长速率和更详细的 VM 增长解释，但“从风险集群直接定位主要增长 VM”的链路已完成。
- [待办] 预计存储耗尽算法增强：区分长期趋势预测和单日大数据量冲击，避免一次性迁入/突增导致耗尽天数突然大幅缩短后被误读为持续风险。建议同时展示 30/90 天平滑趋势、近 24 小时异常增长提示，以及排除单日突增后的稳健预测口径。

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
- 文档记录当前版本边界：平台 `v0.5.2`、runner `v0.3.1`、Prometheus `v2.55.1`、分支 `dev2`。

### Phase 17 - dev2 受控重建

状态：完成第一版

目标：

- 在 `dev2` 上进行 v2 全新重写，但保留 v1 信息架构和核心功能口径。
- v2 不兼容旧升级路径；升级中心、组件升级和 Prometheus 升级重新设计。
- v2 必须兼容 v1 现场数据迁入，尤其是 SQLite 业务数据、Prometheus 历史指标和旧 VM 卷 payload。
- 控制部署复杂度，默认保持 5 个容器：`frontend`、`web-api`、`collector-worker`、`prometheus`、`upgrade-runner`。
- v2 后续构建、部署和现场验证可以使用 `10.20.11.3`，远端仓库必须切换到 `dev2` 分支。
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
- 只在 `dev2` 上推进，不影响 `dev/main`。
- 在 `10.20.11.3` 执行 v2 验证前，先确认远端仓库位于 `dev2`。
- 不提交 `.env`、SQLite、Prometheus 数据、Tower 凭据、升级包、迁移包、备份包。

最新验证摘要：

- 历史验证记录：平台版本曾切换为 `v0.5.2`，runner 组件版本曾为 `v0.3.0`；当前 `v0.5.2` 正式升级包需要 `runner v0.3.1`。
- `10.20.11.3:/data/smartx-storage-forecast/project` 已在 `dev2` 构建并启动五个容器。
- 历史健康接口曾返回 `version=v0.5.2`、`runner_version=v0.3.0`；当前待升级验证应以 `runner_version=v0.3.1` 为准。
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
- [已解决] SQLite 备份清理第一版：空间清理页在“SQLite 清理并整理”下方新增独立框体，可扫描 `/data/smartx-storage-forecast/backups` 顶层 SQLite 数据库备份，勾选后删除；不会清理升级前备份、导入前备份、Prometheus 备份或 `.tar.gz` 文件。
- [已解决] 升级中心 v2 后续增强文档补齐：`docs/v2-upgrade-center-design.md` 已补 manifest 组件声明、执行边界、组合升级顺序、Prometheus 回归和失败恢复策略。

### Phase 21 - Excel 客户模板固化

状态：已同步测试机并通过回归验证

- 以用户确认的 `storage-forecast-optimized_1.xlsx` 为唯一 Excel 版式基准。
- 固化 Sheet 顺序、列宽、行高、合并范围、冻结窗格和开源字体。
- 模板文件不得保存现场 Tower、集群、VM 或容量数据；运行时只填充实时数据。
- 每个集群 Sheet 从统一集群模板生成，避免多集群导出时格式漂移。
- [已完成] 摘要 KPI 表第 1、3 行改为黑色粗体。
- [已完成] 日增长详情标题合并 `A1:I1`。
- [已完成] 新增独立月增长详情 Sheet，复用日增长详情布局并读取月增长 VM 数据。

### Phase 22 - 升级任务跨重启恢复

状态：已完成，测试机故障注入验证通过

优先级：P0

目标：

- 平台升级、Prometheus 升级和 runner 组件升级在 `web-api`、`upgrade-runner` 或宿主机意外重启后，不再永久停留在 `pending/running`。
- 升级步骤具备持久化检查点、执行器心跳、任务租约、幂等恢复、人工接管和回滚能力。
- `runner v0.3.0` 已作为通用升级协议基线；本次 `v0.5.2` 新增 Compose project/network 迁移能力，发布 `runner v0.3.1`。
- 普通平台代码、镜像、Compose 配置和常规迁移升级不要求先升级 runner；只有升级包需要 runner 未提供的新能力时，才要求先升级 runner。

实施边界：

- Phase 18、Phase 19、Phase 20、Phase 21 均为已完成项，不再阻塞 Phase 22。
- Phase 22 第一版只治理升级中心任务，不扩展到报表导出、数据迁移或空间清理任务。
- 对结果不明确且重复执行可能产生风险的步骤，默认暂停并等待人工选择“继续执行 / 执行回滚 / 标记失败”，不盲目自动重试。
- runner 与平台升级业务解耦：runner 不再直接依赖平台 `UpgradeService` 的具体步骤实现，只执行稳定、版本化的升级任务协议。

核心设计：

- `task.json` 持久化每个步骤的 `status`、`attempt`、`started_at`、`finished_at`、`checkpoint`、`result` 和错误信息。
- runner 持久化 `executor_id`、`lease_owner`、`lease_expires_at`、`heartbeat_at`，避免多个 runner 重复接管同一任务。
- runner 启动时扫描 `pending/running/runner_restarting/recovery_required` 任务，并与 SQLite `tasks` 表进行对账。
- 已确认成功的步骤直接跳过；备份、镜像加载、override 写入和健康检查按幂等规则恢复。
- 服务重启步骤通过实际镜像、容器创建时间、运行状态、版本接口和健康检查判断结果，不仅依赖进程退出码。
- 项目文件迁移、数据库迁移等无法可靠判断结果的步骤进入 `recovery_required`，由任务中心提供人工恢复操作。
- 恢复失败或健康检查失败时生成 `critical` 严重告警，并允许使用升级前备份与旧 override 执行回滚。
- runner 暴露稳定的 `protocol_version` 和 `capabilities`，例如备份、镜像加载、白名单文件同步、Compose override、服务重建、HTTP/Prometheus 健康检查、受控迁移脚本、回滚和断点恢复。
- 平台升级包声明 `minimum_runner_protocol` 和 `required_capabilities`；预检查按能力匹配，不因普通平台版本变化而要求升级 runner。
- 升级步骤由平台升级包和 manifest 描述，runner 只提供通用原子动作、状态机和安全边界，避免每次增加平台步骤都重建 runner。

runner 发布策略：

1. `runner v0.3.0` 提供通用协议、能力协商、检查点、租约和恢复状态机基线。
2. 普通平台功能升级不要求跟随升级 runner。
3. 只有出现旧 runner 无法表达的新原子能力、Docker/Compose 接口变化、安全修复或容器拓扑变化时，才发布新的 runner 组件版本。
4. `runner v0.3.1` 仅为 `v0.5.2` 的 Compose project/network 迁移新增 `compose.project_migrate.v1`。
5. 新 runner 必须保持旧协议兼容；平台包在确实需要新能力时才通过 `required_capabilities` 阻止旧 runner 执行。

计划测试：

- 在备份、镜像加载、项目文件同步、override 写入、服务重启和健康检查各阶段分别强制重启 runner，验证恢复结果。
- 在平台服务重启期间重启 `web-api`，确认任务中心状态、日志、进度和告警不会丢失或重复。
- 模拟两个 runner 同时发现同一任务，验证任务租约只允许一个执行器获得所有权。
- 模拟 SQLite 与 `task.json` 状态不一致，验证对账规则不会把已失败任务重新执行。
- 验证当前测试环境先安装 `runner v0.3.1`，随后执行需要 `compose.project_migrate.v1` 的 `v0.5.2` 平台升级包。
- 使用多个后续平台模拟版本验证均无需升级 runner；仅当升级包声明未知 capability 时才阻止执行并提示升级 runner。
- 验证 Phase 22 平台失败后仍可回滚到上一平台版本，且 `runner v0.3.1` 继续兼容旧平台升级任务。

当前实施进度：

- [已实现] 独立 `upgrade_protocol` 与 `upgrade_runner`，Runner 不再导入平台 `UpgradeService`。
- [已实现] schema 3、协议版本、能力协商、包内 checksums 校验和 manifest 编译器。
- [已实现] task.json 原子写入、revision、Runner 心跳、SQLite 租约与安全接管。
- [已实现] 标准 Action、迁移脚本沙箱、分级恢复、人工继续/回滚/失败 API 和自动回滚一次。
- [已实现] 前端恢复控制面和 Runner 协议/能力/心跳展示。
- [已实现] 平台、Runner、Prometheus 与平台+观测组合包构建器，统一 schema 3 和 `checksums.sha256`。
- [已实现] Prometheus 组件包默认轻量化，不导出历史指标，不强制包含 `prometheus.tar`；离线环境才通过 `--offline-image` 携带镜像 tar。
- [已明确] 平台/组件升级只做升级前本机备份用于回滚；Prometheus 历史数据导出/导入只属于完整数据迁移包。
- [已完成] 升级相关 Markdown 统一更新：README 中英文、架构、部署、功能模块、版本治理和升级问题文档均对齐平台 `v0.5.2`、Runner `v0.3.1`、schema 3、四类升级包树形结构和 Prometheus 数据边界。
- [已实现] 沙箱宿主机路径映射；回滚删除升级新增文件并 recreate 原版本服务。
- [已实现] SQLite WAL 一致性快照、按作用域恢复 SQLite/Prometheus、回滚后健康复检和健康检查重试窗口。
- [已实现] web-api 与 Runner 对 `task.json` 使用 revision 乐观并发控制，陈旧恢复操作返回 409。
- [已验证] `10.20.11.3` 完成容器构建、Runner 重启接管、安全动作恢复、脚本中断受控暂停、实际沙箱执行、自动回滚单测和恢复界面回归。

### Phase 23 - v0.5.0 稳定化收敛

状态：已完成

优先级：P0

目标：

- 冻结 `v0.5.0` 功能面，不再插入新的升级能力或大 UI 需求，只处理发布阻塞问题。
- 把升级中心从“功能继续扩张”切换到“主路径稳定验收”，确保测试机和正式包都能稳定完成部署、升级、回滚和任务中心展示。
- 用户继续提出业务需求；架构与版本节奏由 Codex 收束到明确 Phase，避免需求直接打穿当前发布线。

版本边界：

- `v0.5.0`：稳定首发版，目标是可部署、可升级、可导出、可迁移。
- 当前正式口径固定为 `v0.5.2`；源码 `VERSION`、README、文档、正式升级包和常规镜像 tag 必须保持一致。
- `v0.5.4`、`v0.5.5` 等只作为测试升级包目标版本时，不代表正式版本变化，不能反向修改源码版本和对外文档。
- 后续报表交付质量、数据迁移与清理增强等需求继续进入新 Phase 排期；是否形成正式新版本由发布前统一决定。

实施边界：

- 不新增 Runner capability。
- 不改变升级包 schema 3 的外部兼容口径。
- 不触碰 `10.20.11.12`；只在 `10.20.11.3` 做测试机验证。
- 不把历史 Prometheus 数据放入平台/组件升级包。
- 不为了清理显示问题手工修改业务库作为长期方案；允许用一次性脚本整理测试机历史故障注入数据，但必须记录并可复现。

待修复问题：

- [已完成] Runner 自升级完成后，`task.json` 顶层已为 `success`，但 `steps.restart` 仍为 `running`、`steps.healthcheck` 仍为 `pending`，导致前端看起来像任务 hang 住。
- [已完成] 统一升级任务状态投影第一步：`task.json` 是执行权威，runner-only 无 execution plan 任务投影时使用 task 自带 steps，避免 SQLite 与 task file 步骤不一致。
- [已完成] 为 runner 自升级恢复收尾增加回归测试，覆盖 `runner_restarting + runner_resume_pending + no execution_plan`。
- [已完成] 增加 `v0.5.0` 升级中心固定验收脚本，覆盖版本健康、Runner 心跳/能力、成功任务 steps 一致性和 `v0.5.0` 平台包无迁移 payload。
- [已完成] 用固定验收脚本驱动平台包、Runner 组件包、Prometheus 轻量包三条真实升级主路径回归。
- [已完成] 修复 Runner 组件升级 runtime override 未显式覆盖旧入口的问题，避免新镜像仍按 `app.upgrade.runner` 旧模块启动失败。
- [已完成] Runner/web-api 成功终态统一写入 `finished_at`，避免 `task.json` 作为权威记录缺少完成时间。
- [已完成] 使用产品 API 标记信息类任务已读并清空 clearable 历史任务，隔离 `10.20.11.3` 历史故障注入任务对任务中心的干扰。

验收标准：

- 平台升级、Runner 组件升级、Prometheus 轻量组件升级三条主路径均能结束为一致的 `success/failed/recovery_required` 状态。
- 任何 `success` 升级任务的 steps 不得存在 `running/pending`。
- 任务中心角标与未处理通知一致，确认告警不改变排序位置。
- 历史 v0.5.0 基线验证：`/api/system/health` 返回 `version=v0.5.0`、`runner_version=v0.3.0`，前端 8080 与 Prometheus healthy 返回 200。
- 固定验收脚本和目标单测通过后，才允许提交并推送 `dev2`。

测试升级包记录：

- [已完成] 在 `10.20.11.3` 临时构建 `v0.5.4` 与 `v0.5.5` 测试升级包，只用于验证升级链路。
- [已完成] 两个测试包均确认 `schema_version=3`、`min_version=v0.5.0`、`database_migration=false`，不包含 `migration`、`migration_steps` 或 `migrations/`。
- [已明确] 测试包目标版本不改变当前正式平台版本，正式版本仍以根目录 `VERSION` 为准。

### Phase 24 - 采集重试、部分成功与趋势缺采标记

状态：已实现，待用户体验验证

优先级：P0

目标：

- 定时采集失败后，只重试失败 Tower/集群；默认每 15 分钟重试一次，最多额外重试 3 次。
- 任一启用 Tower/集群获取失败都算采集异常，任务中心生成普通告警 `Tower/集群采集异常`。
- 部分成功时，成功 Tower/集群仍写入 SQLite 当前态和 Prometheus；失败目标不写新样本、不伪造旧值。
- 虚拟机趋势图识别缺采日期，不补 0、不复制旧值，并在页面显示 `非最新` 与缺采提示。

当前实施进度：

- [已实现] Tower 新增采集重试配置：`collection_retry_enabled`、`collection_retry_interval_minutes`、`collection_retry_max_attempts`，旧库默认回填 `true/15/3`。
- [已实现] `collection_runs` 扩展触发来源、周期、尝试次数、成功目标、失败目标和已发布 metrics 目标。
- [已实现] 采集服务改为目标级 try/catch；单个集群失败不会丢弃其他成功集群。
- [已实现] `metric_snapshots` 只保存本周期成功目标生成的 metrics，失败目标不进入本周期 `/metrics`。
- [已实现] 重试入口支持 `target_filter`，worker 定时采集失败后只对失败目标进行有限重试。
- [已实现] 采集异常进入任务中心 warning，标题固定为 `Tower/集群采集异常`，错误信息脱敏。
- [已实现] VM 趋势接口返回 `latest_success_at`、`latest_collection_status`、`has_collection_gap`、`gap_dates`、`data_freshness`。
- [已实现] 虚拟机页面显示 `非最新` 和缺采日期提示；趋势图插入 null 断点，避免跨缺采日连线。

待验证：

- [已完成] 前端 TypeScript build 和目标测试已在远端容器环境执行。
- [已完成] 远端 `10.20.11.3` 已执行后端目标测试、前端 build、健康检查、空间清理按钮扫描和报表导出主流程抽检。

### Phase 25 - 平台自检与升级后验收

状态：已撤销

优先级：P0

背景：

- v2 已进入 `v0.5.0` 稳定线，继续堆大功能的收益低于提高现场可诊断能力。
- 当前很多验收依赖人工 curl、容器测试和页面抽检；升级、采集、Prometheus、报表和清理链路一旦出问题，需要更快定位是服务、数据、采集、任务还是报表生成问题。
- Phase 25 曾计划把“平台是否健康、数据是否可信、升级后是否可用”固化为产品化自检能力。

撤销决定：

- 用户确认该平台级自检功能太重，会把采集失败、数据一致性、趋势缺采、任务中心告警等关联问题拆成多块 critical/warning，现场观感复杂。
- 已移除服务管理页 `平台自检` 卡片、`/api/admin/system/self-check` API、`scripts/verify_platform.py`、升级后自动 self-check 记录和相关测试。
- 保留轻量报表数据质量说明：报表页和 Word/Excel 继续展示实际采集窗口、缺采日期、样本是否足够和数据不完整集群。
- 平台升级页仍保留版本、升级包、服务运行状态和清理入口。

最终范围：

- 不再提供平台级自检 API、CLI、服务管理页自检面板或升级后自动自检。
- 不再把同一个采集根因拆成多条平台级自检告警。
- 日常运维入口回到现有服务管理页：平台状态、组件状态、升级包、服务运行状态、清理扫描和任务中心。
- 数据可信度只在需要解释结论的地方展示：报表页、Word、Excel，以及数据质量相关任务告警。

撤销验收：

- 代码中不存在 `SelfCheckService`、`/api/admin/system/self-check`、`scripts/verify_platform.py`、`self_check_status/self_check_summary/self_check_finished_at` 的运行逻辑。
- 服务管理页不显示 `平台自检`、`快速自检`、`深度自检` 或 `深度自检并验证报表导出`。
- 升级成功后不再创建 `升级后自检异常` 或 `升级后存在需关注项`。
- 报表数据质量说明继续保留，避免把报表可信度解释能力一并删掉。

### Phase 26 - P1 数据正确性：SQLite/Prometheus 一致性与报表数据质量

状态：已实现并在 `10.20.11.3` 验证

优先级：P1

目标：

- 后台统一检查 SQLite 当前态与 Prometheus 历史/当前样本是否一致，避免页面和报表在数据链路断裂时仍给出看似可靠的结论。
- 报表 API、报表页、Word 和 Excel 导出都展示“数据质量说明”，说明实际采集窗口、缺采天数、样本是否足够、哪些集群数据不完整。
- 数据质量异常只解释可信度并产生告警，不修改 Prometheus、不伪造样本、不改变预测算法和增长榜算法。

当前实施进度：

- [已实现] 新增 `DataQualityService`，按启用 Tower/集群范围比较 SQLite VM/集群数量与 Prometheus 当前 series 数。
- [已实现] 数据一致性规则：最近采集成功但 Prometheus 无样本判 `critical`；VM series 与 SQLite VM 数差异超过 `max(10, 10%)` 判 `warning`；低于 50% 判 `critical`；查询窗口存在 `partial_failed/failed` 记录缺采日期。
- [已实现] 采集完成后执行数据质量检查，任务中心合并生成 `数据一致性异常` 或 `数据质量需关注`，避免重复刷屏。
- [已实现] 数据质量检查结果供任务中心告警、报表 API、报表页和 Word/Excel 导出复用；平台级自检已撤销，不再展示全局自检卡片。
- [已实现] `latest_report()` 返回 `data_quality` 字段，前端报表页兼容显示 `数据质量正常/需关注/异常/未知`。
- [已实现] Word 客户版在“一 摘要”中新增“数据质量说明”，包含本报表统计窗口、实际采集窗口、样本是否足够、缺采天数、数据不完整集群和 SQLite/Prometheus 数量。
- [已实现] Excel 新增 `数据质量说明` Sheet，位于 `执行摘要` 后，保持已删除的目录/范围明细/集群汇总等冗余 Sheet 不恢复。
- [已实现] 文档更新 API 合同、README 中英文和计划文件，说明一致性检查与报表数据质量口径。

待验证：

- [已完成] 在 `10.20.11.3` 容器内运行后端目标测试：`test_v2_data_quality/test_v2_reports/test_v2_report_exports/test_v2_worker`。
- [已完成] 在 `10.20.11.3` Node 容器内运行前端目标测试：`ServicePage.test.tsx ReportsPage.test.tsx` 共 25 个通过。
- [已完成] 重建并 recreate `web-api`、`collector-worker`、`frontend`。
- [已完成] 验证 `/api/system/health` 返回 `ok=true`，frontend `8080` 返回 200，Prometheus `/-/healthy` 返回 healthy。
- [已完成] 真实报表 API 返回 `data_quality.status=critical`，指出 SQLite VM 数 177、Prometheus VM series 数 0、缺采日期和不完整集群；这符合当前测试机数据面异常现状。
- [已完成] 导出 Word/Excel，Word 包含“数据质量说明”和异常提示；Excel Sheet 顺序为 `封面/执行摘要/数据质量说明/容量趋势/...`，`数据质量说明` Sheet 包含 SQLite/Prometheus 数量、缺采天数和不完整集群。

### Phase 27 - 任务中心卡片四区布局与详情可读性

状态：已完成

优先级：P1

目标：

- 固化任务中心卡片 UI：左上为图标和标题，右上为 `确认/X`，左下为详情与进度条，右下为百分比与日期时间。
- 告警任务和普通信息任务都要把百分比和日期时间放在右下角。
- 详情默认显示 2 行，超过 2 行再截断；鼠标悬停和无障碍文本保留完整详情。
- 不新增展开/收起按钮，避免任务中心卡片高度和滚动行为继续复杂化。

实施项：

- [已实现] 任务卡片结构改为 `header controls / body actions` 四区布局。
- [已实现] `.task-menu-actions` 右下对齐：使用 `align-self: stretch` 和 `justify-content: flex-end`，告警任务和普通信息任务的百分比/日期时间均固定在右下角。
- [已实现] `.task-menu-detail` 使用两行 line clamp，移除详情的一行强制省略。
- [已实现] 详情节点增加 `aria-label`，与 `title` 一样保存完整详情。
- [已实现] 步骤列表和日志列表每行增加完整 `title/aria-label`，解决下面框内截断后悬停没有完整提示的问题。
- [已实现] 任务菜单宽度从 520px 收敛到 480px，保留四区布局和右侧时间/进度可读性。
- [已完成] 所有测试和重建均在 `10.20.11.3` 执行：`AppLayout.test.tsx` 19 个测试通过，frontend 已重建并 recreate，`http://127.0.0.1:8080` 返回 200。

### Phase 28 - 报表页顶部右侧紧凑信息栈

状态：已完成

优先级：P1

目标：

- 将报表页顶部从“三列等高卡片”改为“左侧预测报表 + 右侧紧凑信息栈”。
- 右侧信息栈包含 `历史样本窗口`、`容量增长速率`、`数据质量摘要`。
- 将数据质量信息从左侧预测报表卡片中移到右侧，避免左侧报表卡把右侧 KPI 卡片拉得过高。

实施项：

- [已实现] `.report-top-row` 改为两列，右侧新增 `.report-side-stack`。
- [已实现] 历史样本窗口和容量增长速率改为右侧紧凑卡片，高度约 132px。
- [已实现] 数据质量摘要改为右侧紧凑纵向卡片，只显示核心状态、窗口、缺采、样本和不完整集群。
- [已实现] 更新 `ReportsPage.test.tsx` 覆盖右侧摘要、左侧不再显示数据质量卡片和 Tower 前缀不再出现。
- [已完成] 在 `10.20.11.3` 跑报表页前端测试，重建并 recreate frontend，验证 8080 和健康接口。

### Phase 29 - 生产等价测试环境与发布验收门禁

状态：规划中

优先级：P0

背景：

- `10.20.0.6` 生产类环境暴露了报表日增长虚拟机名称缺失问题，但 `10.20.11.3` 和 `10.20.11.12` 测试环境没有提前暴露。
- 根因不是单一代码错误，而是测试环境和发布流程没有强制验证“最终 tag 镜像 + 干净部署 + 真实 API 数据契约”。
- 后续必须把测试环境分层，明确哪些环境允许脏调试，哪些环境必须像生产一样不可热修、不可本地构建、不可用未发布镜像。

目标：

- 建立三类环境职责，避免调试环境、升级演练环境和发布验收环境混用。
- 发布前必须用最终交付物验收：`main` 分支 tag、Actions/DockerHub 产出的版本镜像、正式部署脚本和固定验收数据。
- 把“页面没报错”升级为“关键业务链路有断言”的验收门禁，尤其覆盖 Dashboard、报表、任务中心、升级中心和采集链路。
- 任何生产热修必须回流到代码、测试和 tag 镜像，不能让生产环境成为唯一验证点。

环境分层：

- `dev/debug`：推荐继续使用 `10.20.11.3`。
  - 允许本地构建、临时补丁、容器内排查、数据污染和快速重建。
  - 用于开发验证和定位问题，不作为发布通过依据。
- `upgrade rehearsal`：推荐继续使用 `10.20.11.12`。
  - 用于 `v0.5.0 -> v0.5.1` 这类升级包演练。
  - 允许按测试需要重置，但每轮升级前必须记录起始版本、镜像 tag、升级包 sha256 和数据库状态。
  - 不允许把本地热修后的容器当作正式验收通过。
- `release canary`：建议使用独立干净环境，可临时使用 `10.20.0.6`，后续最好固定一台专用主机。
  - 只允许从 DockerHub 拉取正式 tag 镜像。
  - 只允许使用 `main` 分支 tag 对应的源码包、部署脚本和升级包。
  - 禁止直接修改容器内 JS、Python、配置文件；如果必须热修，修完后必须销毁并重新用 tag 镜像部署验证。
  - 验收通过后才允许发布 GitHub Release、交付升级包或通知用户升级。

发布验收流程：

- [ ] `dev2` 合并到 `main` 前，本地和 `10.20.11.3` 目标测试通过。
- [ ] `main` 打正式 tag，例如 `v0.5.2`。
- [ ] GitHub Actions 必须从 `main` 的 tag 构建镜像，镜像 tag 必须与版本号一致。
- [ ] 等待 DockerHub 镜像可拉取，并记录镜像 digest。
- [ ] `release canary` 清理旧容器、旧网络和旧项目文件，只保留需要的应用数据或使用固定验收数据集。
- [ ] `release canary` 通过 DockerHub tag 镜像全新部署。
- [ ] 执行后端 smoke：`/api/system/health`、Tower/集群列表、VM 列表、报表 API、任务列表、Prometheus 健康。
- [ ] 执行前端 smoke：Dashboard 日/月增长、报表日/月增长 TOP、任务中心告警显示、服务管理、升级中心上传/预检查。
- [ ] 执行数据契约验收：报表增长 VM 同时覆盖顶层 `vm_name/vm_id` 和 legacy `labels.vm/labels.vm_id` 两种响应。
- [ ] 执行升级包验收：从最低支持版本升级到当前版本，确认预检查 sha256、步骤进度、回滚材料和最终健康状态。
- [ ] 验收结果写入 `progress.md`，失败项必须修复后重新从 tag 镜像部署验证，不能只在运行环境手工 patch。

固定验收用例：

- Dashboard：
  - 日增长样本不足时显示“样本不足”，不显示空箭头。
  - 月增长不足 30 天时显示“样本不足”；满足 30 天但缺采时显示黄色缺采提示。
  - VM 名称、容量、增长值、趋势断点不出现空白或 `undefined`。
- 报表页：
  - 日增长 TOP 和月增长 TOP 必须显示 VM 名称。
  - 数据质量卡片能显示实际窗口、缺采天数、样本状态和不完整集群。
  - Word/Excel 导出包含数据质量说明。
- 任务中心：
  - 所有任务显示右下角日期时间。
  - 告警确认后不跳回任务中心顶部。
  - 详情截断时有完整 `title/aria-label`。
- 升级中心：
  - 上传完成和预检查后必须显示升级包 sha256。
  - `v0.5.0 -> v0.5.1` 无 schema 迁移时，不包含 migration、migration_steps、script.sandbox.v1 和 `migrations/run_migrations.py`。
  - 有 schema 跨版本升级时，累计 migration step 按版本顺序执行且可幂等跳过。
- 采集链路：
  - 采集失败时创建任务中心任务或告警。
  - 部分集群成功时成功目标写入 SQLite 和 Prometheus，失败目标不伪造新样本。
  - 账号认证失败和连接失败错误文案应可区分。

数据与契约策略：

- 固定一份脱敏验收数据集，至少包含：
  - 1 个 Tower、1 个启用集群、若干 VM。
  - 日增长和月增长 TOP 数据。
  - 缺采日期和样本不足场景。
  - 报表 API 返回顶层 `vm_name/vm_id` 的场景。
  - legacy `labels.vm/labels.vm_id` 的兼容场景。
- 前端测试必须使用契约 fixture，不只 mock 理想结构。
- 后端测试必须覆盖真实 API 返回字段，避免前端和后端各自通过但集成失败。

反污染规则：

- `release canary` 不允许 `docker compose build`。
- `release canary` 不允许编辑容器内静态资源、Python 文件或数据库补丁脚本。
- `release canary` 每次验收必须记录：
  - 平台版本、Runner 版本、镜像 tag、镜像 digest。
  - 部署来源：DockerHub tag 或升级包 sha256。
  - 数据库来源：固定验收数据、升级前数据或全新初始化。
  - 验收人、验收时间和失败项。
- 如果在 canary 上发现问题：
  - 只能临时排查，不把热修状态作为通过。
  - 修复必须提交到 `dev2/main`，重新打 tag 或移动测试 tag 后，再从零部署验收。

交付物：

- [已实现] 新增 `docs/release-acceptance.md`，记录环境矩阵、门禁步骤、固定用例和反污染规则。
- [已实现] 补充前端契约测试：报表增长 VM 名称兼容顶层字段和 legacy labels。
- [已实现] 新增 `scripts/release_smoke_check.py`，提供只读 release canary smoke 检查。
- [已记录] 在 `progress.md` 中记录本轮发布验收体系实现和目标测试结果；正式 canary 部署/升级验收仍需在选定非生产 canary 后执行。

### Phase 30 - Compose Project/Network 固定化与升级链路修复

状态：已实现，待验证

优先级：P0

背景：

- `10.20.0.6` 按常规命令 `docker compose -f docker-compose.offline.yml up -d` 部署后，Docker Compose 默认使用目录名生成 project：`smartx-hci-capacity-insight-main`。
- 程序内 `SMARTX_COMPOSE_PROJECT_NAME` 原先写死为 `smartx-storage-forecast`，导致后端按错误 project label 查询 Docker。
- 直接结果是服务管理页“未读取到服务状态”，平台升级页 Compose 项目显示旧值，观测组件版本显示 `-`。
- 同一配置还会影响升级链路：web-api 预检查、服务状态读取、Runner `compose.apply` 和回滚重启都会依赖 compose project。
- 用户确认更合理的根修复是在所有 Compose 文件里写顶层 `name:`，并固定 Docker network name，让常规 `docker compose up -d` 也天然带稳定 project/network。

目标：

- 用户无需记住 `--project-name`，直接执行 `docker compose -f docker-compose.offline.yml up -d` 也会创建固定 project。
- 固定 Docker network 名称，避免源码目录变化或手动更新时生成新网络导致冲突。
- 服务状态、Prometheus 版本、平台升级、组件升级和回滚都使用同一套 project/network。
- 保留后端“从当前容器 label 反查真实 project”的兜底，兼容历史现场。
- 不再对 `10.20.0.6` 执行任何写操作；生产只允许只读诊断，除非用户明确批准具体命令。

实施项：

- [已实现] 在 `docker-compose.yml`、`docker-compose.offline.yml`、`docker-compose.release.yml` 顶层增加：

```yaml
name: smartx-hci-capacity-insight
```

- [已实现] 三个 Compose 文件中 `web-api` 与 `upgrade-runner` 的环境变量统一为：

```yaml
SMARTX_COMPOSE_PROJECT_NAME: smartx-hci-capacity-insight
```

- [已实现] 三个 Compose 文件中的网络统一为固定真实 Docker network：

```yaml
networks:
  smartx-net:
    name: smartx-hci-capacity-insight-net
    driver: bridge
    ipam:
      config:
        - subnet: 10.249.249.0/24
```

- [已实现] 保持服务内部仍引用逻辑网络名 `smartx-net`，只固定网络真实名称，不改变服务间通信方式。
- [已实现] `SMARTX_PROJECT_PATH` 继续保持容器内路径 `/data/smartx-storage-forecast/project`，因为该路径是容器内挂载点，不等同于宿主机源码目录。
- [已实现] `SMARTX_HOST_PROJECT_PATH` 继续使用 `${PWD}`，保证 Runner 调用 Docker daemon 时能把宿主机源码目录传给 Docker。
- [已实现] 后端 `UpgradeService.verification()` 保留兜底逻辑：若配置 project 查不到服务，则 inspect 当前 `web-api` 容器 label，使用真实 `com.docker.compose.project` 读取服务状态。
- [已实现] `compose.apply` 和 `rollback.restore` 继续显式传 `--project-name context.compose_project`，该值来自统一后的 `SMARTX_COMPOSE_PROJECT_NAME`。
- [已实现] 文档更新：部署文档推荐不带 `--project-name` 的普通命令，显式 `--project-name smartx-hci-capacity-insight` 仅作为兼容旧 Compose 或排障写法。

测试计划：

- [已验证] 配置测试：三个 Compose 文件都包含顶层 `name: smartx-hci-capacity-insight`。
- [已验证] 配置测试：三个 Compose 文件都包含 `SMARTX_COMPOSE_PROJECT_NAME: smartx-hci-capacity-insight`。
- [已验证] 配置测试：三个 Compose 文件都包含 `name: smartx-hci-capacity-insight-net`。
- [已验证] 配置测试：三个 Compose 文件不再包含 `SMARTX_COMPOSE_PROJECT_NAME: smartx-storage-forecast`。
- [已验证] 服务状态测试：project 一致时，`verification.services` 返回 web-api、collector-worker、frontend、prometheus、upgrade-runner。
- [已验证] 服务状态测试：配置 project 与当前容器真实 label 不一致时，后端能从当前容器 label fallback 读取实际服务。
- [已验证] 观测版本测试：Prometheus 镜像为 `prom/prometheus:v2.55.1` 时，`prometheus_version=v2.55.1`。
- [已验证] Runner 测试：`compose.apply` 生成命令必须包含 `--project-name smartx-hci-capacity-insight`。
- [已验证] Runner 测试：`rollback.restore` 的 stop 和 up 命令必须使用同一 project name。
- [ ] 部署验收：在非生产 canary 上进入任意目录名，执行 `docker compose -f docker-compose.offline.yml up -d`，Docker label 必须为 `com.docker.compose.project=smartx-hci-capacity-insight`，网络必须为 `smartx-hci-capacity-insight-net`。
- [ ] 升级验收：执行一次测试升级包，确认不会创建第二套 project 容器或第二个 smartx 网络。

生产/现场处理规则：

- `10.20.0.6` 当前只做只读诊断，不再写文件、不传测试文件、不 recreate 容器。
- 如果后续需要恢复或调整 `10.20.0.6`，必须先列出将执行的命令和 diff，等用户明确确认后再执行。
- 已有现场如果存在旧 project 容器或旧网络，升级前必须人工确认：

```bash
docker ps --format '{{.Names}} {{.Label "com.docker.compose.project"}}'
docker network ls | grep smartx
```

- 如果存在多个 project 同时挂同一数据目录，必须先停旧 project，再按固定 project/network 重新拉起，禁止两个 project 同时管理同一套数据。

### Phase 31 - 报表页容量增长速率算法优化

状态：已规划，待实施

优先级：P1

背景：

- 报表页左侧集群预测使用统计窗口内的集群容量趋势，可以显示长期增长预测。
- 右侧“容量增长速率”当前只使用最近 7 天集群容量首尾差，并且通过 `max(0, value)` 把负增长压成 `0`。
- 在 `10.20.11.3` 当前数据中，近 7 天集群容量略有下降，所以 API 返回 `cluster_growth_rate.per_day=0`，页面显示 `0 B/天`；但 30 天预测趋势仍然为正，用户感知为口径矛盾。
- 用户确认希望优化算法：日增长按当天或最近一天实际速率，容量减少可以显示负数；月/季度增长速率需要更贴近实际预算，不应简单由 7 天值乘出来。

目标：

- 日增长速率反映最近一天真实净变化，允许负数，例如 `-12.30 GiB/天`。
- 月增长速率使用近 30 天趋势，季度增长速率使用近 90 天趋势，分别服务容量预算和趋势判断。
- 月/季度不再直接用日增长乘 `30/90`，也不再沿用最近 7 天首尾差。
- 样本不足时明确提示“样本不足”或“数据不足”，不能把未知或负增长伪装为 `0 B`。
- 不改采集逻辑、不改 Prometheus 写入、不改容量风险算法；本阶段只优化报表增长速率展示和导出说明。

后端实施口径：

- 在 `backend/app/v2/reports/service.py` 中新增统一增长速率计算函数，例如 `cluster_growth_rates_from_series()`。
- `latest_report()` 查询三组集群容量序列：
  - 日窗口：近 1 天，建议 `step="1h"`，用于捕捉最近一天净变化。
  - 月窗口：近 30 天，`step="1d"`。
  - 季度窗口：近 90 天，`step="1d"`。
- 每个启用集群独立计算，最后汇总：
  - 日增长：最近 24 小时窗口内最早点和最新点的差值除以实际间隔天数，允许负数。
  - 月增长：近 30 天趋势斜率乘 30，趋势函数应与现有 `forecast_series()` 口径一致或复用其线性趋势能力。
  - 季度增长：近 90 天趋势斜率乘 90。
- 样本判断：
  - 每个窗口至少需要两个有效点才可计算。
  - 如果某个集群窗口样本不足，该集群不参与该窗口汇总，并记录该窗口 `sample_sufficient=false`。
  - 如果全部启用集群某窗口都不足两点，该窗口值为 `null`，前端显示“数据不足”。
  - 如果有部分集群可计算、部分不足，返回汇总值并带 `sample_sufficient=false`，前端显示“样本不足”提示。
- API 兼容：
  - 保留 `cluster_growth_rate_per_day`，值等于新的 `cluster_growth_rate.per_day`，兼容旧调用。
  - `growth_rate_window_days` 保留但不再作为页面主要口径；新字段为权威。
  - `cluster_growth_rate` 扩展为：

```json
{
  "per_day": -123,
  "per_month": 456,
  "per_quarter": 789,
  "day_sample_sufficient": true,
  "month_sample_sufficient": false,
  "quarter_sample_sufficient": false,
  "day_window_days": 1,
  "month_window_days": 30,
  "quarter_window_days": 90
}
```

前端实施口径：

- 更新 `frontend/src/types.ts` 的 `ForecastPayload.cluster_growth_rate` 类型，增加窗口和样本字段。
- 更新 `ReportsPage` 容量增长速率卡片：
  - 标题保持 `容量增长速率`。
  - 副标题由 `7 天平均` 改为 `日/月/季度趋势`。
  - 三行分别显示：`日：±X/天`、`月：±X/月`、`季度：±X/季度`。
  - 负数必须保留 `-`，不能被格式化成 `0 B`。
  - `null` 显示 `数据不足`。
  - `sample_sufficient=false` 且有数值时，在该行显示黄色 `样本不足` 小提示。
- 前端 fallback：
  - 如果后端只有旧字段，则按旧字段渲染，避免旧 API 报错。
  - 旧字段 fallback 不显示样本提示。

导出和文档实施口径：

- Word/Excel 报表中同步说明增长速率口径：
  - 日：最近一天净变化。
  - 月：近 30 天趋势折算。
  - 季度：近 90 天趋势折算。
- Word/Excel 中负增长使用负数展示。
- 样本不足时保留数值并标注“样本不足”；完全不足时写“数据不足”。
- 更新 `findings.md` 中旧的“容量增长速率当前需求为最近 7 天平均”记录，追加当前新口径，避免后续误读。

测试计划：

- 后端测试：
  - 最近一天容量下降时，`per_day` 返回负数，不再返回 0。
  - 近 1 天下降但近 30 天增长时，日为负、月为正。
  - 近 30 天和近 90 天趋势不同，`per_month` 和 `per_quarter` 分别按各自窗口计算。
  - 单个集群样本不足时，不影响其他集群计算，并返回对应 sample flag。
  - 全部集群窗口不足两点时，返回 `null` 和 `sample_sufficient=false`。
  - 只统计启用 Tower/集群范围，禁用集群和 orphan series 不参与。
- 前端测试：
  - 容量增长速率卡显示日/月/季度三行。
  - 负数显示 `-` 前缀。
  - 样本不足时显示黄色提示。
  - `null` 显示 `数据不足`。
  - 旧 API 只有 `per_day/per_month/per_quarter` 时仍能渲染。
- 导出测试：
  - Word/Excel 包含新口径说明。
  - 负增长和样本不足文案正确。
- 远端验证：
  - 在 `10.20.11.3` 调用 `/api/reports/latest`，确认当前场景日增长可显示负数，月/季度按 30/90 天趋势显示。
  - 重建 `web-api/frontend` 后目视确认报表页不再出现“长期预测增长但速率显示 0”的矛盾。

验收标准：

- 当前 `10.20.11.3` 这种近 7 天下降但 30 天增长的场景，页面应显示日增长为负数、月/季度为趋势值或样本不足提示。
- 任何负增长都不能被后端或前端强行压成 `0 B`。
- 报表页、Word、Excel 对增长速率口径一致。
- 不影响容量风险、VM 日/月增长榜、本日/本月新增 VM、数据质量说明等既有功能。

## 专项升级链路历史任务归档

`v0.5.1 + runner v0.3.0 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2` 的历史 Phase 任务细节已从本文件移出，统一归档到：

```text
docs/v0.5.1-to-v0.5.2-upgrade-chain-task-findings.md
```

后续这条链路的详细修复计划、失败记录、包路径/SHA、任务 ID 和完整链路验证，先写入：

```text
docs/v0.5.1-to-v0.5.2-upgrade-chain-worklog.md
```

等链路全部完成后，再把最终结论、最终包和验收结果摘要回填到本文件。

## UPG-041 v0.5.2 升级后自动采集

状态：实施中。

- [x] 确认根因：UPG-040 包只恢复历史 SQLite/Prometheus 数据，v0.5.2 执行计划没有升级后采集动作。
- [x] 完成设计：runner 写一次性标记，collector-worker 等父升级成功后消费，采集独立进入任务中心。
- [x] 写入设计与详细实施计划。
- [x] TDD 实现 compiler、runner marker、worker consumer 和任务中心状态。
- [x] 重打 v0.5.1u2、runner v0.3.1、v0.5.2 UPG-041 三包。
- [ ] 在 10.20.11.3 从正常业务库执行完整链路：升级主链已成功，自动采集因测试恢复夹具只恢复 DB/Prometheus、未恢复与 DB 配套的旧 `.env` 而失败；先找回并成对恢复旧 `smartx.db + .env`，不得要求重新填写 Tower 凭据。
- [ ] 增加凭据迁移安全门禁：来源库存在加密 Tower 凭据时，目标 `.env` 缺失或密钥不匹配必须中止目录迁移/旧环境清理并给出明确错误，不得静默创建默认密钥。
- [ ] 修正迁移顺序与候选优先级：先确定/迁移业务数据库，再以该数据库验证目标和 legacy `.env`；迁入旧 DB 时不得因目标 `.env` 已存在就无条件保留它。
- [ ] 处理 UPG-042 代码审查阻塞：迁移 `.env` 权限改为 `0600`；异常/不完整 Tower schema fail-closed；无认证 XOR 密文不得用“非空解密结果”作为唯一兼容依据。
- [ ] UPG-043 修复 credential helper 目标 DB host path 映射：`directory_transition.target_root` 下的同路径 bind mount 必须保持宿主机绝对路径，不能再套用 `/data -> SMARTX_HOST_DATA_PATH` 映射。修复前不得重试 v0.5.2。
- [ ] 验证当前容量、趋势新样本、VM 真实名称、post-cleanup 和旧目录清理。
- [x] UPG-043 fix3 在 10.20.11.3 完成核心链路：凭据迁移、自动采集、post-cleanup、数据和目录验收通过。
- [x] UPG-044 修复 verification 最近包排序：history 已改为无副作用只读视图，按业务创建时间排序；verification 按成功平台包完成时间独立选最新。fix4 已通过本地/10.20.11.3 各 165 项回归、包静态门禁、真实历史 SHA/mtime 无变化验证和隔离 HTTP release smoke。

详细计划：`docs/superpowers/plans/2026-07-10-post-upgrade-auto-collection.md`。

## UPG-045 / UPG-046 / UPG-047 / UPG-048 最终升级链路闭环

状态：完成。fix7 已由完整链路证明不可交付；fix8 已在 `10.20.11.3` 完成代码测试、依赖完整回归、真实 Docker bind、构建、包体门禁、真实业务基线全链路和最终 release smoke 验收。

执行边界：

- 当前及后续所有 Python 验证、依赖安装、镜像构建、升级包构建、包体门禁和完整升级链路只允许在 `10.20.11.3` 执行。
- 不连接、不恢复、不验证 `10.20.11.12`。
- 本地工作区只维护源码和文档，不运行 Python，不安装测试依赖，不构建升级包。

- [x] 固定已发布输入：`v0.5.1u2` SHA256 `d5f277167445e7636ddfba16b4f780b40d59952467bb1c8e72d2469b43ee0a49`；runner `v0.3.1` SHA256 `d10e15cf7b516d172ebe2f1bc37621f9cf32d8ab3abd548f808ae5c5de151d2c`，两者不得修改。
- [x] UPG-045：v0.5.2 worker 兼容已发布 bridge 未生成自动采集 marker 的情况；fix5 链路已证明主升级、自动采集和 post-cleanup 成功。
- [x] UPG-046：终态 runner task 必须投影到任务中心，并保证重复状态查询不刷新 `updated_at`。
- [x] UPG-047 第一方案：尝试通过 v0.5.2 正式 compose 的 runner 启动命令修正 `.env` 权限；完整链路证明该命令会被已发布 runner handoff compose 覆盖，因此 fix7 不可交付。
- [x] `10.20.11.3` 依赖完整回归：198 项通过，1 项跳过，退出码 0。
- [x] 仅从 `/home/user1/codex-build/worktree-upg047` 构建 v0.5.2 fix7，并完成 checksums、manifest、镜像身份、敏感成员、bundled images 和 compose chmod 门禁；SHA256 `1cde8e34617fcddc00e1a334516694ab0e34fc2997f164a91c718f5f17317497`。
- [x] fix7 完整链路执行完成并定位验收失败：主任务/自动采集/post-cleanup 与任务中心投影均通过，但最终 `.env` 仍为 `0644`；根因是发布 runner handoff compose 覆盖正式 runner command。fix7 不可交付。
- [x] UPG-048 / fix8 TDD：在 web-api 主 apply 路径增加仅针对 `.env` 的权限 shim，不修改已发布 u2/runner。
- [x] fix8 在 `10.20.11.3` 通过 compose 定向测试、2 项 package-builder 测试、198 项依赖完整回归以及真实 Docker 单文件 bind 权限验证；宿主机 `.env` 从 `0644` 修正为 `0600`，web-api 保持 running。
- [x] 仅在 `10.20.11.3:/home/user1/codex-build/worktree-upg048` 构建 fix8，完成 sidecar/internal checksums、manifest/source compatibility、镜像身份、敏感成员、bundled images、三份 compose shim 和 bridge render 门禁；包 SHA256 `692aca8b58ad8199c43c02a3771fa4fd7a62f1d7bbf4f198af4bd2e4b2c67733`。
- [x] 在 `10.20.11.3` 审计并恢复真实 `v0.5.1 + runner v0.3.0`：五容器和旧 project/network/subnet 正确，业务计数 `towers=1/clusters=1/vm_latest=556/vm_volumes=89588`，`.env` SHA `8b644112...`、`0600 root:root`，目标根目录不存在。
- [x] 在 `10.20.11.3` 按正常产品流程执行已发布 `v0.5.1u2 -> runner v0.3.1 -> v0.5.2 fix8`；任务依次为 `upgrade-5680ff0264c4acbd -> upgrade-53ebaff4da3218df -> upgrade-9ad951d4024b2c16`，全部成功。
- [x] 验收任务中心终态与幂等查询、自动采集、post-cleanup、`.env` SHA/`0600 root:root`、业务计数、五容器镜像、project/network/subnet、七目录、旧路径清理、history/verification 只读稳定性和 release smoke；最终 `critical=0/warning=0`。

## Phase 49 - v0.5.2 后续治理与风险待办

状态：待处理

背景：v0.5.2 升级链路已闭环，但在代码审查和现场测试中发现若干治理/风险项，统一记录待处理。

### 3. compose 镜像 tag 仍可被 .env 覆盖

- 源码 compose 仍使用 `${SMARTX_IMAGE_TAG:-v0.5.2}` 模板。
- 现场 `.env` 若残留旧 `SMARTX_IMAGE_TAG=v0.5.1`，`docker compose up -d` 会把镜像拉回旧版。
- 升级包内 compose 已在打包时渲染固定 tag（安全），但**源码 compose 仍是模板**，现场误用风险仍在。
- 待办：正式部署场景下禁止 `.env` 覆盖镜像版本；或部署后强制校验 `.env` 无版本 key。

### 4. 测试机地址散落在内部文档

- `progress.md`、`findings.md`、UPG worklog、计划文档中存在大量 `10.20.11.3` / `10.20.11.12` / `10.20.0.6`。
- 对外发布文档（README/CHANGELOG/deployment）已清理，但内部工作记录一旦被复制到公开渠道会泄露拓扑信息。
- 待办：内部文档保持现状（排障需要），但对外交付文档必须零业务地址；必要时增加发布前地址扫描门禁。

### 5. post_upgrade_cleanup_status 与 post-cleanup 实际状态不一致

- 现场测试发现 `task.json` 里 `post_upgrade_cleanup_status: pending`，但实际 post-cleanup 任务已 success。
- 属于历史字段/投影不同步，会误导后续排障。
- 待办：统一 task 顶层 cleanup 状态字段与 post-cleanup 子任务状态投影。

### 6. 测试机无统一一键回归

- 每次完整链路验证靠临时脚本（`do_step.py`、`upg_chain.py` 等）和人工核对。
- 待办：把完整链路验证固化为脚本/工具，包含基线恢复、三步升级、自动采集/cleanup 验收、数据/目录/.env 断言和报告生成。

### 7. 标准业务基线未固化为产物

- 多次因数据源选择错误导致误判（本次 .3 就踩了 `v2-migration-verify` 旧库 vs `fixtures` 配套库的坑）。
- 待办：把「SQLite + 配套 .env + Prometheus 数据」固化为一个可校验 SHA 的标准基线产物，恢复脚本只用它。
