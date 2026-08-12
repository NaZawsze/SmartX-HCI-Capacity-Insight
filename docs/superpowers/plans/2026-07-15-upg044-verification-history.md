# UPG-044 Verification History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让升级历史查询保持只读，并让 verification 稳定选择业务时间上最新的成功平台包。

**Architecture:** 把 runner task 的“只读完成视图”和“持久化收敛”分开。`status()` 保留持久化与 cleanup 调度职责；`history()` 只使用内存视图并按业务时间排序；`verification()` 在成功平台候选中按完成时间独立选择，不依赖文件 mtime 或 history 当前顺序。

**Tech Stack:** Python 3、FastAPI service layer、SQLite task projection、`unittest`。

## Global Constraints

- 只在 `10.20.11.3` 验证，禁止操作 `10.20.11.12`。
- 不删除历史任务、不手工修改 task.json mtime、不通过清理旧记录掩盖问题。
- `status()` 必须继续创建当前任务 post-cleanup；`history()` 和 `verification()` 必须无副作用。
- 时间字段无效时不得返回 500。
- 本轮不提交 Git；当前 worktree 已包含整条 v0.5.2 未提交改动。

---

### Task 1: 锁定 verification 稳定排序

**Files:**
- Modify: `backend/tests/test_v2_upgrade.py`
- Modify: `backend/app/v2/upgrade/service.py`

**Interfaces:**
- Consumes: `UpgradeService.history()`、`UpgradeService.verification()`。
- Produces: `_successful_package_sort_key(task: dict[str, Any]) -> tuple[...]`。

- [x] **Step 1: 写失败测试**

创建新旧两个成功平台 task；新任务 `finished_at` 更晚，但旧 task.json mtime 更新。断言 verification 选择新 task id/SHA。

- [x] **Step 2: 验证 RED**

```bash
PYTHONPATH=backend python3 -m unittest \
  backend.tests.test_v2_upgrade.V2UpgradeServiceTest.test_verification_uses_latest_finished_package_instead_of_task_file_mtime
```

预期：旧实现选择旧 task，断言失败。

- [x] **Step 3: 最小实现**

新增安全时间解析/排序键；verification 对真实成功平台候选使用 `max(..., key=_successful_package_sort_key)`。排序字段依次为 `finished_at`、`uploaded_at`、`created_at`、`started_at`、`updated_at`、task id。

- [x] **Step 4: 验证 GREEN**

运行 Task 1 测试，预期 PASS。

### Task 2: history 查询无副作用

**Files:**
- Modify: `backend/tests/test_v2_upgrade.py`
- Modify: `backend/app/v2/upgrade/service.py`

**Interfaces:**
- Produces: `_completed_runner_task_view(task: dict[str, Any]) -> dict[str, Any]`，只返回内存视图。
- `status()` 继续调用 `_normalize_completed_runner_task()` 持久化。

- [x] **Step 1: 写两个失败测试**

1. 历史 success task 带 post-upgrade cleanup 配置，调用 history 后 cleanup 目录不存在，原 task.json 内容/SHA/mtime 不变。
2. raw running task 的 actions 全部完成，history 返回 succeeded；磁盘仍为 running，且不创建 cleanup。

- [x] **Step 2: 验证 RED**

```bash
PYTHONPATH=backend python3 -m unittest \
  backend.tests.test_v2_upgrade.V2UpgradeServiceTest.test_history_does_not_schedule_cleanup_or_rewrite_success_task \
  backend.tests.test_v2_upgrade.V2UpgradeServiceTest.test_history_projects_completed_runner_task_without_persisting
```

预期：旧实现创建 cleanup 或改写 task.json，至少一项失败。

- [x] **Step 3: 最小实现**

`_completed_runner_task_view()` 对全部 action 为 succeeded/skipped 的非终态 task 复制顶层字典并设置内存 success/recovery 字段；不调用 `_save_task_file()`、`_project_runner_task()` 或 `_maybe_schedule_post_upgrade_cleanup()`。history 使用该视图。

