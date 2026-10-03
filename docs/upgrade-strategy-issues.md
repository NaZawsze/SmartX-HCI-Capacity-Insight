# 升级策略问题细分清单（2026-09-27 复查）

用途：把「升级策略 / runner / web-api」当前所有已知问题**逐条拆细**，每条给出现象、根因、证据、影响、修复方向与状态。执行计划与验收证据见
[superpowers/plans/2026-09-27-v053-full-chain-acceptance-plan.md](superpowers/plans/2026-09-27-v053-full-chain-acceptance-plan.md)；
整改立项见 `docs/pending-tasks.md` #47；根因记录见 `findings.md` 2026-09-27 各条。

状态图例：🔴 未修（有风险）｜🟠 已绕开未根治｜🟡 规则已立未脚本化｜🟢 已修复并验证｜⚪ 测试缺口

---

## A. 架构/契约层（骨架级）

### US-01 🟢 源端执行：平台包的新校验对"当次升级"无效
- **现象**：编译计划（`execution.py:32 compile_execution_plan`）、预检查、执行编排全部运行在**源端 web-api**；平台包带来的新逻辑只存在于目标镜像里，**当次升级用不到**。
- **证据**：49-50 的动作级预检查与"同 project 不停 runner"修复，对 `v0.5.2 → v0.5.3` 这一次完全无效（`.12` 三轮实测：老 web-api 照跑老逻辑）。
- **影响**：所有安全增强都"晚一代"；v0.5.3 的预检查只能保护 v0.5.3→v0.5.4。
- **方向**：无代码级解法 → 只能用「发布顺序写死 + 源端版本矩阵验收 + 文档写死」压制（#47③）。
- **状态**：🟢 **已收敛为已知边界（2026-09-29）**：查证 Kubernetes version skew policy 后确认，**「旧版本组件执行升级、新版本逻辑当次不生效」是业界常态而非缺陷**（K8s 明确支持控制面与节点版本偏斜，升级时执行的就是旧 kubelet）。原「🔴 架构缺陷」定性作废，架构方向（控制面/执行面分离）经核对与业界一致。**正解不是重构**，而是：
  1. **把偏斜写死成可执行的支持矩阵** `docs/version-skew-matrix.md`：逐组合标注支持状态 + **实测证据**（task id / 干净 VM 记录），未实测的显式标 ⚠️；
  2. **矩阵门禁化**（`test_us01_version_skew_matrix.py` 9 例）：标 ✅ 必须有实测证据，标 ⚠️ 必须写明"未实测"，三条硬规则（先平台后 runner / runner 不降级 / 单飞）必须在位，且必须写明"为什么不做代码级重构"与"加固该放在哪一侧"。
  3. **加固位置指引**（矩阵 §4）：涉及"别让坏包进现场"的加固，优先放**构建期门禁**（与运行期版本无关，最可靠），其次放 runner，最后才是 web-api 运行期检查。
- **门禁的实际作用**：写矩阵时我一度把"manifest 声明支持"当成"已验证"写进 ✅ 行，**被门禁当场拦下**并要求补真实 task id——这正是本项最有价值的部分，防止矩阵在后续改动中悄悄失真。
- 未实测组合（v0.5.0/v0.5.1/v0.5.1u1 → v0.5.3）**保留声明但标注未实测**，不得对客户承诺。

### US-02 🟢 runner 版本号是隐式契约（同版本不同能力）
- **现象**：`RUNNER_VERSION` 不随能力变更 → 同一 `v0.3.1` 三副面孔（仓库 26 动作 / 发行包 25 动作 / DockerHub 干脆没有）。
- **证据**：`dab2e0f`(08-12) 给 runner +2053 行但 `git show dab2e0f -- RUNNER_VERSION` 为空；DockerHub tags API 只有 `latest`/`runner-sha-31a1209`/`v0.3.0`。
- **影响**：能力级预检查分辨不了 → 失败落在 cutover 之后。
- **方向**：bump 纪律 + **硬门禁脚本**（发布前自动比对三处同源）+ 动作级校验。
- **状态**：🟢 **已完成（2026-09-27，49-54）**：`scripts/verify_runner_delivery_consistency.py` 把「三处同源核对」做成一条命令（C1 仓库 `RUNNER_VERSION`／C2 动作表 AST 静态提取／C3 三个源码 compose 字面量 tag／C4 组件包 manifest 与镜像归档 SHA256／C5 **离线解析包内镜像归档比对 `RUNNER_VERSION` 与 `actions.py` md5 与仓库一致**／C6 DockerHub tag 200 默认关闭），任一 FAIL 非零退出、SKIP 必须显式；配对单测 22 例；**已接入 `docs/release-acceptance.md` 发布门禁第 4 步**。`.3` 实证：v0.3.2 包全绿，v0.3.1 包（`dd096bf2…`）正确 FAIL。**本条关闭**。

### US-03 🟢 runner 生命周期散落三个入口
- **现象**：组件升级（web-api `compose stop/up`）、平台升级 handoff（runner 自己 `docker run` helper）、legacy 清理（runner 动作 `runner.stop_legacy_runtime`）三方都能动同一个 runner 容器。
- **证据**：`execution.py` 的 bootstrap stop、`actions.py:1449` handoff、`actions.py:1548` stop_legacy。
- **影响**：时序 bug 温床 —— US-04 就是这么产生的。
- **方向**：收敛到单一入口（建议统一由"当前源端"决定，且**先比对 compose project 再决定是否停**）。
- **状态**：🟢 **已收敛（2026-09-29）**。抽出 `resolve_runner_stop_decision()` 作为**唯一决策处**（返回可断言、可留痕的纯数据 `stop/reason/runner_project/target_project`，`reason` 带 `purpose` 便于事后取证）；`stop_legacy_runtime` 经它判断、拒绝时给结构化 `skip_reason`；web-api 侧 `_should_stop_previous_runner` 语义对齐，并有**收敛一致性测试**（逐输入比对两侧判定）。
- **收敛测试抓到的真 bug**：web-api 侧 `if not bootstrap` 把空 dict（`{}`）当成"没有 bootstrap 对象"而跳过停止，但它紧邻的 `target_project` 空串分支本意是"未声明 → 保守停止"——两者语义相同、判定相反。改为 `is None` 精确判断。旧测试 `test_runner_bootstrap_stop.py` 曾用 `{}` 表示"非 bootstrap"，掩盖了这个不一致，一并更正。

### US-04 🟢 老 web-api 的无条件 stop（v0.5.2 源端，改不到）
- **现象**：目标布局机器上**原地**做 runner 组件升级，新 runner 启动后 10 秒被 SIGKILL（`exit=137`），心跳过期 → 后续预检查报"未检测到 upgrade-runner 心跳"。
- **根因**：`execution.py` 在 `_runner_bootstrap` 时无条件 `docker compose --project-name <当前project> stop upgrade-runner`；同 project 场景下停的就是刚启动的新 runner。
- **证据**：`.12` 两轮复现（08:16、09:04 UTC，启动后 10s kill，docker events `start → kill(+10s) → stop/die`）；第四轮加守卫后 **runner 存活 90s**。
- **影响**：**B-b「先升 runner 再升平台」在 v0.5.2 现场不可行**；客户若强行先升 runner 仍会踩（老镜像改不到）。
- **方向**：流程定死「先平台、后 runner」（#47③）；老现场无代码解法，只能靠文档与升级中心提示。
- **状态**：🟢 **已根治为「预检查拦截」（2026-09-29）**。源端镜像确实改不到（那是已发布版本），但此前"已绕开"只写在台账里、**没有任何机制阻止客户踩**。现新增预检查项 `runner_first_order`：
  - **拦截**：源端 < v0.5.3 且属**原地升级**（bootstrap 目标 project == 当前 project）→ 预检查失败，消息含实测症状（10s SIGKILL / 心跳过期）、可执行指引（**先升级平台再升级 runner**）与"源端无法修改"说明，避免运维试图改镜像；
  - **放行**：非原地升级（旧桥接布局 bootstrap 到不同 project，历来可行）；源端 ≥ v0.5.3（已含平台侧守卫）。
- **为什么这样算根治**：把"踩了之后排查半天"变成"当场看到可读错误并知道怎么做"。源端代码缺陷仍在（改不到），但**它不再能以静默方式伤害客户**。测试 8 例含接线断言。

---

## B. 升级流程/断言层

