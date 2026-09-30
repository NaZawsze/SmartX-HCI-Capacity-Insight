# progress 历史归档：2026-07

> 归档日期：2026-09-30 ｜ 来源：仓库根 [`progress.md`](../../progress.md) ｜ 切片范围：52 个 `## ` 小节（首「2026-07-08 UPG-036 本地回归验证」→ 末「2026-07-17 UPG-048 fix8 远端验证与 .3-only 约束」）
> 内容为逐字搬运（脚本按 `^## ` 标题切片），与原文 byte 级一致，未改写 / 重排 / 合并。
> 本文件只读：历史记录此后不再改写；原位置留有指针，索引见 [`progress.md`](../../progress.md) 顶部「历史归档索引」。

## 2026-07-08 UPG-036 本地回归验证

状态：已完成

本轮继续 `v0.5.1 + runner v0.3.0 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2` 链路，处理 UPG-036：runner 组件升级实际成功但 start API 因 task revision 竞争返回 409 的问题。

本地确认：

- 代码已包含 runner-only final save conflict 恢复逻辑。
- 回归测试已覆盖新 runner 在 `docker compose up -d upgrade-runner` 期间先写入 `success`，旧 web-api 最终保存撞 revision 的场景。
- 第一次测试命令写错类名 `UpgradeServiceTest`，实际类名为 `V2UpgradeServiceTest`；这是测试选择器错误，不是产品失败，已记录到专项 worklog。

验证命令：

```text
PYTHONPATH=backend python3 -m unittest \
  backend.tests.test_v2_upgrade.V2UpgradeServiceTest.test_runner_bootstrap_returns_success_when_new_runner_wins_final_task_save \
  backend.tests.test_v2_upgrade \
  backend.tests.test_v2_foundation \
  backend.tests.test_upgrade_runner_engine \
  backend.tests.test_v2_package_builders \
  backend.tests.test_upgrade_protocol
```

结果：

```text
Ran 144 tests in 5.735s
OK (skipped=1)
```

下一步：

- 同步当前 worktree 到 `10.20.11.3`。
- 在远端 web-api 镜像环境跑依赖完整回归。
- 重打包含该修复的 `v0.5.1u2` 和 `v0.5.2` 包。

远端验证补充：

```text
host=10.20.11.3
source=/home/user1/codex-build/worktree-upg036-runner-start-conflict
docker_image=nazawsze/smartx-hci-capacity-insight-web-api:v0.5.2

first_attempt:
  result=FAILED errors=9
  root_cause=/src was mounted read-only, package builder tests need temporary writes to VERSION/.env

rerun_with_writable_mount:
  result=Ran 175 tests in 186.825s, OK
```

远端打包与静态闸门：

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

静态闸门结果：

```text
v0.5.1u2 image identity:
  VERSION=v0.5.1u2
  RUNNER_VERSION=v0.3.0
  no minimum_runner_version
  source_versions=v0.5.0,v0.5.1,v0.5.1u1,v0.5.1u2

v0.5.2 image identity:
  VERSION=v0.5.2
  RUNNER_VERSION=v0.3.1
  minimum_runner_version=v0.3.1
  manifest keys include source_compatibility, environment_transitions, directory_transition, legacy_cleanup, post_upgrade

both platform packages:
  package compose has no SMARTX_IMAGE_TAG / SMARTX_RUNNER_IMAGE_TAG / SMARTX_APP_VERSION / SMARTX_RUNNER_VERSION
```

完整链路验证：

```text
host=10.20.11.3
baseline=v0.5.1 + runner v0.3.0 + prometheus=true

script_notes:
  - shell heredoc 链路脚本被引号破坏，未形成有效升级任务。
  - base64 脚本首次本地生成缺少 import sys，未执行远端升级。
  - 第一版 Python 链路脚本在 v0.5.1u2 web-api 重启窗口遇到 login connection refused 后退出；实际 v0.5.1u2 task 已成功。
  - resume 脚本增加重试后完成 runner 和 v0.5.2 链路。

v0.5.1u2:
  task=upgrade-1e3345094fc9c4dc
  start_http=200
  status=succeeded
  health_after=v0.5.1u2 + runner v0.3.0 + prometheus=true

runner v0.3.1:
  task=upgrade-a31572ffb4d37e54
  start_http=200
  status=succeeded
  health_after=v0.5.1u2 + runner v0.3.1 + prometheus=true
  UPG-036=false HTTP 409 已修复

v0.5.2:
  task=upgrade-f3e7160e4397acf0
  start_http=200
  status=succeeded
  post_cleanup=post-cleanup-upgrade-f3e7160e4397acf0 succeeded
  health_after=v0.5.2 + runner v0.3.1 + prometheus=true

final:
  network=smartx-hci-capacity-insight-net 10.249.251.0/24
  old_paths_missing=/opt/smartx-storage-forecast,/data/upgrades,/data/backups,/data/exports,/data/compose-runtime,/data/smartx-capacity-insight-data,/prometheus-data
  target_paths_exist=/data/smartx-storage-forecast/project,/data/smartx-storage-forecast/app,/data/smartx-storage-forecast/upgrades,/data/smartx-storage-forecast/compose-runtime,/data/smartx-storage-forecast/prometheus
  component_history_count=1
  verification.latest_package.sha256=5ab9d41d1192efb794c9a43db4d340ef86bbeb0e5a4755118e517f715cdca2cc
  release_smoke critical_count=0 warning_count=0
```

## 2026-07-08 升级链路专项 MD 边界确认

状态：已完成

用户再次确认：`v0.5.1 + runner v0.3.0 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2` 这条链路的修复和任务计划需要单独列一个 MD，相关 task/findings 从根文档拉出来，等全部完成后再总结回 `findings.md` 和 `task_plan.md`。

本次确认结果：

- 专项归档文件已存在：`docs/v0.5.1-to-v0.5.2-upgrade-chain-task-findings.md`。
- 当前执行 worklog 已存在：`docs/v0.5.1-to-v0.5.2-upgrade-chain-worklog.md`。
- 根 `task_plan.md` 和 `findings.md` 已保留入口和摘要，不继续承载链路细节。
- 在专项归档文件中补充 `Completion Summary Contract`，明确链路闭环后再按顺序回填根 `task_plan.md` / `findings.md`，且只回填最终结论，不回填过程日志。

## 2026-07-08 升级链路 task/findings 原文归档拆分

状态：已完成

用户要求将 `v0.5.1 + runner v0.3.0 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2` 链路的修复任务和 findings 单独列为 MD，避免根级 `task_plan.md` / `findings.md` 继续膨胀。

本次整理：

- 新增 `docs/v0.5.1-to-v0.5.2-upgrade-chain-task-findings.md`。
  - 原文归档了 root `task_plan.md` 中 `Phase 26 v0.5.2 Compose Project/Network Migration Fix` 及其后的链路专项历史任务块。
  - 追加归档了 root `task_plan.md` 中散落在中部的 `Phase 41 - v0.5.1u2-fix15 runner bootstrap 目标根挂载`。
  - 原文归档了 root `findings.md` 中 `Phase 32 v0.5.1u2-fix9 Runner Active Version 根因发现` 及其后的链路专项历史发现块。
- `task_plan.md` 只保留专项链路入口、当前摘要和“完成后再回填最终结论”的规则。
- `findings.md` 只保留专项链路入口、稳定项目级结论和“完成后再回填最终根因”的规则。
- `docs/v0.5.1-to-v0.5.2-upgrade-chain-worklog.md` 增加 archive 入口，后续当前链路执行记录仍写 worklog。

后续规则：

- 历史 task/findings 查 archive。
- 当前失败、修复计划、包和验证查 worklog。
- 根文档只在链路最终闭环后回填摘要。

## 2026-07-08 升级链路 task/findings 专项文档边界整理

状态：已完成

用户要求不要继续把 `v0.5.1 + runner v0.3.0 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2` 链路的修复和任务计划散写到 `task_plan.md` / `findings.md`，而是单独维护一个 MD，等全部完成后再汇总回根计划和根发现。

本次整理：

- `docs/v0.5.1-to-v0.5.2-upgrade-chain-worklog.md`
  - 增加 `Document Boundary`，明确该文件是链路详细记录唯一入口。
  - 增加 `Root Task and Findings Extraction`，列出已从 `task_plan.md`、`findings.md`、`progress.md` 和升级 issue/ledger 文档抽出的范围。
  - 明确后续失败证据、修复计划、包路径/SHA、task ID、health/docker/history/目录验收都先写这里。
- `task_plan.md`
  - 增加专项升级链路文档入口。
  - 明确主计划暂时只保留最终阶段摘要。
- `findings.md`
  - 增加专项升级链路发现归档入口。
  - 明确主发现暂时只保留稳定结论和项目级注意事项。

后续规则：

- 链路未完全闭环前，不再把详细过程追加到 `task_plan.md` / `findings.md`。
- 链路完成后，再把最终结论、最终包、验收结果和不可重复问题摘要回填到根文档。

## 2026-07-08 UPG-034 v0.5.2 report-all-vms 打包与完整链路验证

状态：已在 10.20.11.3 完整链路验证通过

本轮完成：

- v0.5.2 报表导出 all-VM 优化已进入新包。
- 远端依赖完整回归通过：

```text
docker image=nazawsze/smartx-hci-capacity-insight-web-api:v0.5.2
PYTHONPATH=/src/backend HOSTNAME= python -m unittest \
  backend.tests.test_v2_foundation \
  backend.tests.test_v2_upgrade \
  backend.tests.test_upgrade_runner_engine \
  backend.tests.test_v2_package_builders \
  backend.tests.test_upgrade_protocol \
  backend.tests.test_v2_reports \
  backend.tests.test_v2_report_exports

Ran 173 tests in 168.373s
OK
```

新包：

```text
v0.5.2-report-all-vms
path=/home/user1/codex-build/packages-upg034-report-all-vms/03-v0.5.2-report-all-vms/smartx-capacity-insight-upgrade-v0.5.2.tar.gz
sha256=23d275a3e44bc9b45c083f33cac505107f9a03ac53b42120a4cf9a67f2236cf3
```

## 2026-07-09 UPG-039 cleanup guard pathmap 验证闭环

状态：已在 `10.20.11.3` 完整链路验证通过。

本轮完成：

- 修复 runner v0.3.1 `data_migration_guard` 的 host/container 路径归一化。
- 目标 DB host path `/data/smartx-storage-forecast/app/smartx.db` 在 target runner 中解析为 `/data/smartx.db`。
- 归一化后等于 target DB 的 legacy path 会跳过，原因记录为 `same_as_target_after_handoff`。
- handoff 后 legacy source 不可读或被剔除，但 target DB 有业务数据时，cleanup guard 允许继续，原因记录为 `legacy_sources_unavailable_after_handoff`。
- 仍保留硬门禁：如果可读 legacy DB 业务计数高于 target DB，则 cleanup 失败。

验证：

```text
local_tests=Ran 151 tests in 6.156s, OK (skipped=1)
remote_tests=Ran 151 tests in 53.682s, OK (skipped=1)
host=10.20.11.3
remote_worktree=/home/user1/codex-build/worktree-upg039-guard-pathmap-20260709204525
```

包：

```text
runner=/home/user1/codex-build/packages-upg039-guard-pathmap/02-runner-v0.3.1-upg039-guard-pathmap/smartx-upgrade-runner-v0.3.1.tar.gz
runner_sha256=fff608aed4c59069ed870858a3c64ccdca62f52d7d3b6faee3c47e2675d22e9d

v0.5.2=/home/user1/codex-build/packages-upg039-guard-pathmap/03-v0.5.2-upg039-guard-pathmap/smartx-capacity-insight-upgrade-v0.5.2.tar.gz
v0.5.2_sha256=04e557c04ea1d63bcc512122ed10a59eca105c186edcf15ef8f8ed4acc081419
```

完整链路：

```text
baseline=v0.5.1 + runner v0.3.0
v0.5.1u2=upgrade-528d1f42aa5b62dd succeeded
runner=upgrade-4b1c542232cce245 succeeded
v0.5.2=upgrade-37fbd66390f39880 succeeded
post_cleanup=post-cleanup-upgrade-37fbd66390f39880 success
```

最终结果：

```text
health.version=v0.5.2
health.runner_version=v0.3.1
health.checks.prometheus=true
db=/data/smartx-storage-forecast/app/smartx.db
users=1
towers=1
clusters=1
collection_runs=37
vm_latest=523
vm_volumes=89530
old_paths_missing=/opt/smartx-storage-forecast,/data/smartx-capacity-insight-data,/data/upgrades,/data/backups,/data/exports,/data/compose-runtime,/prometheus-data
```

完整链路：

```text
baseline=v0.5.1 + runner v0.3.0 + prometheus=true
v0.5.1u2 task=upgrade-761854a403bd06bb succeeded
runner task=upgrade-4c404ec5d16ca511 succeeded
v0.5.2 task=upgrade-d2607588845d142a succeeded
post-cleanup task=post-cleanup-upgrade-d2607588845d142a succeeded
```

最终状态：

```text
health.version=v0.5.2
health.runner_version=v0.3.1
health.checks.prometheus=true
network=smartx-hci-capacity-insight-net 10.249.251.0/24
old network=smartx-storage-forecast_smartx-net missing
legacy paths missing=/opt/smartx-storage-forecast,/data/upgrades,/data/backups,/data/exports,/data/compose-runtime,/data/smartx-capacity-insight-data,/prometheus-data
target task files retained=v0.5.1u2,runner,v0.5.2,post-cleanup
component-upgrade/history count=1
release_smoke_check critical_count=0 warning_count=0
```

## 2026-07-06 UPG-031 target app mountpoint cleanup 计划、本地修复与远端验证

状态：已在 10.20.11.3 完整链路验证通过

fix19 完整链路结果：

```text
baseline: v0.5.1 + runner v0.3.0 + prometheus=true
v0.5.1u2-fix19: success
runner-v0.3.1-postcleanupfix6: success
v0.5.2-postcleanupfix6: main task success
post-cleanup-upgrade-26670806af7e8414: running, stuck at cleanup-target-app-residuals
```

失败证据：

```text
health:
  version=v0.5.2
  runner_version=v0.3.1
  checks.directories=false

runner logs:
  RevisionConflict: 任务 revision 已变化：期望 13，实际 0
```

根因：

- `target_app_residual_paths` 里的 `/data/smartx-storage-forecast/app/upgrades`、`app/backups`、`app/exports`、`app/compose-runtime` 是 final runtime 的嵌套 bind mount 目标目录，不是旧环境残留。
- 删除这些目录会扰动当前 runner/web-api 的 `/data/upgrades`、`/data/backups`、`/data/exports`、`/data/compose-runtime` 挂载点，导致健康目录检查失败和 runner task store revision 冲突。

本地修复：

- `scripts/build_upgrade_package.py`
  - v0.5.2 `legacy_cleanup.target_app_residual_paths` 改为空列表。
- `backend/app/upgrade_runner/actions.py`
  - cleanup 收到旧包里的 active target mountpoint 时返回 `skipped: active target mountpoint`，不调用 helper，也不直接删除。
- `backend/tests/test_v2_package_builders.py`
  - 断言 v0.5.2 manifest 不再生成 `target_app_residual_paths`。
- `backend/tests/test_upgrade_runner_engine.py`
  - 断言 `/data/smartx-storage-forecast/app/upgrades` 这类活动挂载点被跳过且 marker 保留。

本地验证：

```text
PYTHONPATH=backend python3 -m unittest \
  backend.tests.test_v2_package_builders \
  backend.tests.test_upgrade_runner_engine \
  backend.tests.test_upgrade_protocol \
  backend.tests.test_v2_upgrade

Ran 123 tests in 4.472s
OK (skipped=1)
```

下一轮包：

```text
v0.5.1u2-fix20-skip-active-target-mountpoints
  path=/home/user1/codex-build/packages-v051u2-fix20/01-v0.5.1u2-fix20-skip-active-target-mountpoints/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz
  sha256=249c54884b4195ed25feeb0ef21f0dedc5039de7cdaabaf9ec5e172c1c0b790d

runner-v0.3.1-postcleanupfix7-skip-active-target-mountpoints
  path=/home/user1/codex-build/packages-v052-postcleanupfix7/02-runner-v0.3.1-postcleanupfix7-skip-active-target-mountpoints/smartx-upgrade-runner-v0.3.1.tar.gz
  sha256=43f6a5fbc2150cfb6511f67e4104613c9bdb995fd5c78186bf4fcbd6a12bccf2

v0.5.2-postcleanupfix7-skip-active-target-mountpoints
  path=/home/user1/codex-build/packages-v052-postcleanupfix7/03-v0.5.2-postcleanupfix7-skip-active-target-mountpoints/smartx-capacity-insight-upgrade-v0.5.2.tar.gz
  sha256=5e2aaff6ac0ebe97993b2499169eecd951e9c9683bb7e579de201f6371b3a1b9
```

远端验证：

```text
10.20.11.3:
PYTHONPATH=backend python3 -m unittest \
  backend.tests.test_v2_package_builders \
  backend.tests.test_upgrade_runner_engine \
  backend.tests.test_upgrade_protocol \
  backend.tests.test_v2_upgrade

Ran 123 tests in 28.305s
OK (skipped=1)

STATIC_GATE_OK
u2_source_versions=v0.5.0,v0.5.1,v0.5.1u1,v0.5.1u2
runner_bootstrap_target_root=/data/smartx-storage-forecast
v052_cleanup_target_app_residual_paths=[]
RUNNER_IMAGE_ACTIVE_MOUNTPOINT_SKIP_OK

baseline:
  version=v0.5.1
  runner_version=v0.3.0
  directories/database/prometheus=true

full chain:
  v0.5.1u2 task=upgrade-1cb2b21f905a0df2 succeeded
  runner v0.3.1 task=upgrade-0f881a8f584ca943 succeeded
  v0.5.2 task=upgrade-edc9d233736cf967 succeeded
  post-cleanup for upgrade-edc9d233736cf967 succeeded

final health:
  version=v0.5.2
  runner_version=v0.3.1
  prometheus=true

final cleanup:
  MISSING /opt/smartx-storage-forecast
  MISSING /data/upgrades
  MISSING /data/backups
  MISSING /data/exports
  MISSING /data/compose-runtime
  MISSING /data/smartx-capacity-insight-data
  MISSING /prometheus-data
  EXISTS /data/smartx-storage-forecast/project
  EXISTS /data/smartx-storage-forecast/app
  EXISTS /data/smartx-storage-forecast/upgrades
  EXISTS /data/smartx-storage-forecast/compose-runtime
  EXISTS /data/smartx-storage-forecast/prometheus

CHAIN_OK
```

## 2026-07-06 UPG-030 host cleanup helper 本地修复

状态：已确认根因并本地实现；待同步 10.20.11.3 打包和完整链路验证

fix18 完整链路在 `10.20.11.3` 的结果：

```text
v0.5.1u2-fix18: success
runner-v0.3.1-postcleanupfix5: success
v0.5.2-postcleanupfix5: health=v0.5.2 + runner v0.3.1 + prometheus=true
post-cleanup: failed
```

关键失败：

```text
OSError: [Errno 16] Device or resource busy: PosixPath('/data/upgrades')
/data/smartx-storage-forecast/upgrades/<task_id>/task.json missing
```

