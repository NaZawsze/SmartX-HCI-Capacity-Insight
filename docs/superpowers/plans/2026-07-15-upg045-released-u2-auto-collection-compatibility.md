# UPG-045 through UPG-048 Released-Input Compatibility Plan

**Goal:** 在不修改已发布 v0.5.1u2 和 runner v0.3.1 资产的前提下，保证 v0.5.2 升级完成后自动采集一次、任务中心终态正确且目标 `.env` 权限为 `0600`。

**Architecture:** 保留 runner 显式 marker 路径；v0.5.2 worker 增加幂等兼容发现，从最新成功平台任务的 manifest 补建缺失 marker，再复用现有消费逻辑。

**Execution boundary:** 当前闭环的 Python、依赖安装、测试、镜像/升级包构建、包体门禁和完整链路全部只在 `10.20.11.3` 执行。本地只维护源码/文档；不连接或操作 `10.20.11.12`。

## Immutable Inputs

```text
v0.5.1u2_sha256=d5f277167445e7636ddfba16b4f780b40d59952467bb1c8e72d2469b43ee0a49
runner_v0.3.1_sha256=d10e15cf7b516d172ebe2f1bc37621f9cf32d8ab3abd548f808ae5c5de151d2c
```

## Task 1: TDD lock the released-bridge failure

- [x] 新增测试：成功平台 task 声明 `post_upgrade.auto_collection=true`，但没有 action/marker 时，worker 必须补建 marker 并执行一次采集。
- [x] 新增测试：多个历史候选只补最新成功平台任务。
- [x] 新增测试：已有 marker 或同 ID 采集任务时不补建、不重复采集。
- [x] 运行测试确认旧实现 RED，失败原因必须是只扫描 marker、无法发现任务。

## Task 2: Minimal compatibility implementation

- [x] 在 `backend/app/v2/worker.py` 增加安全任务读取、平台候选判断和业务时间排序。
- [x] 每轮 `run_pending_post_upgrade_collection()` 前最多补建一个最新候选 marker。
- [x] 不修改 parent task.json，不调用 history/status，不改变显式 marker 状态机。
- [x] 目标测试 GREEN，现有 worker/upgrade/runner 测试保持通过。

## Task 3: Build and static validation

- [x] 只重建 v0.5.2 fix5；v0.5.1u2 和 runner release 包保持原 SHA。
- [x] 运行 10.20.11.3 回归、镜像身份、manifest、checksums、敏感成员和 bundled-image 门禁。
- [x] 记录 fix5 路径和 SHA。

## Task 4: Historical fix5 immutable-source chain

- [x] 恢复真实 `v0.5.1 + runner v0.3.0` 基线。
- [x] 正常升级正式 v0.5.1u2 原包并验收。
- [x] 正常升级正式 runner v0.3.1 原包并验收。
- [x] 正常升级 v0.5.2 fix5，主任务、post-cleanup、自动采集最终均成功。
- [x] 该结果只作为 UPG-045 历史证据；当前 fix8 不再使用该主机做验证。

## Task 5: UPG-046 task-center convergence

- [x] runner 已先写终态时，web-api 仍将父任务投影为 `success/100`。
- [x] 重复 status 查询不刷新 SQLite 任务 `updated_at`。
- [x] 在 `10.20.11.3` 完成相关回归。

## Task 6: UPG-047 failure and UPG-048 fix8

- [x] fix7 完整链路证明正式 compose 的 runner command 会被已发布 handoff compose 覆盖；fix7 标记 `DO NOT USE`。
- [x] fix8 将权限修正移到主 apply 必定重建的 web-api：单文件 RW bind 到 `/run/smartx-runtime.env`，启动前 `chmod 600` 后 exec uvicorn。
- [x] `10.20.11.3` 定向测试、198 项依赖完整回归和真实 Docker bind 验证通过。
- [x] 在 `10.20.11.3` 构建 fix8 并完成所有包体门禁；SHA256 `692aca8b58ad8199c43c02a3771fa4fd7a62f1d7bbf4f198af4bd2e4b2c67733`。

