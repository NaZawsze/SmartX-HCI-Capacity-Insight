# AI 交接文档 · 2026-10-08（Phase 69 + 版本画像 + 两个缺陷修复；候选 r34 已构建未发布）

> **这份文档回答三个问题**：这一轮做完了什么、没做完什么、下一位接手者第一步该做什么。
> 通用执行纪律见 [ai-handoff-guide.md](ai-handoff-guide.md)；工作标准见 AGENTS.md（每次开工必读）。
> 本文只写本轮增量与当前状态，全部结论都有实测证据，证据位置写在各项后面。

- 更新时间：2026-10-08 00:55（CST）；**状态回填：2026-10-08 晚（接手会话已做完 §4 全部待办，见各节 ✅ 注记）**
- 分支：`dev2`（**未推送**，推送需用户明确要求）
- 最后提交：`2bfb003`（US-40 修复；`c2376ea` 为接手会话检查点空提交，本回填为文档提交）
- 环境：`.3` = 10.20.11.3（开发/主测试机，登录方式见 AGENTS §5）；生产塔 10.20.11.7 **不可达**（见 §3.4）

---

## 1. 三分钟速览

| 维度 | 状态 |
| --- | --- |
| 已发布平台版本 | **v0.5.3**（2026-10-05） |
| 仓库开发线 | **v0.5.4**（`VERSION` = v0.5.4；候选已重切） |
| **当前候选对** | **平台 r34 `1601c66a…` + runner r35 `3518402b…`**（r34 取代 r30；runner 侧 r35 取代 r33——含 US-40 修复，r33 勿用） |
| 平台包位置 | `.3:/data/r34-out/smartx-capacity-insight-upgrade-v0.5.4.tar.gz`（SHA256 `1601c66afb7321701145907b9f643d5b29b630fbc74a9e0055b8ff74e07bb998`） |
| `.3` 运行实例 | **平台 v0.5.4 + runner v0.3.2**（2026-10-08 完成：组件升级 `upgrade-926c2f7a3fccf0c1` + 平台升级 `upgrade-36bbb3312806abdd` 均 succeeded，8 项验收全过） |
| 发布状态 | **未发布**，等用户明确指令；r30 的既有验收**不覆盖 r34**，发布前须重走链路 |
| 测试基线（.3） | 后端 **1148 tests / 1 failure（既有环境限制，见 §6）/ 7 skipped**；前端 **124 passed + tsc 0**；`verify_api_docs` OK；矩阵门禁 2 项 OK |
| 本轮主线 | Phase 69 所有者/虚拟机组落地 + Tower 版本可见与「按版本选 API」（#84）+ 用户报的 4 个 UI 问题 + 两个真机缺陷（已分配=0 / 缓存竞态） |

---

## 2. 本轮完成（4 个提交 + 接手会话 1 个修复提交，可直接接手）

| 提交 | 内容 |
| --- | --- |
| `e10d4a3` | **后端**：①#84 版本画像（`cloudtower/profiles.py`，4.4.0 下限四档 floor；客户端按画像选容量来源，`capacity_source` 随 payload）②已分配策略串修复 + Tower 版本读取/落库/入 API ③摘要缓存×Prometheus 抓取竞态修复（`SUMMARY_CACHE_SETTLE_SECONDS=120`）④Phase 69 后端（owner/folder 采集→库→API→报表两列）；4 条 expand-only 迁移（`vm_latest.owner/folder_name`、`towers.tower_version`、`clusters.os_version`，**version=v0.5.4**） |
| `bd7b679` | **前端**：VM 页所有者/虚拟机组、卷负值哨兵显示 `-`、Tower 状态行「⚠ N 天」（按上一次**成功**采集 + UTC 解析）、趋势图小窗口溢出、切换集群不再跳回概览、设置页版本两行（`Tower: v4.5.0` / `SmartXOS: 6.1.1`） |
| `ed90c85` | **文档**：新增 `docs/cloudtower-api-version-matrix.md`（长期维护件）+ `test_cloudtower_api_version_matrix.py` 一致性门禁；findings 三条新结论；CHANGELOG v0.5.4 补录；task_plan Phase 70、pending #84/#85 闭环、doc-map 登记、progress 本轮记录 |
| `5225589` | **候选 r34 登记**：ledger r34 条目（门禁证据）+ CHANGELOG 状态块更新为 平台 r34 + runner r33，并显式标注 r30 验收不覆盖 r34 |
| `2bfb003` | **US-40 修复（接手会话，2026-10-08）**：`.3` 升级 r34 首跑在 `run-migration` 失败——迁移沙箱的**脚本自身挂载**用容器内路径（`-v` 左半边由宿主 dockerd 解析，源不存在时静默自建空目录树）→ 目标布局下任何带迁移的包必然失败。修复=脚本挂载改走 `docker_host_path()`（一行）+ 回归测试重构为真实布局形态并断言脚本挂载宿主路径；v0.3.2 开发线，按 #82 先例不 bump 版本号。四件套登记（issues US-40 / findings / task_plan Phase 71 / pending #86）随本提交 |

