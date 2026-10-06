# 版本偏斜支持矩阵（US-01）

## 1. 为什么需要这份矩阵

平台升级是 **web-api 编译计划 → 交给 upgrade-runner 执行** 的两段式。因此**当次升级用不到目标版本的新校验**——用到的逻辑来自源端 web-api：

- 源端 v0.5.2 收到 v0.5.3 的包，跑的是 v0.5.2 的编译器与预检查；
- v0.5.3 新增的动作级预检查、「同 project 不停 runner」等增强，**对 v0.5.2 → v0.5.3 这一次无效**，只对 v0.5.3 → 更高版本生效。

查证 Kubernetes version skew policy 后确认：**「旧版本组件执行升级、新版本逻辑当次不生效」是业界常态而非缺陷**（K8s 明确支持控制面与节点版本偏斜，升级时执行的就是旧 kubelet）。因此本项**不做代码级重构**，改用「矩阵写死 + 构建期门禁 + 实测」把它从隐患变成已知边界。

**推论（必须记住）**：任何"升级前加固"，只在**源端已含该逻辑**时才有保护作用。加固要么等下一版生效，要么在源端侧可独立生效（不依赖目标版本）。

## 2. 支持矩阵

| 源端 | → 目标 | 支持 | 当次生效的源端逻辑 | 备注 |
| --- | --- | --- | --- | --- |
| v0.5.1u2 + runner v0.3.1 | v0.5.3 | ✅ | v0.5.1u2 的编译/预检查 | **已发布基线**（GitHub Release `v0.5.1u2`：平台包 `d5f27716…` + runner v0.3.1 包 `d10e15cf…`，各带 `.sha256`）；**已实测**直升 v0.5.3（老桥接布局，AGENTS 固定链路的桥接节点） |
| v0.5.2 + runner v0.3.1 | v0.5.3 | ✅ | v0.5.2 的编译/预检查 | **现场主路径，已实测**：`upgrade-6f035c3e52b83428` succeeded + 8 项验收全过，runner 保持 v0.3.1 |
| v0.5.2 + runner v0.3.2 | v0.5.3 | ✅ | 同上 | **已实测**（US-26 判别格）：`upgrade-7c0720d6207ea942` succeeded，runner 保持 v0.3.2 未被降级 |
| v0.5.3 + runner v0.3.1 | v0.5.3（同版本重装） | ✅ | v0.5.3 全套 | **已实测**：`.12` `upgrade-b07795625cf0d681` succeeded（US-24 修复验证） |
| v0.5.3 + runner v0.3.2 | v0.5.3 | ✅ | v0.5.3 全套 | **已实测**（判别格）：`.12` `upgrade-2874d3eb97b67ce4` / `.14` `upgrade-326019438f66d8d1` succeeded，runner 保持 v0.3.2 |
| v0.5.0 / v0.5.1 / v0.5.1u1 | v0.5.3 | ⚠️ 声明支持但未实测 | 各自源端逻辑 | 早期布局；**未经端到端验收，不得对客户承诺** |
| v0.5.2 + runner v0.3.1 | v0.5.4 | ⚠️ 声明支持但**未实测**（**收窄后唯一合法的 v0.5.2 源格**） | v0.5.2 逻辑 | 计划动作集常量；已用已发布 v0.5.2 镜像内编译器**静态实测**（动作集与候选编译器一致）；**真机待批次 C0**（`.14` 先、`.12` 后，见 [upgrade-matrix-runbook](superpowers/plans/2026-10-06-upgrade-matrix-runbook.md) §6）——C1/C4 都从 v0.5.3 出发，覆盖不到本格 |
| v0.5.3 + runner v0.3.1/v0.3.2 | v0.5.4 | ⚠️ 声明支持但**未实测** | 各自源端逻辑 | 计划动作集常量；已用已发布 v0.5.3 镜像内编译器**静态实测**（动作集与候选编译器一致）；**真机待 C1**（v0.3.1 源）与 **C2→C4**（v0.3.2 源，US-26 判别格） |
| v0.5.0 / v0.5.1 / v0.5.1u1 / v0.5.1u2 | v0.5.4 | ⛔ 不支持 | — | 用户 2026-10-06 定案：v0.5.4 只支持目标布局（v0.5.2+），旧布局先升 v0.5.3（链路已验证）。矩阵全表见 [upgrade-chain.md](upgrade-chain.md) §7 |

`source_compatibility` 声明的权威来源是包 manifest，由 `scripts/build_upgrade_package.py::_source_compatibility()` 生成，由 `precheck.py::_check_source_compatibility()` 在**源端**校验。

## 3. 偏斜的三条硬规则

1. **默认先平台、后 runner**。唯一例外是平台确需更高 runner 能力（`minimum_runner_version` 高于现场）时先升 runner。
   顺序颠倒会让 v0.5.2 源端的 web-api 停掉刚启动的新 runner → 升级中断（US-04 根因，源端代码改不到，只能靠规则规避）。
2. **runner 不得被降级**。平台包对 runner 只有基线声明（`deploy: false`），现场 runner ≥ 基线时保持不动（US-26）。
3. **同一时刻只允许一个升级任务**（US-23 单飞守卫）。偏斜期间尤其重要——此时最容易出现"用错版本的任务在跑"。

## 4. 已发布 runner 能力基线（2026-09-30 逐字节核验）

验收基线一律用**已发布** runner 资产，不用开发期本地重建镜像。当前唯一已发布基线是 `runner v0.3.1`。

