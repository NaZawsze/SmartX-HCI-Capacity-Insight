# SmartX HCI Capacity Insight - 工作进度

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

## 2026-06-01

### 创建项目持久化上下文文档

状态：完成

已创建：

- `task_plan.md`
- `findings.md`
- `progress.md`

目的：

- 让后续会话可以快速恢复项目上下文。
- 记录远端路径、分支规则、部署方式和已知问题。
- 避免依赖本地 `planning-with-files` 插件 hook，降低 reconnect 风险。

### 当前远端状态

远端：

- 主机：`10.20.11.3`
- 项目路径：`/data/smartx-storage-forecast/project`
- 分支：`dev`
- 当前基线：`ed3ed5f`，标签 `v0.3.3U1`

未提交应用变更：

- `backend/app/api/routes.py`
- `backend/app/services/dashboard.py`
- `frontend/src/components/ClusterCapacityChart.tsx`
- `frontend/src/pages/ReportsPage.tsx`
- `frontend/src/pages/VmsPage.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/types.ts`

这些变更属于最近的报表/图表优化：

- 已使用百分比文案。
- 报表容量增长速率固定按 7 天平均计算。
- 报表趋势图支持 7/30/90/365/720 天范围。
- 后端报表接口支持 `chart_days`。

### 已完成验证

近期报表/图表变更此前已验证：

- `python3 -m py_compile backend/app/services/dashboard.py backend/app/api/routes.py` 通过。
- `docker compose build frontend` 通过。
- `docker compose build web-api` 通过。
- 已重启 `web-api` 和 `frontend`。
- `frontend` 返回 `200`。
- `api_metrics` 返回 `200`。
- `chart_days=720` 直接检查返回了有效响应，包含 `growth_rate_window_days: 7`。

### 本次注意

- 本次只写文档，不提交代码。
- 文档不包含密码或敏感凭据。
- 后续如果用户要求提交，应先检查所有未提交变更，确认文档和应用改动是否一起提交。

### 导出报表可读性优化

状态：完成

本次需求：

- 导出报表中当前容量、上期容量、增长量、增长率相关 VM 表格需要增加排序能力或排序标识。
- 增长率超过 20% 且增长量大于 100 GiB 的虚拟机需要红色底纹标识。
- Word 增加按集群定位的目录栏。

已修改：

- `backend/app/services/report_export.py`

待验证：

- 后端语法检查。
- 容器内生成 Word 和 Excel 文件。
- 检查 Excel 包含目录 sheet、表格结构和高亮底纹。
- 检查 Word 包含目录和集群书签/跳转结构。

验证结果：

- `python3 -m py_compile backend/app/services/report_export.py` 通过。
- 已重建并重启 `web-api`。
- 容器内生成 `storage-forecast-all-20260601.docx`，大小约 150 KiB。
- 容器内生成 `storage-forecast-all-20260601.xlsx`，大小约 44 KiB。
- Excel 检查到 `目录` sheet、`VmAmountSummary` 和 `VmRatioSummary` 表格。
- Word 检查到目录、集群 bookmark、排序表头和排名列。
- 构造高风险 VM 样例验证：Word 和 Excel 均写入 `F4CCCC` 红色底纹。
- `/metrics` 返回 `200`。

### 修复导出报表生成时间时区

状态：完成

发现：

- `10.20.11.3` 宿主机当前时区是 `America/New_York`。
- `web-api` 容器当前时区是 `UTC`。
- 应用配置 `SMARTX_COLLECTION_TIMEZONE=Asia/Shanghai`。
- 报表导出原来使用 `datetime.now()`，依赖容器默认时区，所以生成时间慢 8 小时。

修复：

- `backend/app/services/report_export.py` 使用 `get_settings().collection_timezone` 和 `zoneinfo.ZoneInfo` 生成本地时间。
- Word/Excel 的生成时间显示增加时区名，例如 `2026-06-01 13:33:27 Asia/Shanghai`。

验证：

- 重建并重启 `web-api`。
- 重新生成 Word/Excel。
- Word 检查到生成时间为 `2026-06-01 13:33:27 Asia/Shanghai`。
- Excel 检查到生成时间为 `2026-06-01 13:33:37 Asia/Shanghai`。
- `/metrics` 返回 `200`。

### 版本治理

状态：进行中

已完成：

- 盘点仓库和 DockerHub 版本混乱问题。
- 临时隔离修复 `main` 的三份 compose 文件，并将 `v0.5.0` tag 指向该修复提交。
- 在 dev 中新增 `RUNNER_VERSION`。
- 将平台版本元数据改为 `v0.5.0`。
- 将 runner compose tag 拆为 `SMARTX_RUNNER_IMAGE_TAG:-v0.3.0`。
- 平台升级包脚本不再包含 `upgrade-runner.tar`。
- runner 组件包脚本默认读取 `RUNNER_VERSION`。
- GitHub Actions 拆分平台三件套和 runner 专用 workflow。
- 新增 `docs/version-governance.md` 记录版本规则和 DockerHub tag 清理方法。

待验证：

- Python 语法检查。
- `scripts/build_upgrade_package.py --check-version`。
- 关键测试断言。
- 敏感信息扫描。

验证记录：

- `python3 -m py_compile backend/app/services/upgrade.py backend/app/core/config.py scripts/build_upgrade_package.py scripts/build_runner_component_package.py backend/tests/test_deployment_config.py backend/tests/test_upgrade.py` 通过。
- `python3 scripts/build_upgrade_package.py --check-version` 通过，输出 `Version metadata OK: v0.5.0`。
- 直接导入 `backend/tests/test_upgrade.py` 时本地缺少 `pydantic`，需要在远端环境或容器内跑完整导入测试。

### 修复清理空间显示 0B

状态：完成

发现：

- 镜像扫描显示的是未被容器使用的镜像，但清理接口原来调用 Docker `/images/prune`，带 tag 的旧版本镜像经常不会被 prune 删除，所以 Docker 返回 `SpaceReclaimed=0`。
- 服务管理的空间清理成功后立即调用 `scanSpaceCleanup()`，清理后自然扫描为 `0B`，覆盖了本次清理释放结果。

修复：

- `backend/app/services/system_control.py` 镜像清理改为逐个删除扫描出的未使用镜像。
- 镜像清理结果返回候选逻辑大小、预计释放大小和删除失败列表。
- `frontend/src/pages/ServicePage.tsx` 保留本次清理结果，不再用清理后重扫覆盖为 `0B`。
- `docs/upgrade-issues.md` 将 UPG-013 标记为已解决。

### 升级预检查步骤化与网络检查

状态：完成

发现：

- 后端平台预检查已有 manifest、version、services、sha256、docker、upgrade-runner、volumes、image-names、project-files、compose-tag、disk、migration 等检查。
- 前端预检查步骤原来只有 5 个泛化步骤，结果返回后只在最后一步显示失败，无法看出是镜像名、compose、项目文件还是磁盘问题。
- 升级预检查还缺少 compose 网络检查，不能在上传阶段发现 172.16/172.17 或非 `10.249.249.0/24` 的配置。

修复：

- `backend/app/services/upgrade.py` 新增 `network` 检查，校验当前 compose 与升级包 `project/docker-compose.offline.yml`。
- `frontend/src/pages/ServicePage.tsx` 将平台和组件预检查步骤改为按后端检查项分组，并在步骤内展示聚合后的检查消息。
- `backend/tests/test_deployment_config.py` 增加文本断言覆盖网络检查和前端步骤映射。
- `docs/upgrade-issues.md` 将 UPG-011 标记为已解决，UPG-014 补充“已纳入升级预检查”。

### 升级前备份进度

状态：完成

发现：

- 平台升级由 `upgrade-runner` 轮询 pending 任务后执行 `_create_backup()`。
- 旧备份过程只在 `_run_step()` 开始和完成时保存 task，因此 tar/gzip 大目录时页面会长时间停在“生成升级前数据备份”。
- 前端已经能显示 step message 和 logs，缺的是后端备份过程中持续更新 task。

修复：

- `_create_backup()` 先扫描待备份文件总数和总字节数，写入 `backup_total_files`、`backup_total_bytes`。
- 新增 `_BackupProgress` 和进度 reader，备份写入时按字节统计，并按 5 秒或 10% 进度节流更新 `backup_processed_*`、step message 和日志。
- 任务中心 detail 改为使用当前 running step 的 message，能直接显示 `备份中 xx%`。
- `docs/upgrade-issues.md` 将 UPG-008 标记为已解决。

### 平台升级 UI 去重

状态：完成

发现：

- 平台升级顶部已经展示当前版本、目标版本、最近成功包等信息。
- 下方“服务运行核验”又作为独立区块展示刷新按钮和服务运行表，视觉上像二级框，用户需要在多个区域判断升级状态。

修复：

- 新增统一“平台状态”区域，集中展示版本、升级包、compose 和运行服务。
- `renderUpgradeRuntimeVerification()` 只返回运行服务表，刷新按钮移到平台状态标题行。
- `docs/upgrade-issues.md` 将 UPG-010 标记为已解决。

验证：

- 本地 `python3 -m py_compile backend/app/services/upgrade.py backend/tests/test_deployment_config.py` 通过。
- 本地 `python3 scripts/build_upgrade_package.py --check-version` 通过。
- 本地敏感信息 diff 扫描未发现密码、secret、credential。
- 10.20.11.3 已拉取 dev，`python3 -m py_compile`、`scripts/build_upgrade_package.py --check-version`、`docker compose build frontend` 通过。

### runner 生命周期文档版本来源

状态：完成

修复：

- `docs/upgrade-runner-lifecycle.md` 将“升级后核验”文案更新为“平台状态”。
- `docs/upgrade-issues.md` 将 UPG-017 标记为已解决。
- `docs/releases/CHANGELOG.md` 同步服务管理页命名，避免维护人员继续引用旧区域名。

### 当前状态汇总

状态：完成

最近提交：

- `df77a57 docs: update runner version source notes`
- `dcf328d fix: consolidate upgrade status UI`
- `7fd71b6 fix: report upgrade backup progress`
- `3d917c0 fix: make upgrade precheck steps actionable`
- `2cf9103 fix: report cleanup reclaimed space accurately`

已解决：

- Docker 镜像清理和空间清理显示 `0B`。
- 升级预检查步骤化，并覆盖镜像名/tag、compose、项目文件、敏感路径、volume、网络和磁盘空间。
- 升级前备份显示扫描总量、处理字节数、当前文件和小日志。
- 平台升级 UI 合并为“平台状态”，不再重复展示升级后核验。
- runner 生命周期文档已明确平台版本来自镜像内 `/app/VERSION`，runner 版本独立来自 `/data/upgrade-runner.version` 或 `RUNNER_VERSION`。

剩余：

- Prometheus 组件升级策略仍为设计待定。
- [已解决] 数据迁移后的 Prometheus 历史指标、日/月增长和趋势图已在 `10.20.11.3` 完成真实回归验证。
- 数据迁移导入前需要自动生成备份，备份成功后才继续导入。
- 需要根据历史升级问题重新设计全新的平台升级和组件升级模式。

### v0.5.1 到 v0.5.2 升级链路验证

状态：运行态验证通过，任务目录迁移仍需后续优化

验证主机：

- `10.20.11.3`

验证链路：

```text
v0.5.1 + runner v0.3.0
  -> v0.5.1u2-fix10 + runner v0.3.0
  -> v0.5.1u2-fix10 + runner v0.3.1 fsdirfix9
  -> v0.5.2-fix2 + runner v0.3.1
```

最终可用包：

- v0.5.1u2 bridge: `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2-fix10/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz`
  - SHA256: `b976ef8c761271ac06cd8bd3e23d3394a84360ea189e46b1042bc2ced70651df`
- runner v0.3.1: `/home/user1/codex-build/packages-v052-layout-fix/02-runner-v0.3.1-fsdirfix9/smartx-upgrade-runner-v0.3.1.tar.gz`
  - SHA256: `128571d20ea56fbd5d8684832c398458453a660b5e8d752e5dff5d2c200b1c04`
- v0.5.2 platform: `/home/user1/codex-build/packages-v052-layout-fix/03-v0.5.2-fix2/smartx-capacity-insight-upgrade-v0.5.2.tar.gz`
  - SHA256: `a224d0de60c688d5d7033b21d3ea00869b253ff3aef6c6b1ecc9a31498aebfbc`

最终运行态：

- `/api/system/health` 返回 `ok=true`。
- 平台版本：`v0.5.2`。
- runner 版本：`v0.3.1`。
- Prometheus 健康检查通过。
- 新 project 容器已启动：`web-api`、`collector-worker`、`frontend`、`prometheus`、`upgrade-runner`。
- `/data/smartx-storage-forecast/project/prometheus/prometheus.yml` 是文件，不再被 Docker bind 创建成目录。

本轮修复点：

- runner 的 project 拷贝在来源是升级包 `project/` 时不再跳过 `prometheus/`，避免 `prometheus.yml` 缺失。
- runner 在 v0.5.2 directory transition 中保持旧 runner 本地可见路径不变，只通过 Docker helper 写宿主机目标目录。
- runner 通过 helper 容器准备宿主机 Prometheus 数据目录权限，避免 Prometheus 因 `queries.active` 无法写入而反复重启。
- v0.5.2 平台包服务列表加入 `upgrade-runner`，但仍不包含 runner 镜像 archive；目标机使用组件升级阶段已加载的 runner v0.3.1 镜像。

已知残留：

- v0.5.2 切换后，当前正在执行的 v0.5.2 task 文件仍在 legacy `/data/upgrades/<task_id>/task.json`。新 web-api 使用 `/data/smartx-storage-forecast/upgrades`，因此该特定 task 的状态接口可能在切换后返回 404。
- 该问题不影响最终运行态，但会影响任务中心对“本次 v0.5.2 升级任务”的最终展示。后续应补充 task 目录迁移或双写策略。

### 新增报表与 VM 口径需求

状态：待处理

新增需求：

- 月增长最快 VM 必须排除历史数据不足 30 天的 VM；如果刚部署没有任何 VM 满足 30 天样本，月增长最快 VM 显示为空。
- Word/Excel 导出报表的月增长 TOP VM 使用同样过滤口径。
- Word/Excel 导出报表需要在“上期容量”表头或说明中直接标注统计窗口起止日期。
- 报表页在“日增长最快 VM”下新增“本日新建 VM”，在“月增长最快 VM”下新增“本月新建 VM”。
- 本日/本月新建 VM 支持点击跳转到虚拟机页面。
- 验证并必要时修复 VM 改名显示：历史数据以 UUID 绑定，最新一次采集后页面展示名称应与 Tower 最新名称同步。

初步口径建议：

- VM 身份继续使用 `tower_id + cluster_id + vm_id`。
- VM 名称只作为展示字段，不能作为历史数据绑定字段。
- “新建 VM”建议按该 VM 在 Prometheus 历史指标中首次出现时间判断。
- 月增长过滤建议按该 VM 指标最早样本与当前统计结束时间的跨度判断，跨度小于 30 天则排除。
- “上期容量”建议更名或注释为“统计窗口起始容量”，并显示具体日期范围，例如 `统计窗口：2026年05月01日-2026年05月31日`。

### 数据迁移导入前备份

状态：已解决

新增需求：

- [已完成] 数据迁移导入前自动生成当前系统备份，避免导入包异常、导入中断、Prometheus block 合并异常或权限问题导致难以回退。
- [已完成] 备份路径使用 `/data/smartx-storage-forecast/backups/import-before-YYYYMMDDHHMMSS-任务前缀.tar.gz`。
- [已完成] 页面任务中心和导入完成提示显示备份路径。
- [已完成] 备份成功后才开始导入；备份失败默认阻止继续导入。
- [已完成] 导入完成结果中返回 `backup_path`。

### 2026-06-05 数据迁移备份、报表 VM 口径与历史指标回归

状态：已完成

实现：

- 数据迁移导入在写入业务库和 Prometheus 历史指标前生成导入前备份，跳过 `upgrades/backups/exports/compose-runtime` 和 Prometheus `wal/chunks_head/lock/queries.active` 等运行时目录。
- 报表月增长 VM 要求样本跨度满 30 天；不足 30 天不进入月增长榜，Word/Excel 导出复用同一口径。
- 报表接口增加 `day_new_vms`、`month_new_vms`、`period_window` 和 `month_growth_min_sample_days`。
- 报表页增加“本日新建 VM”和“本月新建 VM”，点击仍按 `vm_id` 跳转。
- VM 展示名称优先使用最新采集名称，历史趋势和增长计算继续按 `tower_id + cluster_id + vm_id` 绑定。
- Word/Excel VM 表头从“上期容量”改为“期初容量”，并显示统计窗口起止日期。
- 修复增长量/增长率双 TOP100 合并后可能超过 100 条的问题。

验证：

- 本地 `python3 -m py_compile backend/app/services/dashboard.py backend/app/services/data_migration.py backend/app/services/report_export.py backend/tests/test_dashboard.py backend/tests/test_data_migration.py` 通过。
- `10.20.11.3` 远端 `docker compose build web-api frontend` 通过，frontend `tsc -b && vite build` 通过；仅存在 Vite 大 chunk 提示。
- `10.20.11.3` 重启 `web-api/frontend` 后 `/metrics` 返回 200，`8080` 返回 200。
- `10.20.11.3` Prometheus 当前 `smartx_vm_storage_used_bytes` 查询返回 175 条 series。
- `10.20.11.3` 报表接口返回：`clusters=1`、`day_fastest_growing_vms=100`、`month_fastest_growing_vms=0`、`day_new_vms=0`、`month_new_vms=0`；月榜为空符合“样本满 30 天”新口径。
- `10.20.11.3` Word/Excel 导出均可生成；Word 和 Excel 均确认包含“统计窗口”和“期初容量”。
- `10.20.11.3` 容器内验证导入前备份 helper：备份包含 `smartx.db` 和 Prometheus block，跳过 app 运行时目录和 Prometheus runtime 目录。

### 2026-06-05 UPG-016 数据迁移历史指标回归

状态：已解决

验证链路：

- 迁移导出任务生成 `/data/smartx-storage-forecast/exports/migrations/smartx-storage-migration-20260605113838.tar.gz`。
- 导出包包含 `smartx-data/smartx.db` 和 7 个 Prometheus block 的 `meta.json`。
- 导出包不包含 Prometheus `wal` 运行时目录，也不包含导入任务运行时目录。
- 使用 merge 模式导回当前系统，返回 `ok=True`，生成导入前备份 `/data/smartx-storage-forecast/backups/import-before-20260605114014-0ac6678f.tar.gz`。
- 同包回导未覆盖现有数据：业务库已有记录跳过，Prometheus 已有 7 个 block 跳过。
- 重启 `web-api`、`collector-worker`、`prometheus` 后服务均正常运行。
- Prometheus 即时查询 `smartx_vm_storage_used_bytes` 返回 175 条 series。
- Prometheus `query_range` 最近 7 天返回 175 条 series，前 10 条 series 共 260 个历史点。
- 报表接口返回 `clusters=1`、`day_fastest_growing_vms=100`、集群趋势点数 13；月增长为空符合 30 天样本口径。

### 2026-06-05 Phase 5 版本治理执行

状态：已完成

实现：

- `backend/app/core/config.py` 增加 `read_runner_version()`，runner 组件版本优先读取镜像内 `/app/RUNNER_VERSION`，环境变量 `SMARTX_RUNNER_VERSION` 仅作为兜底覆盖。
- `backend/Dockerfile`、`backend/Dockerfile.worker`、`backend/Dockerfile.upgrade` 均复制根目录 `VERSION` 和 `RUNNER_VERSION`，避免平台版本和 runner 版本依赖 compose 默认值。
- `docs/deployment.md` 修正离线部署说明：平台三件套默认 `v0.5.0`，`upgrade-runner` 默认 `v0.3.0`，不再描述为 `latest`。
- `docs/deployment.md` 补充 `/data/smartx-storage-forecast/upgrades`、`/data/smartx-storage-forecast/backups`、`/data/smartx-storage-forecast/exports`、`/data/smartx-storage-forecast/compose-runtime` 运行产物目录说明，并修正密码修改入口为 admin 头像菜单。
- `docs/version-governance.md` 和 `docs/releases/CHANGELOG.md` 补充镜像内置版本文件规则。
- 增加测试断言，防止后续 Dockerfile 漏复制 `RUNNER_VERSION`、部署文档回退到 `latest/v0.3.1`、runner 版本不读镜像文件。

验证：

- `python3 scripts/build_upgrade_package.py --check-version --no-build` 通过，输出 `Version metadata OK: v0.5.0`。
- `python3 -m py_compile backend/app/core/config.py backend/tests/test_upgrade.py backend/tests/test_deployment_config.py scripts/build_upgrade_package.py scripts/build_runner_component_package.py` 通过。
- 自定义静态断言通过，确认 compose 拆分 `SMARTX_IMAGE_TAG:-v0.5.0` 与 `SMARTX_RUNNER_IMAGE_TAG:-v0.3.0`，Dockerfile 均复制 `VERSION/RUNNER_VERSION`，部署文档不再包含 `latest` 默认 tag 或 `SMARTX_IMAGE_TAG=v0.3.1`。
- `python3 -m pytest backend/tests/test_upgrade.py backend/tests/test_deployment_config.py` 未执行成功，原因是本机 Python 环境缺少 `pytest` 模块。

### 全新平台升级与组件升级模式设计

状态：待处理

新增需求：

- 基于之前遇到的升级失败、runner 自升级、compose tag 不闭环、项目文件未同步、路径只读、任务卡住、备份不透明等问题，重新设计平台升级和组件升级模式。
- 目标不是继续修补现有流程，而是形成新的升级架构、状态机、包格式和回滚策略。
- Prometheus 升级纳入该新模式设计，作为 `observability` 组件处理，不再单独作为零散待办。

设计范围：

- 统一升级包入口：上传后读取 `manifest.json`，自动识别平台三件套、runner、Prometheus 或组合包。
- 平台升级、组件升级、Prometheus/observability 升级的职责边界。
- web-api 与 upgrade-runner 的职责分工，尤其是 runner 自升级的安全路径。
- manifest、镜像名、tag、compose/project 文件同步和版本来源的统一规则。
- Prometheus 升级的强制备份、数据目录权限检查、版本兼容检查、健康检查和历史指标查询回归。
- 升级前备份、项目文件备份、运行配置备份和手动/自动回滚策略。
- 跨容器重启后的任务恢复、日志持久化、步骤状态和 UI 展示。
- 旧版本向新升级模式过渡的兼容或迁移方案。

### 2026-06-05 后续产品化待办归并

状态：已记录

归并结果：

- 升级体系相关建议已合并到 Phase 12：统一升级包入口、manifest 自动识别组件、runner 执行、Prometheus/observability 组件升级、备份验证、回滚和任务恢复。
- 数据迁移相关建议整理为 Phase 13：把导入/导出提升为灾备能力，覆盖 SQLite、Prometheus 历史指标、merge 规则、导入前备份和导入后健康验证。
- 报表相关建议整理为 Phase 14：客户交付型 Word/Excel 报表、风险摘要、统一图表风格、高风险 VM 前置、导出留存和任务中心下载。
- 首页风险相关建议整理为 Phase 15：容量风险驾驶舱，任一集群超过 80% 即提示风险，展示最危险集群、预计耗尽时间、7 天增长和主要增长 VM。
- 项目架构整理作为 Phase 16，优先级最低；当前不拆微服务容器，保持 5 容器，未来仅在必要时评估 `task-worker`。
- 版本治理不新建重复阶段，作为 Phase 5 的长期规则继续执行。

### 2026-06-05 SQLite latest_vm_volumes 存储体积分析

状态：已记录

发现：

- `10.20.11.3` 的 `smartx.db` 文件约 135M，其中 `latest_vm_volumes` 占约 94M。
- `latest_vm_volumes` 当前 523 行，但 `payload_json` 合计约 93M，最大单行约 268KB。
- 最大样本中单台 VM 的 `payload_json` 是 258 个虚拟卷对象列表，每个对象保存了较完整的 Tower 原始卷字段。
- 已将“优化 `latest_vm_volumes` 存储结构”和“兼容旧版本迁移包导入”加入 Phase 13。

要求：

- 新结构只保留页面、报表、导出和分析需要的字段。
- 旧版本迁移包导入时，从旧 `payload_json` 抽取所需字段写入新结构，其他原始字段丢弃。
- 需要配套旧数据迁移脚本，并验证 VM 页面、报表导出、迁移导入导出和历史指标分析。

### 2026-06-05 feature/upgrade-v2 受控重建任务文档

状态：已记录

新增文档：

- `docs/v2-rebuild-task-plan.md`

关键决策：

- `feature/upgrade-v2` 采用全新重写，但保留 v1 信息架构和核心功能口径。
- v2 必须支持 v1 现场数据迁入。
- v2 不兼容旧升级路径，升级中心、组件升级和 Prometheus 升级重新设计。
- 默认保持 5 个容器：`frontend`、`web-api`、`collector-worker`、`prometheus`、`upgrade-runner`。

同步更新：

- `task_plan.md` 新增 Phase 17，记录 v2 受控重建目标、产出文档和执行原则。

边界说明：

- 本次只写入任务文档和计划进度，不修改业务代码。

### 2026-06-06 v2 细化设计文档清单

状态：已记录

更新内容：

- 在 `docs/v2-rebuild-task-plan.md` 增加 `## 11. v2 细化设计文档清单`。
- 在 `task_plan.md` 的 Phase 17 补充 Phase V2-0 细化文档交付物。

Phase V2-0 计划产出：

- `docs/architecture-v2.md`
- `docs/v1-data-compatibility.md`
- `docs/v2-upgrade-center-design.md`
- `docs/v2-api-contracts.md`
- `docs/v2-frontend-design.md`
- `docs/v2-implementation-sequence.md`

边界说明：

- 本次只记录细化文档计划，还没有创建上述设计文档。
- 未修改业务代码。

### 2026-06-06 Phase V2-0 细化设计文档创建

状态：已完成第一批

新增文档：

- `docs/architecture-v2.md`
- `docs/v1-data-compatibility.md`
- `docs/v2-upgrade-center-design.md`
- `docs/v2-api-contracts.md`
- `docs/v2-frontend-design.md`
- `docs/v2-implementation-sequence.md`

同步更新：

- `docs/v2-rebuild-task-plan.md` 中 Phase V2-0 状态改为进行中，并勾选上述 6 个文档。
- `task_plan.md` 的 Phase 17 标记上述 6 个文档已创建。

边界说明：

- 本次只创建和更新文档。
- 未修改业务代码。
- Phase V2-0 仍需后续更新 `docs/functional-modules.md` 和 `docs/upgrade-issues.md`，把 v2 模块边界和旧升级问题规避策略映射进去。

### 2026-06-06 v2 远端测试约定

状态：已记录

约定：

- v2 后续构建、部署和现场验证可以使用 `10.20.11.3`。
- 远端执行 v2 验证前，必须确认仓库分支为 `feature/upgrade-v2`。

同步更新：

- `docs/v2-rebuild-task-plan.md`
- `docs/v2-implementation-sequence.md`
- `task_plan.md`

### 2026-06-06 Phase V2-0 文档收口与前端风格约束

状态：已完成

用户要求：

- 严格按照开发文档实施。
- 前端风格和 v1 保持一致。

更新内容：

- `docs/v2-frontend-design.md` 增加 v1 风格继承硬约束。
- `docs/functional-modules.md` 增加 v2 模块边界映射。
- `docs/upgrade-issues.md` 增加 v2 升级中心规避历史问题策略。
- `docs/v2-rebuild-task-plan.md` 标记 Phase V2-0 文档项完成，并记录前端风格边界。
- `task_plan.md` 同步前端风格要求和文档收口状态。

边界说明：

- 本次仍只更新文档。
- 后续代码实施必须按 v2 文档执行。
- 前端允许重构组件，但不能改变 v1 的整体视觉语言、导航结构、主要操作位置和业务术语。

验证记录：

- 文档敏感词检查未发现真实密码或 token。
- 固定字符串检查确认 `docs/functional-modules.md` 和 `docs/upgrade-issues.md` 的 Phase V2-0 待办没有遗留未勾选项。
- 固定字符串检查确认“前端风格必须和 v1 保持一致”已写入 `docs/v2-rebuild-task-plan.md`、`docs/functional-modules.md` 和 `task_plan.md`。

错误记录：

- 曾使用包含反引号的 `rg` 命令检查 markdown checkbox，zsh 将反引号解释为命令替换导致报错；已改用 `rg -F` 固定字符串重新检查。

### 2026-06-06 Phase V2-1 项目骨架启动

状态：进行中

实施内容：

- 新增 `backend/app/v2/` 命名空间。
- 新增 v2 后端模块占位：`auth`、`inventory`、`collection`、`metrics`、`forecast`、`reports`、`migration`、`upgrade`、`tasks`、`system`。
- 新增 `backend/app/v2/registry.py`，声明 v2 后端模块清单。
- 新增前端 v2 目录骨架：`frontend/src/v2/components`、`frontend/src/v2/pages`、`frontend/src/v2/services`、`frontend/src/v2/types`。
- 新增 `backend/tests/test_v2_skeleton.py`，用 Python 标准库 `unittest` 验证 v2 后端模块可导入和前端 v2 目录存在。

TDD 验证：

- RED：`PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_skeleton -v` 先失败，原因是 `app.v2` 和 `frontend/src/v2/*` 不存在。
- GREEN：新增最小骨架后，同一命令通过，2 个测试全部 OK。

本地验证：

- `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_skeleton -v` 通过。
- `python3 -m py_compile` 检查新增 v2 模块和测试文件通过。

限制：

- 本机缺少 `pytest`，暂不能跑 pytest 全量测试。
- 本机缺少 `npm`，暂不能跑前端构建。
- 完整 pytest、frontend build 和远端容器验证需要后续在 `10.20.11.3` 的 `feature/upgrade-v2` 分支执行。

### 2026-06-06 Phase V2-1 统一任务模型

状态：已完成本地最小验证

实施内容：

- 新增 `backend/app/v2/tasks/models.py`。
- 定义 `TaskStatus`：`pending`、`running`、`success`、`failed`、`cancelled`。
- 定义 `TaskType`：`report`、`migration_export`、`migration_import`、`upgrade`、`cleanup`、`collection`。
- 定义 `TaskSnapshot`，用于统一任务列表和任务详情的基础状态。
- 定义 `ErrorSnapshot`，用于返回安全的公开错误码和错误消息。

TDD 验证：

- RED：`PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_task_models -v` 先失败，原因是 `app.v2.tasks.models` 不存在。
- GREEN：新增最小模型后，同一命令通过，3 个测试全部 OK。

本地验证：

- `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_task_models -v` 通过。
- `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_skeleton -v` 通过。
- `python3 -m py_compile backend/app/v2/tasks/models.py backend/tests/test_v2_task_models.py` 通过。

### 2026-06-06 Phase V2-1 远端构建验证收口

状态：完成

远端验证位置：

- 主机：`10.20.11.3`
- v2 独立 worktree：`/data/smartx-storage-forecast/project`
- 分支来源：`origin/feature/upgrade-v2`
- 提交：`2894378`

注意：

- 原 `/data/smartx-storage-forecast/project` 仍在 `dev` 且存在未提交变更，没有直接切换。
- v2 验证使用独立 worktree，避免影响现有 dev 环境。
- 远端构建前临时从 `.env.example` 复制 `.env`，仅用于 Docker compose build，不纳入提交。

远端验证：

- `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models -v` 通过，5 个测试 OK。
- `python3 -m py_compile backend/app/v2/__init__.py backend/app/v2/registry.py backend/app/v2/tasks/models.py backend/tests/test_v2_skeleton.py backend/tests/test_v2_task_models.py` 通过。
- `docker compose build web-api frontend` 通过。
- Docker 内 frontend 执行 `npm run build` 通过，仅保留 Vite 大 chunk 提示。

结论：

- Phase V2-1 项目骨架满足“后端语法检查通过、前端构建通过、空壳应用可构建”的阶段验收。
- `docs/v2-rebuild-task-plan.md` 已将 Phase V2-1 标记为完成。

### 2026-06-06 Phase V2-2 基础平台与认证

状态：进行中，本地核心验证完成

实施内容：

- 新增 `backend/app/v2/config.py`，定义 v2 版本读取、运行目录和环境配置。
- 新增 `backend/app/v2/security.py`，使用标准库实现密码哈希、密码校验、token 签发和 token 校验。
- 新增 `backend/app/v2/database.py`，实现 v2 SQLite 初始化、默认管理员创建和基础任务表。
- 新增 `backend/app/v2/auth/service.py`，实现登录、当前用户和修改密码核心服务。
- 新增 `backend/app/v2/system/health.py`，实现数据库和运行目录健康检查。
- 新增 `backend/app/v2/api.py` 和 `backend/app/v2/main.py`，提供独立 v2 FastAPI 应用壳：`/api/auth/login`、`/api/me`、`/api/me/password`、`/api/system/health`。
- 新增 `frontend/src/v2/services/auth.ts`，定义 v2 登录、当前用户、改密 API 客户端。
- 新增 `frontend/src/v2/components/AccountMenu.tsx`，保留 v1 风格的 admin 头像菜单：设置密码、登出。
- 新增 `frontend/src/v2/types/tasks.ts`，同步 v2 后台任务基础类型。

TDD 记录：

- RED：`PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_foundation -v` 先失败，原因是 `app.v2.config`、`app.v2.auth.service` 等模块不存在。
- GREEN：新增 v2 配置、数据库、认证、安全和健康检查模块后，`backend.tests.test_v2_foundation` 通过。
- RED：新增 `test_settings_from_environment_reads_current_environment` 后先失败，原因是 `V2Settings` 默认值在模块导入时读取环境变量。
- GREEN：将环境变量默认值改为 `default_factory` 后，该测试通过。
- 新增 `backend/tests/test_v2_auth_api.py`；本机缺少 FastAPI 依赖时跳过，远端/Docker 环境用于实际验证 API 链路。

本地验证：

- `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_auth_api -v` 通过：10 个测试 OK，1 个 FastAPI 集成测试因本机缺依赖跳过。
- `python3 -m py_compile backend/app/v2/api.py backend/app/v2/main.py backend/app/v2/config.py backend/app/v2/security.py backend/app/v2/database.py backend/app/v2/auth/service.py backend/app/v2/system/health.py backend/tests/test_v2_foundation.py backend/tests/test_v2_auth_api.py` 通过。

