# SmartX HCI Capacity Insight 代码模块清单

快照时间：2026-09-19；版本：平台 v0.5.3 / runner v0.3.1（dev2 分支）。

本文完整列出仓库内全部代码模块、部署资产与测试资产的**结构清单**（路径、规模、职责、所属容器），用作结构索引。功能域视角（每个功能域的常见问题与修复历史）见 [functional-modules.md](functional-modules.md)；升级问题台账见 [upgrade-issues.md](upgrade-issues.md)；文档分类索引见 [doc-map.md](doc-map.md)。规模为 `wc -l` 快照，仅供相对参考。

## 1. 运行形态与代码入口

平台为模块化单体，五个容器；不拆分业务微服务（架构边界见 AGENTS.md）。

| 容器 | 镜像构建 | 代码入口 | 职责 |
| --- | --- | --- | --- |
| web-api | `backend/Dockerfile` | `python -m app.v2.main`（uvicorn） | FastAPI：鉴权、业务查询、报表、数据迁移、升级中心 API |
| collector-worker | `backend/Dockerfile.worker` | `python -m app.v2.worker` | 定时/手动采集 Tower 数据，写 SQLite 与 Prometheus（:9108 导出） |
| frontend | `frontend/Dockerfile` | React/TS SPA，Nginx 静态服务 | Web UI（8080→80） |
| prometheus | `prom/prometheus:v2.55.1` | `prometheus/prometheus.yml` | 容量历史时序存储与查询 |
| upgrade-runner | `backend/Dockerfile.upgrade` | `python -m app.upgrade_runner.main` | 平台/组件升级执行、备份、Compose 操作、健康检查、回滚、legacy 清理 |

## 2. 后端（backend/app）

### 2.1 web-api 主体（`app/v2/` 顶层）

| 模块 | 行数 | 职责 |
| --- | --- | --- |
| `main.py` | 32 | FastAPI 应用组装、路由聚合 |
| `config.py` | 149 | 运行配置（SMARTX_* 环境变量：数据根、DB、Prometheus、目录、阈值等） |
| `database.py` | 389 | SQLite 连接、WAL/busy_timeout、索引、tasks 表仓储 |
| `security.py` | 90 | 密码哈希、token、Tower 凭据加解密（XOR） |
| `worker.py` | 576 | collector-worker 主程序：采集调度、失败重试、部分成功处理、指标导出 |
| `parsing.py` | 13 | Tower 返回解析入口 |
| `registry.py` | 16 | 域路由注册 |
| `scope.py` | 6 | 集群/范围口径 |

### 2.2 API 路由层（`app/v2/api/`，2490 行）

| 模块 | 行数 | 职责 |
| --- | --- | --- |
| `deps.py` | 137 | 鉴权依赖（Bearer token、admin 校验） |
| `models.py` | 544 | Pydantic 响应模型（契约对齐，见 v2-api-contracts.md） |
| `auth.py` | 131 | 登录/改密/me |
| `dashboard.py` | 115 | 总览聚合接口 |
| `vms.py` | 175 | 虚拟机清单/趋势接口 |
| `reports.py` | 188 | 报表生成/下载接口 |
| `towers.py` | 244 | Tower 配置 CRUD/测试 |
| `collection.py` | 137 | 采集触发/调度/记录接口 |
| `tasks.py` | 164 | 任务中心接口（含通知确认/删除） |
| `system.py` | 140 | 健康检查（ok/version/runner_version/checks 探测） |
| `admin/` | 484 | 管理接口子包：`upgrade.py`(234，平台/组件升级 24 条)、`migration.py`(99)、`system_admin.py`(95)、`exports.py`(33) |

### 2.3 业务域包（`app/v2/<域>/`）

