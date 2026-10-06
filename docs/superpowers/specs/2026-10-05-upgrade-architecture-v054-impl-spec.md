# 实施级详设：升级架构重构（runner v0.3.2 + 平台 v0.5.4）

- 日期：2026-10-05
- 上位设计：[2026-10-05-upgrade-architecture-v054-design-v2.md](2026-10-05-upgrade-architecture-v054-design-v2.md)（架构决策与理由）
- 本文档定位：**工程实施规格**——交给实施 AI/工程师填充代码用。每项工作给出：现状（文件:行）、目标行为、
  数据结构、错误处理、测试与验收判据。
- 实施者须先读：AGENTS.md（全文）、docs/project-guide-for-ai.md、本文档。

---

## 0. 给实施 AI 的须知（红线，违反即返工）

1. **验证纪律**：任何"已完成/已通过"结论必须有真实测试输出或 `.3`/`.14` 真机证据；单测全绿 ≠ 脚本能跑
   （AGENTS §12）。测试用例**必须写在类内、`if __name__` 之前**（历史上发生过写在 main 块后静默不跑）。
2. **不删旧路径**：旧编译器/旧组件升级编排保留为兜底，直到新路径在 `.14` 全绿（批次 C）。
3. **动作词汇冻结**：平台升级计划只准使用 runner v0.3.1 已有的 26 个动作（清单见 §1.3）。
   新增动作仅允许出现在"由 v0.3.2+ runner 执行"的任务中，且必须过 §W7 门禁评审。
4. **版本治理**：runner 版本号 v0.3.2 沿用（从未交付，governance 允许并入）；**任何 runner 代码变更必须
   在同一次提交内完成**（历史事故 `dab2e0f`）。RUNNER_VERSION 不得私自再 bump。
5. **凭据/机器纪律**：不在任何日志/文档/提交里记录密码；`.12` 只走产品流程；`.3` 随便造但不影响交付物。
6. **兼容是硬约束**：§10 兼容矩阵的每一格都必须工作。拿不准时，先问设计文档，再问用户。

## 1. 现状代码地图（2026-10-05，dev2 `8deb053`）

### 1.1 runner（backend/app/upgrade_runner/）

| 文件 | 行数 | 职责 | 关键点 |
| --- | --- | --- | --- |
| actions.py | 2722 | 26 个动作实现 | `compose.apply`:1280、`rollback.restore`:2595、`default_handlers`:2692 |
| main.py | 660 | 主循环（3s 轮询）+ 心跳线程（5s） | `_project_task`:359（**直接写业务库 tasks 表**）、`_writeback_runner_compose_tag`:120、`_apply_tag_writeback_if_needed`:197、`_finish_runner_component_steps`:211（组件任务重启后收尾，**:471-493 调用**）、`_is_runner_component_task`:98、`_heartbeat_until_done`:404、`_heartbeat_with_retry`:426（#82 修复） |
| engine.py | 282 | 任务修订/检查点/task.json 读写 | US-24 修复（inode 判等）在此 |
| lease.py | 154 | `LeaseManager`（租约+实例心跳） | 表：`upgrade_runner_state`、`upgrade_task_leases`；`_connect` 已改显式关闭（US-28 缓解） |
| store.py | 52 | task.json 读写 | |
| sandbox.py | 69 | `script.run_sandboxed` | |

### 1.2 web-api 升级侧（backend/app/v2/upgrade/）

| 文件 | 行数 | 职责 |
| --- | --- | --- |
| service/execution.py | 769 | start/cancel/recovery/rollback/status；`_should_stop_previous_runner`:27（US-04 守卫） |
| service/precheck.py | 665 | v0.5.2 有 7 检查；v0.5.3 +`runner_actions`+`disk_space`（9 项） |
| compiler.py | 415 | manifest → 动作计划（逐 `actions.append`） |
| service/taskfile.py | 300 | task.json 读写 |
| service/intake.py | 266 | 上传/解包/建任务 |
| service/runner_presence.py | 105 | 双通道在场判定（实例心跳/任务租约，30s 阈值） |
| settlement.py | 160 | 升级收尾守护线程 |
| service/{paths,fs,cleanup,verification}.py | — | 路径/文件/清理/验证 |
| housekeeping.py / backup_retention.py | 278/271 | 产物清理/备份保留 |

### 1.3 runner v0.3.1 动作词汇表（26 个，冻结基准）