- [x] **Step 4: 保持 status 行为**

`_normalize_completed_runner_task()` 复用完成判断，但继续持久化、投影任务中心和调度 cleanup。现有 status cleanup 测试必须继续通过。

- [x] **Step 5: 验证 GREEN**

运行 Task 2 两项和既有 post-cleanup/status 测试，预期 PASS。

### Task 3: history 稳定业务排序

**Files:**
- Modify: `backend/tests/test_v2_upgrade.py`
- Modify: `backend/app/v2/upgrade/service.py`

**Interfaces:**
- Produces: `_history_task_sort_key(task: dict[str, Any]) -> tuple[...]`。

- [x] **Step 1: 写失败测试**

创建 mtime 与 `created_at` 顺序相反的两个任务，断言 history 按 `created_at` 倒序。

- [x] **Step 2: 验证 RED**

```bash
PYTHONPATH=backend python3 -m unittest \
  backend.tests.test_v2_upgrade.V2UpgradeServiceTest.test_history_orders_by_business_created_time_not_task_file_mtime
```

- [x] **Step 3: 最小实现并 GREEN**

history 读取所有 task 后按 `created_at`、`uploaded_at`、`started_at`、`finished_at`、`updated_at`、task id 排序；不得调用 `path.stat().st_mtime`。

### Task 4: 回归、远端验证与 fix4 打包

**Files:**
- Modify: `docs/v0.5.1u2-to-v0.5.2-upgrade-issues.md`
- Modify: `docs/v0.5.1-to-v0.5.2-upgrade-chain-worklog.md`
- Modify: `docs/upgrade-package-ledger.md`
- Modify: `findings.md`
- Modify: `progress.md`
- Modify: `task_plan.md`

- [x] **Step 1: 本地回归**

```bash
PYTHONPATH=backend python3 -m unittest \
  backend.tests.test_v2_foundation \
  backend.tests.test_v2_upgrade \
  backend.tests.test_upgrade_runner_engine \
  backend.tests.test_v2_package_builders \
  backend.tests.test_upgrade_protocol
```

结果：`Ran 165 tests in 6.651s, OK (skipped=2)`；`py_compile` 与 `git diff --check` 同时通过。

- [x] **Step 2: 10.20.11.3 远端回归**

同步源码到独立 build worktree，运行与本地相同测试。任何失败立即停止并报告。

- [x] **Step 3: 构建 fix4**

runner 代码未变化则复用 fix3 runner 包；重建 v0.5.2 fix4 平台包并执行镜像身份、manifest、checksums、敏感成员门禁。

- [x] **Step 4: 当前环境验证，不重跑升级**

在 10.20.11.3 临时使用 fix4 web-api 镜像执行测试或最小服务级验证；连续调用 history、verification、release smoke，断言最近包始终为 `upgrade-7d86beb3c459bc0a` / `3722d788...`，且调用前后历史 task.json SHA/mtime 不变、无新增旧 cleanup。

- [x] **Step 5: 更新文档**

记录测试结果、fix4 路径/SHA、是否需要重新走完整升级链路，以及 UPG-044 最终状态。

最终结果：远端 `Ran 165 tests in 49.302s, OK (skipped=2)`；fix4 SHA256 为 `29fa1ca308ab41db999a58c6d93908f601d1b355822cab6c6c66ac5a2c8390b7`。fix4 镜像连续执行 service/HTTP history 与 verification，最近包始终为 `upgrade-7d86beb3c459bc0a / 3722d788...`，10 个历史 `task.json` 的 SHA/mtime 不变且无新增 cleanup。隔离 HTTP release smoke 为 `critical=0, warning=0`，health 三项均为 true。本轮查询修复不改 runner、compiler、执行计划、迁移或 compose，按计划不重跑完整升级链。