根因：

- `legacy_cleanup.legacy_paths` 里的 `/data/upgrades` 是宿主机旧目录。
- final runner 容器内 `/data/upgrades` 已经映射到宿主机 `/data/smartx-storage-forecast/upgrades`。
- 旧实现直接 `Path('/data/upgrades')` 删除，等于清空新 upgrades 目录内容，删除目标 task mirror 后再因为挂载点忙而失败。

本地修复：

- `scripts/build_upgrade_package.py`：v0.5.2 `legacy_cleanup` 增加 `helper_image`。
- `backend/app/v2/upgrade/compiler.py`：post-cleanup 子任务把 `helper_image` 传给文件清理 action。
- `backend/app/upgrade_runner/actions.py`：cleanup 文件删除改为可通过 helper 容器按宿主机路径执行；缺 helper 且命中当前活动挂载点时拒绝直接删除。
- 新增/更新测试覆盖 helper 路径、post-cleanup task 参数、v0.5.2 manifest。

本地验证：

```text
PYTHONPATH=backend python3 -m unittest backend.tests.test_upgrade_runner_engine
Ran 47 tests, OK

PYTHONPATH=backend python3 -m unittest backend.tests.test_upgrade_protocol backend.tests.test_v2_upgrade
Ran 50 tests, OK (skipped=1)

PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_package_builders
Ran 24 tests, OK
```

下一步：

```text
v0.5.1u2-fix19-host-cleanup-helper
runner-v0.3.1-postcleanupfix6-host-cleanup-helper
v0.5.2-postcleanupfix6-host-cleanup-helper
```

远端打包前新增构建修复：

- 10.20.11.3 首次打 `v0.5.1u2-fix19` 失败在 frontend Docker build：

```text
COPY . .
ERROR: cannot replace to directory .../node_modules/@testing-library/jest-dom with file
```

- 根因是 `frontend/.dockerignore` 缺失，远端测试产生的 `frontend/node_modules` 被带入 Docker build context。
- 已新增 `frontend/.dockerignore`，排除 `node_modules/dist/coverage/*.tsbuildinfo/.vite` 等本地构建产物。
- 已新增 unittest 回归测试：`test_frontend_docker_context_excludes_local_build_artifacts`。

远端验证：

```text
10.20.11.3:
PYTHONPATH=backend python3 -m unittest \
  backend.tests.test_v2_package_builders \
  backend.tests.test_upgrade_runner_engine \
  backend.tests.test_upgrade_protocol \
  backend.tests.test_v2_upgrade

Ran 122 tests in 28.064s
OK (skipped=1)
```

已生成候选包：

```text
v0.5.1u2-fix19-host-cleanup-helper
path=/home/user1/codex-build/packages-v051u2-fix19/01-v0.5.1u2-fix19-host-cleanup-helper/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz
sha256=fcb8d63cb561f0e11790d7ca4ff2086c7ee2d16ddcc5280bb60d3244b35094a4

runner-v0.3.1-postcleanupfix6-host-cleanup-helper
path=/home/user1/codex-build/packages-v052-postcleanupfix6/02-runner-v0.3.1-postcleanupfix6-host-cleanup-helper/smartx-upgrade-runner-v0.3.1.tar.gz
sha256=ad24904b79255968632119db1773f10f0cf41185b3c7b8f02f00763c3f99577c

v0.5.2-postcleanupfix6-host-cleanup-helper
path=/home/user1/codex-build/packages-v052-postcleanupfix6/03-v0.5.2-postcleanupfix6-host-cleanup-helper/smartx-capacity-insight-upgrade-v0.5.2.tar.gz
sha256=2bcc7bb6534aae05538777aa7822dc6d48a4ac27ed0a787add68a5180d1501a1
```

静态闸门：

```text
STATIC_GATE_OK
u2_source_versions=v0.5.0,v0.5.1,v0.5.1u1,v0.5.1u2
v052_cleanup_helper=nazawsze/smartx-hci-capacity-insight-web-api:v0.5.2
RUNNER_IMAGE_HOST_CLEANUP_HELPER_OK
```

## 2026-07-06 runner-v0.3.1-postcleanupfix2 实现与打包

状态：已实现、已打包、静态闸门通过；待完整链路验证

本轮修复上一轮完整链路失败的直接原因：`runner-v0.3.1-handofffix1` 不包含 `.env` 迁移和 `post_upgrade.schedule_cleanup` handler。

本地新增/修复：

- `scripts/build_runner_component_package.py`
  - runner 镜像自检从“只 import 模块”升级为真实能力检查。
  - 自检覆盖：
    - `default_handlers()` 包含 `post_upgrade.schedule_cleanup`。
    - `filesystem.prepare` 能执行 `env_file_migration` 并移除 `SMARTX_IMAGE_TAG` / `SMARTX_RUNNER_IMAGE_TAG`。
    - `task.migrate_runtime_state` + `task.sync_runtime_state` 之后，最终 success 会写入目标 task mirror。
  - `docker compose build upgrade-runner` 前如果仓库根目录没有 `.env`，临时创建空 `.env`，构建后删除，避免 compose build 直接失败。
- `backend/tests/test_v2_package_builders.py`
  - 新增 runner 包自检脚本断言。
  - 新增 runner builder 临时 `.env` 回归测试。

验证：

```text
local:
PYTHONPATH=backend python3 -m unittest \
  backend.tests.test_v2_package_builders \
  backend.tests.test_upgrade_runner_engine \
  backend.tests.test_upgrade_protocol \
  backend.tests.test_v2_upgrade

Ran 117 tests
OK (skipped=1)

10.20.11.3:
Ran 117 tests in 26.842s
OK (skipped=1)
```

新包：

```text
runner-v0.3.1-postcleanupfix2
path=/home/user1/codex-build/packages-v052-postcleanupfix2/02-runner-v0.3.1-postcleanupfix2/smartx-upgrade-runner-v0.3.1.tar.gz
sha256=f99cdb9312fd0f07ab38585ddcf2c29623db8fda34bc989695944458b76190c2
```

静态闸门：

```text
package_type=component
component=upgrade-runner
version=v0.3.1
members=manifest.json, release-notes.md, images/upgrade-runner.tar, checksums.sha256
RUNNER_STATIC_GATE_OK
```

## 2026-07-06 v0.5.1u2-fix15 bootstrap target root 本地修复

状态：已本地实现并通过单元测试；待同步到 10.20.11.3 打包验证

新失败结论：

- `runner-v0.3.1-postcleanupfix2` 已经包含 `.env` 迁移和 `post_upgrade.schedule_cleanup`。
- 但 v0.5.1u2 生成的 runner bootstrap compose 仍只暴露 legacy 目录。
- runner 必须继续扫描 `/data/upgrades`，否则看不到旧 web-api 提交的 v0.5.2 任务。
- 同时 runner 也必须能访问宿主机 `/data/smartx-storage-forecast/*`，否则 task mirror 和 `.env` 迁移只会写在容器视角里。

本地改动：

- `scripts/build_runner_component_package.py`
  - runner 组件 manifest 新增 `bootstrap_runner.target_root=/data/smartx-storage-forecast`。
- `backend/app/v2/upgrade/service.py`
  - bootstrap runner compose 在保留 `/data/upgrades:/data/upgrades` 的同时，追加 `/data/smartx-storage-forecast:/data/smartx-storage-forecast`。
  - 对 `target_root` 做安全校验，拒绝 `/`、`/data`、`/opt`、相对路径和 `..`。
- `backend/tests/test_v2_upgrade.py`
  - 增加回归测试，确保 bootstrap 同时保留 legacy task scan path 和目标根挂载。
- `backend/tests/test_v2_package_builders.py`
  - 增加 runner 包 manifest `bootstrap_runner` 断言。

本地验证：

```text
PYTHONPATH=backend python3 -m unittest \
  backend.tests.test_v2_package_builders \
  backend.tests.test_upgrade_runner_engine \
  backend.tests.test_upgrade_protocol \
  backend.tests.test_v2_upgrade

Ran 118 tests in 4.470s
OK (skipped=1)
```

下一步：

- 同步到 `10.20.11.3`。
- 远端跑同一组测试。
- 重打 `v0.5.1u2-fix15-bootstrap-target-root` 和 `runner-v0.3.1-postcleanupfix3`。
- 恢复 `10.20.11.3` 基线后重新跑完整链路。

## 2026-07-06 v0.5.1u2-fix14 + v0.5.2-postcleanupfix2 完整链路验证失败

状态：失败，已停止；不继续修改代码

测试环境：`10.20.11.3`

已执行链路：

```text
baseline:
  version=v0.5.1
  runner_version=v0.3.0
  prometheus=true

v0.5.1u2-fix14-env-postcleanup-compiler:
  task=upgrade-20ada1e4a47ea1bd
  result=success
  health: version=v0.5.1u2, runner_version=v0.3.0, prometheus=true

runner-v0.3.1-handofffix1:
  task=upgrade-46b246e27b297cf8
  result=success
  health settled after a short heartbeat delay:
    version=v0.5.1u2, runner_version=v0.3.1, prometheus=true

v0.5.2-postcleanupfix2:
  task=upgrade-4caf98b7f3a368e6
  result=failed
```

失败现场：

```text
health after failure:
  ok=true
  version=v0.5.2
  runner_version=v0.3.1
  prometheus=true

task file:
  /data/upgrades/upgrade-4caf98b7f3a368e6/task.json

new task file:
  /data/smartx-storage-forecast/upgrades/upgrade-4caf98b7f3a368e6/task.json
  missing

new web-api status API:
  GET /api/admin/upgrade/status/upgrade-4caf98b7f3a368e6
  404 升级任务不存在
```

失败 action：

```text
id=schedule-post-upgrade-cleanup
type=post_upgrade.schedule_cleanup
status=failed
error=Runner 不支持动作：post_upgrade.schedule_cleanup
```

附带证据：

```text
/data/smartx-storage-forecast/project/.env missing
docker compose -f /data/smartx-storage-forecast/project/docker-compose.release.yml config:
  env file /data/smartx-storage-forecast/project/.env not found
```

根因：

- 本轮只重打了 `v0.5.1u2` 和 `v0.5.2` 平台包，没有重打 runner 组件包。
- `.env` 迁移逻辑是在 `backend/app/upgrade_runner/actions.py` 的 `filesystem.prepare` 中实现的，实际执行者是 runner 容器。
- `post_upgrade.schedule_cleanup` 也是 execution_plan 中由 runner 执行的 action。
- 当前链路使用的 `runner-v0.3.1-handofffix1` 包不包含这两个新增能力：
  - 没有执行 `.env` 迁移，所以 `/data/smartx-storage-forecast/project/.env` 仍缺失。
  - 不支持 `post_upgrade.schedule_cleanup`，所以主任务最后失败。

结论：

- `v0.5.1u2-fix14-env-postcleanup-compiler` 第一跳可用。
- `v0.5.2-postcleanupfix2` 静态包本身能表达正确计划，但不能和旧 `runner-v0.3.1-handofffix1` 组成最终可用链路。
- 下一轮必须补一个新的 `runner v0.3.1` 修复包，至少包含：
  - `filesystem.prepare` 的 `.env` 迁移能力。
  - `post_upgrade.schedule_cleanup` action handler，或重新设计让后置清理调度不作为 runner action 执行。

## 2026-07-06 v0.5.2 `.env` 迁移与 v0.5.1u2 compiler 桥接实现/打包

状态：代码已实现，远端单元测试和升级包静态闸门已通过；完整链路验证待执行

本轮在 10.20.11.3 上完成：

- 同步本地修复文件到 `/home/user1/codex-build/worktree-env-postcleanupfix2`。
- 运行远端单元测试：

```text
PYTHONPATH=backend python3 -m unittest \
  backend.tests.test_v2_package_builders \
  backend.tests.test_v2_upgrade \
  backend.tests.test_upgrade_runner_engine \
  backend.tests.test_upgrade_protocol

Ran 116 tests in 26.834s
OK (skipped=1)
```

- 以 root 构建两个升级包：

```text
v0.5.1u2-fix14-env-postcleanup-compiler
path=/home/user1/codex-build/packages-v051u2-fix14/01-v0.5.1u2-fix14-env-postcleanup-compiler/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz
sha256=4e40bbe1c02b4226c0f1ad2216d31361af955658e131c4216562f0346ef17078

v0.5.2-postcleanupfix2
path=/home/user1/codex-build/packages-v052-postcleanupfix2/03-v0.5.2-postcleanupfix2/smartx-capacity-insight-upgrade-v0.5.2.tar.gz
sha256=7cd5f1e3a2d4b677c377f1ef2f1369da56f5ca08ef5b71ba3dda93e95b9f8816
```

- 静态闸门结果：

```text
CHECKS_TOTAL 32
CHECKS_FAILED 0
STATIC_GATES_OK
```

关键通过项：

- v0.5.1u2-fix14 不写 `minimum_runner_version`，只使用 legacy runner v0.3.0 action 能力。
- v0.5.1u2-fix14 支持来源版本 `v0.5.0/v0.5.1/v0.5.1u1/v0.5.1u2`。
- v0.5.1u2-fix14 包内 project files 仍是 legacy `/opt/smartx-storage-forecast`、旧 project/network、`10.249.249.0/24`。
- v0.5.2-postcleanupfix2 manifest 包含 `.env` 迁移配置，目标为 `/data/smartx-storage-forecast/project/.env`，旧候选为 `/opt/smartx-storage-forecast/.env`。
- 两个包都不包含 `project/.env`、`images/upgrade-runner.tar`、`images/prometheus.tar`。
- v0.5.2 编译后的 execution plan 包含 `post_upgrade.schedule_cleanup`，不包含 same-task `runner.handoff_target_runtime`、`runner.stop_legacy_runtime`、`legacy.cleanup`。

下一步：

- 在 10.20.11.3 执行完整链路验证：

```text
v0.5.1 + runner v0.3.0
  -> v0.5.1u2-fix14-env-postcleanup-compiler
  -> runner v0.3.1-handofffix1
  -> v0.5.2-postcleanupfix2
  -> post-upgrade cleanup task
```

## 2026-07-06 v0.5.2 `.env` 迁移与 v0.5.1u2 compiler 桥接计划写入

状态：只写计划和记录，不修改代码，不操作远端环境

本轮根据 `10.20.11.3` 验证结果，把新的阻断原因和修复计划写入文档。

已确认的问题：

- `v0.5.2-postcleanupfix1` 包上传和预检查通过，任务为 `upgrade-ad3195dc076fa673`。
- 开始升级后失败在 `compose.apply`，runner 日志报错：

```text
env file /data/smartx-storage-forecast/project/.env not found: stat /data/smartx-storage-forecast/project/.env: no such file or directory
```

- 该 `.env` 是 compose 项目目录下的现场运行配置，旧版本可从 `/opt/smartx-storage-forecast/.env` 迁移，不能打入升级包。
- 同次验证发现当前运行的 web-api 仍生成旧 cleanupfix2 execution plan，包含：

```text
runner.handoff_target_runtime
runner.stop_legacy_runtime
legacy.cleanup
```

- 根因是 v0.5.2 平台升级任务由当前 `v0.5.1u2` web-api 编译 plan，因此 v0.5.1u2 桥包也必须同步 postcleanup compiler 逻辑。

已写入：

- `task_plan.md`
  - 新增 Phase 40：`v0.5.2 env 迁移与 v0.5.1u2 compiler 桥接修复计划`。
- `docs/v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md`
  - 新增 `UPG-024 .env 迁移缺失与 v0.5.1u2 compiler 桥接修复`。
- `docs/upgrade-package-ledger.md`
  - `v0.5.2-postcleanupfix1` 标记为 `DO NOT USE FOR FINAL CHAIN`，记录 SHA 和失败任务。
  - 新增 `v0.5.2-postcleanupfix2` planned。
  - 新增 `v0.5.1u2-fix14-env-postcleanup-compiler` planned。

下一轮计划包：

```text
v0.5.1u2-fix14-env-postcleanup-compiler
v0.5.2-postcleanupfix2
```

验收链路仍仅在 `10.20.11.3`：

```text
v0.5.1 + runner v0.3.0
  -> v0.5.1u2-fix14-env-postcleanup-compiler
  -> runner v0.3.1-handofffix1
  -> v0.5.2-postcleanupfix2
  -> post-upgrade cleanup task
```

## 2026-07-06 v0.5.2 post-upgrade cleanup execution_plan 方案写入

状态：只写计划，不修改代码，不操作远端环境

本轮根据“升级完 v0.5.2 后再通过 execution_plan 处理旧环境清理”的思路，已把 cleanupfix2 失败后的替代方案写入文档。

已写入：

- `docs/v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md`
  - 新增 `UPG-023 v0.5.2 成功后 post-upgrade execution_plan 清理方案`。
  - 明确主升级任务只负责平台切换、健康检查、task 迁移和后置清理调度。
  - 明确旧环境清理由 v0.5.2 新 web-api 创建独立 `post_upgrade_cleanup` task，并由 v0.5.2 新 runner 执行。
  - 明确 cleanup 失败不把平台主升级回退为失败，而是进入 warning/critical 通知并允许重试。
- `task_plan.md`
  - 新增 Phase 39：`v0.5.2 post-upgrade cleanup execution_plan 方案`。

计划包名：

```text
fix_id=v0.5.2-postcleanupfix1
path=/home/user1/codex-build/packages-v052-postcleanupfix1/03-v0.5.2-postcleanupfix1/smartx-capacity-insight-upgrade-v0.5.2.tar.gz
sha256=TBD
status=PLANNED
```

下一步：

- 等用户确认是否采用 `postcleanupfix1` 方案。
- 若确认，再实施代码；当前未修改任何代码。

## 2026-07-06 v0.5.2 postcleanupfix1 本地实现

状态：本地代码已实现并通过目标测试；待打包和 `10.20.11.3` 完整链路验证

本轮实现：

- v0.5.2 主升级 execution plan 不再直接执行 `runner.handoff_target_runtime -> runner.stop_legacy_runtime -> legacy.cleanup`。
- v0.5.2 主升级 execution plan 改为在 `task.sync_runtime_state` 后执行 `post_upgrade.schedule_cleanup`。
- 新增后置清理 plan：

```text
post_cleanup.precheck_target_health
runner.stop_legacy_runtime
compose.stop_legacy_project
network.remove_legacy
filesystem.cleanup_legacy_paths
filesystem.cleanup_target_app_residuals
post_cleanup.verify
```

- `UpgradeService` 新增：
  - `create_post_upgrade_cleanup_task(parent_task_id, legacy_cleanup)`
  - `retry_post_upgrade_cleanup(parent_task_id)`
  - `post_upgrade_cleanup_status(parent_task_id)`
- 主升级 task 读取/归一化时，如果已经 `success` 且 manifest 声明 `post_upgrade.create_cleanup_task=true`，会自动创建 `post-cleanup-<parent_task_id>`。
- 新增 API：
  - `GET /api/admin/upgrade/post-cleanup/{task_id}`
  - `POST /api/admin/upgrade/post-cleanup/{task_id}/retry`
- 前端平台升级状态区增加“旧环境清理”状态，并在失败/告警时提供“重试清理”。
- v0.5.2 平台包 manifest 增加：