`backup.create, image.load, filesystem.prepare, files.sync, compose.override, compose.project_migrate,
script.run_sandboxed, compose.apply, runner.handoff_target_runtime, runner.schedule_target_runtime_handoff,
runner.stop_legacy_runtime, post_upgrade.schedule_cleanup, post_upgrade.schedule_collection,
post_cleanup.precheck_target_health, compose.stop_legacy_project, network.remove_legacy,
filesystem.cleanup_legacy_paths, filesystem.cleanup_target_app_residuals, post_cleanup.verify,
health.http, health.prometheus, task.migrate_runtime_state, task.sync_runtime_state, legacy.cleanup,
checkpoint.write, rollback.restore`

---

## W1 Runner 状态文件（US-28/#82 根治）

### 现状
`LeaseManager`（lease.py）直接读写业务 SQLite 两张表：实例心跳 `upgrade_runner_state`（3s 轮询刷一次，
执行期冻结）+ 任务租约 `upgrade_task_leases`（执行期 5s 续租）。web-api 侧 `runner_presence.py` 读同两张表。

### 目标
- 新模块 `backend/app/upgrade_runner/statefile.py`：`RunnerStateStore(path, instance_id, runner_version, protocol_version, capabilities)`。
- **路径**：`Path(database_path).parent / "upgrade-runner-state.json"`（容器内 `/data/upgrade-runner-state.json`，
  宿主机 `app/upgrade-runner-state.json`）——runner 与 web-api 共享同一 `/data` 挂载，从 DB 路径推导、**不硬编码**。
- **Schema**（版本字段兜底演进）：

```json
{
  "schema": 1,
  "instance_id": "…", "runner_version": "v0.3.2", "protocol_version": 3,
  "capabilities": ["backup.v1", "…"],
  "started_at": "…UTC ISO…", "heartbeat_at": "…", "updated_at": "…",
  "leases": {
    "<task_id>": {"lease_owner": "…", "lease_expires_at": "…", "heartbeat_at": "…",
                   "revision": 42, "checkpoint": {…}}
  }
}
```

- **写协议**：同目录临时文件 → 写入 → `flush`+`fsync` → `os.replace` 原子替换。单写者 = runner 进程。
  触发点：主循环每轮（3s）、心跳线程每 5s、租约变更时。文件 < 64KB，开销可忽略。
- **自愈**：启动读取时 JSON 损坏 → 把坏文件改名 `.corrupt-<ts>` 留证 → 视为无状态重建。
- **公共 API**（保持 LeaseManager 现有调用面不变，只换存储）：
  `heartbeat()/upsert_lease(task_id, owner, ttl)/renew_lease(task_id)/release_lease(task_id)/save_checkpoint(task_id, cp)/read()`。
- **DB 兼容镜像（expand 期）**：`LeaseManager` 保留对两张表的写入，但每处包 `try/except: log warning`——
  **失败绝不 raise、绝不重试阻塞**（#82 兜底语义升级为"镜像失败无害"）。v0.5.4 web-api 读文件优先（见下）；
  收缩（停止 DB 镜像）在 v0.5.3 web-api 退出支持矩阵后执行（登记 contraction 清单）。
- **web-api 读取**：`runner_presence.py` 新增 `read_state_file(settings) -> dict | None`（容错：缺失/损坏 → None）；
  `presence_source` 判定顺序改为：**文件实例心跳 → 文件租约 → DB 实例心跳 → DB 租约**（来源名沿用
  `heartbeat`/`task_lease`，语义不变）；`task_lease_is_alive` 同样先查文件。
  v0.5.4 + v0.3.1 组合：文件缺失 → 全部落 DB（v0.3.1 只写 DB）→ 行为与今天一致。

### 验收
- 单元：原子写并发（模拟中断无半文件）、损坏自愈、schema 演进容错。
- 真机：`.14` 升级窗口内 `app/upgrade-runner-state.json` 持续刷新；web-api 升级页 runner 在场判定正常。

## W2 单写者规则（US-24 根治）

### 现状
runner `_project_task`（main.py:359）把任务状态**直接写业务库 tasks 表**；web-api 也写同一行 → 双写者。

### 目标
- **事实源 = task.json**（文件）：执行期 runner 独占写；web-api 只读。
- **tasks 表 = web-api 独占投影**：web-api 在 `UpgradeService.status()` 与 settlement 扫描时，发现 task.json
  比库内新 → 投影更新（status/message/progress/steps/updated_at）。runner 的 `_project_task` 改为
  **best-effort 兼容镜像**（try/except log，低频——每步骤转换一次，非热路径），v0.5.3 web-api 依赖它显示
  进度；v0.5.4 web-api 起以投影为准，镜像在收缩期移除。
