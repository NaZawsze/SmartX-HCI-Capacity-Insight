# 计划：v0.5.3 完整升级链路与 A/B 验收（严格照此执行）

状态：**测试执行计划**（2026-09-27 用户指令：「要全部测试完」「把升级链路写在文档里并且严格按照文档测试」）。
执行人按本文件逐条执行，每阶段完成即在文末「执行结果记录」打勾并写证据（task id / SHA / 命令输出摘要），全部绿之前**不得**执行任何 git 推送/tag/发布动作。

---

## 0. 固定升级链路（本测试的骨架）

~~~text
v0.5.1 + runner v0.3.0
  -> v0.5.1u2            (桥接包，runner 仍 v0.3.0)
  -> runner v0.3.1       (组件升级，用**已发布** Release 资产 d10e15cf…)
  -> v0.5.2              (目标布局：project/network/单根目录/legacy cleanup)
  -> v0.5.3              (本轮候选包：含 49-49 + 49-50；由**已发布** runner v0.3.1 执行)
  -> runner v0.3.2       (可选：平台升级完成**之后**的组件升级)
~~~
> 顺序口径以本文件 §「第四轮执行顺序（2026-09-27 最终口径：**先平台、后 runner**）」为准；下方 B-b 段落已作废。

**⚠️ 以下 B-b 口径已作废（保留为过程记录；执行请以本文件 §「第四轮执行顺序」为准，那里平台包 runner 基线已回退为已发布 `v0.3.1`、「已发布 v0.3.1 直升」重新成立）**：用户 2026-09-27 曾选定 **B-b（先升 runner 再升平台）**，
「方案 A 让已发布 runner v0.3.1 直升 v0.5.3」**不再成立**——平台包 manifest 声明 runner 镜像 `v0.3.2`，
而平台包不打包 runner 镜像，预检查的 `images` 检查（`docker image inspect`）会先拦住没有 v0.3.2 镜像的现场。
因此：

- **A 的验收目标改为**：①升级计划里**不含** `post_upgrade.schedule_collection`；②升级成功后**平台侧**自建标记并创建升级后自动采集任务（runner 只负责其余 12+7 个动作）。
- **B 的验收目标**：①旧 runner（无 v0.3.2 镜像）→ 预检查**失败**且提示「先做组件升级到 v0.3.2」；②组件升级 v0.3.2 后 → 预检查**全绿** → 升级成功。
- `docs/superpowers/specs/2026-09-27-v053-platform-side-post-upgrade-collection-design.md` 的 A5 条已按此修正。

---

## 1. 固定输入（每项都要记录 SHA 并核对）

| 用途 | 包 | SHA256（前16位） | 来源 |
| --- | --- | --- | --- |
| 基线包 | `smartx-capacity-insight-upgrade-v0.5.1.tar.gz` | `ef24643b…` | .3/.12 `/data/upgrade-packages/` |
| 桥接包 | `smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `d5f27716…` | `.12:/root/chain-verify-20260722/packages/` |
| runner v0.3.1（**已发布**） | `smartx-upgrade-runner-v0.3.1.tar.gz` | `d10e15cf…` | 同上（= Release 资产，25 动作） |
| 目标布局包 | `smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `692aca8b…` | 同上 |
| **本轮 runner v0.3.2** | `smartx-upgrade-runner-v0.3.2.tar.gz` | 执行时填写 | `.3` 构建 |
| **本轮 v0.5.3 候选包** | `smartx-capacity-insight-upgrade-v0.5.3.tar.gz` | 执行时填写 | `.3` 构建 |

业务数据夹具：`.3:/home/user1/codex-build/fixtures/upg048-v051-business-pair-20260717/{.env,smartx.db}`（`b84520c9…`，users=1/towers=1/vm_latest=556/vm_volumes=89588）。

---

## 第四轮执行顺序（2026-09-27 最终口径：**先平台、后 runner**）

