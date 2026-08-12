# Post-Upgrade Auto Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 v0.5.2 平台升级成功后自动采集一次，并将独立采集任务和结果显示在任务中心。

**Architecture:** v0.5.1u2 编译器追加 `post_upgrade.schedule_collection`；runner v0.3.1 将一次性 JSON 标记写入目标升级任务目录；v0.5.2 collector-worker 等待父升级任务成功后消费标记并调用现有 CollectionService。自动采集与主升级解耦，失败只产生 warning。

**Tech Stack:** Python 3.12、FastAPI、SQLite、APScheduler、Docker Compose、unittest。

## Global Constraints

- 只在 `post_upgrade.auto_collection=true` 的平台包中启用。
- 自动采集 task ID 固定为 `post-upgrade-collection-<parent_upgrade_task_id>`。
- 自动采集失败不得改写主升级或 post-cleanup 的成功状态。
- v0.5.1u2 保持 runner v0.3.0 协议兼容；新动作由升级 runner v0.3.1 执行。
- 所有完整链路测试只在 10.20.11.3 进行，不操作 10.20.11.12。

---

### Task 1: 锁定编译器与 runner 标记协议

**Files:** `backend/tests/test_v2_package_builders.py`、`backend/tests/test_upgrade_runner_engine.py`、`backend/app/v2/upgrade/compiler.py`、`backend/app/upgrade_runner/actions.py`、`backend/app/upgrade_protocol/constants.py`、`backend/app/upgrade_runner/main.py`

- [ ] 新增失败测试：manifest 开启自动采集时，执行计划在 `health.http` 和 `task.sync_runtime_state` 后、cleanup/handoff 前包含 `post_upgrade.schedule_collection`。
- [ ] 新增失败测试：runner 动作在目标 upgrades 父任务目录原子写入标记，重复执行返回同一 task ID，不覆盖终态。
- [ ] 运行定向测试并确认 RED。
- [ ] 实现编译动作、能力映射、safe-resume 和任务步骤映射。
- [ ] 实现标记写入与路径校验，运行定向测试确认 GREEN。

### Task 2: collector-worker 消费一次性标记

**Files:** `backend/tests/test_v2_worker.py`、`backend/tests/test_v2_collection.py`、`backend/app/v2/worker.py`、`backend/app/v2/collection/service.py`

- [ ] 新增失败测试：父升级未成功时不采集；父任务成功后只采集一次。
- [ ] 新增失败测试：自动采集创建“升级后自动采集”任务并更新 success/failed；失败 severity 为 warning，父升级保持 success。
- [ ] 新增失败测试：running 标记在 worker 重启后转为 failed，不重复采集。
- [ ] 运行定向测试确认 RED。
- [ ] 实现 marker 原子状态机、5 秒轮询 job 和 `post_upgrade` trigger 任务中心语义。
- [ ] 运行定向测试确认 GREEN，并回归手动/定时采集测试。

### Task 3: 构建器、静态门禁与文档

**Files:** `scripts/build_upgrade_package.py`、`scripts/verify_upgrade_package_identity.py`、`backend/tests/test_v2_package_builders.py`、升级专项文档和 ledger。

- [ ] 新增失败测试：v0.5.2 manifest 包含 `auto_collection=true`，v0.5.1u2 不包含。
- [ ] 新增失败测试：静态门禁要求 v0.5.2 执行计划包含自动采集动作。
- [ ] 实现构建器与门禁，运行包构建器测试确认 GREEN。
- [ ] 更新 UPG-041 问题、计划、工作日志、ledger、task/findings/progress。

### Task 4: 回归、三包构建和完整链路

- [ ] 本地/10.20.11.3 运行后端完整测试并记录数量。
- [ ] 在 10.20.11.3 构建 UPG-041 v0.5.1u2、runner v0.3.1、v0.5.2 包并记录 SHA256。
- [ ] 恢复 10.20.11.3 为正常业务库的 v0.5.1 + runner v0.3.0。
- [ ] 按正常 API/UI 流程完成三段升级；任何失败立即停止并记录。
- [ ] 验证自动采集任务、当前 Prometheus 样本、真实 VM 名称、数据库计数、容器、目录、project/network 和 post-cleanup。
- [ ] 将最终 task ID、包路径、SHA256 和验收结果写回 ledger/worklog/findings/progress。

### Task 5: UPG-042 Tower 凭据与 `.env` 成对迁移门禁

**Files:** `backend/app/upgrade_runner/actions.py`、`backend/tests/test_upgrade_runner_engine.py`、`scripts/build_upgrade_package.py`、升级专项文档和 ledger。

- [x] 确认通用根因：`filesystem_prepare()` 在迁移 DB 前处理 `.env`，并因 `preserve_existing=true` 无条件保留可能不配套的目标 `.env`。
- [x] 新增 RED：迁入旧 DB 时，能解密凭据的 legacy `.env` 必须覆盖不兼容目标 `.env`。
- [x] 新增 RED：DB 有加密 Tower 凭据但所有 `.env` 候选均不兼容时必须失败，不能创建默认密钥。
- [x] 调整顺序：先确定/迁移目标 DB，再选择 `.env`。
- [x] 使用目标 web-api 镜像的真实 `InventoryService` 校验候选密钥，只返回计数和兼容布尔值。
- [x] 本地 100 项升级定向回归通过；10.20.11.3 同组 100 项通过。
- [x] 10.20.11.3 root Docker 集成测试通过：正确 Fernet 密钥兼容，错误密钥不兼容。
- [x] 重打 runner v0.3.1 和 v0.5.2；v0.5.1u2 复用 UPG-041 包；镜像身份、manifest 和敏感文件静态门禁通过。
- [ ] 修复代码审查阻塞：`.env` 必须 `0600`；schema/SQLite 异常 fail-closed；补充当前 XOR 格式密钥判定策略和回归测试。完成前 UPG-042 两个新包不得交付。
- [ ] 从配套 `smartx.db + .env` 的 v0.5.1 基线重跑完整链路，验证自动采集成功且无需重新填写 Tower 凭据。
