# 设计：runner 交付一致性硬门禁（#47② / US-02）

状态：**已实施并验证**（2026-09-27，task_plan Phase 49 第 54 项）。问题台账 [upgrade-strategy-issues.md](../../upgrade-strategy-issues.md) US-02；立项 [pending-tasks.md](../../pending-tasks.md) #47。

## 1. 背景

同一版本号 `v0.3.1` 曾同时存在三副面孔：交付组件包（2026-07，25 动作、无 `post_upgrade.schedule_collection`）、远端仓库源码（26 动作、有该动作）、DockerHub（只有 `v0.3.0`，`v0.3.1` 从未推）。后果是 `.12` 用交付包首跑 v0.5.3 升级，在**平台已切换之后**才因 `Runner 不支持动作：post_upgrade.schedule_collection` 失败（task `upgrade-cede491efb9b1345`），前三轮用开发镜像的验收全部掩盖了缺陷（根因见 findings.md 2026-09-27）。

用户 2026-09-27 定下硬规则（AGENTS §8/§10-7、version-governance「Runner 能力与版本治理」）：**发布前必须核对三处同源**——①仓库 `RUNNER_VERSION` + 动作表；②runner 组件包（解包核对）；③DockerHub `runner-v<版本>` tag。但核对目前只写在 `docs/release-acceptance.md` 步骤 4 里靠人工逐个命令执行，没有可重复执行的工具，也没有进 CI。

同时现有构建脚本的校验不够：`build_runner_component_package.py::verify_runner_image()` 只校验镜像内**存在** 6 个必需 handler 与两项能力，**不比对**镜像与仓库是否同一份源码，也不校验镜像内 `/app/RUNNER_VERSION`；组件包 manifest 不含动作表（`required_capabilities: []`）。因此把任意旧镜像打成 `…:v0.3.2` 标签也能通过构建校验——这正是"同版本不同能力"的结构性缺口。

## 2. 目标与口径

新增 `scripts/verify_runner_delivery_consistency.py`，把三处同源核对变成一条可重复执行、退出码可判定的命令，供发布前门禁与验收记录使用。

判定规则：

| 检查 | 内容 | 缺前置条件时 |
| --- | --- | --- |
| C1 `repo_version` | 仓库 `RUNNER_VERSION` 可解析为 `v<major>.<minor>.<patch>` | — |
| C2 `repo_actions` | 从 `backend/app/upgrade_runner/actions.py` 的 `default_handlers()` 静态提取动作集（AST 解析，不 import 业务模块） | — |
| C3 `source_compose_literal` | 三个源码 compose 的 runner 镜像行 == `RUNNER_VERSION`，且不含任何 tag 模板变量（与 `build_upgrade_package.assert_source_compose_literal` 同口径） | — |
| C4 `package_manifest` | 组件包 `manifest.json` 的 `version`/`compatibility.min_runner_version` == 仓库 `RUNNER_VERSION`；`components[].images[].sha256` == 镜像归档实测 SHA256 | 未传 `--package` → SKIP |
| C5 `package_image` | 探测包内镜像：`/app/RUNNER_VERSION` == 仓库版本；`app/upgrade_runner/actions.py` 的 md5 == 仓库同名文件；handler 集 == 仓库动作集 | 无 docker 或 `--no-image-probe` → SKIP |
| C6 `dockerhub_tag` | DockerHub tags API 返回 200（tag 已推送） | 未传 `--check-dockerhub` → SKIP |

- **任一 FAIL → 退出码 1**；SKIP 不算失败，但必须在输出里显式列出原因（避免"没检查"被当成"检查通过"）。
- C5 是这条门禁的核心：manifest 里的版本号是打包时写进去的字符串，只有**镜像内部**的版本文件与 `actions.py` 内容才能证明"这个包出自这份源码"。C5 的 md5 比对等价于 version-governance 要求的"组件包与仓库同源"。

## 3. 边界

- 只做核对，**不改任何制品**：不改 runner 代码、不改 `RUNNER_VERSION`、不重打包、不推 tag/镜像。
- 不替代 `build_upgrade_package.py --check-version`（管平台包与源码 compose 字面量）与 `verify_upgrade_package_identity.py`（管平台包镜像身份）；本脚本管 runner 组件包与 runner 镜像。
- 唯一的次生副作用：`--package` 需要 `docker load` 组件包内的镜像归档（同内容重复导入，幂等；在测试机上是既有镜像的重新导入）。用 `--no-image-probe` 可完全避免。
- 默认离线：C6 需显式打开，避免在无外网环境把网络问题误报成交付不一致。

## 4. 测试计划

本地与 `.3`：

1. 单测 `backend/tests/test_verify_runner_delivery_consistency.py`：AST 动作集解析（含 `post_upgrade.schedule_collection`）、源码 compose 字面量通过、manifest 版本不符 → FAIL、镜像归档 SHA 不符 → FAIL、SKIP 不计入失败、FAIL 时退出码非零。
2. `.3` 实证：对 `v0.3.2` 组件包（`/data/upgrade-packages/components-v032-20260927/`）与 `v0.3.1` 组件包（`/data/upgrade-packages/components-v053-20260927/`）各跑一次，记录 C1–C5 逐项结果。
3. 回归：`.3` 后端全量测试与构建测试，确认无新增失败。

## 5. 回滚

删除 `scripts/verify_runner_delivery_consistency.py` 与对应测试文件，撤销 `docs/release-acceptance.md` 步骤 4 的引用与 task_plan 第 54 项即可；不涉及运行时行为，无数据影响。

## 6. 与 #47 其余子项的关系

本条只做 ② 的"硬门禁脚本"部分。US-02 的动作级预检查（`runner_actions`）已在 49-50 实施；①升级后采集改事件驱动（US-06）、③顺序写死（US-04 缓解，已写入文档）与 US-01（源端执行，无代码解法）仍归 pending-tasks #47，另立设计。