> 口径修正：平台包 runner 基线回退为**已发布 v0.3.1**（方案 A 已让升级计划不再依赖新动作），现场无需先做组件升级即可直升；v0.3.2 组件包改为**平台升级完成之后**的可选步骤（那时源端已是 v0.5.3，同 project 停机修复生效）。

1. **阶段 1** 恢复 v0.5.1 + runner v0.3.0 干净基线（数据先固化）
2. **阶段 2** 链路：`u2 → 已发布 runner v0.3.1 → v0.5.2`
3. **阶段 3″** 预检查 → **必须通过**（v0.3.1 镜像现场本来就有；拒绝场景证据保留第一轮 task `upgrade-79a20c17b11f33b0`）
4. **阶段 4′** 平台升级 v0.5.3（**执行者 = 已发布 v0.3.1**）→ A 断言 + 8 项验收（此时 `runner_version=v0.3.1`）
5. **阶段 6** 平台升级后**组件升级 runner → v0.3.2**（源端已 v0.5.3 → 验证停机修复：runner 必须存活）→ health `runner_version=v0.3.2` + 8 项复验 + 5.7 新预检查闸门
6. **阶段 7** 记账（ledger/CHANGELOG/progress/task_plan/pending）

> 旧编号「阶段 4 组件升级在平台升级之前」作废：B-b 顺序在 v0.5.2 源端不可行（老 web-api 无条件 stop 会杀掉新 runner），根因见 findings.md 2026-09-27。

## 2. 阶段 0：`.3` 打包与包静态门禁（不得跳过）

- [ ] 0.1 `docker compose build upgrade-runner` → 镜像 `…-upgrade-runner:v0.3.2`，容器内核对 `RUNNER_VERSION=v0.3.2`、`grep -c schedule_collection = 2`
- [ ] 0.2 `python3 scripts/build_runner_component_package.py --version v0.3.2 --output-dir /data/upgrade-packages/components-v032-20260927` → 记录 SHA
- [ ] 0.3 `python3 scripts/build_upgrade_package.py --check-version` → 期望 `Version metadata OK: v0.5.3`
- [ ] 0.4 `python3 scripts/build_upgrade_package.py --output-dir /data/upgrade-packages/v053-ab-20260927` → 记录候选包 SHA
- [ ] 0.5 `python3 scripts/verify_upgrade_package_identity.py <候选包> --expected-version v0.5.3` → exit 0；核对 manifest `minimum_runner_version=v0.3.2`、runner 镜像 tag `v0.3.2`、`post_upgrade.auto_collection=false` 且 `platform_collection=true`
- [ ] 0.6 `.sha256` 文件 `sha256sum -c` OK；包内敏感成员扫描 0（无 `.env`/`.db`/`.sqlite`）
- [ ] 0.7 后端全量（容器 `unittest discover`）、宿主机构建测试 26、前端 `tsc -b` + vitest、`verify_api_docs`、`verify_release_docs_safe` → 全绿
- [ ] 0.8 计划内容抽验：候选包内 web-api 镜像编译出的计划**不含** `post_upgrade.schedule_collection`（方法见 4.2）

## 3. 阶段 1：`.12` 恢复 v0.5.1 + runner v0.3.0 干净基线

- [ ] 1.1 数据固化：`python3 scripts/capture_baseline.py capture --name v053-before-ab-20260927 --db /data/smartx-storage-forecast/app/smartx.db --env /data/smartx-storage-forecast/project/.env --output /root/baselines --prometheus /data/smartx-storage-forecast/prometheus` → `verify` 必须 `baseline ok`（产物放 `/root/baselines`，避开 post-cleanup 会清的 `/data/backups`）
- [ ] 1.2 拆两套 project 容器与网络，删除 `/opt/smartx-storage-forecast`、`/data/smartx-storage-forecast`、`/data/smartx-capacity-insight-data`、`/data/{upgrades,backups,exports,compose-runtime}`、`/prometheus-data`（先 `docker compose down` 再删，禁 `down -v`）
- [ ] 1.3 解包 v0.5.1 基线 → `/opt/smartx-storage-forecast`，`docker load` 三镜像，放业务夹具（DB + `.env`，0600），`docker compose -p smartx-storage-forecast up -d web-api collector-worker frontend upgrade-runner prometheus`
- [ ] 1.4 基线验收：health `{"ok":true,"version":"v0.5.1","runner_version":"v0.3.0",checks 全 true}`；network `smartx-storage-forecast_smartx-net` subnet `10.249.249.0/24`；DB counts 与夹具一致、integrity ok