| 域 | 行数 | 职责 |
| --- | --- | --- |
| `dashboard/` | 601 | 总览聚合：kpis、增长、**容量风险/增长/预测计算**（`service.py`；`forecast/` 为占位包） |
| `inventory/` | 303 | 集群/数据盘清单 |
| `vms/` | 350 | 虚拟机清单与容量趋势 |
| `metrics/` | 162 | 指标格式化、Prometheus 写入与查询（`formatter.py`/`prometheus.py`/`series.py`） |
| `collection/` | 394 | 采集编排、调度同步、缺采与重试 |
| `data_quality/` | 477 | 数据质量检查（缺采/异常标记） |
| `capacity_alerts/` | 166 | 容量风险阈值与告警口径 |
| `reports/` | 602 + export 子包 | 报表服务（`service.py`、`templates/customer_report.xlsx` 模板、`wording.py` AI 措辞层接口+离线回退）；`export/`：`common.py`(904)、`word.py`(1022)、`excel.py`(807)、`legacy.py`(2) |
| `migration/` | 950 | 数据迁移导出/导入（SQLite+Prometheus 成对迁移） |
| `cleanup/` | 539 | 空间清理（报表/迁移/升级产物） |
| `tasks/` | 411 | 任务中心模型与通知 |
| `upgrade/` | 463 + service 子包 | 升级中心：`compiler.py`（manifest 编译）、`runner.py`（任务下发）、`migrations/`（升级期 DB 迁移脚本）；`service/` 11 文件：intake/precheck/execution/paths/fs/verification/cleanup/taskfile/constants/_compat |
| `cloudtower/` | 290 | CloudTower API 客户端（登录、资源查询） |
| `system/` | 215 | 健康检查（含 checks.directories 目录探测）、版本 |
| `auth/` | 59 | 用户存储 |
| `forecast/` | 1 | 占位包（预测/风险计算实际在 `dashboard/service.py` 与报表层） |

### 2.4 升级执行器（`app/upgrade_runner/`，3535 行 + `app/upgrade_protocol/` 166 行）

| 模块 | 行数 | 职责 |
| --- | --- | --- |
| `actions.py` | 2527 | 全部升级动作 handler：filesystem.prepare/cleanup、backup.create、image.load、files.sync、compose.*、runner.handoff/stop_legacy、post_upgrade.schedule_*、post_cleanup.*、legacy.cleanup、task.migrate/sync_runtime_state 等 |
| `engine.py` | 247 | 执行计划引擎：步骤编排、失败回滚、恢复 |
| `main.py` | 499 | runner 主循环（3s 轮询）、租约获取、心跳、组件任务续跑 |
| `lease.py` | 140 | SQLite 租约与 runner 心跳（upgrade_runner_state/upgrade_task_leases） |
| `store.py` | 52 | task.json 存取与乐观并发 |
| `sandbox.py` | 69 | 沙箱脚本执行（script.run_sandboxed） |
| `upgrade_protocol/` | 166 | 升级协议：常量（版本/能力）、manifest 模型与校验（`constants.py`/`models.py`/`validation.py`） |

### 2.5 共享（`app/core/`）

| 模块 | 行数 | 职责 |
| --- | --- | --- |
| `config.py` | 67 | 镜像内 `/app/VERSION`、`/app/RUNNER_VERSION` 读取（版本身份来源） |

说明：v1 遗留代码（`app/main.py`、`app/api/`、`app/services/`、`app/collector/` 等）已于 2026-09-13 移除，不再随镜像发布。

## 3. 前端（frontend/src，约 11,000 行 TS/TSX，Vite + React + TS）

| 模块 | 内容 |
| --- | --- |
| `pages/` | `LoginPage`、`DashboardPage`（总览）、`VmsPage`（虚拟机）、`ReportsPage`（报表）、`ServicePage`（服务管理，六域子组件见下）、`SettingsPage`（Tower 设置）；每个页面伴随 `.test.tsx` |
| `components/service/` | ServicePage 拆分组件：`PlatformUpgradeSection`、`ComponentUpgradeSection`、`MigrationSection`、`CleanupSection`、`RestartSection`、`HistorySection`、`shared.tsx` |
| `components/tower/` | `TowerForm.tsx`（Tower 配置表单） |
| `components/` | `AppLayout`（布局/导航）、`Card`、`MetricCard`、`StatusPill`、`StorageBar`、`TrendChart`、`ClusterCapacityChart` |
| `services/api.ts` | 统一 API 客户端（token、错误处理） |
| `v2/` | 增量域代码：`components/AccountMenu.tsx`（admin 头像菜单）、`services/auth.ts`、`types/tasks.ts` |
| `styles/` | 全局样式（颜色仅用 `:root` 变量，见 frontend-style-guide.md） |
| `test/` | vitest 测试设置；测试文件 7 个 |

## 4. 部署与构建资产（仓库根）

