# 测试流程与测试范围规范（升级相关）

> 定位：**规定"一次改动要测什么、按什么顺序测、怎么判定、留什么证据"**。
> 与既有文档的分工：
> - [development-verification-process.md](development-verification-process.md)：机器角色、开发/打包/单测的具体命令；
> - [release-acceptance.md](release-acceptance.md)：发布日的验收矩阵与反污染规则；
> - [upgrade-chain.md](upgrade-chain.md)：链路与平台↔runner 配对的**事实口径**；
> - **本文**：把上面三者串成**可执行、可判定、可留证**的测试流程，并定义**每类改动的测试范围**。
>
> 任何"已修复/已通过/可发布"的结论，必须能指向本文某一层的证据；否则不算通过。

## 1. 分层（L0–L6）

| 层 | 名称 | 在哪跑 | 目标 | 典型耗时 |
| --- | --- | --- | --- | --- |
| **L0** | 单元/静态 | `10.20.11.3` | 逻辑正确、契约不漂移 | 2–5 min |
| **L1** | 构建门禁 | `10.20.11.3` | 包身份/一致性/敏感文件 | 5 min（含构建） |
| **L2** | 单机安装与健康 | `10.20.11.14` | 全新安装可用、5 容器/健康/UI | 3–5 min |
| **L3** | 升级链路 | `.14`（首选）/`.12` | 真实升级路径走通 + 数据不变 | 10–30 min |
| **L4** | 反向/缺陷用例 | `.14` | 缺陷态能被识别/自愈，而不是静默失败 | 5–10 min |
| **L5** | 回滚 | `.12` | 失败可回滚、数据可恢复 | 15–20 min |
| **L6** | 发布验收 | `.12` + `.14` | 8 项自检 + 矩阵格回填 | 30–60 min |

**铁律**：`10.20.11.3` **只做 L0/L1**，其部署结果**永远不作为验证证据**（2026-10-15 用户令）。
L2–L6 一律在 `.14`/`.12`，且 `.12` 的宿主**不允许任何手工运维变更**（清理/删容器/改文件），
一切变更只走产品流程。

## 2. 测试范围矩阵（按改动类型决定跑哪些层）

| 改动类型 | L0 | L1 | L2 | L3 | L4 | L5 | L6 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 纯文档 | — | — | — | — | — | — | — |
| 后端逻辑（无升级链路） | ✅ | ✅ | ✅ | — | — | — | — |
| 前端 | ✅（含前端门禁） | ✅ | ✅ | — | — | — | — |
| **升级/执行器（runner）** | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ⚠️ |
| **compose / 安装脚本** | ✅ | ✅ | ✅ | ✅ | ✅ | — | ⚠️ |
| 数据库迁移 | ✅ | ✅（expand-only 门禁） | ✅ | ✅ | — | ✅ | ✅ |
| 发布候选定稿 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

- ✅ 必跑；⚠️ 视改动面（改了回滚路径就必跑 L5；发布前必跑 L6）；— 不适用。
- **改 runner 必须 bump `RUNNER_VERSION`**（AGENTS §6），并在 L1 用"runner 交付一致性"门禁核对
  三处同源（仓库动作表 / 组件包 / 镜像 tag）。

## 3. 各层执行规范

### 3.0 进入条件与受控起点（L2 起，每条链路/用例都适用）

**进入条件（不满足不开跑）**：
1. 候选已过 L1 门禁，且知道自己在测哪个包（平台/runner 包 SHA 记录在案）；
2. **时钟同步**：验证机与构建机时差 < 60s（`date +%s` 对比）。心跳判定、tar 时间戳、
   Prometheus 窗口全部依赖时钟——2026-10-17 实测 `.3` 比本地慢 19s，r40 构建时 tar 已报
   "time stamp is in the future"；偏差大到分钟级会直接把新鲜心跳判成过期；
3. 磁盘可用 ≥ 5G（低于 2G 停止整轮，先按产品流程清理）；
4. T0 基线快照已落盘（`verify_data_integrity.py snapshot`）。