**构建与门禁（全在 `.3`，全部 EXIT=0）**：`git archive HEAD` → `/data/r34-src` →
`TMPDIR=/data/build-tmp python3 scripts/build_upgrade_package.py --output-dir /data/r34-out`；
`--check-version` OK；`verify_upgrade_package_identity.py --expected-version v0.5.4` PASS
（镜像内 runner 基线 = **已发布 v0.3.1**）；`verify_migrations_expand_only.py` OK（4 条加列）；
敏感文件扫描 0 命中（168 成员）。包内 `source_compatibility` = v0.5.2/v0.5.3/v0.5.4。

---

## 3. 本轮关键结论（下一位别重犯）

### 3.1 「已分配」恒为 0 的根因（已修）
新版塔（SMTX OS 6.1.1 / CloudTower v4.5.0）的 `get-vm-volumes` **只返回策略串**
`elf_storage_policy: "REPLICA_2_THIN_PROVISION"`，没有 `elf_storage_policy_replica_num` 等扁平字段
→ 「已分配 = Σ 卷容量 × 副本数」恒乘 0。修法：扁平字段缺失时按策略串推导
（枚举与官方规范逐项核对）。**证据**：findings.md 2026-10-07 两条 + 真机 320.00 GiB · 32.65%。

### 3.2 摘要缓存 × Prometheus 抓取竞态（已修）
摘要缓存按 DB 版本指纹失效，但指标读 Prometheus（**60s 抓取**）：采集完成后、抓取落地前算出的
payload 会把旧值缓存**最长 30 分钟**（实测：修复后的值仍显示 0，重启才恢复）。修法：采集完成后
**120s 结算窗口内跳过缓存读写**。**教训**：缓存失效条件必须覆盖所有上游数据源。

### 3.3 按 Tower 版本选 API（#84，已实施）
- 版本取法：平台版本 `GET /v2/api/get-version`（**纯文本**，POST 同路径 405）；
  节点版本 `get-clusters[].version`。两者层级不同，勿混用。
- 差异断点（官方 4.4.0+ 规范矩阵）：**4.5.0** 起才有 `get-cluster-storage-info`（4.4.x 无 →
  改读集群记录容量）；**4.7.0** 起才有卷扁平策略字段；**4.6.0** 起才有 `used_size`。
- 运行时规则：版本可解析 → 对应画像；**版本未知 → 最新画像 + 能力探测兜底**；
  画像说端点可用时失败**必须上报**（不静默换源）。
- **文档是夹具**：`docs/cloudtower-api-version-matrix.md` 的矩阵块与 `profiles.py` 由单测强制一致——
  改一处必须同步另一处，否则测试 FAILED（已实测门禁有效）。**改这份文档等同改代码，要跑全量。**

### 3.4 环境事实
- 生产塔 **CHINATOWER `10.20.11.7:4433` 自 2026-10-04 19:32 UTC 起不可达**（宿主机与容器均
  `No route to host`）；页面「⚠ N 天」属实，不是显示 bug。
- 测试塔 `10.20.11.101`（只读账号）可达：**CloudTower v4.5.0 / SMTX OS 6.1.1**，
  4 台 VM + 4 卷（各 40 GiB，REPLICA_2_THIN_PROVISION）。
