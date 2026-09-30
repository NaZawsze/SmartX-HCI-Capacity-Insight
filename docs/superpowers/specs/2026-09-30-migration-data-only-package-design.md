# 设计：数据迁移新增「仅导出存储监测数据」包（配置与监测数据分离）

- 日期：2026-09-30
- 关联：`docs/pending-tasks.md` #61；前端 `frontend/src/components/service/MigrationSection.tsx`；后端 `backend/app/v2/migration/service.py`
- 需求来源：用户 2026-09-30「目前迁移数据包没有和配置分开，我希望在仅导出 Tower 配置左边加一个仅导出存储监测数据」
- 状态：设计定稿，待实施

## 1. 背景与问题

实测现有三种导出能力的实际内容（`backend/app/v2/migration/service.py`）：

| 入口 | 实际包内容 |
| --- | --- |
| 导出迁移包（full） | SQLite **仅 towers+clusters**（`tempfile_sqlite_copy` 只建这两张表）+ Prometheus 历史 + .env 恢复密钥 |
| 仅导出 Tower 配置（config） | SQLite 仅 towers+clusters，无 Prometheus + .env 恢复密钥 |
| （不存在） | —— |

**关键缺口**：监测业务数据（`vm_latest` / `vm_volumes` / `collection_runs` / `metric_snapshots`）
**不在任何导出包里**——「配置」和「监测数据」从未分开过，业务库侧的数据目前只能靠整库文件级备份走。
用户诉求即把两者分开：新增「仅导出存储监测数据」。

## 2. 口径（用户视角）

- 新按钮「**仅导出存储监测数据**」位于「仅导出 Tower 配置」**左侧**（用户原话）。
- 数据包含：`vm_latest`、`vm_volumes`、`collection_runs`、`metric_snapshots` + **Prometheus 全部历史**。
- 数据包**不含**：Tower 配置（towers）、集群清单（clusters）、用户账号（users）、任务历史（tasks）、
  升级运行状态（upgrade_runner_state / upgrade_task_leases）。
- **不需要恢复密钥**：包里没有加密的 Tower 凭据 → 不弹恢复密钥对话框、不生成 .env 快照。
- 导入：与现有导入入口共用（后端按 manifest `migration_scope` 自动识别）：
  - **合并导入**：只补监测数据（vm_latest/vm_volumes/collection_runs/metric_snapshots）+ Prometheus 补缺块，
    **不动目标机已配置的 Tower、集群和账号**。
  - **整库替换（overwrite）对数据包直接拒绝**（400）：数据包的 SQLite 被剥过，整库替换会把目标机的
    Tower 配置、账号、任务历史全部清掉——这是数据包语义下绝对要挡的事故。

### 2.1 为什么数据表用「整库拷贝后 DROP 非数据表」而不是「新建空库拷数据」

- 整库拷贝后 DROP，schema 与源库版本**天然一致**（含未来的新表/新列），无 DDL 漂移风险；
  现有 `tempfile_sqlite_copy` 手写 towers/clusters DDL 的方式不扩展。
- DROP 清单显式列「配置与本机运行状态」表，**未来新增业务表默认随数据包走**（符合"数据"语义）；
  若未来新增了不该带的本机状态表，需显式加入 DROP 清单（测试锁住清单）。
- DROP 后 VACUUM，包体积不含已删表空间。

## 3. 改动面

| 文件 | 改动 |
| --- | --- |
| `backend/app/v2/migration/service.py` | 新增 `DATA_SCOPE`、`build_data_export_archive()`、`tempfile_data_sqlite_copy()`（拷贝+DROP+VACUUM）、`_merge_data_sqlite()`；`start_export_task(scope=)` 泛化；`_run_import_task`/`_restore_package` 识别 data 范围（overwrite 拒绝） |
| `backend/app/v2/api/admin/migration.py` | 新增 `POST /api/admin/migration/data/export/start`（复用 export status 轮询路由） |
| `frontend/src/services/api.ts` | 新增 `startMigrationDataExport()` |
| `frontend/src/components/service/MigrationSection.tsx` | 新按钮（Tower 配置左侧）+ `exportDataMigration()`（后台任务模式 + 无恢复密钥弹窗）+ 提示文案与使用说明更新 |
| `backend/tests/test_v2_migration.py` | 新增数据包导出/导入/overwrite 拒绝/无 .env 快照用例 |
| `frontend/src/pages/ServicePage.test.tsx` | 新按钮存在性与行为用例 |
| `docs/api.md` | 新路由登记（跑 `scripts/verify_api_docs.py`） |

**不改动**：full/config 两种导出的现有行为与包格式（向后兼容）；导入的 full/config 路径。

## 4. 测试计划

| # | 用例 | 判据 |
| --- | --- | --- |
| T1 | 数据包导出内容 | manifest `migration_scope=data`；包内 SQLite：vm_latest 有行、towers/clusters/users/tasks 不存在；Prometheus 历史在内；任务无恢复密钥链接、服务器无 .env 快照 |
| T2 | 数据包合并导入 | 目标机 towers/clusters 原样保留；vm_latest 等数据并入；Prometheus 补缺块；本机已有数据不被覆盖（INSERT OR IGNORE） |
| T3 | 数据包 × 整库替换 | 拒绝（400），目标机数据原样，任务 failed 带原因 |
| T4 | 旧包兼容 | full/config 包导入行为与现状完全一致（既有用例不回归） |
| T5 | API | 新路由要求登录；start→status 轮询可用 |
| T6 | 前端 | 按钮位于 Tower 配置左侧；点击走后台任务；成功后**不**弹恢复密钥；文案更新 |
| T7 | 门禁 | `.3` 后端全量无回归 + `verify_api_docs.py` + 前端 tsc/vitest |
| T8 | 真机闭环 | `.3` 用真实库跑一次数据包导出→导入（独立 V2Settings 沙箱目录，不碰运行实例） |

## 5. 风险与回滚

- 风险 1：数据包被当成 full 包覆盖导入 → 已在 T3 用后端 400 挡死（不依赖前端）。
- 风险 2：DROP 清单遗漏未来新增的敏感表 → 测试锁清单；导入侧合并只认 4 张数据表，
  多余表即使混进包也不会被导入。
- 风险 3：大包导出耗时 → 复用 full 导出的后台任务+进度上报模式。
- 回滚：改动集中在 migration service/api/前端单组件，`git revert` 即可；不触碰数据库 schema 与采集链路。