**受控起点（链路测试最容易假通过的地方）**：
- 每条链路（L3-a/b/c）开跑前**必须回到该链路声明的起点**（v0.5.1u2 干净安装 / v0.5.3 干净安装），
  不允许"接着上一条链的终态"开跑——否则测的是 `v0.5.4 → v0.5.4`，不是声明路径；
- 声明的起点必须在日志里留证（`health` 输出 + 起始指纹）。

**退出条件**：同一环境性失败连续 2 次 → 停止整轮，先定性再继续；任一层 FAIL → 不得进入下一层。

### L0 单元/静态（`.3`）

- 后端全量：`python -m unittest`（枚举 `tests/test_*.py`，本项目 `tests/` 无 `__init__.py`，
  `discover` 会报 "not importable"）。
- 前端：`tsc --noEmit` + `vitest run`。
- **判定**：失败数不得超过**基线**（基线写在 `progress.md` 最近一次全量记录里）；
  新增失败必须逐个定性（要么修，要么证明是既有存量并留对照证据）。
- **证据**：命令 + 汇总行（`Ran N tests / failures / errors`）+ 新增/存量失败清单。

### L1 构建门禁（`.3`）

- `scripts/build_release_delivery.sh --output-root <dir> --runner-baseline <已发布版本>`。
- 四道门禁必须全绿：包身份、runner 交付一致性、迁移 expand-only、动作词汇 + 敏感文件 0。
- **判定**：门禁失败即停，不得用 `--skip-*` 绕过。
- **证据**：产物 SHA256（平台包 / runner 包）、门禁输出尾部、构建提交 SHA。

### L2 单机安装与健康（`.14`）

- 全清 → `install/install.sh --yes`。
- **判定（8 项，缺一不可）**：①`health.ok=true` 且 `version/runner_version` 符合预期；
  ②5 容器全 `Up`（`upgrade-runner` 需 `(healthy)`）；③UI 200；④legacy 目录不存在；
  ⑤SQLite `integrity_check=ok` + `foreign_key_check` 为空（用 `verify_data_integrity.py snapshot` 留 T0 基线）；
  ⑥`project/.env` 是**常规文件**且键数 ≥ 15、两枚密钥非空；
  ⑦`docker compose config --quiet` 通过；⑧升级前数据计数为 0 或符合预期。
- **证据**：health JSON、`docker ps` 全量、`.env` 类型与行数、compose config 退出码。

### L3 升级链路（`.14` 首选）

- **必须覆盖"真实客户路径"**，而不是只测"最新版 → 最新版"：
  - 主路径：`v0.5.3 → 组件 <本批 runner> → 平台 <本批候选>`；
  - 老布局：`v0.5.1u2 → v0.5.2 → v0.5.3 → 组件 → 平台`（每一步都要留指纹）。
- **两条驱动路径都要测**：**Web 接口**（upload→precheck→start→poll）与 **CLI**（`upgrade.sh`）。
  两者对 `.env`/健康检查的处理不同，只测一条会漏。
- **判定**：每跳 `succeeded`；每跳后**用 `verify_data_integrity.py` 采样并 `compare` 全 PASS**
  （§4：业务表零变化 + 可增长表旧行不变 + 引用完整性 0 孤儿 + `.env` 密钥未变 + Prometheus 历史不丢）；
  健康 8 项全过；`.env` 在每跳后仍是常规文件。
- **证据**：每跳 task_id + 终态、每跳指纹、日志路径。

> 已知坑（写进规范，避免重复踩）：
> ① 平台升级会重启 runner，预检查可能报"未检测到心跳"——**重试窗口 ≥ 3 分钟**，不要立刻判失败；
> ② 升级成功后的 post-cleanup 会删掉任务目录，`status` 可能 404——**用 health 版本兜底判定**，
> 不要靠轮询 status 无限等待；
> ③ **平台 < v0.5.3 时禁止先做组件升级**（会 SIGKILL 新 runner），必须"先平台到 v0.5.3，再组件"；
> ④ 同版本组件自换（vX→vX）在密集链路里会留 handoff 脏状态——链路中**跳过同版本组件跳**。

