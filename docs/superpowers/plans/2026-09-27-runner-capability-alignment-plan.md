# 计划：v0.5.3 与已发布 runner v0.3.1 能力对齐（方案 A + B）

状态：**只写计划，未实施**。用户 2026-09-27 指示「A+B 你先写计划里不执行」。实施前必须按 AGENTS.md §3 先补设计文档（`docs/superpowers/specs/`），并取得用户对涉及 runner 改动的明确同意。

背景一句话：已发布的 runner v0.3.1（Release 资产 `d10e15cf…`，2026-07-09 上传）不认识 `post_upgrade.schedule_collection` 这条升级动作，而 v0.5.2 平台包的升级计划编译器会下发它 → 以 v0.5.2 为源的升级（即 v0.5.2 → v0.5.3）在**平台已切换之后**失败。证据与根因见 `findings.md` 2026-09-27 三条、`progress.md` 2026-09-27 发布验收、`docs/pending-tasks.md` #45。

### 已确认的事实（2026-09-27 读码）：runner 的这条动作是多余的

- `post_upgrade.schedule_collection` 的实现（`backend/app/upgrade_runner/actions.py:2115`）**不抓数据**，只往 `upgrades/<task_id>/post-upgrade-collection.json` 写一个 `status: pending` 的**标记文件**。
- 真正抓数据的是平台：`backend/app/v2/worker.py` 每 5 秒跑 `run_pending_post_upgrade_collection`，扫描标记、确认父任务 success 后执行采集（采集由 collector-worker 完成）。
- 平台还有兜底 `_ensure_post_upgrade_collection_marker`：**标记不存在时自己补建**（`source: "target_worker_compatibility"`）。
- 结论：**抓数据与 runner 无关，清单里这行是历史时序权宜**（切换瞬间旧 web-api 正被替换、runner 仍在跑且知道任务目录，所以让它顺手留便条），可安全移除——这正是方案 A 的全部内容。

### 已确认的事实（2026-09-27 逐动作比对）：A 做完后，已发布 runner 无需升级即可升 v0.5.3

把 v0.5.3 主升级计划（task `upgrade-72bfb3f52317ef7f` 的 `task.json`）逐条动作与已交付 runner 包 `d10e15cf…` 的动作表（25 个）比对：

- 主计划 13 个动作：`backup.create`、`image.load`、`filesystem.prepare`、`files.sync`、`task.migrate_runtime_state`、`compose.override`、`compose.project_migrate`、`compose.apply`、`health.http`、`task.sync_runtime_state`、`post_upgrade.schedule_cleanup`、`runner.schedule_target_runtime_handoff` —— **全部支持**；唯一缺失 `post_upgrade.schedule_collection`。
- post-cleanup 子任务 7 个动作（`post_cleanup.precheck_target_health`/`runner.stop_legacy_runtime`/`compose.stop_legacy_project`/`network.remove_legacy`/`filesystem.cleanup_legacy_paths`/`filesystem.cleanup_target_app_residuals`/`post_cleanup.verify`）—— **全部支持**。
- 结论：**只要按 A2 去掉那一条，已发布的 runner v0.3.1 不需要任何升级就能完成 v0.5.2 → v0.5.3**；方案 B 不是"能升"的前提，而是交付治理与防复发。

## 方案 A（平台侧，不碰 runner）——保 v0.5.2 现场能直升

目标：**v0.5.2 + 已发布 runner v0.3.1 必须能升到 v0.5.3**，且不再依赖旧 runner 的任何新动作。

- [ ] A1 设计文档：`docs/superpowers/specs/2026-09-27-v053-drop-runner-collection-action-design.md`（未写，实施前补）。
- [ ] A2 改 `backend/app/v2/upgrade/compiler.py`：**不再下发** `post_upgrade.schedule_collection`（该动作对 runner 是多余的，见下）。
- [ ] A3 **不需要新增调度逻辑**：平台侧本来就有，直接复用并补测试——
  - `backend/app/v2/worker.py:229 run_pending_post_upgrade_collection`（每 5 秒的 `post-upgrade-auto-collection` 定时任务）
  - `backend/app/v2/worker.py:195 _ensure_post_upgrade_collection_marker`：没有 runner 写的标记时**平台自己补建**（`source: "target_worker_compatibility"`），再按父任务是否 success 决定执行
  - 本方案只需验证"runner 不写标记 → 平台仍能在 5 秒内自建标记并执行采集"，并补一条回归测试。
- [ ] A4 测试：编译器单测（源 v0.5.2 → 计划中不含 `post_upgrade.schedule_collection`；源 v0.5.1u2 → 行为不变）；平台侧调度采集的单测（成功建任务、失败不改写主任务状态）。
- [ ] A5 验收（硬门禁，必须用**已发布** runner 包 `d10e15cf…`）：`.12` 恢复 v0.5.1 基线 → `v0.5.1u2(d5f277) → runner v0.3.1(d10e15cf) → v0.5.2(692aca8b) → v0.5.3(候选包)`，要求主任务 success、post-cleanup success、平台侧自动采集任务已创建（Tower 不可达只记环境限制）、8 项验收全过。
- [ ] A6 不改 runner 代码 → **不需要** bump `RUNNER_VERSION`；但需在 ledger/CHANGELOG 记录"v0.5.3 已兼容已发布 runner"。
- 回滚：还原 A2/A3 两处提交即可，未触碰任何已发布物。