- 热路径（5s 心跳/租约）已由 W1 全部出库——**US-28 的根因面清零**。

### 验收
- 单元：投影幂等（重复投影不产生副作用）、file newer 判定。
- 真机：升级执行期间 `sqlite3` 侧无 runner 连接（`lsof` 按容器 PID 查）；任务中心进度正常。

## W3 runner 自换组件升级（kubeadm/Omaha）

### 现状
组件升级 = web-api 编排（写 runner compose → recreate），runner 侧已有：组件任务识别（`_is_runner_component_task`）、
重启后收尾（`_finish_runner_component_steps`，main.py:471-493）、compose tag writeback（`_apply_tag_writeback_if_needed`）、
`runner.schedule_target_runtime_handoff` 动作。

### 目标流程（v0.3.2 起生效；v0.3.1→v0.3.2 这一跳仍走旧编排=最后一次）
1. **web-api**：intake 校验组件包（tar + `manifest.json{version, image_tar}`，SHA256 侧车核验）→ 落
   `upgrades/component-<id>/` → 建任务（components=["runner"]，steps=`[verify, load, writeback, handoff, presence_wait]`，
   manifest 带 `target_version`、`image_tar`、`previous_version`）→ 提交（现有轮询机制送达）。
2. **runner** 拾取组件任务后执行：
   a. verify：tar SHA256 复核；
   b. `image.load`（复用现有动作逻辑）；
   c. compose writeback（复用 `_apply_tag_writeback_if_needed`）——**writeback 前先捕获回滚锚点**
      `{previous_version, previous_image_tag, previous_image_id}` 存入 task.json + 状态文件；
   d. `runner.schedule_target_runtime_handoff`（现有动作）：调度替换 → runner 退出 → Docker 重建；
3. **新 runner** 启动 → 首个轮询周期 `_finish_runner_component_steps` 判定 runner_version==target → 步骤收尾 → 任务 success；
4. **web-api** 轮询 task.json + 状态文件：`runner_version == target_version` 即完成；**presence 超时 120s** →
   任务 `failed` + 恢复动作 = 兜底重建（`docker compose up -d upgrade-runner`，web-api 现有能力）+ 回滚锚点可用。
5. **组件回滚**：锚点保留 → 反向自换（同流程，target=previous_version）。旧组件包在保留期内不删（backup_retention 联动）。

### 验收（T11）
`.14`：v0.3.2→v0.3.3-rc 自换——服务中断 ≤30s、新 runner presence ≤60s、web-api 全程零 compose 编排调用、
restarts 计数符合预期（旧容器被 replace，新容器 restarts=0）。

### W3b 路径出处审计（2026-10-05 补充，宿主/容器路径混用的系统性修复）

**发现（.3 交付实例实测取证）**：runner 写运行时 compose 用宿主风格路径
`/data/smartx-storage-forecast/compose-runtime`，在容器内穿过 app bind 落进 UPG-050 载体
`app/smartx-storage-forecast/compose-runtime/`（10-03 的 v0.3.2 文件）；辅助容器挂载**真实**目录
（8-12 的 v0.3.1 旧文件）→ **8-12 起 handoff 新配置全部被忽略**，平台升级 handoff「实测通过」
是旧文件恰好描述了当时正确的目标。真实 compose-runtime 其实已正确挂载在 runner 的
`/data/compose-runtime`——纯路径选择错误。

**决策（用户 2026-10-05 批准）：方案 A**——runner 内部一律用容器路径，仅在 `docker run -v` /
`docker compose -v` 边界用 `ActionContext.docker_host_path` 翻译为宿主路径。否决方案 B
（给 runner 补挂真实路径 = 改 compose = 动 config-hash = 正面撞 US-26/US-37 热点 + 四交付面同步）。

**实施要求**：
1. 盘点 `actions.py`/`main.py` 全部**文件写点**与全部 **-v 挂载点**，产出清单（允许写进测试注释）：
   容器内写一律容器路径；宿主路径只允许出现在 -v 字符串与传给下一版 runner 的
   `SMARTX_HOST_*` env 里；
2. 修复 `_runner_runtime_paths`、`_write_runner_runtime_compose`、`_target_upgrade_state_path`、
   辅助容器挂载构造、`compose.override` 等其它写路径动作；
3. 回归测试：构造「双视图」环境（app 载体 vs 真实目录并存）断言写入落在真实目录；
4. A 落地并验证后清理载体中的陈旧 `docker-compose.runner-upgrade.yml`
   （**只删文件、不动载体目录本身**——UPG-050 红线）；