```json
"post_upgrade": {
  "create_cleanup_task": true,
  "cleanup_task_policy": "after_platform_health_success",
  "cleanup_failure_severity": "warning"
}
```

- `docs/upgrade-package-ledger.md` 将 `v0.5.2-cleanupfix3` 标记为被 `postcleanupfix1` 方案取代，并新增 `v0.5.2-postcleanupfix1` 候选记录。

本地验证：

- `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_package_builders backend.tests.test_v2_upgrade backend.tests.test_upgrade_runner_engine backend.tests.test_upgrade_protocol`：111 tests OK，1 skipped。
- `python3 -m py_compile backend/app/v2/upgrade/compiler.py backend/app/v2/upgrade/service.py backend/app/v2/api.py backend/app/upgrade_protocol/constants.py backend/app/upgrade_runner/actions.py backend/app/upgrade_runner/engine.py backend/app/upgrade_runner/main.py scripts/build_upgrade_package.py`：通过。
- `frontend ./node_modules/.bin/vitest run ServicePage.test.tsx`：21 tests OK。
- `frontend ./node_modules/.bin/tsc -b`：通过。

下一步：

- 在 `10.20.11.3` 同步代码后重打 `v0.5.2-postcleanupfix1`。
- 仅在 `10.20.11.3` 从干净 `v0.5.1 + runner v0.3.0` 基线验证：

```text
v0.5.1 + runner v0.3.0
  -> v0.5.1u2-fix13-imageidentity
  -> runner v0.3.1-handofffix1
  -> v0.5.2-postcleanupfix1
  -> post-upgrade cleanup task
```

## 2026-07-03 v0.5.2-cleanupfix2 完整链路失败与 cleanupfix3 方案写入

状态：只写文档，不修改代码，不操作远端环境

本轮已确认：

- `10.20.11.3` 正常链路中：
  - `v0.5.1 -> v0.5.1u2-fix13-imageidentity` 成功。
  - `runner v0.3.0 -> v0.3.1-handofffix1` 成功。
  - `v0.5.1u2 -> v0.5.2-cleanupfix2` 平台健康成功，但最终升级任务失败。
- `v0.5.2-cleanupfix2` 失败任务：
  - `task_id=upgrade-47b45bc1aafa0e86`
  - `task_file=/data/upgrades/upgrade-47b45bc1aafa0e86/task.json`
  - `status=failed`
  - `failed_action=cleanup-legacy-runtime`
  - `error=当前 runner 仍挂载待清理旧路径，必须先完成 runner handoff：/opt/smartx-storage-forecast`
- 失败时新平台已健康：
  - `version=v0.5.2`
  - `runner_version=v0.3.1`
  - `checks.directories/database/prometheus=true`
  - 新 project `smartx-hci-capacity-insight` 五个容器运行。
- 失败根因：
  - `runner.handoff_target_runtime` 启动了新 runner，但没有停止旧 runner `smartx-storage-forecast-upgrade-runner-1`。
  - 旧 runner 仍挂载 `/opt/smartx-storage-forecast`、`/data/upgrades`、`/data/compose-runtime`、`/prometheus-data`。
  - `legacy.cleanup` mount guard 正确拒绝删除旧目录。
  - task 状态仍在 `/data/upgrades/<task_id>`，新 web-api 读取 `/data/smartx-storage-forecast/upgrades`，所以 status/history 返回 404/空。

已写入文档：

- `docs/v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md`
  - 新增 `2026-07-03 cleanupfix2 完整链路失败后的修复计划`。
  - 明确 `runner.stop_legacy_runtime`、task 绝对目标路径迁移、测试、静态闸门和完整链路验收。
- `docs/v0.5.1u2-to-v0.5.2-upgrade-issues.md`
  - 新增 cleanupfix2 失败现场证据和根因。
- `docs/upgrade-issues.md`
  - 更新 UPG-021 状态：cleanupfix2 失败，需 cleanupfix3。
- `docs/upgrade-package-ledger.md`
  - `v0.5.2-cleanupfix2` 改为 `DO NOT USE FOR FINAL CHAIN`。
  - 新增 `v0.5.2-cleanupfix3` planned 记录。
- `task_plan.md`
  - 新增 Phase 38：`v0.5.2-cleanupfix3 旧 runner 下线与 task 迁移修复计划`。

下一步实现要点：

- 新增 `runner.stop_legacy_runtime` action，放在 `runner.handoff_target_runtime` 和 `legacy.cleanup` 之间。
- 修正 `task_migrate_runtime_state`，对 `/data/smartx-storage-forecast/upgrades` 这类 manifest 目标绝对路径不再走旧 `/data` host 映射。
- 只重打 `v0.5.2-cleanupfix3`，除非测试证明 `v0.5.1u2-fix13` 或 `runner v0.3.1-handofffix1` 必须修改。
- 完整验证仍只在 `10.20.11.3`，不操作 `10.20.11.12`。

## 2026-07-02 v0.5.1u2 -> runner v0.3.1 -> v0.5.2 handoff 修复实现与打包

状态：代码已实现，三份包已生成并完成静态闸门；完整正常升级链路待在 `10.20.11.3` 执行

本轮根因确认：

- `v0.5.2` 升级任务的 `execution_plan` 是由当前 `v0.5.1u2` web-api 在开始升级时编译。
- 因此只重打 `v0.5.2` 包不够，`v0.5.1u2` 桥包也必须具备编译 `runner.handoff_target_runtime` 的能力。
- runner 必须支持目标 upgrades 宿主机路径，否则 cutover 后 web-api 和 runner 会继续看到不同的 `/data/upgrades` 来源。
- cleanup 前必须确认当前 runner 不再挂载 legacy source，避免再次出现 `/opt/smartx-storage-forecast` busy。

实现内容：

- `backend/app/upgrade_runner/actions.py`
  - 新增 `ActionContext.host_upgrades_path` 和 `host_exports_path`。
  - `docker_host_path()` 先识别目标宿主机路径，再按 `backups/compose-runtime/prometheus/project/upgrades/exports/data` 映射。
  - `task.migrate_runtime_state` 写入目标 host upgrades task dir。
  - 新增 `runner.handoff_target_runtime` action。
  - `legacy.cleanup` 删除前检查当前 runner mounts，发现 legacy source 直接失败并提示必须先 handoff。
- `backend/app/upgrade_runner/main.py`
  - RunnerSettings 支持 `SMARTX_HOST_UPGRADES_PATH` 和 `SMARTX_HOST_EXPORTS_PATH`。
  - 任务中心增加 runner handoff 步骤。
- `backend/app/upgrade_runner/engine.py`
  - `runner.handoff_target_runtime` 加入 safe resume。
- `backend/app/v2/upgrade/compiler.py`
  - v0.5.2 cleanup 计划加入 `task.sync_runtime_state -> runner.handoff_target_runtime -> legacy.cleanup`。
- `backend/app/v2/upgrade/service.py`
  - runner compose 生成使用目标 host path helpers，不再把容器内 `/data/upgrades`、`/data/compose-runtime` 当宿主机 bind source。
- `backend/app/upgrade_protocol/constants.py`
  - 新增 `runner.handoff.v1` capability。
- `scripts/build_upgrade_package.py`
  - v0.5.2 legacy cleanup 包 manifest 声明 `runner.handoff.v1`。

验证：

- 本地：
  - `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_upgrade`：32 tests OK，1 skipped。
  - `PYTHONPATH=backend python3 -m unittest backend.tests.test_upgrade_runner_engine backend.tests.test_upgrade_protocol`：51 tests OK。
  - `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_package_builders`：14 tests OK。
  - `python3 -m py_compile` 覆盖本轮修改文件，通过。
- `10.20.11.3`：
  - 构建上下文：`/home/user1/codex-build/worktree-handofffix`。
  - 升级相关测试：97 tests OK，1 skipped。
  - Python 3.13 输出若干既有 SQLite ResourceWarning，但测试结果为 OK。

已生成包：

- `v0.5.1u2-fix11`
  - path: `/home/user1/codex-build/packages-v052-handofffix/01-v0.5.1u2-fix11/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz`
  - sha256: `0482837fdf4a6785801cb27a03bb5a210146fbcb8f92e6abbf63c07e1f8ba0a8`
  - 说明：桥包仍保持旧 project/network/目录，但 web-api 具备编译 handoff action 的能力。
- `runner-v0.3.1-handofffix1`
  - path: `/home/user1/codex-build/packages-v052-handofffix/02-runner-v0.3.1-handofffix1/smartx-upgrade-runner-v0.3.1.tar.gz`
  - sha256: `678f9acafd90e0c8dafdc0664d251ee29de5f8d0b04eb3796b540ea174a4d16a`
  - 静态闸门：component-only、只包含 `images/upgrade-runner.tar`、镜像内有 `runner_handoff_target_runtime`、默认 `host_upgrades_path=/data/smartx-storage-forecast/upgrades`。
- `v0.5.2-cleanupfix2`
  - path: `/home/user1/codex-build/packages-v052-handofffix/03-v0.5.2-cleanupfix2/smartx-capacity-insight-upgrade-v0.5.2.tar.gz`
  - sha256: `6e996dd90637ce02dba0db34430d7e784ff6dedd17437ee74dcfe2c0eb70a48a`
  - 静态闸门：manifest 包含 `runner.handoff.v1`，compiled actions 为 `... task.sync_runtime_state -> runner.handoff_target_runtime -> legacy.cleanup`，包内不含 `images/prometheus.tar` 和 `images/upgrade-runner.tar`。

待验证链路：

```text
10.20.11.3 only
v0.5.1 + runner v0.3.0
  -> v0.5.1u2-fix11
  -> runner v0.3.1-handofffix1
  -> v0.5.2-cleanupfix2
```

验证失败处理规则：

- 任一步失败后立即停止。
- 先记录 task id、失败 action、task.json、runner/web-api logs、docker inspect、容器列表、network 列表和目录状态。
- 不自动继续修复。

## 2026-07-02 v0.5.1u2 到 v0.5.2 升级规划专项文档

状态：完成

本次只写文档，不修改代码，不操作远端环境。

已新增：

- `docs/v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md`

记录内容：

- 新增 `UPG-022 v0.5.1u2 到 v0.5.2 升级控制面切换规划`。
- 写入当前两个连续错误：第一次 `legacy.cleanup` 因 `/opt/smartx-storage-forecast` busy 失败；第二次同版本 v0.5.2 任务因 web-api 和 runner 的 `/data/upgrades` 宿主机来源不一致而 pending。
- 写入修复包策略：`runner v0.3.1-handofffix1`、`v0.5.2-cleanupfix2`，以及仅必要时才出的 `v0.5.1u2-fix14`。
- 写入详细代码计划：host upgrades 路径模型、runner compose 宿主机 bind source 修复、task runtime state 迁移修复、`runner.handoff_target_runtime` action、cleanup 前 mount 安全检查。
- 写入单元测试、静态包闸门、`10.20.11.3` 完整链路验证和失败处理规则。

同步更新：

- `docs/v0.5.1u2-to-v0.5.2-upgrade-issues.md` 增加修复规划文档入口。
- `docs/upgrade-issues.md` 的 `UPG-021` 增加修复规划文档入口。

## 2026-07-02 v0.5.1u2 到 v0.5.2 升级问题专项文档

状态：完成

本次只做文档整理，不修改代码，不操作远端环境。

已新增：

- `docs/v0.5.1u2-to-v0.5.2-upgrade-issues.md`

记录内容：

- 从 `docs/upgrade-issues.md` 单独拉出 `UPG-021 v0.5.2 升级成功后旧环境残留未自动清理`。
- 写入 `v0.5.1 + runner v0.3.0 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2` 链路边界。
- 写入 source、bridge、runner bootstrap、target 四个版本节点的 project/network/subnet 和应用目录职责。
- 写入 v0.5.1/v0.5.1u2 旧布局、runner bootstrap 过渡布局、v0.5.2 目标单根目录布局。
- 写入历史失败模式：v0.5.1u2 过早引入新 project/network、runner 版本显示停留 v0.3.0、runner bootstrap 数据目录挂载错误、v0.5.2 切换后当前任务状态丢失。
- 写入 2026-07-02 当前现场问题：`10.20.11.3` 健康已到 `v0.5.2 + runner v0.3.1`，但旧 runner/network/目录仍残留，且同版本任务 `upgrade-f247b607ec29f8a4` 因 web-api 与 runner 的 `/data/upgrades` 宿主机来源不一致而保持 pending。

同步更新：

- `docs/upgrade-issues.md` 的 `UPG-021` 增加专项文档入口。

## 2026-07-02 v0.5.2 旧残留自动清理计划写入

状态：已写入规划文件，未改业务代码

- 用户询问旧残留能否在升级时全部自动删除，并要求把之前计划和本次计划一起详细写入相关 Markdown。
- 已更新 `docs/v0.5.0-to-v0.5.2-upgrade-plan.md`：
  - Node 4 不再描述为“旧目录留给显式空间清理”。
  - 明确 v0.5.2 最终健康通过后执行 `legacy.cleanup`。
  - 明确 `task.migrate_runtime_state`、`task.sync_runtime_state` 和任务状态双写，避免新 web-api 切换后任务中心找不到当前升级任务。
  - 写入 legacy project/network、legacy paths、target app residual paths、禁止删除目标目录和最终验证项。
- 已更新 `task_plan.md`：
  - 新增 `Phase 35 v0.5.2 成功后旧环境残留自动清理计划`。
  - 计划包括 manifest `legacy_cleanup`、runner task state mirror、compiler action 顺序、runner cleanup action、安全保护、单测和 `10.20.11.3` 验证步骤。
- 已更新 `findings.md`：
  - 记录旧残留根因、任务状态迁移风险、为什么清理必须由 runner 串在最终健康之后执行。
- 已更新 `docs/upgrade-issues.md`：
  - 新增 `UPG-021 v0.5.2 升级成功后旧环境残留未自动清理`。
- 已更新 `docs/upgrade-package-ledger.md`：
  - 在 `v0.5.2-fix2` 下记录下一版 v0.5.2 包必须携带 legacy cleanup 和 task state mirror；未生成包前不标记为 USE。
- 约束再次明确：
  - 只在 `10.20.11.3` 验证。
  - 不操作 `10.20.11.12`。
  - 不把清理能力放进 `v0.5.1u2` 或 runner `v0.3.1`。

## 2026-07-02 v0.5.2-cleanupfix1 实现与打包

状态：已实现、已在本地和 `10.20.11.3` 通过目标测试、已生成升级包；完整正常升级链路验证待执行

- 使用 TDD 实施 Phase 35：
  - 先新增 manifest、compiler、runner engine、cleanup action 红灯测试。
  - 确认旧代码缺 `legacy_cleanup`、缺 `task.migrate_runtime_state` / `task.sync_runtime_state` / `legacy.cleanup` action、缺任务状态双写。
- 实现内容：
  - `scripts/build_upgrade_package.py` 为 v0.5.2 manifest 增加 `legacy_cleanup` allowlist。
  - `backend/app/v2/upgrade/compiler.py` 在 v0.5.2 计划中加入 `task.migrate_runtime_state -> compose.override -> ... -> health.http -> task.sync_runtime_state -> legacy.cleanup`。
  - `backend/app/upgrade_runner/engine.py` 支持任务状态 mirror，迁移后后续 `_save()` 同步写旧任务目录和新任务目录。
  - `backend/app/upgrade_runner/actions.py` 新增 `task_migrate_runtime_state`、`task_sync_runtime_state`、`legacy_cleanup`。
  - `backend/app/upgrade_runner/main.py` 增加任务中心步骤：`迁移升级任务状态`、`清理旧环境残留`。
  - `backend/app/upgrade_protocol/constants.py` 将新 action 映射到 `task.recovery.v1`，不提升 runner protocol。
- 本地验证：
  - `python3 -m py_compile` 覆盖本次修改文件，通过。
  - `git diff --check` 覆盖本次修改文件和相关文档，通过。
  - `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_package_builders backend.tests.test_upgrade_protocol backend.tests.test_upgrade_runner_engine backend.tests.test_v2_upgrade`：90 tests OK，1 skipped。
- `10.20.11.3` 验证：
  - 已同步完整后端、测试、脚本、compose、版本文件和相关文档到 `/data/smartx-storage-forecast/project`。
  - 远端同组测试通过：90 tests OK，1 skipped。Python 3.13 输出了若干已有 SQLite ResourceWarning，但测试结果通过。
  - 已生成包：
    - path: `/home/user1/codex-build/packages-v052-legacy-cleanup/03-v0.5.2-cleanupfix1/smartx-capacity-insight-upgrade-v0.5.2.tar.gz`
    - sha256: `a314e7d8493c4e926890813e43d6ce7721578aa98a07e706e94f3fc2e26d9e88`
  - 包静态闸门通过：
    - manifest `version=v0.5.2`
    - platform services 包含 `web-api`、`collector-worker`、`frontend`、`prometheus`、`upgrade-runner`
    - manifest 包含 `legacy_cleanup` 的 legacy paths、target app residual paths、protected paths
    - 编译 action 顺序为 `backup.create`、三次 `image.load`、`filesystem.prepare`、`files.sync`、`task.migrate_runtime_state`、`compose.override`、`compose.project_migrate`、`compose.apply`、`health.http`、`task.sync_runtime_state`、`legacy.cleanup`
    - required capabilities 包含 `task.recovery.v1`
    - 不包含 `images/prometheus.tar` 和 `images/upgrade-runner.tar`
- 未操作 `10.20.11.12`。

## 2026-07-02 v0.5.1u2 -> v0.5.2 历史 fix 问题文档补录

状态：已更新文档，未操作任何远端环境

- 已更新 `docs/v0.5.1u2-to-v0.5.2-upgrade-issues.md`：
  - 新增“历史 fix 版本问题总表”。
  - 集中记录 `v0.5.1u2` 从 `fix0` 到 `fix11` 的失败/被替代原因。
  - 集中记录 runner v0.3.1 `fsdirfix4` 到 `handofffix1` 的失败/被替代原因。
  - 集中记录 v0.5.2 `phase34-prometheus-compose` 到 `cleanupfix2` 的失败/被替代原因。
  - 明确 `v0.5.1u2-fix11` 为 `DO NOT USE`，因为它从 `v0.5.1 + runner v0.3.0` 正常升级时预检查失败。
- 已更新 `docs/upgrade-package-ledger.md`：
  - 将 `v0.5.1u2-fix11` 从 `USE` 改为 `DO NOT USE`。
  - 记录失败原因：manifest 错误要求 `minimum_runner_version=v0.3.1`、v0.3.1 capabilities，且 `source_compatibility.supported_versions=[]`。
- 当前结论：
  - `runner-v0.3.1-handofffix1` 和 `v0.5.2-cleanupfix2` 只能算静态闸门通过。
  - 完整链路验证被 `v0.5.1u2-fix11` 桥包失败阻塞。
  - 下一步如果继续修包，必须先修正 v0.5.1u2 桥包：保持 runner v0.3.0 兼容，同时保留 v0.5.2 handoff plan compiler 能力。

## 2026-07-02 v0.5.1u2 桥包 manifest 修复

