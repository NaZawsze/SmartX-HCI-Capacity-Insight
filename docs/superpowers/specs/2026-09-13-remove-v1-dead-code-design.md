# 移除 v1 死代码设计（Phase 49-10 #14）

更新时间：2026-09-13
状态：已定稿，待实施
关联：task_plan.md Phase 49 第 12 项；docs/pending-tasks.md P3 #14

## 1. 背景与目标

v2 重建后，backend 内残留 v1 模块约 4800 行（`app/main.py`、`app/api/`、`app/services/`、`app/collector/`、`app/db.py`、`app/models.py`、`app/cli.py`、`app/upgrade/`、`app/core/security.py`、`app/core/vm_volumes.py`）。运行入口只使用 `app.v2.*` 与 `app.upgrade_runner.*`，这批代码纯随镜像发布：增大镜像、混淆维护、扩大攻击面。

目标：删除死代码；保留被构建管线依赖的模块；回归确认 v2 对 v1 **迁移包**（tar 数据包）的兼容不受影响；镜像体积下降可量化。

## 2. 依赖盘点结论（2026-09-12/13 核查）

### 2.1 删除集（v1 专属，互相引用闭环，无外部引用）

| 路径 | 说明 |
| --- | --- |
| `app/main.py`、`app/api/` | v1 FastAPI 入口与路由（compose 实际运行 `app.v2.main:app`） |
| `app/services/`（users/upgrade/report_export/data_migration/dashboard/forecast 等） | v1 业务服务 |
| `app/collector/` | v1 采集器（v2 为 `app/v2/worker.py`） |
| `app/db.py`、`app/models.py`、`app/core/security.py`、`app/core/vm_volumes.py` | v1 基础设施 |
| `app/cli.py` | v1 命令行工具（依赖 app.db/app.services.users） |
| `app/upgrade/` | v1 升级执行器（v2 为 `app/upgrade_runner/`） |
| 测试：`tests/test_dashboard.py`、`test_data_migration.py`、`test_security.py`、`test_upgrade.py`、`test_forecast.py` | v1 专项测试，随代码删除 |

### 2.2 保留集（含关键依赖）

| 路径 | 保留原因 |
| --- | --- |
| `app/core/config.py` | **被 `scripts/build_upgrade_package.py:310` 与 `scripts/verify_upgrade_package_identity.py:111` 依赖**（读取 VERSION/RUNNER_VERSION 元数据），是发布管线组成部分；仅依赖 pydantic_settings，独立可存 |
| `app/upgrade_protocol/` | `app/upgrade_runner/*` 与 `app/v2/upgrade/*` 共用的协议库 |
| `app/upgrade_runner/` | 独立升级执行器（compose `python -m app.upgrade_runner.main`） |
| `app/v2/`、`app/__init__.py` | 现役代码 |

容器入口不受影响：web-api `uvicorn app.v2.main:app`、worker `python -m app.v2.worker`、runner `python -m app.upgrade_runner.main`。

## 3. 迁移包兼容回归

v2 对 v1 **数据迁移包**（tar 导出包）的兼容在 `app/v2/migration/` 自带实现（不 import v1 模块）；其兼容性由保留的 `tests/test_v2_migration.py` 回归覆盖。本设计不删除任何 v2 代码，迁移包兼容以该测试通过为准；另在 .3 部署后用真实 v1 迁移包（如存在）走一次导入冒烟。

## 4. 实施步骤

1. `git rm` 删除集（代码 + 5 个 v1 专项测试）。
2. 残余引用检查：`grep -r "from app.main|app.api|app.services|app.collector|app.db|app.models|app.core.security|app.core.vm_volumes|from app.upgrade\b"` 在 backend/app、backend/tests、scripts 内应为空。
3. 本地全套 v2 测试回归。
4. .3 部署：解压 → 重建 web-api/worker/frontend/upgrade-runner 四镜像 → recreate → 健康检查 → 远端测试回归 → 记录四镜像体积前后对比。
5. 冒烟：存在真实 v1 迁移包则走一次导入验证；无则跳过并记录。

## 5. 验收结果（2026-09-13 实施）

- [x] backend/app 下无 v1 模块（仅剩 `__init__.py`、`core/config.py`、`upgrade_protocol/`、`upgrade_runner/`、`v2/`），残余引用 grep 为空。
- [x] .3 全量 317 tests / 10 个已知环境性错误（9 只读挂载 + 1 缺 pytest），与移除前基线一致，零回归。
- [x] 四镜像重建、五容器健康。**镜像体积基本持平**（web-api 417MB、worker 157MB、runner 224MB、frontend 49.7MB）——死代码仅约 200KB 源码，镜像体积由依赖主导；实际收益为维护清晰、仓库与镜像内容一致、攻击面收敛。
- [x] 升级包构建脚本（依赖 app/core/config.py）回归通过（builder 用例在基线内）。

## 6. 运维教训（补充）

- .3 的代码同步是 tar 解压（不删除归档中不存在的文件）：删除型变更部署后，必须手工清理 .3 上的残留文件（本次为 5 个 v1 专项测试文件 + app 下 v1 目录/文件），否则残留文件参与测试/构建会产生假错误。
- 镜像瘦身如需量化收益，应针对依赖层（requirements 精简）而非源码删除。

## 6. 回滚

单提交 revert；镜像重建即恢复。