### US-05 🟢 已实施；顺序验收不做（用户 2026-09-28 定）：post-cleanup 健康断言"版本相等"→ 升级顺序敏感
- **现象**：`_require_cleanup_health`（`upgrade_runner/actions.py:1884-1886`）用 `!=` 等值比较 `required_health.runner_version`。manifest 现在写 `v0.3.1`：先升平台（runner=v0.3.1）✅；**先升 runner 到 v0.3.2 再升平台 → "清理前 runner 版本不匹配" → 升级成功但 post-cleanup 失败**（旧环境不清理、残留累积）。
- **证据**：代码可证（`if expected_runner and ... != expected_runner: raise`）；第四轮只测了"先平台"顺序，未覆盖另一条。
- **方向**：平台侧打包时**不写** `required_health.runner_version`（代码 `if expected_runner` 为空即跳过），只校验平台版本 + 三项 health；或改为"≥"语义（需改 runner，须 bump，且老 runner 收不到）。
- **状态**：🟢 **已实施（49-52，提交 8115c41）**；**2026-09-28 用户决定：runner-first 顺序不是受支持链路（链路只有"先平台、后 runner"），且 v0.3.2 不随本次发布 → M3-08/M3-10 两格记 N/A、不做顺序验收**；本项按「代码 + manifest 实证的防御性修复」记录（r5 候选包 manifest 实证 `required_health` 无 `runner_version`），发布材料不得写"顺序无关已实测"。原状态描述：**已实施（49-52，提交 8115c41）**：`build_upgrade_package.py` 的 `required_health` 移除 `runner_version`（runner 侧 `if expected_runner` 空即跳过，无需 bump runner）；候选包 `b9560eee…` 的 manifest 已无该字段（`required_health` 仅 `version`+`checks`），`.3` 门禁全过；**`.12` MVP（先 runner 后平台顺序）待授权执行**。设计：`docs/superpowers/specs/2026-09-27-us05-us23-release-blocking-fix-design.md`。

### US-06 🟢 升级后采集链路：5 秒常驻轮询 + 落盘便条 + 冗余的 runner 写便条
- **现象**：`worker.py` 每 5 秒扫 `upgrades/*/`（常驻、无开关、无指标）；便条本应由触发方写，却让 runner 插手（而这正是 49-49 要删的冗余）。
- **证据**：`worker.py:458` `seconds=5`、`worker.py:195` 平台可自建标记（`source=target_worker_compatibility`）。
- **影响**：功能正确、开销可忽略，但**事件驱动的事用高频轮询**，链路隐蔽、难观测、难关闭。
- **方向**：升级成功时平台侧直接投递采集任务；轮询降为 30~60s 兜底；加开关与指标（#47①）。
- **状态**：🟢 **已实施（2026-09-29，随 US-30 一并落地）**。`worker.py::ensure_post_upgrade_collection_for` 改为由升级收尾守护线程（`settlement.py`）**扫到成功任务时顺手投递**，5 秒常驻轮询降级为兜底。证据：`worker.py:250-256` docstring 自称 US-06 并说明改造前后；pending-tasks #47「采集链路」条目亦记为已实施。此前「已立项未实施」为滞后状态。

### US-07 🟢 升级前磁盘空间未硬校验
- **现象**：`image.load`/备份/迁移都要占空间，但预检查清单里**没有磁盘空间检查**；空间不足会在执行中段失败（留下半升级状态）。
- **证据**：`precheck.py` 的 checks 只有 manifest/paths/source_compatibility/runner_protocol/checksums/images/project_files/prometheus 权限。
- **方向**：预检查加"可用空间 ≥ 包大小 × N + 备份预留"；失败即 precheck_failed。
- **状态**：🟢 **已实施并验证（49-55 / S1-1，2026-09-27）**：`precheck` 新增 `disk_space` 项——需要 = 包内容（解包目录内文件求和；给 `.tar.gz` 时按 ×3）+ 预留（默认 2 GiB，`SMARTX_UPGRADE_DISK_HEADROOM_BYTES`）；按 `st_dev` 去重检查 `upgrades`/`backups`/`/`，不足即 `precheck_failed`。`.3` 实测真实候选包：payload 624,777,779 B → 需要 2.58 GiB，可用 33.34 GiB；容器全量 424 tests OK。设计：`docs/superpowers/specs/2026-09-27-upgrade-disk-space-precheck-design.md`（含首版误用目录 `st_size` 的修正记录）。

### US-08 🟢 长任务期间心跳被判 stale 的边界未验证
- **现象**：升级执行中 web-api 侧会读 runner 心跳（`_runner_state_is_fresh`），若单步耗时超过新鲜度阈值，可能被判"未检测到 runner"。
- **证据**：`RUNNER_HEARTBEAT_STALE_SECONDS` 存在；本轮升级时长 2~3 分钟未触发，但**大包/慢盘/大 DB 备份**场景未测。
- **方向**：验收补"长任务"用例；或执行期间暂停 staleness 判定。
- **状态**：🟢 **已取证并修复（49-57 / S1-3，2026-09-27）**：`.3` 真实同版本升级实测发现比假设更严重——**整个执行期实例心跳冻结**（`update_runner_state` 只在 `run_pending_once` 开头调用；task `upgrade-c921c5bc0aad72e5`，执行约 75s 心跳未动），而阈值 30s。后果：执行期并发预检查报"未检测到 upgrade-runner 心跳"、升级页组件目录 `compatible=False`。修法（**不动 runner、不升版本**）：web-api 新增 `service/runner_presence.py`，把"存在有效任务租约"（执行期每 5s 续租）也算作在场证据，`source` 记 `task_lease`；协议校验/组件目录/health 共用同一判定。runner 侧"执行期也刷新实例心跳"登记为下次 runner 交付的待办。设计：`docs/superpowers/specs/2026-09-27-runner-presence-during-execution-design.md`。

### US-09 🟢 重复上传/预检失败任务无清理策略
- **现象**：预检失败的包会留下 `upgrades/<tid>` 目录与任务中心 failed 项（本轮 `.12` 累积 8 个），真实客户会看到噪音。
- **证据**：`.12` 任务目录列表；`pending-tasks` 中"保留最近 N 个"已降级为 API 参数。
- **方向**：预检失败任务 TTL 自动清理（保留最近 N 个）。
- **状态**：🟢 **已实施并验证（49-56 / S1-2，2026-09-27）**：web-api 守护线程（默认 6h）按 TTL（默认 7 天）+ 保留最新 N 个（默认 3）自动删除**从未执行过**任务（`precheck_failed`/`uploaded`）的包内容（原始归档 + 解包目录，单个失败任务约 800 MiB），**保留 `task.json` 与任务中心记录**；执行过/失败/回滚类不自动清（取证），活跃升级时整轮跳过，包内容被清后预检查给出「请重新上传」的明确提示。`.3` 实测：5 个过期任务保留 3 个、删 2 个（含归档与解包目录，task.json 保留且记 `package_cleaned_at`），fresh/success 不动，活跃任务存在时整轮跳过；容器全量 437 tests OK。设计：`docs/superpowers/specs/2026-09-27-upgrade-artifact-housekeeping-design.md`。

### US-23 🟢 已修并经 `.12` 验证：并发升级无「单飞」守卫
- **现象**：`start()`（`execution.py:42`）只校验**本任务**状态 `precheck_passed`，**不检查是否已有其它平台升级在执行**；runner 侧 `run_pending_once` 又是按 mtime 串行消费所有 pending 任务。
- **链路**：两个包先后上传并预检通过 → 两次 `start` 都成功 → 第二个任务排队执行时，**环境已被第一个任务改变**（版本/项目/目录/镜像全变了），而它的执行计划是按旧状态编译的 → 在错误状态上执行（可能失败，也可能"成功"地做错事）。
- **证据**：`execution.py:42-60` 无任何 running/pending 互斥检查；删除任务时倒是有保护（`intake.py:81`「升级任务正在执行…不能删除」），说明设计者考虑过并发，唯独 start 漏了。
- **影响**：客户连点两次、两个管理员并行操作、或"预检失败→再传一个包→两个都 start"都会触发；真实现场风险中高。
- **方向**：`start` 前检查是否存在**其它**平台升级任务处于 `pending/running/runner_restarting/recovery_*` → `400 升级任务正在执行中`；同时 runner 执行前**重新校验 source_compatibility**（防止计划过期）。列入 #47③。
- **状态**：🟢 **已实施并经 `.12` 复验（49-52，提交 8115c41/32f9a95；2026-09-29）**：`execution.py::start()` 增加 `_ensure_no_active_upgrade`（ACTIVE={pending,running,runner_restarting,recovery_required,rollback_pending,rollback_running}；类级 `threading.Lock` 消除扫描-认领竞态；retry/recovery/rollback 同守卫，cancel/delete 不拦）；新增 `test_upgrade_single_flight.py` 9 用例 + API 测试断言；`.3` 全量 386 OK。**`.12` 已验证（2026-09-28）**：平台升级 `upgrade-b07795625cf0d681` 执行中，第二个已预检通过的包 `upgrade-88e7262584becb7c` 的 start → **400** `升级任务 … 正在执行或需要恢复，不能开始新的升级。`；另验证逃生门标记失败后守卫正常释放（新 start 恢复放行）。runner 执行前重验 source_compatibility 未做（需 bump runner，留 #47）。