状态：本地代码已修复并通过相关测试；尚未生成正式 fix 包，尚未远端链路验证

参考文档：

- `docs/v0.5.1u2-to-v0.5.2-upgrade-issues.md`

本轮根因：

- `v0.5.1u2-fix11` 失败不是 runner 包问题，而是桥包 manifest 被打坏。
- `scripts/build_upgrade_package.py` 对所有 platform 包统一写入：
  - `minimum_runner_version=read_runner_version()`，当前为 `v0.3.1`
  - `required_capabilities=["backup.v1","image.v1","files.v1","compose.v1","health.v1","rollback.v1"]`
- 这适合 v0.5.2 目标包，但不适合 `v0.5.1u2` 桥包，因为 `v0.5.1u2` 必须由源环境 runner v0.3.0 执行。
- `_supported_source_versions()` 只识别三段版本号，遇到 `v0.5.1u2` 这种补丁后缀版本会返回空列表，导致 `supported_versions=[]`。

修复内容：

- `scripts/build_upgrade_package.py`
  - 新增 `LEGACY_PLATFORM_CAPABILITIES`，用于 `v0.5.2` 之前的桥包。
  - 新增 `MODERN_PLATFORM_CAPABILITIES`，继续用于 `v0.5.2+` 目标包。
  - 只有 `version >= v0.5.2` 的 platform 包才写入 `minimum_runner_version`。
  - `v0.5.1u2` 桥包 required capabilities 回到旧 action 名：`backup.create`、`image.load`、`files.sync`、`compose.override`、`compose.apply`、`health.http`、`rollback.restore`。
  - `_supported_source_versions()` 改为使用已有 `_version_tuple()`，支持 `v0.5.1u1` / `v0.5.1u2` 这种补丁后缀版本。
  - release notes 对桥包显示“兼容现有 upgrade-runner v0.3.0 能力”，不再写最低 runner v0.3.1。
- `backend/tests/test_v2_package_builders.py`
  - 新增红灯测试 `test_v051u2_bridge_package_keeps_runner_v030_compatibility`，防止再次把桥包打成 v0.3.1 runner 才能执行的包。

本地验证：

- 红灯确认：新增测试最初失败，失败内容复现现场错误：
  - manifest 含 `minimum_runner_version=v0.3.1`
  - manifest required capabilities 为 `backup.v1/image.v1/files.v1/compose.v1/health.v1/rollback.v1`
  - `source_compatibility.supported_versions=[]`
- 修复后验证：
  - `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_package_builders.V2PackageBuilderTest.test_v051u2_bridge_package_keeps_runner_v030_compatibility`：通过。
  - `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_package_builders`：15 tests OK。
  - `PYTHONPATH=backend python3 -m unittest backend.tests.test_upgrade_protocol backend.tests.test_upgrade_runner_engine backend.tests.test_v2_upgrade`：83 tests OK，1 skipped。
  - `python3 -m py_compile scripts/build_upgrade_package.py backend/tests/test_v2_package_builders.py`：通过。
  - `git diff --check -- scripts/build_upgrade_package.py backend/tests/test_v2_package_builders.py`：通过。
- 本地 tar manifest 抽检：
  - `minimum_runner_version=None`
  - `required_capabilities=["backup.create","image.load","files.sync","compose.override","compose.apply","health.http","rollback.restore"]`
  - `source_compatibility.supported_versions=["v0.5.0","v0.5.1","v0.5.1u1","v0.5.1u2"]`
  - 无 `environment_transitions`
  - 无 `legacy_cleanup`

未执行：

- 未操作 `10.20.11.12`。
- 未同步到 `10.20.11.3`。
- 未生成正式 `v0.5.1u2` fix 包。
- 未执行完整升级链路验证。

## 2026-07-02 v0.5.1u2-fix12 project files 计划写入

状态：已写入升级相关 Markdown，未改业务代码，未重新打包

- 已更新 `docs/v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md`：
  - 新增 `v0.5.1u2-fix11` manifest 失败问题。
  - 新增 `v0.5.1u2-fix12-first` project files 静态闸门失败问题。
  - 将修复包策略从 `v0.5.1u2-fix11` 调整为 corrected `v0.5.1u2-fix12`。
  - 新增 “0. 修复 v0.5.1u2 project files 版本选择” 详细实施计划。
- 已更新 `docs/v0.5.1u2-to-v0.5.2-upgrade-issues.md`：
  - 历史 fix 表新增 `fix12-first`。
  - 记录失败包路径和 sha256。
  - 记录 manifest 已正确但 compose 仍为 v0.5.2 目标布局的证据。
- 已更新 `docs/upgrade-package-ledger.md`：
  - 新增 `v0.5.1u2-fix12-first`，状态为 `DO NOT USE`。
- 已更新 `task_plan.md`：
  - 新增 `Phase 36 v0.5.1u2-fix12 project files 版本化打包计划`。
- 已更新 `findings.md`：
  - 新增 `Phase 36 v0.5.1u2-fix12 project files 根因发现`。
- 当前不可用包：
  - path: `/home/user1/codex-build/packages-v051u2-fix12/01-v0.5.1u2-fix12/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz`
  - sha256: `475beeeb2a25f77fcbd29a23b3449474a742fa0cd437ccda4e3bd1d734ccbfc6`
  - reason: manifest 桥包语义已修正，但 project files 仍是 v0.5.2 新 project/network/目录布局。

## 2026-07-02 v0.5.1u2-fix12 project files 本地修复实现

状态：本地代码已修复并通过相关测试；尚未生成新的正式 `v0.5.1u2-fix12` 包，尚未远端链路验证

本轮修复内容：

- `scripts/build_upgrade_package.py`
  - 新增 `LEGACY_PROJECT_FILE_VALUES`，定义 v0.5.2 目标布局到 v0.5.1u2 legacy 布局的版本化替换表。
  - 新增 `_project_file_override()`：当目标版本 `< v0.5.2` 时，不再直接复制当前 worktree 的三个 compose 文件，而是生成 legacy project/network/path 版本。
  - 新增 `_assert_project_files_match_version()`：包内 compose 与目标版本布局不匹配时，打包阶段直接失败。
  - `v0.5.2+` 包仍复制当前 target 布局，不影响 v0.5.2 单根 `/data/smartx-storage-forecast/*` 设计。
- `backend/tests/test_v2_package_builders.py`
  - `test_v051u2_bridge_package_keeps_runner_v030_compatibility` 现在会打开包内 `docker-compose.release.yml`、`docker-compose.offline.yml`、`docker-compose.yml`。
  - 断言 v0.5.1u2 三个 compose 都包含旧 project/network/subnet/path。
  - 断言 v0.5.1u2 三个 compose 都不包含 `smartx-hci-capacity-insight-net`、`/data/smartx-storage-forecast`、`10.249.251.0/24`。

本地验证：

- `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_package_builders.V2PackageBuilderTest.test_v051u2_bridge_package_keeps_runner_v030_compatibility`：通过。
- `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_package_builders`：15 tests OK。
- `PYTHONPATH=backend python3 -m unittest backend.tests.test_upgrade_protocol backend.tests.test_upgrade_runner_engine backend.tests.test_v2_upgrade`：83 tests OK，1 skipped。
- `python3 -m py_compile scripts/build_upgrade_package.py backend/tests/test_v2_package_builders.py`：通过。
- `git diff --check -- scripts/build_upgrade_package.py backend/tests/test_v2_package_builders.py docs/v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md docs/v0.5.1u2-to-v0.5.2-upgrade-issues.md docs/upgrade-package-ledger.md task_plan.md findings.md progress.md`：通过。

未执行：

- 未操作 `10.20.11.12`。
- 未同步到 `10.20.11.3`。
- 未生成新的正式 `v0.5.1u2-fix12` 包。
- 未执行完整升级链路验证。

## 2026-07-02 v0.5.1u2-fix12-projectfiles 打包与静态闸门

状态：已在 `10.20.11.3` 重打 `v0.5.1u2` 候选包并通过静态闸门；完整正常升级链路第一步验收失败，该包已标记 `DO NOT USE`

远端构建上下文：

```text
10.20.11.3:/home/user1/codex-build/worktree-v051u2-fix12
```

新包：

```text
fix_id=v0.5.1u2-fix12-projectfiles
path=/home/user1/codex-build/packages-v051u2-fix12/02-v0.5.1u2-fix12-projectfiles/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz
sha256=0d992c9cd42e4287db3fb43845e6590b84904d55846de952dadbc9116a2e14d9
status=DO NOT USE
```

远端测试：

- `python3 -m py_compile scripts/build_upgrade_package.py backend/tests/test_v2_package_builders.py`：通过。
- `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_package_builders.V2PackageBuilderTest.test_v051u2_bridge_package_keeps_runner_v030_compatibility`：通过。
- `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_package_builders`：15 tests OK。

静态闸门：

- manifest `version=v0.5.1u2`。
- manifest 无 `minimum_runner_version`。
- manifest 无 `environment_transitions`。
- manifest 无 `legacy_cleanup`。
- manifest `required_capabilities=backup.create,image.load,files.sync,compose.override,compose.apply,health.http,rollback.restore`。
- manifest `source_compatibility.supported_versions=v0.5.0,v0.5.1,v0.5.1u1,v0.5.1u2`。
- 包内无 `images/upgrade-runner.tar`。
- 包内无 `images/prometheus.tar`。
- 包内 `project/docker-compose.release.yml`、`project/docker-compose.offline.yml`、`project/docker-compose.yml` 均包含：
  - `name: smartx-storage-forecast`
  - `SMARTX_COMPOSE_PROJECT_NAME: smartx-storage-forecast`
  - `SMARTX_PROJECT_PATH: /opt/smartx-storage-forecast`
  - `/data/smartx-capacity-insight-data/app:/data`
  - `/data/upgrades:/data/upgrades`
  - `/data/backups:/data/backups`
  - `/data/exports:/data/exports`
  - `/data/compose-runtime:/data/compose-runtime`
  - `/prometheus-data:/prometheus-data`
  - `name: smartx-storage-forecast_smartx-net`
  - `subnet: 10.249.249.0/24`
- 包内三个 compose 均不包含：
  - `smartx-hci-capacity-insight-net`
  - `/data/smartx-storage-forecast`
  - `10.249.251.0/24`

已同步文档：

- `docs/upgrade-package-ledger.md`
- `docs/v0.5.1u2-to-v0.5.2-upgrade-issues.md`
- `docs/v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md`
- `task_plan.md`

完整链路失败：

- baseline: `10.20.11.3` 当前为 `v0.5.1 + runner v0.3.0`。
- 升级包：`v0.5.1u2-fix12-projectfiles`。
- 任务：`upgrade-07eb997948160b33`。
- 任务结果：`succeeded`。
- 任务中所有 action 均为 `succeeded`：
  - `backup`
  - 三个 `image.load`
  - `files.sync`
  - `compose.override`
  - `compose.apply`
  - `health.http`
- Docker 容器状态：
  - `smartx-storage-forecast-web-api-1` 使用 `nazawsze/smartx-hci-capacity-insight-web-api:v0.5.1u2`。
  - `smartx-storage-forecast-collector-worker-1` 使用 `nazawsze/smartx-hci-capacity-insight-collector-worker:v0.5.1u2`。
  - `smartx-storage-forecast-frontend-1` 使用 `nazawsze/smartx-hci-capacity-insight-frontend:v0.5.1u2`。
  - `smartx-storage-forecast-upgrade-runner-1` 仍使用 `v0.3.0`。
  - network 仍为 `smartx-storage-forecast_smartx-net`，subnet 仍为 `10.249.249.0/24`。
- 节点验收失败：
  - `/api/system/health` 返回 `ok=true`、`version=v0.5.2`、`runner_version=v0.3.0`、`checks.prometheus=true`。
  - 预期应为 `version=v0.5.1u2`、`runner_version=v0.3.0`。
- web-api 容器内证据：
  - `/app/VERSION=v0.5.2`
  - `/app/RUNNER_VERSION=v0.3.1`
  - `/app/app/core/config.py` 中 `DEFAULT_APP_VERSION = "v0.5.2"`、`DEFAULT_RUNNER_VERSION = "v0.3.1"`。
  - `/app/app/v2/config.py` 中 `DEFAULT_APP_VERSION = "v0.5.2"`、`DEFAULT_RUNNER_VERSION = "v0.3.1"`。

结论：

- `fix12-projectfiles` 确实修复了 project files 版本选择。
- 但该包打包时保存的 `v0.5.1u2` 镜像 tag 内容是 v0.5.2，导致桥包第一步虽然任务成功，版本验收仍失败。
- 不能继续执行 runner v0.3.1 和 v0.5.2 升级验证。

未执行：

- 未操作 `10.20.11.12`。
- 未执行 runner v0.3.1 升级。
- 未执行 v0.5.2 升级。

## 2026-07-03 v0.5.1u2-fix13-imageidentity 计划写入

状态：已写入计划，未改代码，未重新打包，未操作远端

本次只做文档落地：

- 已更新 `task_plan.md`：
  - 新增 `Phase 37 v0.5.1u2-fix13 镜像身份闸门与干净重打计划`。
  - 明确 fix12 失败根因是 `v0.5.1u2` Docker tag 内容被 v0.5.2 镜像污染。
  - 明确后续必须增加 local image identity gate 与 package image tar identity gate。
- 已更新 `findings.md`：
  - 新增 `Phase 37 v0.5.1u2-fix12 镜像污染根因发现`。
  - 记录容器内 `/app/VERSION=v0.5.2`、`/app/RUNNER_VERSION=v0.3.1` 等关键证据。
- 已更新升级 issue 文档：
  - `docs/v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md`
    - 新增 `planned v0.5.1u2-fix13-imageidentity`，写明边界、硬闸门、文件修改范围和 `10.20.11.3` 验证链路。
  - `docs/v0.5.1u2-to-v0.5.2-upgrade-issues.md`
    - 在 fix 系列表中新增 `fix13-imageidentity=PLANNED`，并记录必须拒绝的污染镜像形态。
  - `docs/upgrade-package-ledger.md`
    - 新增 `v0.5.1u2-fix13-imageidentity` 台账行，状态为 `PLANNED`，sha256 为 `TBD`。

未执行：

- 未修改 `scripts/build_upgrade_package.py`。
- 未新增 `scripts/verify_upgrade_package_identity.py`。
- 未生成 `v0.5.1u2-fix13-imageidentity` 包。
- 未操作 `10.20.11.3`。
- 未操作 `10.20.11.12`。

## 2026-07-03 v0.5.1u2-fix13-imageidentity 本地实现

状态：本地代码已实现并通过本地验证；尚未在 `10.20.11.3` 重打包，未操作 `10.20.11.12`

本轮代码改动：

- `scripts/build_upgrade_package.py`
  - 新增 web-api 镜像内部身份读取与校验。
  - `v0.5.1u2` 要求 `/app/VERSION=v0.5.1u2`、`/app/RUNNER_VERSION=v0.3.0`，并校验 `app.core.config` / `app.v2.config` 默认版本常量。
  - `v0.5.2+` 要求 `/app/RUNNER_VERSION` 与当前 `RUNNER_VERSION` 一致。
  - `build_images=False` 时必须显式 `allow_existing_images=True`，CLI 对应 `--allow-existing-images`。
  - `check_version_metadata=False` 不再跳过镜像内部身份检查。
- `scripts/verify_upgrade_package_identity.py`
  - 新增最终包校验脚本。
  - 解包升级包，校验 `checksums.sha256`。
  - 对包内 `images/web-api.tar` 执行 `docker load`，再用临时 tag 读取 `/app/VERSION`、`/app/RUNNER_VERSION` 和默认版本常量。
  - 校验对象是包内 image tar，不是宿主机同名 tag。
- `scripts/build_bundle_upgrade_package.py`
  - 透传 `allow_existing_images`，并给 CLI 增加 `--allow-existing-images`，避免组合包绕过平台包复用规则。
- `backend/tests/test_v2_package_builders.py`
  - 新增无显式允许时拒绝 `build_images=False` 的测试。
  - 新增 `v0.5.1u2` web-api 镜像内部是 v0.5.2 时必须失败的测试。
  - 新增 v0.5.1u2 / v0.5.2 runner baseline 身份测试。
  - 新增最终包校验脚本必须加载包内 `images/web-api.tar` 的测试。

本地验证：

- 红灯确认：
  - `test_platform_builder_rejects_no_build_without_explicit_existing_image_allowance` 初次失败，旧代码未拒绝静默复用已有镜像。
  - `test_package_identity_verifier_loads_package_image_tar` 初次失败，脚本不存在。
- 绿灯结果：
  - `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_package_builders`：19 tests OK。
  - `PYTHONPATH=backend python3 -m unittest backend.tests.test_upgrade_protocol backend.tests.test_upgrade_runner_engine backend.tests.test_v2_upgrade`：83 tests OK，1 skipped。
  - `python3 -m py_compile scripts/build_upgrade_package.py scripts/build_bundle_upgrade_package.py scripts/verify_upgrade_package_identity.py backend/tests/test_v2_package_builders.py`：通过。
  - `git diff --check -- scripts/build_upgrade_package.py scripts/build_bundle_upgrade_package.py scripts/verify_upgrade_package_identity.py backend/tests/test_v2_package_builders.py task_plan.md findings.md progress.md docs/upgrade-package-ledger.md docs/v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md docs/v0.5.1u2-to-v0.5.2-upgrade-issues.md`：通过。

待执行：

- 同步到 `10.20.11.3`。
- 在 `10.20.11.3` 重打 `v0.5.1u2-fix13-imageidentity`。
- 对生成包执行 manifest / project files / local image identity / package image tar identity / checksums / no sensitive files 静态闸门。
- 静态闸门通过后，再按正常链路验证 `v0.5.1 + runner v0.3.0 -> v0.5.1u2-fix13 -> runner-v0.3.1-handofffix1 -> v0.5.2-cleanupfix2`。

## 2026-07-03 v0.5.1u2-fix13-imageidentity 远端打包阻塞

状态：已停止，未继续修复，未生成包

已执行：

- 已同步当前工作区到 `10.20.11.3:/home/user1/codex-build/worktree-v051u2-fix13`。
- 远端验证通过：
  - `python3 -m py_compile scripts/build_upgrade_package.py scripts/build_bundle_upgrade_package.py scripts/verify_upgrade_package_identity.py backend/tests/test_v2_package_builders.py`：通过。
  - `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_package_builders`：20 tests OK。
  - `PYTHONPATH=backend python3 -m unittest backend.tests.test_upgrade_protocol backend.tests.test_upgrade_runner_engine backend.tests.test_v2_upgrade`：83 tests OK，1 skipped。

打包命令：

```text
host=10.20.11.3
worktree=/home/user1/codex-build/worktree-v051u2-fix13
output_dir=/home/user1/codex-build/packages-v051u2-fix13/01-v0.5.1u2-fix13-imageidentity
target_version=v0.5.1u2
build_images=True
```

失败命令：

```text
env SMARTX_IMAGE_TAG=v0.5.1u2 SMARTX_RUNNER_IMAGE_TAG=v0.3.0 docker compose -f docker-compose.yml build web-api collector-worker frontend
```

失败错误：

