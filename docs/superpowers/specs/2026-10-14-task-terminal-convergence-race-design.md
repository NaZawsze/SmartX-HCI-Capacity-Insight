# 任务终态收敛竞态治理设计（pending #89：幽灵 running 行 + status-404 误报）

- 日期：2026-10-14
- 来源：pending-tasks #89（2026-10-14 用户质询核查后立项）；根因证据见 findings.md
  2026-10-13/14 两节、progress.md 2026-10-14 核查节
- 状态：已批准实施（用户 2026-10-14「修复 88、89，写设计文档」）

## 1. 背景与根因（已定案，2026-10-14 代码级核查）

升级 apply 成功后，post-cleanup（或运维经产品 API「删除升级包」）会删除任务目录，
但 `tasks` 表行停在 `running`——**post-cleanup 删 task.json 与任务行终态写回之间存在
竞态/顺序缺陷**。由此派生两个症状：

1. **幽灵 running 行（产品缺口）**：`.12` `upgrade-6eabea06…` / `.14`
   `upgrade-99996849…` 跨机坐实。`cancel`（只放 pending + 文件存储）、
   `recovery/fail`（只认 task.json）、`DELETE /api/tasks/{id}`（只收终态）全部
   404「升级任务不存在。」；`cleanup_artifacts` 的僵尸判定要 `updated_at` 超 6h
   （`GHOST_TASK_STALE_SECONDS=6*3600`，`cleanup/service.py:189`）才放行——
   **挡空间清理 6 小时**。
2. **status-404 误报（CLI 工具 bug）**：`GET /api/admin/upgrade/status/<id>` 在
   task.json 被删后 404；`delivery/upgrade/upgrade.sh` 的 sed 取不到 `status` 字段
   → 记 `unknown` 空转满 1800s → 误报「超时未收敛」，而升级实际成功
   （`.12`/`.14` 均实测，绕道 `/api/system/health` 验证通过）。

新升级不受影响：单飞守卫按**租约**判定（`task_lease_is_alive`，
`execution.py:213`），过期租约放行。

## 2. 目标

- G1 清理服务能立即识别「runner 执行完、产物被回收、无活租约」的幽灵行，不再被
  挡 6 小时；
- G2 给管理员一条产品化的强制收敛端点（对无 task.json 的 DB 行标记失败）；
- G3 幽灵行在升级中心可见、可操作（status 不再 404 空打死）；
- G4 CLI 不再把「快照缺失但升级实际成功」误报成失败。

## 3. 方案与口径

### 3.1 幽灵判定信号（G1）——正面证据 + 保守兜底

只用「目录不存在」会误伤新建窗口（`test_fresh_running_task_without_dir_still_blocks`
锁定的产品决策），只用「无活租约」同理。采用**正面证据**：

- runner 执行过该任务的持久证据 = runner 状态文件 `rollback_anchors` 持久段存在
  该 task_id 条目（`save_rollback_anchor` 明确设计为跨 `release_lease` 存活，
  见 `statefile.py` 注释；历史保留最近 10 条）；
- 判定：`目录不存在` **且** `rollback_anchors` 有该任务 **且** 无活租约 → 僵尸
  （立即放行，不看新旧）；
- 无锚点证据时**维持原 6h 陈旧规则**（覆盖无锚点的任务类型与锚点被历史淘汰的
  老行）—— backward compatible，既有三态测试全部保持。

### 3.2 强制收敛端点（G2）——recovery/fail 扩展 DB-only 路径

`POST /api/admin/upgrade/recovery/{id}/fail` 现行首行 `_read_task_file` 对幽灵行
404。扩展：task.json 404 时回落 DB 记录，满足

- DB 行存在、状态为 `running`、无活租约（`task_lease_is_alive`）

→ 直接收敛 DB 行到 `failed`（progress=100，message 注明「产物已被回收、结果以
health 版本为准」），返回合成的公开视图。其余情况保持不变：有活租约 → 400（任务
仍被持有，先处理 runner）；无 DB 记录 → 404；终态行 → 400（已收敛，幂等拒绝）。

### 3.3 status 回落 DB（G3）

`status()` 在 task.json 404 时回落 DB 记录（仿 `_read_task_or_pending_record` 的
合成视图，但**不限 pending**），使幽灵行在升级中心可见且能点到「标记失败」。
无 DB 记录仍 404。

### 3.4 CLI 兜底（G4）

`delivery/upgrade/upgrade.sh`：

- 轮询循环内：`STATUS=unknown`（无 status 字段，含 404 detail）时调
  `health_reports_target_version()`——`/api/system/health` 的 `version` 等于
  `TARGET_VERSION` 即判成功（`CONVERGED_VIA_HEALTH=1`）并 break；
- 循环超时后、宣判失败前，再兜底查一次 health（覆盖「每轮都 404」的全程快照缺失）；
- 成功输出追加说明：「任务终态快照缺失（产物已被升级后清理回收），已以 health
  版本到达目标判定升级成功」；
- `TARGET_VERSION` 为 unknown/空时不做兜底（无法比较），维持原行为。

## 4. 边界与不做

- **不动 runner 代码与能力**（AGENTS §6）：post-cleanup 与终态写回的顺序根因在
  runner 侧，其根治需 bump 版本号并随组件发布，另立任务；本设计把症状变得无害
  （可识别、可收敛、不误报）。
- 不改单飞守卫、cancel、delete 的既有语义；
- 不改 `GHOST_TASK_STALE_SECONDS` 的 6h 兜底规则（新增信号只做加法）；
- CLI 改动只碰 `delivery/upgrade/upgrade.sh`（交付脚本，非 runner 镜像内容）。

## 5. 测试计划

| 用例 | 断言 |
| --- | --- |
| 新幽灵立即放行 | anchor 在 + 目录缺 + 无租约 → cleanup 通过、能实际清理 |
| 新鲜窗口不放行 | running + 目录缺 + 无 anchor（沿用旧测试）→ 仍阻塞 |
| 真任务不放行 | running + 目录在（沿用旧测试）→ 仍阻塞 |
| 陈旧无锚点幽灵 | 90 天 + 无 anchor（沿用旧测试）→ 6h 规则仍放行 |
| 有活租约不放行 | anchor 在 + 目录缺 + 租约存活 → 仍阻塞（防止误放行正在跑的） |
| recovery/fail DB-only 收敛 | running + 无租约 + 无 task.json → 200、DB 转 failed、message 含回收语义 |
| recovery/fail 有租约拒绝 | 租约存活 → 400 |
| recovery/fail 无记录 | 未知 id → 404 |
| recovery/fail 幂等拒绝 | 终态行 → 400 |
| status 回落 | 幽灵行 → 200 且含 DB 视图；未知 id → 404 |
| CLI 函数单测（stub curl） | 版本相等 → 0；不等 → 1；health 不可达 → 1；TARGET unknown → 1 |
| CLI 静态锁 | 轮询段含 health 兜底分支；成功段含 CONVERGED_VIA_HEALTH 说明 |

全量回归：`.3` 容器内 `tests.test_v2_cleanup` / `tests.test_stuck_running_recovery` /
`tests.test_us27_us29_fail_cleanup` / CLI 测试文件 + 后端全量无新增失败。

## 6. 回滚

- 后端三处改动均为增量（新增判定分支 / 回落路径），`git revert <commit>` 即可，
  无数据迁移、无存储结构变更；
- CLI 改动随交付脚本，revert 后恢复原轮询逻辑；
- 无 runner 变更 ⇒ 无版本号门槛。