- **预测**：返回扁平副本字段的生产塔平台版本应 **≥ 4.7.0**（塔可达后用 `get-version` 验证）。

---

## 4. ⏳ 未完成（下一位的活，按优先级）

### P0-1 `.3` 平台升级到 r34（或显式放弃该任务） ✅ 已完成（2026-10-08，升级）

> **✅ 完成注记**：首跑（task `upgrade-93e46d573190529f`）precheck 9 项全过后在
> **`run-migration` 失败**——发现 **US-40**（迁移沙箱脚本挂载用容器内路径、宿主被 docker
> 自建空目录；docs/upgrade-strategy-issues.md US-40）。修复（`2bfb003`）后：`.3` 重建
> runner v0.3.2 组件包 **r35**（SHA `3518402b…`，一致性门禁 15 PASS/1 SKIP）→ 组件升级
> `upgrade-926c2f7a3fccf0c1` succeeded → 平台升级二跑 `upgrade-36bbb3312806abdd`
> **succeeded 且 `run-migration` succeeded**（该代码路径首次真机执行）→ 8 项验收全过
> （health v0.5.4/v0.3.2、`schema_migrations` 4 条落库、数据 201/2/2/1 不变、`.env` sha
> 逐位不变、UI 200）→ US-06 升级后自动采集把已分配落库为 320.00 GiB（不再被覆盖回 0）。
> **`.3` 现为 v0.5.4 + runner v0.3.2**。首跑失败任务产物已走产品 API 删除
> （释放 874,938,240 B、记录保留）；宿主遗留的 docker 自建空目录树已清。
> 细节：progress.md 2026-10-08 §B、ledger r35 节。

**为什么做**：`.3` 的平台还是 v0.5.3（旧代码）——它的**定时采集每小时会把已分配重算回 0**
（真机复现过：15:58 scheduled 采集覆盖了 15:54 手动采集的 320 GiB）。升级后 `.3` 自带修复。

**现状（接手时）**：包已上传，任务 `upgrade-93e46d573190529f`（v0.5.3 → v0.5.4），状态 `uploaded`，**未 precheck、未 start**。

```bash
# 在 .3 执行（token 见 §6 重铸方法；/tmp/p69-token 若仍在可直接用）
TOKEN=$(cat /tmp/p69-token)
curl -s -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/admin/upgrade/precheck/upgrade-93e46d573190529f
curl -s -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/admin/upgrade/start/upgrade-93e46d573190529f
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/admin/upgrade/status/upgrade-93e46d573190529f
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/admin/upgrade/post-cleanup/upgrade-93e46d573190529f
```
验收按 `docs/release-acceptance.md`（8 项：health/5 容器/network/SQLite/Prometheus/.env/legacy/UI）。
**若不做**：删除该上传任务（UI 任务中心可删），并知悉 `.3` 的已分配会继续被旧代码覆盖回 0。

### P0-2 恢复 `.3` 测试塔的采集间隔（本轮临时改过） ✅ 已完成（2026-10-08）

> **✅ 完成注记**：`PUT /api/towers/4`（平台 8000）恢复 `collection_interval_minutes` 1440→60，
> 回读确认两塔均 60。

我把 SMTX_TEST（**tower id=4**）的 `collection_interval_minutes` 从 **60 临时改成 1440**（防止核对期间被覆盖）。
**改回 60**（`.3` 上执行；8098 是预览容器，若已清理就把 URL 换成 `http://127.0.0.1:8000`）：

```bash
TOKEN=$(cat /tmp/p69-token)
curl -s -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
 -d '{"name":"SMTX_TEST","base_url":"https://10.20.11.101","username":"OPS","verify_tls":false,"enabled":true,"collection_hour":2,"collection_minute":10,"collection_interval_minutes":60,"collection_mode":"interval","collection_retry_enabled":true,"collection_retry_interval_minutes":15,"collection_retry_max_attempts":3}' \
 http://127.0.0.1:8098/api/towers/4
```

### P1-3 清理 `.3` 预览环境（本轮开发用，属临时设施） ✅ 已完成（2026-10-08）

