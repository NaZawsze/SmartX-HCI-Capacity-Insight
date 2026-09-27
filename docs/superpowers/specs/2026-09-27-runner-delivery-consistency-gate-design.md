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
| C4 `package_manifest` | 组件包 `manifest.json` 的 `version` == 仓库 `RUNNER_VERSION`；`components[].images[].sha256` == 镜像归档实测 SHA256；`min_version`/`compatibility.min_runner_version` 是**下界**（默认 `v0.1.0`），只作信息项、必须 ≤ 自身版本 | 未传 `--package` → SKIP |
| C5 `package_image` | **离线解析包内镜像归档**（docker-save/OCI 层）：`app/RUNNER_VERSION` == 仓库版本；`app/app/upgrade_runner/actions.py` 的 md5 == 仓库同名文件；动作集 == 仓库动作集（同一 AST 解析器） | 未传 `--package` → SKIP |
| C6 `dockerhub_tag` | DockerHub tags API 返回 200（tag 已推送） | 未传 `--check-dockerhub` → SKIP |
| 附加 `live_image` | 可选 `--image <ref> --live-probe`：用 docker 起容器读取版本文件与动作表（用于校验 registry 上拉下来的镜像） | 未给 `--live-probe` → SKIP |

- **任一 FAIL → 退出码 1**；SKIP 不算失败，但必须在输出里显式列出原因（避免"没检查"被当成"检查通过"）。
- C5 是这条门禁的核心：manifest 里的版本号是打包时写进去的字符串，只有**镜像内部**的版本文件与 `actions.py` 内容才能证明"这个包出自这份源码"。C5 的 md5 比对等价于 version-governance 要求的"组件包与仓库同源"。

## 3. 边界

- 只做核对，**不改任何制品**：不改 runner 代码、不改 `RUNNER_VERSION`、不重打包、不推 tag/镜像。
- 不替代 `build_upgrade_package.py --check-version`（管平台包与源码 compose 字面量）与 `verify_upgrade_package_identity.py`（管平台包镜像身份）；本脚本管 runner 组件包与 runner 镜像。
- **默认全离线、零副作用**：组件包检查直接从包内镜像归档的层里读文件，不 `docker load`、不改写本地 tag（在测试机上连续检查多个包时，`docker load` 会覆盖同 tag 镜像并让后续探测读到上一次的内容——见 §7）。只有显式的 `--live-probe` 才会用 docker。

## 4. 测试计划

本地与 `.3`：

1. 单测 `backend/tests/test_verify_runner_delivery_consistency.py`：AST 动作集解析（含 `post_upgrade.schedule_collection`）、源码 compose 字面量通过、manifest 版本不符 → FAIL、镜像归档 SHA 不符 → FAIL、SKIP 不计入失败、FAIL 时退出码非零。
2. `.3` 实证：对 `v0.3.2` 组件包（`/data/upgrade-packages/components-v032-20260927/`）与 `v0.3.1` 组件包（`/data/upgrade-packages/components-v053-20260927/`）各跑一次，记录 C1–C5 逐项结果。
3. 回归：`.3` 后端全量测试与构建测试，确认无新增失败。

## 5. 回滚

删除 `scripts/verify_runner_delivery_consistency.py` 与对应测试文件，撤销 `docs/release-acceptance.md` 步骤 4 的引用与 task_plan 第 54 项即可；不涉及运行时行为，无数据影响。

## 6. `.3` 实证与两处规则修正（2026-09-27 首跑）

对 `.3` 上两个真实组件包跑首版实现，暴露两处必须修正的地方（已改，见 §2）：

1. **`min_runner_version` 是下界、不是内容版本**：首版把它与 `RUNNER_VERSION` 做等值比较，`v0.3.2` 组件包因此误报 FAIL——组件包的 `min_version`/`compatibility.min_runner_version` 是 `build_runner_component_package.py` 的 `DEFAULT_MIN_VERSION`（`v0.1.0`），语义是"此版本及以上都可升级到此包"。改为"信息项 + 必须 ≤ 自身版本"。
2. **按 `RUNNER_VERSION` 拼镜像名探测会探错对象**：首版 `docker load` 包内镜像后固定探测 `…:<RUNNER_VERSION>`。连续检查两个包时，第二次探测读到的是**上一次 load 进去的镜像**，于是"v0.3.1 的包"报出了 v0.3.2 的内容 —— 假 PASS，而且会改写测试机本地同 tag 镜像。改为直接从包内镜像归档的 OCI/docker-save 层里读 `app/RUNNER_VERSION` 与 `app/app/upgrade_runner/actions.py`，去掉 `docker load`。

修正后实测（`.3`，2026-09-27）：

| 输入 | 结果 | 逐项 |
| --- | --- | --- |
| 仓库自检 | PASS（exit 0） | `RUNNER_VERSION=v0.3.2`、26 动作、三个 compose 字面量 |
| `components-v032-20260927/smartx-upgrade-runner-v0.3.2.tar.gz`（`3d99599c…`） | **PASS（exit 0）** | manifest v0.3.2、`min_runner_version=v0.1.0 (≤ v0.3.2)`、归档 SHA 一致、镜像内 `app/RUNNER_VERSION=v0.3.2`、`actions.py` md5 `732b0d94…` == 仓库、动作集 26 == 仓库 |
| `components-v053-20260927/smartx-upgrade-runner-v0.3.1.tar.gz`（`dd096bf2…`） | **FAIL（exit 1，符合预期）** | manifest v0.3.1 ≠ 仓库 v0.3.2；镜像内版本 v0.3.1 ≠ v0.3.2；`actions.py` md5 `e32afe45…` ≠ 仓库 `732b0d94…` |

第三行是这条门禁的价值证明：那个 v0.3.1 包的**动作集与仓库完全一致（都是 26 个）**，只有 `actions.py` 内容与版本号不同——只比"动作有哪些"或只看 manifest 版本号都抓不到，必须比文件内容。`.3` 副作用检查：探测前后运行容器镜像 ID 与 `…:v0.3.1` tag 均未变（`0aca32511008…`）。

## 7. 与 #47 其余子项的关系

本条只做 ② 的"硬门禁脚本"部分。US-02 的动作级预检查（`runner_actions`）已在 49-50 实施；①升级后采集改事件驱动（US-06）、③顺序写死（US-04 缓解，已写入文档）与 US-01（源端执行，无代码解法）仍归 pending-tasks #47，另立设计。