## 4. 阶段 2：链路前三步（到 v0.5.2 + 已发布 runner）

- [ ] 2.1 跑 `scripts/verify_full_upgrade_chain.py --base-url http://127.0.0.1:8000 --pkg-u2 <d5f277> --pkg-runner <d10e15cf> --pkg-v052 <692aca8b>` → 三步 `succeeded`、节点 1/2/3 验收通过、post-cleanup `succeeded`
  - 备注：脚本 `verify_node3` 对 prometheus 用布尔判定（已在 `9dfddd3` 之前修复）；自动采集若因 Tower 不可达 failed → 记为**已知环境限制**，不算失败
- [ ] 2.2 链路终态：health `v0.5.2 / runner v0.3.1`；5 容器；network `smartx-hci-capacity-insight-net` subnet `10.249.251.0/24`；SQLite counts 与夹具一致；7 个 legacy 路径 missing；`.env` 0600
- [ ] 2.3 确认本地**没有** v0.3.2 镜像（`docker image inspect …:v0.3.2` 应失败）——这是 5.1 的前置条件

## 5. 阶段 3：B-b 拒绝场景（旧 runner + 无 v0.3.2 镜像）

- [ ] 3.1 上传本轮 v0.5.3 候选包 → `POST /api/admin/upgrade/upload` → 记 task id
- [ ] 3.2 `POST /api/admin/upgrade/precheck/<tid>` → **必须 `precheck_failed`**
**（2026-09-27 执行中修正：预检查代码跑在「源端」web-api 上。此刻源端是 v0.5.2，其镜像内没有 49-50 新增的 `runner_actions` 检查与组件升级提示文案，因此本阶段只对源端实际具备的检查断言；新增闸门改到 5.7 与单测验证。）**

- [x] 3.3 断言：checks 里 `images` 检查 `ok=false`，message 含 `本地 Docker 镜像不存在` **与 `v0.3.2`**（v0.5.2 源端既有闸门，已生效）
- [ ] 3.3b 断言（**改到 5.7**）：`images` 消息含 `组件升级` 提示 —— 该文案在 v0.5.3 源端；单测在 `.3` 覆盖
- [ ] 3.4 断言（**改到 5.7**）：checks 里存在 `runner_actions` 且 `ok=true`，message 含 `全部支持`
- [x] 3.5 断言：checks 里 `runner_protocol` `ok=true`（心跳 v0.3.1 能力满足）

## 6. 阶段 4：组件升级 runner → v0.3.2

- [ ] 4.1 上传 `smartx-upgrade-runner-v0.3.2.tar.gz` → `POST /api/admin/component-upgrade/upload` → precheck → start → 轮询 `succeeded`（记录 task id）
- [ ] 4.2 组件版本接口 `GET /api/admin/component-upgrade/version` → `version=v0.3.2`；health `runner_version=v0.3.2`
- [ ] 4.3 `docker image inspect …-upgrade-runner:v0.3.2` 存在；容器镜像 tag = `v0.3.2`

## 7. 阶段 5：v0.5.3 升级（A 运行时验收）+ 8 项验收

