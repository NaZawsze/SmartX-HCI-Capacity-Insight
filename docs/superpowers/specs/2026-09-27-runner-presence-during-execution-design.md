# 设计：执行期间 runner 在场判定（US-08 / S1-3）

状态：**已实施并验证**（2026-09-27）。问题台账 [upgrade-strategy-issues.md](../../upgrade-strategy-issues.md) US-08；执行顺序 [../plans/2026-09-27-remaining-work-sequence.md](../plans/2026-09-27-remaining-work-sequence.md) S1-3；根因记录 [findings.md](../../../findings.md) 2026-09-27「runner 两条心跳通道」。

## 1. 取证（`.3` 真实升级）

US-08 的原假设是"单个步骤耗时超过 `RUNNER_HEARTBEAT_STALE_SECONDS = 30` 会被判 stale"。在 `.3` 上跑一次真实同版本升级（v0.5.3 → v0.5.3，候选包 `b9560eee…`，task **`upgrade-c921c5bc0aad72e5`**，结果 success，耗时约 75s）并每 5s 采样两条心跳通道，实测比假设更严重：

| 通道 | 表 | 执行期间表现 |
| --- | --- | --- |
| 实例心跳 | `upgrade_runner_state.heartbeat_at` | **整段执行期冻结**（采样 T02 `14:34:07` → T19 任务结束，约 75s 未动） |
| 任务租约心跳 | `upgrade_task_leases` | 由 `main.py::_heartbeat_until_done` 每 5s 刷新（执行期间由 runner 心跳线程负责） |

根因（读码确认）：`update_runner_state()` 只在 `run_pending_once()` 开头调用一次，而任务在同一个 `run_pending_once` 调用内同步执行完（执行期只跑那个 5s 心跳线程，只续**租约**）。所以"实例心跳新鲜"在执行期必然为假，30s 阈值在这里毫无余量。

## 2. 影响面（web-api 侧消费点）

| 消费点 | 只用实例心跳时的行为 |
| --- | --- |
| `_active_runner_state()` | 主通道失活 → 落到 docker 兜底，`source="docker"` |
| `_check_runner_protocol()`（预检查） | 要求 `source == "heartbeat"` → 执行期并发预检查报**"未检测到 upgrade-runner 心跳…请先升级 upgrade-runner 到 v0.3.1"**（误导性失败） |
| `component_catalog().compatible` | 同样要求 `source == "heartbeat"` → 升级页"Runner 版本（满足/不满足平台要求）"在执行期显示**不满足** |
| `health.runner_version` | 有 docker 探测兜底，通常仍能报出版本（依赖容器内 docker CLI 与 socket） |

`/api/admin/upgrade/version` 只返回平台版本 `{"version": …}`，与 runner 状态无关（此前一次采样把它误读成"API 报 None"，已纠正）。

## 3. 修复口径（**不改 runner、不升版本**）

新增 `backend/app/v2/upgrade/service/runner_presence.py`：

- `instance_heartbeat_is_fresh(state)`：实例心跳在 30s 内。
- `active_task_lease_is_fresh(database)`：`upgrade_task_leases` 中任一租约 `lease_expires_at > now`，或 `heartbeat_at` 在 30s 内 → 证明 runner 正在执行、仍然在场。
- `presence_source(database, state)`：返回 `heartbeat` / `task_lease` / `None`；`RUNNER_PRESENCE_SOURCES = {heartbeat, task_lease}` 供协议校验与组件目录共用，避免各处写死字符串。

三处消费点改用同一判定：`execution.py::_active_runner_state()`（并给 `source` 打上真实来源）、`execution.py::_check_runner_protocol()`、`intake.py::component_catalog()`；`system/health.py::_active_runner_version()` 复用同一函数（并删掉本地重复的 30s 常量）。

**为什么不在 runner 侧修**：让 runner 在执行期也刷新实例心跳要改 runner 代码 → 按 AGENTS §6/§8 必须经用户同意并 bump `RUNNER_VERSION` + 重新交付组件包；而 v0.3.2 的交付决策本身还悬着。web-api 侧修的是同一个症状、风险面最小，且不需要动交付物。runner 侧改进登记为待办，随下次 runner 交付一起做。

## 4. 边界

- **不影响 runner 重启窗口的判定**：runner 被替换期间没有有效租约，仍报"未检测到心跳"——这是期望行为，49-50 的预检查提示已覆盖。
- **任务结束后的一个轮询周期**（≤3s）：租约已释放、实例心跳尚未被下一次空闲轮询刷新，此刻两条通道都不新鲜（`.3` 实测 T21 抓到 `source=None`）。生产里 `_active_runner_state()` 还有 docker 兜底（web-api 镜像内含 docker CLI 且挂了 socket），可覆盖这个瞬时窗口；不额外加宽限。
- 不改变其他守卫（US-23 单飞、`runner_actions` 动作级校验、post-cleanup 健康断言）。
- 租约通道判定失败（DB 异常）按"不在场"处理，与旧行为一致（fail-safe 到原语义）。

## 4.1 `.3` 前后对照实证（2026-09-27）

| 场景 | 旧镜像（部署在跑） | 新代码（部署树覆盖） |
| --- | --- | --- |
| 另一个升级**正在执行**时做预检查 | task `upgrade-baf0dd837c67ad3f`：`runner_protocol` **False**「未检测到 upgrade-runner 心跳，无法确认升级执行器能力。请先升级 upgrade-runner 到 v0.3.1。」而同一次预检查的 `runner_actions` 为 **True**（14 个动作全部支持）→ runner 明明在场 | 同一时刻（升级 `upgrade-b52fbadc1591ab5c` 仍 running、租约 `heartbeat_at=14:43:15` 有效）：`presence_source=task_lease`、`_active_runner_version()=v0.3.1 (source=task_lease)`、`runner_protocol ok=True` |
| 执行期心跳通道 | 实例心跳冻结 75~108s（两次实测），租约每 5s 续 | 前 ~30s 走 `heartbeat`，之后整段执行走 `task_lease` |

## 5. 测试计划

`backend/tests/test_runner_presence_during_execution.py` 13 例：实例心跳新鲜 → `heartbeat`；实例心跳过期 + 有效租约 → `task_lease` 且 `_active_runner_version()` 返回版本；实例过期且无租约 → `RUNNER_NOT_DETECTED`；租约过期/心跳过旧 → 不在场；`lease_expires_at` 过期但心跳仍新 → 在场；DB 查询异常 → 不在场；预检查 `runner_protocol` 接受 `task_lease`；组件目录 `compatible=True`；health 用租约通道取版本、无租约时退回探测。

`.3`：容器内全量回归 + 修复后再跑一次同样的升级实验，观察执行期"runner 在场"判定。

## 6. 回滚

删除 `runner_presence.py` 与三处引用、恢复 `execution.py` 内的 `_runner_state_is_fresh` 旧实现即可；无数据影响、无 runner 参与。