待验证：

- 在 `10.20.11.3` 的 `/data/smartx-storage-forecast/project` 拉取 `feature/upgrade-v2` 后运行 v2 unittest，确认 FastAPI 集成测试实际通过。
- 在远端执行 `docker compose build web-api frontend`，确认后端和前端构建均通过。
- 如后续决定将 Docker 入口切到 `app.v2.main:app`，需要另起阶段处理，因为 Phase V2-2 当前只提供独立 v2 应用壳，不覆盖 v1 主入口。

远端验证中发现：

- `docker compose build web-api frontend` 已通过，frontend `tsc -b && vite build` 通过，仅保留原有 Vite 大 chunk 提示。
- 第一次在 Docker 中运行 v2 unittest 时只挂载了 `backend`，导致 `test_frontend_v2_skeleton_directories_exist` 看不到 `frontend/src/v2/*`，这是测试运行方式问题，后续改为挂载仓库根目录。
- Docker 镜像内存在 `/app/VERSION`，因此 `settings_from_environment()` 返回镜像自带版本是正确行为；测试已改为单独验证 `read_version()` 在版本文件缺失时才使用 `SMARTX_APP_VERSION` 兜底。
- 修正测试后已推送到 `origin/feature/upgrade-v2`，最新提交 `837d49a`。
- 继续在 `10.20.11.3` 拉取最新并补跑 Docker 内 API 集成测试时，SSH 连接超时断开；随后本机到 `10.20.11.3` 的 ping 和 22/tcp 均显示 network unreachable。该远端验证项暂未完成，待网络恢复后继续。
- 本机创建临时 venv `/tmp/smartx-v2-venv` 安装后端依赖后，FastAPI API 集成测试真实执行通过：未登录 `/api/me` 返回 401、默认 admin 登录成功、`/api/me` 返回当前用户、密码不一致返回 400、改密成功、旧密码失效、新密码可登录。
- API 集成测试曾在 Python 3.9 venv 下暴露 `HTTPAuthorizationCredentials | None` 注解兼容问题，已改为 `Optional[HTTPAuthorizationCredentials]`，兼容 Python 3.9/3.12。

### 2026-06-06 Phase V2-2 远端验证收口

状态：完成

远端验证位置：

- 主机：`10.20.11.3`
- v2 worktree：`/data/smartx-storage-forecast/project`
- 分支：`feature/upgrade-v2`
- 提交：`bb2f156`

验证记录：

- `git pull --ff-only origin feature/upgrade-v2` 成功拉到 `bb2f156`。
- `docker compose build web-api frontend` 通过。
- `docker run --rm -v /data/smartx-storage-forecast/project:/src -e PYTHONPATH=/src/backend -w /src smartx-storage-forecast-web-api:local python -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_auth_api -v` 通过：12 个测试 OK。
- FastAPI 集成测试在 Python 3.12 容器内真实执行，覆盖未登录 401、登录、`/api/me`、密码不一致、改密、旧密码失效、新密码登录。

结论：

- Phase V2-2 基础平台与认证满足阶段验收。
- `docs/v2-rebuild-task-plan.md` 已将 Phase V2-2 标记为完成。

### 2026-06-06 Phase V2-3 Tower/Cluster 与指标格式基础

状态：进行中，第一薄片完成本地验证

实施内容：

- `backend/app/v2/database.py` 增加 v2 `towers`、`clusters`、`vm_latest` 表。
- 新增 `backend/app/v2/inventory/models.py`，定义 Tower/Cluster 输入和安全响应记录。
- 新增 `backend/app/v2/inventory/service.py`，实现 Tower 创建、列表、更新、删除、集群同步、集群启用/改名。
- 新增 `backend/app/v2/inventory/scope.py`，统一 all/Tower/cluster scope 解析，并禁止只传 cluster_id 不传 tower_id。
- 新增 `backend/app/v2/metrics/formatter.py`，生成 `smartx_cluster_storage_used_bytes`、`smartx_cluster_storage_total_bytes`、`smartx_vm_storage_used_bytes` 指标文本，VM 指标使用 `tower_id + cluster_id + vm_id` 稳定身份，`vm_name` 仅展示。
- `backend/app/v2/api.py` 增加 v2 Tower CRUD、集群同步和集群更新接口，所有接口复用 `require_user` 鉴权，不返回 password/api_token。

TDD 记录：

- RED：`PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_inventory_metrics -v` 先失败，原因是 `inventory.models`、`inventory.scope`、`metrics.formatter` 不存在。
- GREEN：新增 inventory service/scope 和 metrics formatter 后，该测试通过。
- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_inventory_api -v` 先返回 `/api/towers` 404，说明 v2 API 未接 Tower。
- GREEN：新增 v2 Tower/Cluster API 后，inventory API 测试通过。
- 修复：Python 3.9 + Pydantic 对 `bool | None` 注解不兼容，API 层 Pydantic 模型改为 `Optional[...]`。

本地验证：

- `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v` 通过：14 个测试 OK，2 个 FastAPI 集成测试因本机基础 Python 缺依赖跳过。
- `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v` 通过：16 个测试 OK。
- `python3 -m py_compile backend/app/v2/api.py backend/app/v2/database.py backend/app/v2/security.py backend/app/v2/inventory/models.py backend/app/v2/inventory/service.py backend/app/v2/inventory/scope.py backend/app/v2/metrics/formatter.py backend/tests/test_v2_inventory_metrics.py backend/tests/test_v2_inventory_api.py` 通过。

待处理：

- Phase V2-3 后续还需要 CloudTower 客户端、连接测试、手动采集、collector-worker 定时采集、Prometheus 写入和查询服务。
- 当前只完成 Tower/Cluster 存储与 API、指标文本格式基础，尚未打通真实采集链路。

### 2026-06-06 Phase V2-3 手动采集基础链路

状态：进行中，fake client 驱动的采集基础完成本地验证

实施内容：

- `backend/app/v2/database.py` 增加 `collection_runs` 表。
- 新增 `backend/app/v2/collection/service.py`。
- `CollectionService.run_manual_collection()` 读取已启用 Tower 和已启用集群，调用注入的 CloudTower collector，更新 `vm_latest`，生成 Prometheus 指标文本，并记录 collection run 状态。
- 采集失败时根据 Tower 凭据做错误摘要脱敏，避免 password/api_token 出现在返回 message 中。

TDD 记录：

- RED：`PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_collection -v` 先失败，原因是 `app.v2.collection.service` 不存在。
- GREEN：新增 `CollectionService` 后测试通过。

本地验证：

- `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_collection backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v` 通过：16 个测试 OK，2 个 FastAPI 集成测试因本机基础 Python 缺依赖跳过。
- `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_collection backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v` 通过：18 个测试 OK。
- `python3 -m py_compile backend/app/v2/collection/service.py backend/app/v2/database.py backend/tests/test_v2_collection.py` 通过。

限制：

- 当前采集测试使用 fake CloudTower collector，尚未实现真实 CloudTower HTTP 客户端。
- 当前仅生成 Prometheus exposition 文本，尚未接入 Prometheus 写入/查询服务。

### 2026-06-06 Phase V2-3 远端 Docker 验证

状态：完成

远端验证位置：

- 主机：`10.20.11.3`
- v2 worktree：`/data/smartx-storage-forecast/project`
- 分支：`feature/upgrade-v2`
- 提交：`d38ae2b`

验证记录：

- `git pull --ff-only origin feature/upgrade-v2` 成功拉到 `d38ae2b`。
- `docker compose build web-api frontend` 通过。
- `docker run --rm -v /data/smartx-storage-forecast/project:/src -e PYTHONPATH=/src/backend -w /src smartx-storage-forecast-web-api:local python -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_collection backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v` 通过：18 个测试 OK。

结论：

- V2-3 已完成 Tower/Cluster 存储与 API、指标文本格式、fake client 手动采集基础链路的远端容器验证。
- 后续继续实现真实 CloudTower HTTP 客户端、连接测试接口、Prometheus 查询/健康服务和 collector-worker 定时采集。

### 2026-06-06 Phase V2-3 CloudTower 客户端与 Prometheus 查询基础

状态：进行中，真实客户端与查询基础完成本地验证

实施内容：

- 新增 `backend/app/v2/cloudtower/client.py` 和 `backend/app/v2/cloudtower/service.py`。
- v2 CloudTower 客户端支持用户名密码登录、API token、分页请求、集群列表归一化、集群容量和 VM 容量归一化。
- `POST /api/towers/{tower_id}/test` 接入 v2 API，连接成功后同步集群，连接失败返回脱敏后的错误摘要。
- `POST /api/collection/run` 接入 v2 API，复用 `CollectionService` 和真实 CloudTower service 执行手动采集。
- 新增 `backend/app/v2/metrics/prometheus.py`，提供 Prometheus `/-/ready` 健康检查、instant query 和 query_range 解析。
- v2 系统健康检查增加 Prometheus 检查项。

TDD 记录：

- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_cloudtower_client backend.tests.test_v2_inventory_api -v` 先失败，原因是 `app.v2.cloudtower` 和 `get_cloudtower_service` 不存在。
- GREEN：新增 CloudTower client/service 和 API 连接测试入口后，目标测试通过。
- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_prometheus_service -v` 先失败，原因是 `app.v2.metrics.prometheus` 不存在。
- GREEN：新增 PrometheusService 后，Prometheus 目标测试通过。
- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_foundation -v` 先失败，原因是健康检查不支持 Prometheus 注入。
- GREEN：健康检查接入 Prometheus 后，基础测试通过。

本地验证：

- `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_cloudtower_client backend.tests.test_v2_prometheus_service backend.tests.test_v2_collection backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v` 通过：25 个测试 OK。
- `python3 -m py_compile backend/app/v2/api.py backend/app/v2/cloudtower/client.py backend/app/v2/cloudtower/service.py backend/app/v2/collection/service.py backend/app/v2/inventory/service.py backend/app/v2/metrics/prometheus.py backend/app/v2/system/health.py backend/tests/test_v2_cloudtower_client.py backend/tests/test_v2_prometheus_service.py backend/tests/test_v2_inventory_api.py backend/tests/test_v2_foundation.py` 通过。

限制：

- 当前 Prometheus 已有查询/健康服务，但采集数据仍只返回 exposition 文本，尚未完成 collector-worker 暴露 `/metrics` 或写入式闭环。
- collector-worker 定时采集仍未实现。

### 2026-06-06 Phase V2-3 collector-worker 与 Prometheus scrape 基础

状态：完成本地验证，待远端 Docker 验证

实施内容：

- v2 schema 增加 `metric_snapshots`，采集成功后保存最近一次 Prometheus exposition 文本。
- `CollectionService.latest_metrics_text()` 可读取最近指标文本，供 worker 暴露 `/metrics`。
- 新增 `backend/app/v2/worker.py`：
  - 提供 `/metrics` HTTP handler。
  - 使用 `BackgroundScheduler` 按 `SMARTX_COLLECTION_HOUR` 和 `SMARTX_COLLECTION_MINUTE` 定时执行采集。
  - 定时采集复用 v2 `CloudTowerService` 和 `CollectionService`。
- v2 运行入口切换：
  - `backend/Dockerfile` 从 `app.main:app` 切到 `app.v2.main:app`。
  - `backend/Dockerfile.worker` 从 `app.collector.worker` 切到 `app.v2.worker`。
  - `docker-compose.yml`、`docker-compose.offline.yml`、`docker-compose.release.yml` 的 collector-worker 命令切到 `app.v2.worker`。
- `docs/v2-rebuild-task-plan.md` 将 V2-3 的 collector-worker、Prometheus 查询/健康、Prometheus scrape 基础标记为完成。

TDD 记录：

- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_collection -v` 先失败，原因是 `CollectionService.latest_metrics_text()` 不存在。
- GREEN：新增 `metric_snapshots` 和读取/保存逻辑后测试通过。
- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_worker -v` 先失败，原因是 `app.v2.worker` 不存在。
- GREEN：新增 v2 worker 后测试通过。
- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_skeleton -v` 先失败，原因是 Dockerfile/compose 仍指向 v1 入口。
- GREEN：切换 v2 运行入口后 skeleton 测试通过。

本地验证：

- `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_cloudtower_client backend.tests.test_v2_prometheus_service backend.tests.test_v2_collection backend.tests.test_v2_worker backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v` 通过：28 个测试 OK。
- `python3 -m py_compile backend/app/v2/api.py backend/app/v2/cloudtower/client.py backend/app/v2/cloudtower/service.py backend/app/v2/collection/service.py backend/app/v2/database.py backend/app/v2/inventory/service.py backend/app/v2/metrics/prometheus.py backend/app/v2/system/health.py backend/app/v2/worker.py backend/tests/test_v2_skeleton.py backend/tests/test_v2_cloudtower_client.py backend/tests/test_v2_prometheus_service.py backend/tests/test_v2_collection.py backend/tests/test_v2_worker.py backend/tests/test_v2_inventory_api.py backend/tests/test_v2_foundation.py` 通过。

限制：

- 本机没有 Docker CLI，`docker compose build web-api collector-worker frontend` 无法本地执行，错误为 `zsh:1: command not found: docker`。
- 需要在 `10.20.11.3` 上拉取 `feature/upgrade-v2` 后执行 Docker 构建和容器内测试。
- Phase V2-3 的采集和指标基础链路已具备，但 Dashboard/VM/报表展示仍属于后续 V2-4/V2-5。

### 2026-06-06 Phase V2-3 远端 Docker 验证补充

状态：完成

远端验证位置：

- 主机：`10.20.11.3`
- v2 worktree：`/data/smartx-storage-forecast/project`
- 分支：`feature/upgrade-v2`
- 提交：`38a5af1`

验证记录：

- `git pull --ff-only origin feature/upgrade-v2` 成功拉到 `38a5af1`。
- `docker compose build web-api collector-worker frontend` 通过，确认 v2 `web-api`、v2 `collector-worker` 和前端镜像可构建。
- `docker run --rm -v /data/smartx-storage-forecast/project:/src -e PYTHONPATH=/src/backend -w /src smartx-storage-forecast-web-api:local python -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_cloudtower_client backend.tests.test_v2_prometheus_service backend.tests.test_v2_collection backend.tests.test_v2_worker backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v` 通过：28 个测试 OK。

结论：

- Phase V2-3 的 Tower、真实 CloudTower 客户端、连接测试、手动采集、collector-worker 定时采集基础、Prometheus `/metrics` scrape 基础、Prometheus 查询和健康检查基础已完成本地与远端容器验证。
- 后续进入 Phase V2-4：Dashboard 和 VM 页面，重点把 Prometheus 历史查询结果接入容量风险、日增长、本日新建 VM、VM 列表和趋势。

### 2026-06-06 Phase V2-4 Dashboard/VM 后端第一薄片

状态：完成本地验证，待远端 Docker 验证

实施内容：

- 新增 `backend/app/v2/dashboard/service.py`：
  - 汇总 Tower/集群/VM 数量。
  - 从 Prometheus 集群 used/total 指标计算容量使用率。
  - 任一集群使用率 `>= 80%` 返回 high 风险；`>= 75%` 返回 warning；否则返回 `当前所有集群暂无明显容量风险`。
  - 日增长最快 VM 根据 24 小时 Prometheus range 数据计算增长量和增长率。
  - 本日新建 VM 按 24 小时 range 是否缺少历史样本判断。
  - VM 展示名称优先使用 SQLite `vm_latest` 最新采集名称。
- 新增 `backend/app/v2/vms/service.py`：
  - VM 列表按 scope 查询 Prometheus 即时值。
  - VM 趋势强制使用 `tower_id + cluster_id + vm_id` 查询，避免跨 Tower/集群混合。
  - VM 改名后趋势展示仍使用 SQLite 最新名称。
- 新增 `backend/app/v2/metrics/series.py`，统一解析 Prometheus instant/range 数据和构造带 label 的查询。
- v2 API 增加：
  - `GET /api/dashboard/summary`
  - `GET /api/vms`
  - `GET /api/vms/{vm_id}/trend`
- `backend/app/v2/registry.py` 增加 `dashboard` 和 `vms` 模块。
- `docs/v2-rebuild-task-plan.md` 将 Phase V2-4 标记为进行中，并标出后端基础已完成。

TDD 记录：

- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_dashboard_vm -v` 先失败，原因是 `app.v2.dashboard` 和 `app.v2.vms` 不存在。
- GREEN：新增 Dashboard/VM service 后，Dashboard/VM 服务测试通过。
- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_dashboard_vm_api -v` 先失败，原因是 API 未提供 `get_dashboard_service` 和 `get_vm_service`。
- GREEN：接入 v2 API 后，Dashboard/VM API 测试通过。

本地验证：

- `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_cloudtower_client backend.tests.test_v2_prometheus_service backend.tests.test_v2_collection backend.tests.test_v2_worker backend.tests.test_v2_dashboard_vm backend.tests.test_v2_dashboard_vm_api backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v` 通过：31 个测试 OK。
- `python3 -m py_compile backend/app/v2/api.py backend/app/v2/dashboard/service.py backend/app/v2/vms/service.py backend/app/v2/metrics/series.py backend/app/v2/registry.py backend/tests/test_v2_dashboard_vm.py backend/tests/test_v2_dashboard_vm_api.py backend/tests/test_v2_skeleton.py` 通过。

限制：

- 本次只完成 Dashboard/VM 后端第一薄片。
- VM 详情和卷信息仍待实现。
- 前端 Dashboard/VM 页面仍待接入 v2 API。

### 2026-06-06 Phase V2-4 VM 详情和卷信息后端

状态：完成本地验证，待远端 Docker 验证

实施内容：

- v2 schema 增加 `vm_volumes` 结构化卷表。
- CloudTower client 在采集 VM 时同步获取 VM volumes，并归一化为：
  - `volume_id`
  - `name`
  - `path`
  - `size_bytes`
  - `used_bytes`
  - `storage_policy`
  - `replica_num`
  - `thin_provision`
  - `ec_k`
  - `ec_m`
- `CollectionService` 采集成功后按 `tower_id + cluster_id + vm_id` 替换该 VM 最新卷信息，避免旧卷残留。
- `VmService` 增加：
  - `detail(vm_id, tower_id, cluster_id)`
  - `volumes(vm_id, tower_id, cluster_id)`
- v2 API 增加：
  - `GET /api/vms/{vm_id}`
  - `GET /api/vms/{vm_id}/volumes`
- 详情和卷接口均强制要求 `tower_id` 和 `cluster_id`，避免跨 Tower/集群混合。
- `docs/v2-rebuild-task-plan.md` 将 VM 详情和卷信息后端基础标记为完成。

TDD 记录：

- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_collection backend.tests.test_v2_dashboard_vm -v` 先失败，原因是 `vm_volumes` 表不存在。
- GREEN：新增 `vm_volumes` schema、采集保存逻辑、VM detail/volumes service 后，目标测试通过。
- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_cloudtower_client -v` 先失败，原因是 CloudTower client 未返回 `volumes`。
- GREEN：新增 CloudTower 卷归一化和每 VM 获取卷后，目标测试通过。
- RED：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_dashboard_vm_api -v` 先失败，原因是 VM detail API 404。
- GREEN：新增 VM detail 和 volumes API 后，API 测试通过。

本地验证：

- `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_cloudtower_client backend.tests.test_v2_prometheus_service backend.tests.test_v2_collection backend.tests.test_v2_worker backend.tests.test_v2_dashboard_vm backend.tests.test_v2_dashboard_vm_api backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v` 通过：32 个测试 OK。
- `python3 -m py_compile backend/app/v2/api.py backend/app/v2/cloudtower/client.py backend/app/v2/collection/service.py backend/app/v2/database.py backend/app/v2/vms/service.py backend/tests/test_v2_cloudtower_client.py backend/tests/test_v2_collection.py backend/tests/test_v2_dashboard_vm.py backend/tests/test_v2_dashboard_vm_api.py` 通过。

限制：

- 本次只完成 VM 详情和卷信息后端。
- Dashboard/VM 前端页面仍待接入 v2 API。

远端验证：

- 2026-06-06 09:19 CST，在 `10.20.11.3:/data/smartx-storage-forecast/project` 使用 `smartx-storage-forecast-web-api:local` 容器执行完整 v2 后端测试集。
- 命令：`docker run --rm -v /data/smartx-storage-forecast/project:/src -e PYTHONPATH=/src/backend -w /src smartx-storage-forecast-web-api:local python -m unittest backend.tests.test_v2_skeleton backend.tests.test_v2_task_models backend.tests.test_v2_foundation backend.tests.test_v2_inventory_metrics backend.tests.test_v2_cloudtower_client backend.tests.test_v2_prometheus_service backend.tests.test_v2_collection backend.tests.test_v2_worker backend.tests.test_v2_dashboard_vm backend.tests.test_v2_dashboard_vm_api backend.tests.test_v2_auth_api backend.tests.test_v2_inventory_api -v`
- 结果：32 个测试通过，`OK`。

### 2026-06-06 Phase V2-4 Dashboard/VM 前端接入

状态：完成临时远端容器验证，待正式远端仓库构建验证

实施内容：

- 前端 API 层兼容 v2 Dashboard 响应：
  - `totals` 归一到旧页面使用的 `kpis`。
  - `storage` 归一到容量使用数据。
  - `day_fastest_growing_vms` 和 `day_new_vms` 归一为页面 `MetricItem`。
  - `capacity_risk.level=high` 归一为页面 danger tone。
- Dashboard 页面改为优先展示 v2 `day_fastest_growing_vms`。
- Dashboard 在“日增长最快 VM”下面新增独立“本日新建 VM”卡片，VM 项点击仍跳转到虚拟机页面。
- VM 页面移除旧的全量 `/api/vm-volumes` 依赖，改为选中 VM 后调用：
  - `GET /api/vms/{vm_id}`
  - `GET /api/vms/{vm_id}/volumes`
  - `GET /api/vms/{vm_id}/trend`
- VM 趋势点兼容 v2 `{timestamp, used_bytes}` 格式并转换为图表需要的 `[timestamp, value]`。
- 前端测试增加自动 cleanup，避免多个 render 残留造成误报。
- `docs/v2-rebuild-task-plan.md` 将 Dashboard/VM 前端接入标记完成。

TDD 记录：

- RED：新增 `frontend/src/pages/VmsPage.test.tsx` 后，在远端临时目录运行前端测试失败，原因是 `VmsPage` 仍调用 `api.vmVolumesAll(scope).then(...)`，测试明确要求单 VM 卷接口。
- RED：新增 Dashboard v2 日增长/新建 VM 测试后，页面没有显示 v2 `day_fastest_growing_vms` 数据，也没有“本日新建 VM”独立卡片。
- GREEN：改 API 归一化和 Dashboard/VM 页面后，目标前端测试通过。

验证：

- 远端临时目录 `/tmp/smartx-v2-redcheck`：
  - `npm test -- --run src/pages/DashboardPage.test.tsx src/pages/VmsPage.test.tsx` 通过：2 个测试文件，4 个测试。
  - `npm run build` 通过，Vite 成功生成 `dist`。
- 干净 staged 树 `/tmp/smartx-v2-staged`：
  - 前端目标测试通过：2 个测试文件，4 个测试。
  - `npm run build` 通过。
  - 后端完整 v2 测试集通过：32 个测试 OK。
- 正式远端仓库 `10.20.11.3:/data/smartx-storage-forecast/project` 已拉取到 `b64ec7a`。
- 正式远端仓库执行 `docker compose build web-api frontend` 通过。

限制：

- 本阶段只完成 Dashboard/VM 前端接入。
- 报表页跳转到 VM、月增长、本月新建 VM 属于后续 V2-5 报表阶段。

### 2026-06-06 Phase V2-5 报表 latest_report 第一切片

状态：完成本地和远端验证，待提交

实施内容：

- 新增 `backend/app/v2/reports/service.py`。
- `ReportService.latest_report()` 支持：
  - 集群 90 天预测。
  - 最近 7 天平均容量增长速率。
  - 7/14/30/90/180/365 天统计窗口归一。
  - 7/30/90/365/720 天趋势窗口归一。
  - 日增长 VM、月增长 VM。
  - 月增长 VM 样本跨度不足 30 天时过滤。
  - 本日新建 VM、本月新建 VM。
  - VM 展示名称优先使用 `vm_latest` 最新名称。
- v2 API 新增 `GET /api/reports/latest`，支持全部、Tower、集群 scope。
- 报表页已有结构接入 v2 合同：
  - 显示 90 天预测文案和值。
  - 显示 7 天平均增长速率。
  - 显示日/月增长 VM 和本日/本月新建 VM。
  - VM 项点击可跳转虚拟机页面。
- 新增测试：
  - `backend/tests/test_v2_reports.py`
  - `backend/tests/test_v2_reports_api.py`
  - `frontend/src/pages/ReportsPage.test.tsx`
- `docs/v2-rebuild-task-plan.md` 将 Phase V2-5 第一切片标记为进行中/部分完成。

TDD 记录：

- RED：报表后端测试先失败，原因是 `app.v2.reports.service` 不存在。
- GREEN：新增 `ReportService` 后，报表服务测试通过。
- RED：报表 API 测试先失败，原因是 `get_report_service` 和 `/api/reports/latest` 不存在。
- GREEN：接入 API 后，鉴权、scope、period/chart 参数测试通过。
- 前端新增报表页面测试，验证 v2 合同内容和 VM 跳转。

兼容性修复：

- 当前本地测试环境为 Python 3.9，`dataclass(slots=True)` 和 `zip(..., strict=True)` 不兼容，已改为 Python 3.9 兼容写法。
- “本日新建 VM”测试假数据改为自然日内首次出现，保持业务定义为平台自然日。

验证：

- 本地：
  - `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_reports backend.tests.test_v2_reports_api -v` 通过。
  - v2 后端完整测试集 34 个测试通过。
  - `python3 -m py_compile backend/app/v2/api.py backend/app/v2/reports/service.py backend/tests/test_v2_reports.py backend/tests/test_v2_reports_api.py` 通过。
- 远端 `10.20.11.3:/data/smartx-storage-forecast/project`：
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行报表后端测试通过。
  - 使用临时 `node:22-alpine` 容器安装前端依赖并执行 `npm test -- --run src/pages/ReportsPage.test.tsx` 通过。

限制：

- 本切片尚未实现 v2 Word/Excel 导出、报表文件留存和任务中心下载链接。

### 2026-06-06 Phase V2-5 报表导出与留存第一版

状态：完成本地和远端验证，待提交

实施内容：

- 新增 `backend/app/v2/reports/export.py`。
- v2 API 新增：
  - `GET /api/reports/export/word`
  - `GET /api/reports/export/excel`
  - `GET /api/admin/exports/reports/{filename}`
- Word/Excel 导出复用 `ReportService.latest_report()` 输出，确保与页面口径一致。
- 导出文件保存到 `settings.reports_dir`，即 `/data/smartx-storage-forecast/exports/reports`。
- 下载响应头提供：
  - `Content-Disposition`
  - `X-SmartX-Export-Path`
  - `X-SmartX-Export-Url`
- 文件名格式使用 `storage-forecast-<scope>-YYYYMMDD-HHmmss-<days>d.docx/xlsx`。
- Word 首页包含导出范围、生成时间、统计窗口、预测窗口、集群数量、当前软件版本。
- Excel `汇总` sheet 包含同样基础信息，`VM_TOP100_汇总` sheet 标注统计窗口。
- 高风险 VM 底纹逻辑第一版已接入：增长率超过 20% 且增长量大于 100G 时标红。
- `docs/v2-rebuild-task-plan.md` 将 Word/Excel 导出和留存第一版标记完成。

TDD 记录：

- RED：新增 `backend/tests/test_v2_report_exports.py` 后，未登录访问 `/api/reports/export/word` 返回 404，证明 v2 导出路由缺失。
- GREEN：新增导出模块和 API 路由后，导出鉴权、文件保存、响应头、下载链接测试通过。

验证：

- 本地：
  - `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_report_exports -v` 通过。
  - v2 后端完整测试集 35 个测试通过。
  - `python3 -m py_compile backend/app/v2/api.py backend/app/v2/reports/service.py backend/app/v2/reports/export.py backend/tests/test_v2_report_exports.py` 通过。
- 远端 `10.20.11.3:/data/smartx-storage-forecast/project`：
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_reports backend.tests.test_v2_reports_api backend.tests.test_v2_report_exports` 通过。

限制：

- 当前是导出第一版，文档视觉仍是轻量客户报表，不是 v1 已打磨的完整美化版。
- 报表导出任务中心目前使用前端现有同步下载任务入口，尚未接入 v2 统一后台任务状态持久化。

### 2026-06-06 Phase V2-11 统一任务中心基础

状态：完成本地和远端验证，待提交

实施内容：

- 新增 `backend/app/v2/tasks/service.py`。
- 扩展 `tasks` 表，增加 `links_json` 和 `logs_json`，并为旧库提供 `_ensure_column` 兼容。
- `TaskService` 支持：
  - 创建任务。
  - 更新状态、进度、消息、日志、下载链接。
  - 列出最近任务。
  - 清理已完成任务。
- v2 API 新增：
  - `GET /api/tasks`
  - `DELETE /api/tasks/finished`
- `V2Settings` 增加 `__post_init__`，确保 `data_root` 即使传入字符串也会转为 `Path`。
- 前端 App 登录后轮询 `/api/tasks`，将服务端任务合并到右上角任务菜单。
- 前端清空任务按钮调用 `/api/tasks/finished`，并保留本地运行中任务。
- 报表导出成功后写入 `report` 任务，包含 Word/Excel 下载链接，刷新后仍可在任务菜单看到。

TDD 记录：

- RED：新增 `backend/tests/test_v2_tasks_api.py` 后，`app.v2.tasks.service` 缺失。
- GREEN：新增 `TaskService`、tasks API 后，持久化、列表、清理测试通过。
- RED：扩展 `backend/tests/test_v2_report_exports.py` 要求导出后写入任务表，初始返回 0 个 report 任务。
- GREEN：导出路由写入成功任务和下载链接后测试通过。

验证：

- 本地：
  - `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_report_exports backend.tests.test_v2_tasks_api -v` 通过。
  - v2 后端完整测试集 37 个测试通过。
  - `python3 -m py_compile backend/app/v2/api.py backend/app/v2/config.py backend/app/v2/database.py backend/app/v2/tasks/service.py backend/tests/test_v2_tasks_api.py` 通过。
- 远端 `10.20.11.3:/data/smartx-storage-forecast/project`：
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_report_exports backend.tests.test_v2_tasks_api` 通过。
  - `docker compose build frontend` 通过。

限制：

- 当前任务中心还没有独立步骤表，步骤化进度会在迁移/升级/清理模块接入时继续扩展。

### 2026-06-06 Phase V2-6 数据迁移灾备第一版

状态：完成本地和远端验证，待提交

实施内容：

- 新增 `backend/app/v2/migration/service.py`。
- v2 迁移包格式第一版：
  - `manifest.json`
  - `app/smartx.db`
  - `prometheus/**`
- 迁出：
  - 生成 `.tar.gz` 迁移包。
  - 跳过 Prometheus 运行时目录：`chunks_head`、`lock`、`queries.active`、`wal`。
  - 保存到 `/data/smartx-storage-forecast/exports/migrations`。
  - 写入 `migration_export` 任务并提供下载链接。
- 迁入：
  - 上传文件保存到 `/data/smartx-storage-forecast/exports/imports/{task_id}/`。
  - 解压前校验 tar 成员路径，拒绝绝对路径和 `..`。
  - 写入前强制生成 `/data/smartx-storage-forecast/backups/import-before-*.tar.gz`。
  - 备份包含当前 `app/smartx.db` 和 Prometheus 历史目录。
  - merge 模式使用 `INSERT OR IGNORE`，不覆盖已有 Tower、集群、VM 最新元数据、卷、采集记录和 metrics snapshot。
  - Prometheus 历史目录只补齐缺失文件。
- v2 API 新增：
  - `GET /api/admin/migration/export`
  - `POST /api/admin/migration/import`
  - `/api/admin/exports/migrations/{filename}` 下载分类。
- `docs/v2-rebuild-task-plan.md` 将迁出、迁入、导入前备份、任务中心链接第一版标记完成。

TDD 记录：

- RED：新增 `backend/tests/test_v2_migration.py` 后，`app.v2.migration.service` 缺失。
- GREEN：新增 `MigrationService` 后，迁出包含 SQLite/Prometheus、任务链接、导入前备份、merge 不覆盖已有集群测试通过。
- RED：新增迁移 API 测试后，未登录访问 `/api/admin/migration/export` 返回 404。
- GREEN：接入 v2 migration API 后，鉴权、导出、下载、导入备份测试通过。

验证：

- 本地：
  - `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_migration -v` 通过。
  - v2 后端完整测试集 40 个测试通过。
  - `python3 -m py_compile backend/app/v2/api.py backend/app/v2/migration/service.py backend/tests/test_v2_migration.py` 通过。
- 远端 `10.20.11.3:/data/smartx-storage-forecast/project`：
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_migration` 通过。

### 2026-06-06 Phase V2-7 升级开始前数据备份第一版

状态：完成本地和远端验证，待提交

实施内容：

- `UpgradeService` 增加 `start(task_id)`。
- `POST /api/admin/upgrade/start/{task_id}` 接入。
- start 前要求任务状态为 `precheck_passed`。
- start 阶段生成升级前数据备份：
  - 路径：`/data/smartx-storage-forecast/backups/upgrade-<version>-before-<YYYYMMDDHHMMSS>.tar.gz`
  - 内容：`manifest.json`、`app/smartx.db`、Prometheus 历史目录。
  - 跳过 Prometheus 运行时目录：`chunks_head`、`lock`、`queries.active`、`wal`。
- 任务状态更新为 `backup_completed`，统一任务中心记录“升级前备份已完成，等待 runner 执行后续步骤”。
- `docs/v2-rebuild-task-plan.md` 将“升级前强制备份数据第一版”标记完成。

TDD 记录：

- RED：扩展 `backend/tests/test_v2_upgrade.py` 后，`UpgradeService.start()` 缺失，`/api/admin/upgrade/start/{task_id}` 返回 404。
- GREEN：新增 start 备份阶段和 API 路由后，服务和 API 测试通过。

验证：

- 本地：
  - `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade -v` 通过。
  - v2 后端完整测试集 46 个测试通过。
  - `python3 -m py_compile backend/app/v2/api.py backend/app/v2/upgrade/service.py backend/tests/test_v2_upgrade.py` 通过。
- 远端 `10.20.11.3:/data/smartx-storage-forecast/project`：
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_upgrade` 通过。