### US-24 🟢 已修（并入 v0.3.2，待交付复验）：同版本重装（已在目标布局）时 runner 自伤：`_save` 双写同一 task.json → 崩溃循环、任务卡死

- **现象**：在目标布局上做 `v0.5.3 → v0.5.3` 同版本重装（受支持路径），任务推进到 `compose.override` 后卡死，runner 容器反复重启（实测 17 次），`task.json` revision 只在重启时跳。
- **根因**：`engine._save()`（`upgrade_runner/engine.py:59-67`）在 `task_mirror_dir` 存在时无条件再写一份 mirror；同版本重装时 `task.migrate_runtime_state` 的 source 与 mirror 是**同一目录的两个路径视图** → 每次保存写同一文件两遍（N→N+2），内存 revision 落后 → 下次保存必 `RevisionConflict`。49-50 只修了同族的 `rmtree` 自删，未覆盖镜像写入。
- **证据**：`.12` task `upgrade-d08f064e6e15166a`（attempt=17、36 条 RevisionConflict、动作序列与 revision 轨迹已留档 `/root/baselines/wedged-task-upgrade-d08f064e6e15166a/`）。
- **方向**：mirror 与主 store 同文件时跳过 mirror 写（inode/`resolve()` 判等）；补"同版本重装 + mirror 同源"回归。**改 runner → 需用户同意并 bump 版本（AGENTS §6/§8）**。
- **状态**：🟢 **已修（2026-09-28）**：`engine._save` 增加 inode 判等后跳过同文件 mirror 写；**修复并入 `runner v0.3.2`**（该版本未交付，直接并入；用户 2026-09-28 口径）；单测 4 例通过。**`.12` 已复验（2026-09-28）：装含修复的 `runner v0.3.2` 组件包后跑 v0.5.3 → v0.5.3 同版本重装，`upgrade-26856095c44869d1` 44s succeeded、post-cleanup succeeded、runner 重启 0 次、动作 attempt 最大 1（修复前 attempt=17）→ 🟢 确认修复。注意同轮发现 US-26：平台包会把 runner 降回 v0.3.1。**

### US-25 🟢 已修：卡在 `running` 的任务无产品化出路 → 单飞守卫把环境永久锁死

- **现象**：任务卡在 `running` 后，`cancel` 400（只允许 pending）、`recovery/fail` 400（只允许 recovery_required）、`delete` 拒绝 → 后续所有 `start` 被 US-23 守卫拒绝，环境不可再升级。
- **证据**：`.12` 实测三条接口响应（见 findings.md D2）。
- **方向**：让恢复通道覆盖"长时间无有效租约/无新鲜心跳的 running 任务"（判为 recovery_required 并给 continue/rollback/fail），或提供"标记失败/强制恢复"入口 + 审计。
- **状态**：🟢 **已修（2026-09-28，web-api 侧，未动 runner）**：`recovery/{tid}/fail` 接受「running 且无活租约」的任务；视图暴露 `runner_lost` + `available_recovery_actions=["fail"]`；单测 7 例通过。

### US-26 🟢 已修并 `.12` 验证：现场 runner 已够用时，平台升级仍按包内基线 tag 重建 runner（不该动却动了）

- **定性（2026-09-28 用户口径修正）**：这不是「runner 版本与平台包基线谁优先」的问题。规则是**条件式**的——默认先平台后 runner；**只有平台确需更高 runner（`minimum_runner_version` 高于现场 runner、平台新增了旧 runner 执行不了的能力）时才先升 runner**。而当前 v0.5.2 → v0.5.3 用已发布 runner v0.3.1 就能完成，**runner 完全不需要动**。所以缺陷是：**平台升级在 runner 已够用时仍然动了它**，且动的方式是按包内基线 tag 强制重建 → 把现场更高的版本降级（实测 v0.3.2 → v0.3.1，无任何提示）。
- **现象**：`.12` 先用组件包把 runner 升到 **v0.3.2**（`upgrade-9fdaff9a349bc257` succeeded，容器 tag / 镜像内 `RUNNER_VERSION` / health 三方一致，存活 90s+），随后用 r6 平台包做 **v0.5.3 → v0.5.3 同版本重装**（`upgrade-26856095c44869d1` succeeded）→ 结束后 runner **变回 v0.3.1**（三处均为 v0.3.1）。
- **根因（代码定位）**：`backend/app/v2/upgrade/compiler.py:229` 从**平台包 manifest** 取 runner 镜像（`images[service=upgrade-runner].image`），`runner.handoff_target_runtime`（`actions.py:1360`）用它写运行时 compose 并 `docker compose up -d --no-deps --force-recreate upgrade-runner` → **无条件按包内 tag 重建**。旁证：组件升级只把新 tag 写进 `compose-runtime/docker-compose.runner-bootstrap.yml`，而 `project/docker-compose.yml`、`compose-runtime/docker-compose.runner-upgrade.yml` 与 `docker compose config` 仍解析为 v0.3.1（tag 没有单一事实源）。
- **预检查侧没问题**：`minimum_runner_version` 按「≥」判定，现场 v0.3.2 跑 r6 预检查全绿（含 `runner_actions`）——即「更高版本合法」已被承认，只有执行阶段把它降了回去。
- **影响范围（重要）**：**对本次发布无影响**——正常客户现场 runner 就是 v0.3.1，降级后仍是 v0.3.1，无感知。**会在「下一版交付 runner v0.3.2」之后咬人**：客户先装 v0.3.2（安装成功、日志显示 `跳过停止旧 runner`），之后再升平台就被静默降回 v0.3.1，US-24 等 runner 侧修复随之丢失，且无提示——属于 AGENTS §6「能力漂移」类风险。
- **修法方向（待实施）**：①**编译计划时解析 runner 镜像**：现场 runner 版本 ≥ 包 `minimum_runner_version` 时，handoff 用**现场实际镜像**而不是包内 tag（计划里记录实际会跑的镜像，可审计）；②或动作层：目标 tag 与当前运行 tag 相同则不 `--force-recreate`，现场版本更高时保留现场版本；③补「现场 runner 高于包基线」的回归用例。组件升级侧同时应回写 project compose / runner-upgrade compose，消除 tag 多事实源。
- **证据**：`.12` 2026-09-28 23:08→23:14 实测；`compose-runtime/docker-compose.runner-bootstrap.yml`=v0.3.2 而 `docker-compose.yml`/`docker-compose.runner-upgrade.yml`/`docker compose config`=v0.3.1。
- **状态**：🟢 **已实施并经 `.12` 验证（2026-09-28，提交 7083d72/fe555be；复验证据：r12 同版本重装验收「runner v0.3.2 未被包基线降级」判别通过）**。方案**实施中修正**（设计 §3.2）：初版「计划带 preserve_current + 动作层沿用现场镜像」会**打挂主路径**——已发布 runner v0.3.1 收到空 image 会 `raise ValueError` 导致 v0.5.2→v0.5.3 失败，且需改 runner（AGENTS §6）。最终改为**编译期由 web-api 解析现场 runner 镜像注入 manifest 副本**，编译器照常下发具体镜像，**旧 runner 零改动**、向后兼容。`.3` 门禁全绿（后端 468 OK、build 26 OK、identity 0、交付一致性 C1–C5 全 PASS 证明 `actions.py md5 matches repo` runner 未动、候选包 r8 `3672e920`）。**`.12` 复验全部通过（2026-09-28）**：①**主路径回归** v0.5.2+已发布 runner v0.3.1 → r8 直升 `upgrade-6f035c3e52b83428` succeeded（188s）+ 8 项验收全过，**runner 仍 v0.3.1**（未被无故改动）；②装 v0.3.2 组件包 `upgrade-39600ca4b67b75ad` succeeded，三方一致 v0.3.2、存活 90s+；③**判别格**：v0.5.3 同版本重装 `upgrade-7c0720d6207ea942` succeeded（<10s）、**runner 仍 v0.3.2**（容器 tag / 镜像内 `RUNNER_VERSION` / health 三方一致），**修复前同操作会回落 v0.3.1**；最大 attempt 1、runner 重启 0（US-24 无回归）、8 项验收全过、DB 556/89588 不变、7 条 legacy 路径全清；④US-23 抽查 400 正常。另修 US-26-4 回写正则（真实 compose 在 `upgrade-runner:` 后先有 `build:` 块，`image:` 位置不固定 → 改逐行状态机，提交 4c7ed07）。

