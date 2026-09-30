# task_plan 历史归档：专项升级链路（已收官整节）

> 归档日期：2026-09-30 ｜ 来源：仓库根 [`task_plan.md`](../../task_plan.md) ｜ 切片范围：4 个 `## ` 小节（首「当前执行项 - UPG-036 / UPG-037 / UPG-038 / UPG-039 v0.5.2 final chain」→ 末「UPG 修复链路摘要（全部完成）」）
> 内容为逐字搬运（脚本按 `^## ` 标题切片），与原文 byte 级一致，未改写 / 重排 / 合并。
> 本文件只读：历史记录此后不再改写；这 4 节在 [`task_plan.md`](../../task_plan.md) 原位置已换成指针行；完整索引见 [`docs/doc-map.md`](../doc-map.md)。

## 当前执行项 - UPG-036 / UPG-037 / UPG-038 / UPG-039 v0.5.2 final chain

状态：UPG-039 已在 `10.20.11.3` 完整链路验证通过。此前 UPG-038 follow-up 的 post-cleanup 失败根因是 handoff 后 runner 容器内路径视角变化，cleanup guard 把 host target DB 路径读错，并把容器 `/data/smartx.db` 误当 legacy DB。现已修复 runner v0.3.1 `data_migration_guard` host/container 路径归一化，v0.5.2 主升级和 post-cleanup 均成功。

目标：

- 修复 runner 组件升级实际成功但 start API 因 task revision 竞争误返回 HTTP 409 的问题。
- 保留 UPG-035 `upgrade.verification.latest_package` 只指向真实平台包的修复。
- 重打包含最新修复的 `v0.5.1u2` 和 `v0.5.2` 升级包。
- 验证完整链路：
  `v0.5.1 + runner v0.3.0 -> v0.5.1u2-upg036 -> runner-v0.3.1-upg032-historyfix -> v0.5.2-upg035-upg036`

最终包：

```text
v0.5.1u2-upg036-runner-start-conflict
path=/home/user1/codex-build/packages-upg036-runner-start-conflict/01-v0.5.1u2-runner-start-conflict/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz
sha256=d5f277167445e7636ddfba16b4f780b40d59952467bb1c8e72d2469b43ee0a49

runner-v0.3.1-upg032-historyfix
path=/home/user1/codex-build/packages-upg032-historyfix/02-runner-v0.3.1-historyfix/smartx-upgrade-runner-v0.3.1.tar.gz
sha256=d10e15cf7b516d172ebe2f1bc37621f9cf32d8ab3abd548f808ae5c5de151d2c

v0.5.2-upg035-upg036
path=/home/user1/codex-build/packages-upg036-runner-start-conflict/03-v0.5.2-upg035-upg036/smartx-capacity-insight-upgrade-v0.5.2.tar.gz
sha256=5ab9d41d1192efb794c9a43db4d340ef86bbeb0e5a4755118e517f715cdca2cc
```

验收：

- [已通过] 本地回归：`Ran 144 tests in 5.735s, OK (skipped=1)`。
- [已通过] 远端依赖完整回归：`Ran 175 tests in 186.825s, OK`。
- [已通过] 镜像身份闸门：`v0.5.1u2` 包内 web-api `/app/VERSION=v0.5.1u2`、`/app/RUNNER_VERSION=v0.3.0`；`v0.5.2` 包内 web-api `/app/VERSION=v0.5.2`、`/app/RUNNER_VERSION=v0.3.1`。
- [已通过] 两个平台包内 compose 不含 `SMARTX_IMAGE_TAG`、`SMARTX_RUNNER_IMAGE_TAG`、`SMARTX_APP_VERSION`、`SMARTX_RUNNER_VERSION`。
- [已通过] 完整链路 task：
  - `v0.5.1u2=upgrade-1e3345094fc9c4dc`
  - `runner=upgrade-a31572ffb4d37e54`
  - `v0.5.2=upgrade-f3e7160e4397acf0`
  - `post-cleanup=post-cleanup-upgrade-f3e7160e4397acf0`

后续计划：

