# AI 交接文档 · 2026-10-08（Phase 69 + 版本画像 + 两个缺陷修复；候选 r34 已构建未发布）

> **这份文档回答三个问题**：这一轮做完了什么、没做完什么、下一位接手者第一步该做什么。
> 通用执行纪律见 [ai-handoff-guide.md](ai-handoff-guide.md)；工作标准见 AGENTS.md（每次开工必读）。
> 本文只写本轮增量与当前状态，全部结论都有实测证据，证据位置写在各项后面。

- 更新时间：2026-10-08 00:55（CST）
- 分支：`dev2`（**未推送**，推送需用户明确要求）
- 最后提交：`5225589`，**工作树干净**（无未提交改动）
- 环境：`.3` = 10.20.11.3（开发/主测试机，登录方式见 AGENTS §5）；生产塔 10.20.11.7 **不可达**（见 §3.4）

---

## 1. 三分钟速览

| 维度 | 状态 |
| --- | --- |
| 已发布平台版本 | **v0.5.3**（2026-10-05） |
| 仓库开发线 | **v0.5.4**（`VERSION` = v0.5.4；候选已重切） |
| **当前候选对** | **平台 r34 `1601c66a…` + runner r33 `72291ec7…`**（r34 取代 r30；runner 本批未动） |
| 平台包位置 | `.3:/data/r34-out/smartx-capacity-insight-upgrade-v0.5.4.tar.gz`（SHA256 `1601c66afb7321701145907b9f643d5b29b630fbc74a9e0055b8ff74e07bb998`） |
| `.3` 运行实例 | 平台仍 **v0.5.3**；**r34 已上传未启动**（任务 `upgrade-93e46d573190529f`，状态 `uploaded`） |
| 发布状态 | **未发布**，等用户明确指令；r30 的既有验收**不覆盖 r34**，发布前须重走链路 |
| 测试基线（.3） | 后端 **1148 tests / 1 failure（既有环境限制，见 §6）/ 7 skipped**；前端 **124 passed + tsc 0**；`verify_api_docs` OK；矩阵门禁 2 项 OK |
| 本轮主线 | Phase 69 所有者/虚拟机组落地 + Tower 版本可见与「按版本选 API」（#84）+ 用户报的 4 个 UI 问题 + 两个真机缺陷（已分配=0 / 缓存竞态） |

---

## 2. 本轮完成（4 个提交，可直接接手）

| 提交 | 内容 |
| --- | --- |
| `e10d4a3` | **后端**：①#84 版本画像（`cloudtower/profiles.py`，4.4.0 下限四档 floor；客户端按画像选容量来源，`capacity_source` 随 payload）②已分配策略串修复 + Tower 版本读取/落库/入 API ③摘要缓存×Prometheus 抓取竞态修复（`SUMMARY_CACHE_SETTLE_SECONDS=120`）④Phase 69 后端（owner/folder 采集→库→API→报表两列）；4 条 expand-only 迁移（`vm_latest.owner/folder_name`、`towers.tower_version`、`clusters.os_version`，**version=v0.5.4**） |
| `bd7b679` | **前端**：VM 页所有者/虚拟机组、卷负值哨兵显示 `-`、Tower 状态行「⚠ N 天」（按上一次**成功**采集 + UTC 解析）、趋势图小窗口溢出、切换集群不再跳回概览、设置页版本两行（`Tower: v4.5.0` / `SmartXOS: 6.1.1`） |
| `ed90c85` | **文档**：新增 `docs/cloudtower-api-version-matrix.md`（长期维护件）+ `test_cloudtower_api_version_matrix.py` 一致性门禁；findings 三条新结论；CHANGELOG v0.5.4 补录；task_plan Phase 70、pending #84/#85 闭环、doc-map 登记、progress 本轮记录 |
| `5225589` | **候选 r34 登记**：ledger r34 条目（门禁证据）+ CHANGELOG 状态块更新为 平台 r34 + runner r33，并显式标注 r30 验收不覆盖 r34 |

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