### 4.1 资产同源确认

| 来源 | 标识 | 结果 |
| --- | --- | --- |
| GitHub Release `v0.5.1u2` 组件包 | `smartx-upgrade-runner-v0.3.1.tar.gz` SHA `d10e15cf7b516d172ebe2f1bc37621f9cf32d8ab3abd548f808ae5c5de151d2c` | 包内镜像 `images/upgrade-runner.tar` |
| DockerHub `nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.1` | manifest digest `sha256:90eb5a4239cd9c6863cf7194bfa0bd7fe4935cffb0b5a77467c97ce0b78799fc` | 直接拉 manifest + 代码层比对 |

两处**同一个镜像**：config digest 同为 `sha256:19b8b3e445e728949cda55e0e68ecd71e4b537df05f1c598b7581746c3d03e0c`，
`actions.py` / `main.py` / `engine.py` / `lease.py` / `store.py` / `sandbox.py` 六个文件逐字节一致，
`actions.py` md5 均为 `573dd04b3618d2066b0326c2fd183c8d`，镜像内 `app/RUNNER_VERSION` 自证 `v0.3.1`，构建时间 2026-07-08。
**已知债务**：该镜像无对应 git 提交，CI 无法复现（决定不补源码）。

### 4.2 能力集：25 个动作

`backup.create`、`image.load`、`filesystem.prepare`、`files.sync`、`compose.override`、`compose.project_migrate`、
`script.run_sandboxed`、`compose.apply`、`runner.handoff_target_runtime`、`runner.schedule_target_runtime_handoff`、
`runner.stop_legacy_runtime`、`post_upgrade.schedule_cleanup`、`post_cleanup.precheck_target_health`、
`compose.stop_legacy_project`、`network.remove_legacy`、`filesystem.cleanup_legacy_paths`、
`filesystem.cleanup_target_app_residuals`、`post_cleanup.verify`、`health.http`、`health.prometheus`、
`task.migrate_runtime_state`、`task.sync_runtime_state`、`legacy.cleanup`、`checkpoint.write`、`rollback.restore`

protocol 1，`min_version v0.3.0`，`required_capabilities: []`。该集合与
`backend/app/upgrade_protocol/constants.py` 的 `RELEASED_RUNNER_ACTIONS` 双向零差异。
release note 三条：备份排除 `upgrades`/`backups`/`exports` 与 Prometheus WAL、服务重启用 `compose up --no-deps`、
compose 相对 bind mount 改写为 Docker socket 宿主路径。

### 4.3 v0.3.1 相对开发线 v0.3.2 缺什么

动作集只差 1 个（v0.3.2 共 26 个，新增 `post_upgrade.schedule_collection`），但**共有的 25 个动作实现也全部变化**
（`store.py` / `sandbox.py` 未变）。在 v0.3.1 镜像内 grep 确认为 0 命中的能力：

| 缺失能力 | 对应问题 | 后果 |
| --- | --- | --- |
| `reconcile_project_runner_tag` / `_writeback_runner_compose_tag` | US-32 | 组件升级后 compose 仍写旧 tag，需手工改 |
| `resolve_runner_stop_decision` / `_should_stop_previous_runner` | US-03 / US-04 | 无统一 stop 决策与同 project 守卫 |
| `lease.py` `_connect()` 返回裸连接 | US-28 | 心跳持续堆积未关闭连接与写事务，WAL 下阻塞 web-api 写操作 |

### 4.4 v0.3.1 够不够升 v0.5.3 —— 够（实测 + 静态双证）

v0.5.3 平台包声明 `minimum_runner_version: v0.3.1`，
`required_capabilities: ['backup.v1','image.v1','files.v1','compose.v1','health.v1','rollback.v1','compose.project.v1']`。

- **静态**：方案 A（49-49）后 `backend/app/v2/upgrade/compiler.py` 升级计划**不再下发** `post_upgrade.schedule_collection`
  （该字符串仅存在于第 245 行注释）。compiler 全部 23 种动作类型 100% 落在 v0.3.1 的 25 个动作内。
- **运行**：`10.20.11.12` 发布版 v0.3.1 直升 v0.5.3，task `upgrade-666284beec04cc87` succeeded（12 动作、无 schedule_collection）、
  post-cleanup succeeded、8 项验收全过。

## 5. 加固该放在哪一侧

| 想要的加固 | 能否保护"当次升级" |
| --- | --- |
| 目标镜像里的新预检查/新逻辑 | ❌ 对当次无效，只保护下一版 |
| 源端 web-api 里可独立生效的检查 | ✅ 但需在**该源端版本**就已发布 |
| upgrade-runner 里的动作级检查 | ✅ runner 与平台解耦，可独立升级生效 |
| 构建期门禁（打包时就拦住） | ✅ 与运行期版本无关，最可靠 |

**结论**：涉及"别让坏包进现场"的加固，优先放**构建期门禁**（如 runner 交付一致性、交付物自洽），其次放 runner，最后才是 web-api 运行期检查。

## 6. 相关

- 问题台账与定性：`docs/upgrade-strategy-issues.md` US-01
- 架构方案与业界对照：`docs/upgrade-architecture-options.md` §0.5
- 升级链路铁律：`docs/upgrade-chain.md`
- 版本治理：`docs/version-governance.md`
- 逐字节核验过程与实测输出：`progress.md`（2026-09-30 runner v0.3.1 能力基线核验）