### L4 反向/缺陷用例（`.14`）

针对本次修过的每一类缺陷，**必须有一条"人为制造缺陷 → 系统正确识别/自愈"的用例**：

| 缺陷 | 制造方式 | 期望 |
| --- | --- | --- |
| `.env` 被建成目录 | `rm .env && mkdir .env` | 预检查给可执行原因；执行器自动重建为文件（密钥回填）；升级成功 |
| runner 心跳停 | `docker pause <runner>` | `docker ps` 显示 `(unhealthy)`；平台文案能区分"容器在但心跳停" |
| 旧平台组件升级 | 在 v0.5.2 平台上传组件包 | 新平台预检查 `component_platform` 拒绝并提示先升平台 |
| 幽灵 running 行 | （现场遗留） | 超时后自动收敛，不永久阻塞手动采集/清理 |

- **判定**：必须是"**明确失败 + 可执行指引**"或"**自动修复**"，不允许静默继续。
- **证据**：制造前后的 `compose config` 输出、预检查逐项结果、修复后 `.env` 的键数与权限。

### L4.5 并发与干扰（升级期间，L3/L4 必含各一条）

| 用例 | 操作 | 期望 |
| --- | --- | --- |
| **单飞守卫** | 升级 running 时再发起第二个升级/回滚/恢复 | 400 被拒，原升级不受影响 |
| **升级中用户操作** | 升级执行期间：登录、概览、报表接口各一次 | 可读响应或明确错误，**不得 500/挂死**；升级结束后自动恢复 |
| **升级中手动采集** | 升级执行期间提交 `POST /api/collection/run` | 202 + 后台终态（#87 异步化语义不回退） |
| **升级窗口告警口径** | 升级结束后查任务中心 | 「数据新鲜度」类告警属**预期内**（升级窗口必然缺采）；除它之外的告警必须逐条定性 |

**判定**：升级期间的干扰不得改变升级终态，也不得破坏数据（T1/Tf 照常 `compare`）。

### L5 回滚（`.12`）

- 场景 B（apply 阶段失败）与场景 C（post_upgrade 失败）各一次；数据计数与内容逐位恢复。
- **判定**：`rolled_back` + **回滚后采样（Tr）与 T0 `compare` 全 PASS** + 服务健康；
  备份包可解包且含 `app/smartx.db`。
- **证据**：任务终态、回滚步骤日志、前后指纹。

### L6 发布验收（`.12` + `.14`）

- 按 [release-acceptance.md](release-acceptance.md) 的 8 项自检与矩阵格逐格回填。
- **判定**：矩阵无空格、无"沿用旧结论"（重建候选即作废旧结论）。
- **证据**：矩阵表 + 每格指向的日志/SHA。

## 4. 数据完整性检验（所有层统一）

> 只比 4 张表的行数**不够**：一次升级会同时动 SQLite 业务数据、加密凭据、Prometheus 时序、
> `.env`/compose/备份等文件资产。本节按「**资产清单 → 检验方法 → 采样时点 → 允许差异白名单 →
> 判定**」定义口径，配套脚本 `scripts/verify_data_integrity.py`（`snapshot` / `compare`）。

### 4.1 数据资产清单与责任层