```text
env file /home/user1/codex-build/worktree-v051u2-fix13/.env not found: stat /home/user1/codex-build/worktree-v051u2-fix13/.env: no such file or directory
```

当前判断：

- 打包器已正确进入 fix13 新逻辑：构建命令显式带了 `SMARTX_IMAGE_TAG=v0.5.1u2` 和 `SMARTX_RUNNER_IMAGE_TAG=v0.3.0`。
- 失败发生在 Docker compose build 初始化阶段，镜像还没有开始构建。
- 原因是当前 `docker-compose.yml` 声明了必需的 `.env` 文件，远端新构建目录没有同步 `.env`，而 `.env` 又被敏感文件规则禁止进入升级包/仓库同步。
- 这不是 fix13 镜像身份闸门失败，也不是 v0.5.1u2 包内容失败；当前尚未生成任何 `v0.5.1u2-fix13-imageidentity` 包。

未继续执行：

- 未创建 `.env`。
- 未修改远端构建目录。
- 未生成升级包。
- 未执行静态闸门。
- 未执行完整链路验证。
- 未操作 `10.20.11.12`。

## 2026-07-03 v0.5.1u2-fix13-imageidentity 打包与静态闸门

状态：已生成并通过静态闸门；完整链路未开始，因为 `10.20.11.3` 当前不是要求的基线

本轮补充修复：

- 远端首次打包失败原因是 `docker compose build` 在解析 `env_file: .env` 时要求构建目录存在 `.env`。
- 已在 `scripts/build_upgrade_package.py` 增加 `temporary_compose_env_file()`：
  - 如果构建目录原本有 `.env`，保持不变。
  - 如果构建目录缺少 `.env`，仅在 `docker compose build` 期间创建空 `.env`，构建结束后删除。
  - `.env` 不进入升级包。
- 新增测试：
  - 缺失 `.env` 时构建期间会创建临时空 `.env`，构建后删除。
  - 已存在 `.env` 时不覆盖原内容。

本地验证：

- `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_package_builders`：22 tests OK。
- `PYTHONPATH=backend python3 -m unittest backend.tests.test_upgrade_protocol backend.tests.test_upgrade_runner_engine backend.tests.test_v2_upgrade`：83 tests OK，1 skipped。
- `python3 -m py_compile scripts/build_upgrade_package.py scripts/build_bundle_upgrade_package.py scripts/verify_upgrade_package_identity.py backend/tests/test_v2_package_builders.py`：通过。
- `git diff --check`：通过。

远端验证：

- 已重新同步到 `10.20.11.3:/home/user1/codex-build/worktree-v051u2-fix13`。
- 远端 `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_package_builders`：22 tests OK。

生成包：

```text
fix_id=v0.5.1u2-fix13-imageidentity
path=/home/user1/codex-build/packages-v051u2-fix13/01-v0.5.1u2-fix13-imageidentity/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz
sha256=aa3b4a4a09410d3f65dbfa8bb85196b8bf81a58b127056be3ce5e6431cdd6c8a
status=STATIC GATED ONLY
```

静态闸门：

- manifest gate：通过。
- compose/project files gate：通过。
- package checksums gate：通过。
- no sensitive files gate：通过。
- package image tar identity gate：通过。
  - 包内 `images/web-api.tar` 加载后身份：
    - `/app/VERSION=v0.5.1u2`
    - `/app/RUNNER_VERSION=v0.3.0`
    - `core_default_app_version=v0.5.1u2`
    - `core_default_runner_version=v0.3.0`
    - `v2_default_app_version=v0.5.1u2`
    - `v2_default_runner_version=v0.3.0`
- 临时 `.env` 清理：通过，构建目录最终不存在 `.env`。

完整链路未开始：

```text
host=10.20.11.3
current_health.version=v0.5.2
current_health.runner_version=v0.3.0
required_baseline=v0.5.1 + runner v0.3.0
```

原因：

- 当前测试机不在计划要求的第一步基线。
- 如果直接上传/升级 `v0.5.1u2-fix13`，无法证明 `v0.5.1 + runner v0.3.0 -> v0.5.1u2` 第一节点修复有效。

未执行：

- 未恢复 `10.20.11.3` 基线。
- 未开始正常升级链路。
- 未操作 `10.20.11.12`。

## 2026-07-06 v0.5.2 compose.apply recreate runner 失败与 fix16/postcleanupfix3

状态：已本地实现并通过单元测试；待远端打包和完整链路重测

10.20.11.3 链路进展：

```text
baseline: v0.5.1 + runner v0.3.0 + prometheus=true
v0.5.1u2-fix15: task=upgrade-2e7c544a2bb22a17, success
runner-v0.3.1-postcleanupfix3: task=upgrade-8bd9b6acf580e21b, success
v0.5.2-postcleanupfix2: task=upgrade-bb3a007841e9940d, stuck at compose.apply
```

失败证据：

- 目标 `.env` 已迁移成功。
- 目标 task mirror 已存在。
- 目标 compose config 成功。
- 新 project 容器停在 `Created`。
- target runner `smartx-hci-capacity-insight-upgrade-runner-1` 为 `Exited (137)`。
- runner 日志显示 `Container smartx-hci-capacity-insight-upgrade-runner-1 Recreate` 后中断。

根因：主升级 `compose.apply` 包含 `upgrade-runner`，当前 runner recreate 自己导致任务中断。

本地修复：`compose.apply` 排除 `upgrade-runner`，但 manifest、compose override 和最终 compose 文件仍保留 `upgrade-runner`。

本地验证：

```text
Ran 118 tests in 4.461s
OK (skipped=1)
```

下一轮包：

```text
v0.5.1u2-fix16-skip-runner-compose-apply
v0.5.2-postcleanupfix3-skip-runner-compose-apply
runner-v0.3.1-postcleanupfix3 复用
```

## 2026-07-06 v0.5.2 runner 仍停在 bootstrap 运行目录与 fix17 计划

状态：失败原因已确认；开始按 TDD 实施 fix17

10.20.11.3 最新完整链路结果：

```text
baseline: v0.5.1 + runner v0.3.0 + prometheus=true
v0.5.1u2-fix16: task=upgrade-2378cb537ebaae8a, success
runner-v0.3.1-postcleanupfix3: task=upgrade-b3a40ea0a2f72124, success
v0.5.2-postcleanupfix3: task=upgrade-b1ced31ac7c3b494, success
post-cleanup-upgrade-b1ced31ac7c3b494: pending
```

失败证据：

- `/api/system/health` 返回 `version=v0.5.2`、`runner_version=未检测到 runner`、`prometheus=true`。
- `smartx-hci-capacity-insight-upgrade-runner-1` 容器仍运行，但 env 仍是 bootstrap：
  - `SMARTX_UPGRADES_PATH=/data/upgrades`
  - `SMARTX_PROJECT_PATH=/opt/smartx-storage-forecast`
  - `SMARTX_HOST_UPGRADES_PATH=/data/upgrades`
  - `SMARTX_HOST_COMPOSE_RUNTIME_PATH=/data/compose-runtime`
- 新 web-api 使用 `/data/smartx-storage-forecast/app` 和 `/data/smartx-storage-forecast/upgrades`，因此看不到 runner heartbeat，也没人执行新目录中的 post-cleanup task。

根因：

- UPG-027 的 fix16 排除 `upgrade-runner` 是正确的，否则主升级会 recreate 当前 runner 并导致 `Exited 137`。
- 但排除之后没有补上“主任务成功后把 runner 从 bootstrap env 切到最终 v0.5.2 env”的动作。

计划：

- 新增 runner cutover 调度动作，由当前 runner 启动一个短命 helper。
- helper 等待目标 task mirror 中主任务落到 `success` 后，再执行目标 `docker-compose.runner-upgrade.yml` 重建 runner。
- 新 runner 必须使用目标目录：
  - `/data/smartx-storage-forecast/project`
  - `/data/smartx-storage-forecast/app`
  - `/data/smartx-storage-forecast/upgrades`
  - `/data/smartx-storage-forecast/compose-runtime`
  - `/data/smartx-storage-forecast/prometheus`

下一步包：

```text
v0.5.1u2-fix17-runner-cutover
runner-v0.3.1-postcleanupfix4-runner-cutover
v0.5.2-postcleanupfix4-runner-cutover
```

本地实现：

- `backend/app/v2/upgrade/compiler.py`
  - post-cleanup 模式下，在 `post_upgrade.schedule_cleanup` 后追加 `runner.schedule_target_runtime_handoff`。
  - action 参数显式传入目标 project/app/upgrades/backups/exports/compose-runtime/prometheus 路径。
  - `compose.apply` 仍排除 `upgrade-runner`，不回退到自杀式 recreate。
- `backend/app/upgrade_runner/actions.py`
  - 新增 `runner_schedule_target_runtime_handoff`。
  - 写入目标 `/data/smartx-storage-forecast/compose-runtime/docker-compose.runner-upgrade.yml`。
  - 启动短命 helper 容器，等待目标 task mirror 中主任务 `success` 后再重建 runner。
- `backend/app/upgrade_protocol/constants.py`
  - 新 action 归入 `runner.handoff.v1`，不提升协议版本。
- `scripts/build_runner_component_package.py`
  - runner 镜像自检要求包含新 handler。

本地验证：

```text
PYTHONPATH=backend python3 -m unittest \
  backend.tests.test_v2_package_builders \
  backend.tests.test_upgrade_runner_engine \
  backend.tests.test_upgrade_protocol \
  backend.tests.test_v2_upgrade

Ran 119 tests in 4.336s
OK (skipped=1)

git diff --check: passed
py_compile compiler/actions/engine/main/build_runner_component_package: passed
```

## 2026-07-06 post-cleanup package_path 缺失与 fix18 计划

状态：失败原因已确认；开始按 TDD 实施 fix18

10.20.11.3 最新完整链路结果：

```text
baseline: v0.5.1 + runner v0.3.0 + prometheus=true
v0.5.1u2-fix17: success
runner-v0.3.1-postcleanupfix4: success
v0.5.2-postcleanupfix4: task=upgrade-dcb77202330d5173, success
post-cleanup-upgrade-dcb77202330d5173: pending
```

失败证据：

- `/api/system/health` 返回 `version=v0.5.2`、`runner_version=v0.3.1`、`prometheus=true`。
- `post-cleanup-upgrade-dcb77202330d5173/task.json` 在 `/data/smartx-storage-forecast/upgrades` 下存在，但所有 actions 仍为 `pending`。
- `smartx-hci-capacity-insight-upgrade-runner-1` 日志反复出现：

```text
KeyError: 'package_path'
  File "/app/app/upgrade_runner/main.py", line 419, in run_pending_once
```

根因：

- post-cleanup 是平台创建的内置 runner 任务，不是上传升级包任务，因此没有 `package_path`。
- runner 主循环无条件用 `task["package_path"]` 创建 `ActionContext`，导致内置任务无法启动。

修复计划：

- 为 `post_upgrade_cleanup` 这种 package-less 内置任务提供 `<task_dir>/package` 占位路径。
- 普通升级包任务仍继续使用 `task["package_path"]`。
- 新增失败测试覆盖无 `package_path` 的 post-cleanup task 可以被 `run_pending_once` 执行。

实现与验证：

- 本地新增测试先复现 `KeyError: 'package_path'`，再修复通过。
- 修复文件：
  - `backend/app/upgrade_runner/main.py`
  - `backend/tests/test_upgrade_runner_engine.py`
- 本地验证：

```text
PYTHONPATH=backend python3 -m unittest \
  backend.tests.test_v2_package_builders \
  backend.tests.test_upgrade_runner_engine \
  backend.tests.test_upgrade_protocol \
  backend.tests.test_v2_upgrade

Ran 120 tests in 4.561s
OK (skipped=1)

git diff --check: passed
py_compile: passed
```

- 10.20.11.3 远端同组测试：

```text
Ran 120 tests in 29.336s
OK (skipped=1)
```

包与闸门：

```text
v0.5.1u2-fix18-package-less-cleanup-task
path=/home/user1/codex-build/packages-v051u2-fix18/01-v0.5.1u2-fix18-package-less-cleanup-task/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz
sha256=c333c45b260b3632801950ff0ee0570975110e441b222f20b0c693d33772887f

runner-v0.3.1-postcleanupfix5-package-less-cleanup-task
path=/home/user1/codex-build/packages-v052-postcleanupfix5/02-runner-v0.3.1-postcleanupfix5-package-less-cleanup-task/smartx-upgrade-runner-v0.3.1.tar.gz
sha256=fa62c23c498c406ea28734f2deb0d2e03437dcfe5ac53160d3848b63d6c73b53

v0.5.2-postcleanupfix5-package-less-cleanup-task
path=/home/user1/codex-build/packages-v052-postcleanupfix5/03-v0.5.2-postcleanupfix5-package-less-cleanup-task/smartx-capacity-insight-upgrade-v0.5.2.tar.gz
sha256=f76857bef15bcd111cab8051acc066bba43337e86455a63723c32e86ab1fbb10
```

静态闸门：

```text
STATIC_GATE_OK
RUNNER_IMAGE_PACKAGE_LESS_TASK_OK
```

下一步：

- 恢复 `10.20.11.3` 到 `v0.5.1 + runner v0.3.0`。
- 按正常升级流程验证：
  - `v0.5.1u2-fix18`
  - `runner-v0.3.1-postcleanupfix5`
  - `v0.5.2-postcleanupfix5`

## 2026-07-07 v0.5.2 镜像版本控制与 bundle 语义修复计划写入

本轮只写计划和问题记录，未修改代码、未打包、未操作远端环境。

写入内容：

- `docs/v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md`
  - 新增 `UPG-025 v0.5.2 镜像版本控制与 bundle 语义修复计划`。
  - 明确 `.env` 不再控制镜像版本。
  - 明确源码 compose 可作为模板，但包内 compose 必须固定 tag。
  - 明确 bundle 必须透传 `directory_transition`、`legacy_cleanup`、`post_upgrade`、`minimum_runner_version`。
  - 明确 Prometheus chown helper 失败应在 `filesystem.prepare` 阶段硬失败。
- `docs/v0.5.1u2-to-v0.5.2-upgrade-issues.md`
  - 新增 `UPG-025 v0.5.2 镜像版本控制和 bundle 迁移语义风险`。
  - 写入 `.env` allowed/forbidden key。
  - 写入 v0.5.2 / v0.5.1u2 包内 compose 约束。
- `task_plan.md`
  - 新增 `Phase 45 - v0.5.2 镜像版本控制与 bundle 语义修复`。
- `findings.md`
  - 新增 `Phase 45 v0.5.2 镜像版本控制与 bundle 语义发现`。

关键决策：

```text
.env is runtime config only.
Release/upgrade package compose must not depend on SMARTX_IMAGE_TAG or SMARTX_RUNNER_IMAGE_TAG.
Package manifest + fixed package compose tag + container VERSION/RUNNER_VERSION define release identity.
10.20.11.3 is the only validation target for this work.
10.20.11.12 must not be touched in this phase.
```

## 2026-07-07 v0.5.2 镜像版本控制与 bundle 语义修复本地实现

本轮执行 Phase 45，本地代码实现完成，未打包，未操作 10.20.11.3 或 10.20.11.12。

实现内容：

- `scripts/build_upgrade_package.py`
  - 包内 `project/docker-compose.yml`、`project/docker-compose.release.yml`、`project/docker-compose.offline.yml` 在打包阶段渲染为固定 image tag。
  - v0.5.2 包内不再保留 `SMARTX_IMAGE_TAG` / `SMARTX_RUNNER_IMAGE_TAG`。
  - v0.5.1u2 桥包包内固定平台 tag `v0.5.1u2`、runner tag `v0.3.0`，同时保持 legacy project/network/目录。
- `scripts/build_bundle_upgrade_package.py`
  - bundle manifest 从 platform manifest 透传 `minimum_runner_version`、`environment_transitions`、`directory_transition`、`legacy_cleanup`、`post_upgrade`。
- `backend/app/upgrade_runner/actions.py`
  - `.env` sanitize key 扩展到 `SMARTX_IMAGE_TAG`、`SMARTX_RUNNER_IMAGE_TAG`、`SMARTX_APP_VERSION`、`SMARTX_RUNNER_VERSION`。
  - 目标 `.env` 已存在时也 sanitize 并重写，返回 `sanitized_existing`。
  - Prometheus chown helper 失败时抛出 `Prometheus 数据目录权限修复失败...`，不再静默继续。
- `backend/tests/test_v2_package_builders.py`
  - 新增/调整 v0.5.2、v0.5.1u2、bundle 包断言。
- `backend/tests/test_upgrade_runner_engine.py`
  - 新增/调整 `.env` sanitize 和 Prometheus chown 失败断言。

TDD 记录：

```text
RED:
  platform package compose still contained SMARTX_IMAGE_TAG / SMARTX_RUNNER_IMAGE_TAG
  v0.5.1u2 package compose still contained SMARTX_IMAGE_TAG / SMARTX_RUNNER_IMAGE_TAG
  bundle manifest missing minimum_runner_version
  copied .env kept SMARTX_APP_VERSION / SMARTX_RUNNER_VERSION
  existing target .env kept all version keys
  Prometheus chown helper failure did not raise

GREEN:
  all targeted tests passed after implementation
```

本地验证：

```text
PYTHONPATH=backend python3 -m unittest \
  backend.tests.test_v2_package_builders \
  backend.tests.test_upgrade_runner_engine \
  backend.tests.test_v2_upgrade \
  backend.tests.test_upgrade_protocol

Ran 125 tests in 4.503s
OK (skipped=1)

python3 -m py_compile \
  scripts/build_upgrade_package.py \
  scripts/build_bundle_upgrade_package.py \
  scripts/build_runner_component_package.py \
  scripts/verify_upgrade_package_identity.py

passed

git diff --check
passed
```

下一步：

- 在 10.20.11.3 上同步代码后重新打 v0.5.1u2、runner v0.3.1、v0.5.2 包。
- 做静态包内容验证：解包检查 compose 不含版本 env key，bundle manifest 含 v0.5.2 迁移字段。
- 再执行完整链路：

```text
v0.5.1 + runner v0.3.0
  -> v0.5.1u2
  -> runner v0.3.1
  -> v0.5.2
```

- 10.20.11.12 不参与本轮测试或修改。

## 2026-07-07 Phase 45 远端打包与静态闸门

本轮继续执行 Phase 45，只操作 `10.20.11.3`，未操作 `10.20.11.12`。

远端构建目录：

```text
/home/user1/codex-build/worktree-phase45-env-fixed-tags
```

生成包：

```text
v0.5.1 baseline helper:
  /home/user1/codex-build/packages-phase45-env-fixed-tags/00-v0.5.1-baseline/smartx-capacity-insight-upgrade-v0.5.1.tar.gz
  sha256=6353e2102700326a999e41c0bb10bc439cc3cb5236179243540a37dfb10e56bb

v0.5.1u2-envfixed-tags:
  /home/user1/codex-build/packages-phase45-env-fixed-tags/01-v0.5.1u2-envfixed/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz
  sha256=7047d2593dbe855472950c61b5a8f164121c0daca3b71a14f91b1922e221c615

runner-v0.3.1-envfixed-tags:
  /home/user1/codex-build/packages-phase45-env-fixed-tags/02-runner-v0.3.1-envfixed/smartx-upgrade-runner-v0.3.1.tar.gz
  sha256=423facbc4346eea63e03aa4d817bf15dbb62218358b69cbac5ab1c326c9cc4c9

v0.5.2-envfixed-tags:
  /home/user1/codex-build/packages-phase45-env-fixed-tags/03-v0.5.2-envfixed/smartx-capacity-insight-upgrade-v0.5.2.tar.gz
  sha256=123a2603e751f718bf4ced4991a17bc809b206e73dacbd1fb8a79b8d4f79d0d5
```

