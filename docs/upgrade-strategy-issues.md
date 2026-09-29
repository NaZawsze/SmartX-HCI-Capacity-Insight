# 升级策略问题细分清单（2026-09-27 复查）

用途：把「升级策略 / runner / web-api」当前所有已知问题**逐条拆细**，每条给出现象、根因、证据、影响、修复方向与状态。执行计划与验收证据见
[superpowers/plans/2026-09-27-v053-full-chain-acceptance-plan.md](superpowers/plans/2026-09-27-v053-full-chain-acceptance-plan.md)；
整改立项见 `docs/pending-tasks.md` #47；根因记录见 `findings.md` 2026-09-27 各条。

状态图例：🔴 未修（有风险）｜🟠 已绕开未根治｜🟡 规则已立未脚本化｜🟢 已修复并验证｜⚪ 测试缺口

---

## A. 架构/契约层（骨架级）

### US-01 🔴 源端执行：平台包的新校验对"当次升级"无效
- **现象**：编译计划（`execution.py:32 compile_execution_plan`）、预检查、执行编排全部运行在**源端 web-api**；平台包带来的新逻辑只存在于目标镜像里，**当次升级用不到**。
- **证据**：49-50 的动作级预检查与"同 project 不停 runner"修复，对 `v0.5.2 → v0.5.3` 这一次完全无效（`.12` 三轮实测：老 web-api 照跑老逻辑）。
- **影响**：所有安全增强都"晚一代"；v0.5.3 的预检查只能保护 v0.5.3→v0.5.4。
- **方向**：无代码级解法 → 只能用「发布顺序写死 + 源端版本矩阵验收 + 文档写死」压制（#47③）。
- **状态**：🟠 **定性已更正（2026-09-28）**：查证 Kubernetes 的 version skew policy 后确认，**「旧版本组件执行升级、新版本逻辑当次不生效」是业界常态而非缺陷**（K8s 明确支持控制面与节点版本偏斜，升级时执行的就是旧 kubelet）。**正解不是重构，而是把版本偏斜策略写死（支持矩阵）+ 补齐 N-2 兼容与实测**。原「🔴 架构缺陷」定性作废，架构方向（控制面/执行面分离）经核对与业界一致。详见 `docs/upgrade-architecture-options.md` §0.5。

### US-02 🔴 runner 版本号是隐式契约（同版本不同能力）
- **现象**：`RUNNER_VERSION` 不随能力变更 → 同一 `v0.3.1` 三副面孔（仓库 26 动作 / 发行包 25 动作 / DockerHub 干脆没有）。
- **证据**：`dab2e0f`(08-12) 给 runner +2053 行但 `git show dab2e0f -- RUNNER_VERSION` 为空；DockerHub tags API 只有 `latest`/`runner-sha-31a1209`/`v0.3.0`。
- **影响**：能力级预检查分辨不了 → 失败落在 cutover 之后。
- **方向**：bump 纪律 + **硬门禁脚本**（发布前自动比对三处同源）+ 动作级校验。
- **状态**：🟢 **已完成（2026-09-27，49-54）**：`scripts/verify_runner_delivery_consistency.py` 把「三处同源核对」做成一条命令（C1 仓库 `RUNNER_VERSION`／C2 动作表 AST 静态提取／C3 三个源码 compose 字面量 tag／C4 组件包 manifest 与镜像归档 SHA256／C5 **离线解析包内镜像归档比对 `RUNNER_VERSION` 与 `actions.py` md5 与仓库一致**／C6 DockerHub tag 200 默认关闭），任一 FAIL 非零退出、SKIP 必须显式；配对单测 22 例；**已接入 `docs/release-acceptance.md` 发布门禁第 4 步**。`.3` 实证：v0.3.2 包全绿，v0.3.1 包（`dd096bf2…`）正确 FAIL。**本条关闭**。