限制：

- start 当前只完成强制备份，不执行 Docker load、项目文件同步、服务重启和健康检查；这些仍需由 runner 执行链路继续实现。

限制：

- 当前是 v2 迁移第一版，v1 旧迁移包和旧 `latest_vm_volumes.payload_json` 到 v2 结构化卷表的深度兼容仍待实现。
- 迁移任务已有任务中心记录，但尚未拆分为持久化步骤表。

### 2026-06-06 Phase V2-8 空间清理第一版

状态：完成本地和远端验证，待提交

实施内容：

- 新增 `backend/app/v2/cleanup/service.py`。
- v2 API 新增：
  - `GET /api/admin/system/cleanup-artifacts/scan`
  - `POST /api/admin/system/cleanup-artifacts`
- 清理范围第一版：
  - `/data/smartx-storage-forecast/upgrades`
  - `/data/smartx-storage-forecast/exports/reports`
  - `/data/smartx-storage-forecast/exports/migrations`
  - `/data/smartx-storage-forecast/exports/imports`
- 清理明确不碰 `/data/smartx-storage-forecast/backups`。
- 扫描返回每项：
  - key、label、path、count、size、size_label。
  - total_count、total_size、space_reclaimable。
- 清理按真实文件大小统计释放空间，并写入 `cleanup` 任务日志。
- `docs/v2-rebuild-task-plan.md` 将空间扫描和清理第一版标记完成。

TDD 记录：

- RED：新增 `backend/tests/test_v2_cleanup.py` 后，`app.v2.cleanup` 缺失。
- GREEN：新增 `CleanupService` 后，扫描/清理真实大小、不删除 backups、任务记录测试通过。
- 扩展 API 测试后，清理接口鉴权、扫描和执行测试通过。

验证：

- 本地：
  - `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_cleanup -v` 通过。
  - v2 后端完整测试集 42 个测试通过。
  - `python3 -m py_compile backend/app/v2/api.py backend/app/v2/cleanup/service.py backend/tests/test_v2_cleanup.py` 通过。
- 远端 `10.20.11.3:/data/smartx-storage-forecast/project`：
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_cleanup` 通过。

限制：

- 旧 Docker 镜像扫描/清理尚未接入 v2；本阶段只完成运行文件产物清理。

### 2026-06-06 Phase V2-7 升级中心 manifest/预检查第一版

状态：完成本地和远端验证，待提交

实施内容：

- 新增 `backend/app/v2/upgrade/service.py`。
- v2 升级包上传第一版：
  - 保存上传包到 `/data/smartx-storage-forecast/upgrades/{task_id}`。
  - 解压到 `/data/smartx-storage-forecast/upgrades/{task_id}/package`。
  - 解析 `manifest.json`。
  - 自动识别 `components[*].type`，支持 `platform`、`runner`、`observability` 等组件类型。
  - 拦截绝对路径、`..`、`.env`、`smartx.db`、`backups`、`exports`、`compose-runtime`、`password`、`token`、`secret` 等敏感路径。
- v2 升级预检查第一版：
  - manifest 基础字段。
  - 包内路径安全。
  - 镜像 archive 是否存在。
  - 镜像 sha256 是否匹配。
  - `project_files=true` 时校验 `project/docker-compose.offline.yml`。
- v2 API 新增：
  - `POST /api/admin/upgrade/upload`
  - `POST /api/admin/upgrade/precheck/{task_id}`
- 上传和预检查结果写入统一任务中心。
- `docs/v2-rebuild-task-plan.md` 将统一 manifest、组件识别、预检查第一版标记完成。

TDD 记录：

- RED：新增 `backend/tests/test_v2_upgrade.py` 后，`app.v2.upgrade.service` 缺失。
- GREEN：新增 `UpgradeService` 后，上传解析组件、sha256/project_files 预检查、敏感路径拒绝测试通过。
- 扩展 API 测试后，升级上传/预检查接口鉴权和返回测试通过。

验证：

- 本地：
  - `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade -v` 通过。
  - v2 后端完整测试集 45 个测试通过。
  - `python3 -m py_compile backend/app/v2/api.py backend/app/v2/upgrade/service.py backend/tests/test_v2_upgrade.py` 通过。
- 远端 `10.20.11.3:/data/smartx-storage-forecast/project`：
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_upgrade` 通过。

限制：

- 本阶段只实现上传和预检查薄片，不执行 Docker load、项目文件同步、备份、重启、健康检查和回滚。

### 2026-06-06 Phase V2-3 采集记录 API

状态：完成本地和远端验证，待提交

实施内容：

- `CollectionService` 增加：
  - `list_runs(limit=30)`
  - `run_detail(run_id)`
- v2 API 新增：
  - `GET /api/collection/runs`
  - `GET /api/collection/runs/{run_id}`
- 手动采集路由改为复用 `get_collection_service` 依赖，便于测试和后续扩展。
- `docs/v2-rebuild-task-plan.md` 将采集状态写入 SQLite、采集记录列表和详情 API 标记完成。

TDD 记录：

- RED：新增 `backend/tests/test_v2_collection_runs_api.py` 后，未登录访问 `/api/collection/runs` 返回 404。
- GREEN：新增 CollectionService 查询方法和 API 路由后，鉴权、列表倒序、详情、404 测试通过。

验证：

- 本地：
  - `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_collection_runs_api backend.tests.test_v2_collection -v` 通过。
  - v2 后端完整测试集 46 个测试通过。
  - `python3 -m py_compile backend/app/v2/api.py backend/app/v2/collection/service.py backend/tests/test_v2_collection_runs_api.py` 通过。
- 远端 `10.20.11.3:/data/smartx-storage-forecast/project`：
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_collection_runs_api` 通过。

### 2026-06-06 Phase V2-6 迁移校验和导入健康检查

状态：完成本地和远端验证，待提交

实施内容：

- v2 迁移包 `manifest.json` 增加 `files` 字段。
- 每个导出的 SQLite/Prometheus 文件记录：
  - `size`
  - `sha256`
- 导入完成后返回 `health`：
  - SQLite 是否存在。
  - Prometheus 目录是否存在。
  - Prometheus block 数量和部分 block 名称。
  - `complete` 标识业务库和 Prometheus 历史指标是否完整。
- 如果迁移包只包含业务库、没有 Prometheus 历史 block，`health.complete=false` 并返回提示信息。
- `docs/v2-rebuild-task-plan.md` 将“迁移包校验信息”和“导入后 Prometheus 历史指标回归检查第一版”标记完成。

TDD 记录：

- RED：扩展 `backend/tests/test_v2_migration.py` 后，manifest 缺少 `files`，导入结果缺少 `health`。
- GREEN：新增文件 sha256/size manifest 和 `MigrationService.health_check()` 后测试通过。

验证：

- 本地：
  - `PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_migration -v` 通过。
  - v2 后端完整测试集 46 个测试通过。
  - `python3 -m py_compile backend/app/v2/migration/service.py backend/tests/test_v2_migration.py` 通过。
- 远端 `10.20.11.3:/data/smartx-storage-forecast/project`：
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_migration` 通过。

### 2026-06-06 Phase V2-1 部署目录与健康检查写权限

状态：完成本地验证，待远端验证和提交

实施内容：

- v2 健康检查从“目录存在”升级为“目录存在且可写”。
- 对每个 required directory 写入并删除 `.smartx-healthcheck` marker，能发现 Prometheus 数据目录权限错误、只读挂载或目录被占用为不可写路径等问题。
- 新增回归测试覆盖目录存在但 marker 无法写入时 `directories=false`。
- `docs/v2-rebuild-task-plan.md` 将 v2 配置模型、版本文件、运行目录、健康检查和 pre_install 初始化标记完成。

TDD 记录：

- RED：新增 `test_health_check_reports_required_directory_writeability` 后，旧健康检查仍返回 `ok=True`，测试按预期失败。
- GREEN：新增 `_directory_ready()` 写入 marker 判断后，v2 foundation 和 deployment config 测试通过。

验证：

- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_foundation -v` 通过。
- 本地：临时安装 pytest 到 `/tmp/smartx-v2-venv` 后，`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m pytest backend/tests/test_deployment_config.py -q` 通过，15 个部署约束测试通过。
- 本地：v2 后端完整 unittest 集 47 个测试通过。
- 远端 `10.20.11.3:/data/smartx-storage-forecast/project`：
  - 拉取前发现远端存在旧验证留下的未提交 v2 改动，已用 `git stash push -u -m remote-pre-pull-20260606110431` 保存后快进到 `b9bc271`。
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_foundation` 通过。
  - 执行 `./pre_install.sh` 成功，目录完整；Prometheus 数据目录为 `nobody:nogroup`，对应 `65534:65534`。
  - `docker compose build web-api frontend` 通过。

### 2026-06-06 Phase V2-6 迁移导出精确进度与任务步骤

状态：完成本地验证，待远端验证和提交

实施内容：

- v2 `tasks` 表新增 `steps_json`，`TaskService` 支持创建、更新、列表返回结构化步骤。
- v2 新增迁移导出后台任务 API：
  - `POST /api/admin/migration/export/start`
  - `GET /api/admin/migration/export/status/{task_id}`
- 迁移导出任务保存 `steps`、`logs`、`processed_bytes`、`total_bytes`、下载链接和服务器留档路径。
- 迁移包文件名增加随机后缀，避免同一秒多次导出覆盖留档文件。
- 导出打包时逐文件记录“当前文件”和已处理/总字节数，解决大数据迁出时看起来卡在固定百分比的问题第一版。
- 前端任务中心类型新增 `steps`，任务菜单显示最近步骤摘要；迁移导出任务 patch 保留后端 steps。
- `docs/v2-rebuild-task-plan.md` 将迁出精确进度和统一任务步骤标记完成第一版。

TDD 记录：

- RED：TaskService 测试新增 `steps` 后，`create_task()` 不接受 `steps` 参数。
- GREEN：tasks schema 增加 `steps_json`，TaskService create/update/list 支持 steps。
- RED：v2 迁移 API 测试调用 `/api/admin/migration/export/start` 返回 404。
- GREEN：新增 start/status API 和迁移导出任务状态转换。
- RED：同秒连续导出导致下载文件被覆盖，测试发现 download content 和原始 export content 不一致。
- GREEN：迁移包文件名增加随机后缀，并避免 start 任务内部重复创建独立完成任务。
- RED：任务状态日志没有“当前文件”。
- GREEN：导出按候选文件逐项打包并更新日志、字节进度。

验证：

- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_tasks_api backend.tests.test_v2_migration -v` 通过。
- 本地：v2 后端完整 unittest 集 47 个测试通过。
- 本地：`python3 -m py_compile backend/app/v2/api.py backend/app/v2/database.py backend/app/v2/migration/service.py backend/app/v2/tasks/service.py backend/app/v2/system/health.py backend/tests/test_v2_migration.py backend/tests/test_v2_tasks_api.py` 通过。
- 本机无 `npm` 可执行文件，前端构建将在远端 Docker build 中验证。
- 远端 `10.20.11.3:/data/smartx-storage-forecast/project`：
  - 快进拉取到 `8300d47`。
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_tasks_api backend.tests.test_v2_migration` 通过。
  - `docker compose build web-api frontend` 通过，前端 Vite 构建成功；仅有 bundle 大小警告。

### 2026-06-06 Phase V2-10 v1 迁移包与旧 VM 卷 payload 兼容

状态：完成本地验证，待远端验证和提交

实施内容：

- v2 数据迁入兼容 v1 迁移包路径：
  - v2：`app/smartx.db`、`prometheus/`
  - v1：`smartx-data/smartx.db`、`prometheus-data/`
- v2 merge 导入时，如果 incoming SQLite 不存在 v2 `vm_volumes` 表，但存在 v1 `latest_vm_volumes.payload_json`，会抽取必要字段写入 v2 `vm_volumes`。
- 抽取字段包含卷 ID、名称、path、容量、已用容量、存储策略、副本数、thin provision、EC k/m、采集时间。
- 原始 Tower 嵌套对象、vm_disks 等大 payload 不写入 v2 结构表。
- `docs/v2-rebuild-task-plan.md` 将 v1 迁移包导入和旧 VM 卷 payload 抽取标记为第一版完成。

TDD 记录：

- RED：构造 v1 风格迁移包 `smartx-data/smartx.db`，导入后 `restored` 为空，说明 v2 未识别 v1 路径。
- GREEN：新增 v1/v2 数据目录兼容路径，新增 `_merge_v1_latest_vm_volume_payloads()`，测试通过。

验证：

- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_migration -v` 通过。
- 本地：v2 后端完整 unittest 集 48 个测试通过。
- 远端 `10.20.11.3:/data/smartx-storage-forecast/project`：
  - 快进拉取到 `fa4c2f3`。
  - 使用 `smartx-storage-forecast-web-api:local` 容器执行 `backend.tests.test_v2_migration` 通过。

### 2026-06-06 Phase V2-12 升级执行链第一版

状态：完成本地验证，待远端验证和提交

实施内容：

- v2 `UpgradeService.start()` 从“备份后等待 runner”升级为第一版可执行链：
  - 生成升级前备份。
  - 加载 manifest 中声明的 platform 镜像。
  - 同步 `project/` 白名单项目文件，并先备份目标项目文件到 `/data/smartx-storage-forecast/backups/project-files-before-版本-时间/`。
  - 写入 `/data/smartx-storage-forecast/compose-runtime/docker-compose.upgrade.yml`。
  - 通过 `docker compose -f docker-compose.offline.yml -f <override> up -d --no-deps ...` 重启 platform 服务。
  - 写入结构化 steps、logs、backup_path、project_backup_path、override_path。
- 平台升级只处理 `web-api`、`collector-worker`、`frontend`；manifest 里的 runner 镜像不会写入平台 override。
- 新增 `UpgradeCommandExecutor`，生产默认执行真实命令；测试可注入 fake executor。
- API 测试通过 `SMARTX_UPGRADE_DRY_RUN=1` 避免本地/CI 无 Docker CLI 时失败，生产不设置该变量。
- `docs/v2-rebuild-task-plan.md` 将平台三件套升级、项目文件备份同步、升级历史第一版标记完成；真正由 upgrade-runner 接管仍保留待办。

TDD 记录：

- RED：升级测试导入 `UpgradeCommandExecutor` 失败。
- GREEN：新增 executor 抽象，start 执行 Docker load、项目同步、override 写入和 compose up。
- 回归：API 测试本地无 Docker CLI 失败，增加显式 dry-run 环境变量用于测试环境。

验证：

- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade -v` 通过。
- 本地：v2 后端完整 unittest 集 48 个测试通过。
- 远端 `10.20.11.3:/data/smartx-storage-forecast/project`：
  - 快进拉取到 `a671e6c`。
  - 使用 `SMARTX_UPGRADE_DRY_RUN=1` 执行 `backend.tests.test_v2_upgrade` 通过。
  - `docker compose build web-api frontend` 通过。

### 2026-06-06 Phase V2-12 upgrade-runner 接管第一版

状态：完成本地验证，待远端验证和提交

实施内容：

- 新增 `app.v2.upgrade.runner`：
  - `run_pending_once(settings, tasks, executor, project_path)` 扫描 `/data/smartx-storage-forecast/upgrades/*/task.json`。
  - 遇到 `status=pending` 且 `runner_requested=true` 的升级任务，调用 v2 `UpgradeService.execute_task()` 执行。
  - `main()` 循环每 3 秒扫描一次，支持 SIGTERM/SIGINT 退出。
- `UpgradeService.start(task_id, submit_to_runner=True)` 支持只提交任务给 runner，不在 web-api 内执行 Docker 操作。
- compose 和 `backend/Dockerfile.upgrade` 的 runner 入口统一改为 `python -m app.v2.upgrade.runner`。
- 部署测试新增校验，防止 runner 入口回退到旧 `app.upgrade.runner`。
- `docs/v2-rebuild-task-plan.md` 将“升级任务由 upgrade-runner 执行”标记为第一版完成。

TDD 记录：

- RED：新增 runner 接管测试后，`app.v2.upgrade.runner` 模块不存在。
- GREEN：新增 runner 模块、start 提交模式和 execute_task 复用执行链。
- 回归：compose/Dockerfile 仍指向旧 runner，更新入口并补部署测试。

验证：

- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade -v` 通过。
- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m pytest backend/tests/test_deployment_config.py -q` 通过，16 个测试通过。
- 本地：v2 后端完整 unittest 集 49 个测试通过。

### 2026-06-06 Phase V2-15 upgrade-runner 依赖瘦身

状态：完成本地验证，待远端验证和提交

实施内容：

- `backend/requirements-upgrade.txt` 不再安装 FastAPI/Pydantic/python-multipart 等 web-api 依赖，runner 镜像构建不再因为 PyPI 拉取 FastAPI 失败而中断。
- `app.v2.upgrade.service` 对 FastAPI 依赖使用兼容 shim：web-api 环境仍使用 FastAPI `HTTPException`/`UploadFile`，runner 环境无 FastAPI 时仍可 import 并执行任务。
- 部署测试新增 runner 依赖约束，防止后续重新把 web-api 依赖塞回 runner 镜像。

TDD 记录：

- RED：新增部署测试后，`requirements-upgrade.txt` 包含 `fastapi` 导致失败。
- GREEN：移除 runner 第三方依赖，并让 upgrade service 不硬依赖 FastAPI。

验证：

- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m pytest backend/tests/test_deployment_config.py -q` 通过，17 个测试通过。
- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade -v` 通过。
- 本地：v2 后端完整 unittest 集 49 个测试通过。

远端验证补充：

- 远端 `10.20.11.3:/data/smartx-storage-forecast/project`：
  - 快进拉取到 `c16c078`。
  - `docker compose build upgrade-runner` 通过。
  - 验证此前失败的 runner pip 安装问题已解除；空 `requirements-upgrade.txt` 可正常构建镜像。

### 2026-06-06 Phase V2-12 Prometheus observability 组件升级第一版

状态：完成本地与远端验证

实施内容：

- v2 升级 manifest 支持 `type=observability` 的 Prometheus 组件。
- 平台升级、observability 升级的镜像和服务集合拆分计算：
  - platform 只处理 `web-api`、`collector-worker`、`frontend`。
  - observability 只处理 `prometheus`。
- Prometheus 组件预检查增加数据目录写入检查，并统计历史 block 数量。
- Prometheus 组件升级只写入 `prometheus` 镜像 override，只重启 Prometheus，不误重启平台三件套。
- `docs/v2-rebuild-task-plan.md` 将 Prometheus 组件升级第一版和 Prometheus 权限预检查第一版标记完成。

TDD 记录：

- RED：新增 `test_observability_upgrade_only_restarts_prometheus_and_checks_permissions` 后，升级服务不会识别 observability 组件，也不会检查 Prometheus 数据目录权限。
- GREEN：新增 observability 镜像/服务解析、Prometheus 权限预检查、统一 upgrade override 写入和按 manifest 服务重启。

验证：

- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade -v` 通过，5 个测试通过。
- 本地：v2 后端完整 unittest 集 50 个测试通过。
- 本地：`python3 -m py_compile backend/app/v2/upgrade/service.py backend/tests/test_v2_upgrade.py` 通过。
- 远端 `10.20.11.3:/data/smartx-storage-forecast/project`：
  - 快进拉取到 `24a8ea8`。
  - `docker run --rm -v /data/smartx-storage-forecast/project:/src -e PYTHONPATH=/src/backend -e SMARTX_UPGRADE_DRY_RUN=1 -w /src smartx-storage-forecast-web-api:local python -m unittest backend.tests.test_v2_upgrade -v` 通过，5 个测试通过。
  - `docker compose build web-api frontend upgrade-runner` 通过。

### 2026-06-06 Phase V2-12 runner 组件升级第一版

状态：完成本地验证，待远端验证和提交

实施内容：

- v2 升级执行链支持纯 `runner` 组件包。
- runner 组件升级只加载 `upgrade-runner` 镜像，只重启 `upgrade-runner`。
- runner 组件升级运行时 override 写入 `/data/smartx-storage-forecast/compose-runtime/docker-compose.runner-upgrade.yml`，不再写项目目录。
- 平台升级和 Prometheus 升级继续使用 `/data/smartx-storage-forecast/compose-runtime/docker-compose.upgrade.yml`，runner 组件升级独立隔离。
- runner 自升级采用两阶段恢复：重启自身前写入 `runner_restarting` 和 `runner_resume_pending`，新 runner 启动后扫描该状态并完成健康检查收尾，避免任务卡死在执行中。
- `docs/v2-rebuild-task-plan.md` 将 runner 组件升级第一版和 runner 自升级不中断链第一版标记完成。

TDD 记录：

- RED：新增 `test_runner_component_upgrade_writes_runtime_override_and_only_restarts_runner` 后，服务不会生成 `docker-compose.runner-upgrade.yml`，测试因文件不存在失败；补充 runner 重启中断模拟后，`SystemExit` 直接冒出导致任务无法恢复。
- GREEN：新增 runner 镜像/服务解析、runner-only 判断、runner 专用 override 写入，以及 `runner_restarting` 状态的恢复收尾逻辑。

验证：

- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade.V2UpgradeServiceTest.test_runner_component_upgrade_writes_runtime_override_and_only_restarts_runner -v` 通过。
- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade -v` 通过，6 个测试通过。
- 本地：v2 后端完整 unittest 集 51 个测试通过。
- 本地：`python3 -m py_compile backend/app/v2/upgrade/service.py backend/tests/test_v2_upgrade.py` 通过。

### 2026-06-06 Phase V2-12 升级 API 与回滚闭环第一版

状态：完成本地验证，待远端验证和提交

实施内容：

- 后端补齐前端服务管理页已调用的 v2 升级接口：
  - `/api/admin/upgrade/status/{task_id}`
  - `/api/admin/upgrade/history`
  - `/api/admin/upgrade/package/{task_id}`
  - `/api/admin/upgrade/version`
  - `/api/admin/upgrade/verification`
  - `/api/admin/component-upgrade/*` 上传、预检查、开始、状态、历史、删除和版本别名。
- 升级 service 返回前端公共状态：`succeeded`、`running`、`prechecked` 等，同时 task 文件内部仍保留执行状态。
- 回滚第一版支持恢复项目文件备份、移除运行时 override、重启 manifest 声明服务，并写入 rollback steps/logs。
- `docs/v2-rebuild-task-plan.md` 将回滚和历史记录第一版标记完成。

TDD 记录：

- RED：API 测试新增 status/history/version/verification/component alias 后，`/api/admin/upgrade/status/{task_id}` 返回 404。
- GREEN：补齐 UpgradeService 公共任务响应和 API 路由别名。
- RED：回滚测试调用 `service.rollback()` 失败，因为方法不存在。
- GREEN：实现项目文件恢复、override 删除、服务重启和 rollback 状态写入。

验证：

- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade.V2UpgradeApiTest.test_upgrade_api_requires_auth_uploads_and_prechecks_package -v` 通过。
- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade.V2UpgradeServiceTest.test_rollback_restores_project_files_and_removes_runtime_override -v` 通过。
- 本地：`PYTHONPATH=backend /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade -v` 通过，7 个测试通过。
- 本地：v2 后端完整 unittest 集 52 个测试通过。
- 本地：`python3 -m py_compile backend/app/v2/api.py backend/app/v2/upgrade/service.py backend/app/v2/upgrade/runner.py backend/tests/test_v2_upgrade.py` 通过。

### 2026-06-06 Phase V2-8 服务重启与旧镜像清理接口第一版

状态：完成本地验证，待远端验证和提交

实施内容：

- 新增 v2 系统控制服务 `app.v2.system.control`。
- 后端新增 `/api/admin/system/restart`，按 v2 设计提交重启 `web-api`、`collector-worker`、`prometheus`。
- 后端补齐前端服务管理页已调用的 Docker 镜像接口：
  - `/api/admin/system/cleanup-images/scan`
  - `/api/admin/system/cleanup-images`
- 旧镜像清理支持先扫描再清理，返回镜像列表、每个镜像大小、预计可释放空间、实际释放空间和日志。
- 测试和 API 支持 `SMARTX_UPGRADE_DRY_RUN=1`，避免本地/CI 没有 Docker CLI 时误清理真实镜像。
- `docs/v2-rebuild-task-plan.md` 将服务重启第一版和未使用 Docker 镜像扫描清理第一版标记完成。

TDD 记录：

- RED：新增镜像清理 service 测试后，`CleanupService` 不支持 executor，也没有 `scan_unused_images()`。
- GREEN：新增 Docker image 扫描/inspect/rm 执行链，兼容 Docker 按行 JSON 和测试 JSON 数组输出。
- RED：API 测试要求 cleanup-images 和 restart 接口后，`/api/admin/system/cleanup-images/scan` 返回 404。
- GREEN：新增系统控制服务和三个后端 API 路由。

验证：

- 本地：`PYTHONPATH=backend SMARTX_UPGRADE_DRY_RUN=1 /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_cleanup -v` 通过，3 个测试通过。
- 本地：v2 后端完整 unittest 集 53 个测试通过。
- 本地：`python3 -m py_compile backend/app/v2/api.py backend/app/v2/cleanup/service.py backend/app/v2/system/control.py backend/tests/test_v2_cleanup.py` 通过。

### 2026-06-06 Phase V2-9 升级包与组件包 v2 manifest 闭环

状态：完成本地验证，待远端验证和提交

实施内容：

- 平台升级包脚本改为输出 v2 manifest：
  - `schema_version: "2"`
  - `package_id`
  - `components[0].type = platform`
  - `components[0].images[].archive`
  - `project_files: true`
  - `project_file_list` 白名单明细
  - `migration.script = scripts/migrate.sh`
  - `compatibility.min_platform_version`
- runner 组件包脚本改为输出 v2 manifest：
  - `schema_version: "2"`
  - `components[0].type = runner`
  - `project_files: false`
  - `compatibility.min_runner_version`
- 平台包继续不包含 `upgrade-runner.tar`，runner 包继续只包含 `upgrade-runner`。
- migrate 脚本从 `project_file_list` 读取白名单，并从 `components[].images[]` 写平台服务 override。
- `docs/v2-rebuild-task-plan.md` 将 Phase V2-9 “升级包和组件包打包第一版”标记完成。

TDD 记录：

- RED：新增 `backend/tests/test_v2_package_builders.py` 后，两个包构建器测试因 manifest 缺少 `schema_version` 失败。
- GREEN：调整两个打包脚本输出 v2 manifest，并更新旧部署配置断言。

验证：

- 本地：`PYTHONPATH=backend SMARTX_UPGRADE_DRY_RUN=1 /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_package_builders -v` 通过，2 个测试通过。
- 本地：`/tmp/smartx-v2-venv/bin/python -m pytest backend/tests/test_deployment_config.py backend/tests/test_v2_package_builders.py -q` 通过，19 个测试通过。
- 本地：`PYTHONPATH=backend SMARTX_UPGRADE_DRY_RUN=1 /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_upgrade -v` 通过，7 个测试通过。
- 本地：`python3 -m py_compile scripts/build_upgrade_package.py scripts/build_runner_component_package.py` 通过。

### 2026-06-06 Phase V2-14 顶部菜单点击空白处收起验证

状态：完成远端验证，待提交

实施内容：

- 新增 `frontend/src/components/AppLayout.test.tsx`，覆盖：
  - 账号头像菜单打开后点击内容区会自动收起。
  - 任务菜单打开后点击内容区会自动收起。
- 当前 `AppLayout` 已有 `pointerdown` 外部点击关闭逻辑，本次只补自动化测试和任务文档勾选。
- `docs/v2-rebuild-task-plan.md` 将“点击空白处可收起任务菜单”和“下拉菜单点击空白处自动收起”标记完成。

验证：

- 远端 `10.20.11.3`：`npm test -- AppLayout.test.tsx` 通过，1 个测试文件、2 个测试通过。

### 2026-06-06 Phase V2-11 失败任务展示验证

状态：完成远端验证，待提交

实施内容：

- 扩展 `frontend/src/components/AppLayout.test.tsx`，覆盖失败任务在任务中心中展示：
  - 失败任务标题和错误摘要。
  - 失败步骤，如 `失败 校验镜像`。
  - 错误日志摘要，如镜像 sha256 不匹配。
- 当前 `AppLayout` 已渲染 `task.detail`、`task.steps` 和 `task.logs`，本次补测试和文档勾选。
- `docs/v2-rebuild-task-plan.md` 将“失败任务展示失败步骤和错误摘要”标记完成。

验证：

- 远端 `10.20.11.3`：`npm test -- AppLayout.test.tsx` 通过，1 个测试文件、3 个测试通过。

### 2026-06-06 Phase V2-6 overwrite 导入显式确认验证

状态：完成本地和远端验证，待提交

实施内容：

- 后端 API 测试补充 `mode=overwrite` 且 `confirmed=false` 时返回 `400`，错误明确提示覆盖导入会清空当前系统数据。
- 前端 `ServicePage` 测试覆盖：
  - 选择覆盖导入后，未勾选确认时“导入迁移包”按钮禁用。
  - 勾选“我确认覆盖当前系统数据”后才调用 `api.importMigration(file, "overwrite", true, ...)`。
- 修复 `ServicePage` 滚动重置在不支持 `HTMLElement.scrollTo` 的环境中抛错的问题，回退到设置 `scrollTop = 0`。
- 测试环境 `frontend/src/test/setup.ts` 增加 `window.scrollTo` stub。
- `docs/v2-rebuild-task-plan.md` 将 “overwrite 模式必须显式选择” 标记完成。

验证：

- 本地：`PYTHONPATH=backend SMARTX_UPGRADE_DRY_RUN=1 /tmp/smartx-v2-venv/bin/python -m unittest backend.tests.test_v2_migration -v` 通过，4 个测试通过。
- 远端 `10.20.11.3`：`npm test -- ServicePage.test.tsx` 通过，1 个测试文件、4 个测试通过。

### 2026-06-06 Phase V2-7 升级中心预检查与平台状态验证

状态：完成远端验证，待提交

实施内容：

- 扩展 `frontend/src/pages/ServicePage.test.tsx`，覆盖平台升级页：
  - “平台状态”区域集中展示当前版本、目标版本、升级中心版本、Compose 项目、最近成功包、SHA256 和服务运行表。
  - 页面不再出现单独的“服务运行核验”二级区块。
  - 点击“预检查”后立即显示步骤化进度，包括执行中和未执行状态。
- 当前 `ServicePage` 已具备平台状态合并和预检查步骤化 UI，本次补自动化测试和任务文档勾选。
- `docs/v2-rebuild-task-plan.md` 将“预检查显示步骤化进度”和“页面合并平台状态和升级后核验”标记完成。

验证：

- 远端 `10.20.11.3`：`npm test -- ServicePage.test.tsx` 通过，1 个测试文件、6 个测试通过。

### 2026-06-06 Phase V2-8 服务管理页面结构验证

状态：完成远端验证，待提交

实施内容：

- 扩展 `frontend/src/components/AppLayout.test.tsx`，覆盖“服务管理”作为主导航项位于“设置”后，并点击后触发 `onNavigate("service")`。
- 扩展 `frontend/src/pages/ServicePage.test.tsx`，覆盖服务管理二级菜单包含：
  - 数据迁移
  - 服务重启
  - 空间清理
  - 平台升级
  - 组件升级
  - 升级历史
- 新增 `frontend/src/pages/SettingsPage.test.tsx`，确认设置页只保留 Tower 配置，不出现服务管理、系统升级、数据迁移内容。
- 修复 `AppLayout` 滚动重置在不支持 `HTMLElement.scrollTo` 的环境中抛错的问题，回退到设置 `scrollTop = 0`。
- `docs/v2-rebuild-task-plan.md` 将服务管理独立页、二级菜单、设置页清理和对应前端 UI 项标记完成。

验证：

- 远端 `10.20.11.3`：`npm test -- AppLayout.test.tsx ServicePage.test.tsx SettingsPage.test.tsx` 通过，3 个测试文件、12 个测试通过。

### 2026-06-06 Phase V2-8 空间清理按钮色彩验证

状态：完成远端红绿验证，待提交

实施内容：

- 扩展 `frontend/src/pages/ServicePage.test.tsx`，覆盖“空间清理”页：
  - “扫描”按钮使用 `primary-button service-header-button`。
  - “一键清理”按钮使用 `danger-button service-header-button`。
- 修复 `frontend/src/pages/ServicePage.tsx` 中空间清理扫描按钮仍使用次级按钮的问题，改为主色按钮。
- `docs/v2-rebuild-task-plan.md` 将“清理按钮使用危险色，扫描按钮使用主色”标记完成。

TDD 记录：

- RED：远端 `10.20.11.3` 执行 `npm test -- ServicePage.test.tsx`，新增测试失败，收到 `secondary-button service-header-button`，符合预期。
- GREEN：改为 `primary-button service-header-button` 后，远端同一测试通过，1 个测试文件、8 个测试通过。

### 2026-06-06 Phase V2 文档状态治理

状态：完成远端验证，待提交

实施内容：

- 按现有 v2 源码和测试覆盖，对 `docs/v2-rebuild-task-plan.md` 中已完成但未勾选的任务做状态对齐。
- 本次只标记已有测试证据的第一版能力：
  - 认证、登录、token、`/api/me`、改密、管理接口鉴权。
  - Tower CRUD、连接测试、集群同步、集群启用和 scope 参数。
  - CloudTower 客户端、采集入口、定时采集、启用集群过滤、指标写入、VM 最新名称和卷数据。
  - Prometheus 指标 label、查询服务、趋势身份过滤、健康检查。
  - v2 schema、结构化 VM 卷、任务状态、导出留档、升级历史第一版。
  - 报表 90 天预测、7 天平均、图表窗口、30 天样本过滤、新建 VM、导出留存和任务链接第一版。
  - v1 信息架构、统一布局、Dashboard/VM/报表页面第一版。
- 未标记仍缺实现或缺专门验证的项，例如 Word 目录、Word 页脚、部署发版现场验证。

验证计划：

- 远端 `10.20.11.3`：使用 `smartx-storage-forecast-web-api:local` 容器运行 15 个 v2 后端测试模块，40 个测试通过。
- 远端 `10.20.11.3`：使用 `node:22-alpine` 运行核心前端测试 `AppLayout/Dashboard/Vms/Reports/Service/Settings`，6 个测试文件、18 个测试通过。
- 注意：第一次前端测试发现远端存在 macOS 资源叉垃圾文件 `frontend/src/pages/._ReportsPage.test.tsx` 导致 Vitest 误读；已删除 `frontend/src/**/._*` 后重跑通过。

### 2026-06-06 Phase V2-5 报表 Word 目录页脚与高风险底纹

状态：完成远端红绿验证，待提交

实施内容：

- 扩展 `backend/tests/test_v2_report_exports.py`，验证：
  - Word 文档包含“目录”以及每个集群名称。
  - Word 页脚包含 Tower、集群和生成时间。
  - Word 高风险 VM 行写入红色底纹 `F4CCCC`。
  - Excel 高风险 VM 样式仍包含 `F4CCCC`。
- 修改 `backend/app/v2/reports/export.py`：
  - 首页信息表后新增集群目录段。
  - Word 页脚输出 `Tower - 集群 - 生成时间`。
  - Word VM 表格对增长率超过 20% 且增长量大于 100G 的 VM 行设置红色底纹。
- `docs/v2-rebuild-task-plan.md` 将 Word 目录、Word 页脚、高风险 VM 底纹标红标记完成。

TDD 记录：

- RED：远端 `10.20.11.3` 运行 `python -m unittest backend.tests.test_v2_report_exports -v`，失败于 Word XML 不包含“目录”，符合预期。
- GREEN：实现目录、页脚和 Word 底纹后，远端同一测试通过。

### 2026-06-06 Phase V2-9 部署发版状态治理

状态：完成远端验证，待提交

实施内容：

- 根据 `backend/tests/test_deployment_config.py` 和 `backend/tests/test_v2_package_builders.py` 的验证结果，更新 `docs/v2-rebuild-task-plan.md`：
  - 平台镜像使用平台版本 tag。
  - runner 镜像使用 runner 版本 tag。
  - 平台 GitHub Actions 与 runner GitHub Actions 分离。
  - offline/release compose 使用明确版本，且不包含 build。
  - 平台升级包不包含 `.env`、数据库、Prometheus 数据、凭据，也不包含 runner 镜像。
  - 打包脚本自动校验版本一致性。
  - README 已写明升级包目录结构，changelog 第一版已存在。

验证：

- 远端 `10.20.11.3`：容器内临时安装 `backend/requirements-dev.txt` 后执行 `python -m pytest backend/tests/test_deployment_config.py backend/tests/test_v2_package_builders.py -q`，19 个测试通过。

### 2026-06-06 Phase V2 测试计划状态治理

状态：完成远端验证，待提交

实施内容：

- 根据已通过的自动化测试结果，对 `docs/v2-rebuild-task-plan.md` 的阶段项和测试计划项做状态对齐。
- 标记完成的范围仅限已有自动化测试覆盖的第一版能力：
  - v1 数据兼容迁入、导入后健康验证、平台升级、项目文件同步。
  - 数据迁移页面、服务重启、compose/Dockerfile、GitHub Actions、pre_install。
  - 后端测试计划中的认证、Tower、采集、Prometheus、Dashboard、VM 改名、月增长过滤、报表、迁入备份、v1 兼容、升级预检查、空间清理。
  - 前端测试计划中的登录/token 过期第一版、scope 切换第一版、Dashboard 风险、新建 VM 卡片、VM 跳转、报表/迁移/升级/清理任务。
- 保留现场端到端项未完成，包括新部署采集、真实 v1 迁入后趋势回归、平台/runner/Prometheus 真实升级包执行。

验证依据：

- 远端 v2 后端 40 个 unittest 通过。
- 远端核心前端 18 个 Vitest 通过。
- 远端部署配置和打包脚本 19 个 pytest 通过。

### 2026-06-06 Phase V2 前端布局与滚动条回归

状态：完成远端验证，待提交

实施内容：

- 新增 `frontend/src/components/AppLayout.test.tsx` 用例，验证 `.workspace.auto-scrollbar` 默认隐藏滚动条、滚动时添加 `is-scrolling`、900ms 后自动移除。
- 新增 `frontend/src/pages/DashboardPage.test.tsx` 用例，验证首页容量风险、Tower、集群是 `dashboard-metrics-row` 下三个独立指标卡，不互相嵌套。
- 新增 `frontend/src/styles/global.test.ts`，验证关键响应式 CSS：
  - 桌面 Dashboard 指标行保持容量风险小列、Tower/集群中列的受控列宽。
  - 960px 移动端 Dashboard/metrics 切单列，workspace 不遮挡滚动。
  - 服务管理二级导航在移动端横向换行，service-focus 主内容移动端左右边距收缩。
- `docs/v2-rebuild-task-plan.md` 标记 Dashboard 独立卡片、移动端第一版布局、隐藏滚动条三项完成。

验证：

- 远端 `10.20.11.3`：`npm test -- AppLayout.test.tsx DashboardPage.test.tsx`，2 个测试文件、9 个测试通过。
- 远端 `10.20.11.3`：`npm test -- global.test.ts`，1 个测试文件、3 个测试通过。

### 2026-06-06 Phase V2 远端现场验证与旧库兼容修复

状态：完成本轮修复和远端 smoke，待继续升级/迁移端到端验证

发现的问题：

- `10.20.11.3` 的 v2 工作目录已在 `feature/upgrade-v2`，但运行容器最初仍是旧入口：`uvicorn app.main:app`、`python -m app.collector...`。
- v2 镜像启动后，默认数据路径指向 `/data/smartx-storage-forecast/app/smartx.db`；当前 compose 将业务库目录挂载到容器 `/data`，真实业务库是 `/data/smartx.db`，导致 API 读到空库。
- 旧库中已有 `latest_vm_volumes` 和 `latest_vm_volume_items`，但 v2 新表 `vm_latest`、`vm_volumes` 初始为空，切到 v2 后 VM 页面和 Dashboard 容易空。
- Prometheus 当前 instant 查询为空时，`/api/vms` 只依赖 Prometheus 会返回 0 台 VM；但 SQLite 中有最新 VM 和卷数据，趋势 query_range 仍可查到历史点。
- 远端当前 compose 实际 project name 是 `smartx-storage-forecast`；使用不匹配的 project name 执行 `docker compose ps` 会显示空表。
- 现场库里存在历史导入残留的 tower_id 1/2/3 数据，而当前启用 Tower/集群只有 tower_id 3；默认 Dashboard、VM、报表必须按当前启用集群过滤，否则会显示旧残留 VM 和没有趋势的历史记录。

实施内容：

- `backend/app/v2/config.py` 支持 `SMARTX_DB_PATH` 和 `SMARTX_PROMETHEUS_DATA_PATH` 覆盖，compose 明确传入 `/data/smartx.db` 与 `/prometheus-data`。
- `docker-compose.yml`、`docker-compose.offline.yml`、`docker-compose.release.yml` 同步补齐 v2 数据路径环境变量。
- `backend/app/v2/database.py` 初始化时兼容旧 `latest_vm_volumes`，自动 backfill 到 `vm_latest` 和 `vm_volumes`。
- `backend/app/v2/api.py` 的 VM 趋势接口兼容前端使用的 `period_days` 参数。
- `backend/app/v2/dashboard/service.py` 返回 Tower 树，支持前端 scope 选择；Prometheus instant 为空时从 SQLite `vm_latest` 兜底 VM 概览，且不会把兜底数据误算为“本日新建 VM”。
- `backend/app/v2/vms/service.py` 在 Prometheus instant 为空时从 SQLite `vm_latest` 返回 VM 列表。
- `backend/app/v2/dashboard/service.py`、`backend/app/v2/vms/service.py`、`backend/app/v2/reports/service.py` 默认只统计当前启用集群下的数据；选择 Tower/集群时使用对应启用范围过滤。

验证：

- 远端 `10.20.11.3` 执行 `./pre_install.sh`，目录和 Prometheus 权限检查通过。
- 远端重建并启动 v2 compose 后，容器入口确认：`uvicorn app.v2.main:app`、`python -m app.v2.worker`、`python -m app.v2.upgrade.runner`。
- 远端受影响后端测试：`test_v2_foundation`、`test_v2_dashboard_vm`、`test_v2_dashboard_vm_api`、`test_v2_migration` 共 18 个测试通过。
- 远端完整 v2 后端测试曾扩展至 43 个测试并通过。
- 远端 smoke：登录成功；Dashboard 读取到 1 个 Tower、1 个集群；启用范围过滤修复后 Dashboard VM 数和 `/api/vms` 均为 177 台；Word/Excel 报表保存到 `/data/smartx-storage-forecast/exports/reports`；迁移导出任务成功并返回下载 URL；空间清理扫描返回可清理项；compose 五个容器均运行。
- 远端运行容器内复核：`backend.tests.test_v2_foundation`、`backend.tests.test_v2_dashboard_vm`、`backend.tests.test_v2_dashboard_vm_api`、`backend.tests.test_v2_migration` 共 18 个测试通过。
- 远端运行容器内复核：新增 orphan 指标/SQLite 残留过滤测试后，`backend.tests.test_v2_dashboard_vm`、`backend.tests.test_v2_reports` 共 6 个测试通过。

仍未完成：

- 真实“新增 Tower 并采集”未在本轮执行，避免覆盖现场已有 Tower 凭据和数据。
- 平台升级包、runner 组件包、Prometheus 组件包未实际执行。
- 迁出数据导入独立验证环境未执行。
- 日/月增长是否非空仍取决于 Prometheus 历史样本窗口和当前 scrape 状态，本轮只验证趋势、VM 列表、报表和迁移导出恢复。

### 2026-06-06 Phase V2 v0.5.0 / runner v0.3.0 版本治理与远端验证

状态：完成本轮版本治理、远端构建、运行 smoke 和升级包生成，待继续真实升级包执行

实施内容：

- 平台版本统一为 `v0.5.0`，根目录 `VERSION`、compose 默认平台 tag、README、部署文档、版本治理文档和测试断言同步更新。
- `upgrade-runner` 组件版本统一为 `v0.3.0`，根目录 `RUNNER_VERSION`、compose `SMARTX_RUNNER_IMAGE_TAG`、runner 组件包脚本和测试断言同步更新。
- 明确 `v0.5.0` 平台升级包只面向 v2 同架构后续升级；v1/v0.4.x 不走原地升级，只通过“新装 v2 + 数据迁移包导入”兼容。
- README 中升级包结构更新为 v2 manifest：`schema_version=2`、`components`、`project_files`、`scripts/migrate.sh`、`project/**`。
- 当前口径补充：Phase 22 后升级包规范已升级为 manifest schema 3，并使用 `minimum_runner_protocol`、`required_capabilities` 和 `checksums.sha256` 做能力与完整性校验；README 当前示例以 schema 3 为准。
- 三个后端 Dockerfile 增加 `PIP_DEFAULT_TIMEOUT=120` 和 `PIP_RETRIES=10`，缓解现场 pip 下载超时导致构建失败。
- 远端 `10.20.11.3` 已删除旧平台、runner 和 Prometheus 容器/镜像后重新构建 v2。

远端验证：

- `python3 scripts/build_upgrade_package.py --check-version --no-build` 通过，输出 `Version metadata OK: v0.5.0`。
- `docker compose build web-api collector-worker frontend upgrade-runner` 通过。
- 镜像内版本检查：`web-api` 与 `upgrade-runner` 均显示 `/app/VERSION=v0.5.0`、`/app/RUNNER_VERSION=v0.3.0`。
- 容器内测试通过：`backend.tests.test_deployment_config`、`backend.tests.test_v2_package_builders`、`backend.tests.test_v2_upgrade` 共 9 个测试通过。
- 容器内测试通过：`backend.tests.test_v2_dashboard_vm`、`backend.tests.test_v2_reports`、`backend.tests.test_v2_migration` 共 10 个测试通过。
- `bash pre_install.sh` 通过，确认 `/data/smartx-storage-forecast/upgrades`、`/data/smartx-storage-forecast/backups`、`/data/smartx-storage-forecast/exports`、`/data/smartx-storage-forecast/compose-runtime` 和 Prometheus 权限准备完成。
- `docker compose --project-name smartx-storage-forecast up -d` 启动五个容器成功。
- HTTP 验证通过：`/api/system/health` 返回 `version=v0.5.0`、`runner_version=v0.3.0`；`/api/admin/upgrade/version` 返回 `v0.5.0`；`/api/admin/component-upgrade/version` 返回 `v0.3.0`；前端 `8080` 返回 200；Prometheus `/-/healthy` 正常。
- 登录后接口验证通过：Dashboard、报表接口均返回数据；Dashboard 风险文案为 `当前所有集群暂无明显容量风险`。

升级包：

- 平台升级包：`/data/upgrade-packages/smartx-capacity-insight-upgrade-v0.5.0.tar.gz`，大小约 342 MB，SHA256 `6924766cb52a67b9562c2894300ec7eddd09d397b37ec79203c84c2b3e83a53b`。
- runner 组件包：`/data/upgrade-packages/components/smartx-upgrade-runner-v0.3.0.tar.gz`，大小约 81 MB，SHA256 `6c44e1d09a15573e06d15f247ea7ef438a6cf8a24d48e54cf5925dba7b57a748`。
- 平台包 manifest：`version=v0.5.0`、`min_version=v0.5.0`、`package_type=platform`、只包含 `web-api`、`collector-worker`、`frontend`，不包含 `images/upgrade-runner.tar`。
- runner 包 manifest：`version=v0.3.0`、`package_type=component`、只包含 `images/upgrade-runner.tar`。
- 两个包检查均未发现 `.env`、`smartx.db`、Prometheus 数据或凭据类内容。

注意：

- 使用 `docker compose run` 时必须显式 `--project-name smartx-storage-forecast`，否则目录名 `smartx-storage-forecast-v2` 会尝试创建同样 `10.249.249.0/24` 的网络并与正式网络冲突。
- 本轮没有执行真实平台升级包、runner 组件包和 Prometheus 组件包升级流程；这些仍保留为后续端到端验证项。

### 2026-06-06 Phase V2-7 真实平台升级与 runner 组件升级验证

状态：完成平台升级包和 runner 组件包真实执行验证，修复 runner-only 组件升级执行者问题

现场验证：

- 在 `10.20.11.3` 通过 API 上传并执行 `/data/upgrade-packages/smartx-capacity-insight-upgrade-v0.5.0.tar.gz`。
- 平台升级任务 `upgrade-9c1b8ce0fb6f7b47` 成功：
  - 生成升级前备份 `/data/smartx-storage-forecast/backups/upgrade-v0.5.0-before-20260606085950.tar.gz`。
  - 加载 `web-api`、`collector-worker`、`frontend` 三个 `v0.5.0` 镜像。
  - 同步项目文件并备份到 `/data/smartx-storage-forecast/backups/project-files-before-v0.5.0-20260606090010`。
  - 写入 `/data/smartx-storage-forecast/compose-runtime/docker-compose.upgrade.yml`。
  - 平台三件套重启后容器均运行，`/api/system/health` 返回 `version=v0.5.0`、`runner_version=v0.3.0`。
- 首次真实执行 runner 组件包 `/data/upgrade-packages/components/smartx-upgrade-runner-v0.3.0.tar.gz` 时发现现场问题：
  - 任务 `upgrade-aa714bd774e894a3` 完成备份、加载镜像和写 runner override 后停在 `restart running`。
  - Docker 状态显示旧 runner 退出，新 runner 容器一度只处于 Created，说明 runner 自己执行 `docker compose up -d --no-deps upgrade-runner` 会被自身重启打断。

修复内容：

- 新增 API 回归测试：runner-only 组件升级通过 `/api/admin/component-upgrade/start/{task_id}` 启动后不再返回 `pending + runner_requested`，而是由 web-api 直接执行。
- RED：远端容器内执行 `backend.tests.test_v2_upgrade.V2UpgradeApiTest.test_upgrade_api_requires_auth_uploads_and_prechecks_package`，新断言失败，实际返回 `pending`。
- GREEN：`backend/app/v2/api.py` 将组件升级 start 改为 `upgrade.start(..., submit_to_runner=False)`。
- 清理成功路径：`backend/app/v2/upgrade/service.py` 在任务成功时清空 `runner_resume_pending=False`，并将日志文案改为“升级服务已提交重启”。

修复后验证：

- 远端容器内同一 API 回归测试通过。
- 重建并重启远端 `web-api` 后，再次通过 API 执行 runner 组件包，任务 `upgrade-99f319a07635fcb1` 成功：
  - 生成备份 `/data/smartx-storage-forecast/backups/upgrade-v0.3.0-before-20260606091212.tar.gz`。
  - 加载 `nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.0`。
  - 写入 `/data/smartx-storage-forecast/compose-runtime/docker-compose.runner-upgrade.yml`。
  - runner 容器成功切换为 `nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.0` 并运行。

仍未完成：

- Prometheus 组件包真实执行和历史指标回归仍未跑。
- 新部署添加 Tower 并采集、v1 迁移包导入独立验证环境仍未跑。

补充验证产物：

- 修复后重新生成平台升级包：`/data/upgrade-packages/smartx-capacity-insight-upgrade-v0.5.0.tar.gz`，大小 `342339041` bytes，SHA256 `0958b9aa592ef528aabd489d1e979104d3878e1a0978a467d1a6735c96f195c5`。
- 修复后重新生成 runner 组件包：`/data/upgrade-packages/components/smartx-upgrade-runner-v0.3.0.tar.gz`，大小 `81373272` bytes，SHA256 `6567f7ec135b550e690ecc41bb468e45e798d37fdcb80f38b589532d5fb4c023`。
- 平台包 manifest 仍为 `version=v0.5.0`、components `platform`，不包含 `images/upgrade-runner.tar`。
- runner 组件包 manifest 仍为 `version=v0.3.0`、components `runner`，只包含 `images/upgrade-runner.tar`。
- 包内检查未发现 `.env`、`smartx.db`、Prometheus 历史数据或凭据；`project/prometheus/prometheus.yml` 是 Prometheus 配置文件，属于预期项目文件。

### 2026-06-06 Phase V2 前端版本断言与远端测试清理

状态：完成

发现与修复：

- 远端用 Docker `node:22-alpine` 跑 Vitest 时，`frontend/src` 内残留 macOS `._*` AppleDouble 文件导致 Vite 尝试解析二进制文件失败。
- `frontend/src/pages/ServicePage.test.tsx` 中平台状态测试仍断言旧包名 `smartx-capacity-insight-upgrade-v0.4.1`，已修正为 `v0.5.0`。

验证：

- 删除远端 `frontend/src/**/._*` 运行产物后，执行 `docker run --rm -v /data/smartx-storage-forecast/project/frontend:/app -w /app node:22-alpine npm test -- AppLayout.test.tsx DashboardPage.test.tsx global.test.ts ServicePage.test.tsx` 通过。
- 前端结果：4 个测试文件、20 个测试通过。

### 2026-06-06 Phase V2 Prometheus observability 组件包与真实升级验证

状态：完成

实施内容：

- 新增 `scripts/build_prometheus_component_package.py`，用于生成 Prometheus/observability 组件升级包。
- Prometheus 组件包 manifest 使用 `schema_version=2`，组件类型为 `observability`，服务只包含 `prometheus`，镜像只包含 `images/prometheus.tar`。
- 当前口径补充：Phase 22 后 Prometheus 组件包使用 schema 3；默认轻量包只包含 manifest、配置和健康检查，离线环境才通过 `--offline-image` 包含 `images/prometheus.tar`。
- 修复升级任务公开字段：`components=["observability"]` 时返回 `kind=component`、`component=prometheus`。
- 修复组件升级启动逻辑：只有 runner-only 包由 web-api 直接执行；Prometheus/observability 组件包提交给 upgrade-runner 执行。

TDD 记录：

- RED：新增 `test_prometheus_component_builder_emits_observability_manifest` 后，脚本不存在导致测试失败。
- GREEN：新增 Prometheus 组件包构建脚本，测试通过。
- RED：新增 API 断言后，Prometheus 组件包被错误返回为 `kind=platform`。
- GREEN：修复 `_public_task()` 分类和 component-upgrade start 执行者选择，远端容器内 API 测试通过。

远端验证：

- 在 `10.20.11.3` 生成真实组件包：`/data/upgrade-packages/components/smartx-prometheus-v2.55.1.tar.gz`。
- 包大小：`121243325` bytes。
- SHA256：`c01bd4d9753751b2e1e75acb7f171055c8740770c05c034f8a9cf43bd24801db`。
- 包结构检查：只包含 `manifest.json`、`release-notes.md`、`images/prometheus.tar`；不包含平台镜像或 runner 镜像。
- 当前口径补充：这是 2026-06-06 的历史包结构；当前 Prometheus 包还包含 `checksums.sha256`、`config/prometheus.yml` 和 `health/queries.json`，且默认不包含 `images/prometheus.tar`。
- 首次真实执行 Prometheus 组件包任务 `upgrade-8e38afe4ac520146` 成功，验证 Prometheus 重启后 healthy，历史 `query_range` 返回 175 条 series。
- 修复分类/执行者后，再次真实执行 Prometheus 组件包任务 `upgrade-91593ac4799312d2` 成功：
  - upload 返回 `kind=component`、`component=prometheus`、`components=["observability"]`。
  - start 返回 `pending` 且 `runner_requested=true`，由 upgrade-runner 执行。
  - 升级前备份：`/data/smartx-storage-forecast/backups/upgrade-v2.55.1-before-20260606093851.tar.gz`。
  - Prometheus 容器重启后 healthy。
  - `smartx_vm_storage_used_bytes` 最近 2 天 `query_range` 返回 175 条 series。

仍未完成：

- 新部署添加 Tower 并采集未执行，避免覆盖现场已有 Tower 凭据和采集状态。
- v1 迁移包导入独立验证环境仍未执行。

### 2026-06-06 Phase V2 数据迁移隔离回归与报表历史尾点回退

状态：完成一轮不影响正式数据的隔离迁移回归，并修复报表 instant 为空时的增长榜空白问题

发现：

- 在 `10.20.11.3` 使用最新迁移包 `/data/smartx-storage-forecast/exports/migrations/smartx-capacity-insight-migration-20260606075715-438dc55b.tar.gz` 导入隔离目录 `/data/v2-migration-verify`。
- 隔离导入结果：SQLite 中 `towers=1`、`clusters=1`、`vm_latest=523`、`vm_volumes=89530`；Prometheus 历史 block 为 `7` 个，迁移健康检查 `complete=true`。
- 隔离 Prometheus 直接查询历史 block：`smartx_vm_storage_used_bytes` 90 天窗口返回 `525` 条历史 series，最大样本时间为 `2026-06-06 13:07:52`。
- 单独只有历史 block、还没有当前 scrape 样本时，Prometheus 当前 instant 可能为空；旧报表逻辑依赖 instant 作为 VM 当前值，会导致日/月增长榜暂时为空。

修复：

- `backend/app/v2/reports/service.py` 中 VM 增长榜当前值优先使用 Prometheus instant；instant 为空或缺少部分 VM 时，用历史窗口每条 VM series 的最后一个样本回退。
- 集群总容量优先使用 `smartx_cluster_storage_total_bytes` instant；instant 为空时，用历史窗口尾点回退，避免预测报表缺少容量阈值。
- 新增 `backend/tests/test_v2_reports.py` 覆盖 Prometheus instant 为空但 range 有历史样本时，日增长、月增长和集群总容量仍可恢复。

验证：

- 本地 `python3 -m py_compile backend/app/v2/reports/service.py backend/tests/test_v2_reports.py` 通过。
- 远端容器内 `backend.tests.test_v2_reports backend.tests.test_v2_migration backend.tests.test_v2_dashboard_vm` 共 11 个测试通过。
- 远端隔离 Prometheus + 迁移目录验证：修复后报表返回 `clusters=1`、`cluster_points=15`、`day_growth=100`。
- 隔离包 `month_growth=0` 符合 v2 口径：该迁移包历史跨度约 15 天，不满足月增长榜固定 `>=30` 天样本跨度要求。

仍未完成：

- 新部署后添加 Tower 并真实采集的现场验证未执行，避免擅自修改现有 Tower 配置和凭据。

### 2026-06-06 Phase V2 真实 Tower 采集闭环与凭据兼容

状态：完成真实采集验证，修复 v1 Tower 凭据兼容和报表重复集群问题

发现：

- `10.20.11.3` 的 v2 环境已有启用 Tower `CHINATOWER` 和启用集群 `SMARTX-TT-WW`，但首次手动采集失败，提示 `Tower requires either an API token or username/password.`。
- 只读检查确认 Tower 用户名存在，但旧密码/API Token 无法被 v2 当前凭据格式解密。
- 根因是 v1/v0.4.x Tower 凭据使用 Fernet 加密，密钥种子来自 `SMARTX_CREDENTIAL_KEY` 或 `SMARTX_SECRET_KEY`；v2 第一版只支持新凭据格式。
- 用户重新录入 Tower 密码后，远端布尔检查显示 `password_decrypts=true`。
- 真实采集后发现报表里同一集群被拆成两条 series：历史指标带 `cluster/tower` label，新指标不带，Prometheus 按完整 label set 生成多条 series。

修复：

- `V2Settings` 增加 `credential_key`。
- `InventoryService.get_tower_secret_material()` 优先按 v2 格式解密；失败后按 v1 Fernet 格式兼容解密，密钥种子优先 `SMARTX_CREDENTIAL_KEY`，其次 `SMARTX_SECRET_KEY`。
- 新增 `backend/tests/test_v2_inventory_metrics.py` 覆盖 v1 Fernet 凭据可由 v2 读取。
- `ReportService.latest_report()` 按 `(tower_id, cluster_id)` 合并集群 series，避免旧 label 和新 label 导致同一集群重复显示。
- 新增 `backend/tests/test_v2_reports.py` 覆盖同集群多 label series 合并。

现场验证：

- 手动采集成功：`采集完成：1 个集群，172 台虚拟机。`
- collector-worker `/metrics` 有约 `27608` bytes，VM 指标行 `174`，集群 used 指标行 `3`。
- Prometheus target `smartx-collector` 状态 `up`，当前 VM instant 样本 `172` 条，最近 2 小时 series `172` 条。
- Dashboard：`towers=1`、`clusters=1`、`vms=177`、`day_growth=69`、采集状态 success。
- VM：列表 `172` 台，首个 VM 7 天趋势点 `146`。
- Report：`clusters=1`、`cluster_points=14`、`forecast_days=90`。

验证命令：

- 本地 `python3 -m py_compile backend/app/v2/config.py backend/app/v2/security.py backend/app/v2/inventory/service.py backend/app/v2/reports/service.py backend/tests/test_v2_inventory_metrics.py backend/tests/test_v2_reports.py` 通过。
- 本地 `git diff --check` 通过。
- 远端容器内后端组合测试 `backend.tests.test_v2_reports backend.tests.test_v2_inventory_metrics backend.tests.test_v2_collection backend.tests.test_v2_dashboard_vm backend.tests.test_v2_migration backend.tests.test_v2_upgrade backend.tests.test_v2_package_builders` 共 28 个测试通过。
- 远端前端关键测试 `AppLayout.test.tsx DashboardPage.test.tsx global.test.ts ServicePage.test.tsx` 共 20 个测试通过。
- 远端健康检查：`/api/system/health` 返回 ok，前端 8080 返回 200，Prometheus healthy。

### 2026-06-06 Phase V2 任务文档状态治理

状态：完成一轮 v2 任务文档对齐

发现：

- 根目录 `task_plan.md` 顶部仍保留 v1/dev 旧上下文：默认分支 `dev`、路径 `/data/smartx-storage-forecast/project`、基线 `v0.3.3U1` 和一批旧报表未提交变更。
- `docs/v2-rebuild-task-plan.md` 中 Phase V2-3 到 V2-9 的 checklist 已全部完成，但阶段状态仍写“进行中”或“待处理”。
- `docs/upgrade-issues.md` 和 `docs/functional-modules.md` 仍把 Prometheus 组件升级策略、全新升级模式、runner 自升级标为“设计待定/待处理”，与当前 v2 代码和远端真实验证不一致。

处理：

- `task_plan.md` 当前环境改为 v2 事实：`feature/upgrade-v2`、`/data/smartx-storage-forecast/project`、平台 `v0.5.0`、runner `v0.3.0`。
- `task_plan.md` 将 v1/dev 旧报表提交阶段标记为归档，不再作为当前 v2 待办。
- `task_plan.md` 将 Phase 12 全新升级模式和 Phase 13 数据迁移灾备标记为“完成第一版”，并补充当前证据和后续增强边界。
- `docs/v2-rebuild-task-plan.md` 将 Phase V2-3 到 V2-9 状态统一改为“完成第一版”。
- `docs/upgrade-issues.md` 将 Prometheus/observability 组件升级策略和 v2 全新升级模式标记为已解决第一版。
- `docs/functional-modules.md` 将升级模式、runner-only 组件升级和 Prometheus observability 组件升级标记为已解决。

验证：

- 本轮是文档状态治理，没有修改代码。
- 已计划执行 `git diff --check` 和状态检查后提交。

### 2026-06-06 Phase V2-15 首页容量风险 API 第一版

状态：完成 Dashboard 容量风险结构增强

目标：

- 首页打开后能一眼看到容量风险。
- 风险判断必须以单集群为准：任一集群使用率 `>=80%` 即高风险，不被整体平均容量掩盖。
- API 返回足够结构化的信息，前端风险卡片和风险提示不再只依赖前端兜底文案。

TDD 记录：

- RED：在 `backend/tests/test_v2_dashboard_vm.py` 增加断言，要求 `capacity_risk` 返回 `title`、`danger_count`、`warning_count` 和 `top_clusters`；远端容器内测试因缺少 `title` 失败。
- GREEN：`DashboardService._capacity_risk()` 返回完整结构：`level/title/message/description/cluster_count/warning_count/danger_count/top_clusters`。

验证：

- 远端容器内单测 `backend.tests.test_v2_dashboard_vm.V2DashboardVmTest.test_dashboard_summary_uses_single_cluster_risk_and_latest_vm_names` 通过。
- 远端容器内 `backend.tests.test_v2_dashboard_vm` 共 5 个测试通过。
- 远端临时 Node 容器内 `DashboardPage.test.tsx` 共 4 个测试通过。
- 本地 `python3 -m py_compile backend/app/v2/dashboard/service.py backend/tests/test_v2_dashboard_vm.py` 通过。
- 本地 `git diff --check` 通过。
- 在 `10.20.11.3` 重建并重启 `web-api` 后，真实 `/api/dashboard/summary` 返回完整容量风险字段：`level/title/description/cluster_count/warning_count/danger_count`，且 `top_clusters=1`。

### 2026-06-06 Phase V2-14 报表容量风险摘要

状态：完成 Word/Excel 首页容量风险摘要第一版

目标：

- 报表不只导出数据表，还要在首页把客户最关心的容量风险前置展示。
- 风险摘要复用集群当前容量/总容量口径，任一集群达到阈值即可提示。

TDD 记录：

- RED：扩展 `backend/tests/test_v2_report_exports.py`，要求 Word XML 和 Excel 汇总页包含“容量风险摘要”以及 `Cluster A 使用率超过 80%`。
- GREEN：`backend/app/v2/reports/export.py` 在 Word 首页基础信息表和 Excel `汇总` sheet 增加“容量风险摘要”。
- 测试样例调整为 Cluster A 当前容量 `810/1000`，确保测试真实覆盖高风险路径。

验证：

- 远端容器内 `backend.tests.test_v2_report_exports.V2ReportExportApiTest.test_report_exports_require_auth_save_files_and_expose_download_link` 通过。
- Excel 断言改为 `openpyxl.load_workbook` 读取汇总页单元格，避免依赖 `sharedStrings.xml` 是否存在。

### 2026-06-06 Phase V2-16 项目架构总览

状态：完成项目架构总览文档第一版

目标：

- 给 v2 重建后项目提供一个统一架构入口，方便后续接手、排障和继续开发。
- 把容器职责、数据职责、任务模型、升级包结构、迁移包结构和安全边界集中记录，避免只散落在多个细节文档里。

处理：

- 新增 `docs/architecture.md`。
- 文档记录 5 容器交付形态：`frontend`、`web-api`、`collector-worker`、`prometheus`、`upgrade-runner`。
- 文档记录后端模块边界、SQLite/Prometheus/`/data` 职责、任务模型、升级包结构、迁移包结构、安全边界和当前版本边界。
- `task_plan.md` 将 Phase 16 标记为完成第一版。
- `docs/v2-rebuild-task-plan.md` 补充 `docs/architecture.md` 作为架构总览交付物。

验证：

- 本轮为文档架构整理，无代码改动。

### 2026-06-06 Phase V2-17 远端完整回归与测试隔离修复

状态：完成 v2 第一版远端回归验证

目标：

- 继续完成 `feature/upgrade-v2` 受控重建收口。
- 在 `10.20.11.3` 重新验证远端 v2 分支、容器状态、后端测试、前端测试和健康检查。
- 修复回归过程中发现的测试隔离和旧 schema 兼容问题。

发现：

- 远端 `test_v2_cleanup` 的 API 测试调用 `/api/admin/system/restart` 时没有 mock 系统重启服务，在带 Docker socket 的容器里会真实执行 `docker compose up -d`，导致在线验证环境容器被重建。
- 远端容器环境包含 `SMARTX_DB_PATH=/data/smartx.db`。部分 API 测试只设置 `SMARTX_DATA_ROOT`，仍会被 `SMARTX_DB_PATH` 覆盖到真实业务库，导致采集记录测试读到现场历史记录。
- 旧库如果已存在 `users` 表但缺少 `updated_at` 列，修改密码会执行 `UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP ...` 并报 `sqlite3.OperationalError: no such column: updated_at`。

修复：

- `backend/tests/test_v2_cleanup.py` 使用 FastAPI `dependency_overrides` 替换 `get_system_control_service`，重启接口测试改为 fake service，不再真实执行 Docker 重启。
- `backend/app/v2/config.py` 在 `SMARTX_DATA_ROOT` 被显式改为非 `/data` 且 `SMARTX_DB_PATH` 仍为 compose 默认 `/data/smartx.db` 时，忽略该默认 DB path，避免测试或临时实例污染真实库。
- `backend/app/v2/database.py` 初始化时为旧 `users` schema 补 `updated_at` 列，并回填当前时间；新建 schema 仍保留原来的 `DEFAULT CURRENT_TIMESTAMP`。
- `backend/tests/test_v2_foundation.py` 增加上述两个回归测试。

验证：

- 本地目标测试 `backend.tests.test_v2_foundation.V2FoundationTest.test_settings_ignore_default_compose_db_path_when_data_root_is_overridden`、`test_database_adds_users_updated_at_for_existing_schema`、`test_settings_respect_compose_mounted_data_paths` 通过。
- 本地 `python3 -m py_compile backend/app/v2/config.py backend/app/v2/database.py backend/tests/test_v2_foundation.py backend/tests/test_v2_cleanup.py` 通过。
- `10.20.11.3` 受影响后端组合测试 `backend.tests.test_v2_auth_api backend.tests.test_v2_collection_runs_api backend.tests.test_v2_cleanup backend.tests.test_v2_foundation` 共 16 个通过。
- `10.20.11.3` 完整 v2 后端测试 `test_v2_*` 共 65 个通过。
- `10.20.11.3` 前端关键测试 `AppLayout.test.tsx DashboardPage.test.tsx global.test.ts ServicePage.test.tsx` 共 20 个通过。
- `10.20.11.3` 健康检查：`/api/system/health` 返回 `version=v0.5.0`、`runner_version=v0.3.0`，前端 `8080` 返回 `200`，Prometheus `/-/healthy` 返回 healthy。

注意：

- 旧 v1 测试和非 v2 测试中仍有会操作 Docker 或依赖旧服务的用例，不适合作为远端在线环境全量回归命令。当前 v2 远端回归以 `backend/tests/test_v2_*.py` 为准。

### 2026-06-06 升级问题台账 v2 口径收口

状态：完成文档口径治理

发现：

- `docs/upgrade-issues.md` 仍保留多处 v1/v0.4 或 runner v0.2.x 时代的“待验证、待完整回归、v0.4.0 升级包、v0.2.2 基线”描述。
- `docs/v2-upgrade-center-design.md` 仍写着 web-api 不直接执行复杂 Docker 升级动作，但真实 v2 方案已经根据 runner-only 自升级断链问题调整为：runner-only 组件升级由 web-api 直接执行，平台和 Prometheus/observability 升级继续交给 upgrade-runner。

处理：

- `docs/upgrade-issues.md` 更新时间改为 2026-06-06。
- 将 UPG-001、UPG-002、UPG-003、UPG-004、UPG-005、UPG-006、UPG-007、UPG-008、UPG-009、UPG-011、UPG-014、UPG-015、UPG-019 的状态描述对齐到 v2 当前事实。
- 补充 `10.20.11.3` 已真实执行平台升级包、runner 组件包和 Prometheus/observability 组件包的验证记录。
- `docs/v2-upgrade-center-design.md` 明确 runner-only 组件升级由 web-api 直接执行，平台升级和 Prometheus/observability 升级由 upgrade-runner 执行。

验证：

- 本轮只修改文档。

### 2026-06-07 v2 任务中心通知与配置迁移决策记录

状态：文档已记录，代码待实施

处理：

- 用户确认数据迁移优先采用“配置迁移包”方案。
- 配置迁移包只迁移 SQLite 中的 `towers` 和 `clusters`，用于新机器快速恢复 Tower 纳管关系。
- 完整迁移包继续用于无缝搬家，保留 SQLite 必要数据和 Prometheus 历史指标。
- 暂不拆分 SQLite 双 DB；`config.db + runtime.db` 作为后续低优先级架构治理项。
- 用户确认任务中心需要 `info`、`warning`、`critical` 三类通知。
- 任务中心角标应代表未处理通知数量，不代表 pending/running 任务数量。
- 告警和严重告警需要确认或删除后才消除角标；一键清空只清除已读信息和已确认告警。

修改文件：

- `task_plan.md`
- `findings.md`
- `docs/v2-rebuild-task-plan.md`
- `progress.md`

验证：

- `git diff --check` 通过。
- `git status --short` 确认本轮只包含文档变更。
- 敏感词扫描未发现新增真实密码、token 或私钥；命中项均为通用字段说明或历史文档规则。
- `rg` 检查当前任务文档和升级台账不再保留未收口的 v2 待验证项；剩余 v0.2.x/v0.4.0 文本仅作为历史现象或历史验证记录保留。

### 2026-06-07 Phase 18 任务中心状态机与残留任务清理

状态：完成第一版并已部署到 `10.20.11.3`

问题：

- 任务中心出现多条 `执行系统升级`，进度 1%，点 X 后显示“升级任务不存在”或“已从等待队列移除”，但点“清空”后又恢复。
- 用户要求：清空只能清成功完成任务；异常/失败任务不能被清空，需要手动点 X 消除。
- 用户最后明确要求“直接清理掉”现场残留任务。

根因：

- 前端开始升级时曾使用 `upgrade-start-*` 临时 id 创建任务中心记录，取消接口需要真实后端升级 `task_id`，因此取消会找不到升级任务。
- SQLite `tasks` 表中残留了大量 `pending` 升级任务，但对应 `/data/smartx-storage-forecast/upgrades/<task_id>/task.json` 已不存在；`/api/tasks` 会继续返回这些记录，而“清空”不会删除 pending。
- 前端任务合并逻辑曾让本地 active 状态压过后端完成态，导致完成任务可能继续显示执行中。

代码修复：

- `backend/app/v2/upgrade/service.py`
  - `cancel()` 支持 task.json 缺失时回退读取 SQLite `tasks` pending 记录，把孤儿升级任务标记为 `cancelled`。
- `backend/app/v2/tasks/service.py`
  - `clear_finished()` 改为只删除 `success`。
  - 新增 `delete_inactive()`，仅允许删除非 `pending/running` 任务。
- `backend/app/v2/api.py`
  - 新增 `DELETE /api/tasks/{task_id}` 手动移除非 active 任务。
- `frontend/src/App.tsx`
  - `clearTasks()` 只移除 `succeeded`。
  - 新增任务 X 处理逻辑：pending 升级走取消；failed/cancelled 走手动删除。
  - `addTask()` 改为同 id upsert。
  - `mergeTasks()` 允许后端完成态覆盖本地 active。
- `frontend/src/pages/ServicePage.tsx`
  - `startUpgrade()` / `startComponentUpgrade()` 使用真实 `task_id` 创建任务中心任务。
- `frontend/src/components/AppLayout.tsx`
  - failed/cancelled 显示“从任务中心移除”的 X。
  - pending 的系统/组件升级显示“取消等待任务”的 X。

测试：

- 本地通过：
  - `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_upgrade.V2UpgradeServiceTest.test_cancel_orphaned_pending_upgrade_task_marks_task_cancelled backend.tests.test_v2_upgrade.V2UpgradeServiceTest.test_cancel_pending_upgrade_prevents_runner_execution_and_marks_task_cancelled`
  - `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_tasks_api.V2TaskServiceTest.test_task_service_persists_lists_updates_and_clears_finished_tasks`
  - `python3 -m py_compile backend/app/v2/upgrade/service.py backend/app/v2/tasks/service.py backend/app/v2/api.py`
- 远端 `10.20.11.3` 通过：
  - 后端目标测试 2 个通过。
  - 前端 `AppLayout.test.tsx ServicePage.test.tsx` 17 个测试通过。
  - 前端 build 通过。
  - 重建并启动 `web-api`、`frontend` 后，`/api/system/health=200`、`8080=200`。

现场清理：

- 在 `10.20.11.3` 的 `web-api` 容器内连接 `/data/smartx.db`。
- 清理前 `tasks` 表 19 条记录，大部分为 `pending` 的 `执行系统升级` 且 `task.json` 已缺失。
- 用户明确要求直接清理后，执行 `DELETE FROM tasks`。
- 清理后确认 `tasks_count=0`。

注意：

- 本次直接清理只删除任务中心记录，未删除业务库数据、升级包目录、Prometheus 历史指标或备份。
- 后续如果用户没有明确要求，不要直接 `DELETE FROM tasks`；优先使用页面 X 或 API。

### 2026-06-07 Phase 19 数据迁移进度、SQLite 瘦身与升级文档增强

状态：完成第一版并已在 `10.20.11.3` 验证

目标：

- 执行 v2 待办 3、5、4，顺序为数据迁移大数据量进度优化、SQLite/虚拟卷存储结构瘦身、升级中心 v2 后续增强文档补齐。

实现：

- 数据迁移导入新增后台任务接口：
  - `POST /api/admin/migration/import/start`
  - `GET /api/admin/migration/import/status/{task_id}`
  - 前端数据迁移页默认使用后台任务，任务中心展示上传保存、解压校验、导入前备份、SQLite 导入、Prometheus 历史指标导入、健康检查。
- 数据迁移导出继续使用后台任务，并保留扫描、打包、保存、下载链接和服务器留档路径。
- 迁入上传包保存到 `/data/smartx-storage-forecast/exports/imports/<task_id>/`。
- 导入前备份保存到 `/data/smartx-storage-forecast/backups/import-before-*.tar.gz`，备份成功后才继续写入业务库和 Prometheus 历史 block。
- 导入健康检查返回 SQLite 表计数、数据库大小和 Prometheus block 摘要。
- v2 正式数据源只使用 `vm_volumes`：
  - 初始化旧库时从 `latest_vm_volumes.payload_json` 抽取必要字段写入 `vm_volumes`。
  - 抽取完成后删除旧 `latest_vm_volumes` 表。
  - `schema_migrations` 记录 `drop_legacy_latest_vm_volumes`。
  - 覆盖导入旧库后也会执行 v2 初始化迁移。
- 空间清理新增 SQLite 空间整理：
  - `GET /api/admin/system/sqlite-vacuum/scan`
  - `POST /api/admin/system/sqlite-vacuum`
  - 执行前备份 `smartx.db` 到 `/data/smartx-storage-forecast/backups/sqlite-before-vacuum-*.db`。
- 升级中心文档增强：
  - `docs/v2-upgrade-center-design.md` 补充 manifest 组件声明、执行边界、组合升级顺序、Prometheus 历史指标回归、失败恢复和 v2 兼容边界。
  - `docs/v2-api-contracts.md` 补充迁移后台任务和 SQLite VACUUM API。
  - `docs/v1-data-compatibility.md` 补充旧 VM 卷 payload 抽取后删除规则。

本地验证：

- `python3 -m py_compile backend/app/v2/migration/service.py backend/app/v2/database.py backend/app/v2/cleanup/service.py backend/app/v2/api.py` 通过。
- 本地 `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_migration backend.tests.test_v2_foundation backend.tests.test_v2_cleanup` 因本机不安装依赖，仍停在缺少 `fastapi/httpx`，需在 `10.20.11.3` 容器内完成完整验证。

远端验证：

- `10.20.11.3:/data/smartx-storage-forecast/project` 后端容器内测试通过：
  - `backend.tests.test_v2_migration`
  - `backend.tests.test_v2_foundation`
  - `backend.tests.test_v2_cleanup`
  - 共 22 个测试通过。
- 远端 `node:22-alpine` 容器内前端测试通过：
  - `ServicePage.test.tsx` 共 10 个测试通过。
- 远端 `docker compose --project-name smartx-storage-forecast build web-api frontend` 通过。
- 重建 `web-api` 和 `frontend` 后：
  - `/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
  - `8080` 返回 `HTTP/1.1 200 OK`。
  - Prometheus `/-/healthy` 返回 healthy。