静态闸门结果：`STATIC_GATE_OK`。

- `v0.5.1u2` 包内 compose 不包含 `SMARTX_IMAGE_TAG`、`SMARTX_RUNNER_IMAGE_TAG`、`SMARTX_APP_VERSION`、`SMARTX_RUNNER_VERSION`。
- `v0.5.1u2` 包内 compose 固定平台 `:v0.5.1u2`、runner `:v0.3.0`，并保留 legacy project/network/目录。
- `runner v0.3.1` manifest `bootstrap_runner.target_root=/data/smartx-storage-forecast`。
- `v0.5.2` 包内 compose 不包含版本 env key，固定平台 `:v0.5.2`、runner `:v0.3.1`。
- `v0.5.2` manifest 包含 `minimum_runner_version`、`environment_transitions`、`directory_transition`、`legacy_cleanup`、`post_upgrade`。

完整链路未开始，阻塞在恢复 `10.20.11.3` 基线：

```text
required_baseline=v0.5.1 + runner v0.3.0
failure_stage=baseline reset
compose=/opt/smartx-storage-forecast/docker-compose.yml
compose_images=nazawsze/smartx-storage-forecast-web-api:v0.5.1,
               nazawsze/smartx-storage-forecast-collector-worker:v0.5.1,
               nazawsze/smartx-storage-forecast-frontend:v0.5.1,
               nazawsze/smartx-storage-forecast-upgrade-runner:v0.3.0
available_images=nazawsze/smartx-hci-capacity-insight-web-api:v0.5.1,
                 nazawsze/smartx-hci-capacity-insight-collector-worker:v0.5.1,
                 nazawsze/smartx-hci-capacity-insight-frontend:v0.5.1,
                 nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.0
error=docker compose attempted to pull old smartx-storage-forecast repositories and then failed because /opt/smartx-storage-forecast/backend build context does not exist
```

当前 `10.20.11.3` 状态：

- SmartX 容器未运行。
- `/opt/smartx-storage-forecast`、`/data/smartx-capacity-insight-data/app`、`/prometheus-data` 已按 baseline reset 创建。
- 未继续执行 `v0.5.1u2 -> runner v0.3.1 -> v0.5.2` 链路。

下一步必须先确认基线恢复策略：

- 用户明确否定“给新镜像补旧仓库 tag”的方案。
- 重新只读检查 `10.20.11.3` 后发现真实 v0.5.1 基线包：
  `/data/upgrade-packages/smartx-capacity-insight-upgrade-v0.5.1.tar.gz`。
- 该包本身定义的旧环境是：
  - 旧 project/network/目录：`smartx-storage-forecast`、`smartx-storage-forecast_smartx-net`、`/opt/smartx-storage-forecast`、legacy `/data/*`。
  - 镜像仓库：`nazawsze/smartx-hci-capacity-insight-*`，版本 `v0.5.1`；runner 为 `nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.0`。
- 结论：上次 `/opt/smartx-storage-forecast/docker-compose.yml` 中的 `nazawsze/smartx-storage-forecast-*` 是错误 baseline helper 产物，不能作为真实旧环境依据。
- 已在 `task_plan.md` 增加 `Phase 46 - 真实 v0.5.1 基线恢复与完整链路验证`。
- 已在 `findings.md` 增加 `Phase 46 真实 v0.5.1 基线恢复发现`。

下一步：

```text
使用 /data/upgrade-packages/smartx-capacity-insight-upgrade-v0.5.1.tar.gz 恢复真实 v0.5.1 + runner v0.3.0 基线
然后执行：
  v0.5.1 -> v0.5.1u2-envfixed-tags
  runner v0.3.0 -> runner-v0.3.1-envfixed-tags
  v0.5.1u2 -> v0.5.2-envfixed-tags
```

## 2026-07-08 Phase 46 基线恢复 Prometheus 权限问题

已按真实 v0.5.1 包恢复 `10.20.11.3` 基线，容器启动到了旧 project：

```text
project=smartx-storage-forecast
network=smartx-storage-forecast_smartx-net
subnet=10.249.249.0/24
health.version=v0.5.1
health.runner_version=v0.3.0
health.checks.prometheus=false
```

失败点：

```text
container=smartx-storage-forecast-prometheus-1
state=Restarting
mount_source=/data/smartx-capacity-insight-data/prometheus
mount_target=/prometheus
owner=root:root
mode=755
error=open /prometheus/queries.active: permission denied
```

根因：

- 真实 v0.5.1 compose 挂载 Prometheus 数据目录为 `/data/smartx-capacity-insight-data/prometheus`。
- 本轮 baseline restore 脚本只创建并 chown 了 `/prometheus-data`，没有处理实际挂载目录。
- 这是测试机基线恢复脚本问题，不是 Phase45 三个候选升级包问题。

修正动作：

```text
mkdir -p /data/smartx-capacity-insight-data/prometheus
chown -R 65534:65534 /data/smartx-capacity-insight-data/prometheus
docker restart smartx-storage-forecast-prometheus-1
重新等待 /api/system/health
```

## 2026-07-08 Phase 46 链路继续验证状态

只读检查 `10.20.11.3` 当前状态：

```text
time=2026-07-08 13:48:12 +0800
health.version=v0.5.1u2
health.runner_version=v0.3.0
health.checks.prometheus=true
project=smartx-storage-forecast
network=smartx-storage-forecast_smartx-net
subnet=10.249.249.0/24
target_network=smartx-hci-capacity-insight-net missing
```

当前运行容器：

```text
frontend image=nazawsze/smartx-hci-capacity-insight-frontend:v0.5.1u2
collector-worker image=nazawsze/smartx-hci-capacity-insight-collector-worker:v0.5.1u2
web-api image=nazawsze/smartx-hci-capacity-insight-web-api:v0.5.1u2
upgrade-runner image=nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.0
prometheus image=prom/prometheus:v2.55.1
```

候选包仍在：

```text
v0.5.1u2 sha256=7047d2593dbe855472950c61b5a8f164121c0daca3b71a14f91b1922e221c615
runner v0.3.1 sha256=423facbc4346eea63e03aa4d817bf15dbb62218358b69cbac5ab1c326c9cc4c9
v0.5.2 sha256=123a2603e751f718bf4ced4991a17bc809b206e73dacbd1fb8a79b8d4f79d0d5
```

下一步：通过正常组件升级流程执行 `runner v0.3.0 -> v0.3.1-envfixed-tags`。如果预检查、升级任务或升级后版本显示失败，停止并记录原因，不继续 v0.5.2。

## 2026-07-08 Phase 46 runner v0.3.1 组件升级结果

通过正常组件升级流程上传并预检查：

```text
package=/home/user1/codex-build/packages-phase45-env-fixed-tags/02-runner-v0.3.1-envfixed/smartx-upgrade-runner-v0.3.1.tar.gz
sha256=423facbc4346eea63e03aa4d817bf15dbb62218358b69cbac5ab1c326c9cc4c9
task_id=upgrade-a70ca672e8b61cd5
upload=ok
precheck=ok
```

启动阶段出现一个需要前端/API 后续优化的现象：

```text
initial start curl saw HTTP error
later start retry returned 400 detail="预检查通过后才能开始升级。"
task status already succeeded
```

实际任务已成功，说明第一次 start 请求已经触发了组件升级，客户端侧拿到的 HTTP 错误属于“服务/状态切换期间的误导性失败提示”，不是升级失败。

组件任务最终状态：

```text
status=succeeded
steps:
  backup=succeeded
  load_images=succeeded
  project_files=succeeded
  write_override=succeeded
  restart=succeeded
  healthcheck=succeeded
runtime_override=/data/compose-runtime/docker-compose.runner-bootstrap.yml
```

升级后验收：

```text
health.version=v0.5.1u2
health.runner_version=v0.3.1
health.checks.prometheus=true
runner_container=smartx-hci-capacity-insight-upgrade-runner-1
runner_image=nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.1
```

下一步：继续通过正常平台升级流程执行 `v0.5.1u2 -> v0.5.2-envfixed-tags`。

## 2026-07-08 UPG-032 组件历史迁移修复与完整链路复测

问题：

```text
phase45 envfixed 完整链路第一次通过后，最终 /api/admin/component-upgrade/history 为空。
原因：task.migrate_runtime_state 只迁移当前 v0.5.2 平台任务，post-cleanup 删除 /data/upgrades 后，旧 runner 组件任务历史丢失。
```

本地修复：

```text
changed=backend/app/upgrade_runner/actions.py
changed=backend/tests/test_upgrade_runner_engine.py
test_added=test_task_migrate_runtime_state_preserves_existing_upgrade_history
```

TDD 记录：

```text
RED:
PYTHONPATH=backend python3 -m unittest backend.tests.test_upgrade_runner_engine.UpgradeEngineTest.test_task_migrate_runtime_state_preserves_existing_upgrade_history
result=FAIL, target_root/upgrade-v051u2/task.json missing

GREEN:
same command
result=OK

REGRESSION:
PYTHONPATH=backend python3 -m unittest backend.tests.test_upgrade_runner_engine backend.tests.test_v2_upgrade backend.tests.test_v2_package_builders backend.tests.test_upgrade_protocol
result=Ran 126 tests in 4.537s, OK (skipped=1)
```

新 runner 包：

```text
package=/home/user1/codex-build/packages-upg032-historyfix/02-runner-v0.3.1-historyfix/smartx-upgrade-runner-v0.3.1.tar.gz
sha256=d10e15cf7b516d172ebe2f1bc37621f9cf32d8ab3abd548f808ae5c5de151d2c
```

复测链路：

```text
baseline=v0.5.1 + runner v0.3.0
v0.5.1u2_package=/home/user1/codex-build/packages-phase45-env-fixed-tags/01-v0.5.1u2-envfixed/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz
v0.5.1u2_sha256=7047d2593dbe855472950c61b5a8f164121c0daca3b71a14f91b1922e221c615
runner_package=/home/user1/codex-build/packages-upg032-historyfix/02-runner-v0.3.1-historyfix/smartx-upgrade-runner-v0.3.1.tar.gz
runner_sha256=d10e15cf7b516d172ebe2f1bc37621f9cf32d8ab3abd548f808ae5c5de151d2c
v0.5.2_package=/home/user1/codex-build/packages-phase45-env-fixed-tags/03-v0.5.2-envfixed/smartx-capacity-insight-upgrade-v0.5.2.tar.gz
v0.5.2_sha256=123a2603e751f718bf4ced4991a17bc809b206e73dacbd1fb8a79b8d4f79d0d5
```

任务结果：

```text
v0.5.1u2_task=upgrade-06220c473a9718b6
v0.5.1u2_status=succeeded
runner_task=upgrade-8ee2b5c0b110944e
runner_status=succeeded
v0.5.2_task=upgrade-a4a200b28bc83d17
v0.5.2_status=succeeded
post_cleanup_task=post-cleanup-upgrade-a4a200b28bc83d17
post_cleanup_status=succeeded
```

最终验收：

```text
health.version=v0.5.2
health.runner_version=v0.3.1
health.checks.prometheus=true
containers=smartx-hci-capacity-insight-* platform v0.5.2, runner v0.3.1, prometheus v2.55.1
network=smartx-hci-capacity-insight-net
subnet=10.249.251.0/24
old_network=smartx-storage-forecast_smartx-net missing
old_paths=/data/upgrades,/opt/smartx-storage-forecast,/data/smartx-capacity-insight-data,/data/backups,/data/exports,/data/compose-runtime,/prometheus-data missing
```

任务历史验收：

```text
/api/admin/upgrade/history count=4
  post-cleanup-upgrade-a4a200b28bc83d17 succeeded v0.5.2
  upgrade-a4a200b28bc83d17 succeeded v0.5.2 sha256=123a2603e751f718bf4ced4991a17bc809b206e73dacbd1fb8a79b8d4f79d0d5
  upgrade-8ee2b5c0b110944e succeeded v0.3.1 sha256=d10e15cf7b516d172ebe2f1bc37621f9cf32d8ab3abd548f808ae5c5de151d2c
  upgrade-06220c473a9718b6 succeeded v0.5.1u2 sha256=7047d2593dbe855472950c61b5a8f164121c0daca3b71a14f91b1922e221c615

/api/admin/component-upgrade/history count=1
  upgrade-8ee2b5c0b110944e component succeeded v0.3.1 sha256=d10e15cf7b516d172ebe2f1bc37621f9cf32d8ab3abd548f808ae5c5de151d2c

/data/smartx-storage-forecast/upgrades contains:
  upgrade-06220c473a9718b6/task.json
  upgrade-8ee2b5c0b110944e/task.json
  upgrade-a4a200b28bc83d17/task.json
  post-cleanup-upgrade-a4a200b28bc83d17/task.json
```

备注：

- 组件 start 接口仍出现一次 `HTTP 409` 但任务实际 succeeded；这是已有“重启/状态切换期间误导性失败提示”问题，未影响本次链路。
- v0.5.2 主任务成功后前两次 health sample 显示 `runner_version="未检测到 runner"`，第三次恢复为 `v0.3.1`；属于 runner handoff/heartbeat 短窗口，最终状态正确。

## 2026-07-08 UPG-033 health runner fallback 修复与完整链路复测

修复目标：

```text
v0.5.2 主任务成功后，即使 runner heartbeat 尚未写入新 DB，
/api/system/health 也应从 running upgrade-runner 容器识别当前 runner 版本。
禁止回退到 web-api 内置 RUNNER_VERSION baseline。
```

代码与测试：

```text
changed=backend/app/v2/system/health.py
changed=backend/tests/test_v2_foundation.py
test_added=test_health_check_falls_back_to_running_runner_probe

PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_foundation backend.tests.test_v2_upgrade backend.tests.test_upgrade_runner_engine backend.tests.test_v2_package_builders backend.tests.test_upgrade_protocol
result=Ran 141 tests, OK (skipped=1)
```

新 v0.5.2 包：

```text
package=/home/user1/codex-build/packages-upg033-healthfix/03-v0.5.2-healthfix/smartx-capacity-insight-upgrade-v0.5.2.tar.gz
sha256=b1b0aff943bd208cc4aed57c0488abccfd0405cbdbadf443253cfad91e1def20
```

完整链路：

```text
baseline=v0.5.1 + runner v0.3.0

v0.5.1u2_package=/home/user1/codex-build/packages-phase45-env-fixed-tags/01-v0.5.1u2-envfixed/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz
v0.5.1u2_sha256=7047d2593dbe855472950c61b5a8f164121c0daca3b71a14f91b1922e221c615

runner_package=/home/user1/codex-build/packages-upg032-historyfix/02-runner-v0.3.1-historyfix/smartx-upgrade-runner-v0.3.1.tar.gz
runner_sha256=d10e15cf7b516d172ebe2f1bc37621f9cf32d8ab3abd548f808ae5c5de151d2c

v0.5.2_package=/home/user1/codex-build/packages-upg033-healthfix/03-v0.5.2-healthfix/smartx-capacity-insight-upgrade-v0.5.2.tar.gz
v0.5.2_sha256=b1b0aff943bd208cc4aed57c0488abccfd0405cbdbadf443253cfad91e1def20
```

任务结果：

```text
v0.5.1u2_task=upgrade-f7bdd6a188ee5d78
v0.5.1u2_status=succeeded
runner_task=upgrade-900f6735e0d76fac
runner_status=succeeded
v0.5.2_task=upgrade-0b23bb79cc9dc869
v0.5.2_status=succeeded
post_cleanup_task=post-cleanup-upgrade-0b23bb79cc9dc869
post_cleanup_status=succeeded
```

最终验收：

```text
immediate health samples 1..8:
  version=v0.5.2
  runner_version=v0.3.1
  health.checks.prometheus=true

network=smartx-hci-capacity-insight-net 10.249.251.0/24
old_network=smartx-storage-forecast_smartx-net missing
old_paths=/data/upgrades,/opt/smartx-storage-forecast,/data/smartx-capacity-insight-data,/data/backups,/data/exports,/data/compose-runtime,/prometheus-data missing
component-upgrade/history contains runner task upgrade-900f6735e0d76fac
/data/smartx-storage-forecast/upgrades contains v0.5.1u2, runner, v0.5.2, post-cleanup task files
```

## 2026-07-08 UPG-037 升级重启窗口与 verification runner fallback 计划记录

用户确认：升级期间前端可以对 Internal Server Error 做容错，但必须有超时时间；默认计划采用 5 分钟。

已写入：

```text
docs/v0.5.1-to-v0.5.2-upgrade-chain-worklog.md
docs/v0.5.1u2-to-v0.5.2-upgrade-issues.md
docs/v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md
```

计划摘要：

```text
UPG-037A:
  frontend upgrade polling treats web-api restart 500/network errors as reconnecting state
  timeout=5 minutes
  after timeout show original error/Internal Server Error

UPG-037B:
  /api/admin/upgrade/verification runner_version fallback aligns with health/component version
  source order=fresh heartbeat -> running runner /app/RUNNER_VERSION -> image tag -> 未检测到 runner
  runner_protocol precheck remains heartbeat-capability strict
```

## 2026-07-08 UPG-037 详细计划补充记录

用户要求把“Internal Server Error 可容错，但必须有超时时间”的方案记录到相关 md。

已更新：

```text
docs/v0.5.1-to-v0.5.2-upgrade-chain-worklog.md
docs/v0.5.1u2-to-v0.5.2-upgrade-issues.md
docs/v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md
task_plan.md
findings.md
```

补充内容：

```text
frontend:
  restart_window_timeout=5 minutes
  scope=upgrade/status, component-upgrade/status, verification refresh, post-cleanup refresh
  behavior=5 minutes reconnecting + keep polling; after timeout show original error/Internal Server Error

backend:
  verification runner_version=fresh heartbeat -> running runner /app/RUNNER_VERSION -> image tag -> 未检测到 runner
  runner_protocol precheck remains fresh-heartbeat capability strict

package_scope:
  rebuild v0.5.2 only
  keep v0.5.1u2 and runner v0.3.1 unchanged unless evidence proves otherwise

validation:
  target=10.20.11.3
  chain=v0.5.1 + runner v0.3.0 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2
  failure_rule=record root cause first and stop before silent repair
```

本次只记录计划，没有修改代码、没有打包、没有操作远端环境。

## 2026-07-08 UPG-037 implementation local verification

- Added backend regression coverage for verification runner fallback and docker-only runner_protocol strictness.
- Added frontend regression coverage for platform/component upgrade polling restart-window tolerance.
- Implemented frontend 5-minute restart-window reconnect handling for upgrade status, component status, verification refresh, and post-cleanup status refresh.
- Backend behavior already satisfied the new verification fallback tests; no production backend change was required.

Verification so far:

