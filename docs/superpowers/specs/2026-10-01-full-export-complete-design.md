# 设计：导出迁移包名实相符——SQLite 携带全量业务数据（#68）

- 日期：2026-10-01
- 关联：task_plan #64；pending-tasks #68/#61；`2026-10-01-merge-import-tower-remap-design.md`（#63）
- 状态：设计定稿，随批准实施
- 背景：2026-10-01 三按钮名称与功能一致性审计发现，「导出迁移包」文案承诺
  「包含 Tower 配置与全部历史数据」「两者一起保存才能完整恢复」，
  但其 SQLite 一直用 `tempfile_sqlite_copy`（仅 towers+clusters）——
  **库内监测数据（vm_latest/vm_volumes/collection_runs/metric_snapshots）不在包内**，
  恢复「迁移包+恢复密钥」得不到完整系统。数据包出现前无人察觉。

## 1. 修复口径

**让内容向名称看齐**：全量导出的 SQLite 改为**全量业务拷贝**——

| 保留 | 剥离（本机运行状态，不随包走） |
| --- | --- |
| towers、clusters、vm_latest、vm_volumes、collection_runs、metric_snapshots、schema_migrations | users（账号）、tasks（任务历史）、upgrade_runner_state、upgrade_task_leases |

- 剥离清单与 #63 的 `DATA_EXPORT_DROP_TABLES` 同机制（拷贝后 DROP + VACUUM），
  复用同一 helper（参数化 drop 清单）；
- **导入侧零改动**：`_merge_sqlite`（含 #63 重映射）本就支持全部数据表合入；
- manifest `sqlite_scope` 由 `config` 改为 `full`（如实反映；旧版导入方只读 `migration_scope`，兼容）；
- 恢复密钥机制不变（towers 密文仍在包内）。

## 2. 修复后三按钮语义（审计结论的落点）

| 按钮 | SQLite 内容 | Prometheus | 恢复密钥 | 语义 |
| --- | --- | --- | --- | --- |
| 导出迁移包 | **全量业务**（配置+监测数据） | ✅ | 需要 | 完整备份 |
| 仅导出存储监测数据 | 仅 4 张监测数据表 | ✅ | 不需要 | 只搬数据 |
| 仅导出 Tower 配置 | 仅 towers+clusters | ❌ | 需要 | 只接 Tower |

前端文案同步：「包含 Tower 配置与全部历史数据」→「包含 Tower 配置、库内监测数据与全部历史指标的完整备份」；
hint 与使用说明按上表语义改写。

## 3. 测试计划

| # | 用例 | 判据 |
| --- | --- | --- |
| T1 | 全量导出内容 | 包内 SQLite 含 towers/clusters/vm_latest/…，**无** users/tasks/upgrade_*；manifest sqlite_scope=full |
| T2 | 全量包合并恢复 | 目标机得到 Tower 配置 + 监测数据（业务数据真随包） |
| T3 | 前端文案 | 服务页描述与新语义一致（静态断言） |
| T4 | `.3` 门禁 | 迁移用例 + 全量无回归 |

## 4. 风险与回滚

- 包体积增大（vm_volumes 全量，`.3` 实测库 34M 级）——后台任务模式本就有进度与留档；
- 旧版平台导入新包：读 `migration_scope=full`，合并逻辑兼容（多出的数据表会合入）；
- 回滚：单提交 `git revert`；不改包 manifest 结构、不改导入协议。
