# 设计：升级收尾兜底（US-30 / US-27）——post-cleanup 不再依赖客户端轮询

状态：设计（2026-09-28，用户指令「修，继续写相关文档」）。**实施随本设计进行**。
问题记录：`docs/upgrade-strategy-issues.md` US-30（🔴）、US-27（🟠）；实测证据见 `progress.md` 2026-09-28 第 3 批。

## 1. 背景（实测）

`.12` task `upgrade-0de5b6ad24d41c56`：**14 个动作全部 succeeded**、状态 `success`，但 `/data/smartx-capacity-insight-data`、`/prometheus-data`、`/data/upgrades` 三条 legacy 路径**至今残留**。

**代码链条**：

```
升级执行完成
  └─ post_upgrade.schedule_cleanup 动作  → 只写标记文件（marker_path），不清理
  └─ post_upgrade_cleanup_task_id = None  → 清理任务未创建
        ↓
谁创建清理任务？ _maybe_schedule_post_upgrade_cleanup()   (execution.py:648)
        ↓ 谁调用它？ _normalize_completed_runner_task()     (execution.py:627)
        ↓ 谁调用它？ execution.py:151（status 接口 = 客户端轮询）
                    cleanup.py:104（查 cleanup 状态）
        ↓
worker 侧无任何后台兜底
```

**结论**：**只要没有客户端调用 `status` 接口，升级后清理任务就永远不会被创建**。任务却显示"成功"。

**触发条件不是异常路径，而是"没人看"** —— 用脚本/定时任务发起升级、不持续轮询状态即命中。本轮实测正是如此（start 后未等完成即返回）。

## 2. 口径

1. **升级收尾不得依赖客户端行为**。平台升级一旦终态为 `success`，清理任务必须最终被创建，与有没有人看 UI 无关。
2. **复用既有守护线程框架**（US-09 的 `housekeeping`），不引入新的进程/容器。
3. **幂等**：兜底只补建**缺失的**清理任务；已存在则不动（现有 `_maybe_schedule_post_upgrade_cleanup` 已有该判断）。
4. **不改变升级计划与协议**：不动 `execution_plan`、不动 manifest、不动 runner。
5. **失败任务不自动收尾**（US-31 另行处理）：本设计只保证"**成功**但没清理"被兜住；失败态的收尾提示仍走 US-27 的 `cleanup_required`。

## 3. 实施

### 3.1 守护线程 `app/v2/upgrade/settlement.py`（新文件）

```
settlement.py
  scan_missing_settlement(settings, database, *, now) -> list[str]
      扫 upgrades/*/task.json：status ∈ {success, succeeded}
      且 manifest.post_upgrade.create_cleanup_task 为真
      且 manifest.legacy_cleanup 非空
      且 post_upgrade_cleanup_task_id 缺失 或 对应 task.json 不存在
      → 返回 task_id 列表（只读，不改任何东西）

  ensure_settlement_once(settings, database, *, now) -> dict
      对每个漏网任务调用 UpgradeService.create_post_upgrade_cleanup_task(task_id, legacy_cleanup)
      单个失败不中断其余；返回 {created: [...], failed: [{task_id, error}]}
      幂等：创建前再查一次（防与客户端轮询并发重复建）

  start_settlement_daemon(settings, database, *, interval_seconds=None, stop_event=None)
      守护线程：启动即跑一次（覆盖 web-api 重启后的补建），之后按间隔跑
      默认间隔 5 分钟（远小于升级频率，成本可忽略）
      SMARTX_UPGRADE_SETTLEMENT_INTERVAL_SECONDS=0 可关闭
```

**为什么放 web-api 而不是 worker**：清理任务创建要走 `UpgradeService`（web-api 侧服务），worker 是独立进程、不持有该服务；housekeeping 守护线程同样在 web-api（`main.py:46`），照抄即可。

### 3.2 接线（`main.py`）

- 新增 `settlement_stop_event`，startup 启动、shutdown 停止，与 housekeeping 完全对称。

### 3.3 兜底的幂等与并发

- `create_post_upgrade_cleanup_task` 本身会写 `post_upgrade_cleanup_task_id`；并发下两个调用可能都通过"不存在"判断 → 用**先写 task.json 再回写父任务 id**的顺序（现有实现已如此），并让 `ensure_settlement_once` 在创建前**重新读一次父任务文件**缩小窗口。
- 重复创建的后果是产生两个 `post-cleanup-<id>` 目录（幂等覆盖写），不会破坏数据；守护线程每轮都按"id 缺失或目录无 task.json"判定，可自愈。

### 3.4 配置

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `SMARTX_UPGRADE_SETTLEMENT_INTERVAL_SECONDS` | `300` | 兜底扫描间隔；`0` 关闭 |

新增 `V2Settings.upgrade_settlement_interval_seconds`（默认值同 `.env.example` 口径写死默认值，不强制进 `.env`）。

## 4. 测试计划

| # | 用例 | 通过标准 |
| --- | --- | --- |
| 1 | `scan` 只认「成功 + 有 legacy_cleanup + 清理任务缺失」 | 其它状态（failed/pending/running/无 legacy_cleanup/已有 cleanup）一律不返回 |
| 2 | `ensure_settlement_once` 补建成功 | 创建出 `post-cleanup-<id>/task.json`，父任务写入 `post_upgrade_cleanup_task_id` |
| 3 | **幂等**：连续调用两次 | 第二次 `created` 为空，不产生第二个清理任务 |
| 4 | **不依赖轮询**：造一个"已 success 但无 cleanup 任务"的任务，**全程不调用 status 接口** | `ensure_settlement_once` 仍能补建（这是 US-30 的判别用例） |
| 5 | 单个失败不影响其余 | 一个任务构造异常，其余仍被补建，失败项进 `failed` 列表 |
| 6 | 关闭开关 | `interval<=0` 时 `start_settlement_daemon` 返回 `None` |
| 7 | 回归：现有 housekeeping 与升级测试 | `.3` 后端全量 + build_tests 全绿 |

**`.12` 判别格**：造一个"成功但无 cleanup 任务"的任务（不调 status）→ 等守护线程（≤5 分钟）→ 确认 `post-cleanup-<id>` 目录出现；再跑一次成功升级，确认 legacy 路径被清。

## 5. 边界（不做）

- 不动升级计划/协议/runner（US-30 纯 web-api 侧）。
- 不处理**失败态**的自动收尾（US-31 另行排期；失败态仍走 US-27 的 `cleanup_required` 提示 + 人工重跑）。
- 不做备份保留策略（US-31 附带项，另议）。
- 不引入新容器/新进程。

## 6. 回滚

纯 web-api 侧新增模块 + 2 处接线，回滚即还原；不影响已升级环境与协议。开关 `SMARTX_UPGRADE_SETTLEMENT_INTERVAL_SECONDS=0` 可现场止血。

## 7. 关联

- 问题：`docs/upgrade-strategy-issues.md` US-30（🔴）、US-27（🟠 关键路径）
- 复用框架：`backend/app/v2/upgrade/housekeeping.py`（US-09）
- 实测证据：`progress.md` 2026-09-28 第 3 批（`auto_rollback.log`、U1 任务文件）
- 验证闭环：task_plan 第 57 项（阶段 A 覆盖本项判别格）