```text
PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_upgrade.V2UpgradeServiceTest.test_verification_uses_running_runner_container_when_heartbeat_is_stale backend.tests.test_v2_upgrade.V2UpgradeServiceTest.test_verification_falls_back_to_runner_image_tag_when_version_file_is_empty backend.tests.test_v2_upgrade.V2UpgradeServiceTest.test_runner_protocol_precheck_does_not_accept_docker_only_runner_fallback
result=Ran 3 tests, OK

PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_upgrade backend.tests.test_v2_foundation backend.tests.test_upgrade_runner_engine backend.tests.test_v2_package_builders backend.tests.test_upgrade_protocol
result=Ran 146 tests, OK (skipped=1)

frontend vitest --run ServicePage.test.tsx
result=24 tests passed

frontend vitest --run
result=83 tests passed

frontend tsc -b && vite build
result=passed; Vite large chunk warning only
```

## 2026-07-09 UPG-038 data migration guard planning

用户要求把修复计划详细写入相关 md。

已记录失败事实：

```text
host=10.20.11.3
chain=v0.5.1 + runner v0.3.0 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2
v0.5.1u2_task=upgrade-0d944fd29242c0fb succeeded
runner_task=upgrade-b3b5f205f14f451b succeeded
v0.5.2_task=upgrade-c5510018291d4656 succeeded
post_cleanup=post-cleanup-upgrade-c5510018291d4656 succeeded
failure=business data not migrated
before_counts=towers 1, clusters 1, vm_latest 522, vm_volumes 89529, collection_runs 25
after_counts=towers 0, clusters 0, vm_latest 0, vm_volumes 0, collection_runs 1
task_checkpoint=filesystem.prepare.copied_app_sources []
```

已写入计划：

```text
docs/v0.5.1-to-v0.5.2-upgrade-chain-worklog.md
docs/v0.5.1-to-v0.5.2-upgrade-chain-task-findings.md
docs/v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md
task_plan.md
findings.md
```

计划核心：

```text
policy=compare-before-cleanup
empty target db + legacy business db => replace target with legacy db
conflicting target business db + legacy business db => fail before cleanup
cleanup requires migration checkpoint and business counts validation
rebuild runner v0.3.1 and v0.5.2; keep v0.5.1u2 unchanged unless tests prove otherwise
verify only on 10.20.11.3
```

## 2026-07-09 UPG-038 follow-up cleanup guard path planning

用户要求给出并写入修复计划。

已记录最新失败事实：

```text
host=10.20.11.3
chain=v0.5.1 + runner v0.3.0 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2
v0.5.1u2_task=upgrade-60dd4ec8163e1df0 succeeded
runner_task=upgrade-a272344cdbf0ed85 succeeded
v0.5.2_task=upgrade-14d79d309b95ff76 succeeded
post_cleanup=post-cleanup-upgrade-14d79d309b95ff76 failed
```

关键证据：

```text
host target db=/data/smartx-storage-forecast/app/smartx.db
host target counts=towers 1, clusters 1, vm_latest 523, vm_volumes 89530

active runner mount:
  host /data/smartx-storage-forecast/app -> container /data

inside runner:
  /data/smartx.db = target business db with full counts
  /data/smartx-storage-forecast/app/smartx.db = missing/invalid target path
```

计划核心：

```text
fix_scope=runner v0.3.1 data_migration_guard path normalization
target_host_path_under_SMARTX_HOST_DATA_PATH => map to SMARTX_DB_PATH/container data path
legacy path resolving to same target path => remove from legacy comparison
legacy unavailable after handoff + target has business data => allow cleanup with skipped_reason
legacy still readable + has business data => require target counts >= legacy counts
rebuild runner v0.3.1 and v0.5.2; keep v0.5.1u2 unchanged unless tests prove otherwise
verify only on 10.20.11.3; do not touch 10.20.11.12
```

## 2026-07-10 UPG-041 升级后自动采集

状态：计划完成，开始 TDD 实施。

现场发现：v0.5.2 升级后 SQLite 与 Prometheus 历史目录存在，但最后指标时间早于当前 30 天窗口，页面显示 `0 B` 和无趋势；源库 `vm_latest.name` 本身为 VM ID。检查 compiler/runner/worker 后确认执行链路没有升级后采集动作。

设计：v0.5.1u2 compiler 追加 `post_upgrade.schedule_collection`；runner v0.3.1 写目标任务目录一次性 marker；v0.5.2 collector-worker 在父任务 success 后执行 `trigger=post_upgrade` 采集，并创建独立任务中心记录。失败只告警，不改变平台升级结果。

文档：

```text
docs/superpowers/specs/2026-07-10-post-upgrade-auto-collection-design.md
docs/superpowers/plans/2026-07-10-post-upgrade-auto-collection.md
```

TDD 进度：新增 compiler/runner/worker 测试并确认 RED；最小实现后 96 项定向测试通过，1 项因本机缺 APScheduler 跳过。完整本地 discover 受到环境阻塞：本机为 Python 3.9 且缺 `pydantic`、`fastapi`、`cryptography`、`docx`、`pytest`，产生 35 个导入错误；不是代码断言失败。下一步在 10.20.11.3 依赖完整环境复测。

10.20.11.3 定向依赖完整回归：96 tests OK。UPG-041 包：

```text
v0.5.1u2_sha256=111095012bc2047a84a4c5cd841024e429a29a8a70cb3792c309dd6b4a4fae8f
runner_v0.3.1_sha256=6bb891e5088cbcc4c188e055daf56bd0eb6b695f299e9caec87eb3dbbacea2ff
v0.5.2_sha256=54e67555d06688491ad2c2d2f25a9a47a7e2639aa76f420aee6f7113acd86b94
u2_task=upgrade-16243cd1de457060 success
runner_task=upgrade-d4f926f88ec295ca success
v0.5.2_task=upgrade-d50ecdcf5a316b1f success
auto_collection_task=post-upgrade-collection-upgrade-d50ecdcf5a316b1f failed/warning
```

自动采集失败原因：恢复源数据库含加密密码，但测试恢复夹具只保存了 DB/Prometheus，没有保存与密文配套的旧 `.env`；恢复时使用了不匹配的构建环境 `.env`。任务中心功能正确：标题“升级后自动采集”、progress=100、status=failed、severity=warning，平台 health 仍为 v0.5.2 + runner v0.3.1。不得要求用户重新填写凭据；下一步只读查找配套旧 `.env`，并补充来源库存在加密凭据时的密钥迁移门禁。

用户澄清本次目标不是修复 10.20.11.3 的具体 Tower 密码，而是修复所有环境升级后 Tower 账号凭据未保留的问题。已停止现场历史密钥排查并清理临时目录。通用根因确认：`filesystem_prepare()` 在迁移 DB 前处理 `.env`，且无条件保留已存在的目标 `.env`，会把旧 DB 密文与新/默认密钥拼在一起。下一步按 TDD 增加数据库与 `.env` 配套验证和失败门禁。

UPG-042 TDD 已完成：两个 RED 分别证明旧实现错误保留目标 `.env`、不兼容密钥不失败；实现后 6 个关键用例和本地 100 项升级定向回归通过。10.20.11.3 同组 100 项通过。Docker 集成首次以 user1 运行因无 docker.sock 权限失败，未进入代码逻辑；按既定测试机方式切 root 后同一用例通过，确认真实 web-api `InventoryService` 能接受配套 Fernet 密钥并拒绝错误密钥。

UPG-042 包已在 10.20.11.3 构建并通过静态门禁：runner SHA256 `6db414b85c4a789918fd2a10c4238e383ffc3ae24e7320d130be0c875c9a7c37`；v0.5.2 SHA256 `ed70d52e726f5275aed76ebd645298a8c5c2f6c2dc19061c1221203d93f521a2`。平台包镜像身份、manifest `require_credential_decryption=true`、`post_upgrade.auto_collection=true`、无 `.env`/`smartx.db` 成员检查均通过。

完整链路恢复前检查发现 10.20.11.3 现有恢复归档没有可用的带凭据配套夹具：target DB 加密凭据为 0；旧 named-volume DB 有 1 条加密凭据但归档 `.env` 不兼容。未重置环境、未修改 Tower 凭据、未操作 10.20.11.12。完整链路保持未验证状态。

代码审查发现 UPG-042 三个阻塞：runner 写 `.env` 使用 0644；当前 XOR 凭据无认证，错误密钥可能解出非空 UTF-8；Tower schema 不完整或 SQLite 错误被当作 0 凭据 fail-open。因此已将两个 UPG-042 新包标记 DO NOT DELIVER，后续需 TDD 修正并重打。

按用户方案，10.20.11.3 已恢复为 v0.5.1 + runner v0.3.0 并停止：health 五项正常、Prometheus true，旧 project/network 为 `smartx-storage-forecast` / `smartx-storage-forecast_smartx-net` (`10.249.249.0/24`)；DB 计数为 users 1、towers 1、clusters 1、collection_runs 38、vm_latest 523、vm_volumes 89530；`.env` 位于 `/opt/smartx-storage-forecast/.env`，权限 0600。等待用户重新保存 Tower 凭据后再开始升级。

用户已重新保存 Tower 凭据并完成手动采集。只读基线证据：health `v0.5.1 + runner v0.3.0 + prometheus=true`；collection run `id=39,status=success,trigger=manual`；加密凭据字段 1；VM 总数 556，已有真实名称 195；源 `.env` SHA256 `8b644112e7433b5059b10d1f08ee344295f2217f442e7030df1f62c0ac50814f`。

UPG-042 审查阻塞已进入第二轮 TDD：新增 5 个 RED，覆盖 env 0600、XOR 来源配对、目标 XOR 假阳性拒绝、不完整 Tower schema 和损坏 SQLite fail-closed；实现后 5 项 GREEN，本地升级定向回归 105 项通过、1 项 Docker 测试按环境跳过。尚未重打包或开始升级。

2026-07-14 UPG-042 fix2 构建与链路：runner SHA `509472c7f99efe63628549532e989e8506fb1a679730b84d51caa2f772a71908`，v0.5.2 SHA `d341eec29cb7950bdaecc13c2b115b6efc6c306d213df8fe779440a7aa7874fd`；身份/manifest/敏感文件和专项测试通过。链路中 v0.5.1u2 task `upgrade-ec4bbbdc22e767c4`、runner task `upgrade-f8f3cf2799e9da7c` 成功，v0.5.2 task `upgrade-5abf32abd0faa85b` 在 `filesystem.prepare` 失败。

UPG-043 根因：credential helper 的目标 DB `/data/smartx-storage-forecast/app/smartx.db` 被 `docker_host_path` 误按容器 `/data` 映射为 `/data/smartx-capacity-insight-data/app/smartx-storage-forecast/app/smartx.db`。失败后平台保持 v0.5.1u2 + runner v0.3.1 健康；源/目标 DB 计数一致；源 env SHA 不变且 0600；目标 env、采集 marker、cleanup 均未创建。按约束停止，未修改代码、未重试。

2026-07-14 UPG-043 本地修复：新增 `test_filesystem_prepare_keeps_target_root_database_on_same_host_path_for_credential_helper`。首次运行误用了 `UpgradeEngineTest`，得到用例定位错误；改为正确的 `UpgradeActionTest` 后稳定 RED，实际 mount 为 `host_data_path/smartx-storage-forecast/app/smartx.db`。修复仅在 credential helper 路径解析链传递 manifest `target_root`：该绝对根下 DB/`.env` 保持同宿主机路径，其余路径继续使用原 `docker_host_path()` 映射。目标用例 GREEN；`py_compile` 通过；升级专项回归 `Ran 161 tests in 6.248s, OK (skipped=2)`。尚未同步测试机、打包或重试升级。

2026-07-14 UPG-043 远端与打包：当前源码同步到 10.20.11.3 独立 `/home/user1/codex-build/worktree-upg043`，关键文件 SHA 与本地一致；远端升级专项回归 `Ran 161 tests in 45.445s, OK (skipped=2)`，root Docker Fernet 集成测试 1 项通过。fix3 runner SHA `e424fdca91c17a34328f22f7c79d4dfc2de13edb259a8eedde16b584445e999f`，v0.5.2 SHA `3722d788a3bcb89cd2e5b94a099ce843f6ad470edfac34c5bdf67232c33663a4`；镜像身份、runner 镜像源码、manifest、sidecar/internal checksums、敏感文件、平台不携带 runner/Prometheus 镜像门禁通过。两个中间门禁失败均为临时验证脚本期望值错误，修正脚本后同一包通过，未重建包。完整链路尚未启动。

2026-07-14 UPG-043 fix3 链路核心通过：runner `upgrade-b91262afa445f0e8`、平台 `upgrade-7d86beb3c459bc0a`、自动采集和 post-cleanup 均成功。最终 env SHA/0600、业务计数、VM 名称、当前 Prometheus 194 series、目标 project/network、旧路径删除、连续 health 和 release smoke 均通过。最终 verification 验收暴露 UPG-044：history 按可变 task.json mtime 排序且读取时会补调度旧 cleanup，旧任务被重写后排到最前，最近成功包从 fix3 `3722d788...` 错误回退到旧包 `54e67555...`。已停止，未修改代码或重打包。

2026-07-15 UPG-044 TDD RED：新增 4 个回归测试，分别覆盖 verification 按完成时间而非 mtime 选包、history 不重写成功任务/不补 cleanup、history 对 actions 已完成的 raw running task 只做内存 success 视图、history 按 created_at 而非 mtime 排序。四项均稳定失败且错误与 10.20.11.3 现场一致；尚未修改生产代码。

2026-07-15 UPG-044 最小实现：history 使用纯内存 completed-runner view，不再调用持久化 normalize；history 按 created/uploaded/started/finished/updated 业务时间排序；verification 在成功平台候选中按 finished/uploaded/created/started/updated 时间显式取最新。4 项 UPG-044 测试 GREEN，3 项既有 status/post-cleanup 调度测试通过。本地升级专项完整回归 `Ran 165 tests in 6.651s, OK (skipped=2)`；`py_compile` 与 `git diff --check` 通过。下一步仅在 `10.20.11.3` 的独立构建目录执行同组远端回归。

2026-07-15 UPG-044 fix4 完成：源码同步到 `10.20.11.3:/home/user1/codex-build/worktree-upg044`，关键文件 SHA 匹配，远端 `Ran 165 tests in 49.302s, OK (skipped=2)`。平台包 `/home/user1/codex-build/packages-upg044-verification-history-fix4/03-v0.5.2-upg044-fix4/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` SHA256 `29fa1ca308ab41db999a58c6d93908f601d1b355822cab6c6c66ac5a2c8390b7`；sidecar、manifest、internal checksums、镜像身份、敏感成员和不携带 runner/Prometheus 镜像门禁通过。runner 复用 UPG-043 fix3 `e424fdca...`。

2026-07-15 UPG-044 现场隔离验收：fix4 service 连续 5 次、HTTP verification 连续 3 次均选择 `upgrade-7d86beb3c459bc0a / 3722d788...`；release smoke `critical=0, warning=0`，health directories/database/prometheus 全 true。查询前后线上 10 个历史 `task.json` SHA/mtime 不变，目录与 cleanup 集合不变；临时容器和 fixture 已删除。首次 HTTP fixture 因只读 Prometheus 目录导致 marker health false，按规则停止并报告；修正为独立可写 fixture 且显式要求 `health.ok=true` 后一次通过。未替换运行中的 web-api，未重跑完整升级链，未操作 `10.20.11.12`。

## 2026-07-10 UPG-040 空业务库 post-cleanup 兼容修复

状态：已在 `10.20.11.3` 与 `10.20.11.12` 验证。

根因：UPG-039 只放行“legacy path handoff 后不可读，但 target 已有业务数据”。空系统来源没有 Tower/cluster/VM 数据时，target 合法地也没有业务数据，旧逻辑仍错误阻止 cleanup。

修复：`data_migration_guard` 读取父 v0.5.2 任务 `filesystem.prepare` checkpoint。只有 `source_db_counts` 明确无业务数据且 target DB 有效时，返回 `parent_source_had_no_business_data`；父 checkpoint 缺失、target 无效、或 source 有业务数据仍保持失败。

测试和包：

```text
local=Ran 152 tests in 6.092s, OK (skipped=1)
10.20.11.3=Ran 152 tests in 48.113s, OK (skipped=1)

runner=/home/user1/codex-build/packages-upg040-empty-source/02-runner-v0.3.1-upg040-empty-source/smartx-upgrade-runner-v0.3.1.tar.gz
runner_sha256=ed416b97b7afab6c06359d3b74aa6e03256c8f41e5b7313b4dc3a85634d475d1
v0.5.2=/home/user1/codex-build/packages-upg040-empty-source/03-v0.5.2-upg040-empty-source/smartx-capacity-insight-upgrade-v0.5.2.tar.gz
v0.5.2_sha256=0b2166d36a7fd0ccc54416ba4ac1d0f749eeb9cbbce1b979b2735957de207b4d
```

验证：

```text
10.20.11.3:
  u2=upgrade-891334c5ac85007b success
  runner=upgrade-52f6c7c53b89ad53 success
  v0.5.2=upgrade-a3734551cbbaff02 success
  post_cleanup=success

10.20.11.12:
  u2=upgrade-79cae85f494677a2 success
  runner=upgrade-3ec9762ff81c5101 success
  v0.5.2=upgrade-5a22d9f11248f7f3 success
  post_cleanup=post-cleanup-upgrade-5a22d9f11248f7f3 success
  final_db=users 1; towers/clusters/collection_runs/vm_latest/vm_volumes 0
  legacy_paths=all missing
```

## 2026-07-17 UPG-047 恢复执行检查点

- 断电前的 `10.20.11.3` 依赖完整回归会话已收尾并读取最终输出：`Ran 198 tests in 151.108s`、`OK (skipped=1)`、退出码 `0`。
- 本地同一源码完整回归证据为 `Ran 198 tests, OK (skipped=4)`。
- UPG-046 已修复 runner 顶层已成功但任务中心仍停在 `running/32%` 的投影遗漏，并增加重复查询不改变 `updated_at` 的幂等测试。
- UPG-047 已确认已发布 runner 固定把 `.env` 写为 `0644`；兼容修复位于 v0.5.2 三份 compose 的 runner 启动命令，启动时先 `chmod 600` 再 exec runner。
- 真实 bind mount 验证结果：容器内和宿主机 `.env` 最终均为 `0600`。
- fix6 SHA `2a1cbd0aeb193608fadbd96ef2b8c77837d258a1cda81e2c9aeb83857e54c154` 不包含 UPG-047，标记为 `DO NOT USE`。
- 下一步：仅从 `10.20.11.3:/home/user1/codex-build/worktree-upg047` 构建 fix7，执行全部包体门禁后直传 `10.20.11.12`，再跑不修改两个 release 输入包的完整升级链。

## 2026-07-17 UPG-047 fix7 构建与静态门禁

```text
package=/home/user1/codex-build/packages-upg047-env-permission-fix7/03-v0.5.2-upg047-fix7/smartx-capacity-insight-upgrade-v0.5.2.tar.gz
sha256=1cde8e34617fcddc00e1a334516694ab0e34fc2997f164a91c718f5f17317497
size=234M
build_host=10.20.11.3
source=/home/user1/codex-build/worktree-upg047
```