| # | 资产 | 位置 | 升级时的正常变化 | 必检层 |
| --- | --- | --- | --- | --- |
| 1 | **业务表**：`towers`、`clusters`、`vm_latest`、`vm_volumes`、`users` | SQLite | **零变化**（含加密凭据列、口令哈希） | L2/L3/L5/L6 |
| 2 | **运行表**：`tasks`、`collection_runs`、`metric_snapshots` | SQLite | 允许**新增行**；升级前已有行不得变化 | L3 |
| 3 | **迁移表**：`schema_migrations` | SQLite | **只增**（记录已应用迁移）；不得减少或改写 | L3/L6 |
| 4 | **runner 表**：`upgrade_runner_state`、`upgrade_task_leases` | SQLite | 任意变化（心跳/租约，运行时数据） | 不作判据 |
| 5 | **Prometheus 时序** | `/prometheus-data` + HTTP API | 历史样本**不得丢**；升级窗口可短暂缺采 | L3/L6 |
| 6 | **`.env`** | `project/.env` | 键集合与密钥**不变**（值不回显，只比 key 与 sha） | L2/L3 |
| 7 | **compose / 项目文件** | `project/` | 与升级包内容一致（包内 `checksums.sha256`） | L2/L3 |
| 8 | **备份包** | `backups/*.tar.gz` | 可解包、内含 `app/smartx.db` + `project/`、sha256 与记录一致 | L5/L6 |
| 9 | **导出物** | `exports/`（Word/Excel） | 接口 200、文件非空、可打开 | L3/L6 |
| 10 | **迁移包**（如涉及） | `exports/migration-*` | 可导入且业务表计数/指纹与源一致 | 专项 |

### 4.2 检验方法（七类，缺一不可）

**(1) 内容指纹（稳定列）** — 禁止 `SELECT *`（升级会加列 → 假报不一致）：

| 表 | 稳定列 |
| --- | --- |
| `towers` | `id, name, url, username, password_encrypted, api_token_encrypted`（凭据列**必须**参与，否则"凭据被清空"测不出来） |
| `clusters` | `tower_id, cluster_id, name` |
| `vm_latest` | `tower_id, cluster_id, vm_id, name, used_bytes` |
| `vm_volumes` | `tower_id, cluster_id, vm_id, volume_id, name, used_bytes` |
| `users` | `id, username, password_hash`（只比哈希，不比明文） |

- 输出 `{count, digest}`，`digest = sha256(repr(sorted(rows)))[:16]`。
- **可增长表**（`tasks`/`collection_runs`/`metric_snapshots`）：用 `count_before ≤ count_after`
  且「升级前已有主键集合的行内容不变」判定，不能要求 count 相等。

**(2) 语义计数（接口 vs DB）** — 数据"在"不等于"对"：
- 概览/报表接口的 VM 总数、容量合计，与 DB 聚合（`COUNT(*)`、`SUM(used_bytes)`）一致（容差 0）；
- 「本日/本月新建 VM」计数与 `local_created_at`（缺失时回落首见）口径一致（#36/#37）；
- 回收站 VM 在概览与报表接口出现 **0 次**，详情深链返回 `original_name` + `in_recycle_bin=true`（②③）。

**(3) 引用完整性（孤儿行）**：
- `vm_latest.cluster_id` ∈ `clusters.cluster_id`；`vm_volumes.vm_id` ∈ `vm_latest.vm_id`；
- `clusters.tower_id` ∈ `towers.id`；`vm_latest.tower_id` ∈ `towers.id`；
- 每条查询必须返回 0 行孤儿。

**(4) 加密可用性（最容易漏、后果最重）**：
- **Tower 凭据可解密**：用 `.env` 的 `SMARTX_CREDENTIAL_KEY` 解密 `towers` 中的凭据列，
  解密失败 = `.env` 与 DB 不配对（迁移把密钥换了/丢了）；有塔时再做一次连接测试；
- **用户可登录**：用升级前的管理员口令调用 `/api/auth/login` 必须 200（`SECRET_KEY` 未变）。

**(5) 时序连续性（Prometheus）**：
- 升级前记录：series 数量、最近样本时间戳、指定时间窗内的样本数；
- 升级后：**升级前的历史窗口样本数与值必须完全一致**（`/api/v1/query_range` 比对）；
- 升级窗口内允许缺采，但**恢复采集后**必须继续有样本（`smartx_cluster_storage_used_bytes` 等）；
- 关键指标：`smartx_cluster_storage_used_bytes`、`_total_bytes`、`_allocated_bytes`、
  `smartx_vm_storage_used_bytes`。