- UPG-037 已记录到专项升级文档：升级期间前端对 web-api 重启窗口做 5 分钟容错；`/api/admin/upgrade/verification` runner version 对齐 health/component fallback。
- UPG-037 只计划重打 v0.5.2；不修改已验证的 `v0.5.1u2` 和 `runner v0.3.1` 核心链路包。
- UPG-037 详细执行边界已补充：前端容错只限升级相关轮询，5 分钟后必须显示原始错误或 `Internal Server Error`；后端 verification runner fallback 只用于展示，不能放宽 runner_protocol 预检查。
- UPG-037 验证要求：在 `10.20.11.3` 恢复 `v0.5.1 + runner v0.3.0` 后重新走正常链路，失败时先记录根因并停止，不继续静默修复。
- UPG-038 已记录到专项升级文档：v0.5.2 `filesystem.prepare` 不能只用“目标 smartx.db 存在”判断数据有效；必须比较旧库/目标库业务计数，空目标库可被旧业务库替换，双业务库冲突必须硬失败，cleanup 必须在数据迁移有效后才能删除旧目录。
- [已通过] runner 组件升级 start 返回 HTTP 200，不再出现“任务已成功但 API 返回 409”的假失败。
- [已通过] 最终健康：`version=v0.5.2`、`runner_version=v0.3.1`、`prometheus=true`。
- [已通过] `upgrade.verification.latest_package` 指向真实 v0.5.2 平台任务 `upgrade-f3e7160e4397acf0`，SHA 非空且不是 post-cleanup。
- [已通过] 旧 network 和 legacy 目录已清理，目标目录均存在。
- [已通过] release smoke：`critical_count=0`、`warning_count=0`。
- [未通过] UPG-038 链路复测：
  - `v0.5.1u2=upgrade-0d944fd29242c0fb`
  - `runner=upgrade-b3b5f205f14f451b`
  - `v0.5.2=upgrade-c5510018291d4656`
  - `post-cleanup=post-cleanup-upgrade-c5510018291d4656`
  - health/version/docker/project/network 均达到目标，但目标 DB `/data/smartx-storage-forecast/app/smartx.db` 只有 96K，`towers=0`、`clusters=0`、`vm_latest=0`、`vm_volumes=0`。
  - v0.5.2 task checkpoint 显示 `copied_app_sources=[]`，post-cleanup 随后删除旧 `/data/smartx-capacity-insight-data`。
  - 下一步：修复 runner v0.3.1 `filesystem.prepare` 数据迁移策略和 v0.5.2 cleanup 门禁，重打 runner/v0.5.2 包，在 `10.20.11.3` 重新完整链路验证。
- [未通过] UPG-038 follow-up 链路复测：
  - `v0.5.1u2=upgrade-60dd4ec8163e1df0`
  - `runner=upgrade-a272344cdbf0ed85`
  - `v0.5.2=upgrade-14d79d309b95ff76`
  - `post-cleanup=post-cleanup-upgrade-14d79d309b95ff76`
  - v0.5.2 主任务成功，最终业务库实际已迁移到 host `/data/smartx-storage-forecast/app/smartx.db`，计数为 `towers=1`、`clusters=1`、`vm_latest=523`、`vm_volumes=89530`。
  - post-cleanup 失败原因不是数据未迁移，而是 target runner 容器内路径视角变化：host `/data/smartx-storage-forecast/app` 挂载为容器 `/data`，cleanup guard 仍按 host 路径 `/data/smartx-storage-forecast/app/smartx.db` 检查目标库，并把容器 `/data/smartx.db` 误当 legacy 库。
  - 已由 UPG-039 修复：runner v0.3.1 `data_migration_guard` 会把 host target DB 映射到容器 `/data/smartx.db`，解析后等于 target 的 legacy 路径会剔除，避免误判。
- [已通过] UPG-039 完整链路复测：
  - `v0.5.1u2=upgrade-528d1f42aa5b62dd`
  - `runner=upgrade-4b1c542232cce245`
  - `v0.5.2=upgrade-37fbd66390f39880`
  - `post-cleanup=post-cleanup-upgrade-37fbd66390f39880`
  - 最终健康：`version=v0.5.2`、`runner_version=v0.3.1`、`checks.prometheus=true`。
  - 最终业务库：`/data/smartx-storage-forecast/app/smartx.db`，`users=1`、`towers=1`、`clusters=1`、`collection_runs=37`、`vm_latest=523`、`vm_volumes=89530`。
  - 旧目录 `/opt/smartx-storage-forecast`、`/data/smartx-capacity-insight-data`、`/data/upgrades`、`/data/backups`、`/data/exports`、`/data/compose-runtime`、`/prometheus-data` 均已清理。