> **✅ 完成注记**：`p69-api` 已删、vite 进程（2334704/2334716/2334717/2405187）已 kill、
> `vite.p69.config.ts` / `/tmp/p69-*`（含 token）/ `/tmp/full-suite*.log` / `/tmp/r34-build.log` /
> `tmp_probe*.py` 已删。**教训**：清理命令里 `ps|grep` 的 kill 循环把**自己 shell 的命令行**
> （含字面 `vite.p69.config.ts`）匹配进去杀掉（SSH exit 255）——本文档「不要用 pkill -f」的
> 警告在「同一条命令里 ps+grep+kill」时同样成立，剩余删除要另起一条不含 ps/kill 的命令。

```bash
docker rm -f p69-api                        # 预览 API（8098）
ps -eo pid,args | grep "[v]ite.p69"         # 找 PID（注意：不要用 pkill -f "vite.p69"——会匹配到自己的命令行把 SSH 会话杀掉）
kill <上面的 PID>                            # 本轮为 2334704 / 2334716 及其 node 子进程
rm -f /data/c3fix/frontend/vite.p69.config.ts
rm -f /tmp/p69-token /tmp/p69-api.log /tmp/p69-vite.log /tmp/full-suite.log /tmp/full-suite2.log /tmp/r34-build.log
rm -f /data/c3fix/tmp_probe*.py             # 本轮临时探针（仓库内正式探针在 scripts/，勿删）
```
`/data/c3fix`（`.3` 上的仓库工作副本）保持不动——它是标准测试树；需要与提交同步时用
`git archive HEAD | ssh 解包` 覆盖（AGENTS §4）。

### P1-4 发布前必须做（本轮**没有**做）
- **r30 的验收结论不覆盖 r34+r35**：`.12` / `.14` 须按 `docs/release-acceptance.md` 全流程重走
  （候选内容已变；r30+r33 的 C1–C4 格证据不覆盖 Phase 69/版本画像/US-40）。
- 发布动作链（推送 dev2/main、tag、Release、DockerHub）**只在用户明确说「发布」后执行**。
- 三处 runner 同源核对（runner 侧现为 **r35**：`.3` 已跑 `verify_runner_delivery_consistency.py
  --live-probe` 15 PASS/1 SKIP；v0.3.2 的 git tag / DockerHub 镜像 / Release 资产仍按 #53 挂起，
  发布时一并出）。

### P2-5 记录项（文档小债） ✅ 已修（2026-10-08）
`docs/version-governance.md` 开头「下一开发口径 v0.5.4 尚未启动」已过时——接手会话已修正为
当前开发口径 v0.5.4（已发布 v0.5.3 + 候选 v0.5.4 的表述）。

---

## 5. 下一位接手的第一步（建议顺序）

> **（2026-10-08 回填）** §4 的三个 `.3` 待办（P0-1/P0-2/P1-3）与 P2-5 已全部完成，
> `.3` 现为 v0.5.4 + runner v0.3.2、已分配稳定 320 GiB。剩余工作只有 P1-4：
> 等用户明确「发布」后，按最终候选（平台 r34 + runner r35）在 `.12`/`.14` 重走发布验收，
> 再执行发布动作链。

1. 读 AGENTS.md + 本文件 + `docs/pending-tasks.md`（P0 表：#84/#85/#86 均闭环，#86 含 `.3` 验证链）。
2. `git log --oneline -8` 对上 §2 的提交（`5225589` → `c2376ea` 检查点 → `2bfb003` US-40 → 本回填）。
3. 确认 `.3` 状态（health v0.5.4/v0.3.2、已分配 320 GiB、SMTX_TEST 间隔 60）。
4. 按 P1-4 安排发布前重验（等用户指令）。

---

## 6. 验证基线（对不上先看这里）

