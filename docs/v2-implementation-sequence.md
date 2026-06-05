# v2 实施顺序

更新时间：2026-06-06

## 1. 总原则

v2 按阶段重建，每个阶段都必须可验证、可提交、可回退。不要同时重写所有模块。

规则：

- 只在 `feature/upgrade-v2` 上实施。
- 后续 v2 构建、部署和现场验证可以使用 `10.20.11.3`，远端也必须切换到 `feature/upgrade-v2` 分支后执行。
- 每阶段只做本阶段范围，不混入其他模块。
- 每阶段结束更新 `progress.md`。
- 每阶段提交前检查不包含 `.env`、数据库、Prometheus 数据、凭据、升级包、迁移包、备份包。

## 2. Phase V2-0 - 文档冻结

目标：冻结实现前决策。

交付物：

- `docs/architecture-v2.md`
- `docs/v1-data-compatibility.md`
- `docs/v2-upgrade-center-design.md`
- `docs/v2-api-contracts.md`
- `docs/v2-frontend-design.md`
- `docs/v2-implementation-sequence.md`

验收：

- 文档覆盖所有 v1 核心功能。
- 文档覆盖所有升级问题的 v2 规避策略。
- 文档不包含真实凭据。

## 3. Phase V2-1 - 项目骨架

目标：建立后端和前端 v2 目录结构。

交付物：

- 后端模块目录。
- 前端页面和组件目录。
- 统一类型和任务模型。
- 空壳应用可启动。

不做：

- 不实现采集。
- 不实现报表。
- 不实现升级。

验收：

- 后端语法检查通过。
- 前端构建通过。
- 健康检查接口返回 200。

## 4. Phase V2-2 - 基础平台和认证

目标：让平台可以登录、鉴权、初始化数据库。

交付物：

- 配置读取。
- 版本读取。
- SQLite 初始化。
- 登录。
- `/api/me`。
- 修改密码。
- admin 头像菜单。

验收：

- 默认账号可登录。
- 修改密码后旧密码失效。
- 未登录访问管理 API 返回 401。

## 5. Phase V2-3 - Tower、采集、Prometheus

目标：打通数据采集主链路。

交付物：

- Tower CRUD。
- 连接测试。
- 集群同步和启用。
- CloudTower 客户端。
- 手动采集。
- collector-worker 定时采集。
- Prometheus 写入和查询。

验收：

- 添加 Tower 后能同步集群。
- 手动采集成功。
- Prometheus 能查询 VM 容量指标。
- 采集失败不泄露凭据。

## 6. Phase V2-4 - Dashboard 和 VM

目标：恢复核心可视化。

交付物：

- Dashboard summary。
- 容量风险判断。
- 日增长最快 VM。
- 本日新建 VM。
- VM 列表。
- VM 趋势。
- VM 卷详情。

验收：

- 任一集群超过 80% 首页显示高风险。
- VM 趋势有数据。
- VM 改名后趋势不断裂。

## 7. Phase V2-5 - 报表

目标：恢复页面预测和客户导出。

交付物：

- `latest_report`。
- 90 天预测。
- 7 天平均增长速率。
- 月增长 30 天样本过滤。
- 本月新建 VM。
- Word/Excel 导出。
- 报表留存和下载。

验收：

- 页面报表有集群数据。
- Word/Excel 可打开。
- 导出文件留存在 `/data/exports/reports`。
- 月增长榜不包含样本不足 30 天的 VM。

## 8. Phase V2-6 - 数据迁移

目标：实现灾备型迁出迁入和 v1 数据兼容。

交付物：

- v2 迁出包。
- v2 迁入。
- 导入前备份。
- v1 迁移包兼容。
- Prometheus block 导入。
- 导入后健康验证。

验收：

- v1 迁移包导入后趋势图、日增长、月增长、预测报表都有数据。
- 导入前备份真实存在。
- 旧 VM 卷 payload 被抽取为结构化字段。

## 9. Phase V2-7 - 升级中心

目标：实现统一升级模式。

交付物：

- 升级包上传。
- manifest 解析。
- 包列表。
- 预检查。
- 平台升级。
- runner 组件升级。
- Prometheus 组件升级。
- 回滚和历史记录。

验收：

- 上传包能自动识别组件。
- 平台升级不默认升级 runner。
- Prometheus 升级后历史指标仍可查询。
- 失败后保留回滚入口。

## 10. Phase V2-8 - 服务管理

目标：完成运维页面闭环。

交付物：

- 数据迁移页面。
- 服务重启。
- 空间扫描和清理。
- 任务中心统一展示。

验收：

- 清理前能看到待删除列表。
- 清理后显示本次释放空间。
- 任务中心能显示日志和下载链接。

## 11. Phase V2-9 - 部署和现场验证

目标：验证 v2 可部署、可迁移、可升级。

交付物：

- Dockerfile。
- compose。
- GitHub Actions。
- pre_install。
- 升级包打包脚本。
- runner 组件包打包脚本。

现场验证：

- 在 `10.20.11.3` 部署，并确认远端仓库位于 `feature/upgrade-v2`。
- 执行 `pre_install.sh`。
- 启动 offline compose。
- 添加 Tower。
- 完成采集。
- 导出报表。
- 迁出并迁入验证环境。
- 执行平台升级。
- 执行 runner 升级。
- 执行 Prometheus 升级。

## 12. 提交流程

每阶段提交前：

```bash
git status --short
git diff --stat
```

提交范围必须只包含当前阶段文件。

文档阶段提交信息示例：

```text
docs: add v2 architecture documents
```

代码阶段提交信息按模块：

```text
feat: add v2 auth foundation
feat: add v2 collection pipeline
feat: add v2 migration import compatibility
```