### US-03 🟠 runner 生命周期散落三个入口
- **现象**：组件升级（web-api `compose stop/up`）、平台升级 handoff（runner 自己 `docker run` helper）、legacy 清理（runner 动作 `runner.stop_legacy_runtime`）三方都能动同一个 runner 容器。
- **证据**：`execution.py` 的 bootstrap stop、`actions.py:1449` handoff、`actions.py:1548` stop_legacy。
- **影响**：时序 bug 温床 —— US-04 就是这么产生的。
- **方向**：收敛到单一入口（建议统一由"当前源端"决定，且**先比对 compose project 再决定是否停**）。
- **状态**：🟠 平台侧已加守卫（`_should_stop_previous_runner`），**未收敛**。

### US-04 🟠 老 web-api 的无条件 stop（v0.5.2 源端，改不到）
- **现象**：目标布局机器上**原地**做 runner 组件升级，新 runner 启动后 10 秒被 SIGKILL（`exit=137`），心跳过期 → 后续预检查报"未检测到 upgrade-runner 心跳"。
- **根因**：`execution.py` 在 `_runner_bootstrap` 时无条件 `docker compose --project-name <当前project> stop upgrade-runner`；同 project 场景下停的就是刚启动的新 runner。
- **证据**：`.12` 两轮复现（08:16、09:04 UTC，启动后 10s kill，docker events `start → kill(+10s) → stop/die`）；第四轮加守卫后 **runner 存活 90s**。
- **影响**：**B-b「先升 runner 再升平台」在 v0.5.2 现场不可行**；客户若强行先升 runner 仍会踩（老镜像改不到）。
- **方向**：流程定死「先平台、后 runner」（#47③）；老现场无代码解法，只能靠文档与升级中心提示。
- **状态**：🟠 已绕开未根治。

---

## B. 升级流程/断言层

### US-05 🟢 已实施；顺序验收不做（用户 2026-09-28 定）：post-cleanup 健康断言"版本相等"→ 升级顺序敏感
- **现象**：`_require_cleanup_health`（`upgrade_runner/actions.py:1884-1886`）用 `!=` 等值比较 `required_health.runner_version`。manifest 现在写 `v0.3.1`：先升平台（runner=v0.3.1）✅；**先升 runner 到 v0.3.2 再升平台 → "清理前 runner 版本不匹配" → 升级成功但 post-cleanup 失败**（旧环境不清理、残留累积）。
- **证据**：代码可证（`if expected_runner and ... != expected_runner: raise`）；第四轮只测了"先平台"顺序，未覆盖另一条。
- **方向**：平台侧打包时**不写** `required_health.runner_version`（代码 `if expected_runner` 为空即跳过），只校验平台版本 + 三项 health；或改为"≥"语义（需改 runner，须 bump，且老 runner 收不到）。
- **状态**：🟢 **已实施（49-52，提交 8115c41）**；**2026-09-28 用户决定：runner-first 顺序不是受支持链路（链路只有"先平台、后 runner"），且 v0.3.2 不随本次发布 → M3-08/M3-10 两格记 N/A、不做顺序验收**；本项按「代码 + manifest 实证的防御性修复」记录（r5 候选包 manifest 实证 `required_health` 无 `runner_version`），发布材料不得写"顺序无关已实测"。原状态描述：**已实施（49-52，提交 8115c41）**：`build_upgrade_package.py` 的 `required_health` 移除 `runner_version`（runner 侧 `if expected_runner` 空即跳过，无需 bump runner）；候选包 `b9560eee…` 的 manifest 已无该字段（`required_health` 仅 `version`+`checks`），`.3` 门禁全过；**`.12` MVP（先 runner 后平台顺序）待授权执行**。设计：`docs/superpowers/specs/2026-09-27-us05-us23-release-blocking-fix-design.md`。

