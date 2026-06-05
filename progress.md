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

状态：进行中

发现：

- 镜像扫描显示的是未被容器使用的镜像，但清理接口原来调用 Docker `/images/prune`，带 tag 的旧版本镜像经常不会被 prune 删除，所以 Docker 返回 `SpaceReclaimed=0`。
- 服务管理的空间清理成功后立即调用 `scanSpaceCleanup()`，清理后自然扫描为 `0B`，覆盖了本次清理释放结果。

修复：

- `backend/app/services/system_control.py` 镜像清理改为逐个删除扫描出的未使用镜像。
- 镜像清理结果返回候选逻辑大小、预计释放大小和删除失败列表。
- `frontend/src/pages/ServicePage.tsx` 保留本次清理结果，不再用清理后重扫覆盖为 `0B`。
- `docs/upgrade-issues.md` 将 UPG-013 标记为已解决。