- [ ] 5.1 重跑候选包 precheck → **必须通过**（源端仍是 v0.5.2，检查项为 `images`/`runner_protocol`/`source_compatibility`/`checksums`/`project_files`/`manifest`/`paths` 全 `ok=true`）
- [ ] 5.2 `POST /api/admin/upgrade/start/<tid>` → 轮询主任务 `succeeded`（记录 task id、耗时）
- [ ] 5.3 **A 断言一**：升级任务 `task.json` 的 `actions` 列表**不含** `post_upgrade.schedule_collection`，**含** `post_upgrade.schedule_cleanup`
- [ ] 5.4 **A 断言二**：`post-cleanup-<tid>` 任务 `success`；`upgrades/<tid>/post-upgrade-collection.json` 存在且 `source=target_worker_compatibility`（**平台自建标记**，runner 没写）；`post-upgrade-collection-<tid>` 任务已创建（Tower 不可达 → `failed` 记为环境限制，不影响判定）
- [ ] 5.5 8 项验收：
  - health `{"ok":true,"version":"v0.5.3","runner_version":"v0.3.2",checks 全 true}`（连测 2 次）
  - 5 容器镜像 tag：三件套 `v0.5.3`、runner `v0.3.2`、prometheus `v2.55.1`
  - project/network `smartx-hci-capacity-insight(-net)` subnet `10.249.251.0/24`
  - SQLite 位于目标 app 目录、`integrity ok`、行数与夹具一致（users1/towers1/vm_latest556/vm_volumes89588）
  - Prometheus 挂目标目录、`/-/ready` 200
  - `.env` 目标 project 下 0600、sha 与夹具一致
  - 7 个 legacy 路径全部 missing；目标 7 目录齐全；`upgrades/` 保留四个升级任务目录
  - UI `HTTP 8080 = 200`
- [ ] 5.6 前端产物含本轮特征（`rgba(22, 119, 255, 0.12)`、`已分配容量`）
- [ ] 5.7 **源端已变成 v0.5.3** → 用同一候选包再跑一次 precheck，断言：
  - checks 里**存在** `runner_actions` 且 `ok=true`，message 含 `全部支持`（新闸门在 v0.5.3 源端生效）
  - checks 里 `images` `ok=true`（v0.3.2 镜像已在阶段 4 就位）
  - 该次 precheck 结果不影响已完成的升级（仅取证用）

## 8. 阶段 6：记账与（仅在全部通过后）推送申请

- [ ] 6.1 `docs/upgrade-package-ledger.md`：v0.5.3 新候选包行 + runner v0.3.2 组件包行（SHA、任务 id、验收结论）
- [ ] 6.2 `docs/releases/CHANGELOG.md` 验证说明补本轮数据；`progress.md` 写完整过程；`task_plan` 49/49-49、49/50 勾选；`pending-tasks` #45/#46 更新
- [ ] 6.3 `git diff --check` + 提交
- [ ] 6.4 **以上全绿后**，再向用户申请推 `runner-v0.3.2` tag（AGENTS §4：建 tag/推送必须用户明确要求）

## 9. 失败处理（AGENTS §10）

任一步失败：停止继续打包/升级 → 记录 task id、失败步骤、原始错误、容器/目录/DB 状态与包 SHA → 先报告用户 → 修复后**从干净基线重来**，不在半升级现场补跑。

---

## 本轮发现的问题（细分清单见 [upgrade-strategy-issues.md](../../upgrade-strategy-issues.md)）

架构定性：**控制面-执行面分离 + 声明式计划驱动 + Expand–Contract 两阶段**升级编排（web-api 编排、runner 代理执行、先切换后清理）。**骨架合理、问题在契约与实现层**，共 23 条细分问题：

