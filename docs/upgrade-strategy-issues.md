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
- **状态**：🔴 已识别，靠流程绕开。

### US-02 🔴 runner 版本号是隐式契约（同版本不同能力）
- **现象**：`RUNNER_VERSION` 不随能力变更 → 同一 `v0.3.1` 三副面孔（仓库 26 动作 / 发行包 25 动作 / DockerHub 干脆没有）。
- **证据**：`dab2e0f`(08-12) 给 runner +2053 行但 `git show dab2e0f -- RUNNER_VERSION` 为空；DockerHub tags API 只有 `latest`/`runner-sha-31a1209`/`v0.3.0`。
- **影响**：能力级预检查分辨不了 → 失败落在 cutover 之后。
- **方向**：bump 纪律 + **硬门禁脚本**（发布前自动比对三处同源）+ 动作级校验。
- **状态**：🟡 bump 与动作级校验已做（49-50），**硬门禁脚本未做**。

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

### US-26 🟠 新发现（本轮 .12 验收）：现场 runner 已够用时，平台升级仍按包内基线 tag 重建 runner（不该动却动了）

- **定性（2026-09-28 用户口径修正）**：这不是「runner 版本与平台包基线谁优先」的问题。规则是**条件式**的——默认先平台后 runner；**只有平台确需更高 runner（`minimum_runner_version` 高于现场 runner、平台新增了旧 runner 执行不了的能力）时才先升 runner**。而当前 v0.5.2 → v0.5.3 用已发布 runner v0.3.1 就能完成，**runner 完全不需要动**。所以缺陷是：**平台升级在 runner 已够用时仍然动了它**，且动的方式是按包内基线 tag 强制重建 → 把现场更高的版本降级（实测 v0.3.2 → v0.3.1，无任何提示）。
- **现象**：`.12` 先用组件包把 runner 升到 **v0.3.2**（`upgrade-9fdaff9a349bc257` succeeded，容器 tag / 镜像内 `RUNNER_VERSION` / health 三方一致，存活 90s+），随后用 r6 平台包做 **v0.5.3 → v0.5.3 同版本重装**（`upgrade-26856095c44869d1` succeeded）→ 结束后 runner **变回 v0.3.1**（三处均为 v0.3.1）。
- **根因（代码定位）**：`backend/app/v2/upgrade/compiler.py:229` 从**平台包 manifest** 取 runner 镜像（`images[service=upgrade-runner].image`），`runner.handoff_target_runtime`（`actions.py:1360`）用它写运行时 compose 并 `docker compose up -d --no-deps --force-recreate upgrade-runner` → **无条件按包内 tag 重建**。旁证：组件升级只把新 tag 写进 `compose-runtime/docker-compose.runner-bootstrap.yml`，而 `project/docker-compose.yml`、`compose-runtime/docker-compose.runner-upgrade.yml` 与 `docker compose config` 仍解析为 v0.3.1（tag 没有单一事实源）。
- **预检查侧没问题**：`minimum_runner_version` 按「≥」判定，现场 v0.3.2 跑 r6 预检查全绿（含 `runner_actions`）——即「更高版本合法」已被承认，只有执行阶段把它降了回去。
- **影响范围（重要）**：**对本次发布无影响**——正常客户现场 runner 就是 v0.3.1，降级后仍是 v0.3.1，无感知。**会在「下一版交付 runner v0.3.2」之后咬人**：客户先装 v0.3.2（安装成功、日志显示 `跳过停止旧 runner`），之后再升平台就被静默降回 v0.3.1，US-24 等 runner 侧修复随之丢失，且无提示——属于 AGENTS §6「能力漂移」类风险。
- **修法方向（待实施）**：①**编译计划时解析 runner 镜像**：现场 runner 版本 ≥ 包 `minimum_runner_version` 时，handoff 用**现场实际镜像**而不是包内 tag（计划里记录实际会跑的镜像，可审计）；②或动作层：目标 tag 与当前运行 tag 相同则不 `--force-recreate`，现场版本更高时保留现场版本；③补「现场 runner 高于包基线」的回归用例。组件升级侧同时应回写 project compose / runner-upgrade compose，消除 tag 多事实源。
- **证据**：`.12` 2026-09-28 23:08→23:14 实测；`compose-runtime/docker-compose.runner-bootstrap.yml`=v0.3.2 而 `docker-compose.yml`/`docker-compose.runner-upgrade.yml`/`docker compose config`=v0.3.1。
- **状态**：🟠 **新发现未修**（口径已由用户 2026-09-28 明确；**不阻塞 v0.5.3 发布**，须在**交付 runner v0.3.2 之前**修完）。