### US-27 🟢 已实施并经 .12/.14 复验：US-25 逃生门只改状态，不清理也不回滚 → 旧路径残留

- **现象**：任务被中断后走 `recovery/fail` 标记失败，**环境留下半迁移残留**：`/data/upgrades/upgrade-925f38527816ae1f/package`（被中断任务在旧路径的包目录）与 `/data/smartx-capacity-insight-data/{app,prometheus}`（空骨架，被中断升级的 `filesystem.prepare` 造出）重新出现 → 8 项验收第 7 项「legacy 路径全 missing」判**异常**。
- **数据红线**：**未受损**——live 库 `/data/smartx-storage-forecast/app/smartx.db` `integrity ok`、556/89588 与升级前一致；旧数据目录仅 12K 空骨架，无数据分叉。
- **收干净的方式**：再跑一次成功升级，其 post-cleanup 会清掉全部 legacy 路径（本轮实测 `upgrade-26856095c44869d1` 的 post-cleanup succeeded，7 条路径全清）。
- **方向**：逃生门在标记失败时提示"环境可能半迁移，需再跑一次升级让 post-cleanup 收尾"，或在 `recovery/fail` 响应里带 `cleanup_required=true` + 残留路径清单；理想是提供"标记失败并清理残留"的产品化收尾动作。
- **状态**：🟢 **已实施并经 `.12`/`.14` 复验（2026-09-29）**（提交 9d60a68/4a5b2f1，`.3` 门禁全过）：`recovery/fail` 增加 `_residual_legacy_paths()` **只读**探测（7 条 legacy 路径）+ 任务视图暴露 `cleanup_required` / `residual_paths`；`error` **追加**（不覆盖原失败语义）收尾指引「环境可能半迁移 → 重跑一次完整升级由 post-cleanup 收尾 → 之前不要开始新升级」；前端新增「需要收尾」面板显示残留路径。测试 8 例（含只读性断言：探测不得含 rmtree/unlink/mkdir）。**`.12`/`.14` 复验通过**：`upgrade-acf7a29bb647e5a2` 视图由 `cleanup_required=True / 5 条误报 / actions=None` 变为 `cleanup_required=False / residual_paths=[] / actions=['fail']`（既不误报也不丢入口）。**其中残留探测的误报是 US-31 一并修掉的**（容器内 bind mount 挂载点必然存在，直接 `Path.exists()` 判定会永远误报）。

### US-28 🟢 已修（本轮 .12 验收发现）：runner 组件升级后有约 10 分钟 SQLite 写锁窗口，web-api 写操作直接 500

- **现象**：`.12` 跑 runner v0.3.1 组件升级后，紧接着的 **v0.5.2 平台步预检查连续 3 次 HTTP 500**（`sqlite3.OperationalError: database is locked`），心跳当时新鲜（age=2s）、health 全绿——**不是 US-08 心跳问题**。
- **根因取证**：锁的持有者是 runner 容器主进程（`python -m app.upgrade_runner.main`，`hrtimer_nanosleep` 空闲态），它持有**大量未关闭的 DB 连接**：`/proc/<pid>/fd` 指向 `/data/smartx.db` 的 fd 数实测 **52 → 30 秒后降到 14**；DB 目录无 `-wal/-shm`，即 rollback journal 模式，未提交事务独占写锁。约 10 分钟后锁自行释放，预检随即正常（7 项全 true）。
- **影响**：升级链上「组件升级 → 下一个平台步」这一常见组合会随机失败，且失败形态是裸 500（无重试/无友好提示），运维只能干等重试。上轮 `rebuild_all.sh` 记录的「v0.5.2 升完预检 `runner_protocol=False`」也是同一窗口的不同表现。
- **方向**：①runner 侧改用 WAL + 短事务/显式 close，消除长写锁（**改 runner → 需用户同意并 bump 版本**）；②web-api 侧对 `database is locked` 做有限重试/退避并返回可读提示，而不是裸 500；③验收驱动脚本在组件步之后显式等待锁释放（本轮已按此处理）。
- **证据**：`.12` 2026-09-28 22:29–22:40（`upgrade-b32d44b1badb1783` 之后），web-api 容器日志三连 500 + `fuser` 定位 + fd 计数两次采样。
- **状态**：🟢 **已修（2026-09-28，用户批准）**——**根因**：`lease.py::_connect()` 返回裸连接，调用方 `with self._connect() as conn` **只提交事务不关闭连接**，心跳每 5 秒漏一个（`.12` 实测 52 fd / 约 10 分钟写锁窗口）。改为真正的 `@contextmanager`（异常路径也关闭）。**版本口径**：v0.3.2 从未交付，按 US-24 先例直接并入、**不 bump**。
- **顺带补上门禁漏洞（US-02 家族）**：`verify_runner_delivery_consistency.py` 的 C5 原先**只 md5 校验 `actions.py`**，改 `lease.py`/`main.py` 等模块不会被发现——正是「同版本号不同能力」的核心风险。已扩展为**整个 `app/upgrade_runner` 源码树聚合指纹**（7 个模块），并**指名不一致模块**。实证：新包 `7f72721f…` 全 PASS（`树指纹 matches repo, 7 个模块`）；旧包 `c69e2129…` 精确报出 `不一致模块：lease.py`（改造前完全抓不到）。
- **两侧都做了**：`database.py` 翻译 `database is locked` → 领域异常 → `main.py` 映射 **503 + 可读文案**（**刻意不做退避重试**：锁窗口分钟级，HTTP 内等待必撞超时）。测试：连接生命周期 5 例（含 fd 计数不累积）+ 门禁回归 3 例 + US-28 503 映射 6 例。
- **`.3` 门禁**：后端 **490 tests OK (skipped=2)**、build_tests 26 OK、门禁 C1–C5 全 PASS（C6 DockerHub SKIP）。

### US-29 🟢 已决策（2026-09-28 用户决定）：放弃人工回滚，保留失败自动回滚

- **决定**：**不做人工回滚**（下线回滚按钮与 `POST /api/admin/upgrade/rollback/{tid}`、`recovery/{tid}/rollback` 的用户可见入口）；**失败自动回滚必须保留**（`execution.py:345-370`，升级执行抛异常时自动恢复项目文件备份、删除 override、`docker compose up` 拉回旧镜像 → `rolled_back`）。
- **依据**：
  - 人工回滚**从未验证**（审计矩阵 US-17 空白格）；`rollback_healthcheck` 步骤在代码里直接标注「**回滚健康检查占位通过**」——是占位实现，不是真检查。
  - 一个未验证的按钮在客户现场被误点，比没有这个按钮危险（`rollback_failed` 状态本身已经存在，说明回滚也可能失败）。
  - 失败自动回滚是**已验证**的安全网（第四/五轮链路的失败路径都走过）。
- **直接后果（重要）**：失败后**没有回滚兜底**，唯一出路是「逃生门（US-25）→ 标记失败 → 再跑一次成功升级由 post-cleanup 收尾」。**因此 US-27 从「体验问题」升为「关键路径」**。
- **执行口径**：UI 隐藏回滚入口；API 保留但标记废弃（避免老客户端 404）；自动回滚路径与 `rolled_back` 状态**不动**。
- **状态**：🟢 **已实施（2026-09-28，提交 9d60a68）**：前端恢复操作区**移除「执行回滚」按钮**（保留「继续执行」「标记失败」）；服务层 `rollback()` / `recovery_rollback()` **保留实现与路由**（老客户端/历史任务不 404），加注释标注已下线；**失败自动回滚路径（`rolled_back` 终态、`rollback_config` 恢复步骤）未动**——测试固化该边界。审计矩阵 US-17 转 N/A。

### US-30 🟢 新发现（第 3 批实测）：升级成功但 post-cleanup 从不执行——**没有客户端轮询就永不收尾**

