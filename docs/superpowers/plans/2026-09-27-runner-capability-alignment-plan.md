# 计划：v0.5.3 与已发布 runner v0.3.1 能力对齐（方案 A + B）

状态：**只写计划，未实施**。用户 2026-09-27 指示「A+B 你先写计划里不执行」。实施前必须按 AGENTS.md §3 先补设计文档（`docs/superpowers/specs/`），并取得用户对涉及 runner 改动的明确同意。

背景一句话：已发布的 runner v0.3.1（Release 资产 `d10e15cf…`，2026-07-09 上传）不认识 `post_upgrade.schedule_collection` 这条升级动作，而 v0.5.2 平台包的升级计划编译器会下发它 → 以 v0.5.2 为源的升级（即 v0.5.2 → v0.5.3）在**平台已切换之后**失败。证据与根因见 `findings.md` 2026-09-27 三条、`progress.md` 2026-09-27 发布验收、`docs/pending-tasks.md` #45。

## 方案 A（平台侧，不碰 runner）——保 v0.5.2 现场能直升

目标：**v0.5.2 + 已发布 runner v0.3.1 必须能升到 v0.5.3**，且不再依赖旧 runner 的任何新动作。

- [ ] A1 设计文档：`docs/superpowers/specs/2026-09-27-v053-drop-runner-collection-action-design.md`（未写，实施前补）。
- [ ] A2 改 `backend/app/v2/upgrade/compiler.py`：源版本 ≥ v0.5.2（runner 可能是已发布旧包）时**不下发** `post_upgrade.schedule_collection`；或按"当前 runner 动作表是否支持"做条件下发（倾向前者：语义更简单，旧 runner 本就不该负责切换前后的事）。
- [ ] A3 v0.5.3 web-api 侧兜底：升级主任务成功且健康检查通过后，由**平台自己**创建升级后自动采集任务（进任务中心，沿用"采集失败不改写升级成功状态"口径；`post_upgrade.auto_collection` 语义保留在平台侧）。
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

## 执行顺序与门禁

1. 先做 A（平台侧，低风险，不需要动 runner）→ 用 `d10e15cf` 走完整链路验收。
2. 再做 B（需同意 + bump v0.3.2 + 推 tag）→ 预检查动作级校验 + 新 runner 组件升级验收。
3. 两步都过之后，才进入 v0.5.3 发布流程（`docs/release-acceptance.md` Release Day，含新增的第 4 步 Runner 交付一致性核对）。
4. 验收证据必须写明所用包/镜像的 **SHA 与来源（Release 资产 or 本地构建）**（AGENTS §10 第 7 条）。

## 明确不做

- 不修改、不重发已发布的 `d10e15cf…` runner 组件包与 `v0.5.2` 平台包。
- 不用同一个 `v0.3.1` 版本号发布任何能力不同的 runner。
- 不用测试机上开发期重建的 runner 镜像充当验收基线。
