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