- API 轻量真实验证通过：
  - 迁移导出后台任务 `status=succeeded`、`progress=100`，且返回下载链接。
  - SQLite VACUUM scan 返回 `size=141012992`、`estimated_reclaimable=67407872`。
  - 迁移健康检查返回“业务库和 Prometheus 历史指标完整”，Prometheus block 数 `9`，SQLite 表数 `13`。

注意：

- 本轮真实验证只执行 SQLite VACUUM 扫描，没有执行真实 VACUUM，避免无必要改动现场业务库；VACUUM 代码路径已由后端单测覆盖备份后整理。

### 2026-06-07 v2 升级包类型文档补齐

状态：文档完成

处理：

- `docs/v2-upgrade-center-design.md` 将升级包结构拆分为三类：
  - 平台升级包：`web-api`、`collector-worker`、`frontend`，执行者为 `upgrade-runner`。
  - 升级中心组件包：`upgrade-runner`，执行者为 `web-api`。
  - 观测组件包：Prometheus，执行者为 `upgrade-runner`。
- 文档分别写明三类包的树形目录、是否允许 `project/`、是否需要迁移脚本、版本独立性和执行流程。

验证：

- 本轮只修改文档。

### 2026-06-07 任务中心通知与配置迁移实现

状态：完成第一版并已在 `10.20.11.3` 验证

实现：

- 任务中心通知状态持久化到 SQLite `tasks` 表：新增 `severity`、`seen_at`、`acknowledged_at`。
- 后端任务返回 `severity`、`unhandled`、`clearable`，并新增：
  - `POST /api/tasks/seen`
  - `POST /api/tasks/{task_id}/ack`
  - `DELETE /api/tasks/clearable`
- 前端任务角标改为未处理通知数量，不再统计 running/pending。
- 信息类成功任务打开任务中心并点击空白关闭后标记已读。
- 告警/严重告警失败任务显示“确认”按钮，确认或 X 删除后才清除角标。
- 一键清空只清理已读信息任务和已确认告警/严重告警任务。
- 新增配置迁移包：
  - `GET /api/admin/migration/config/export`
  - 包名 `smartx-config-migration-YYYYMMDDHHMMSS-*.tar.gz`
  - manifest 标记 `migration_scope=config`
  - 包内只包含 `towers/clusters` 的轻量 SQLite，不包含 Prometheus 历史指标。
- 数据迁移导入自动识别 `config` 与 `full` 包；配置导入前仍生成备份，只 merge `towers/clusters`。
- 前端数据迁移页新增“导出配置迁移包”，与完整“导出迁移包”区分。

验证：

- `10.20.11.3` 后端容器内通过：
  - `backend.tests.test_v2_tasks_api`
  - `backend.tests.test_v2_migration`
  - 共 11 个测试通过。
- `10.20.11.3` Node 容器内通过：
  - `AppLayout.test.tsx`
  - `ServicePage.test.tsx`
  - 共 22 个测试通过。
- `10.20.11.3` 完成 `docker compose --project-name smartx-storage-forecast build web-api frontend`。
- `10.20.11.3` 完成 `web-api/frontend` recreate。
- 远端健康检查通过：
  - `/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
  - `8080` 返回 `HTTP/1.1 200 OK`。

注意：

- 配置迁移包适合新机器快速恢复 Tower 纳管和集群配置；不保留趋势、日增长、月增长和预测历史。
- 需要保留历史趋势和预测时继续使用完整迁移包，完整迁移包仍包含 SQLite 业务库和 Prometheus 历史 block。

### 2026-06-07 Phase V2-15.3 首页风险链路增强

状态：完成并通过目标测试

实现：

- Dashboard API `capacity_risk.top_clusters[]` 增加 `top_growth_vms`，复用已有日增长最快 VM 结果，不新增 Prometheus 查询。
- 每个风险或关注集群最多返回 3 台主要增长 VM，字段包含 `tower_id`、`cluster_id`、`vm_id`、`vm_name`、`current_bytes`、`growth_amount`、`growth_ratio`。
- 首页顶部“容量风险”小卡行为保持不变，继续跳转风险集群报表。
- 首页底部“风险提示”从单个大按钮改为信息面板，展示风险摘要、查看风险报表入口和主要增长 VM。
- 点击主要增长 VM 行复用 `onSelectVm(vm_id, vm_name)`，直接进入虚拟机页面。
- 风险集群无增长 VM 时显示 `风险集群暂无明显 VM 增长来源`。

验证：

- 本地通过 `python3 -m py_compile backend/app/v2/dashboard/service.py backend/tests/test_v2_dashboard_vm.py`。
- 本地通过 `git diff --check`。
- `10.20.11.3` 后端容器内通过 `backend.tests.test_v2_dashboard_vm`，共 6 个测试通过。
- `10.20.11.3` Node 容器内通过 `DashboardPage.test.tsx`，共 9 个测试通过。

### 2026-06-08 Phase 14 Word 报表产品化优化

状态：完成并已在 `10.20.11.3` 验证

实现：

- v2 Word 导出继续使用 v2 `latest_report()` 数据口径和现有导出 API，不回退 v1 查询逻辑。
- Word 报表恢复接近 v1 的客户交付版式：封面品牌条、英文副标题、蓝色分隔线、报告说明卡片、页眉页脚、目录表格和集群书签。
- 参考客户版模板补充执行摘要、关键发现、容量风险评估矩阵和短/中/长期运维建议。
- Word 表格不再沿用旧红底高风险行风格，改为直接参考客户版模板：深蓝表头、浅色摘要/斑马纹、增长量蓝色、增长率橙/红色。
- 保留 v2 生成的趋势图、Top 10 VM 增长图、TOP100 数据口径，并在摘要和集群汇总/章节中增加虚拟机数量。
- 运维建议不依赖 AI 服务，使用本地规则模板生成：按集群使用率、预计耗尽天数、Top 增长 VM、单 VM 容量和增长率输出确定性建议。
- 报告摘要增加 v1 风格 KPI 卡片，并前置“容量风险摘要”，正常/高风险文案按当前集群容量口径生成。
- 集群章节保留客户化 KPI 网格、风险建议、容量趋势图、Top 10 VM 增长量图、增长量 TOP100 和增长率 TOP100。
- 月增长为空时继续展示日增长数据和明确空状态文案，避免 Word 看起来像导出失败。
- Word VM 表格排序列使用箭头标识：`增长量 ↓`、`增长率 ↓`。
- 集群章节 TOP100 候选改为合并“本次统计窗口增长 VM”和“月增长 VM”，按 `tower_id + cluster_id + vm_id` 去重，避免 7/14/30 天导出时 TOP100 不全。
- Word 目录补充小标题，包含报告摘要、集群容量增长概览、本次统计窗口增长 VM、每个集群的 Top 10 VM 增长量、增长量 TOP100 和增长率 TOP100。

验证：

- 本地通过 `python3 -m py_compile backend/app/v2/reports/export.py backend/tests/test_v2_report_exports.py`。
- 本地通过 `git diff --check`。
- `10.20.11.3` 后端容器内通过 `backend.tests.test_v2_report_exports`，共 8 个测试通过。
- `10.20.11.3` 完成 `docker compose --project-name smartx-storage-forecast build web-api` 和 `web-api` recreate。
- `10.20.11.3` `/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 真实调用 `/api/reports/export/bundle?period_days=30` 成功，任务中心只生成 1 个“导出预测报表”任务，links 为 `Word`、`Excel`。
- 抽取生成的 Word XML，确认包含客户模板色值 `1A3C6E` / `F0F4FA` / `007ACC`、`Storage Capacity Forecast Report`、`执行摘要`、`报告摘要`、`关键发现`、`风险评估与建议`、`容量风险评估矩阵`、`短期（本月）`、`中期（1-3 个月）`、`长期（3 个月以上）`、`增长量 TOP100 虚拟机` 和 `增长率 TOP100 虚拟机`；旧版曾包含 `SmartX 超融合平台`，二次优化后已要求移除该官方平台表述。
- 抽取生成的 Word 包含 `word/media/*` 4 个图表资源，确认 v2 图表仍保留。

### 2026-06-08 Phase 14 Word 客户版模板二次优化

状态：完成并已在 `10.20.11.3` 验证

实现：

- 封面品牌名统一为 `存储容量预测平台`，不再使用 `SmartX 超融合平台` 作为项目名。
- DOCX 字体统一使用开源 `Noto Serif` / `Noto Serif CJK SC`，不依赖 `微软雅黑` / `Microsoft YaHei`。
- 封面元信息改为 `Tower范围`、`集群范围`；单 Tower/集群显示具体名称，多 Tower/多集群显示 `全部 Tower（N 个）`、`全部集群（N 个）`。
- 统计窗口改为选择窗口与实际采集窗口的交集；选择窗口超过采集历史时，Word 显示实际样本窗口。
- 关键发现和运维建议改为 run 级重点强调：VM 名称、Tower/集群、容量值、增长值、百分比和天数前后保留空格，并加粗放大。
- `2.2` 容量增长趋势表新增 `Tower` 列，避免多 Tower 场景只显示集群名。
- `2.3` 容量使用率可视化改为 Top 10 集群容量使用率图表说明和图表，风格向 Top 10 VM 增长图靠齐；图表生成失败时仍保留明确说明。

本地验证：

- `python3 -m py_compile backend/app/v2/reports/export.py backend/tests/test_v2_report_exports.py` 通过。
- `PYTHONPATH=backend /Users/nazawsze/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest backend.tests.test_v2_report_exports` 通过，8 个测试中 2 个按原条件跳过。
- `git diff --check` 通过。

远端验证：

- `10.20.11.3:/data/smartx-storage-forecast/project` 已同步本轮修改并重建 `web-api`。
- `docker compose --project-name smartx-storage-forecast build web-api` 通过，随后 `web-api` recreate 成功。
- `/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 容器内 `PYTHONPATH=backend python -m unittest backend.tests.test_v2_report_exports` 通过，共 8 个测试。
- 发现并修复图表字体细节：DOCX 正文使用 `Noto Serif CJK SC`；matplotlib 对保留的 `NotoSerifCJK-Regular.ttc` 识别为 `Noto Serif CJK JP`，因此图表字体使用同一个开源 TTC 的 `Noto Serif CJK JP` family，避免中文图表掉字。
- 真实数据导出 14 天和 365 天 Word 均成功；选择窗口超过采集历史时，两个文件都显示实际样本窗口 `2026-05-25 - 2026-06-08`。
- 已用 Documents 渲染工具把真实 Word 渲染为 PNG 检查：封面、执行摘要、2.2、2.3、5.2 页面无明显空白或错位；2.2 包含 Tower 列，2.3 为 Top 10 集群容量使用率图表，5.2 重点值加粗放大。
- 抽取 14 天和 365 天 Word XML 确认：包含 `存储容量预测平台`、`Tower范围`、`集群范围`、`Top 10 集群容量使用率`；不包含 `SmartX 超融合平台`、`微软雅黑`、`Microsoft YaHei`；包内均包含 3 个图表媒体资源。

### 2026-06-08 预计存储耗尽算法增强待办

状态：已记录，代码待实施

结论：

- 当前预计存储耗尽基于最近窗口的线性趋势：`(总容量 - 当前已用) / slope_per_day`。
- 如果某天发生一次性大数据量写入，线性趋势会被拉陡，第二天预计耗尽天数可能突然变短。
- 已在 Phase 15 后续增强中新增待办：后续需要区分长期趋势预测和单日大数据量冲击，建议展示 30/90 天平滑趋势、近 24 小时异常增长提示，以及排除单日突增后的稳健预测口径。

### 2026-06-08 Word 客户版模板细节纠正

状态：完成并已在 `10.20.11.3` 验证

实现：

- 封面在 `Tower范围` 上方新增空白 `客户名称` 字段，避免把 Tower 名称误当客户名称。
- 关键发现和运维建议的重点强调规则调整：VM 名称前后只加 1 个空格并加粗放大；容量、增长量、百分比和天数只加粗放大，不额外插入左右空格。
- 风险矩阵去掉 `单 VM 容量异常`，改为更中性的 `重点 VM 容量`。

本地验证：

- `python3 -m py_compile backend/app/v2/reports/export.py backend/tests/test_v2_report_exports.py` 通过。
- `PYTHONPATH=backend /Users/nazawsze/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest backend.tests.test_v2_report_exports` 通过，8 个测试中 2 个按原条件跳过。
- `git diff --check` 通过。

远端验证：

- `10.20.11.3:/data/smartx-storage-forecast/project` 已同步本轮修改。
- 容器内 `PYTHONPATH=backend python -m unittest backend.tests.test_v2_report_exports` 通过，共 8 个测试。
- 已重建并 recreate `web-api`，`/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 真实数据导出 14 天和 365 天 Word 均成功，统计窗口显示实际样本窗口 `2026-05-22 - 2026-06-08`。
- 抽取真实 Word XML 确认：包含 `客户名称`、`重点 VM 容量`、`存储容量预测平台`；不包含 `单 VM 容量异常`、`SmartX 超融合平台`；容量值/增长值没有左右双空格。
- 已用 Documents 渲染工具检查 14 天 Word：封面客户名称为空且位于 `Tower范围` 上方；风险矩阵和运维建议页无明显错位，VM 名称加粗放大并有单空格视觉分隔，数据值只加粗放大。

### 2026-06-08 Word 客户版增长口径与范围信息修正

状态：完成并已在 `10.20.11.3` 验证

实现：

- 执行摘要和 KPI 卡片不再使用 `较上月增长`，改为 `统计窗口增长`，并显示实际统计窗口。
- `2.2 容量增长趋势` 表头改为 `统计窗口增长`、`近 90 天样本增长`、`近 365 天样本增长`、`90 天预测`，避免把短采集窗口误读为自然月/季度/年度环比。
- `2.1 范围基本信息` 增加 `Tower范围`、`Tower数量`，多 Tower/多集群时显示聚合范围摘要。
- 执行摘要、关键发现和运维建议正文中的 Tower/集群名称加粗放大。

本地验证：

- `python3 -m py_compile backend/app/v2/reports/export.py backend/tests/test_v2_report_exports.py` 通过。
- `PYTHONPATH=backend /Users/nazawsze/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest backend.tests.test_v2_report_exports` 通过，9 个测试中 2 个按原条件跳过。
- `git diff --check` 通过。

远端验证：

- `10.20.11.3:/data/smartx-storage-forecast/project` 已同步本轮修改。
- 容器内 `PYTHONPATH=backend python -m unittest backend.tests.test_v2_report_exports` 通过，共 9 个测试。
- 已重建并 recreate `web-api`，`/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 真实数据导出 14 天和 365 天 Word 均成功，统计窗口显示实际样本窗口 `2026-05-22 - 2026-06-08`。
- 抽取真实 Word XML 确认：包含 `统计窗口增长`、`近 90 天样本增长`、`近 365 天样本增长`、`Tower数量`；不包含 `较上月`、`较上季度`、`较上一年`。
- 已用 Documents 渲染工具检查 14 天 Word：执行摘要 KPI 显示 `统计窗口增长` 并附实际窗口，`2.1` 范围基本信息包含 Tower 范围/数量和集群范围/数量，`2.2` 表头改为统计窗口与近 90/365 天口径。

### 2026-06-08 Word 客户版自查与预测 current 修复

状态：完成并已在 `10.20.11.3` 验证

自查结论：

- 14 天真实导出显示统计窗口 `2026-05-25 - 2026-06-08`，符合选择 14 天窗口。
- 365 天真实导出显示统计窗口 `2026-05-22 - 2026-06-08`，符合“选择窗口超过采集历史时，以实际采集窗口为准”。
- 封面和执行摘要中的 `Tower范围`、`集群范围` 与真实数据一致；多 Tower/多集群逻辑继续使用聚合范围摘要。
- 真实 Word XML 不包含 `较上月`、`较上季度`、`较上一年`、`SmartX 超融合平台`。

发现并修复：

- `forecast_series()` 原先用去离群后的最后一个点作为 `current`。当最新真实增长点被趋势过滤视为离群点时，365 天导出的 `当前已用容量` 和 `90 天容量` 会回退到旧值，出现“统计窗口增长有 1.39 TB，但 90 天预测仍等于当前容量”的不合理现象。
- 修复后 `current` 固定使用最新原始观测点；趋势斜率仍优先使用去离群样本，并在斜率为 0 但原始窗口存在正增长时使用原始窗口斜率兜底。
- `2.2 容量增长趋势` 表头进一步改为 `近 90 天样本增长`、`近 365 天样本增长`，并增加说明：采集历史不足 90/365 天时按可用样本窗口计算，避免刚部署环境误读。

验证：

- 本地 `py_compile` 通过。
- 本地 `backend.tests.test_v2_report_exports` 通过，9 个测试中 2 个按原条件跳过。
- 本地 `git diff --check` 通过。
- 远端容器内 `backend.tests.test_v2_reports backend.tests.test_v2_report_exports` 通过，共 15 个测试。
- 远端已重建并 recreate `web-api`，`/api/system/health` 返回 `ok=true`。
- 远端真实 365 天导出：`current=24507238580224.0`、`forecast_90d=32623814971151.06`、统计窗口 `2026-05-22 - 2026-06-08`；Word 文本显示 `90 天容量29.67 TB`、`统计窗口：2026-05-22 - 2026-06-08`。

### 2026-06-08 报表导出 6 种时间区间 Profile 化计划记录

状态：完成第一版，并已在 `10.20.11.3` 验证

结论：

- 用户提出导出报表有 `7/14/30/90/180/365` 六种时间区间，希望降低不同窗口下文案和口径出错概率。
- 对比后选择“1 套客户版渲染系统 + 6 个时间区间 Profile”，不做 6 份完整模板，也不做 6 套替换脚本。
- Profile 已统一驱动 Word 和 Excel 的窗口名称、增长指标标题、VM 榜单标题、样本不足说明和运维建议语气。
- 前端 6 个按钮和 API 入参 `period_days` 保持不变；后端新增内部 Profile 层完成。

实现：

- 新增 `ReportPeriodProfile` 和 `report_period_profile()`。
- 六个 Profile 固定为 `7/14/30/90/180/365`，分别对应短期突增、近两周、月度、季度、中长期和年度巡检语义。
- Word 客户版 KPI、关键发现、VM 增长章节、Top 10 VM 图表、集群增长表和运维建议短期标题均读取 Profile。
- Excel 汇总、`VM_TOP100_汇总` 和各集群 Sheet 均读取同一个 Profile。
- 选择窗口大于实际采集历史时，样本说明显示 `已按当前可用样本窗口计算`，统计窗口继续使用选择窗口与实际采集窗口的交集。

验证：

- 本地 `py_compile` 通过。
- 本地 `backend.tests.test_v2_report_exports` 通过，12 个测试中 2 个按原条件跳过。
- 本地 `git diff --check` 通过。
- 本地 `backend.tests.test_v2_reports` 因本机未安装 `httpx` 无法运行；按约束未在本机安装依赖，改在远端容器验证。
- `10.20.11.3` 容器内 `backend.tests.test_v2_report_exports backend.tests.test_v2_reports` 通过，共 18 个测试。
- `10.20.11.3` 已重建并 recreate `web-api`，`/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 真实数据导出 `7d/30d/365d` Word 和 Excel 均成功；三组文件都确认包含对应 Profile 标题和 VM 榜单标题。
- 真实 `365d` 导出在采集历史不足一年时，仍按实际数据窗口生成说明和统计窗口。

### 2026-06-09 Word 客户版封面标题与渲染细节修正

状态：完成并已在 `10.20.11.3` 验证

实现：

- Word 客户版封面标题改为 `SMARTX超融合存储容量分析报告`。
- 英文副标题改为 `SMARTX HCI Storage Capacity Analysis Report`。
- 旧标题 `存储容量预测分析报告` 和旧英文副标题 `Storage Capacity Forecast Report` 不再出现在 Word 正文 XML。
- 客户版封面适当减少空段落，降低封面后出现异常大空白的概率。
- 运维建议第三段标题从 `长期（3 个月以上）` 调整为 `三个月以上`，规避 LibreOffice 渲染时特定中文字符在蓝色加粗小标题中被裁切的问题；含义保持为三个月以上的长期治理建议。
- 运维建议分组标题统一使用轻量项目符号样式，和正文区分更清楚。
- VM Top 20 表格增加分页控制：标题和统计窗口跟随表格，表头跨页重复，数据行禁止跨页拆分。
- `3.2` 增长率 Top 20 表格前主动分页，避免出现表头留在上一页、数据行从下一页开始的断裂。

验证：

- 本地 `py_compile` 通过。
- 本地 `backend.tests.test_v2_report_exports` 通过，12 个测试中 2 个按原条件跳过。
- 本地 `git diff --check` 通过。
- `10.20.11.3` 容器内 `backend.tests.test_v2_report_exports backend.tests.test_v2_reports` 通过，共 18 个测试。
- `10.20.11.3` 已重建并 recreate `web-api`，`/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 真实数据导出 14 天 Word 成功，最新验证文件路径：`/data/smartx-storage-forecast/exports/reports/storage-forecast-all-20260609-113141-14d.docx`。
- 抽取真实 Word XML 确认：包含新封面标题和新英文副标题，不包含旧标题；统计窗口包含 `2026-05-26 - 2026-06-09`；包含 `三个月以上`。
- 抽取真实 Word XML 确认：包含 `w:tblHeader`、`w:cantSplit` 和分页符；不包含 `Hyperconverged`。
- 已用 Documents 渲染工具检查真实 14 天 Word：封面标题显示正常，运维建议页 `短期（两周内）`、`中期（1-3 个月）`、`三个月以上` 均完整显示，无明显空白页或错位；`3.2` 增长率 Top 20 表格标题、统计窗口、表头和数据行位于同一页。

### 2026-06-09 Excel 客户版模板化计划记录

状态：完成第一版，并已在 `10.20.11.3` 验证

结论：

- 用户提供 `存储容量预测分析报表_客户版.xlsx`，希望 v2 Excel 直接学习该模板，最好以模板为母版填充真实数据，并注意容量单位。
- 已检查模板结构：包含 `封面`、`执行摘要`、`容量趋势`、`VM增长TOP20`、`日增长详情`；其中 `VM增长TOP20` 和 `日增长详情` 已有冻结窗格，整体适合作为客户版 Excel 样式基底。
- 已将模板纳入 `backend/app/v2/reports/templates/customer_report.xlsx`，`build_report_xlsx()` 加载模板后填充 v2 数据；保留现有 Excel 导出 API、bundle 任务和下载路径。
- 模板内硬编码内容需要清理：`SmartX 超融合平台`、错误客户名、固定 Tower/集群、固定统计窗口和样例容量数据都不能进入真实导出。
- Excel 多 Tower/多集群展示规则已落地：封面显示范围摘要，正文新增 `范围明细` Sheet，每行一个 `Tower + 集群`；容量趋势、集群汇总和每集群 Sheet 保留 Tower 归属。

实现：

- `封面`、`执行摘要`、`容量趋势`、`VM增长TOP20`、`日增长详情` 复用客户版模板结构和基础样式。
- 新增/保留 `目录`、`范围明细`、`集群汇总`、`VM_TOP100_汇总`、`本日新建VM`、`本月新建VM` 和每集群独立 Sheet。
- Excel 客户可读 Sheet 使用格式化容量单位；完整 Top100 Sheet 继续保留筛选/排序结构。

验证：

- TDD RED：新增 `test_xlsx_uses_customer_template_with_v2_scope_and_units` 后，旧实现因缺少模板 Sheet 失败。
- 本地 `backend.tests.test_v2_report_exports` 通过，13 个测试中 2 个按原条件跳过。
- 本地 `py_compile` 和 `git diff --check` 通过。
- 本地 `backend.tests.test_v2_reports` 因本机缺少 `httpx` 无法运行；按用户约束未在本机安装依赖，改在远端容器验证。
- `10.20.11.3` 容器内 `backend.tests.test_v2_report_exports backend.tests.test_v2_reports` 通过，共 19 个测试。
- `10.20.11.3` 已重建并 recreate `web-api`，`/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 真实接口导出 14 天 bundle 成功，Excel 文件：`/data/smartx-storage-forecast/exports/reports/storage-forecast-all-20260609-133224-14d.xlsx`。
- 真实 Excel 验证通过：包含 `封面`、`执行摘要`、`容量趋势`、`VM增长TOP20`、`日增长详情`、`目录`、`范围明细`、`集群汇总`、`VM_TOP100_汇总`、`本日新建VM`、`本月新建VM` 和现场集群 Sheet；包含新封面标题、HCI 英文副标题、`近 14 天样本增长` 和容量单位；不包含 `SmartX 超融合平台`。