## Task 7: Full fix8 chain on 10.20.11.3

- [x] 审计当前运行时，并保全配套 `smartx.db + .env`。
- [x] 恢复真实 `v0.5.1 + runner v0.3.0`，health、业务数据、旧 project/network/subnet 和目录门禁通过。
- [x] 正常执行已发布 v0.5.1u2 和已发布 runner v0.3.1，固定 SHA 未变化。
- [x] 正常执行 v0.5.2 fix8，主任务、自动采集、post-cleanup 全部成功。
- [x] 数据、凭据、权限、镜像、project/network/subnet、目录清理、任务幂等、history/verification 只读稳定性和 release smoke 全部通过。

## Final Fix8 Evidence

```text
host=10.20.11.3
u2_task=upgrade-5680ff0264c4acbd success
runner_task=upgrade-53ebaff4da3218df success
v0.5.2_task=upgrade-9ad951d4024b2c16 success
auto_collection=post-upgrade-collection-upgrade-9ad951d4024b2c16 success
post_cleanup=post-cleanup-upgrade-9ad951d4024b2c16 success
fix8_sha256=692aca8b58ad8199c43c02a3771fa4fd7a62f1d7bbf4f198af4bd2e4b2c67733
env_sha256=8b644112e7433b5059b10d1f08ee344295f2217f442e7030df1f62c0ac50814f
env_mode=0600 root:root
release_smoke=critical 0, warning 0
```

## Execution Evidence

```text
local_targeted_regression=Ran 174 tests in 7.265s, OK (skipped=3)
local_dependency_complete_regression=Ran 197 tests in 10.370s, OK (skipped=4)
10.20.11.3_dependency_complete_regression=Ran 197 tests in 176.320s, OK (skipped=1)

v0.5.1u2_release_sha256=d5f277167445e7636ddfba16b4f780b40d59952467bb1c8e72d2469b43ee0a49
runner_v0.3.1_release_sha256=d10e15cf7b516d172ebe2f1bc37621f9cf32d8ab3abd548f808ae5c5de151d2c

fix5_package_10.20.11.3=/home/user1/codex-build/packages-upg045-released-u2-auto-collection-fix5/03-v0.5.2-upg045-fix5/smartx-capacity-insight-upgrade-v0.5.2.tar.gz
fix5_package_10.20.11.12=/data/upgrade-packages/upg045-fix5/smartx-capacity-insight-upgrade-v0.5.2.tar.gz
fix5_sha256=1f155cee36b89041e1196452e0f62f5bad91e274bdf034fb71941806ae6daa3a
fix5_static_gates=sidecar,internal-checksums,manifest,image-identity,sensitive-members,bundled-images PASS

10.20.11.12_baseline=v0.5.1 + runner v0.3.0; health all true
10.20.11.12_u2_task=upgrade-a80c00b665340e87 succeeded
10.20.11.12_runner_task=upgrade-fc51e4c53a1b14a1 succeeded
10.20.11.12_intermediate=v0.5.1u2 + runner v0.3.1; health all true
10.20.11.12_fix5_task=upgrade-7b8f26242070ee47 succeeded (historical evidence only)
```

The earlier routing interruption was later resolved and fix5 was confirmed successful. It is retained only as historical UPG-045 evidence. The current UPG-048 acceptance host is exclusively `10.20.11.3`.

## Failure Classification

- v0.5.1u2 上传/预检查/执行失败：归属 v0.5.1u2 release。
- runner release 组件阶段失败：归属 runner release。
- 前两段成功而 v0.5.2 功能缺失或失败：归属 v0.5.2 向后兼容。
- 禁止通过修改 release 包、手工补 marker 或手工触发采集伪造通过。