### US-06 🟠 升级后采集链路：5 秒常驻轮询 + 落盘便条 + 冗余的 runner 写便条
- **现象**：`worker.py` 每 5 秒扫 `upgrades/*/`（常驻、无开关、无指标）；便条本应由触发方写，却让 runner 插手（而这正是 49-49 要删的冗余）。
- **证据**：`worker.py:458` `seconds=5`、`worker.py:195` 平台可自建标记（`source=target_worker_compatibility`）。
- **影响**：功能正确、开销可忽略，但**事件驱动的事用高频轮询**，链路隐蔽、难观测、难关闭。
- **方向**：升级成功时平台侧直接投递采集任务；轮询降为 30~60s 兜底；加开关与指标（#47①）。
- **状态**：🟠 已立项未实施。

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
- **状态**：🟠 **已实施（49-52，提交 8115c41/32f9a95）**：`execution.py::start()` 增加 `_ensure_no_active_upgrade`（ACTIVE={pending,running,runner_restarting,recovery_required,rollback_pending,rollback_running}；类级 `threading.Lock` 消除扫描-认领竞态；retry/recovery/rollback 同守卫，cancel/delete 不拦）；新增 `test_upgrade_single_flight.py` 9 用例 + API 测试断言；`.3` 全量 386 OK。**`.12` 已验证（2026-09-28）**：平台升级 `upgrade-b07795625cf0d681` 执行中，第二个已预检通过的包 `upgrade-88e7262584becb7c` 的 start → **400** `升级任务 … 正在执行或需要恢复，不能开始新的升级。`；另验证逃生门标记失败后守卫正常释放（新 start 恢复放行）。runner 执行前重验 source_compatibility 未做（需 bump runner，留 #47）。

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
- **状态**：🟠 **已实施（2026-09-28，提交 7083d72/fe555be），待 `.12` 复验**。方案**实施中修正**（设计 §3.2）：初版「计划带 preserve_current + 动作层沿用现场镜像」会**打挂主路径**——已发布 runner v0.3.1 收到空 image 会 `raise ValueError` 导致 v0.5.2→v0.5.3 失败，且需改 runner（AGENTS §6）。最终改为**编译期由 web-api 解析现场 runner 镜像注入 manifest 副本**，编译器照常下发具体镜像，**旧 runner 零改动**、向后兼容。`.3` 门禁全绿（后端 468 OK、build 26 OK、identity 0、交付一致性 C1–C5 全 PASS 证明 `actions.py md5 matches repo` runner 未动、候选包 r8 `3672e920`）。**`.12` 复验全部通过（2026-09-28）**：①**主路径回归** v0.5.2+已发布 runner v0.3.1 → r8 直升 `upgrade-6f035c3e52b83428` succeeded（188s）+ 8 项验收全过，**runner 仍 v0.3.1**（未被无故改动）；②装 v0.3.2 组件包 `upgrade-39600ca4b67b75ad` succeeded，三方一致 v0.3.2、存活 90s+；③**判别格**：v0.5.3 同版本重装 `upgrade-7c0720d6207ea942` succeeded（<10s）、**runner 仍 v0.3.2**（容器 tag / 镜像内 `RUNNER_VERSION` / health 三方一致），**修复前同操作会回落 v0.3.1**；最大 attempt 1、runner 重启 0（US-24 无回归）、8 项验收全过、DB 556/89588 不变、7 条 legacy 路径全清；④US-23 抽查 400 正常。另修 US-26-4 回写正则（真实 compose 在 `upgrade-runner:` 后先有 `build:` 块，`image:` 位置不固定 → 改逐行状态机，提交 4c7ed07）。

### US-27 🟠 已实施待 .12 复验：US-25 逃生门只改状态，不清理也不回滚 → 旧路径残留