5. M1/M2（平台升级 handoff）与 T11（自换）真机重跑——路径修复触碰平台升级路径，旧结论作废。

## W4 compose diff 收敛（US-26 根治）

### 现状
`compose.apply`（actions.py:1280）按 plan 给定服务列表 `up -d --no-deps <services>`——**compose 原生行为**
对配置未变的服务本来就是 no-op；US-26 的降级来自 handoff 路径的 `--force-recreate`。

### 目标（三层防护）
1. **前置断言**：服务列表含 `upgrade-runner` → 拒绝该服务并记 warning（编译器本就排除，防回归）；
2. **观测**：apply 前对列表内每个服务做 best-effort 判定（运行容器 image ID/`com.docker.compose.config-hash` label
   vs 期望配置），日志输出 `将重建: […]；未变更: […]`——**不做自研哈希**（脆弱），以 compose 原生收敛为准绳；
3. **apply 后断言**：`upgrade-runner` 容器 ID 与 apply 前一致（若变化 = 步骤失败，宁可失败不可静默降级）。
- 禁令重申：任何代码路径不得引入 `--force-recreate`（加 grep 门禁到 W7）。

### 验收（T3）
`.14` 平台升级：prometheus、upgrade-runner 容器 ID 不变；任务日志含差异清单。

## W5 回滚三场景（US-17 关闭）

### 场景 A：失败自动回滚（runner 侧策略，零新动作）
- runner 执行平台升级任务时，在**首次 compose.apply 之前**捕获回滚锚点（三件套当前 image tag + 镜像 ID），
  存 checkpoint（现有 `checkpoint.write`）+ 状态文件。
- 触发（2026-10-06 修订，实施发现的规格修正——已核实 v0.5.3 引擎 f07e581:154 起 health.* 失败本就
  自动回滚，故「缺省 false」一刀切会让老 manifest 丢掉既有回滚能力，属行为回退）：
  **刻意不对称**——①`health.*` 失败**无条件回滚**（保留 v0.5.3 既有行为，不受开关影响）；
  ②`compose.apply` / `post_upgrade.*` 失败需 manifest 显式 `rollback_on_failure: true` **且**锚点已捕获
  （新触发面 opt-in，老 manifest 行为不变）；仅对平台组件任务生效（组件任务有自己的锚点回滚，见 W3）。
  另：自动回滚的机制从旧 `rollback.restore`（整库恢复 = 场景 C 语义，会吞采集数据）改为**锚点驱动的
  应用回滚**（只指回三件套旧 tag，数据不动）——旧动作保留为无锚点时的兜底路径。
- 动作序列（runner 内部子流程，复用现有动作实现函数，不进计划词汇）：`compose.override`（旧 tag）→
  `compose.apply` → `health.*` → 终态 `rolled_back`（失败证据完整保留）；回滚失败 = `rollback_failed` → 现有 recovery。
- **修复 v1 的首升局限**：v0.5.3 编译的任务 payload 内含完整 manifest → v0.3.2 runner 照样能读到
  `rollback_on_failure` → **v0.5.3→v0.5.4 首升即有自动回滚**。

### 场景 B：手动应用回滚（保数据）
- 锚点：**不新建第三份文件**（2026-10-06 落地修订）。A5 已把锚点写在 ①`task.json`
  ②状态文件持久段 `rollback_anchors`（`e594432` 修掉"任务结束锚点随租约消失"）；
  B8 读状态文件为事实源、回退扫 `task.json`。三份锚点一旦不同步，回滚会按过期值执行——
  比没有锚点更危险。原写的 `app/rollback-anchor.json` 作废。
- API：`GET /api/admin/upgrade/rollback-availability` → `{available, blockers[], target_version}`；
  判定 = ①旧镜像在本地（docker image inspect）②未执行 contract 迁移（migration registry 快照对比）
  ③无进行中任务（单飞守卫）。
- 执行：`POST /api/admin/upgrade/rollback` → 建 rollback 任务（v0.5.4 web-api 自己的编译路径生成：
  override 旧 tag → apply → health）→ 单飞/审计/任务中心全适用。前端：升级中心「回滚到上一版本」入口。

### 场景 C：整备回滚（应用+数据）
- 走 **`script.run_sandboxed`**（v0.3.1 已有动作，零词汇变更）：包内附带沙箱恢复脚本
  （停平台写方 → 恢复 SQLite/Prometheus/.env（`docs/backup-recovery.md` 五步）→ 指回旧 tag → 起服务）。