- **现象**：`.12` 上 task `upgrade-0de5b6ad24d41c56` **14 个动作全部 succeeded**（含 `post_upgrade.schedule_cleanup`），任务状态 `success`，但 `/data/smartx-capacity-insight-data`、`/prometheus-data`、`/data/upgrades` 三条 legacy 路径**至今残留**。
- **根因（代码定位）**：`_maybe_schedule_post_upgrade_cleanup()`（`execution.py:648`）只在 `_normalize_completed_runner_task()` 里被调用，而后者**仅在两处被触发**：`execution.py:151`（`status` 接口，即**客户端轮询**）与 `cleanup.py:104`。**worker 侧没有任何后台兜底**。
  - 任务执行完毕 → 计划已落 `post_upgrade_cleanup_task_id: None`（清理任务未创建）
  - `post_upgrade.schedule_cleanup` 动作只写了**标记文件**（`marker_path: /data/upgrades/<id>/post-upgrade-collection`），本身不清理
  - **只要没人调用 `status` 接口，清理任务就永远不会被创建**
- **触发场景**：本轮实测——start 后**未等完成就返回/取消**，期间无任何 UI 轮询。真实客户若用脚本/定时任务发起升级而不持续轮询状态，就会命中。
- **影响**：**升级"成功"但旧环境不清理**，磁盘持续增长（每次升级还留一份 ~4.7MB 备份，实测 `backups/` 累积 5 份），且残留目录会让后续升级的 legacy 扫描面变大。这是 US-27 的**第三个实例**，但机理不同（不是"标记失败不收尾"，而是"根本没人触发"）。
- **方向**：①把「任务终态 → 投影 + 创建 post-cleanup」做成**后台兜底**（worker 或 web-api 守护线程扫 `success` 且无 `post_upgrade_cleanup_task_id` 的任务并补建），不依赖客户端轮询；②或由 runner 在 `schedule_cleanup` 后直接投递清理意图；③补一条断言：平台升级成功后，**不调用 status 接口**也应最终产生 cleanup 任务。
- **证据**：`.12` 2026-09-28 13:30–14:0x（`auto_rollback.log` 收尾 8 项验收第 7 项报 3 条 EXISTS + U1 任务文件取证）。
- **状态**：🟢 **已修（2026-09-29）**。**根因**：`_maybe_schedule_post_upgrade_cleanup()` 由 `_normalize_completed_runner_task()` 触发，而后者**只在 status 接口（客户端轮询）**与 `cleanup.py` 路径被调用 → 没人轮询则清理任务永不创建，任务却显示"成功"（`.12` task `upgrade-0de5b6ad24d41c56` 14/14 动作 succeeded 但 legacy 路径残留）。
- **修复**：新增 `backend/app/v2/upgrade/settlement.py` 后台守护线程，定期扫描「status=success + manifest 有 `post_upgrade.create_cleanup_task` + `legacy_cleanup` 非空 + 清理任务目录不存在」并**幂等**补建；`main.py` startup/shutdown 接线；配置 `SMARTX_UPGRADE_SETTLEMENT_INTERVAL_SECONDS`（默认 300，≤0 关闭），**启动即扫一次**以覆盖历史漏网任务。
- **判别证据**：`.3` 造「成功但缺 cleanup」fixture 后重启 web-api，清理任务于**容器启动后 6 秒**自动创建，**全程未调用 status 接口**（这正是原缺陷的触发条件）；幂等复验 `created=[]` 不重复创建；测试 9 例。
- **顺带修的可观测性缺陷**：项目无 logging 基础配置、root logger 实际为 WARNING，原 `logger.info` 的"发现未收尾升级/已补建清理任务"在容器日志里**完全不可见** → 改用 `logger.warning`（发现未收尾升级本身即异常）。

### US-31 🟠 新发现（第 3 批实测）：失败自动回滚**只覆盖 `health.*` 失败**，不是通用安全网

- **现象**：注入 `image.load` 失败（破坏镜像归档）→ task `upgrade-acf7a29bb647e5a2` 终态 `failed`，**未触发任何回滚**（`rollback_attempts: None`，`recovery_status: none`）。
- **根因**：`engine.py:146` 的触发条件是
  ```python
  if str(action.get("type", "")).startswith("health.") and int(task.get("rollback_attempts") or 0) < 1:
      return self._automatic_rollback(task, exc, action)
  ```
  即**只有 `health.*` 动作失败才自动回滚**；`image.load` / `files.sync` / `compose.apply` 等失败一律直接 `failed`。
- **这本身是合理设计**：早期动作失败时环境尚未改变，回滚无意义。但**文档与认知必须纠正**——US-29 决定放弃人工回滚后，文档把「失败自动回滚」称为"唯一安全网"，而实际上它**只覆盖升级末段的健康检查失败**这一段窗口。
- **附带发现**：`backup.create` 已成功（留下 ~4.7MB 备份）后才失败，**该备份无人回收**；实测 `backups/` 累积 5 份历史备份。
- **方向**：①修正文档口径（"安全网"仅覆盖 health 阶段失败）；②早期失败时给出「残留物清单 + 收尾指引」（复用 US-27 的 `cleanup_required` 机制，覆盖**所有**失败态而非仅 `recovery/fail`）；③备份保留策略（成功任务保留 N 份/按 TTL，失败任务随取证期）。
- **状态**：🟠 **部分修复**（`.12` 已闭环；备份保留策略仍待排期，见下）。
- **修复一：所有 failed 任务都有收尾指引**（不只走人工 `recovery/fail` 的那些）。早期动作失败由 runner 自行判定 `failed`、不经任何人工入口，此前既无残留清单也无操作入口。两处根因：①`cleanup_required` 只挂在 `recovery/fail`；②**`setdefault` 陷阱**——`engine.py` 用 `setdefault` 兜 `available_recovery_actions`，而键存在且值为 `None` 时 `setdefault` **不替换**，失败任务带着 `None` 定格，前端 `?.includes()` 拿不到任何按钮。现 `_public_task` 对所有 `failed` 任务补残留探测+指引+`fail` 入口，engine 侧显式归一 `None`。
- **修复二：残留探测必须在宿主视角判断**。探测在 web-api 容器内执行，而 `/data/backups`、`/data/exports`、`/data/compose-runtime`、`/prometheus-data` 是 bind mount 挂载点、容器视角**必然存在**（且必须存在，删掉会拆掉全机挂载，UPG-050）——旧实现直接 `Path.exists()` **永远误报**。`.12` 实测：7 个 legacy 宿主路径全部已清空（环境干净），探测却报 5 个"残留"，把管理员引向无意义的收尾操作。改为经 `_container_mount_source` 换算宿主真实路径：**有映射时，宿主源存在=正常布局、不存在=布局未建立（即真残留）；无映射时保守用容器路径**（宁多报不漏报）。
- **`.12` 判别证据**：平台包 r13（SHA `60114ad9701be381275b6bf7aeac2bb4de10245d6d5dcdc6bd1d3327ccd9cca3`）升级 succeeded 后，历史失败任务 `upgrade-acf7a29bb647e5a2` 视图由 `cleanup_required=True / 5 条误报 / actions=None` 变为 `cleanup_required=False / residual_paths=[] / actions=['fail']`；health `v0.5.3 / runner v0.3.2` 三项 checks 全 true。
- **备份保留策略：🟢 已修（2026-09-29）**。新增 `backend/app/v2/upgrade/backup_retention.py` + 守护线程（`main.py` 接线），按 **TTL（默认 14 天）+ 保留最近 N 份（默认 5）** 裁剪两类产物（`upgrade-*-before-*.tar.gz` 数据快照、`project-files-<task_id>/` 项目备份），`SMARTX_UPGRADE_BACKUP_TTL_DAYS` / `_KEEP_RECENT` / `_CLEANUP_INTERVAL_SECONDS` 可调，两者为 0 即关闭。
  - **安全约束一：最新 N 份豁免过期判定**。即使全部超期也必须保住 N 份——备份是"出事前能否回退"的最后一道保险，全清等于回退无门。
  - **安全约束二：按类型分别计算**（不混在一起数）。回退需要「数据快照 + 项目备份」**配对**；混合计数会留下"3 数据 + 2 项目"，于是有 1 份数据备份的配对项目备份被删——正是要避免的残缺备份。实现初版正是这么错的，由测试抓出。
  - 只清本模块命名的产物；`customer-manual-backup.tar.gz`、导出物等一律不动。`plan_cleanup` 只读。
  - 排序口径：数据备份按**文件名内时间戳**，项目备份目录名无时间戳、按 **mtime**。
  - 测试 14 例（TTL、数量裁剪、保底豁免、配对保持、只读性、非法配置回退、main 接线）。