```bash
# 后端全量（.3 容器内，需 Python 3.12 镜像；只提供解释器与依赖，代码读自挂载的 /data/c3fix。
# 2026-10-08 起预览容器 p69-api 已清理，用平台镜像 v0.5.4（或 .3 上仍在的 v0.5.3 镜像）均可）
docker run --rm --network=none -v /data/c3fix:/w -w /w/backend -e PYTHONPATH=/w/backend \
  --entrypoint python nazawsze/smartx-hci-capacity-insight-web-api:v0.5.4 \
  -m unittest discover -s tests
# 期望：Ran 1148 tests / FAILED (failures=1, skipped=7)
# 唯一失败 = test_v2_upgrade.V2UpgradeServiceTest.test_start_can_submit_task_for_runner_and_runner_executes_it
#   —— 既有环境限制（该用例需要真实 docker socket / runner 执行链），非本轮回归。

# 前端（.3 的 /data/c3fix/frontend，node v22 在 /usr/local/bin）
cd /data/c3fix/frontend && ./node_modules/.bin/vitest run && ./node_modules/.bin/tsc --noEmit
# 期望：124 passed / 12 files；tsc 静默通过

# 契约与门禁（本地或 .3 均可）
python3 scripts/verify_api_docs.py                     # OK: api.md 82 条与后端 81 条一致
python3 scripts/verify_migrations_expand_only.py       # OK（4 条目全部加列）
python3 -m unittest tests.test_cloudtower_api_version_matrix   # 文档↔画像一致性（2 项）

# CloudTower 版本矩阵重生成（只读，带缓存）
python3 scripts/probe_cloudtower_api_versions.py --all --json /tmp/ct-api-matrix.json

# 登录 token 重铸（.3；容器需存在）
# 注（2026-10-08）：p69-api 预览容器已随 P1-3 清理，/tmp/p69-token 已删；
# 重铸改用平台 web-api 容器（`docker ps` 查实际容器名，如 smartx-hci-capacity-insight-web-api-1）：
docker exec -e PYTHONPATH=/app -w /app <web-api 容器名> python -c \
 "from app.v2.config import V2Settings; from app.v2.security import create_token; print(create_token('admin', V2Settings().secret_key, 240))" > /tmp/p69-token
# 平台侧（8000）用同一 secret（.env 相同），该 token 同样可用
```

---

## 7. 相关文档索引（本轮新增/更新）

| 文档 | 说明 |
| --- | --- |
| [cloudtower-api-version-matrix.md](cloudtower-api-version-matrix.md) | **CloudTower 版本对接矩阵（4.4.0+，长期维护件）**；与 `profiles.py` 单测强制一致；新版本发布时按 §5 更新流程维护 |
| [superpowers/specs/2026-10-07-tower-api-version-profiles-design.md](superpowers/specs/2026-10-07-tower-api-version-profiles-design.md) | #84 版本画像设计（运行时规则、未知版本兜底、风险回滚） |
| [superpowers/specs/2026-10-07-vm-owner-visibility-design.md](superpowers/specs/2026-10-07-vm-owner-visibility-design.md) | Phase 69 实现级设计（A1–A5 验收） |
| [upgrade-package-ledger.md](upgrade-package-ledger.md) | 候选 r34 条目 + **r35 runner 组件包条目**（US-40 修复、`.3` 验证链、门禁证据） |
| [releases/CHANGELOG.md](releases/CHANGELOG.md) | v0.5.4 节（本批新增/修复/工程与运维 + 状态块已更新为 **r34/r35** + US-40 修复与 `.3` 验证链登记） |
| `findings.md` | 2026-10-07 四条：Tower 版本取法 / API 差异矩阵 / 摘要缓存竞态 / 策略串-only 卷响应；**2026-10-08 一条：docker `-v` 左半边宿主解析 + 源不存在自建空目录（US-40 根因）** |
| `progress.md` | 2026-10-07 节 A–E（Phase 69 验收、四个 UI 修正、两个缺陷、#84 与矩阵文档）；**2026-10-08 节（接手会话：三个 `.3` 待办 + US-40 发现/修复/验证全记录）** |
| `task_plan.md` | Phase 69（已实施）+ **Phase 70**（版本可见性与 #84）+ **Phase 71**（US-40 修复 + r34 `.3` 升级完成） |
| `docs/pending-tasks.md` | #84/#85/**#86** 已闭环；P0 表首三行是本轮登记 |
| `docs/upgrade-strategy-issues.md` | **US-40 条目**（现象/两层根因/为何没拦住/影响/修复/`.3` 验证证据） |
