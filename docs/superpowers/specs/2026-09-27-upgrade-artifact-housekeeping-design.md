# 设计：升级任务运行产物自动清理（US-09 / S1-2）

状态：**已实施并验证**（2026-09-27）。问题台账 [upgrade-strategy-issues.md](../../upgrade-strategy-issues.md) US-09；执行顺序 [../plans/2026-09-27-remaining-work-sequence.md](../plans/2026-09-27-remaining-work-sequence.md) S1-2；用户决策依据：2026-09-21「保留最近 N 个升级任务只在 API 层、界面不暴露」。

## 1. 背景

上传的升级包会解到 `upgrades/<task_id>/`：原始压缩包（v0.5.3 候选包 235.6 MiB）+ 解包目录 `package/`（595.8 MiB）——**一个预检失败的任务就占约 830 MiB**。`.12` 一轮验收就积了 8 个失败任务目录（≈6.6 GiB），只能靠人工跑「空间清理」，而那个入口默认 `keep_recent_upgrades=0`（全删）且在有升级任务在跑时直接拒绝，日常没人会去点。结果：包内容一路堆积，磁盘被慢慢吃掉。

## 2. 口径

新增 `app/v2/upgrade/housekeeping.py`：web-api 侧周期性清理**从未执行过**的升级任务运行产物。

- **候选状态**（只有"没跑过"的终态）：`precheck_failed`、`uploaded`。
  - **不含** `failed`/`success`/`rollback_*`/`cancelled`：这些任务跑过，`task.json`、日志、备份指针是升级失败取证链的一部分（troubleshooting 手册要求失败先取证），**不做自动清理**。
- **触发条件**（两者同时满足）：任务年龄 > TTL（默认 **7 天**，`SMARTX_UPGRADE_ARTIFACT_TTL_DAYS`，`<=0` 关闭本功能）**且**不在按 mtime 排序的最新 **N 个**之内（默认 **3**，`SMARTX_UPGRADE_ARTIFACT_KEEP_RECENT`）。年龄取 `updated_at`，缺失时取 `created_at`。
- **删除范围**：只删包内容——`package/` 目录与上传的原始归档（`task["filename"]`）；**保留 `task.json`**，使其预检查结论、checks、时间线仍留在任务中心与历史里。
  - 删后写回 `package_cleaned_at`，并把 `package_path`/`uploaded_path` 置空，避免留下指向已删文件的路径。
  - 路径安全：待删路径必须位于该任务的 `upgrades/<task_id>/` 之内，越界一律跳过。
- **守卫**：
  - 存在活跃升级任务（`_ACTIVE_UPGRADE_STATUSES`：pending/running/runner_restarting/recovery_required/rollback_pending/rollback_running，与 US-23 单飞守卫共用同一集合，避免两处漂移）→ **整轮跳过**。
  - 写回 `task.json` 前**重新读取并复核状态**仍在候选集内，防并发（用户在清理期间重新预检/开始升级）。
- **调度**：web-api startup 起一个守护线程，默认每 **6 小时**跑一次（`SMARTX_UPGRADE_HOUSEKEEPING_INTERVAL_SECONDS`，`<=0` 关闭），与采集新鲜度探针（`freshness.py`）同构；实际删除了东西才写一条 `CLEANUP` 任务记录，避免每轮都刷任务中心。
- **预检查配合**：`precheck()` 遇到包内容已被清理（`package_path` 为空或不存在）时给出可读失败项（"升级包内容已被自动清理，请重新上传"），而不是抛异常或报令人费解的路径错误。

## 3. 边界（不做）

- 不自动删失败/成功/回滚任务目录（取证与回滚依赖）。
- 不碰任务中心 30 天保留策略与采集记录 7 天策略（`cleanup/service.py` 既有行为不变）。
- 不新增界面选项、不暴露 keep-N 给客户界面（沿用 2026-09-21 决策）。
- 不改 runner、不改升级执行链路。

## 4. 测试计划

1. 单测 `backend/tests/test_upgrade_artifact_housekeeping.py`：
   - 候选与年龄：超 TTL 的 `precheck_failed`/`uploaded` 被清；未超 TTL 的不动；`success`/`failed`/`running`/`cancelled` 即使是候选状态也不动；
   - 保留最近 N：比 TTL 更"新"的 N 个保留；
   - 删除内容：`package/` 与原始归档消失，`task.json` 保留且带 `package_cleaned_at`、路径置空；
   - 守卫：存在活跃任务 → 整轮跳过且不删；`ttl_days<=0` → 关闭；
   - 路径越界（`package_path` 指向任务目录之外）→ 跳过不删；
   - 守护线程：`interval_seconds<=0` 不启动。
2. `.3`：造一个真实的预检失败任务（上传 → 预检失败），把 `created_at`/`updated_at` 改到 8 天前，跑一次清理，断言 `package/` 与归档被删、`task.json` 在、任务中心记录保留；随后 `.3` 容器内全量回归无新增失败。

## 5. 回滚

删除 `housekeeping.py`、`main.py` 的守护线程挂载点与 `V2Settings` 的三个字段即可；被清理的任务只损失包内容（可重新上传），不影响任何已执行任务的取证数据。