- 前端强确认：提示数据丢失窗口（升级时刻 → 现在）。
- 前提检查同场景 B，另加 `backup 文件存在且 SHA 通过`。

### 迁移纪律（三场景的地基）
`backend/app/v2/upgrade/migrations/registry.json` 新增条目**只允许加列/加表**；破坏性操作延后到 contract。
门禁见 W7。

## W6 七步常量流程 + 编译器瘦身

- 现状：compiler.py 按 manifest 条件分支 append 动作。对不含
  `environment_transitions/legacy_cleanup/runner 组件` 的 v0.5.4 manifest，v0.5.3 编译器输出的计划
  ≈ `backup → image.load×3 → filesystem.prepare → files.sync → task_state → compose.override → compose.apply →
  health×2 → post_upgrade.schedule_collection`（≈10 步，已接近七步；`project_migrate/legacy/handoff` 不会出现）。
- 本版工作：①**断言测试**锁死"v0.5.4 包 × 各源版本 → 计划不含迁移/交接/legacy 动作"（防编译器回归）；
  ②`filesystem.prepare`/`task_state` 等对目标布局机器的实际必要性逐个核查，能在 v0.5.5 退役的登记清单；
  ③**不强行改编译器结构**（它已退化为常量模板；重构收益低、回归风险高——诚实评估后留给后续版本）。
- v1 设计 6（计划随包）**作废**：常量模板下编译器无偏斜知识，无需随包。

### W6.1 支持矩阵收窄（2026-10-06 用户定案）

实测发现：按原打包参数（`DEFAULT_MIN_VERSION=v0.5.0`）v0.5.4 计划是 **10 步**，含
`compose.project_migrate` / `filesystem.prepare` / `task.migrate_runtime_state` /
`task.sync_runtime_state` / `post_upgrade.schedule_cleanup` / `runner.schedule_target_runtime_handoff`；
只把 min_version 改成 v0.5.2、但 `directory_transition`/`legacy_cleanup` 仍非空时是 9 步。
**"常量计划"成立的前提是 v0.5.4 不再声明目录迁移与 legacy 清理。**

定案（`scripts/build_upgrade_package.py`）：

| 项 | 取值 |
| --- | --- |
| `TARGET_LAYOUT_FLOOR_VERSION` | `v0.5.4` |
| `MINIMUM_SOURCE_VERSION` | `v0.5.2` |
| `_effective_min_version()` | 目标 ≥ v0.5.4 时，来源下限一律抬到 v0.5.2 |
| `_directory_transition()` / `_legacy_cleanup()` | 目标 ≥ v0.5.4 返回 `{}` |
| `source_compatibility.supported_versions` | `[v0.5.2, v0.5.3, v0.5.4]` |
| 旧布局（v0.5.0 / v0.5.1 / v0.5.1u1 / v0.5.1u2） | ⛔ 不支持直升，precheck 拒绝 + 引导「先升 v0.5.3」（remediation 文案见 B3） |
| v0.5.3 及更早的包 | **不受影响**，仍支持 v0.5.0–v0.5.1u2 直升 |

### W6.2 v0.5.4 计划动作集（断言锁的是**集合**，不是步数）

平台包（platform-only 组件）：
`{backup.create, image.load(×3), files.sync, compose.override, compose.apply, health.http}`
bundle 包（带 observability 组件）额外 `health.prometheus`。
带 schema 迁移时额外 `script.run_sandboxed`（SQLite 迁移走沙箱，与 legacy 布局迁移无关）。

两处与本文早先措辞的偏差（以代码为准，已核实）：

1. `health.prometheus` **只在声明 observability 组件时**出现（编译器按组件分支），
   平台-only 包不含它。
2. `post_upgrade.schedule_collection` **不由编译器下发**——49-49 已把升级后自动采集改为
   平台侧调度（`post_upgrade.platform_collection` → `worker.py`），该动作只写标记文件。
   runner 仍实现它，仅为老桥接计划（v0.5.3 及更早的包）兜底。

「七步」是设计里的流程分组（backup → load → sync → swap → health → verify → checkpoint），
一个分组可对应多个动作；测试不锁步数。

### W6.3 退役登记（v0.5.5 候选）