`.12` 实测 `backups/` 累积 **13 份 / 79MB**（`backup.create` 先成功、后续 `image.load` 失败所致）。需定策略：成功任务保留 N 份或按 TTL，失败任务随取证期到期清理。此项会持续增长磁盘占用，属运维债而非正确性问题。

### US-32 🟢 已修（第 5 批实测）：compose 的 runner tag 回写**自实现起从未生效**（只读挂载 + 静默吞错）

- **现象**：`.12` 上反复出现「现场跑 `v0.3.2`、`project/docker-compose.yml` 却写 `v0.3.1`」的多事实源。宿主任何一次 `docker compose up -d` 都会据此把 runner 静默降级（与 US-26 同类后果）。
- **根因（两层，都很典型）**：
  1. **回写放在 web-api 侧，但它没有写权限**。`docker-compose.yml:26` 把 project 目录以 `:ro` 挂给 web-api，容器内实测 `WRITE FAILED: Read-only file system`。`_sync_runner_image_into_compose_files` 的写入必然抛 `OSError`，又被 `except OSError: continue` **静默吞掉** → US-26（r8）的"compose 回写消除多事实源"**一次都没成功过**。
  2. **修好权限还不够：取数来源也是错的**。首次实现放在 US-30 守护线程里按现场镜像对账，但守护线程同样没有写权限；改到 runner 侧后仍不生效——因为平台升级时 web-api 只在**内存里**把现场镜像注入编译用的计划（`_inject_field_runner_image`），落盘 `task.json` 的 `manifest` 仍是包内基线。`.12` 实测：manifest 里 `v0.3.1`、计划 `schedule-runner-target-runtime-handoff` 的 `params.image` 里才是现场 `v0.3.2`。按 manifest 取值 → 与 compose 相同 → 空转。
- **最终修复**（`backend/app/upgrade_runner/actions.py::reconcile_project_runner_tag` + `engine.py` 收尾）：
  - 放在**runner** 侧任务收尾（所有动作完成、project 文件同步之后）——runner 以宿主身份运行、写入无阻碍，且它才是"我是哪个镜像"的权威；"谁写 project 文件"也只有它一个答案（平台升级的 project 同步本来就由 runner 做）。
  - 镜像取自**执行计划**：`runner.handoff` 的 `params.image` → `compose.override` 的 `images[]` → 兜底 manifest。
  - **不新增动作、不改能力集**：动作表仍 26 个，`required_capabilities` 不变，旧 runner 缺这段逻辑只是维持现状，平台包 `minimum_runner_version` 无需变更。
  - 善后动作不参与成败判定：写失败/异常只记 warning 与 task log，**绝不**把已成功的升级判成失败。
  - web-api 侧同名方法保留仅作兼容，并改为**写入失败记 warning**——"静默吞错"才是让这个缺陷潜伏这么久的元凶。
- **`.12` 判别证据**：平台升级前 compose `v0.3.1`（陈旧）→ 升级 `upgrade-2874d3eb97b67ce4` succeeded → 升级后 compose 自动 `v0.3.2`，task log 留痕「compose runner tag 已对齐：…v0.3.1 -> …v0.3.2」，health `v0.5.3 / runner v0.3.2` 三项 checks 全 true。
- **交付形态**：runner 组件包 `components-v032-r4-20260929/smartx-upgrade-runner-v0.3.2.tar.gz` SHA `26dfcdd7e6c942a7944ad3c6e3006f193126af6bd4beacdf7a5cfdcf9fbf5b29`；门禁 C1–C5 **12 项 PASS / 0 FAIL**（C6 DockerHub 按用户决定 SKIP）；动作数仍 26，证明未新增动作。
- **教训（值得写进规范）**：①"某功能上线了"不等于"它生效过"——只读挂载 + 宽泛 `except` 能让一个函数长期空转而无任何告警；②跨进程传递"修正后的数据"时，落盘副本与内存副本可能不一致，**消费方必须确认自己读的是权威副本**（本例是执行计划，不是 manifest）；③功能放在哪个进程，要看那个进程**有没有权限**做，而不是逻辑上"谁更懂"。

- **⚠️ 2026-09-30 补充：组件升级路径还有第三层，回写仍然不触发**（`.14` 实测，修复后仍失败）
  - **现象**：回写逻辑已移到 runner 侧并单测通过，但 `.14` 上组件升级 task `upgrade-ead521581ad91115` 报 success、runner 已是 `v0.3.2`，compose 仍写 `v0.3.1`。
  - **根因（第三层：触发条件本身错了）**：runner 侧两条回写路径**都以「任务未收尾」为前提**——
    - `status == "success" and _has_unfinished_steps(task)`：组件升级任务的步骤**已被 web-api 收尾为全部 succeeded**，条件不成立；
    - `status == "runner_restarting" and runner_resume_pending and not execution_plan`：该任务 status 是 `success`、且组件任务本就无 `execution_plan`，条件不成立。
    - 两条都不触发 → `run_pending_once` 直接 `continue` → 回写从未执行。manifest 里有正确的 `v0.3.2`、`reconcile_project_runner_tag` 本身也可用，**只是没被调到**。
  - **最终修复**（commit `fe7bf1a`）：新增第三条**幂等兜底路径**，判据从「任务状态」改为「**compose tag 是否已对齐**」——
    - `_compose_runner_tag_now()` 读当前 compose 声明的 tag；
    - `_runner_tag_aligned()` 比对任务声明的 runner 镜像；compose 读不到时视为已对齐，不反复扰动现场；
    - `_apply_tag_writeback_if_needed()` 仅在未对齐时回写并留痕，已对齐则不追加日志（避免每次轮询刷一遍）。
  - **`.14` 闭环判别证据**：r8 包 `components-v032-r8-20260930/…v0.3.2.tar.gz` SHA `cedbf4c4a77a…`（完整构建，门禁 12 PASS）→ 走产品 API 预检查 7 项全 ok → task `upgrade-8c90bbc7bd52290c` succeeded → compose **v0.3.1 → v0.3.2**、health `ok=True v0.5.3/v0.3.2`、5/5 容器 Up、日志留痕「已对齐 compose runner tag」、**40 秒内日志条数稳定在 5（幂等）**。
  - **补测**：US-32 定向 15 → **21 例**，覆盖 success 终态的未对齐/已对齐/compose 缺失/回写生效/幂等/分支存在六种情形。
  - **教训（补）**：④**回写/收尾类逻辑必须用「任务真实终态」判别**，只在单测 happy path 里跑通不足以证明生效——本例 15 个单测全绿但真机不触发，直到按真实终态补测才暴露。

### US-37 🟢 已修复并经 `.14` 真机验证（2026-09-30）：同一 compose project 下混用不同 compose 文件起服务 → Docker 判定「配置变了」→ 静默 recreate + SIGKILL（exit 137）

- **现场（2026-09-30 `.3`，用户发现）**：用户在 `.3` 导入迁移包后发现服务挂了。
  `web-api` 容器 `Exited (137)`、`OOMKilled=false`、`Error=` 空；另有两个卡在 `Created` 的残留容器。
  内存 15Gi 总量 / 12Gi 可用 → **排除 OOM**。
- **先排除的误判方向**：迁移包确实只含数据（`manifest.json` + `app/smartx.db` + `prometheus/*/blocks`），
  导入任务 `migration-import-24fc0c44b1f0b0a2` 为 `success`，且
  `grep -c compose backend/app/v2/migration/service.py` = **0**（迁移代码完全不碰 compose）。
  **数据完好**（`integrity=ok`、590 VM、89636 volume、`.env` 600 未破坏）。
- **真正的根因（`docker events` 决定性证据）**：
  ```
  10:31:40 container create 12524e10d4ab  name=64ff891973e4_...web-api-1
           └─ config_files=.../docker-compose.offline.yml
  10:31:40 container kill    64ff891973e4     signal=15      <- 杀老 web-api
  10:31:51 container die     64ff891973e4     exitCode=137   <- SIGKILL 后的 137
  ```
  修复前各容器用的 compose **不一致**：
  ```
  web-api            -> docker-compose.yml
  collector-worker   -> docker-compose.offline.yml
  ```
  Docker Compose 用 **`com.docker.compose.config-hash`** 判定「配置是否变了」。
  同一 project 名下用**不同 compose 文件**起服务，config-hash 必然不同 →
  判定为「配置变更」→ **recreate 旧容器** → 旧容器被 `signal=15`/`signal=9` 杀掉 → `exitCode=137`。