### 2026-06-09 清理测试注入的 Prometheus 异常容量点

状态：完成现场清理，未改代码

现象：

- 用户发现 7 天 Word 报表中 `当前已用容量 22.27 TB`、`近 7 天样本增长 569.98 GB`，但 `90 天预测容量` 被算成 `945.41 TB`，使用率 `431.35%`。
- 排查确认该值来自 `forecast_series()` 对集群历史点做线性趋势预测；不是由 `近 7 天样本增长` 直接外推。

根因：

- `10.20.11.3` Prometheus 中存在测试注入异常点：
  - metric：`smartx_cluster_storage_used_bytes`
  - labels：`tower_id="3"`、`cluster_id="cm551tvrv029a0858up57q8qu"`
  - 异常值：`212069600408371` bytes
  - 异常时间范围约：`1780894329 - 1780903929`
- 该异常点把线性回归斜率拉到约 `10.26 TB/天`，导致 90 天预测被拉高到约 `945 TB`。

处理：

- 临时使用 compose override 给 Prometheus 增加 `--web.enable-admin-api`，重启 Prometheus。
- 通过 `delete_series` 删除该 metric 在 `1780893600 - 1780904600` 的测试样本。
- 执行 `clean_tombstones`。
- 恢复原 compose 启动参数并 recreate Prometheus，确认 `web.enable-admin-api=false`。

验证：

- 重新查询 report：异常点数量为 `0`。
- `current=22.27 TB`，`period_growth_7=569.98 GB`。
- `forecast_90d` 从约 `945 TB` 恢复为约 `32.03 TB`。
- `slope_per_day` 恢复为约 `111.08 GB/天`。
- 真实导出 7 天 bundle 成功，Word `/data/smartx-storage-forecast/exports/reports/storage-forecast-all-20260609-141020-7d.docx` 不再包含 `945.41` 或 `431.35`，包含约 `32.03` 的 90 天预测值。

### 2026-06-09 Word 章节重排计划记录

状态：已记录计划，尚未实施代码

用户要求：

- `执行摘要` 改成 `摘要`。
- `三`、`四` 开始按照集群分开汇报。
- `五` 进行所有集群汇总报告。
- 报告第二页插入目录，且 `三`、`四` 要按集群分目录项。

计划结论：

- Word 结构调整为：封面、目录、`一  摘要`、`二  集群容量概览`、`三  集群虚拟机增长分析`、`四  集群容量趋势图表`、`五  全集群汇总报告`。
- `三` 按集群拆分 Top 20 增长量 VM 和 Top 20 增长率 VM。
- `四` 按集群拆分容量趋势图和 Top 10 VM 增长图。
- `五` 只放全局风险矩阵、全局建议和声明。
- 目录页必须紧跟封面，并按每个集群生成 `三.x`、`四.x` 目录项。

未执行：

- 本轮只更新计划文件，没有修改 `backend/app/v2/reports/export.py`，没有同步远端，也没有重建容器。

### 2026-06-09 Word 封面统计窗口与 2.2 增长周期修复

状态：本地实现并通过本地目标测试，待远端验证

用户要求：

- 封面 `统计窗口` 下方新增 `本报表统计窗口`。
- Word 章节 `2.2 容量增长趋势` 不再展示 `近 365 天样本增长`。
- `2.2` 固定展示 `近 14 天样本增长`、`近 30 天样本增长`、`近 90 天样本增长`。
- 对 14/30/90 天周期，如果采集历史不足对应天数则显示 `数据不足`，避免把短历史样本误当完整周期增长。

实现：

- `backend/app/v2/reports/export.py`：
  - `_customer_cover_meta()` 新增 `本报表统计窗口`。
  - `_customer_cluster_growth_table()` 表头改为 14/30/90 天样本增长和 90 天预测容量。
  - 新增 `_cluster_growth_window_label()` / `_cluster_period_growth_with_min_span()`，采集跨度不足目标周期时返回 `数据不足`。
  - 2.2 表格说明更新为 14/30/90 天口径。
- `backend/tests/test_v2_report_exports.py`：
  - 覆盖封面新增 `本报表统计窗口`。
  - 覆盖 2.2 不再包含 `近 365 天样本增长`。
  - 覆盖短历史场景下 30/90 天显示 `数据不足`。

本地验证：

- `backend.tests.test_v2_report_exports`：14 个测试通过，2 个因本机缺 FastAPI 依赖跳过。
- `py_compile backend/app/v2/reports/export.py backend/tests/test_v2_report_exports.py` 通过。
- `git diff --check` 通过。

远端验证：

- 已同步 `backend/app/v2/reports/export.py` 和 `backend/tests/test_v2_report_exports.py` 到 `10.20.11.3:/data/smartx-storage-forecast/project`。
- 容器内 `backend.tests.test_v2_report_exports backend.tests.test_v2_reports` 通过，共 20 个测试。
- 已重建并 recreate `web-api`。
- `/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 真实导出 90 天 Word：`/data/smartx-storage-forecast/exports/reports/storage-forecast-all-20260609-143412-90d.docx`。
- 真实 Word XML 验证：包含 `本报表统计窗口`、`近 14 天样本增长`、`近 30 天样本增长`、`近 90 天样本增长`、`数据不足`，不包含 `近 365 天样本增长`。

### 2026-06-09 Word 目录、章节重排与报表窗口拆分实施

状态：已在 `10.20.11.3` 验证完成

用户要求：

- `执行摘要` 改成 `摘要`。
- 报告第二页插入目录，并且 `三`、`四` 要按集群分目录项。
- `三`、`四` 开始按照集群分开汇报。
- `五` 进行所有集群汇总报告。
- `本报表统计窗口` 应显示用户选择的 7/14/30/90/180/365 天窗口；`统计窗口` 继续显示真实有效采集窗口。

实现：

- `backend/app/v2/reports/export.py`：
  - Word 构建顺序调整为封面、目录、`一  摘要`、`二  集群容量概览`、`三  集群虚拟机增长分析`、`四  集群容量趋势图表`、`五  全集群汇总报告`。
  - 新增 `_customer_add_directory()`，用可见目录表格列出 `2.1/2.2/2.3`、每个集群的 `三.x`、每个集群的 `四.x` 和第五章。
  - `三` 章按集群拆分增长量 Top 20 和增长率 Top 20，VM 数据只来自该集群。
  - `四` 章按集群拆分容量趋势图和 Top 10 VM 增长量图；图表不可生成时写完整空态标题。
  - 新增 `_requested_report_window_label()`，`本报表统计窗口` 使用用户选择窗口，`统计窗口` 使用实际有效采集窗口。
- `backend/tests/test_v2_report_exports.py`：
  - 增加/更新 Word XML 测试，覆盖目录顺序、集群章节拆分、报表窗口拆分和旧章节名移除。

本地验证：

- `backend.tests.test_v2_report_exports`：17 个测试通过，2 个因本机缺 FastAPI 依赖跳过。
- `py_compile backend/app/v2/reports/export.py backend/tests/test_v2_report_exports.py` 通过。
- `git diff --check` 通过。
- `backend.tests.test_v2_reports` 在本机因缺 `httpx` 无法导入 Prometheus 客户端，需在 `10.20.11.3` 容器内验证。

远端验证：

- 已同步本轮文件到 `10.20.11.3:/data/smartx-storage-forecast/project`，远端原文件备份为 `/tmp/smartx-v2-report-files-20260609150430.tar.gz`。
- 容器内执行 `backend.tests.test_v2_report_exports backend.tests.test_v2_reports`，23 个测试通过。
- 已重建并 recreate `web-api`。
- `/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 真实导出 90 天 Word：`/data/smartx-storage-forecast/exports/reports/storage-forecast-all-20260609-151000-90d.docx`。
- 真实 Word XML 验证：包含 `目录`、`一  摘要`、`三  集群虚拟机增长分析`、`四  集群容量趋势图表`、`五  全集群汇总报告`、`本报表统计窗口` 和 `近 90 天（`；不包含旧章节 `一  执行摘要`、`三  虚拟机增长分析`、`四  容量趋势图表`、`五  风险评估与建议`。

### 2026-06-09 Excel Sheet 精简与单元格显示修复

状态：已在 `10.20.11.3` 验证完成

用户要求：

- 检查真实导出的 Excel，修复单元格文字/数值显示不全。
- 删除 `目录`、`范围明细`、`集群汇总`、`VM_TOP100_汇总`。
- 将 `VM增长TOP20` 改为 `VM增长TOP100`。
- 每个集群独立 Sheet 模仿 TOP100 表格式，并避免容量 bytes 原始值导致 `########` 或科学计数法。

实现：

- `backend/app/v2/reports/export.py`：
  - `build_report_xlsx()` 不再创建四个冗余 Sheet，并在导出前兜底删除。
  - 模板 Sheet `VM增长TOP20` 在导出时重命名为 `VM增长TOP100`，左右表均输出 TOP100。
  - 每集群 Sheet 顶部概览改为 Tower、集群、当前容量、统计窗口增长、90 天预测容量、总容量、使用率、预计耗尽天数和风险。
  - VM 表、日增长和新建 VM Sheet 均使用 `GiB/TiB/%/天` 可读文本，不再输出原始 bytes。
  - 增加固定列宽、标题合并、换行和行高，保证 VM 名称、容量和说明文本可读。
- `backend/tests/test_v2_report_exports.py`：
  - 覆盖 Sheet 列表、`VM增长TOP100`、集群 Sheet 可读容量、关键列宽和冗余 Sheet 移除。

验证：

- 本地 `backend.tests.test_v2_report_exports`：17 个测试通过，2 个因本机缺 FastAPI 依赖跳过。
- 本地 `py_compile backend/app/v2/reports/export.py backend/tests/test_v2_report_exports.py` 通过。
- 本地 `git diff --check` 通过。
- 已同步 `backend/app/v2/reports/export.py` 和 `backend/tests/test_v2_report_exports.py` 到 `10.20.11.3:/data/smartx-storage-forecast/project`，远端原文件备份为 `/tmp/smartx-v2-excel-report-files-20260609155444.tar.gz`。
- 容器内执行 `backend.tests.test_v2_report_exports backend.tests.test_v2_reports`，23 个测试通过。
- 已重建并 recreate `web-api`，`/api/system/health` 返回 `ok=true`。
- 真实导出 14 天 Excel：`/data/smartx-storage-forecast/exports/reports/storage-forecast-all-20260609-160108-14d.xlsx`。
- 真实 Excel 验证：Sheet 为 `封面`、`执行摘要`、`容量趋势`、`VM增长TOP100`、`日增长详情`、`本日新建VM`、`本月新建VM`、`SMARTX-TT-WW`；没有 `目录`、`范围明细`、`集群汇总`、`VM_TOP100_汇总`、`VM增长TOP20`；未发现大整数容量值。

### 2026-06-09 Word 原生目录与标题样式修复

状态：已在 `10.20.11.3` 验证完成

用户要求：

- Word 不再手写目录表格，应使用真实标题样式和 Word 普通目录。
- 五个主章节使用标题一；集群章节使用标题二；小标题可进入标题三。
- 文档打开时应自动更新目录。

实现：

- `backend/app/v2/reports/export.py`：
  - 将客户版 Word 目录页从 `_customer_add_directory()` 手写表格改为 `_customer_add_native_toc()` 原生 TOC 字段。
  - TOC 字段使用 `TOC \\o "1-3" \\h \\z \\u`，覆盖 `Heading 1/2/3`。
  - 在 `settings.xml` 写入 `w:updateFields=true`，让 Word/WPS 打开文件时更新目录。
  - `一/二/三/四/五` 主章节改为真实 `Heading 1`。
  - `2.1/2.2/2.3`、`三.x`、`四.x`、`5.1/5.2` 改为真实 `Heading 2`。
  - 集群内 `增长量 Top 20` / `增长率 Top 20` 表标题改为真实 `Heading 3`，可进入三级目录。
- `backend/tests/test_v2_report_exports.py`：
  - 新增 `test_docx_uses_native_toc_and_real_heading_styles`，覆盖 TOC 字段、`updateFields`、移除旧目录表头、主章节 `Heading1` 和集群章节 `Heading2`。

本地验证：

- RED：新增测试在旧实现上失败，原因是 DOCX XML 不包含 `TOC`，且目录仍是 `章节/内容` 手写表格。
- GREEN：实现后该测试通过。
- `backend.tests.test_v2_report_exports`：18 个测试通过，2 个因本机缺 FastAPI 依赖跳过。

远端验证：

- 已同步本轮文件到 `10.20.11.3:/data/smartx-storage-forecast/project`。
- 容器内执行 `backend.tests.test_v2_report_exports backend.tests.test_v2_reports`，24 个测试通过。
- 已重建并 recreate `web-api`。
- `/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 真实导出 14 天 Word：`/data/smartx-storage-forecast/exports/reports/storage-forecast-all-20260609-163003-14d.docx`。
- 真实 Word XML 验证：包含 `TOC` 和 `1-3`、`w:updateFields w:val="true"`、`Heading1`、`Heading2`、`Heading3`；不包含旧手写目录表头 `章节` / `内容`。

### 2026-06-09 Word 2.3 容量使用率可视化纯文本块化

状态：已在 `10.20.11.3` 验证完成

用户要求：

- 参考客户版截图和用户补充代码，`2.3 容量使用率可视化` 使用 DOCX 纯文本块实现，不再用图片型 Top10 集群容量使用率图。

实现：

- `backend/app/v2/reports/export.py`：
  - `2.3` 从 `_customer_usage_chart()` 改为 `_customer_usage_bars()`。
  - 多集群范围默认选择当前使用率最高的集群，并在说明中写明 Tower/集群名称。
  - 展示两条 DOCX 原生进度条：`当前使用率` 和 `90 天预测使用率`。
  - 进度条使用 `█/░` 纯文本块：`█` 表示已用比例，`░` 补足剩余比例，当前使用率为深蓝，90 天预测为亮蓝。
  - 每条进度条右侧展示 `容量阈值` 和阈值容量。
  - 下方补充容量安全边际说明，高风险时写明安全边际不足。
- `backend/tests/test_v2_report_exports.py`：
  - 扩展 Word XML 测试，覆盖 `当前使用率`、`90 天预测使用率`、`容量阈值`、`容量安全边际`、`█/░` 文本块和深蓝/亮蓝文字颜色，并断言 `2.3` 区段不再出现旧 `Top 10 集群容量使用率`。

验证：

- RED：新增测试在旧实现上失败，原因是 `2.3` 仍为旧 Top10 图表，缺少 `90 天预测使用率`。
- GREEN：实现后目标测试通过。
- 本地 `backend.tests.test_v2_report_exports`：18 个测试通过，2 个因本机缺 FastAPI 依赖跳过。
- 本地 `py_compile backend/app/v2/reports/export.py backend/tests/test_v2_report_exports.py` 通过。
- 本地 `git diff --check` 通过。
- 已同步本轮文件到 `10.20.11.3:/data/smartx-storage-forecast/project`，远端原文件备份为 `/tmp/smartx-v2-docx-text-bars-before-*.tar.gz`。
- 容器内执行 `backend.tests.test_v2_report_exports backend.tests.test_v2_reports`，24 个测试通过。
- 已重建并 recreate `web-api`，`/api/system/health` 返回 `ok=true`。
- 真实导出 14 天 Word：`/data/smartx-storage-forecast/exports/reports/storage-forecast-all-20260609-171217-14d.docx`。
- 真实 Word XML 验证：`2.3` 区段包含 `当前使用率`、`90 天预测使用率`、`容量阈值`、`容量安全边际`、`█/░` 文本块、深蓝 `1A3C6E` 和亮蓝 `007ACC` 文字颜色；不包含旧 `Top 10 集群容量使用率`。
- 已将真实导出的 Word 拉回本机渲染为 PNG，确认 `2.3` 视觉为纯文本块进度条，10.16% 显示 10 个深色块，右侧紧跟容量阈值。
- 字体继续使用开源 `Noto Serif` / `Noto Serif CJK SC`，不使用 `微软雅黑`。

### 2026-06-10 Excel 客户模板固化

状态：已同步 `10.20.11.3`，容器回归验证完成

- 已以用户修改的 `storage-forecast-optimized_1.xlsx` 重建并净化仓库 Excel 模板。
- 已清除模板中的 Tower、集群、VM 和容量数据，保留列宽、行高、样式、合并范围和冻结窗格。
- 已增加隐藏集群模板 Sheet，实际导出按集群复制，输出文件不保留模板 Sheet。
- 已新增精确布局回归测试，覆盖固定 Sheet 顺序、关键列宽、关键行高、合并范围和字体。
- 本地 `backend.tests.test_v2_report_exports` 20 个测试通过，2 个因本机缺 FastAPI 依赖跳过。
- 已同步到 `10.20.11.3:/data/smartx-storage-forecast/project`，重建并 recreate `web-api`。
- 测试机容器内 `backend.tests.test_v2_report_exports backend.tests.test_v2_reports` 共 26 个测试通过。
- `/api/system/health` 返回 `ok=true`，数据库和 Prometheus 检查正常。
- 测试机真实数据导出：`/data/smartx-storage-forecast/exports/reports/storage-forecast-all-20260610-193153-14d.xlsx`。
- 真实导出包含 7 个固定 Sheet 和 `SMARTX-TT-WW` 集群 Sheet；TOP100 为 101 行，关键列宽与用户模板一致，全部字体为 `Noto Sans CJK SC`，输出中不包含隐藏模板 Sheet。

### 2026-06-10 Excel 摘要与增长详情补充

状态：测试机真实数据验证完成

- 执行摘要 KPI 表第 4、6 行全部改为黑色粗体。
- `日增长详情` 标题合并为 `A1:I1`，避免标题文字显示不全。
- 在 `日增长详情` 后新增 `月增长详情`，使用 `month_fastest_growing_vms`，列结构和布局与日增长详情一致。
- 本地目标测试完成 RED/GREEN 验证；完整 `backend.tests.test_v2_report_exports` 共 21 个测试通过，2 个因本机缺 FastAPI 依赖跳过。
- 已同步到 `10.20.11.3`，重建并 recreate `web-api`；容器内报表测试共 27 个通过。
- 真实导出：`/data/smartx-storage-forecast/exports/reports/storage-forecast-all-20260610-201601-14d.xlsx`。
- 真实文件确认摘要第 4、6 行均为黑色粗体，日/月增长标题均合并 `A1:I1`，`月增长详情` 位于 `日增长详情` 后，全部字体为 `Noto Sans CJK SC`。
- 当前现场历史窗口不足 30 天，因此月增长详情保留 Sheet 并显示明确空状态；满 30 天后按既有月增长口径填充 VM。

### 2026-06-10 Excel TOP100 初始视口修复

状态：测试机真实数据验证完成

- 根因是客户模板的 `VM增长TOP100` Sheet 保存了 `topLeftCell=C1` 和活动单元格 `H15`，导出文件继承后默认从 C 列打开。
- 导出时保留 `A5` 冻结窗格，同时强制将初始视口重置为 `A1`，活动单元格重置为 `A5`。
- 新增回归断言，确保后续模板更新不会再次把默认视口带回 C 列。
- 本地 `backend.tests.test_v2_report_exports` 共 21 个测试通过，2 个因本机缺 FastAPI 依赖跳过；`py_compile` 与 `git diff --check` 通过。
- 已同步到 `10.20.11.3`，容器内报表测试共 27 个通过，并重建、recreate `web-api`；健康检查返回 `ok=true`。
- 真实导出：`/data/smartx-storage-forecast/exports/reports/storage-forecast-all-20260610-203302-14d.xlsx`，确认 `VM增长TOP100` 的 `topLeftCell=A1`、冻结窗格 `A5`、活动单元格 `A5`。

### 2026-06-10 Excel 日增长标签色清理

状态：测试机真实数据验证完成

- 清除 `日增长详情` Sheet 从客户模板继承的紫色标签色，表格内容、字体、列宽和内部配色保持不变。
- 导出代码显式设置 `日增长详情.sheet_properties.tabColor=None`，避免后续替换模板时再次带回标签颜色。
- 新增回归断言；本地完整报表测试 21 个通过、2 个因本机缺 FastAPI 依赖跳过，`py_compile` 与 `git diff --check` 通过。
- 已同步到 `10.20.11.3`，容器内报表测试 27 个通过，重建并 recreate `web-api`，健康检查返回 `ok=true`。
- 真实导出：`/data/smartx-storage-forecast/exports/reports/storage-forecast-all-20260610-223344-14d.xlsx`，确认 `日增长详情` 的 `tabColor=None`。

### 2026-06-10 Phase 编号与优先级整理

状态：计划文档已更新

- 将重复的 `Phase 18 - Excel 客户模板固化` 统一编号为 `Phase 21`。
- Phase 18 任务中心状态机、Phase 19 分级通知、Phase 20 配置迁移包和 Phase 21 Excel 客户模板均保持已完成状态。
- 新增 `Phase 22 - 升级任务跨重启恢复`，状态为待实施，优先级为当前最高 `P0`。
- 最初记录了 `runner v0.3.1` 两阶段引导方案；用户确认 v0.3.0 尚未正式发布后，已撤销该方案。
- Phase 22 改为直接完善并重新构建同版本 `runner v0.3.0`，正式发布后普通平台升级尽量不再要求先升级 runner。
- 新兼容策略使用 `protocol_version + required_capabilities`，不再把平台升级与 runner 具体版本机械绑定。
- 记录恢复设计边界：检查点、心跳与租约、SQLite/task.json 对账、幂等恢复、人工接管和回滚。

### 2026-06-10 Phase 22 升级协议与 Runner 恢复实现

状态：已完成并通过 `10.20.11.3` 故障注入验证

- 新增独立升级协议、manifest 编译器、原子任务存储和 SQLite Runner 租约。
- Runner v0.3.0 拆分为独立 main、engine、actions、store、sandbox、lease，不再依赖平台 UpgradeService。
- 新增标准升级 Action、受控迁移脚本沙箱、分级恢复和健康检查失败后自动回滚一次。
- 新增恢复 API 与前端继续、回滚、标记失败控制面。
- 平台、Runner、Prometheus 构建器升级到 schema 3，并生成 `checksums.sha256`。
- 升级文档补充平台包、Runner 包、Prometheus 包和组合包组成、执行者、流程及禁入内容。
- 新增平台与 Prometheus 组合包构建器，组合包默认不包含 Runner。
- 补齐沙箱宿主机路径映射、升级新增文件回滚删除和原版本服务 recreate。
- 测试机已完成 Runner/web-api/frontend 重建，健康接口、Prometheus 和前端入口正常。
- 测试机后端 Phase 22 相关测试 42 个通过，前端 `ServicePage` 15 个测试通过。
- Runner 停止期间注入 `running` 安全动作，重启后自动接管成功，attempt 从 1 增加到 2，checkpoint 与 revision 正常递增。
- 注入执行结果不明确的 `script.run_sandboxed` 后，Runner 保持 attempt=1 并进入 `recovery_required`，提供继续、回滚、标记失败。
- 使用真实 `smartx-storage-forecast-web-api:local` 镜像执行受限沙箱脚本，`network=none`、只读根文件系统、宿主机数据路径映射、SHA256 和完成标记均生效。
- Runner 状态表显示 `v0.3.0`、协议版本 1、完整 capability 列表和持续心跳；恢复任务正确投影为 `critical`。
- 重建后的 `/api/system/health` 返回 `ok=true`，前端返回 200，Prometheus `/-/healthy` 正常；故障注入任务和文件已清理。
- SQLite 备份改用 Backup API，回归覆盖 WAL 未 checkpoint 数据；自动回滚按 `platform/observability/bundle` 作用域恢复 SQLite 和 Prometheus 数据。
- 健康检查增加最多 30 次、每次间隔 2 秒的默认等待窗口；回滚完成后必须再次通过健康检查，否则进入 `rollback_failed` 严重告警。
- Runner 进程 `instance_id` 在多轮扫描中保持不变，测试机两次心跳查询 owner 一致、时间持续更新。
- 最终镜像重建后再次执行真实受限沙箱任务，状态为 `success`，完成标记存在，测试任务和文件已清理。

### 2026-06-11 Phase 22 Prometheus 升级包边界修正

状态：文档和构建器口径已统一，待最终提交

- 明确平台升级、Prometheus/observability 组件升级和组合升级都不导出 Prometheus 历史数据。
- Prometheus 组件包默认改为轻量包：包含 `manifest.json`、`checksums.sha256`、`release-notes.md`、`config/prometheus.yml` 和 `health/queries.json`，镜像使用仓库 tag 引用。
- 只有离线环境使用 `--offline-image` 时，Prometheus 组件包或组合包才包含 `images/prometheus.tar`。
- 升级前的 Prometheus 数据目录备份只保存在服务器 `/data/smartx-storage-forecast/backups/...`，用于失败回滚或人工恢复，不进入升级包。
- Prometheus 历史 block 的导出/导入边界收敛到完整数据迁移包；配置迁移包仍只迁移 Tower/Cluster 配置。

### 2026-06-11 升级文档统一更新

状态：文档更新完成，待提交

- README 中英文、`docs/v2-upgrade-center-design.md`、`docs/architecture.md`、`docs/deployment.md`、`docs/functional-modules.md`、`docs/version-governance.md` 和 `docs/upgrade-issues.md` 已统一到当前升级口径。
- 平台版本固定为 `v0.5.0`，Runner 组件版本固定为 `v0.3.0`，组合包示例改为当前平台版本语境，避免误解为 `v0.6.0`。
- 四类升级包树形结构已统一：平台包、Runner 组件包、Prometheus 轻量/离线组件包、平台+观测组合包。
- 历史 `schema_version=2` 和早期 Prometheus tar 包记录保留为历史事实，并在旁边补充当前 schema 3 与轻量包口径。


### 2026-06-11 v0.5.0 跨版本升级累计迁移支持

状态：已完成并通过本地与 `10.20.11.3` 验证

- 平台升级包构建器新增 SQLite migration registry，按 `source_version < step.version <= target_version` 选择累计迁移步骤。
- 用户确认当前正式版本仍使用 `v0.5.0`，不因测试升级包目标版本发布新的正式版本；当前 `v0.5.0` 正式包无 schema 迁移时不包含 `migration`、`migration_steps`、`script.sandbox.v1` 或迁移脚本。
- 当未来目标版本跨过 schema 变化版本时，打包器生成单文件 `migrations/run_migrations.py`，Runner 仍只执行一个沙箱脚本，脚本内部按版本顺序执行并记录所有命中步骤。
- registry step 支持声明幂等 `sql` 列表和 `add_column_if_missing` 操作，生成的迁移脚本会先执行迁移动作，再写入 `schema_migrations`；单步失败不会写成功记录。
- registry 校验收紧：`sql` 必须是字符串数组，`database` 当前只允许 `sqlite`，重复 step id、未知 operation 或缺少加列参数都会在打包阶段失败。
- SQLite `schema_migrations` 表升级为 `id/version/description/script_sha256/applied_at`，保留旧 `name/applied_at` 表的兼容迁移。
- 组合包透传平台包的 `database_migration`、`migration_steps` 和迁移脚本，且保留 `run_migrations.py` 文件名；schema 3 包不再默认 fallback 到旧 `scripts/migrate.sh`。
- 本地目标测试 15 个通过，`scripts/build_upgrade_package.py --check-version --no-build` 返回 `Version metadata OK: v0.5.0`，`git diff --check` 通过。
- `10.20.11.3` 已重建并 recreate `web-api`、`collector-worker`、`frontend`；`/api/system/health` 返回 `version=v0.5.0`、`runner_version=v0.3.0`，前端 8080 和 Prometheus healthy 均返回 200。
- `10.20.11.3` 目标测试 15 个通过，最终检查包 `smartx-capacity-insight-upgrade-v0.5.0.tar.gz` 的 manifest 确认 `database_migration=false`，不包含 `migration`、`migration_steps`、`script.sandbox.v1`、`migrations/` 或 `scripts/migrate.sh`。

### 2026-06-11 v0.5.0 稳定化收敛决策

状态：计划已建立，待实施

- 用户确认后续继续以需求提出为主，由 Codex 负责整体架构、版本节奏和稳定性方案把控。
- 版本节奏收束为“一版一个主目标”：当前只固定 `v0.5.0` 稳定线，后续升级中心、报表质量、数据迁移与清理增强进入独立 Phase，正式版本号发布前统一决定。
- 新增 `Phase 23 - v0.5.0 稳定化收敛`，冻结当前功能面，优先修发布阻塞和升级中心主路径稳定性。
- 在 `10.20.11.3` 排查 runner 组件升级“hang 住”问题：真实执行已完成，Runner 心跳与版本正常，任务顶层状态与 SQLite 投影多为 `success`。
- 发现伪 hang 根因：runner 自升级恢复收尾后 `task.json` 顶层已为 `success`，但 `steps.restart` 仍为 `running`、`steps.healthcheck` 仍为 `pending`，前端可能据此显示仍在等待新进程确认。
- 真实业务库路径确认：宿主机 `/data/smartx-storage-forecast/app/smartx.db` 映射到容器内 `/data/smartx.db`；宿主机 `/data/smartx.db` 是 0 字节误导文件。
- Phase 23 后续修复方向：统一 `task.json` 到 SQLite 任务中心的状态投影，runner 自升级收尾必须同步 steps，增加固定验收脚本覆盖平台、Runner、Prometheus 三条升级主路径。

### 2026-06-11 Phase 23 Runner 自升级伪 hang 修复

状态：本地实现完成，待 `10.20.11.3` 验证

- 按 TDD 增加回归断言：runner-only 组件升级从 `runner_restarting` 恢复后，`task.json` 与 SQLite 投影中的 `restart`、`healthcheck` steps 都必须为 `succeeded`。
- RED：新增断言后，`backend.tests.test_v2_upgrade.V2UpgradeServiceTest.test_runner_component_upgrade_writes_runtime_override_and_only_restarts_runner` 失败，实际 `restart=running`。
- GREEN：`app.upgrade_runner.main` 新增 steps 替换 helper；`runner_restarting + runner_resume_pending + no execution_plan` 恢复分支同步收尾 `restart` 和 `healthcheck`，并写入 `finished_at`。
- `_project_task()` 在没有 `execution_plan.actions` 时投影 `task.steps`，确保 runner 自升级这类 web-api 直执行任务不会丢失步骤状态。
- 本地单测通过：目标回归测试 1 个通过；升级中心相关测试 `backend.tests.test_v2_upgrade backend.tests.test_upgrade_runner_engine backend.tests.test_upgrade_protocol backend.tests.test_v2_package_builders` 共 51 个通过、1 个跳过。

### 2026-06-11 Phase 23 Runner 自升级远端验证

状态：`10.20.11.3` 验证通过

- 增加历史自愈回归测试：旧版遗留的 `status=success` runner 组件升级任务，如果 `steps.restart=running` 或 `steps.healthcheck=pending`，新 Runner 启动扫描时会归一化为 `succeeded` 并重新投影到 SQLite。
- 本地升级中心相关测试更新为 52 个通过、1 个跳过。
- 已同步到 `10.20.11.3:/data/smartx-storage-forecast/project`，远端升级中心相关测试 52 个通过、1 个跳过。
- 已重建并 recreate `upgrade-runner`；健康接口返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`。
- 新增固定验收脚本 `scripts/verify_upgrade_center_v050.py` 并在测试机通过：
  - Runner 心跳存在，能力数 10。
  - 22 条成功升级任务 SQLite 投影无 `running/pending` steps。
  - 13 个成功 `task.json` 无 `running/pending` steps。
  - `smartx-capacity-insight-upgrade-v0.5.0.tar.gz` 确认无 `migration`、无 `migration_steps`、不要求 `script.sandbox.v1`，且包含平台三件套镜像。

### 2026-06-11 Phase 23 主路径稳定化收尾

状态：`10.20.11.3` 三条真实升级主路径验证通过，待提交