| 动作 | v0.5.4 计划 | 目标布局机器上的必要性核查 | 结论 |
| --- | --- | --- | --- |
| `filesystem.prepare` | 不发射 | 7 个目标目录在 v0.5.2 安装/升级时已建，且载体目录是禁删红线（UPG-050）；其余职责（legacy 路径搬迁、env 迁移）参数已空 | **可退役**，残留风险由 health `checks.directories` 兜底 |
| `task.migrate_runtime_state` | 不发射 | 迁移的是 legacy `upgrades` 目录里的旧任务状态；目标布局机器的任务本就在目标 `upgrades` 下 | **可退役** |
| `task.sync_runtime_state` | 不发射 | 与 legacy cleanup 配对（收尾前同步运行态）；无 cleanup 即无意义 | **可退役** |
| `compose.project_migrate` | 不发射 | 旧 project/network 重命名；目标布局已是 `smartx-hci-capacity-insight` | **可退役**（保留实现供老桥场景） |
| `runner.handoff_target_runtime` / `runner.schedule_target_runtime_handoff` / `runner.stop_legacy_runtime` | 不发射 | 旧布局引导期把 runner 迁进新 project；v0.5.2+ 的 runner 已在目标 project。W3 自换（`component.*`）与之无关，保留 | **可退役**（保留实现） |
| `legacy.cleanup` / `compose.stop_legacy_project` / `network.remove_legacy` / `filesystem.cleanup_*` / `post_cleanup.*` | 不发射 | 只服务旧布局清理 | **可退役**（保留实现） |
| `post_upgrade.schedule_cleanup` | 不发射 | 只在 `create_cleanup_task` + legacy_cleanup 同时成立时下发 | **可退役**（保留实现） |
| `post_upgrade.schedule_collection` | 不发射 | 49-49 起平台侧调度；老包计划仍会下发 | 保留（兼容），不列退役 |

「可退役」= v0.5.5 起可从**默认计划模板**里去掉；**动作实现一律保留**，
因为 v0.5.3 及更早的包编译出的计划仍会下发它们（老桥接场景兜底）。

## W7 两道构建门禁

### 7.1 动作词汇冻结门禁 `scripts/verify_upgrade_plan_vocabulary.py`
- 输入：候选平台包 + 已发布 runner 组件包（Release 资产）。
- 步骤：①manifest `schema_version` 与已发布线一致（变更即 fail——老编译器必须能读）；
  ②用**候选包内编译器**对每个 `source_compatibility` 源版本生成计划 → 动作集 ⊆ 已发布 runner 包 manifest
  动作集；③`git diff <published-tag>..HEAD -- backend/app/v2/upgrade/compiler.py` 非空时输出
  「编译器有变更，需人工核对偏斜矩阵」警告（不 fail，但必须出现在发版检查单）。
- 接入 `ops/package.sh`（身份门禁之后）；输出 PASS/FAIL 供 ledger 引用。

### 7.2 expand-only 迁移门禁
- 扫描 `backend/app/v2/upgrade/migrations/registry.json` 新增条目对应 SQL/代码：
  含 `DROP TABLE|DROP COLUMN|ALTER ... RENAME|MODIFY|DELETE FROM|UPDATE .* SET`（破坏性模式）→ fail，
  除非条目显式标记 `"contract": true` 且关联 contract 计划（默认禁止新增 contract 条目）。

## W8 US-39 守卫投递

- 打包：`build_upgrade_package.py` 把 `delivery/compose-guard.sh` 复制进平台包 project 载荷（根级 `compose-guard.sh`）；
  `files.sync` 自然带进现场 project 目录。
- 标记回填：`files.sync` 动作末尾（runner 侧，有 project 写权）：若 project/.env 无
  `SMARTX_COMPOSE_FILE_ACTIVE` → 从**运行中容器的 `com.docker.compose.project.config_files` label** 取 basename
  写入（逻辑自包含移植自 delivery/compose-guard.sh 的 resolve，不 source 外部脚本）。幂等：已有标记不覆盖。

## 10. 兼容矩阵（每格都要有测试或演练覆盖）

| # | web-api | runner | 场景 | 关键判据 |
| --- | --- | --- | --- | --- |
| M1 | v0.5.2 | v0.3.1 | 升 v0.5.3 | 已发布路径（回归即可） |
| M2 | v0.5.3 | v0.3.1 | 升 v0.5.4（七步+场景 A） | 主路径；runner 容器 ID 不变；healthcheck 失败自动回滚实测 |
| M3 | v0.5.3 | v0.3.1 | 组件升 v0.3.2 | 旧编排最后一次；guard 下安全 |
| M4 | v0.5.3 | v0.3.2 | presence/预检查 | DB 兼容镜像保证 v0.5.3 判定正常 |
| M5 | v0.5.4 | v0.3.1 | presence 文件缺失回落 DB | 行为与今天一致 |
| M6 | v0.5.4 | v0.3.2 | 终态：自换/文件优先/投影 | 全部新特性生效 |
| M7 | v0.5.4 | v0.3.2 | 场景 B/C 手动回滚 | 判定 API + 任务化执行 |