| 资产 | 职责 |
| --- | --- |
| `docker-compose.yml` | 开发/主 Compose（版本由镜像内 VERSION 定） |
| `docker-compose.offline.yml` | 离线部署（本地镜像，目标布局挂载） |
| `docker-compose.release.yml` | Release 交付 Compose |
| `docker-compose.upgrade.yml` | 升级链路专用（runner bootstrap/cutover） |
| `pre_install.sh` | 安装前置：目录创建、权限、SELinux/防火墙/Prometheus 权限 |
| `backend/Dockerfile`、`Dockerfile.worker`、`Dockerfile.upgrade` | web-api / collector-worker / upgrade-runner 镜像 |
| `frontend/Dockerfile` | 前端镜像（Node 构建 + Nginx） |
| `backend/requirements-api.txt`、`-worker.txt`、`-upgrade.txt`、`-dev.txt`、`requirements.txt` | 分容器依赖 |
| `prometheus/prometheus.yml` | Prometheus 抓取配置 |
| `VERSION`、`RUNNER_VERSION` | 平台/runner 版本身份（v0.5.3 / v0.3.1） |
| `.github/workflows/docker-images.yml`、`upgrade-runner-image.yml` | CI：发布镜像与 runner 镜像构建 |

## 5. 测试资产

| 位置 | 内容 |
| --- | --- |
| `backend/tests/` | 31 个测试文件：v2 各域 API/服务、升级引擎（`test_upgrade_runner_engine.py`，67 项含 UPG-049 两个守卫回归）、升级协议、部署配置、worker 管线；远端全量回归以 `.3` 上 `backend/tests/test_v2_*.py` 为准（最近基线 310 tests，见 upgrade-package-ledger.md 2026-09-19 条目） |
| `backend/build_tests/test_v2_package_builders.py` | 升级包构建门禁测试（26 项） |
| `frontend/src/**/*.test.tsx` | vitest 页面/组件测试（7 文件，85 用例） |
| `scripts/verify_*.py`、`scripts/verify_full_upgrade_chain.py` | 包身份/升级中心/全链路验证脚本 |

## 6. 运维与打包脚本（scripts/）

| 脚本 | 职责 |
| --- | --- |
| `build_upgrade_package.py` / `build_bundle_upgrade_package.py` | 平台升级包 / 直升合并包构建 |
| `build_runner_component_package.py` / `build_prometheus_component_package.py` | runner / Prometheus 组件包构建 |
| `verify_upgrade_package_identity.py` | 包结构、manifest、内部版本、镜像 tag、SHA256 门禁 |
| `verify_upgrade_center_v050.py` | 升级中心 API 流程验证 |
| `verify_full_upgrade_chain.py` | 完整升级链路验证 |
| `verify_release_docs_safe.py` | 发布文档一致性检查 |
| `verify_api_docs.py` | api.md 与后端路由双向比对 + 契约单向校验（API 文档防漂移门禁） |
| `release_smoke_check.py` | 发布冒烟检查 |
| `capture_baseline.py` | 升级前基线采集（DB 计数、容器、目录） |
| `bind-mount-recover.sh` | UPG-050 嵌套挂载体检与一键恢复（check/recover；运行期禁删 app/ 挂载点目录） |

## 7. 文档（docs/）

完整分类与用途见 [doc-map.md](doc-map.md)。主要分组：架构与指南（`architecture-v2.md`、`project-guide-for-ai.md`、`api.md`、`v2-api-contracts.md`、`deployment.md`、`usage.md`、`ova-delivery.md`、`frontend-style-guide.md`）、升级链路（`upgrade-issues.md`、`v0.5.1-to-v0.5.2-upgrade-chain-worklog.md`、`upgrade-package-ledger.md`、`upgrade-runner-lifecycle.md`、`v2-upgrade-center-design.md`、`version-governance.md`）、流程（`development-verification-process.md`、`ai-handoff-guide.md`、`release-acceptance.md`）、运维（`troubleshooting.md`、`backup-recovery.md`）、发布（`releases/CHANGELOG.md`）、设计与计划（`superpowers/specs/`、`superpowers/plans/`）。

## 8. 不入库的本地文件

`AGENTS.md`（工作标准，本地维护）、`.codex/`（Codex 本地工作区，2026-09-19 起排除）、`.zcode/`、`tmp_*.py`（临时脚本，如 `tmp_check_volumes.py`）、`开发 SmartX*.md`（本地笔记）。`findings.md`、`progress.md`、`task_plan.md` 在仓库根目录且入库。