- 继续排查真实 Prometheus 轻量包升级时发现任务 `upgrade-3e8f1399ffd3cb33` 停在 `pending`，原因是 `upgrade-runner` 容器在 runner 组件升级后持续重启。
- Runner 日志显示旧入口错误：`No module named 'app.upgrade'`；确认 runtime override 只覆盖 image，未覆盖 command，导致新 runner 镜像仍按旧模块名启动。
- 按 TDD 增加 runner 组件升级 override 回归断言：必须包含 `app.upgrade_runner.main`，且不得包含 `app.upgrade.runner`；RED 失败后修复 `_write_override()`。
- 按 TDD 增加 runner 组件升级成功时 `task.json.finished_at` 回归断言；同时为 Runner engine 成功终态写入 `finished_at`，确保平台/Prometheus 任务文件也完整落盘。
- 本地升级中心相关测试通过：`backend.tests.test_v2_upgrade backend.tests.test_upgrade_runner_engine backend.tests.test_upgrade_protocol backend.tests.test_v2_package_builders` 共 53 个通过、1 个跳过。
- 已同步到 `10.20.11.3`，远端同组测试 53 个通过、1 个跳过；重建并 recreate `web-api`、`upgrade-runner`，重新生成 runner 组件包。
- 真实 runner 组件升级再次执行成功：`upgrade-5703b1c5fe62f710`，`status=success`，`finished_at` 有值，`restart/healthcheck` 均为 `succeeded`。
- 真实 Prometheus 组件升级再次执行成功：`upgrade-28b02dbdd78e4502`，`status=success`，`finished_at` 有值，所有 actions 均为 `succeeded`。
- 固定验收脚本在测试机通过：健康版本 `platform=v0.5.0`、`runner=v0.3.0`，27 条 SQLite 成功升级任务和 18 个成功 `task.json` 均无 `running/pending` steps，v0.5.0 平台包无迁移 payload。
- 远端健康检查通过：`/api/system/health` 返回 `ok=true`，前端 8080 返回 200，Prometheus `/-/healthy` 返回 200。
- 追加验证真正的 Prometheus 轻量包：在 `/data/upgrade-packages/components-light/` 重新生成默认包，tar 成员只有 `manifest.json`、`release-notes.md`、`config/prometheus.yml`、`health/queries.json`、`checksums.sha256`，不包含 `images/prometheus.tar`。
- 真实轻量 Prometheus 组件升级 `upgrade-73ac11cad1f299da` 通过 API 上传、预检查、启动和轮询，最终公开状态 `succeeded`，`finished_at=2026-06-11T15:52:29.756938+00:00`。
- 再次运行固定验收脚本通过：28 条 SQLite 成功升级任务和 19 个成功 `task.json` 均无 `running/pending` steps，系统健康、前端 8080 和 Prometheus healthy 正常。

### 2026-06-11 v0.5.0 稳定线任务中心确认滚动稳定性

状态：已实现并部署到 `10.20.11.3`，待提交

- 用户此前指出：任务中心点击失败历史任务的“确认”后会回到任务中心顶部，希望确认告警不改变当前浏览位置。
- 后端已有回归测试覆盖 `acknowledge()` 不更新排序用的 `updated_at`，本轮补前端滚动稳定性。
- `AppLayout` 任务列表增加滚动位置保存与 `useLayoutEffect` 恢复；确认告警或刷新任务数据后，任务菜单列表保持原 `scrollTop`。
- 增加前端回归测试：滚动任务中心列表后确认第 6 个告警，rerender 为已确认任务，`.task-menu-list.scrollTop` 保持 180。
- 在 `10.20.11.3` 使用临时 Node 容器和 `phase22-node-modules` volume 运行 `AppLayout.test.tsx`，17 个测试通过。
- 已重建 frontend 镜像并 recreate 容器；运行容器 image 为 `smartx-storage-forecast-frontend:local`，创建时间 `2026-06-11T15:59:12Z`，`8080` 返回 200，`/api/system/health` 正常。

### 2026-06-11 Phase 23 测试机任务中心历史整理

状态：已完成

- 使用 `/api/tasks` 审计 `10.20.11.3` 任务中心：共有 30 条可见任务，其中 7 条成功信息任务未读，3 条 critical 历史任务已确认且 clearable，无未确认告警。
- 没有手工改 SQLite；通过公开 API 调用 `/api/tasks/seen` 标记 7 条信息任务已读，再调用 `DELETE /api/tasks/clearable` 清空 clearable 历史任务。
- 清理后 `/api/tasks` 返回 0 条，历史故障注入任务不再干扰任务中心观感。
- Phase 23 状态更新为已完成。

### 2026-06-11 v0.5.0 升级中心完成审计

状态：目标完成，待用户决定提交/推送

完成证据：

- v0.5.0 稳定基线：`10.20.11.3` `/api/system/health` 返回 `version=v0.5.0`、`runner_version=v0.3.0`，frontend 8080 与 Prometheus `/-/healthy` 均返回 200。
- v0.5.0 平台包边界：固定验收脚本确认 `smartx-capacity-insight-upgrade-v0.5.0.tar.gz` 无 `migration`、无 `migration_steps`、不要求 `script.sandbox.v1`，且包含平台三件套镜像。
- Runner 组件升级：真实任务 `upgrade-5703b1c5fe62f710` 成功，`restart/healthcheck` 均为 `succeeded`，`finished_at` 有值；runtime override 固定为 `app.upgrade_runner.main`。
- Prometheus 轻量组件升级：真实任务 `upgrade-73ac11cad1f299da` 成功，默认轻量包不含 `images/prometheus.tar`，`finished_at` 有值。
- 任务中心：测试机历史故障注入任务已通过产品 API 清理，`/api/tasks` 返回 0 条、未处理通知 0；确认告警不更新后端排序时间，前端确认后保持任务列表滚动位置。
- 固定验收脚本：远端通过，19 个成功 `task.json` 无 `running/pending` steps；清理任务中心后 SQLite 任务投影为空，符合测试机整理后的状态。
- 本地回归：`python3 -m py_compile ...`、升级中心/任务中心相关单测共 61 个通过、3 个跳过，`git diff --check` 通过。
- 远端前端回归：`AppLayout.test.tsx` 17 个测试通过；frontend 已重建并 recreate。

剩余事项不属于当前目标完成条件：

- 当前工作树仍有未提交改动和新增文件，等待用户明确提交/推送指令。
- 报表质量、数据迁移和清理增强按用户要求降级为后续低优先级，不阻塞当前 `v0.5.0` 稳定线。

### 2026-06-12 v0.5.0u1 测试升级包

状态：已生成，待用户测试启动

- 用户要求打包一个 `v0.5.0u1` 版本升级包，仅用于测试升级。
- 未修改本地仓库 `VERSION`；在 `10.20.11.3` 创建临时副本 `/tmp/smartx-v050u1-build`，只在临时副本中替换平台版本、compose 默认 tag 和 `docker-compose.upgrade.yml` 镜像 tag 为 `v0.5.0u1`。
- 生成路径：`/data/upgrade-packages/v050u1-test/smartx-capacity-insight-upgrade-v0.5.0u1.tar.gz`。
- SHA256：`fb5f1cc49590d2a4e36502befd3230379d7dac21f3b14d9d8b28c7a49bf26d86`。
- 包校验通过：manifest `schema_version=3`、`version=v0.5.0u1`、`min_version=v0.5.0`、`database_migration=false`，不包含 `migration` 或 `migration_steps`。
- 包成员 40 个，无 `.env`、SQLite、Prometheus 历史数据、`/data`、`backups`、`upgrades`、`migrations/` 或 `scripts/migrate.sh`。
- 已通过升级中心上传和预检查，但未启动升级；预检查任务 id：`upgrade-7d9a438ee431b1f4`，状态 `precheck_passed`。

### 2026-06-12 测试升级包版本口径统一

状态：文档已更新

- 用户确认统一口径版本为 `v0.5.0`，`v0.5.4`、`v0.5.5` 只作为测试升级包目标版本，不作为正式版本发布。
- 已在 README 中英文、部署文档、升级中心设计和版本治理中补充：当前正式平台版本、源码版本、文档版本和常规镜像 tag 均为 `v0.5.0`；临时测试包目标版本不能反向修改 `VERSION` 或正式文档。
- `10.20.11.3` 已生成测试包：
  - `/data/upgrade-packages/smartx-capacity-insight-upgrade-v0.5.4.tar.gz`
  - SHA256：`39cfeb283e0ab54d837de4f4d8f2a8e69ca2692e39255adcbf24ea28b92cf5d0`
  - `/data/upgrade-packages/smartx-capacity-insight-upgrade-v0.5.5.tar.gz`
  - SHA256：`4623fc7c39c053e5e717806bd44c294c49ac77c4720cb252cd3a7f035c17f295`
- 两个测试包均来自临时构建目录，不修改仓库 `VERSION`；包校验通过：`schema_version=3`、`min_version=v0.5.0`、`database_migration=false`，不包含 `migration`、`migration_steps` 或 `migrations/`。

### 2026-06-12 dev2 分支收口准备

状态：执行中

- 用户确认 `dev` 分支废弃，`dev2` 作为 v2 当前开发与发布分支。
- 已将当前规划与设计文档中的现行分支口径从 `feature/upgrade-v2` 更新为 `dev2`；历史流水记录只作为历史事实保留。
- 下一步：将 `dev2` 当前内容推送到 `main`，创建并推送 `v0.5.0` tag，然后删除远端废弃 `dev` 分支。

### 2026-06-13 Phase 24 采集重试与趋势缺采标记

状态：已实现并部署到 `10.20.11.3`，待用户体验验证

- 按用户确认计划开始实现采集重试、部分成功写入 Prometheus 和 VM 趋势缺采提示。
- 已补后端回归测试：部分失败只发布成功目标 metrics、失败目标脱敏并生成 `Tower/集群采集异常` warning；Tower 重试配置旧库默认回填；retry 可只采上次失败目标；VM trend 返回缺采元数据。
- 已实现后端核心：目标级采集、`partial_failed`、`collection_runs` 目标 JSON 字段、TaskService 采集告警、worker 有限重试、VM trend freshness/gap 元数据。
- 已实现前端核心：Tower 表单显示采集失败重试配置；VM 趋势卡显示 `非最新`、最近成功采集时间和缺采日期；TrendChart 用 null 断点避免跨缺采日连线。
- 本地验证：`git diff --check` 通过；`python3 -m py_compile` 通过；`backend.tests.test_v2_collection`、`backend.tests.test_v2_worker`、`backend.tests.test_v2_dashboard_vm`、`backend.tests.test_v2_collection_runs_api` 共 18 个测试通过，2 个因本地缺依赖跳过。
- 已同步到 `10.20.11.3:/data/smartx-storage-forecast/project`，重建并 recreate `web-api`、`collector-worker`、`frontend`。
- 远端容器内后端目标测试通过：`backend.tests.test_v2_collection`、`backend.tests.test_v2_worker`、`backend.tests.test_v2_dashboard_vm`、`backend.tests.test_v2_collection_runs_api` 共 18 个通过。
- 远端前端目标测试通过：`SettingsPage.test.tsx`、`VmsPage.test.tsx` 共 9 个测试通过；`npm run build` 通过，仅有 chunk size 警告。
- 远端健康检查通过：`/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`；frontend 8080 返回 200；Prometheus `/-/healthy` 返回 200。
- 远端 API 功能抽检通过：
  - 登录成功。
  - `/api/towers` 返回重试配置字段，现有 Tower 默认值为 `true/15/3`。
  - `/api/tasks` 可访问。
  - 空间清理相关扫描接口可访问：本地存储、运行产物扫描、SQLite 扫描、镜像扫描。
  - `/api/vms/{vm_id}/trend` 返回 `latest_success_at`、`latest_collection_status`、`has_collection_gap`、`data_freshness` 字段。
  - `/api/reports/export/bundle?period_days=7` 成功生成 Word 和 Excel，两个导出文件路径均存在。
- 远端 UI 功能抽检通过：
  - 浏览器登录 `http://10.20.11.3:8080/` 成功，首页显示概览数据。
  - 服务管理 > 空间清理页中，运行产物“扫描”、SQLite“扫描 SQLite”、SQLite 备份“扫描备份”三个按钮均可点击并返回页面结果；未执行任何删除/清理动作。
  - 报表页点击“导出”可打开导出弹窗，点击弹窗“导出”后任务中心后端记录生成 `导出预测报表` 成功任务，Word/Excel 两个链接文件均存在。

### 2026-06-13 Phase 25 平台自检与升级后验收规划

状态：已记录后续优化方向

- 用户询问项目还有哪些优化空间；判断当前最值得做的是“平台自检与升级后验收”，优先提升生产可诊断能力，而不是继续堆叠大功能。
- 已将 Phase 24 从“实施中”更新为“已实现，待用户体验验证”，并记录远端前端 build、目标测试、健康检查、空间清理按钮和报表导出 UI 抽检已完成。
- 新增 Phase 25：平台自检与升级后验收。
- Phase 25 目标包括：
  - 后端统一自检 API。
  - CLI 验证脚本 `scripts/verify_platform.py`。
  - 升级后复用同一套验收。
  - 服务管理页升级为运维控制台第一版。
  - 覆盖服务、SQLite、采集、Prometheus、VM 趋势、任务中心、空间清理扫描和报表导出。
- 规划边界：以只读检查为主；空间清理只 scan，不自动删除；报表导出只在深度验收中生成验证文件；不写入虚假 Prometheus 样本。
- 使用 planning-with-files 的 session catchup 时，插件缓存路径下未找到 `scripts/session-catchup.py`，命令返回 `No such file or directory`；已记录该工具路径异常，继续使用现有 `task_plan.md`、`findings.md`、`progress.md` 作为当前上下文来源。

### 2026-06-13 Phase 25 self-check implementation progress
- Added backend self-check RED/GREEN unit tests for quick structure, Prometheus critical, collection partial_failed warning, missing SQLite table critical, and deep report bundle verification.
- Added backend self-check service skeleton and FastAPI GET/POST routes.
- Added CLI tests and scripts/verify_platform.py using the self-check API only.
- Local Python lacks fastapi/python-docx, so API TestClient is skipped locally and real API/docx verification must run in container/remote.

### 2026-06-13 Phase 25 implementation update
- Implemented SelfCheckService, API routes, CLI script, upgrade post-success self-check recording, ServicePage self-check UI, and docs updates.
- Local verification so far: py_compile passed; targeted backend self-check/CLI/upgrade tests passed with 1 FastAPI TestClient skip due local dependency.
- Frontend npm tests cannot run locally because npm is not installed in this host shell; must run in remote/container Node environment.

### 2026-06-13 Phase 25 local verification
- Fixed CLI test stdout capture after local verification exposed JSON read bug.
- Local command passed: python3 -m py_compile backend/app/v2/self_check/service.py backend/app/v2/api.py backend/app/v2/upgrade/service.py backend/tests/test_v2_self_check.py backend/tests/test_verify_platform_cli.py backend/tests/test_v2_upgrade.py scripts/verify_platform.py.
- Local command passed: PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_self_check backend.tests.test_verify_platform_cli backend.tests.test_v2_upgrade.V2UpgradeServiceTest.test_successful_upgrade_records_post_upgrade_self_check_and_alerts_on_critical (11 tests OK, 1 skipped for missing FastAPI TestClient).
- git diff --check passed.

### 2026-06-13 Phase 25 remote API validation
- Synced code to 10.20.11.3 using tar over SSH after fixing remote project ownership; rsync was unavailable on remote.
- Rebuilt images with correct repository prefix `nazawsze/...:v0.5.0` after initially building a typo tag `nazwawsze/...`.
- Recreated web-api and frontend.
- Remote health passed: `/api/system/health` ok=true version v0.5.0 runner v0.3.0; frontend 8080 returned 200; Prometheus healthy returned 200.
- Remote self-check API passed: quick healthy 20 checks; deep healthy 21 checks; deep with report export healthy 21 checks and produced Word/Excel links.

### 2026-06-13 Phase 25 remote UI and target test validation
- Remote backend target tests passed on `10.20.11.3`: `backend.tests.test_v2_self_check`, `backend.tests.test_verify_platform_cli`, and the upgrade self-check integration test ran 11 tests OK with 1 local dependency skip.
- Remote frontend target test passed in a Node container: `ServicePage.test.tsx` ran 19 tests OK.
- Browser UI validation passed for the service management self-check card: the card renders, quick self-check button enters loading state, and the result refreshes with a new timestamp.
- The live `10.20.11.3` environment currently reports `critical` through self-check because the latest scheduled collection failed with `Tower requires either an API token or username/password`; Prometheus current sample counts are therefore insufficient and VM trend freshness is partial.
- This live critical result is treated as expected self-check behavior rather than a UI/API failure: the platform services are reachable, but self-check correctly marks the data plane as not trustworthy until Tower credentials and collection recover.

### 2026-06-15 Phase 26 P1 数据正确性实施进展

状态：已实现并在 `10.20.11.3` 验证

- 已新增 `backend/app/v2/data_quality/service.py`，提供统一 `DataQualityService.evaluate()` 和 `evaluate_and_alert()`。
- 已接入采集完成后的后台一致性检查，`critical` 生成或更新 `数据一致性异常`，`warning` 生成或更新 `数据质量需关注`。
- 已将平台自检指标检查升级为 `data_quality.consistency`，摘要展示 SQLite/Prometheus VM 数、不完整集群数、缺采日期数和最新 Prometheus 样本时间。
- 已在 `latest_report()` 返回 `data_quality` 字段，报表页显示数据质量状态、实际采集窗口、缺采天数、样本是否足够和不完整集群数量；缺少字段时按未知状态兼容。
- 已在 Word 客户版“一 摘要”中新增“数据质量说明”，解释本报表统计窗口、实际采集窗口、样本是否足够、缺采天数、数据不完整集群和 SQLite/Prometheus 数量。
- 已在 Excel 导出新增固定 Sheet `数据质量说明`，位于 `执行摘要` 后，继续移除 `目录`、`范围明细`、`集群汇总`、`VM_TOP100_汇总` 等冗余 Sheet。
- 已更新 `docs/v2-api-contracts.md`、`README.md`、`README.zh-CN.md`、`task_plan.md` 和 `findings.md`，记录 P1 数据正确性口径。
- 用户要求所有测试和验证都在 `10.20.11.3` 执行；本地只做代码阅读和补丁编辑，不把本地测试作为验收依据。
- 远端后端目标测试通过：在 `10.20.11.3` 使用 `nazawsze/smartx-hci-capacity-insight-web-api:v0.5.0` 临时容器挂载 `/data/smartx-storage-forecast/project/backend`，运行 `tests.test_v2_data_quality tests.test_v2_self_check tests.test_v2_reports tests.test_v2_report_exports tests.test_v2_worker` 共 46 个测试通过。
- 远端前端目标测试通过：在 `10.20.11.3` 使用 `node:22-alpine` 挂载 `/data/smartx-storage-forecast/project/frontend`，运行 `npm test -- ServicePage.test.tsx ReportsPage.test.tsx`，2 个测试文件、25 个测试通过。
- 远端构建通过：`docker compose -p smartx-storage-forecast build web-api collector-worker frontend` 成功，frontend build 仅保留既有 Vite 大 chunk 提示。
- 已在 `10.20.11.3` recreate `web-api`、`collector-worker`、`frontend`；运行容器镜像为 `smartx-storage-forecast-*:local`。
- 远端健康检查通过：`/api/system/health` 返回 `ok=true`、`version=v0.5.0`、`runner_version=v0.3.0`；frontend `8080` 返回 200；Prometheus `/-/healthy` 返回 healthy。
- 远端真实报表 API 返回 `data_quality.status=critical`，原因是当前测试机 SQLite 有 177 台 VM，但 Prometheus 当前 VM series 为 0；缺采日期为 `2026-06-06`、`2026-06-13`，不完整集群为 `CHINATOWER / SMARTX-TT-WW`。该结果符合当前测试机数据面异常现状。
- 远端真实导出通过：`/api/reports/export/bundle?period_days=14` 生成 Word `/data/smartx-storage-forecast/exports/reports/storage-forecast-all-20260615-160141-14d.docx` 和 Excel `/data/smartx-storage-forecast/exports/reports/storage-forecast-all-20260615-160148-14d.xlsx`。
- Word XML 已确认包含 `数据质量说明` 和异常提示；Excel 已用 openpyxl 确认 Sheet 顺序包含 `数据质量说明` 且位于 `执行摘要` 后，并包含 `SQLite 当前 VM 数`、`Prometheus 当前 VM series 数`、缺采天数和不完整集群字段。

### 2026-06-15 任务中心告警日期补充

状态：已在 `10.20.11.3` 验证并重建前端

- 用户反馈任务中心告警没有告警日期。
- 根因：后端任务已有 `created_at/updated_at`，前端也映射为 `createdAt/updatedAt`，但任务中心告警卡片只展示标题、详情、进度和操作按钮，没有展示告警发生日期。
- 已在 `frontend/src/components/AppLayout.tsx` 中为 `warning/critical` 告警任务增加 `告警日期：YYYY/MM/DD HH:mm:ss`，使用 `createdAt` 作为原始告警发生时间，避免确认告警时受 `updatedAt` 变化影响。
- 告警日期按 `Asia/Shanghai` 固定格式化，避免测试容器或浏览器时区导致时间漂移。
- 已补 `frontend/src/components/AppLayout.test.tsx` 用例，覆盖 warning/critical 任务显示原始告警日期。
- 远端 `10.20.11.3` 前端目标测试通过：`AppLayout.test.tsx`，18 个测试通过。
- 已在 `10.20.11.3` 重建并 recreate `frontend`，最终 `http://127.0.0.1:8080` 返回 `HTTP/1.1 200 OK`。

### 2026-06-16 任务中心操作按钮标题行对齐

状态：已在 `10.20.11.3` 验证并重建前端

- 用户反馈 `确认` 和 `X` 仍未与任务标题同排，截图中按钮位于右侧列顶部但低于标题基线。
- 根因：按钮仍挂在 `.task-menu-actions` 右侧进度列内，即使顶部对齐也只能相对右侧列布局，无法和标题自然同一行。
- 已将任务卡片标题区域改为 `.task-menu-title-row`，标题左侧省略显示，`确认` 和 `X` 放入标题行右侧 `.task-menu-title-actions`。
- 右侧 `.task-menu-actions` 现在只保留进度百分比和两行日期时间，避免按钮与百分比/日期互相挤压。
- 已补前端测试覆盖：`确认任务告警` 和 `从任务中心移除` 必须位于 `.task-menu-title-row` 内；先同步新测试到远端验证旧布局失败，再完成实现后通过。
- 远端 `10.20.11.3` 前端目标测试通过：`AppLayout.test.tsx`，19 个测试通过。
- 已在 `10.20.11.3` 重建并 recreate `frontend`，最终 `http://127.0.0.1:8080` 返回 `HTTP/1.1 200 OK`。

### 2026-06-16 任务中心右上/右下四格结构修正

状态：已在 `10.20.11.3` 验证并重建前端

- 用户通过截图标注说明：上一版只是加宽后的旧排版，`确认/X` 仍混在左侧标题区域，未形成真正四格。
- 根因：按钮仍属于 `.task-menu-header-row`，导致右上区域并不是独立控件区；右侧进度/时间也未与按钮共享同一右侧列。
- 已将任务卡片网格改为 `header controls / body actions`：
  - 左上 `header`：状态图标 + 标题。
  - 右上 `controls`：`确认` + `X`。
  - 左下 `body`：详情、步骤、日志、下载按钮和进度条。
  - 右下 `actions`：`100%` 和日期时间。
- 已补回归测试：`确认任务告警` 不允许再位于 `.task-menu-header-row` 或标题行内，必须在 `.task-menu-controls`；进度和日期必须在 `.task-menu-actions`。
- 远端 `10.20.11.3` 前端目标测试通过：`AppLayout.test.tsx`，19 个测试通过。
- 已在 `10.20.11.3` 重建并 recreate `frontend`，最终 `http://127.0.0.1:8080` 返回 `HTTP/1.1 200 OK`。

### 2026-06-16 任务中心四块布局视觉校正

状态：已在 `10.20.11.3` 验证并重建前端

- 用户指出当前视觉仍不像标注的四个方框：左上/右上/左下/右下没有明显拉开，详情和进度条仍显得过窄。
- 根因：虽然 DOM 已按 `header/meta/body/actions` 分区，但弹层整体宽度只有 420px，右侧列和间距占用后，左侧区域不足；同时 `.task-progress` 未明确 `display:block;width:100%`，视觉上没有铺满左下详情区。
- 已将任务菜单宽度从 `420px` 提升到 `520px`，保持小屏时仍受 `calc(100vw - 32px)` 约束。
- 已将右侧进度/日期列从 `86px` 收窄为 `72px`，减少对左侧四块主体区域的挤压。
- 已让 `.task-progress` 明确 `display:block;width:100%`，使左下详情区的红色进度条贴合该区域宽度。
- 远端 `10.20.11.3` 前端目标测试通过：`AppLayout.test.tsx`，19 个测试通过。
- 已在 `10.20.11.3` 重建并 recreate `frontend`，最终 `http://127.0.0.1:8080` 返回 `HTTP/1.1 200 OK`。

### 2026-06-16 任务中心 2x2 信息布局

状态：已在 `10.20.11.3` 验证并重建前端

- 用户指出四列布局仍会把详情区域挤窄，期望布局为：左上角标题、右上角 `确认/X`、左下角详情、右下角进度和时间。
- 根因：独立按钮列处于整张卡片中间，会从标题和详情共同可用宽度中扣除，导致详情仍过早省略。
- 已将任务卡片改为两列两行区域布局：`header/meta` + `body/actions`。
- 左上 `header` 包含状态图标、标题和右侧操作按钮；右上 `meta` 只显示进度百分比；左下 `body` 显示详情、步骤、日志、下载和进度条；右下 `actions` 显示日期时间。
- 详情区域保留完整 `title` 悬停提示，并且可用宽度不再被中间按钮列单独切开。
- 已补前端测试覆盖：标题和 `确认/X` 必须在同一个 header 区，详情必须在 body 区，进度必须在 meta 区，日期必须在 actions 区。
- 远端 `10.20.11.3` 前端目标测试通过：`AppLayout.test.tsx`，19 个测试通过。
- 已在 `10.20.11.3` 重建并 recreate `frontend`，最终 `http://127.0.0.1:8080` 返回 `HTTP/1.1 200 OK`。

### 2026-06-16 任务中心按钮独立列与进度时间保位

状态：已在 `10.20.11.3` 验证并重建前端

- 用户进一步澄清：进度百分比和日期时间位置不要动，`确认` 和 `X` 需要与标题同排，但不应挤占标题正文列。
- 根因：上一版把按钮放进标题行内部，视觉上和标题同排，但正文列宽没有改善，空间结构仍不符合预期。
- 已将任务卡片改为四列布局：状态图标、正文内容、操作按钮、进度日期。
- `确认` 和 `X` 现在位于独立 `.task-menu-controls` 列，顶部与标题行对齐；`.task-menu-actions` 继续只承载 `100%` 和两行日期时间。
- 已补前端测试覆盖：按钮必须在 `.task-menu-controls`，不得在标题行内部；进度必须保留在 `.task-menu-actions`，不得进入按钮列。
- 远端 `10.20.11.3` 前端目标测试通过：`AppLayout.test.tsx`，19 个测试通过。
- 已在 `10.20.11.3` 重建并 recreate `frontend`，最终 `http://127.0.0.1:8080` 返回 `HTTP/1.1 200 OK`。

### 2026-06-16 Phase 27 任务中心四区布局与详情可读性收尾

状态：已在 `10.20.11.3` 验证并重建前端

- 用户最终确认本轮只做详情显示方案 1、2，并把前面任务中心卡片 UI 调整一并收敛：左上角标题，右上角 `确认/X`，左下角详情和进度条，右下角百分比和日期时间。
- 红灯测试阶段：远端 `AppLayout.test.tsx` 先因详情缺少完整 `aria-label` 失败，证明测试覆盖到“悬停/无障碍保留完整详情”的要求。
- 实现调整：
  - `frontend/src/components/AppLayout.tsx` 保持 `.task-menu-header-row`、`.task-menu-controls`、`.task-menu-body`、`.task-menu-actions` 四个直接区域；`确认/X` 位于右上控件区，百分比和 `TaskDate` 位于右下动作区。
  - 详情 `<small>` 增加 `task-menu-detail`、完整 `title` 和完整 `aria-label`。
  - `frontend/src/styles/global.css` 将 `.task-menu-actions` 设为 `align-self: stretch`、`justify-content: flex-end`，让告警任务和普通信息任务的百分比/日期时间都落到真实右下角。
  - `.task-menu-detail` 改为两行 line clamp、允许换行和任意位置断行，避免长采集异常详情只显示一行。
- 远端验证：
  - `10.20.11.3` Node 容器内运行 `src/components/AppLayout.test.tsx`，19 个测试通过。
  - 已重建并 recreate `frontend`。
  - `curl -fsSI http://127.0.0.1:8080` 返回 `HTTP/1.1 200 OK`。
- 计划文件同步：`task_plan.md` Phase 27 已标记完成；`docs/superpowers/plans/2026-06-16-task-menu-four-zone-layout.md` 所有步骤已勾选。
- 小错误记录：尝试用 `perl -0pi` 批量勾选计划文件时因临时文件创建受限失败，已改用 `apply_patch` 完成，没有影响源码。

### 2026-06-16 任务中心步骤/日志提示与宽度收敛

状态：已在 `10.20.11.3` 验证并重建前端

- 用户反馈主详情悬停有 label，但下面框内步骤/日志显示不全且悬停没有完整 label；同时 UI 结构已经稳定，任务菜单宽度可以适当缩小。
- 根因：主详情 `.task-menu-detail` 已有完整 `title/aria-label`，但 `task.steps` 和 `task.logs` 的内部 `<span>` 没有 `title/aria-label`；菜单宽度仍保留上一轮调大后的 520px。
- 按 TDD 补远端红灯测试：要求步骤 `失败 校验镜像` 和日志 `镜像 sha256 不匹配：images/web-api.tar` 都能通过 `title` 找到并带有 `aria-label`；旧实现按预期失败。
- 实现：
  - `frontend/src/components/AppLayout.tsx` 给步骤行和日志行补完整 `title/aria-label`。
  - `frontend/src/styles/global.css` 将 `.task-menu` 宽度从 `520px` 收敛到 `480px`，右侧列和四区布局不变。
- 远端验证：
  - `10.20.11.3` Node 容器内运行 `src/components/AppLayout.test.tsx`，19 个测试通过。
  - 已重建并 recreate `frontend`。
  - recreate 后首次 curl 遇到 nginx 刚启动的 `Recv failure: Connection reset by peer`，等待 3 秒复查返回 `HTTP/1.1 200 OK`。

### 2026-06-16 撤销平台自检功能

状态：已在 `10.20.11.3` 验证并重建

- 用户明确要求去掉平台自检功能，原因是页面过重，并且采集失败会连带显示多个 critical/warning，现场观感复杂。
- 移除范围：
  - 后端 `/api/admin/system/self-check` GET/POST 路由。
  - `backend/app/v2/self_check` 模块。
  - `scripts/verify_platform.py` CLI。
  - 升级成功后的 quick self-check 自动记录和 `升级后自检异常/升级后存在需关注项` 告警。
  - 服务管理页 `平台自检` 卡片、快速自检/深度自检/报表验证按钮及样式。
  - 对应后端、CLI、前端测试。
- 保留范围：
  - `DataQualityService` 和报表 `data_quality` 字段。
  - 报表页、Word、Excel 的“数据质量说明”，用于解释报表可信度。
  - 平台升级页已有的版本、服务状态、升级包和清理旧版本能力。
- 文档收口：
  - `task_plan.md` Phase 25 已改为撤销状态，不再把平台自检写成当前能力。
  - README 中英文、部署文档、升级中心文档和 API 合同均说明自检面板/API/CLI 已移除。
- 本地验证：
  - `PYTHONPYCACHEPREFIX=/private/tmp/codex-pycache python3 -m py_compile backend/app/v2/api.py backend/app/v2/upgrade/service.py backend/app/v2/reports/export.py backend/tests/test_v2_upgrade.py` 通过。
  - `git diff --check` 通过。
  - 运行时代码残留扫描只剩 `ServicePage.test.tsx` 的负向断言。
- 远端验证：
  - 已同步到 `10.20.11.3:/data/smartx-storage-forecast/project`，并删除远端遗留的 `backend/app/v2/self_check`、`scripts/verify_platform.py`、`backend/tests/test_v2_self_check.py`、`backend/tests/test_verify_platform_cli.py`。
  - 后端目标测试通过：使用 `nazawsze/smartx-hci-capacity-insight-web-api:v0.5.0` 挂载最新 `backend/app` 和 `backend/tests`，运行 `tests.test_v2_upgrade tests.test_v2_data_quality tests.test_v2_reports tests.test_v2_report_exports`，共 52 个测试通过。
  - 前端目标测试通过：`src/pages/ServicePage.test.tsx src/pages/ReportsPage.test.tsx`，共 25 个测试通过。
  - 已重建并 recreate `web-api`、`frontend`。
  - `/api/system/health` 返回 `ok=true`、版本 `v0.5.0`、runner `v0.3.0`；frontend `8080` 返回 `HTTP/1.1 200 OK`。
  - `/api/admin/system/self-check` 返回 `404 {"detail":"Not Found"}`。
  - 重建后的 `web-api` 容器内不存在 `/app/app/v2/self_check`，且 `app.v2.self_check` 不可导入。

### 2026-06-17 报表页顶部右侧紧凑信息栈实现

状态：已在 `10.20.11.3` 验证并重建前端

- 已将报表页顶部改为左侧 `集群预测报表` + 右侧紧凑信息栈。
- 右侧信息栈包含 `历史样本窗口`、`容量增长速率`、`数据质量摘要` 三张卡片，不再被左侧报表卡片等高拉伸。
- 已将数据质量摘要从左侧报表卡片移除，避免重复展示；右侧摘要只显示核心状态、实际窗口、缺采天数、样本状态和不完整集群。
- 不完整集群按集群名显示，一行一个，不再显示 Tower 前缀。
- 已更新 `ReportsPage.test.tsx` 覆盖：左侧不再包含数据质量摘要、右侧三张卡存在、缺少 `data_quality` 时显示未知状态。
- 已清理旧左侧数据质量卡片 CSS 和未使用的 `dataQualitySampleHint`。
- 本地轻量检查：`rg` 未发现旧类/未使用函数残留；`git diff --check` 通过。
- 远端验证：
  - 已同步 `ReportsPage.tsx`、`ReportsPage.test.tsx`、`global.css` 和计划文件到 `10.20.11.3:/data/smartx-storage-forecast/project`。
  - 已在远端 Node 容器内运行 `src/pages/ReportsPage.test.tsx`，8 个测试通过。
  - 已在远端重建并 recreate `frontend`。
  - `http://10.20.11.3:8080` 返回 `HTTP/1.1 200 OK`。
  - `http://10.20.11.3:8000/api/system/health` 返回 `ok=true`，版本为 `v0.5.0`，Runner 版本为 `v0.3.0`。