## 11. 测试规格汇总

| # | 层级 | 内容 | 判据 |
| --- | --- | --- | --- |
| T1 | 单元 | 状态文件原子写/损坏自愈/schema 容错/并发 | 永远可解析或触发重建 |
| T2 | 单元 | 投影幂等、file-newer 判定、镜像失败无害 | 无异常冒泡 |
| T3 | `.14` | diff 收敛 | 未变更服务容器 ID 不变 + 差异日志 |
| T4 | 单元 | runner 触碰守卫 | upgrade-runner 进列表 → 拒绝 |
| T5 | `.14` | 回滚五项（A×3 失败点 + B + C） | 各场景判据（v2 设计 §5） |
| T6 | 构建 | expand-only 门禁 | 破坏性迁移即 fail |
| T7 | 构建 | 词汇冻结门禁 | 缺动作即 fail；r17 包回归 PASS |
| T8 | `.12`/`.14` | 兼容矩阵 M1–M7 | 逐格通过 |
| T9 | 预览 | 场景 B 前端入口 + 场景 A 失败展示 | 预检查/任务中心文案正确 |
| T10 | `.3` | 全量回归 | 后端 unittest + tsc + vitest 回基线 |
| T11 | `.14` | 组件自换 | 中断 ≤30s、presence ≤60s、零编排 |
| T12 | `.14` | 七步流程断言 | 计划无迁移/交接/legacy 动作 |

## 11.1 r18 交付目录口径（2026-10-06 澄清）

r18 以 `--skip-offline` 构建（仅平台包 + runner 组件包）——**不阻塞批次 C**：
- C1 的「全新安装」步骤用的是 **v0.5.3 的离线交付目录**（`.3:/data/us37-verify/packages/latest/offline-delivery/`，
  先装 v0.5.3 再直升 v0.5.4），不需要 v0.5.4 交付目录；
- GitHub Release 资产按 v0.5.3 先例 = 平台包 + runner 组件包 + `.sha256`，不含交付目录；
- 若将来需要 v0.5.4 交付目录（全新装 v0.5.4 的客户）：用**已门禁的 r18 包**跑
  `build_offline_delivery.py`（OPS_RUNNER_BASELINE_TAG=**v0.3.2**——本火车首次随平台交付 runner，
  交付物 compose 基线 = 本次发布的 runner），不得重跑 package.sh（docker build 不可复现，会换包 SHA）。

## 12. 实施顺序与依赖

```text
W1 状态文件 ──→ W2 单写者 ──→ W3 自换（依赖 W1 的 presence）──→ 批次 C 验收
     │                        ├──→ W4 diff 收敛（独立，可并行）
     │                        └──→ W5 场景 A（依赖锚点=W3 引入的锚点机制）
W7 门禁（独立，先做——保护后续每一步）
W8 US-39（独立，随 files.sync 顺带）
W6 七步断言（批次 B，依赖 W4/W5 落地后验证）
W5 场景 B/C（批次 B 平台侧）
```

提交纪律：单工作项单提交；每个工作项提交信息注明对应 W 编号与测试结果。

## 13. 文档同步清单（实施完成时）

- AGENTS §6：已按自换修订（2026-10-05 完成，见 git 历史）——实施后核对表述与实现一致；
- `docs/upgrade-strategy-issues.md`：US-26/28/17/39 置 🟢（附证据链接）；
- `docs/upgrade-chain.md`：偏斜矩阵落表；
- `docs/version-governance.md`：v0.3.2 交付条目更新（含自换协议冻结声明）；
- `docs/releases/CHANGELOG.md`：v0.5.4 节立项（候选）；
- pending-tasks：#62/#53/#83 关闭或状态推进。

## 14. 补充约束与观察哨（2026-10-05 评审补充）