- **现象**：任务被中断后走 `recovery/fail` 标记失败，**环境留下半迁移残留**：`/data/upgrades/upgrade-925f38527816ae1f/package`（被中断任务在旧路径的包目录）与 `/data/smartx-capacity-insight-data/{app,prometheus}`（空骨架，被中断升级的 `filesystem.prepare` 造出）重新出现 → 8 项验收第 7 项「legacy 路径全 missing」判**异常**。
- **数据红线**：**未受损**——live 库 `/data/smartx-storage-forecast/app/smartx.db` `integrity ok`、556/89588 与升级前一致；旧数据目录仅 12K 空骨架，无数据分叉。
- **收干净的方式**：再跑一次成功升级，其 post-cleanup 会清掉全部 legacy 路径（本轮实测 `upgrade-26856095c44869d1` 的 post-cleanup succeeded，7 条路径全清）。
- **方向**：逃生门在标记失败时提示"环境可能半迁移，需再跑一次升级让 post-cleanup 收尾"，或在 `recovery/fail` 响应里带 `cleanup_required=true` + 残留路径清单；理想是提供"标记失败并清理残留"的产品化收尾动作。
- **状态**：🟠 **已实施（2026-09-28，提交 9d60a68/4a5b2f1，`.3` 门禁全过）**：`recovery/fail` 增加 `_residual_legacy_paths()` **只读**探测（7 条 legacy 路径）+ 任务视图暴露 `cleanup_required` / `residual_paths`；`error` **追加**（不覆盖原失败语义）收尾指引「环境可能半迁移 → 重跑一次完整升级由 post-cleanup 收尾 → 之前不要开始新升级」；前端新增「需要收尾」面板显示残留路径。测试 8 例（含只读性断言：探测不得含 rmtree/unlink/mkdir）。**`.12` 复验待授权**。

### US-28 🟠 新发现（本轮 .12 验收）：runner 组件升级后有约 10 分钟 SQLite 写锁窗口，web-api 写操作直接 500

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

### US-30 🔴 新发现（第 3 批实测）：升级成功但 post-cleanup 从不执行——**没有客户端轮询就永不收尾**

- **现象**：`.12` 上 task `upgrade-0de5b6ad24d41c56` **14 个动作全部 succeeded**（含 `post_upgrade.schedule_cleanup`），任务状态 `success`，但 `/data/smartx-capacity-insight-data`、`/prometheus-data`、`/data/upgrades` 三条 legacy 路径**至今残留**。
- **根因（代码定位）**：`_maybe_schedule_post_upgrade_cleanup()`（`execution.py:648`）只在 `_normalize_completed_runner_task()` 里被调用，而后者**仅在两处被触发**：`execution.py:151`（`status` 接口，即**客户端轮询**）与 `cleanup.py:104`。**worker 侧没有任何后台兜底**。
  - 任务执行完毕 → 计划已落 `post_upgrade_cleanup_task_id: None`（清理任务未创建）
  - `post_upgrade.schedule_cleanup` 动作只写了**标记文件**（`marker_path: /data/upgrades/<id>/post-upgrade-collection`），本身不清理
  - **只要没人调用 `status` 接口，清理任务就永远不会被创建**
- **触发场景**：本轮实测——start 后**未等完成就返回/取消**，期间无任何 UI 轮询。真实客户若用脚本/定时任务发起升级而不持续轮询状态，就会命中。
- **影响**：**升级"成功"但旧环境不清理**，磁盘持续增长（每次升级还留一份 ~4.7MB 备份，实测 `backups/` 累积 5 份），且残留目录会让后续升级的 legacy 扫描面变大。这是 US-27 的**第三个实例**，但机理不同（不是"标记失败不收尾"，而是"根本没人触发"）。
- **方向**：①把「任务终态 → 投影 + 创建 post-cleanup」做成**后台兜底**（worker 或 web-api 守护线程扫 `success` 且无 `post_upgrade_cleanup_task_id` 的任务并补建），不依赖客户端轮询；②或由 runner 在 `schedule_cleanup` 后直接投递清理意图；③补一条断言：平台升级成功后，**不调用 status 接口**也应最终产生 cleanup 任务。
- **证据**：`.12` 2026-09-28 13:30–14:0x（`auto_rollback.log` 收尾 8 项验收第 7 项报 3 条 EXISTS + U1 任务文件取证）。
- **状态**：🔴 **新发现未修**（US-27 的延伸，建议与 US-27 一并修）。

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
- **仍未做（需排期）**：**失败任务留下的备份无人回收**。`.12` 实测 `backups/` 累积 **13 份 / 79MB**（`backup.create` 先成功、后续 `image.load` 失败所致）。需定策略：成功任务保留 N 份或按 TTL，失败任务随取证期到期清理。此项会持续增长磁盘占用，属运维债而非正确性问题。

### US-32 🔴→🟢 已修（第 5 批实测）：compose 的 runner tag 回写**自实现起从未生效**（只读挂载 + 静默吞错）

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