- **前置条件**：升级前必须至少完成一次采集（基线窗口内 points > 0），否则时序检查是"空过"，
  脚本按 `WARN` 记（**不算通过**）。

**(6) 文件资产**：
- `.env`：键集合（≥ 15）与 `SMARTX_SECRET_KEY`/`SMARTX_CREDENTIAL_KEY` 非空；**只记录 key 与
  sha256，绝不回显值**；升级前后按 key 比较，值应一致（重排不算变化）；
- `project/docker-compose.offline.yml` 的 sha256 与包内 `checksums.sha256` 一致；
- 备份包 `tar -tzf` 可列出且含 `app/smartx.db`；导出文件大小 > 0。

**(7) 跨库一致性（SQLite 当前态 vs Prometheus 最新样本）**：
- 采集正常时，`vm_latest.used_bytes` / `clusters` 容量与 Prometheus 最新样本对同一对象应一致，
  容差 ≤ 一个采集周期内的自然变化（默认 0，无法对齐时显式记录原因）；
- **升级后必须确认采集恢复**：终态快照的 Prometheus 窗口 points > 0（否则只是"没丢历史"，
  并不证明"还能采"）——该检查由脚本以 WARN 提示，最终判定时必须人工确认已恢复采集。

### 4.3 采样时点（少一个都不算通过）

| 时点 | 何时 | 用途 |
| --- | --- | --- |
| **T0** | 安装完成 / 注入测试数据后、升级开始前 | 基线 |
| **T1…Tn** | **每跳升级成功后**（含组件升级） | 定位是哪一跳破坏了数据 |
| **Tf** | 终态（post-cleanup 收敛后 + 至少一次采集后） | 最终判定 |
| **Tr** | 失败/回滚后 | 与 T0 比对，确认回滚真的恢复 |

- 一律**宿主直读 DB**（容器内 `/run/smartx-runtime.env` 可能异常，`docker cp` 会挂）；
- DB 路径按布局探测：`/data/smartx-storage-forecast/app/smartx.db` →
  `/data/smartx-capacity-insight-data/app/smartx.db` → `/data/smartx.db`；
- 同时记录 `PRAGMA integrity_check`（必须 `ok`）与 `PRAGMA foreign_key_check`（必须为空）。

### 4.4 允许差异白名单（白名单之外一律 FAIL）

| 允许 | 禁止 |
| --- | --- |
| `tasks`/`collection_runs`/`metric_snapshots` **新增行** | 上述表**已有行内容变化**或行数减少 |
| `schema_migrations` **新增行** | `schema_migrations` 行减少/改写 |
| 新增**列**（expand-only） | 已有列被删除/改名/类型变化 |
| `upgrade_runner_state`/`upgrade_task_leases` 任意变化 | — |
| `updated_at`/`last_seen` 类字段在**允许变化的表**里更新 | 业务表任何字段变化 |
| 升级窗口内 Prometheus **缺采** | 升级前历史样本丢失或值变化 |
| `.env` 行顺序变化 | `.env` 键缺失、密钥变化、文件变成目录 |

### 4.5 判定与证据

- **判定**：业务表指纹逐表一致 + 可增长表"旧行不变" + 引用完整性 0 孤儿 + 加密可用 +
  Prometheus 历史一致 + 文件资产一致；任一项不满足即 **FAIL**，并**不得**用"数据看起来还在"代替。
- **证据**：T0/T1…/Tf 的 `snapshot.json` + `compare` 输出（逐项 PASS/FAIL）写入
  `progress.md`；失败项必须给出**具体表名/列名/行主键**，不接受"数量对得上"。

### 4.6 用法（脚本，所有层复用）

```bash
# 升级前（T0）
python3 scripts/verify_data_integrity.py snapshot --prom http://127.0.0.1:9090 --label t0 --out /data/diag/t0.json
# 每跳成功后（T1…Tn）
python3 scripts/verify_data_integrity.py snapshot --prom http://127.0.0.1:9090 --label t1 --out /data/diag/t1.json
python3 scripts/verify_data_integrity.py compare --before /data/diag/t0.json --after /data/diag/t1.json
# 终态（post-cleanup 收敛 + 至少一次采集后）
python3 scripts/verify_data_integrity.py snapshot --prom http://127.0.0.1:9090 --label final --out /data/diag/final.json
python3 scripts/verify_data_integrity.py compare --before /data/diag/t0.json --after /data/diag/final.json
```