### 14.1 实施陷阱（代码层）
1. **场景 C 前先核实沙箱能力**：`script.run_sandboxed`（sandbox.py）能否执行 docker stop/cp/恢复——先写探针测试
   再定实现；若沙箱不允许，备选方案需重新评审（专用动作 = 词汇变更，或降级为手册产品化）。
   **【2026-10-06 决议】post_upgrade 触发面的覆盖等级**：单测覆盖即为充分，不强制沙箱复现。理由：
   ①`post_upgrade.*` 失败触发的回滚与已沙箱实测的 compose.apply 触发回滚**走同一条回滚代码路径**
   （锚点驱动应用回滚），差异只在触发判定函数（已被单测覆盖）；②post_upgrade 动作是薄调度器，
   自然失败无法在不注入故障的前提下复现，注入=单测已在做的事。批次 C 若在真机遇到自然发生的
   post_upgrade 失败，顺带取证即可，不主动构造。
2. **自换的"最后一步"语义**：`schedule_target_runtime_handoff` 之后的代码不会执行——一切收尾必须放新 runner
   启动路径（`_finish_runner_component_steps` 已具备），handoff 调用后不得再写任何状态。
3. **自换窗口的状态文件竞争**：新旧 runner 短暂并存，os.replace 原子、last-writer-wins——presence 判定必须
   容忍 `instance_id` 变化与心跳跳变。
4. **场景 A 防抖**：自动回滚触发前，健康检查步内先重试（与现有 health.http 重试参数对齐），防瞬态故障
   造成"失败中断 + 回滚中断"双倍服务打断；回滚同样记录完整证据。
5. **expand-only 门禁误报**：SQL 启发式扫描有假阳性（注释含 DROP 等）——必须带 allowlist + 人工复核出口，
   否则门禁会被习惯性绕过（门禁被绕 = 等于没有）。
6. **.env 回填**：0600 root 属主、已有标记不覆盖、与 install 的 .env 再生成不打架；回填失败不阻塞升级（记 warning）。
7. **时间基准**：状态文件/锚点全部 UTC ISO；解析统一 `parse_heartbeat`，不新写时区逻辑。

### 14.2 机器与验证纪律
8. **证据等级**：`.3`=代码行为、`.12`/`.14`=部署验收——批次 C 矩阵按格在对应机器跑，"在 .3 试过"不算数。
9. **`.14` 先恢复基线**（v0.5.3 + runner v0.3.1）再跑矩阵；当前它是 v0.3.2 验证态。
10. **每批合入后重打包**（AGENTS §12）；r18 起包 SHA 入 ledger；开发期多个 v0.3.2 中间构建在 ledger 记录
    SHA 与用途，不得让测试机之间流传"同名不同内容"的 v0.3.2。
    **【2026-10-06 升级为硬规则（r18/r19 连续作废的教训）】打包点必须与代码HEAD对齐并逐镜像核验：**
    ①打包前核对 `git log <打包点>..HEAD -- backend/app` 是否为空——非空 = 包里缺提交，作废重打；
    ②打包后**逐镜像**核验关键修复在产物内（本轮方法：解镜像层 grep 修复符号，r18/r19 均用此法抓出）；
    ③ledger 登记时同步记录「打包点 commit」与「HEAD commit」，两者不一致必须写明差异清单。
    「已修复」不等于「已生效」——r18 缺 A5 修复、r19 含回滚端点 500，连续两次同因。
11. **compose 测试纪律**：`.3`/`.12` 上测试用独立 project 名或先完整 down/up（US-37 教训）。
12. **传输垃圾**：`._*`/`.DS_Store` 进包即炸门禁（构建脚本已过滤，手工打包与测试目录注意清理）。

### 14.3 排期与范围
13. **批次 A 期间不要在 `.3` 的 r17 实例上注入新代码验证**（注入随重建丢失且污染验收）——验证一律走
    `.14` 新装/升级或 `.12` 产品流程；`.3` 只跑测试套件与打包。
14. **场景 B/C 是新用户能力**：UI 过 frontend-style-guide（`:root` 变量、6/8px 圆角）；文案必须让客户
    一眼区分「保数据回滚」与「整备回滚（丢数据，提示丢失窗口）」。

### 14.4 文档与治理
15. AGENTS §6 已按自换修订——实施完成后核对实现与规则一致；**冲突时改设计并重新征求用户同意，不许悄悄偏离**。
16. §13 文档同步清单收尾时逐项核销。
17. 实施入口 = 本文 + AGENTS.md + docs/project-guide-for-ai.md 三份，不要从对话记录考古。

### 14.5 观察哨（v0.5.4 发布后第一周盯）
18. 自换成功率、组件升级停机时长分布、状态文件损坏事件数、DB 镜像写失败日志条数——v2 新机制的首次真实暴露面；
    任何一项异常先停后续推广、回读本文对应设计。