- 视觉截图说明：本机缺少 `npx`，当前 Playwright CLI 包装器不可用；本轮未执行浏览器截图复核。

### 2026-06-17 报表页右侧 KPI 卡两列修正

状态：已在 `10.20.11.3` 验证并重建前端

- 用户截图反馈右侧 `历史样本窗口` 和 `容量增长速率` 被竖向排列，未按预期各占一半。
- 根因：`.report-side-stack` 只设置了 `display: grid`，没有定义两列，浏览器默认按单列布局。
- 已将 `.report-side-stack` 改为 `repeat(2, minmax(0, 1fr))`，两张 KPI 卡位于同一行各占一半。
- 已将 `.report-quality-summary-card` 设置为 `grid-column: 1 / -1`，数据质量摘要继续在下方跨两列。
- 1280px 以下右侧栈保持两列；960px 以下沿用单列响应式。
- 远端验证：
  - `10.20.11.3` Node 容器内 `src/pages/ReportsPage.test.tsx` 8 个测试通过。
  - 已重建并 recreate `frontend`。
  - `http://10.20.11.3:8080` 返回 `HTTP/1.1 200 OK`。
  - `/api/system/health` 返回 `ok=true`，版本为 `v0.5.0`。
  - 线上 CSS 已确认包含 `.report-side-stack{grid-template-columns:repeat(2,minmax(0,1fr))}` 和 `.report-quality-summary-card{grid-column:1 / -1}`。

### 2026-06-17 报表页预测卡等高与数据质量四窗口修正

状态：已在 `10.20.11.3` 验证并重建前端

- 用户截图反馈：
  - `集群预测报表` 左侧卡片下方空白没有补齐到右侧 `数据质量摘要` 底线。
  - `数据质量摘要` 需要按参考图拆成 4 个窗口，而不是标签流。
- 已将 `.report-top-row` 改回 `align-items: stretch`，左侧预测报表卡随右侧区域等高拉伸。
- 已将 `.report-forecast-card` 设置为纵向 flex 卡片，使空白自然留在卡片内部而不是页面外。
- 已重构 `DataQualitySummary`：
  - `实际采集窗口` 窗口：显示天数和起止日期。
  - `缺采` 窗口：显示缺采天数和说明。
  - `样本` 窗口：显示样本足够/不足和解释。
  - `不完整集群` 窗口：显示不完整集群数量和集群名称，仍不显示 Tower 前缀。
- 已更新 `ReportsPage.test.tsx`，断言数据质量摘要内存在 4 个 `.report-quality-window`。
- 远端验证：
  - `10.20.11.3` Node 容器内 `src/pages/ReportsPage.test.tsx` 8 个测试通过。
  - 已重建并 recreate `frontend`。
  - `http://10.20.11.3:8080` 返回 `HTTP/1.1 200 OK`。
  - `/api/system/health` 返回 `ok=true`，版本为 `v0.5.0`。
  - 线上 CSS 已确认包含 `.report-top-row{...align-items:stretch}`、`.report-quality-summary-grid{grid-template-columns:repeat(4,minmax(0,1fr))}` 和 `.report-quality-window{...}`。

### 2026-06-17 数据质量摘要 2x2 窗口布局修正

状态：已在 `10.20.11.3` 验证并重建前端

- 用户反馈数据质量摘要内部 4 个窗口需要两两一行，每行两个窗口。
- 已将 `.report-quality-summary-grid` 从 4 列改为 `repeat(2, minmax(0, 1fr))`。
- 960px 以下继续保持两列，560px 以下降为单列。
- `集群预测报表` 与右侧数据质量摘要底部齐平的规则保持不变：`.report-top-row` 仍为 `align-items: stretch`，`.report-forecast-card` 仍为纵向 flex。
- 远端验证：
  - `10.20.11.3` Node 容器内 `src/pages/ReportsPage.test.tsx` 8 个测试通过。
  - 已重建并 recreate `frontend`。
  - `http://10.20.11.3:8080` 返回 `HTTP/1.1 200 OK`。
  - `/api/system/health` 返回 `ok=true`，版本为 `v0.5.0`。
  - 线上 CSS 已确认包含 `.report-quality-summary-grid{grid-template-columns:repeat(2,minmax(0,1fr))}`，且 `.report-top-row` 仍为 `align-items:stretch`。

### 2026-06-17 数据质量状态标题口径修正

状态：已在 `10.20.11.3` 验证并重建前端

- 用户反馈右侧数据质量卡片不需要额外显示 `数据质量摘要` 标题，状态本身应作为卡片主标题。
- 已移除报表页右侧数据质量卡片的外层 `Card title`，不再显示 `数据质量摘要`。
- 已将数据质量状态文案统一为：`ok` 显示 `数据质量正常`，非 `ok` 或缺失数据质量字段统一显示 `数据质量需关注`。
- 已更新 `ReportsPage.test.tsx`，先验证旧实现失败，再完成实现后在远端跑绿。
- 远端验证：
  - `10.20.11.3` Node 容器内 `src/pages/ReportsPage.test.tsx` 8 个测试通过。
  - 已重建并 recreate `frontend`。
  - `http://10.20.11.3:8080` 返回 `HTTP/1.1 200 OK`。
  - `/api/system/health` 返回 `ok=true`，版本为 `v0.5.0`。

### 2026-06-16 任务中心菜单宽度收敛与平台自检残留复查

状态：已在 `10.20.11.3` 验证并重建前端

- 用户反馈任务菜单仍有明显空白，截图中详情列和右侧百分比/日期列之间浪费空间。
- 已将任务菜单宽度从 `480px` 收敛到 `420px`，移动端边距从 `32px` 收敛到 `24px`。
- 已将任务卡片右侧状态列从 `112px` 收敛到 `78px`，列间距从 `16px` 收敛到 `8px`，左右 padding 从 `18px` 收敛到 `14px`。
- 四区布局保持不变：左上标题、右上确认/X、左下详情和进度条、右下百分比和日期时间。
- 已补前端测试守护任务菜单紧凑布局，避免后续又出现大块空白。
- 本地验证：
  - `git diff --check` 通过。
  - 平台自检运行时代码残留扫描只剩 `ServicePage.test.tsx` 的负向断言。
- 远端验证：
  - `10.20.11.3` Node 容器内运行 `src/components/AppLayout.test.tsx src/pages/ServicePage.test.tsx`，共 39 个测试通过。
  - 远端源码目录扫描平台自检残留，只剩服务管理页负向测试。
  - 远端 `web-api` 容器内不存在 `/app/app/v2/self_check`，且 `app.v2.self_check` 不可导入。
  - `/api/admin/system/self-check` 返回 `404 {"detail":"Not Found"}`。
  - 已重建并 recreate `frontend`，最终 `http://127.0.0.1:8080` 返回 `HTTP/1.1 200 OK`。

### 2026-06-15 任务中心日期位置优化

状态：已在 `10.20.11.3` 验证并重建前端

- 用户反馈告警日期放在详情正文里不容易看到，建议放到右下角，并且所有任务都需要显示日期。
- 已将任务日期统一放到任务卡片右侧操作区底部：告警任务显示 `告警日期`，普通任务显示 `任务日期`。
- 日期继续使用任务 `createdAt`，不受确认、已读或状态更新导致的 `updatedAt` 变化影响。
- 已调整右侧操作区 CSS：上方显示进度/确认/移除按钮，下方右对齐显示日期。
- 已补前端测试覆盖：告警日期位于 `.task-menu-actions`，普通成功任务也显示右下角任务日期。
- 远端 `10.20.11.3` 前端目标测试通过：`AppLayout.test.tsx`，19 个测试通过。
- 已在 `10.20.11.3` 重建并 recreate `frontend`，最终 `http://127.0.0.1:8080` 返回 `HTTP/1.1 200 OK`。

### 2026-06-15 任务中心日期显示防截断优化

状态：已在 `10.20.11.3` 验证并重建前端

- 用户反馈右下角日期仍显示不全，并建议不要增加 `任务日期`、`告警日期` 字样。
- 已将任务卡片右下角可见日期改为两行纯数字：第一行 `YYYY/M/D`，第二行 `HH:mm:ss`。
- 已将 `任务日期/告警日期` 语义保留在 `title` 和 `aria-label`，不再占用可见宽度。
- 已将日期块字体缩小到 9px、宽度收紧到 84px，减少与进度和操作按钮抢空间。
- 远端 `10.20.11.3` 前端目标测试通过：`AppLayout.test.tsx`，19 个测试通过。
- 已在 `10.20.11.3` 重建并 recreate `frontend`，最终 `http://127.0.0.1:8080` 返回 `HTTP/1.1 200 OK`。

### 2026-06-15 任务中心标题行操作按钮优化

状态：已在 `10.20.11.3` 验证并重建前端

- 用户建议将告警任务的 `确认` 和 `X` 放到标题一行的最后，避免按钮挤占正文和日期区域。
- 已将任务菜单标题行改为 `图标 + 标题 + 右侧按钮组`，`确认` 和 `X` 归入 `.task-menu-title-actions`。
- 右侧区域现在只保留进度百分比和两行日期时间；标题过长时标题省略，按钮保持完整显示。
- 已补前端测试覆盖：`确认任务告警` 和 `从任务中心移除` 按钮必须位于 `.task-menu-title-row` 内。
- 远端 `10.20.11.3` 前端目标测试通过：`AppLayout.test.tsx`，19 个测试通过。
- 已在 `10.20.11.3` 重建并 recreate `frontend`，最终 `http://127.0.0.1:8080` 返回 `HTTP/1.1 200 OK`。

后续调整：

- 用户进一步建议按钮放在 `100%` 上面更好；当前最新实现已采用右侧列布局，此标题行方案已被替代。

### 2026-06-15 任务中心右侧列操作按钮优化

状态：已在 `10.20.11.3` 验证并重建前端

- 用户建议将 `确认` 和 `X` 放到右侧 `100%` 上方，形成更清楚的右侧操作列。
- 已将任务菜单右侧改为自上而下：`确认 / X`、进度百分比、两行日期时间。
- 标题行恢复只显示标题，减少右侧按钮对标题宽度的挤压。
- 已补前端测试覆盖：`确认任务告警` 和 `从任务中心移除` 必须位于 `.task-menu-actions` 内，并且 DOM 顺序在 `100%` 前面。
- 远端 `10.20.11.3` 前端目标测试通过：先用新测试验证旧标题行布局失败，再完成实现后 `AppLayout.test.tsx` 19 个测试通过。
- 已在 `10.20.11.3` 重建并 recreate `frontend`，最终 `http://127.0.0.1:8080` 返回 `HTTP/1.1 200 OK`。

### 2026-06-15 任务中心详情完整提示与按钮上移

状态：已在 `10.20.11.3` 验证并重建前端

- 用户反馈采集异常详情 `采集异常：重试 3/3 后仍有 1 个集群失败...` 显示不全，鼠标悬停也没有完整内容，并希望 `确认` 和 `X` 再往上放。
- 根因：任务详情文本使用 ellipsis 省略，但详情节点没有完整 `title`；右侧操作列使用 `justify-content: flex-end`，导致按钮整体靠下。
- 已将任务详情 `<small>` 增加 `task-menu-detail` class 和完整 `title`，鼠标悬停可看到完整失败说明。
- 已将右侧 `.task-menu-actions` 改为顶部对齐，`确认 / X` 按钮贴近卡片顶部，下面依次显示 `100%` 和日期时间。
- 已补前端测试覆盖：失败详情必须存在完整 `title`，并继续验证按钮位于右侧操作列且在 `100%` 前面。
- 远端 `10.20.11.3` 前端目标测试通过：先用新测试验证旧实现失败，再完成实现后 `AppLayout.test.tsx` 19 个测试通过。
- 已在 `10.20.11.3` 重建并 recreate `frontend`，最终 `http://127.0.0.1:8080` 返回 `HTTP/1.1 200 OK`。

### 2026-06-23 生产等价测试环境规划

状态：已写入规划文件，未提交

- 用户指出 `10.20.0.6` 生产类环境暴露了报表日增长 VM 名称缺失，而 `10.20.11.3/10.20.11.12` 没有提前发现，说明当前测试环境无法稳定代表生产交付。
- 已将该问题收敛为 Phase 29：生产等价测试环境与发布验收门禁。
- 已在 `task_plan.md` 明确三类环境：
  - `10.20.11.3` 作为 dev/debug，允许本地构建、热修和数据污染。
  - `10.20.11.12` 作为 upgrade rehearsal，用于受控升级演练。
  - 独立 `release canary` 作为正式验收环境，只使用 DockerHub/tag 镜像和正式部署脚本。
- 已补充发布门禁流程：`dev2 -> main -> tag -> Actions 构建 -> DockerHub tag 镜像 -> canary 全新部署 -> 后端/前端/升级包/数据契约验收 -> Release`。
- 已补充固定验收用例：Dashboard 日/月增长、报表日/月增长 VM 名称、数据质量、任务中心、升级中心 sha256、采集失败与部分成功。
- 已补充反污染规则：canary 禁止本地 build、禁止容器内热修、发现问题后必须回流代码并重新从 tag 镜像部署验证。
- 已在 `findings.md` 记录本次根因：最终交付物未被独立验收、测试环境被开发/升级/热修状态混用、缺少真实 API 数据契约覆盖。

### 2026-06-23 Compose Project/Network 固定化规划

状态：已写入规划文件，未提交

- 用户指出根修复应在所有 `docker-compose*.yml` 中写顶层 project name，并固定 network name，使常规 `docker compose up -d` 不依赖目录名。
- 已将该问题收敛为 Phase 30：Compose Project/Network 固定化与升级链路修复。
- 已在 `task_plan.md` 写明实施口径：
  - 三个 Compose 文件顶层增加 `name: smartx-hci-capacity-insight`。
  - 三个 Compose 文件固定网络真实名称 `smartx-hci-capacity-insight-net`。
  - `SMARTX_COMPOSE_PROJECT_NAME` 统一为 `smartx-hci-capacity-insight`。
  - 后端服务状态读取保留当前容器 label fallback，兼容历史现场。
  - Runner `compose.apply` 和 `rollback.restore` 必须继续使用同一 project name。
- 已在 `findings.md` 记录 `10.20.0.6` 的真实根因：用户使用正常部署命令，Compose 根据目录名生成 project，而程序配置仍按旧 project 查询 Docker。
- 明确生产边界：`10.20.0.6` 后续只做只读诊断；任何写操作、恢复操作或 recreate 都必须先列命令并等待用户明确确认。


### 2026-06-23 Compose Project/Network 固定化实施

状态：本地目标测试通过，未提交

- 已在三个 Compose 文件顶层增加 `name: smartx-hci-capacity-insight`。
- 已固定 Docker 网络真实名称为 `smartx-hci-capacity-insight-net`，服务仍使用逻辑网络 `smartx-net`。
- 已统一 `SMARTX_COMPOSE_PROJECT_NAME=smartx-hci-capacity-insight`，并同步 web-api、Runner、系统重启和配置默认值。
- 已保留并完善服务状态 fallback：配置 project 查不到时，从当前容器 label 反查真实 Compose project，并在 verification 中返回实际读取到的 project。
- 已更新部署文档：推荐普通 `docker compose -f docker-compose.offline.yml up -d`，旧 Compose 可显式使用 `--project-name smartx-hci-capacity-insight`。
- 本地验证通过：`PYTHONPATH=. pytest tests/test_deployment_config.py tests/test_v2_upgrade.py -k 'compose_project_name_is_consistent or discovers_actual_compose_project or verification_reports_service_statuses or falls_back_to_docker_ps' -q`，3 passed。
- 本地验证通过：`PYTHONPATH=. pytest tests/test_upgrade_runner_engine.py -k 'rollback_restores_old_files_removes_new_files_and_recreates_services' -q`，1 passed。
- 未对 `10.20.0.6` 执行任何写操作。

### 2026-06-24 发布验收体系、Smoke 脚本与测试补齐

状态：已实现，目标测试通过；正式 canary 部署/升级验收待选定非生产环境后执行

- 新增 `docs/release-acceptance.md`，明确 `dev/debug`、`upgrade rehearsal`、`release canary` 三类环境职责，以及 canary 禁止本地 build、禁止容器内热修、必须使用最终 tag 镜像和正式升级包的反污染规则。
- 新增 `scripts/release_smoke_check.py`，提供只读 release smoke 检查；未提供账号密码时只检查 frontend、Prometheus 和 `/api/system/health`，提供账号密码后补查任务中心、报表 API、升级版本、组件版本、Prometheus 组件和升级 verification。
- 补充 `ReportsPage.test.tsx` 契约测试：既覆盖 `v0.5.1` 顶层 `vm_name/vm_id`，也覆盖 legacy `labels.vm/labels.vm_id`，确保日增长和月增长 VM 名称不空、不显示 `undefined`。
- 补充 `test_v2_upgrade.py` 服务状态 happy path：compose project 一致时 verification 返回 `web-api`、`collector-worker`、`frontend`、`prometheus`、`upgrade-runner` 五个服务，并识别 Prometheus `v2.55.1`。
- 补充 `test_upgrade_runner_engine.py`：`compose.apply` 必须带 `--project-name smartx-hci-capacity-insight`。
- 本地验证通过：`python3 -m py_compile scripts/release_smoke_check.py`。
- 本地验证通过：`PYTHONPATH=. pytest tests/test_v2_upgrade.py -k 'verification_reports_all_services_when_compose_project_matches or verification_discovers_actual_compose_project or verification_falls_back_to_docker_ps' -q`，3 passed。
- 本地验证通过：`PYTHONPATH=. pytest tests/test_upgrade_runner_engine.py -k 'compose_apply_uses_configured_project_name or rollback_restores_old_files_removes_new_files_and_recreates_services' -q`，2 passed。
- 远端 `10.20.11.3` Node 容器前端目标测试通过：`ReportsPage.test.tsx` 10 tests passed。第一次运行被 macOS `._ReportsPage.test.tsx` 资源叉文件干扰，删除临时测试副本里的 `._*` 后测试通过。
- 本轮未对 `10.20.0.6` 执行任何操作。

### 2026-06-24 报表页容量增长速率算法优化规划

状态：已写入规划文件，未改代码

- 用户反馈报表页左侧预测有增长，但右侧“容量增长速率”显示 `0 B/天`，并进一步提出增长速率算法需要贴近实际预算。
- 只读检查确认当前后端 `cluster_growth_rate` 用最近 7 天首尾差，并通过 `max(0, value)` 把负增长压成 0。
- 只读查询 `10.20.11.3` `/api/reports/latest` 确认当前场景：近 7 天集群容量略下降，`cluster_growth_rate.per_day=0`；但 30 天预测斜率为正，左侧 90 天预测增长。
- 已将新口径写入 `task_plan.md` Phase 31：
  - 日增长使用最近一天净变化，可为负。
  - 月增长使用近 30 天趋势。
  - 季度增长使用近 90 天趋势。
  - 样本不足显示提示，完全不足显示“数据不足”。
  - 不改采集、Prometheus 写入或容量风险算法。
- 已在 `findings.md` 记录旧 7 天口径与新规划口径的差异，避免后续误读。

### 2026-06-24 v0.5.2 同版本升级兼容说明

状态：实施中，待最终验证

- 平台正式版本口径更新为 `v0.5.2`，README、部署/版本治理/升级中心设计和 release acceptance 文档同步说明。
- 平台升级包 manifest 新增/完善 `source_compatibility`，明确支持 `v0.5.0 -> v0.5.2`、`v0.5.1 -> v0.5.2` 和 `v0.5.2 -> v0.5.2`。
- 同版本应用定义为修复安装或重同步镜像、项目文件和 runtime override；迁移选择仍为 `source_version < step.version <= target_version`，因此不会重复选择 SQLite 迁移步骤。
- 服务管理页平台升级详情显示兼容来源版本，预检查步骤将来源版本兼容性与 Runner 协议能力一起展示。
- 未对生产环境 `10.20.0.6` 执行任何操作。

## 2026-06-27 v0.5.2 Compose Migration Implementation

- 将 runner 版本切换为 `v0.3.1`，新增 capability `compose.project_migrate.v1`。
- 新增 runner action `compose.project_migrate`：按旧 Compose project label 停止/删除容器，旧网络为空时删除；旧网络仍有外部容器则失败。
- `v0.5.2` 平台包构建器新增 `environment_transitions`，支持 `v0.5.0/v0.5.1 -> v0.5.2` 迁移到新 project/network。
- Compose 目标 project/network 统一为 `smartx-hci-capacity-insight` / `smartx-hci-capacity-insight-net`。

## 2026-06-27 v0.5.2 Runner Requirement Manifest Update

- 平台升级包 manifest 新增 `minimum_runner_version=v0.3.1`。
- web-api 预检查在 Runner 缺少 `compose.project_migrate.v1` 或无心跳时，会阻止升级并提示先升级 `upgrade-runner` 到 manifest 声明版本。
- `release-notes.md` 明确最低 Runner 版本和 `v0.5.2` 所需 Compose project/network 迁移能力。
- `10.20.11.3` 已重新生成平台升级包：`/data/upgrade-packages/smartx-capacity-insight-upgrade-v0.5.2.tar.gz`，SHA256 `f628a6e1505ac4844365330603d681afe6242943d3141fb53de891d8927d5ac9`。

## 2026-06-29 v0.5.0 到 v0.5.2 升级链路计划文档

- 新增独立文档 `docs/v0.5.0-to-v0.5.2-upgrade-plan.md`。
- 文档明确升级链路：`v0.5.0/v0.5.1 + runner v0.3.0 -> v0.5.1u2 + runner v0.3.0 -> runner v0.3.1 bootstrap -> v0.5.2 + runner v0.3.1`。
- 文档固定每个节点的 Docker Compose project、network name、subnet 和服务版本边界。
- 特别记录 `v0.5.1u2` 不能提前切到 `smartx-hci-capacity-insight` / `smartx-hci-capacity-insight-net`，否则会触发 Docker network pool overlap。

## 2026-06-29 v0.5.1u2-fix9 修补计划写入

状态：已写入规划文件，未改业务代码

- 用户要求这是最后一次，先写出 `v0.5.1u2-fix9` 的详细修补计划。
- 已确认之前 fix8 的问题不是 runner 未升级，而是 active runner version 和组件任务显示模型不完整。
- 现场事实：
  - 活动 runner 已是 `v0.3.1`。
  - web-api 容器内 `/app/RUNNER_VERSION=v0.3.0` 只是桥包 baseline。
  - 页面若显示 `v0.3.0`，说明读取了错误来源或前端使用了旧缓存。
- 已在 `task_plan.md` 新增 `Phase 32 v0.5.1u2-fix9 Runner Active Version 与组件升级显示修复`。
- 已在 `findings.md` 新增 `Phase 32 v0.5.1u2-fix9 Runner Active Version 根因发现`。
- fix9 计划明确：
  - active runner version 只能来自新鲜 heartbeat、running runner 容器 `/app/RUNNER_VERSION` 或 running runner 容器 image tag。
  - web-api `/app/RUNNER_VERSION` 不能作为当前 runner 版本。
  - runner 组件 task 必须稳定投影为 `component=upgrade-runner`。
  - 前端组件页必须绑定真实 task steps，不再展示平台默认“未执行”步骤。
  - fix9 包必须先在 `10.20.11.3` 构建和验证。

## 2026-06-29 v0.5.1u2-fix9 实施与构建

状态：已在 `10.20.11.3` 构建 fix9 包，等待用户按链路验证

- 后端修复：
  - active runner version 不再回落到 web-api `/app/RUNNER_VERSION`。
  - 新鲜 heartbeat 优先；heartbeat 超过 30 秒视为过期。
  - heartbeat 缺失或过期时读取 running `upgrade-runner` 容器内 `/app/RUNNER_VERSION`，再回落 running runner image tag。
  - 未检测到 active runner 时返回 `未检测到 runner`。
  - `history(component_type="runner")` 与 `_public_task()` 支持真实 task 形态 `components=["runner"]` 且顶层 `component` 缺失。
- 前端修复：
  - 组件页用统一 matcher 识别 `upgrade-runner`：`task.component === "upgrade-runner"` 或 `task.components` 包含 `runner`。
  - 目标版本、已选升级包、操作区、执行步骤和包列表状态都绑定真实 runner task。
  - 组件模式没有真实 steps 时不再展示平台默认“未执行”步骤。
- 本地验证：
  - `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_upgrade`：28 passed, 1 skipped。
  - `python3 -m py_compile backend/app/v2/upgrade/service.py backend/app/v2/system/health.py backend/tests/test_v2_upgrade.py`：通过。
  - `git diff --check -- backend/app/v2/upgrade/service.py backend/app/v2/system/health.py backend/tests/test_v2_upgrade.py frontend/src/pages/ServicePage.tsx frontend/src/pages/ServicePage.test.tsx frontend/src/types.ts frontend/src/styles/global.css`：通过。
  - `frontend` `tsc -b`：通过。
  - `frontend` `vitest run src/pages/ServicePage.test.tsx`：21 passed。
- `10.20.11.3` 验证：
  - 同步 fix9 定向文件到 `/home/user1/codex-build/devv2-v051u2-build`，保留 `VERSION=v0.5.1u2`、`RUNNER_VERSION=v0.3.0`。
  - `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_upgrade`：28 passed, 1 skipped。
  - 远端未安装 node/npm/pnpm，前端单测无法在该用户环境直接执行；前端代码已由本地单测与 tsc 验证，并通过远端 Docker 构建进入镜像。
  - package manifest 闸门通过：`version=v0.5.1u2`、`min_version=v0.5.0`、无 `minimum_runner_version`、required capabilities 保持 legacy runner v0.3.0 能力。
  - package components 只有 platform，未包含 runner 镜像。
  - package compose defaults 仍为 `smartx-storage-forecast` / `smartx-storage-forecast_smartx-net`，未切到 `smartx-hci-capacity-insight-net`。
  - web-api 镜像内确认包含 `RUNNER_NOT_DETECTED`、`_active_runner_state_from_docker`、`_component_types_from_task`。
- fix9 包：
  - path: `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2-fix9/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz`
  - sha256: `724265634635c50e079f6e2576c51dc294a83ddfabf4c85a631ee6990cdb6f4b`
- runner v0.3.1 包沿用：
  - path: `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/02-runner-v0.3.1-bootstrap/smartx-upgrade-runner-v0.3.1.tar.gz`
  - sha256: `2dcd14e633512b4a95254ea1dd299b4a2513bd64726e72d4e1cc2e75cdd633aa`

## 2026-06-29 v0.5.1u2-fix10 来源版本兼容补充

状态：已在 `10.20.11.3` 构建 fix10 包，等待用户按链路验证

- 用户在 UI 中发现 `v0.5.1u2` 包的“兼容来源版本”只显示 `v0.5.0`、`v0.5.1`、`v0.5.1u2`，没有 `v0.5.1u1`。
- 判断：`v0.5.1u1 -> v0.5.1u2` 应该支持；这是 manifest `source_compatibility.supported_versions` 漏列，不是 runner 或前端显示 bug。
- 修复：
  - 本地 `scripts/build_upgrade_package.py` 的 patch source versions 加入 `v0.5.1u1`。
  - `10.20.11.3` 的 `/home/user1/codex-build/devv2-v051u2-build/scripts/build_upgrade_package.py` 专用 `v0.5.1u2` 分支返回 `["v0.5.0", "v0.5.1", "v0.5.1u1", "v0.5.1u2"]`。
- 10.20.11.3 构建：
  - path: `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2-fix10/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz`
  - sha256: `b976ef8c761271ac06cd8bd3e23d3394a84360ea189e46b1042bc2ced70651df`
- manifest 闸门：
  - `version=v0.5.1u2`
  - `min_version=v0.5.0`
  - `source_compatibility.supported_versions=["v0.5.0","v0.5.1","v0.5.1u1","v0.5.1u2"]`
  - no `minimum_runner_version`
  - required capabilities 保持 legacy runner v0.3.0 能力
  - components 只有 platform
  - no runner image archive
  - compose defaults 仍为 `smartx-storage-forecast` / `smartx-storage-forecast_smartx-net`
- fix10 沿用 fix9 的 active runner version 与组件任务显示修复；只额外补充 `v0.5.1u1` 来源兼容。

## 2026-06-30 v0.5.2 Prometheus 迁移问题计划写入

状态：已写入规划文件，未改业务代码

- 用户要求先把 Prometheus 修复计划写进相关 Markdown。
- 已确认用户最终决策：
  - v0.5.2 不额外打包 Prometheus 镜像。
  - 不新增单独 Prometheus 组件包语义。
  - Prometheus 作为 v0.5.2 平台 compose 重建服务处理。
- 已在 `10.20.11.3` 完整复现并定位：
  - 默认目录 `/data/smartx-storage-forecast/project` 可部署 `v0.5.1 + runner v0.3.0`。
  - 正常升级 `v0.5.1 -> v0.5.1u2` 成功。
  - 正常升级 `runner v0.3.0 -> v0.3.1` 成功。
  - 正常升级 `v0.5.1u2 -> v0.5.2` 成功。
  - 最终 `version=v0.5.2`、`runner_version=v0.3.1`，但 `checks.prometheus=false`。
- 根因记录：
  - v0.5.2 compose 包含 Prometheus 服务。
  - manifest services 只声明平台三件套。
  - runner 只对 manifest services 执行 `compose.apply`。
  - 旧 project 被迁移清理后 Prometheus 容器被删除，但新 project 未创建 Prometheus。
- 已更新：
  - `task_plan.md`：新增 `Phase 34 v0.5.2 Prometheus Compose 重建修复计划`。
  - `findings.md`：新增 `Phase 34 v0.5.2 Prometheus 健康失败根因发现`。
- 下一步实施要求：
  - v0.5.2 manifest 的 platform services 增加 `prometheus`。
  - 不添加 `images/prometheus.tar`。
  - 预检查确认本地存在 `prom/prometheus:v2.55.1`。
  - 重新在 `10.20.11.3` 执行完整升级链路并要求最终 `checks.prometheus=true`。

## 2026-06-30 v0.5.2 Prometheus Compose 重建实现

状态：已实现，已构建 phase34 包，并已在 `10.20.11.3` 完整升级链路验证通过

- 实现内容：
  - `scripts/build_upgrade_package.py` 新增版本感知平台服务列表：目标版本 `>= v0.5.2` 时，platform services 和 `restart_services` 包含 `prometheus`。
  - v0.5.2 平台包 images 仍只包含 `web-api`、`collector-worker`、`frontend` 三个 tar，不包含 `images/prometheus.tar`。
  - `backend/app/v2/upgrade/service.py` 将 Prometheus 纳入平台 compose 可管理服务，但平台镜像加载仍只接受三件套。
  - 预检查会检查 manifest 中无 archive 的镜像。
  - 对 v0.5.2 平台包，预检查还会从 `project/docker-compose.offline.yml` 解析 `services.prometheus.image`；即使 manifest images 未声明 Prometheus，也会检查本地 Docker 镜像 `prom/prometheus:v2.55.1`。
- 新增/更新测试：
  - v0.5.2 平台包 manifest services/restart_services 包含 `prometheus`。
  - v0.5.2 平台包不包含 `images/prometheus.tar`。
  - 编译执行计划后 `compose.apply.params.services` 包含 `prometheus`。
  - manifest 无 archive 镜像缺失时预检查失败。
  - 包内 compose 声明 Prometheus、manifest images 未声明 Prometheus 时，预检查仍检查 compose 中的 Prometheus 镜像。
- 本地验证：
  - `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_package_builders backend.tests.test_upgrade_protocol backend.tests.test_v2_upgrade`
  - 结果：55 tests OK，1 skipped。
- `10.20.11.3` 单测验证：
  - 已将本轮核心文件同步到 `/home/user1/codex-build/devv2-v052-phase34`。
  - 远端执行同组单测通过：55 tests OK，1 skipped。
- phase34 包：
  - path: `/home/user1/codex-build/packages-v052-phase34/smartx-capacity-insight-upgrade-v0.5.2.tar.gz`
  - sha256: `b5487bbd3e96ecda748060ef31247e3528258905215b33265a3350e4fbf85111`
  - size: `245457484` bytes
- phase34 包静态闸门：
  - `version=v0.5.2`
  - platform services: `web-api`, `collector-worker`, `frontend`, `prometheus`
  - `restart_services`: `web-api`, `collector-worker`, `frontend`, `prometheus`
  - platform images only include `web-api.tar`, `collector-worker.tar`, `frontend.tar`
  - no `images/prometheus.tar`
  - packaged compose contains `prometheus` and `prom/prometheus:v2.55.1`
- `10.20.11.3` 完整链路验证：
  - 已重置为 `v0.5.1 + runner v0.3.0`，基线健康：`ok=true`, `version=v0.5.1`, `runner_version=v0.3.0`, `checks.prometheus=true`。
  - 正常升级 `v0.5.1 -> v0.5.1u2-fix10` 成功，任务 `upgrade-ea5c8223201ab3ee`，最终 `version=v0.5.1u2`, `runner_version=v0.3.0`, `checks.prometheus=true`。
  - 正常组件升级 `runner v0.3.0 -> v0.3.1` 成功，任务 `upgrade-de7a8270ae93e995`，最终 `version=v0.5.1u2`, `runner_version=v0.3.1`, `checks.prometheus=true`。
  - 正常升级 `v0.5.1u2 -> v0.5.2-phase34` 成功，任务 `upgrade-ebb685c6710ccd63`。
  - 最终健康：`ok=true`, `version=v0.5.2`, `runner_version=v0.3.1`, `checks.prometheus=true`。
  - `curl http://127.0.0.1:9090/-/healthy` 返回 `Prometheus Server is Healthy.`。
  - `http://10.20.11.3:8080/` 返回 HTTP 200。
  - Docker 最终容器：`web-api`, `collector-worker`, `frontend`, `prometheus`, `upgrade-runner` 均在 `smartx-hci-capacity-insight` project。
  - Docker 最终网络只剩 `smartx-hci-capacity-insight-net`，旧 `smartx-storage-forecast_smartx-net` 已清理。

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