### P0-1 `.3` 平台升级到 r34（或显式放弃该任务）
**为什么做**：`.3` 的平台还是 v0.5.3（旧代码）——它的**定时采集每小时会把已分配重算回 0**
（真机复现过：15:58 scheduled 采集覆盖了 15:54 手动采集的 320 GiB）。升级后 `.3` 自带修复。

**现状**：包已上传，任务 `upgrade-93e46d573190529f`（v0.5.3 → v0.5.4），状态 `uploaded`，**未 precheck、未 start**。

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

### P0-2 恢复 `.3` 测试塔的采集间隔（本轮临时改过）
我把 SMTX_TEST（**tower id=4**）的 `collection_interval_minutes` 从 **60 临时改成 1440**（防止核对期间被覆盖）。
**改回 60**（`.3` 上执行；8098 是预览容器，若已清理就把 URL 换成 `http://127.0.0.1:8000`）：

```bash
TOKEN=$(cat /tmp/p69-token)
curl -s -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
 -d '{"name":"SMTX_TEST","base_url":"https://10.20.11.101","username":"OPS","verify_tls":false,"enabled":true,"collection_hour":2,"collection_minute":10,"collection_interval_minutes":60,"collection_mode":"interval","collection_retry_enabled":true,"collection_retry_interval_minutes":15,"collection_retry_max_attempts":3}' \
 http://127.0.0.1:8098/api/towers/4
```

### P1-3 清理 `.3` 预览环境（本轮开发用，属临时设施）
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
- **r30 的验收结论不覆盖 r34**：`.12` / `.14` 须按 `docs/release-acceptance.md` 全流程重走
  （候选内容已变）。
- 发布动作链（推送 dev2/main、tag、Release、DockerHub）**只在用户明确说「发布」后执行**。
- 三处 runner 同源核对（本轮未动 runner，r33/v0.3.2 状态不变）。

### P2-5 记录项（文档小债）
`docs/version-governance.md` 开头仍写「下一开发口径 v0.5.4 尚未启动」——已过时（v0.5.4 是当前开发线），
下一位顺手修正。

---

## 5. 下一位接手的第一步（建议顺序）

1. 读 AGENTS.md + 本文件 + `docs/pending-tasks.md`（P0 表已更新：#84/#85 闭环）。
2. `git log --oneline -6` 对上 §2 的四个提交；`git status` 应为干净。
3. 把 P0-2（恢复采集间隔）先做掉——它是环境状态，越早恢复越好。
4. 决定 P0-1：升级 `.3` 到 r34（推荐，之后 `.3` 的已分配会稳定为 320 GiB）或删除该任务。
5. 做 P1-3 清理预览；然后按 P1-4 安排发布前重验（等用户指令）。

---

## 6. 验证基线（对不上先看这里）

```bash
# 后端全量（.3 容器内，需 Python 3.12 镜像；用预览容器镜像或平台镜像均可）
docker run --rm --network=none -v /data/c3fix:/w -w /w/backend -e PYTHONPATH=/w/backend \
  --entrypoint python nazawsze/smartx-hci-capacity-insight-web-api:v0.5.3 \
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

# 预览用的登录 token 重铸（.3；容器需存在）
docker exec -e PYTHONPATH=/w/backend -w /w/backend p69-api python -c \
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
| [upgrade-package-ledger.md](upgrade-package-ledger.md) | 候选 r34 条目（SHA、构建溯源、门禁证据） |
| [releases/CHANGELOG.md](releases/CHANGELOG.md) | v0.5.4 节（本批新增/修复/工程与运维 + 状态块已更新为 r34/r33） |
| `findings.md` | 2026-10-07 四条：Tower 版本取法 / API 差异矩阵 / 摘要缓存竞态 / 策略串-only 卷响应 |
| `progress.md` | 2026-10-07 节 A–E（Phase 69 验收、四个 UI 修正、两个缺陷、#84 与矩阵文档） |
| `task_plan.md` | Phase 69（已实施）+ **Phase 70**（版本可见性与 #84） |
| `docs/pending-tasks.md` | #84/#85 已闭环；P0 表首两行是本轮登记 |