- **为什么会 config-hash 不同（实测 diff）**：三个服务在两个 compose 里的定义**全部不同**——
  主 compose 用 `build: {context: ., dockerfile: backend/Dockerfile}`；
  offline compose 用 `image:` + `pull_policy: never`，并多注入 `SMARTX_COMPOSE_FILE`、
  多挂载 `project:/data/smartx-storage-forecast/project:ro`。
- **结构性根因（比事故本身更重要）**：仓库里有 **4 个 compose 变体**
  （`docker-compose.yml` / `.offline.yml` / `.release.yml` / `.upgrade.yml`），
  **共享同一个 project 名** `smartx-hci-capacity-insight`，
  而**没有任何机制记录「这个实例当初是用哪个 compose 起的」**：
  - `.env.example` 里**没有** compose 文件字段（实测 grep 无命中）；
  - `install.sh` 硬编码 `COMPOSE_FILE="docker-compose.offline.yml"`（第 41 行），但把
    **两个 compose 都装进** `$PROJECT_DIR`（第 322 行的循环）；
  - `upgrade.sh` 完全不碰 compose；
  - `.env` 与 `project/` 目录里**没有留下任何标记**说明用的是哪一个。
  **→ 现场同时存在两份 compose，任何人（包括自动化脚本）都可能用错那一份，
  而系统不会、也没法给出任何提示。** 这与 US-26（compose tag 多事实源）同源：
  **同一实体有两个可写的真相来源，且没有单一事实源仲裁**。
- **触发方式（本次的具体成因）**：开发者在**有真实服务运行的机器**上跑测试，
  用了与运行实例不同的 compose 变体操作同一 project。**这不是产品缺陷，
  是"缺少防护"与"操作缺少隔离"叠加**——但产品完全有能力把它挡下来。
- **诊断教训（值得写进规范）**：**`exit 137` + `OOMKilled=false` = 被人为 SIGKILL**，
  不是内存不足。若两者都成立应优先查「谁在 recreate 我」而不是查内存。

#### 2026-09-30 `.14` 真机验证收尾（T4/T5/T6 全过，过程抓出两个实施缺陷）

交付物：`ops/package.sh` 从 dev2 `7135d40` 重建的离线交付目录（tar SHA `7dddc1ef…`）。
`.14` 干净 VM，真实 Docker compose 全程操作。

| 用例 | 结果 | 关键证据 |
| --- | --- | --- |
| 存量回填（P1 路径） | ✅ | 旧实例（无标记）跑新 `install.sh`：守卫从容器 `config_files` 标签取地面真相 `docker-compose.offline.yml` 回填标记，EXIT=0，5 容器 ID 与 health 逐字节不变 |
| T5 全新安装 | ✅ | 清空目录+删镜像后从交付目录安装：`.env` 含 `SMARTX_COMPOSE_FILE_ACTIVE=docker-compose.offline.yml`（600），与容器标签地面真相一致；守卫装进 project 目录（755）；health ok |
| T6 用错变体被拒 | ✅ | `compose-guard.sh check .env docker-compose.yml` → **exit 2** + 三条路径；`guard && up` 组合下 up 根本未执行；前后容器 ID diff 为空、health 逐字节相同 |
| T6b install.sh 拒绝分支 | ✅ | 标记改为错变体 + `--force-env`（不带 switch）→ EXIT=1「compose 变体不一致，已拒绝启动」，die 发生在 up 之前，容器零扰动；标记跨 `.env` 重生成被保留（RESOLVED_COMPOSE 通路生效） |
| T4 `--force-compose-switch` | ✅ | 守卫序列「1/2 用 docker-compose.yml 停机（不做 recreate）→ 2/2 更新标记」→ 5 容器全部干净重建（ID 全变）、restarts=0、OOMKilled=false、health ok、标记切回 offline |

**验证过程抓出并修复的两个实施缺陷**（都是单测全绿、真机才暴露——正是 AGENTS §12 要求真机收尾的原因）：

1. **守卫接线三处恒假**（`41fc86e` 修复）：install.sh 用 `[ -n "${compose_guard_check:-}" ]`
   判断守卫是否可用，但守卫加载的是**函数**不是变量，参数展开恒为空 →
   标记回填、标记写入、up 前守卫判定三个分支**从未执行过**。36 例静态单测全绿、真机全死。
   修复为 `declare -F`，并补静态禁令 + 行为级双测试（38 例）。
2. **全新安装不写标记**（`c466f42` 修复）：`compose_guard_resolve` 只在已有 `.env` 时执行，
   全新安装的 `.env` 由模板重新生成、天然不含标记——T5 判据不成立。修复为
   `.env` 生成校验通过后补写（值取 RESOLVED_COMPOSE 地面真相，全新安装退到本次待用变体），
   写在守卫判定之前，`--force-env` 重装路径仍受保护。

另修一处外观回归：US-37 步骤插入后总步数 11、进度头仍写死 `/10`（`7135d40`，改为 `TOTAL_STEPS`）。

**遗留观察（已修复，2026-10-01）**：原问题——`--force-env` 重装在守卫拒绝路径上会**先重新生成 `.env`
（密钥更换）再 die**，在跑容器仍持旧密钥，密钥错位会让下次重启后 Tower 凭据解不开。
修复（`b7473f2`）：`.env` 重生成前备份（0600），拒绝时恢复原文件，启动成功后删除备份；
`.14` 行为级实测：拒绝后 `.env` sha256 逐字节一致、备份文件清理、零容器启动。

## C. 已修复并验证（🟢，列此以备回归）

| 编号 | 问题 | 修复 | 证据 |
| --- | --- | --- | --- |
| US-10 | `task.migrate_runtime_state` 在 bind-mount 双视图下 `rmtree` 掉自己的源目录 → 任务目录被删、升级卡死 | `_same_directory`（inode 判等）+ 历史迁移分支同守卫 | `test_task_migrate_alias.py`（含真实 bind mount 回归用例）+ 第四轮直升成功 |
| US-11 | 同 project 原地组件升级被停（平台侧） | `_should_stop_previous_runner` | 4 单测 + 第四轮 runner 存活 90s |
| US-12 | 计划含 runner 不支持的 `post_upgrade.schedule_collection` | 方案 A（manifest `auto_collection=false` + compiler 不下发 + 平台自采） | 第四轮计划 12 动作无该条 + 平台自建标记 |
| US-13 | DockerHub 从未有 `v0.3.1` 镜像 | 直推发行镜像（`90eb5a42…`），`latest` 同步 | tags API 200、`RUNNER_VERSION=v0.3.1`/25 动作/md5 `573dd04b…` |
| US-14 | Release 资产与 tag 源码不同源（7 月资产 vs 8-12 tag） | 规则写死"资产必须 CI 产出"（**未回填历史**） | findings 2026-09-27 |
| US-15 | CHANGELOG v0.5.2 发布日期错误（07-17 → 实为 08-12） | 已修正并注明 | GitHub Release API published `2026-08-12T06:36:06Z` |
| US-16 | 验收曾用开发期重建镜像充当基线（验收≠交付） | 规则写死"必须用 Release 资产" | AGENTS §10-7、development-verification §4.4 |

---
---

#### 修复进展（2026-09-30，提交 `21fb325` / `cf11635` / `8b935bb` / `5529e23`）

| 层 | 状态 | 落点 |
| --- | --- | --- |
| 标记（单一事实源） | ✅ 已实施 | `install.sh` 写 `.env` 的 `SMARTX_COMPOSE_FILE_ACTIVE`（0600、容器内 `/run/smartx-runtime.env` 可读） |
| 守卫（操作前拦截） | ✅ 已实施 | `delivery/compose-guard.sh`，自包含；`up/down/restart` 前比对，不一致默认 exit 2 |
| 交付态接线 | ✅ 已实施 | `install/` 与 `upgrade/` 各一份（`SCRIPT_SOURCES`）；`install.sh` 装进 `PROJECT_DIR`（0755） |
| 诊断文档 | ✅ 已实施 | `troubleshooting.md` §10、`delivery/README.md` §9.1、`development-verification-process.md` §4.5 |
| **实施期设计修正** | ✅ 已记录 | 标记**取自容器 compose 标签**（地面真相），不取自脚本硬编码值——见下 |
| **`.14` 真机验证** | ⏳ **未做** | T4 / T5 / T6 需真实 Docker compose，**是本项的收尾门禁** |