- 退出码：`0 = PASS`、`1 = FAIL`；输出逐项 `PASS/FAIL/WARN`，失败项带**表名/列名/计数**。
- `WARN` 不是通过：Prometheus 不可达会记为 WARN，必须在报告里显式说明"时序未验证"，
  不能当 PASS 计入。
- 脚本自身逻辑由 `backend/tests/test_verify_data_integrity.py`（8 例）锁定：业务行改动、
  凭据被清空、可增长表旧行被改、孤儿行、`.env` 缺键、`.env` 重排不算变化。

## 5. 环境与执行纪律

1. `.3` 只跑 L0/L1；`.14` 跑 L2/L3/L4；`.12` 跑 L3（生产等价）/L5/L6。
2. `.12` **宿主禁改**：清理走 `POST /api/admin/system/cleanup-artifacts` 或按任务删包
   `DELETE /api/admin/upgrade/package/{task_id}`；不得 `docker rmi` / `rm -rf`。
3. 每轮开始前记录**基线**（版本、runner、磁盘、容器、数据计数）；结束记录终态。
4. 磁盘：`.3` 清理时**保留 docker build cache**；`/tmp` 是 tmpfs，清它不释放磁盘。
5. 凭据：`.3` 用 `user1` + `su - root`；`.12`/`.14` 是 root 直登，**不要混用凭据**。
6. 远端脚本用 `setsid nohup ... &` 启动，且 `pkill` 的模式串要写成 `chain_[t]est` 形式
   （否则会杀掉执行命令的 shell 自身）。
7. 长时间链路**分段执行**：先跑 1–2 跳确认，再跑完整链；每段结束立即留证。

## 6. 证据与记录规范

- **日志**：`/data/<场景>-<候选>.log`（例：`verify-r40.log`、`chain-web-r40.log`），
  **完整保留**，不允许 `tail -N` 截断关键失败段（判定所需的失败项必须全文入日志）。
- **候选标识**：`rNN` + 源码提交 SHA + 平台包/runner 包 SHA256，三者一起记入
  [upgrade-package-ledger.md](upgrade-package-ledger.md)。
- **结论落点**：过程 → `progress.md`；稳定结论/坑 → `findings.md`；
  未完成事项 → `docs/pending-tasks.md`（含目标版本与遗留说明）；发布口径 → `CHANGELOG.md`。
- **禁止**：把"计划中的验收"写成"已完成"；用旧候选的结论顶替重建后的候选。

**证据归档**：验证机 `/data` 上的日志与 `/data/diag/*.json` 是**易失的**（机器重装即丢）。
每层结束后，把原始日志与快照打包归档（如 `/data/archive/<候选>-<层>-<日期>.tar.gz`），
`progress.md` 记录归档路径与关键行；只把结论写进文档、原始证据留在机器上 = 证据丢失。

**测试脚本自检纪律**：新的测试/验证脚本必须先在**已知一致状态**上自检
（`snapshot → compare` 同状态必须 0 FAIL、断言路径人工核过一遍），才允许用于正式验证。
2026-10-16 的教训：harness 在 status-404 上空转、心跳窗口误判，两条链路的"失败"其实是脚本问题
——没有自检的脚本会把"脚本 bug"混进"产品结论"，两头都污染。

## 7. 失败处置

1. **失败即停**：先定性（产品缺陷 / 环境残留 / 测试脚本 bug），**不得静默重试同一操作**。
2. 三类定性各自的动作：
   - 产品缺陷 → 记 `findings.md` + 立项（pending），修完**重打候选**并重跑受影响的层；
   - 环境残留 → 记录并**用产品流程**恢复（不得手工改宿主）；
   - 测试脚本 bug → 修脚本，**在日志里注明"脚本问题，非产品结论"**，不得算作通过或失败。