### US-27 🟠 新发现（本轮 .12 验收）：US-25 逃生门只改状态，不清理也不回滚 → 旧路径残留

- **现象**：任务被中断后走 `recovery/fail` 标记失败，**环境留下半迁移残留**：`/data/upgrades/upgrade-925f38527816ae1f/package`（被中断任务在旧路径的包目录）与 `/data/smartx-capacity-insight-data/{app,prometheus}`（空骨架，被中断升级的 `filesystem.prepare` 造出）重新出现 → 8 项验收第 7 项「legacy 路径全 missing」判**异常**。
- **数据红线**：**未受损**——live 库 `/data/smartx-storage-forecast/app/smartx.db` `integrity ok`、556/89588 与升级前一致；旧数据目录仅 12K 空骨架，无数据分叉。
- **收干净的方式**：再跑一次成功升级，其 post-cleanup 会清掉全部 legacy 路径（本轮实测 `upgrade-26856095c44869d1` 的 post-cleanup succeeded，7 条路径全清）。
- **方向**：逃生门在标记失败时提示"环境可能半迁移，需再跑一次升级让 post-cleanup 收尾"，或在 `recovery/fail` 响应里带 `cleanup_required=true` + 残留路径清单；理想是提供"标记失败并清理残留"的产品化收尾动作。
- **状态**：🟠 **新发现未修**（逃生门已能解冻环境，但收尾靠人工再跑一次升级，UI 无提示）。

### US-28 🟠 新发现（本轮 .12 验收）：runner 组件升级后有约 10 分钟 SQLite 写锁窗口，web-api 写操作直接 500

- **现象**：`.12` 跑 runner v0.3.1 组件升级后，紧接着的 **v0.5.2 平台步预检查连续 3 次 HTTP 500**（`sqlite3.OperationalError: database is locked`），心跳当时新鲜（age=2s）、health 全绿——**不是 US-08 心跳问题**。
- **根因取证**：锁的持有者是 runner 容器主进程（`python -m app.upgrade_runner.main`，`hrtimer_nanosleep` 空闲态），它持有**大量未关闭的 DB 连接**：`/proc/<pid>/fd` 指向 `/data/smartx.db` 的 fd 数实测 **52 → 30 秒后降到 14**；DB 目录无 `-wal/-shm`，即 rollback journal 模式，未提交事务独占写锁。约 10 分钟后锁自行释放，预检随即正常（7 项全 true）。
- **影响**：升级链上「组件升级 → 下一个平台步」这一常见组合会随机失败，且失败形态是裸 500（无重试/无友好提示），运维只能干等重试。上轮 `rebuild_all.sh` 记录的「v0.5.2 升完预检 `runner_protocol=False`」也是同一窗口的不同表现。
- **方向**：①runner 侧改用 WAL + 短事务/显式 close，消除长写锁（**改 runner → 需用户同意并 bump 版本**）；②web-api 侧对 `database is locked` 做有限重试/退避并返回可读提示，而不是裸 500；③验收驱动脚本在组件步之后显式等待锁释放（本轮已按此处理）。
- **证据**：`.12` 2026-09-28 22:29–22:40（`upgrade-b32d44b1badb1783` 之后），web-api 容器日志三连 500 + `fuser` 定位 + fd 计数两次采样。
- **状态**：🟠 **新发现未修**。

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