门禁结果：

- sidecar SHA：PASS。
- 包内 `checksums.sha256`：54/54 PASS。
- `verify_upgrade_package_identity.py`：PASS；web-api 内部平台版本 `v0.5.2`、runner 基线 `v0.3.1`。
- bundled images：仅 `web-api`、`collector-worker`、`frontend`，三个 Docker archive RepoTag 均匹配 `v0.5.2`。
- 敏感成员：无 `.env`、SQLite DB、Prometheus 历史数据、PEM/key/id_rsa。
- manifest：schema 3、minimum runner `v0.3.1`、自动采集和 post-cleanup 开启、来源版本列表与目录迁移/cleanup 声明 PASS。
- 三份包内 compose：固定 `smartx-hci-capacity-insight`、`smartx-hci-capacity-insight-net`、`10.249.251.0/24`，且均包含 runner 启动前 `.env chmod 600`；镜像 tag 不受 `.env` 控制。

命令错误记录：首次在源码目录执行 `sha256sum -c <绝对 sidecar 路径>`，sidecar 内相对文件名因此找不到包；切换到包目录后同一 sidecar 校验通过。该错误未修改包，也没有触发重建。

## 2026-07-17 UPG-047 fix7 完整链路失败记录

```text
host=10.20.11.12
baseline=v0.5.1 + runner v0.3.0
baseline_env_sha256=8b644112e7433b5059b10d1f08ee344295f2217f442e7030df1f62c0ac50814f
baseline_env_mode=0600
baseline_db=users 1, towers 0, clusters 0, collection_runs 3, vm_latest 0, vm_volumes 0

v0.5.1u2_task=upgrade-fc5d72c0b5125050 succeeded
runner_v0.3.1_task=upgrade-70f37539375c0ab4 succeeded
v0.5.2_fix7_task=upgrade-786276d25169aa9d succeeded
auto_collection_task=post-upgrade-collection-upgrade-786276d25169aa9d success
post_cleanup_task=post-cleanup-upgrade-786276d25169aa9d success
```

任务中心投影修复验收通过：parent 为 `success/100`，连续两次 status 查询的 `updated_at` 都是 `2026-07-16T17:31:22.088980+00:00`。

最终安全门禁失败：

```text
env_sha256=8b644112e7433b5059b10d1f08ee344295f2217f442e7030df1f62c0ac50814f
env_mode=0644  # expected 0600
runner_actual_cmd=["python","-m","app.upgrade_runner.main"]
runner_config_file=/runner-cutover/runtime/docker-compose.runner-upgrade.yml
```

根因证据：已发布 u2 编译器把 `upgrade-runner` 从 `compose.apply` 服务列表排除；已发布 runner 的 `_write_runner_runtime_compose()` 又把 handoff compose 命令硬编码为 `python -m app.upgrade_runner.main`。异步 helper 在父任务成功后使用这份 compose `--force-recreate upgrade-runner`，因此 fix7 正式 compose 中的 runner chmod 命令不会进入最终容器。fix7 标记为 `DO NOT USE`。

fix8 决策：不修改 u2/runner。将 chmod shim 放到主 apply 必定重建的 web-api：只绑定目标 `.env` 单文件到 `/run/smartx-runtime.env`，web-api 启动时先 chmod 0600 再 exec 原 uvicorn。先做 RED/GREEN，再重建和重跑完整链路。

## 2026-07-17 UPG-048 fix8 远端验证与 .3-only 约束

当前执行边界：

```text
python_tests=10.20.11.3 only
dependency_installation=10.20.11.3 only
image_and_package_build=10.20.11.3 only
full_chain=10.20.11.3 only
10.20.11.12=do not connect or modify
```

fix8 已同步到：

```text
/home/user1/codex-build/worktree-upg048
```

`10.20.11.3` 已通过：

```text
deployment_env_shim=PASS
package_builder_targeted=2 tests OK
dependency_complete_regression=Ran 198 tests in 154.158s, OK (skipped=1)
real_docker_bind=host mode 0644 -> 0600; web-api running; PASS
free_space=/ 41G available; /tmp 7.9G available
```

待执行：同步本轮文档到远端工作区；构建 fix8；包体门禁；恢复 `.3` 的真实 v0.5.1 + runner v0.3.0 配套业务基线；走 immutable u2/runner/fix8 正常链路并完成全量验收。

### UPG-048 v0.5.1 历史基线身份校验器兼容差异

恢复前在 `10.20.11.3` 用当前 `verify_upgrade_package_identity.py` 校验真实历史 v0.5.1 包时停止：

```text
package_sha256=ef24643b1c5a13401c85eb5e4bd3ecac4781bf0af810b85a881037192086e2f2
sidecar=PASS
verifier_failure=v2_default_app_version expected v0.5.1, got v0.5.0
```

只读取证：

```text
/app/VERSION=v0.5.1
/app/RUNNER_VERSION=v0.3.0
core_default_app=v0.5.1
core_default_runner=v0.3.0
v2_default_app=v0.5.0
v2_default_runner=v0.3.0
manifest.version=v0.5.1
```

结论：该包生成于严格镜像身份门禁引入之前，只有未作为运行版本来源的 v2 默认常量遗留 `v0.5.0`。这是当前校验器对历史恢复输入的兼容差异，不是本轮 fix8 包失败，也不修改已发布/历史输入。基线恢复继续以 `/app/VERSION`、`/app/RUNNER_VERSION`、运行镜像 tag 和实际 health 四项一致为硬门禁。

### UPG-048 fix8 构建、静态门禁与 v0.5.1 基线恢复

fix8 包：

```text
host=10.20.11.3
source=/home/user1/codex-build/worktree-upg048
package=/home/user1/codex-build/packages-upg048-webapi-env-permission-fix8/03-v0.5.2-upg048-fix8/smartx-capacity-insight-upgrade-v0.5.2.tar.gz
sha256=692aca8b58ad8199c43c02a3771fa4fd7a62f1d7bbf4f198af4bd2e4b2c67733
size=245282000
```

门禁通过：sidecar、包内 54/54 checksums、web-api 内部 `v0.5.2/v0.3.1` 身份、manifest/source compatibility、仅三件套 archive、三个 Docker RepoTag、55 个成员敏感扫描、三份 target compose web-api shim、旧 bridge `/opt/smartx-storage-forecast/.env` 渲染。

恢复前保全：

```text
fixture=/home/user1/codex-build/fixtures/upg048-v051-business-pair-20260717
db_sha256=b84520c9a3b57af9587c62b0ad6e7632a91f40761d0b0cd5a1e4631a8b3c4ff1
env_sha256=8b644112e7433b5059b10d1f08ee344295f2217f442e7030df1f62c0ac50814f
sqlite_integrity=ok
```

恢复后基线：

```text
health=v0.5.1 + runner v0.3.0; all checks true
containers=web-api/collector-worker/frontend v0.5.1 + runner v0.3.0 + prometheus v2.55.1
project=smartx-storage-forecast
network=smartx-storage-forecast_smartx-net
subnet=10.249.249.0/24
db=users 1,towers 1,clusters 1,collection_runs 47,vm_latest 556,vm_volumes 89588,tasks 13
env_sha256=8b644112e7433b5059b10d1f08ee344295f2217f442e7030df1f62c0ac50814f
env_mode=0600 root:root
target_root=/data/smartx-storage-forecast missing
```

非产品命令错误：当前 Docker Compose 不支持只读参数 `config --networks`，返回 `unknown flag`；改用受支持的完整 `docker compose config` 读取网络，确认无配置问题。

### UPG-048 fix8 完整链路最终验收

输入：

```text
v0.5.1u2_sha256=d5f277167445e7636ddfba16b4f780b40d59952467bb1c8e72d2469b43ee0a49
runner_v0.3.1_sha256=d10e15cf7b516d172ebe2f1bc37621f9cf32d8ab3abd548f808ae5c5de151d2c
v0.5.2_fix8_sha256=692aca8b58ad8199c43c02a3771fa4fd7a62f1d7bbf4f198af4bd2e4b2c67733
```

正常产品流程任务：

```text
v0.5.1u2=upgrade-5680ff0264c4acbd succeeded
runner_v0.3.1=upgrade-53ebaff4da3218df succeeded
v0.5.2_fix8=upgrade-9ad951d4024b2c16 succeeded
post_cleanup=post-cleanup-upgrade-9ad951d4024b2c16 succeeded
auto_collection=post-upgrade-collection-upgrade-9ad951d4024b2c16 success
```

最终验收：

```text
health=v0.5.2 + runner v0.3.1; directories/database/prometheus true
task_center_parent=success/100
task_center_updated_at=2026-07-16T18:43:53.471181+00:00; repeated status unchanged
task_files=4; three history + three verification reads preserved all SHA256 and mtime
verification_package=upgrade-9ad951d4024b2c16 / 692aca8b58ad8199c43c02a3771fa4fd7a62f1d7bbf4f198af4bd2e4b2c67733
env_sha256=8b644112e7433b5059b10d1f08ee344295f2217f442e7030df1f62c0ac50814f
env_mode=0600 root:root
db_integrity=ok
db=users 1,towers 1,clusters 1,collection_runs 48,vm_latest 556,vm_volumes 89588
latest_collection=id 48,status success,trigger post_upgrade,clusters 1,vms 194
real_vm_names=195
prometheus_current_vm_series=194
containers=exact five target containers; image IDs match v0.5.2/v0.3.1/v2.55.1 tags
project_network=smartx-hci-capacity-insight / smartx-hci-capacity-insight-net / 10.249.251.0/24
target_layout=all seven directories present
legacy_project_network_paths=all missing
web_api_env_mount=single-file RW; project mount RO; chmod shim active
runner_handoff_command=original python -m app.upgrade_runner.main
release_smoke=critical 0, warning 0
```

输入路径错误记录：计划中的 `/data/upgrade-packages/validated-upg036` 便捷副本已被此前空间清理移除。未重新打包；改用 `.3` 上原始构建产物并校验固定 SHA 完全匹配后继续。

### 2026-07-17 最终只读复核命令错误

- 目标机：仅 `10.20.11.3`。
- 首次只读复核尝试使用 `sudo -S`，远端返回 `user1 is not in the sudoers file`，命令在任何产品检查或环境操作前终止，环境无变化。
- 第二次连接测试使用 `sshpass` 直接等待嵌套 `su` 提示，停在 `Password:`；未执行产品命令。改为通过 SSH 标准输入单独向 `su` 提交密码后，`id` 返回 `uid=0(root)`。
- 第一次整组复核已确认 fix8 包 SHA256 一致，但错误调用 `/api/v2/system/health` 得到 HTTP 404；因命令启用了 `set -e`，其余只读项未执行。代码确认真实路由为 `/api/system/health`，该 404 不是产品健康失败。
- 后续严格使用既定连接方式 `ssh user1@10.20.11.3` 后 `su - root`；不在本地运行 Python、不安装依赖，也不连接 `10.20.11.12`。

### 2026-07-17 UPG-048 fix8 最终只读复核

- 所有 Python 验证仍只在 `10.20.11.3` 执行；本地未运行 Python、未安装库、未构建或重打包。
- fix8 包 SHA256 复核为 `692aca8b58ad8199c43c02a3771fa4fd7a62f1d7bbf4f198af4bd2e4b2c67733`。
- `/api/system/health` 返回 `ok=true`、平台 `v0.5.2`、runner `v0.3.1`，`directories/database/prometheus` 全部为 `true`。
- 5 个目标容器均为 running；平台镜像为 `v0.5.2`，runner 为 `v0.3.1`，Prometheus 为 `v2.55.1`。
- `.env` 为 `0600 root:root`，SHA256 仍为 `8b644112e7433b5059b10d1f08ee344295f2217f442e7030df1f62c0ac50814f`。
- 网络为 `smartx-hci-capacity-insight-net / 10.249.251.0/24`；七个目标目录均存在，`/opt/smartx-storage-forecast`、`/data/upgrades`、`/data/backups`、`/data/exports` 均不存在。
- 在 `.3` 运行 `scripts/release_smoke_check.py --fail-on-warning`：`critical_count=0`、`warning_count=0`；登录、任务列表、报表 VM 名称、平台/runner/Prometheus 版本、compose project 和 5 服务验证全部通过。
- verification API 回显最终包任务 `upgrade-9ad951d4024b2c16`，包 SHA256 与上述 fix8 SHA 完全一致。

### 2026-07-17 持续目标完成审计准备

- 从主链路 worklog、升级问题文档、包台账和 `task_plan.md` 重新提取验收要求，确认不能以单一 health/smoke 替代完整链路证据。
- 首次向 `findings.md` 追加审计清单时提交了缺少上下文的空 hunk，`apply_patch` 明确拒绝，文件未改变；随后读取文件末尾并使用有效上下文重新追加。
- 首次读取四个目标 task 文件时发现 `.3` 宿主机没有 `jq`，四次摘要命令均返回 `jq: command not found`；未安装 `jq`，改用 `.3` 的 Python 标准库后成功读取四个 task JSON、SQLite 完整性、业务计数和最新任务。

### 2026-07-17 持续目标完成审计证据

- 三个固定输入包 SHA256 重新核对一致：u2 `d5f277167445e7636ddfba16b4f780b40d59952467bb1c8e72d2469b43ee0a49`、runner `d10e15cf7b516d172ebe2f1bc37621f9cf32d8ab3abd548f808ae5c5de151d2c`、fix8 `692aca8b58ad8199c43c02a3771fa4fd7a62f1d7bbf4f198af4bd2e4b2c67733`。
- 四个目标 task JSON 均为成功：u2、runner、fix8 主任务和 post-cleanup；SQLite 任务中心额外确认父任务、组件任务、post-cleanup 和自动采集均为 `success/100`。
- SQLite `PRAGMA integrity_check=ok`；计数为 `users=1,towers=1,clusters=1,collection_runs=48,vm_latest=556,vm_volumes=89588,tasks=18`。最新 run `id=48,status=success,trigger=post_upgrade`，消息为 1 个集群/194 台 VM。
- 连续三轮 status/system history/component history/verification 后，父任务 `updated_at` 不变，四个 `task.json` SHA/mtime 不变；verification 稳定指向 `upgrade-9ad951d4024b2c16` 和 fix8 SHA。
- 首次 Prometheus `/series` 查询得到的是整个保留期历史集合（720 series/210 VM ID），不能作为本次采集计数；改按 run 48 完成时间执行 instant query 后得到 194 series、194 唯一 VM ID、194 个非空 VM 名称。
- 包身份校验器首次以 `user1` 运行因 Docker socket 权限不足失败；随后两次无 TTY 的 root 调用没有返回脚本 JSON，均按证据不足处理。最终使用交互式 `su - root` 成功，退出码 0 并返回 `IDENTITY_CHECK_EXIT_0`；包内 web-api 的版本文件、core/v2 平台默认版本均为 `v0.5.2`，runner 版本文件和 core/v2 runner 默认版本均为 `v0.3.1`。
- 身份校验后重新核对运行态：health 全真，五容器 running 且容器 image ID 与 tag ID 一致；target network 为 `10.249.251.0/24`；旧 project 容器/network 为空；七目录存在，六个 legacy 路径不存在；`.env` 保持 `0600 root:root` 和原 SHA。
- 最终在 `.3` 运行认证 release smoke，并启用 `--fail-on-warning`：`ok=true,critical_count=0,warning_count=0`。前端、Prometheus、health、登录、任务列表、报表 VM 名称、平台/runner/Prometheus 版本、compose project、verification 包身份和五服务全部通过。

### 2026-07-22 `10.20.11.12` 验证：未通过，停止在只读诊断

- root/password 交互式 SSH 登录成功；网络与 SSH 服务正常。未执行重置、清理、上传、重启或升级。
- health 返回 `v0.5.2 + runner v0.3.1`，五个目标容器 running；目标 network 为 `smartx-hci-capacity-insight-net / 10.249.251.0/24`。
- 业务数据库完整性为 `ok`，但计数为 `users=1,towers=0,clusters=0,collection_runs=10,vm_latest=0,vm_volumes=0,tasks=15`；Prometheus VM instant query 返回空结果；自动采集任务均报告 0 集群/0 VM。
- 仅发现目标 `/data/smartx-storage-forecast/app/smartx.db`，backups 目录为空，无旧 SQLite 数据库或 named volume；因此现场无法证明升级前业务数据仍存在，也没有可恢复副本。
- `.12` v0.5.2 task `upgrade-786276d25169aa9d` 的 package SHA 为 `1cde8e34617fcddc00e1a334516694ab0e34fc2997f164a91c718f5f17317497`（fix7，`DO NOT USE`），manifest `database_migration=false`；当前 `.env` 为 `0644`，不是 fix8 的 `0600`。
- 历史 `upgrade-7b8f26242070ee47` 仍为 `running/32%`；其后续 post-cleanup/auto-collection 成功状态不能证明数据迁移成功，因为结果均为 0 数据。
- 发现 `/data/smartx-storage-forecast/app/smartx-storage-forecast` 仅含空 `project` 子目录，约 8 KB，疑似旧残留；按用户要求本轮不自行清理。
- 结论：`.12` 当前不是可接受的完整链路验证基线。继续验证前必须先恢复有效 `v0.5.1 + runner v0.3.0` 业务库/凭据基线，再上传并使用 fix8；本轮在发现数据为空后已停止。

### 2026-07-22 `.12` 恢复重跑预检

- 用户明确要求将 `.12` 恢复后重新验证完整链路；执行链固定为 `v0.5.1 + runner v0.3.0 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2 fix8`。
- 本地记录和 `.3` 包目录确认可用的固定输入为：历史 v0.5.1 基线包、u2 `d5f277...`、runner `d10e15...` 和 fix8 `692aca...`。业务 DB/.env 夹具位于 `/home/user1/codex-build/fixtures/upg048-v051-business-pair-20260717`，需以 root 只读核验后使用。
- `.3` 夹具存在 `.env`（365 bytes）和 `smartx.db`（34,844,672 bytes）；包 SHA 已重新核对：v0.5.1 `6353e210...`、u2 `d5f277...`、runner `d10e15...`、fix8 `692aca...`。`.3` 可用 43 GB，`.12` 可用 40 GB。

### 2026-09-12 AI 项目标准文档

- 新增根目录 `AGENTS.md`，规定 AI 开始工作前的文档读取顺序、`dev2` 分支规则、`.3` 验证机边界、升级链路、数据保护、包门禁和失败报告标准。
- 新增 `docs/project-guide-for-ai.md`，集中说明项目架构、五个容器职责、SQLite/Prometheus 数据边界、旧/新目录、`v0.5.1 + runner v0.3.0 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2` 链路、历史问题结论和文档索引。
- 本次只修改文档，没有修改业务代码、升级包、远端环境或运行时数据；`git diff --check` 通过。
- 补充服务器角色矩阵：`10.20.11.3` 为主测试机，`10.20.11.12` 为升级演练机，`10.20.0.6` 为 release canary/生产等价验收机；默认操作边界已写入 `AGENTS.md` 和 `docs/project-guide-for-ai.md`。
- 将完整服务器清单同步到 `task_plan.md` 和项目进度摘要，明确三台服务器的用途、操作边界和凭据不入库规则。