| 优先级 | 条目 | 状态 |
| --- | --- | --- |
| 立即 | **US-05** post-cleanup 健康断言"版本相等"→ 升级顺序敏感（先升 runner 再升平台会清理失败） | 🟠 已实施（49-52，`8115c41`）；`.12` 顺序验收待授权 |
| #47 整改 | US-01 源端执行（新校验对当次升级无效，架构事实只能靠流程压）／US-02 版本号隐式契约（需硬门禁脚本）／US-03 runner 生命周期三入口未收敛／US-06 采集链路 5 秒轮询 | 🔴/🟡 未实施 |
| 已绕开 | US-04 老 web-api 无条件 stop（靠「先平台后 runner」） | 🟠 |
| 已修复 | US-10 bind-mount 自删、US-11 平台侧停新 runner、US-12 计划多余动作、US-13 DockerHub 无 v0.3.1、US-14 资产不同源、US-15 发布日期错误、US-16 验收用开发镜像 | 🟢 |
| 验收矩阵缺口 | US-17 回滚／US-18 顺序矩阵／US-19 中断恢复／US-20 Tower 可达采集／US-21 拒绝分支／US-22 exit137 取证 | ⚪ |
| #47 整改 | **US-23 并发升级无单飞守卫**（两次 start 都放行，第二个任务在被改过的环境上执行旧计划） | 🟠 已实施（49-52，`8115c41`/`32f9a95`）；`.12` 重复 start 格待授权 |
| 择机 | US-07 升级前磁盘空间未校验、US-08 长任务心跳 stale 边界、US-09 预检失败任务噪音 | 🟡/⚪ |

> 第四轮验收结论只覆盖「先平台、后 runner」这一条顺序（阶段 4′ + 阶段 6）。US-05/US-23 已在 49-52 修复并有 `.3` 单测，但**「先 runner 后平台」这条顺序与「重复 start」两格尚未在 `.12` 实测**（MVP 待授权）；**跑完这两格前不得宣称升级策略整体无问题**。

## 执行结果记录（每完成一项打勾并附证据）

| 阶段 | 结果 | 证据（task id / SHA / 输出摘要） | 时间 |
| --- | --- | --- | --- |
| 0 打包+门禁 | ✅ 第四轮 | 平台包 `e1c0fde814f192fa702469fc870b19590dcae5ed39375c116bc64a8690bab009`；runner 组件包 `3d99599cd0e8fceb…`；`--check-version`/identity/`.sha256`/敏感 0；后端 377 tests OK、构建 26 OK | 2026-09-27 |
| 1 基线恢复 | ✅ | `/root/baselines/v053-r4-baseline-20260927`（verify ok）；health v0.5.1/runner v0.3.0 全绿；subnet 10.249.249.0/24；DB 1/1/556/89588 | 2026-09-27 |
| 2 链路到 v0.5.2 | ✅ | `upgrade-1ea87b5c5c188109`(u2) → `upgrade-2cf232b7cd096409`(runner 已发布 d10e15cf) → `upgrade-5cae8764ee3226bb`(v0.5.2)；节点1/2/3 + post-cleanup succeeded | 2026-09-27 |
| 3 旧 runner 被拒 | ✅（拒绝场景第一轮取证）+ 第四轮 3″ 预检查通过 | 拒绝：`upgrade-79a20c17b11f33b0` precheck=failed（`images`：本地 Docker 镜像不存在 …v0.3.2）；通过：`upgrade-666284beec04cc87` prechecked 7 项全 ok | 2026-09-27 |
| 4 组件升级 v0.3.2 | ✅（第四轮改为「阶段6」，升级之后做） | `succeeded`；`component-version=v0.3.2`；**runner 连续 90s 存活（修复前 10s 必死）**；health v0.5.3/v0.3.2 三 checks 全 true | 2026-09-27 |
| 5 v0.5.3 升级+8项 | ✅（发布版 v0.3.1 直升） | 主任务 `upgrade-666284beec04cc87` **succeeded**；计划 12 动作无 schedule_collection；post-cleanup **succeeded**；标记 `source=target_worker_compatibility`；采集任务已创建（Tower 不可达=环境限制）；8 项验收 runner=v0.3.1 全过，复验 runner=v0.3.2 全过；新闸门 `runner_actions 14 动作全部支持` | 2026-09-27 |
| 6 记账 | ✅ | ledger/CHANGELOG/AGENTS/task_plan/pending/findings/progress 已更新；提交 `9ed5d49` 等 | 2026-09-27 |
