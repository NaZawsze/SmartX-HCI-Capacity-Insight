# SmartX HCI Capacity Insight - 工作计划

## 目标

为 SmartX HCI Capacity Insight 项目保存可恢复的工作上下文，方便后续 Codex 会话快速理解当前状态、部署方式、分支规则和近期改动。

## 当前环境

- 主要开发与验证机器：`10.20.11.3`
- 项目路径：`/opt/smartx-storage-forecast`
- 默认工作分支：`dev`
- 当前基线提交：`ed3ed5f`，标签 `v0.3.3U1`
- 默认提交策略：用户没有特别说明时，提交到 `dev`；只有用户明确要求时才同步 `main` 和打 tag。

## 当前未提交变更

以下变更已经在远端 `dev` 工作区内实现并完成基础验证，但尚未提交：

- VM 页面已用容量百分比前增加 `已使用` 文案。
- 报表页容量增长速率改为固定按最近 7 天平均增长速率计算。
- 报表页容量增长速率卡片提示改为 `7 天平均`。
- 报表预测图支持 `7 / 30 / 90 / 365 / 720` 天范围切换。
- 报表接口 `GET /api/reports/latest` 支持 `chart_days` 参数。
- 报表接口响应增加 `chart_days` 和 `growth_rate_window_days`。

受影响文件：

- `backend/app/api/routes.py`
- `backend/app/services/dashboard.py`
- `frontend/src/components/ClusterCapacityChart.tsx`
- `frontend/src/pages/ReportsPage.tsx`
- `frontend/src/pages/VmsPage.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/types.ts`

## 阶段计划

### Phase 1 - 持久化项目上下文

状态：完成

- 创建 `task_plan.md`、`findings.md`、`progress.md`。
- 记录项目当前架构、部署方式、分支规则、已知坑点。
- 不记录任何账号密码或敏感 token。

### Phase 2 - 提交前验证近期报表改动

状态：待用户要求

- 后端语法检查。
- 前端构建。
- 重启 `web-api` 和 `frontend`。
- 验证 `/metrics`、`8080` 和 `chart_days` 接口。

### Phase 3 - 提交近期报表改动

状态：待用户要求

- 检查 `git diff`。
- 提交到 `dev`。
- 只有用户明确要求时推送、同步 `main`、打 tag。

### Phase 4 - 导出报表可读性优化

状态：完成

- Word 增加集群目录，方便按集群定位章节。
- Word/Excel 的 VM TOP100 表格标明排序口径。
- Excel TOP100 区域使用表格结构，支持表头筛选/排序。
- 增长率超过 20% 且增长量大于 100 GiB 的 VM 行标红底纹。

## 常用验证命令

在 `10.20.11.3:/opt/smartx-storage-forecast` 执行：

```bash
git status --short
git diff --stat
python3 -m py_compile backend/app/services/dashboard.py backend/app/api/routes.py
docker compose build frontend
docker compose build web-api
docker compose up -d web-api frontend
curl -s -o /dev/null -w "frontend:%{http_code}\n" http://127.0.0.1:8080
curl -s -o /dev/null -w "api_metrics:%{http_code}\n" http://127.0.0.1:8000/metrics
```

## 注意事项

- 所有项目实现、构建、部署验证默认都在 `10.20.11.3` 执行。
- 不要在本机运行应用验证，除非用户明确要求。
- 不要回滚用户或其他会话留下的未提交改动。
- 修改文档时不要写入密码、私钥、token。
- 数据相关功能需要同时关注 SQLite 业务库和 Prometheus 历史指标。

### Phase 5 - 版本治理

状态：进行中

目标：

- 平台版本统一为 `v0.4.1`。
- 平台三件套为 `web-api`、`collector-worker`、`frontend`。
- `upgrade-runner` 作为独立组件，版本为 `v0.2.2`。
- 平台升级包不包含 `upgrade-runner`。
- runner 只通过组件升级包和 runner 专用 GitHub Actions 构建。
- 每次版本提交必须更新 `docs/releases/CHANGELOG.md` 和相关版本治理文档。

待办：

- 拆分 `SMARTX_IMAGE_TAG` 和 `SMARTX_RUNNER_IMAGE_TAG`。
- [已完成] 更新平台版本元数据到 `v0.4.1`。
- [已完成] 移除平台升级包中的 runner 镜像。
- [已完成] runner 组件包默认读取 `RUNNER_VERSION`。
- [已完成] GitHub Actions 拆分平台和 runner 构建。
- [已完成] 文档增加 DockerHub 错误 tag 清理方法。
- 本地验证后提交并推送到 `dev`。

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

状态：待处理

- 定义 Prometheus 组件升级策略。
- 回归验证数据迁移后的 Prometheus 历史指标、日/月增长和趋势图。
- 数据迁移导入前自动生成当前系统备份；备份成功后才允许继续导入，备份失败默认阻止导入。

### Phase 11 - 报表与虚拟机口径新增需求

状态：待处理

目标：

- 月增长最快 VM 只展示历史数据满足 30 天的虚拟机；不足 30 天不进入月增长榜，刚部署且没有满足条件时月增长榜为空。
- 报表导出的 Word/Excel 使用同样口径，不导出不足 30 天的月增长 VM。
- 报表导出的“上期容量”需要在表头或说明里直接标注统计窗口起止日期，避免误解为固定“上个月同期”。
- 在报表页“日增长最快 VM”下新增“本日新建 VM”，在“月增长最快 VM”下新增“本月新建 VM”。
- 新建 VM 列表项需要支持点击跳转到虚拟机页面，并定位/过滤到对应 VM。
- 验证 VM 改名场景：数据以 `tower_id + cluster_id + vm_id` 绑定，历史趋势保持连续；最新一次采集后展示名称应同步为 Tower 当前最新名称。

待确认/实现要点：

- 后端增长榜需要能判断每台 VM 的历史样本跨度是否满 30 天。
- “本日新建 VM / 本月新建 VM”需要定义新建判定口径：建议按首次出现指标样本时间判断，而不是按 VM 名称。
- “上期容量”建议改为“期初容量”，或在 Word/Excel 表头说明中标注统计窗口起止日期，例如 `统计窗口：2026年05月01日-2026年05月31日`。
- VM 跳转应继续使用 UUID 口径，避免同名 VM 或改名 VM 混淆。
- 需要检查采集落库/指标标签更新逻辑，确认同一个 `vm_id` 改名后最新名称会覆盖页面展示名称。

### Phase 12 - 全新升级模式设计

状态：待处理

目标：

- 基于之前平台升级和组件升级遇到的问题，重新设计一套更稳定的升级架构，而不是继续在旧流程上打补丁。
- 平台升级、组件升级、Prometheus 升级、项目文件同步、数据备份、回滚、健康检查、任务状态都要形成闭环。

设计重点：

- 平台升级和组件升级的职责边界重新定义：哪些由 web-api 执行，哪些必须由独立 runner 执行。
- runner 自升级不能依赖旧 web-api 写只读路径，也不能在执行任务中重启自己导致任务断链。
- 升级包需要明确区分平台包、组件包、Prometheus 包或统一包类型，并在 manifest 中声明能力和目标组件。
- compose/project 文件、镜像 tag、镜像名、版本来源必须由同一套规则生成和校验。
- 所有升级动作前必须有可验证备份，回滚要覆盖镜像 override、项目文件和必要的运行配置。
- 任务日志和步骤状态要能跨服务重启恢复，避免页面显示“等待执行”但后台已经卡住。
- 新模式需要输出设计文档、接口草案、升级包目录结构、状态机和迁移路线。