3. 每次失败必须记录：现象、命令、完整错误、根因、下一步。禁止"再跑一次看看"。

## 8. 已知未覆盖项（诚实声明，按需立项）

以下**本规范不覆盖**。出现对应场景/客户报告前不阻塞发布，但立项时必须回到本表勾销：

| 项 | 风险 | 何时必须补 |
| --- | --- | --- |
| 性能/大库 | 1 万+ VM 时升级时长、报表接口响应未测 | 首个现场规模接近时 |
| UI 逐页目视 / 多浏览器 | 只验了 HTTP 200，未验渲染 | 发布给外部客户前 |
| 安全专项 | 升级 API 鉴权未做过渗透式专项 | 暴露到非内网前 |
| Docker/compose 版本矩阵 | `healthcheck`/top-level `name` 依赖较新 compose | 首个非自带 Docker 的现场前 |
| 有塔环境端到端 | ①Tower 创建时间归属、②③真实回收站过滤只有单测 | 拿到塔凭据时 |
| 基础设施故障注入 | 升级中磁盘写满/断网/docker.sock 异常 | v0.5.5（与 #96 收尾一起） |
| 幂等/重复执行 | 同一升级包连跑两次、失败后重跑的收敛 | v0.5.5 |
| 人工回滚/整库替换演练 | backup-recovery.md 手册未在真机演练过 | 有生产客户前 |

## 9. 本轮（v0.5.4 / r40）执行清单

按顺序执行，每步留证；前一步不过不进下一步。

- [ ] **L0**：后端全量 + 前端门禁（基线 1240 tests / 1F+1E 存量）
- [ ] **L1**：r40 四道门禁（已构建：平台 `89bc10be…` / runner `1d056aa9…`）
- [ ] **L2**（`.14`）：全新安装 8 项（含 `upgrade-runner` `(healthy)`、心跳每 ~5s 刷新）
- [ ] **L3-a**（`.14`）：`v0.5.3 → 组件 v0.3.3 → 平台 r40`（CLI），每跳指纹
- [ ] **L3-b**（`.14`）：同链路走 **Web 接口**，每跳指纹
- [ ] **L3-c**（`.14`）：`v0.5.1u2 → v0.5.2 → v0.5.3 → 组件 → r40`（老布局，处理旧平台心跳重试）
- [ ] **L4**（`.14`）：`.env` 目录反向用例 / `pause` runner → unhealthy / `component_platform` 拒绝
- [ ] **L4.5**（`.14`）：升级 running 时二次提交 → 400 / 升级中登录·概览·报表冒烟 / 升级窗口告警口径确认
- [ ] **L5**（`.12`）：场景 B/C 回滚（若本批改动涉及回滚路径则必跑）
- [ ] **L6**（`.12`）：同版本重装 + 8 项 + 矩阵回填

**明确不在本轮范围**（需额外条件，单独立项）：
- 有塔环境的功能端到端（① Tower 真实创建时间归属、②③ 真实数据回收站过滤）——`.12`/`.14` 无 Tower 配置；
- UI 逐页目视（本轮只做 HTTP 200 + 关键接口契约）；
- Prometheus 组件升级（#91 已单列）。

## 10. 变更记录

| 日期 | 变更 | 触发 |
| --- | --- | --- |
| 2026-10-17 | 补：进入/退出条件（含时钟同步，`.3` 实测慢 19s）、受控起点纪律、并发与干扰用例、跨库一致性（第七类）、证据归档、脚本自检纪律、已知未覆盖项声明 | 自评缺漏 + r40 构建时 tar 时间戳警告 |
| 2026-10-17 | 首版：分层 L0–L6、范围矩阵、数据完整性口径、证据规范、失败处置、r40 执行清单 | 全链路重测暴露"测试口径不统一/证据不可判定"问题（harness 404 空转、心跳误判、同版本组件自换留脏状态） |