## 方案 B（runner 侧，需用户同意 + 版本号 bump）——让以后能力不再漂移

目标：把 08-12 进入 main 的 runner 能力**按规矩**交付出去，并让预检查能在升级开始前就拦住"runner 落后"。

- [ ] B1 取得用户明确同意（AGENTS §6：未同意不得动 runner）。
- [ ] B2 bump 版本号 **v0.3.1 → v0.3.2**：根目录 `RUNNER_VERSION`、`backend/Dockerfile.upgrade` 内复制逻辑核对、镜像内 `/app/RUNNER_VERSION`、镜像 tag `nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.2`、组件包文件名与 manifest `version`/`min_version`。**同一次提交完成**。
- [ ] B3 打包：`scripts/build_runner_component_package.py --version v0.3.2`，SHA 记入 `docs/upgrade-package-ledger.md` + `docs/releases/CHANGELOG.md`。
- [ ] B4 推 git tag `runner-v0.3.2`（推送需用户执行/授权）→ `.github/workflows/upgrade-runner-image.yml` 出镜像 → **必须核对 DockerHub tag 200**（不允许再出现 404）。
- [ ] B5 预检查补**动作级**校验：升级计划里每个动作的所需能力，逐条比对当前运行 runner 的动作表（心跳/容器内 `/app` 动作表），不满足 → `precheck_failed`，错误信息明确写"请先执行 runner 组件升级到 v0.3.2"；**不得**再出现"能力级通过、动作级在 cutover 后失败"。
- [ ] B6 测试：旧 runner（`d10e15cf`）→ v0.5.3 预检查必须**拒绝**且原因清晰；新 runner（v0.3.2）→ 预检查通过并升级成功。
- [ ] B7 验收：`.12` 先用 v0.3.2 组件包升级 runner，再 v0.5.2 → v0.5.3 成功；三处同源核对（仓库/Release 资产/DockerHub tag）全绿。
- 边界：**B 不能作为 v0.5.3 升级的前置条件**（否则已发布 v0.5.2 现场永远升不上来）；A 与 B 必须并行，A 负责"能升"，B 负责"以后对齐"。

## 方案 C（简化版，2026-09-27 用户改定）——只把发行镜像推上 DockerHub，不补源码

用户原话：「那 v0.5.1u2 不用补了，dockerhub 上补 v0.3.1 镜像就可以了」。
**取消**原计划的 C1–C3（归档分支 + 从镜像反提源码 + 打 `runner-v0.3.1` tag 走 Actions）——因为 Actions 只会照 git 源码构建，而没有任何提交等于发行镜像，**不补源码就走不了 CI**，只能直接 push 镜像。

- [x] C1′ 取得 DockerHub 凭据：用户提供 token（会话内一次性使用，未落盘；**建议吊销**）。
- [x] C2′ 在 `.12`（发行包 `/root/chain-verify-20260722/packages/smartx-upgrade-runner-v0.3.1.tar.gz`，SHA `d10e15cf`）：**先记录**本地 `…:v0.3.1` 当前镜像 ID（现为 `0aca32511008`，运行容器在用）→ `docker load` 发行镜像 → `docker push …:v0.3.1` → **还原本地 tag** → `docker logout`。
- [x] C3′ 校验：DockerHub tag 200；拉取后 `RUNNER_VERSION=v0.3.1`、`grep -c schedule_collection = 0`、动作 25、`actions.py` md5 `573dd04b3618d2066b0326c2fd183c8d`（与发行资产一致）。
- [x] C4′ 记账：ledger/CHANGELOG 写明 DockerHub `v0.3.1` = 发行资产镜像（digest 记录），**并登记已知债务**：该镜像无对应 git 提交、无法由 CI 复现（用户 2026-09-27 决定不补源码）。
- 不做的事：不动 `latest`、不推 git tag/分支、不改已发布 tag 与 Release 资产、不改 main。
- token 纪律：不写入任何文件/提交/日志，用完即 `docker logout`。

## 执行顺序与门禁

1. 先做 A（平台侧，低风险，不需要动 runner）→ 用 `d10e15cf` 走完整链路验收。
2. 再做 B（需同意 + bump v0.3.2 + 推 tag）→ 预检查动作级校验 + 新 runner 组件升级验收。
3. 方案 C（补源码 + 出 DockerHub v0.3.1）可与 A 并行，不阻塞 v0.5.3。
5. A、B、C 都过之后，才进入 v0.5.3 发布流程（`docs/release-acceptance.md` Release Day，含新增的第 4 步 Runner 交付一致性核对）。
4. 验收证据必须写明所用包/镜像的 **SHA 与来源（Release 资产 or 本地构建）**（AGENTS §10 第 7 条）。

## 明确不做

- 不修改、不重发已发布的 `d10e15cf…` runner 组件包与 `v0.5.2` 平台包。
- 不用同一个 `v0.3.1` 版本号发布任何能力不同的 runner。
- 不用测试机上开发期重建的 runner 镜像充当验收基线。