**实施期发现的设计缺陷（已修正，值得记住）**：设计初稿写「`install.sh` 把自己用的
`$COMPOSE_FILE` 写进 `.env`」。核对后发现这会写出**假标记**——
`install.sh` 在已有 `.env` 时会**直接 `exit 0`**（第 231-236 行），
而 `.3` 事故现场恰恰是**已有 `.env`** 的实例，标记永远补不上；
且写入值是硬编码常量，现场可能用别的变体。
**用另一个猜测源去补事实源，正是 US-26/US-32 同类错误的翻版。**
现改为从运行中容器的 `com.docker.compose.project.config_files` 标签取地面真相
（实测 `.3` 返回 `/data/.../project/docker-compose.yml`），
回填规则：已有标记→保持；无标记+容器在跑→取标签 basename；无标记+无容器→取本次要用的。

**T6 仍是收尾必做项**：它是本次事故的直接判别用例
（故意用错 compose → 必须被拒 → 容器 ID 与 health 不变）。

**真机验证记录（`.3`，2026-09-30）**：一次性容器跑全量 **726 tests → 1 failure / 7 skipped**。
唯一失败 `test_v2_upgrade...runner_executes_it` 经对照确认为**既有环境限制、非本次回归**：
在动手前的 `9da006d` 上同环境跑同一测试，结果完全相同（`'failed' != 'success'`）。

### 已排查、确认不是问题（避免重复争论）
- **post-cleanup 失败会被忽略？** 否——存在重试入口 `POST /api/admin/upgrade/post-cleanup/{task_id}/retry`（`api/admin/upgrade.py:145`），且任务 severity 由 `_severity()` 按类型/状态推导，`UPGRADE` 类失败 = **critical**（`tasks/service.py:294`），会进任务中心高亮。
- **在跑任务被误删？** 否——`intake.py:81` 明确拒绝删除 `running/pending/runner_restarting/recovery_*` 状态的任务。
- **同一版本被重复升级？** 允许（`allow_same_version`），属"就地重装/修复"的既定设计（有 `source_compatibility` 测试覆盖）。
- **清理失败阻断升级？** 否——按设计"采集/清理失败不改写平台升级成功状态"（数据优先），配合上一条的 retry 与 critical 告警，口径自洽。

## C2. 结构性结论（2026-09-28 用户判断）：升级执行模型本身是问题源，不只是零散缺陷

> 用户判断：「这种升级模式就是有问题的，而且这个项目就是因为升级不了才重构过一次。」
> 下面不是新增缺陷，而是把已有缺陷归并到一个根因上——**它们是同一个结构的三种表现**。

### 三类共性故障（全部已有实测证据）

| 类别 | 共性 | 本轮/历史证据 |
| --- | --- | --- |
| **① 执行者即被升级对象** | 谁在执行升级，本身就是升级的受害者 | US-01（源端跑老代码，新包校验对当次无效）、US-04（源端老 web-api 无条件 stop 新 runner）、US-26（平台升级顺手把 runner 降级）、US-03（runner 生命周期三个入口互相踩） |
| **② 状态归属不唯一（无单一事实源）** | 同一事实写在多处，靠约定而非机制保持一致 | US-26（三个 compose 文件三个 tag）、US-02（runner 版本号与能力不同源）、US-27（任务终态/残留清理/健康判定三处各说各话） |
| **③ 执行期共享可变资源** | 升级期间执行者与被升级对象共用同一份可变资源 | US-28（runner 与 web-api 共用一个 SQLite，锁是整文件级，心跳堵住全平台写）、US-24（同一 task.json 两个路径视图双写，attempt 17 崩溃循环） |

### 为什么这不是"再修几个 bug"能解决的

1. **第 8 节已经列了 10 条"必须避开的坑"**（`project-guide-for-ai.md`），本轮 US-24/26/27/28 是第 11~14 条——**模式在重复出现**，说明修的是症状。
2. **上一轮重构证明了这一点**：项目已因"升级升不上去"做过一次 v2 重构（升级执行模型、目录标准、版本来源规则都因此重写）。重构后缺陷数显著下降，但**这三类结构没变**，于是同类问题继续长出来。
3. **交付形态本身带来风险**：on-prem 现场、宿主不可控、升级窗口有限、**执行者必须在被升级的环境里就地完成升级**。这四条约束同时存在时，"就地升级 + 执行者自举"几乎必然继续出问题。

### 建议的方向（尚未立项，仅记录判断）

- **短期**：继续按条目修（US-26/27/28 都是小改动），但**不要假装它们修完就"没有问题了"**。
- **中期**：#47 整改应把上面三类当成**验收维度**而不是缺陷清单——凡涉及"执行者/事实源/共享资源"的设计，都要先回答"出问题时谁说了算、怎么恢复"。
- **长期方向与业界方案评估**：见 [upgrade-architecture-options.md](upgrade-architecture-options.md)（声明式收敛 / 原子切换+回滚 / Expand-Contract / 执行者解耦 / N-2 兼容 五方案对比）。若客户对升级稳定性要求高，值得评估**降低就地升级的自举复杂度**（例如执行者与被升级对象彻底解耦、或支持分阶段外部编排）。这属于架构决策，需用户与产品层面拍板，**不是工程侧能单方面决定的**。

### 本轮四条新缺陷的归类（便于后续跟踪）

- US-24 → ③（同一文件两个视图）
- US-26 → ① + ②（执行者被自己降级；tag 三处不一致）
- US-27 → ②（状态归属不唯一：谁负责收尾没人定义）
- US-28 → ③（共享 SQLite + 连接泄漏）

## D. 测试缺口（⚪，需补进验收矩阵）

| 编号 | 缺口 | 为什么重要 |
| --- | --- | --- |
| US-17 | **回滚路径未验**（`rollback.restore`） | 升级失败后的兜底从没跑过 |
| US-18 | **顺序矩阵未验**：`先平台后 runner`（已验）vs `先 runner 后平台`（未验；US-05 已修，待 .12 MVP 补跑） | 客户顺序不受控 |
| US-19 | **中断恢复未验**（执行中 kill → `recovery_required` → continue/rollback） | 现场断电/重启是常态 |
| US-20 | **Tower 可达时升级后自动采集成功未验** | 环境限制，等 10.20.0.6 恢复 |
| US-21 | **`runner_actions` 拒绝分支无端到端**（仅单测 + 第一轮取证） | 新闸门的失败路径 |
| US-22 | **runner `exit=137` 未抓到直接日志**（推断链：代码+时间线+修复后不复现） | 取证完整性 |

---

## E. 优先级建议（要跑多少格子见 [upgrade-audit-matrix.md](upgrade-audit-matrix.md)，共 **894** 格）

1. **立即**：US-05（改打包口径，去掉 `required_health.runner_version`）→ 补 US-18 顺序验收
2. **#47 整改**：US-01/02/03/06（+ 硬门禁脚本、生命周期收敛、采集事件驱动）
3. **验收矩阵补齐**：US-17/19/21（回滚、中断、拒绝分支）
4. **择机**：US-07/08/09（磁盘校验、长任务心跳、任务噪音清理）、US-20（等 Tower）

> 每条问题的根因细节在 `findings.md` 2026-09-27 各条；执行记录在 `progress.md`。

### US-38 🟢 已修（2026-10-01 `.12` 实测）：迁移导入与 prometheus 压实的并发竞态——导入前备份 FileNotFoundError 失败

- **现象（`.12` 实测，task `migration-import-0fe9891921320426`）**：合并导入第二个迁移包时，
  **backup 步**（导入前备份）失败：`[Errno 2] No such file or directory: '/prometheus-data/01M3N406…'`
  → 整个导入 failed（SQLite/prometheus 均未执行；因 backup 在最前，无部分生效问题）。
- **根因**：web-api 备份时逐文件读取 prometheus 数据目录，而 **prometheus 容器并发压实
  （compaction）**——目录列表后、读取前，旧块被删除/合并 → 读侧 FileNotFoundError。
  C2 ③（执行期共享可变资源）的读侧实例：读列表与读文件之间没有对压实并发的一事务性。
- **为何 `.14` 未踩**：其 prometheus 块少且刚导入，压实窗口没撞上；`.12` 块多且持续运行。
- **修复**：读侧全部容错——`_add_directory`（备份）、`_copy_missing_tree`（合并导入）、
  `_export_candidate_files` 与导出主循环（导出）对「读取中消失的文件/块」跳过并计数
  （被压实删掉的块本来就要消失，备份/导入少它无害；硬失败让导入前备份做不出来才致命）。
- **测试**：mock「拷贝/打包时文件消失」——合并路径跳过且计 raced、备份路径跳过不中断、
  blockA 正常入包。
- **状态**：🟢 修复并测试；`.12` 包2 重导已验证通过（见 progress.md 2026-10-01 恢复验证）。
