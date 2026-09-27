# 49-49 设计：v0.5.3 升级后自动采集改为平台侧调度（不再让 runner 执行）

状态：设计（实施随任务项 49-49）。2026-09-27 用户批准「A+B 都做」后落此设计。

## 1. 背景

- 已发布 runner v0.3.1（Release 资产 `d10e15cf…`，25 动作）**没有** `post_upgrade.schedule_collection`；
- 以 v0.5.2 为源升 v0.5.3 时，计划由**源端** `v0.5.2` 的 web-api 编译（`backend/app/v2/upgrade/service/execution.py:32 → compile_execution_plan(task["manifest"])`），而 v0.5.2 编译器看到 manifest `post_upgrade.auto_collection=true` 就会下发该动作；
- runner 在 `backend/app/upgrade_runner/engine.py:104` 抛 `Runner 不支持动作：post_upgrade.schedule_collection` → **平台已切换之后**失败（实测 task `upgrade-cede491efb9b1345`）。

**关键约束（决定方案形态）**：编译动作的代码在**源端已发布的镜像里**，改本仓库 `compiler.py` 对 `v0.5.2 → v0.5.3` 这一步**无效**。唯一还能控制的输入是**目标包的 manifest**。

## 2. 口径

1. **`scripts/build_upgrade_package.py` 生成的 manifest**：
   - `post_upgrade.auto_collection` 由 `true` → **`false`**（老编译器只认这个键，于是**不下发**该动作）；
   - 新增 `post_upgrade.platform_collection: true`（新键，老编译器不认识、忽略；新 worker 认识）。
2. **`backend/app/v2/worker.py::_auto_collection_platform_task`**：改为 `platform_collection or auto_collection`（兼容只带老键的历史包）。
3. **`backend/app/v2/upgrade/compiler.py`**：**不再** append `post_upgrade.schedule_collection` 动作（源端是 v0.5.3 及以后时同样不下发），相关 `ACTION_CAPABILITIES`/常量保留不动（runner 仍实现该动作，历史任务可能引用）。
4. 采集执行链路**完全复用现状**：`worker.py:229 run_pending_post_upgrade_collection`（5 秒轮询）+ `worker.py:195 _ensure_post_upgrade_collection_marker`（缺标记自建，`source=target_worker_compatibility`）。

## 3. 为什么安全

- 读码确认：runner 的该动作**只写标记文件** `upgrades/<task>/post-upgrade-collection.json`，不采集（`upgrade_runner/actions.py:2115`）；真正采集由平台 worker 完成，且 worker **本来就会在缺标记时自建标记**。
- `post_upgrade.create_cleanup_task`（post-cleanup）是**独立键**，不受影响；runner 已实现 `post_upgrade.schedule_cleanup`，清理链路不变。
- 已逐动作比对：v0.5.3 计划其余 12 个动作 + post-cleanup 7 个动作，已发布 runner **全部支持** → 去掉这一条后无需升级 runner。

## 4. 边界（不做）

- 不改 runner 代码/版本（runner 侧归方案 B，独立 bump v0.3.2）。
- 不改已发布包（`d10e15cf`、`692aca8b`、`54aa8807`）。
- 不移除 `post_upgrade.schedule_collection` 动作实现与常量映射。
- 不改变「升级后自动采集失败不改写平台升级成功状态」的既有口径。

## 5. 测试计划

- `backend/build_tests/test_v2_package_builders.py`：
  - `manifest["post_upgrade"]["platform_collection"] is True`、`auto_collection is False`；
  - `compile_execution_plan` 结果 `assertNotIn("post_upgrade.schedule_collection", action_types)`（原 270/1056 断言翻转）；
  - 顺序断言 279/280 相应删除（改为 `task.sync_runtime_state` → `post_upgrade.schedule_cleanup` 的顺序保持）。
- `backend/tests/test_v2_worker.py`：新增「manifest 只带 `platform_collection`」「两者都带」「只带 `auto_collection`（历史包）」三例；既有用例继续通过（兼容读取）。
- `backend/tests/test_upgrade_runner_engine.py`：runner 侧动作测试**不动**（runner 仍实现该动作）。
- 远端验收（硬门禁）：**严格按 [docs/superpowers/plans/2026-09-27-v053-full-chain-acceptance-plan.md](docs/superpowers/plans/2026-09-27-v053-full-chain-acceptance-plan.md) 执行**——`.12` 恢复 v0.5.1 基线 → `u2(d5f277) → runner v0.3.1(d10e15cf 已发布) → v0.5.2(692aca8b) → runner v0.3.2(本轮组件包) → v0.5.3(候选包)`。
- **口径修正（2026-09-27，用户选定 B-b 后）**：B-b 使平台包声明 runner 镜像 `v0.3.2`，预检查 `images` 检查（`docker image inspect`）会先拦住没有该镜像的现场，因此**「已发布 v0.3.1 直升 v0.5.3」不再成立**。A 的验收改为：
  1. 升级计划 `actions` **不含** `post_upgrade.schedule_collection`（含 `post_upgrade.schedule_cleanup`）；
  2. 升级成功后**平台自建标记** `post-upgrade-collection.json`（`source=target_worker_compatibility`）并创建升级后自动采集任务（Tower 不可达只记环境限制）；
  3. 主任务 success、post-cleanup success、8 项验收全过。

## 6. 回滚

- 只动 3 处文件（`scripts/build_upgrade_package.py`、`worker.py`、`compiler.py`）+ 测试，还原即回滚；不触碰任何已发布物、不动 runner。

## 7. 与方案 B 的关系

- **B-b 选定后（2026-09-27）**：A 负责「升级计划不再要求 runner 实现那条多余动作 + 升级后由平台自己完成采集」；B（runner v0.3.2 组件升级前置 + 动作级预检查）负责「早失败 + 防复发」。**现场直升的前提由 B-b 改为「先做 runner 组件升级到 v0.3.2」**（预检查 `images` 检查给出明确提示）。
- B 的动作级校验只在**源端 ≥ v0.5.3** 时生效（预检查代码跑在源端），不覆盖 `v0.5.2 → v0.5.3` 这一次；那一次的拦点是镜像存在性检查。