- [已通过] UPG-040 空业务库完整链路复测：
  - 修复 post-cleanup 对空来源业务库的误拦截：仅当父任务 `filesystem.prepare.source_db_counts` 明确无业务数据且 target DB 有效时，才以 `parent_source_had_no_business_data` 放行。
  - 10.20.11.3 空业务库链路：`upgrade-891334c5ac85007b -> upgrade-52f6c7c53b89ad53 -> upgrade-a3734551cbbaff02`，post-cleanup success。
  - 10.20.11.12 空业务库链路：`upgrade-79cae85f494677a2 -> upgrade-3ec9762ff81c5101 -> upgrade-5a22d9f11248f7f3`，post-cleanup success。
  - 最终两台机器均为 `v0.5.2 + runner v0.3.1 + prometheus=true`；legacy `/opt`、`/data/*` runtime、`/data/smartx-capacity-insight-data`、`/prometheus-data` 均已清理。

## 当前执行项 - UPG-031 / fix20

状态：已在 `10.20.11.3` 完整链路验证通过。

目标：

- 解决 fix19 链路中 `target_app_residual_paths` 删除 final runtime 活动挂载点的问题。
- `target_app_residual_paths` 不再生成；旧包传入这些路径时 runner 必须识别并跳过活动挂载点。
- 生成并验证：
  - `v0.5.1u2-fix20-skip-active-target-mountpoints`
  - `runner-v0.3.1-postcleanupfix7-skip-active-target-mountpoints`
  - `v0.5.2-postcleanupfix7-skip-active-target-mountpoints`

已完成：

- v0.5.2 manifest 的 `legacy_cleanup.target_app_residual_paths` 改为空列表。
- runner cleanup 对 `/data/smartx-storage-forecast/app/upgrades`、`app/backups`、`app/exports`、`app/compose-runtime` 这类 final runtime mountpoint 返回 skipped。
- 本地 123 个升级相关单测通过。
- `10.20.11.3` 远端 123 个升级相关单测通过。
- 已生成并静态验证三个候选包：
  - `v0.5.1u2-fix20-skip-active-target-mountpoints`
  - `runner-v0.3.1-postcleanupfix7-skip-active-target-mountpoints`
  - `v0.5.2-postcleanupfix7-skip-active-target-mountpoints`
- 完整链路已通过：
  `v0.5.1 + runner v0.3.0 -> v0.5.1u2-fix20 -> runner-v0.3.1-postcleanupfix7 -> v0.5.2-postcleanupfix7`
- post-cleanup 成功，旧 `/opt/smartx-storage-forecast` 和 legacy `/data/upgrades`、`/data/backups`、`/data/exports`、`/data/compose-runtime`、`/data/smartx-capacity-insight-data`、`/prometheus-data` 均已清理。

验收：

- [已通过] `10.20.11.3` 完整链路：
  `v0.5.1 + runner v0.3.0 -> v0.5.1u2-fix20 -> runner-v0.3.1-postcleanupfix7 -> v0.5.2-postcleanupfix7`
- [已通过] 主 v0.5.2 task 和 post-cleanup task 都保留在 `/data/smartx-storage-forecast/upgrades`。
- [已通过] 旧宿主机路径清理成功或明确显示 missing。
- [已通过] 最终健康：`version=v0.5.2`、`runner_version=v0.3.1`、`prometheus=true`。

## 专项升级链路历史任务归档（已完成）

`v0.5.1 + runner v0.3.0 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2` 链路已在 `10.20.11.3` / `10.20.11.12` 完整验证通过。详细修复计划、失败记录、包路径/SHA、任务 ID 归档到：

- 任务与发现归档：`docs/v0.5.1-to-v0.5.2-upgrade-chain-task-findings.md`
- 当前执行与验证记录：`docs/v0.5.1-to-v0.5.2-upgrade-chain-worklog.md`

根目录不再承载历史 Phase 细节。

## UPG 修复链路摘要（全部完成）

UPG-041~048 已在 v0.5.2 fix8 中全部闭环。覆盖：升级后自动采集、任务中心投影、.env 权限 0600、凭据迁移安全门禁、credential helper host path 映射、verification 最近包排序、已发布 u2 兼容。最终链路 `v0.5.1u2(d5f277) -> runner v0.3.1(d10e15) -> v0.5.2 fix8(692aca8b)` 验证通过，release smoke `critical=0/warning=0`。

详见 `docs/v0.5.1-to-v0.5.2-upgrade-chain-worklog.md` 和 Release。

