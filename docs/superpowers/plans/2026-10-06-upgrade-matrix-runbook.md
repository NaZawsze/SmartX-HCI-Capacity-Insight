# 升级矩阵操作清单（`.12` / `.14`）——用户亲自执行，我方提供判据与取证

最后更新：2026-10-06

本文件是**执行清单**：每格给出「前置 → 操作 → 判据（可逐条核对的硬事实）→ 取证命令」。
矩阵操作由用户亲自执行；执行期间需要取证（读 `task.json` / 容器 ID / 日志 / 计数）时由 AI 配合，
**AI 不代替用户在 `.12`/`.14` 上做变更**（AGENTS §5：`.12` 生产等价，一切变更走产品流程）。

## 0. 机器与凭据（2026-10-06 修正）

| 机器 | 地址 | 角色 | 登录方式 |
| --- | --- | --- | --- |
| `.14` | **`10.20.11.14`** | 干净验证机（C1 / 场景 B、C 回滚演练） | **root 直登**（密码见 `docs/development-verification-process.md` §1 的口径；**不在本文抄录**） |
| `.12` | **`10.20.11.12`** | 发布机（生产等价，C2 / C4） | **root 直登**（同上） |
| `.3` | `10.20.11.3` | 开发/主测试机（打包、门禁、沙箱） | `user1` + `su - root`（AGENTS §5） |

**两处历史错误（勿再犯）**：
1. `10.20.0.14` 是 Tower 网段地址，**不是** `.14`；`.14` 是 `10.20.11.14`。
2. `.12` / `.14` 是 root 直登，与 `.3` 的 `user1` + `su - root` 模式不同；
   凭据口径在 `docs/development-verification-process.md` §1（`.12` 行），**动手前先查文档，不要拿 `.3` 的去试**。

## 1. 共同前置

| 项 | 值 |
| --- | --- |
| **r21 平台包** | `.3:/data/r21-out/smartx-capacity-insight-upgrade-v0.5.4.tar.gz`<br>SHA256 `074a49374605ecbd41aebc6b1140e62b37f115af4de0a7ba4bec46a86a976012` |
| **r21 runner 组件包** | `.3:/data/r21-out/smartx-upgrade-runner-v0.3.2.tar.gz`（**逐字节继承 r20**）<br>SHA256 `05d8e015368928d93d41d8ba6881de5153e048578791c6653395e2df95fbaf47` |
| 取包方式 | 两者都**含镜像归档**，目标机只需 `docker load`（`.14` 的 Docker Hub 被 DNS sinkhole，不能靠拉取） |
| 取 token | `POST /api/admin/upgrade/login` 不存在；用 `POST /api/auth/login`，body `{"username":"admin","password":"<安装时的管理员密码>"}`，返回 `access_token` |

**`.14` 当前基线（2026-10-06 00:49:50Z 实测，可直接当 C1 的对照）**

| 服务 | 容器 ID | 镜像 |
| --- | --- | --- |
| web-api | `846aa3c8951e30bfd01cede0abef4897ab89fe5a981f3e4786a01d8c4022fe29` | `…-web-api:v0.5.3` |
| collector-worker | `1ee005acf288e7c87e3cb42297b32d435467007e514f983081bab7428c28d627` | `…-collector-worker:v0.5.3` |
| frontend | `e2b85a57a712e90ce2ce82fa52945782e4238c01efaa36daab39d555eada89b7` | `…-frontend:v0.5.3` |
| **prometheus** | `00d97b6f49fb9537d30642e8fc6b7dcac28b8951d378502fd23e02dee236df18` | `prom/prometheus:v2.55.1` |
| **upgrade-runner** | `2f814016f904dbb74aca92e5929f89b8aa8d1c0ef1f31a59bdf2c434adddb764` | `…-upgrade-runner:v0.3.1` |

`.env` SHA256 `60fa1ec3bc1f3fd0caea3192068e11bac88a0a5d5acc9c6d1cdba2c5e8935393`；业务库
`towers=0 clusters=0 vm_latest=0 vm_volumes=0 collection_runs=2`（**干净机，无业务数据**）。

---

## 2. C1（`.14`）：v0.5.3 → v0.5.4 直升（T3 判据）

### 操作（全部走产品 API）

```bash
# 0) 取包（.3 → .14）
scp .3:/data/r21-out/smartx-capacity-insight-upgrade-v0.5.4.tar.gz root@10.20.11.14:/root/
sha256sum /root/smartx-capacity-insight-upgrade-v0.5.4.tar.gz    # 必须 = 074a4937…

# 1) 上传 → 2) 预检查 → 3) 启动（token 取自 /api/auth/login）
curl -s -X POST http://127.0.0.1:8000/api/admin/upgrade/upload -H "Authorization: Bearer $TOKEN" \
     -F "file=@/root/smartx-capacity-insight-upgrade-v0.5.4.tar.gz"          # → task_id
curl -s -X POST http://127.0.0.1:8000/api/admin/upgrade/precheck/$TASK -H "Authorization: Bearer $TOKEN"
curl -s -X POST http://127.0.0.1:8000/api/admin/upgrade/start/$TASK   -H "Authorization: Bearer $TOKEN"
# 4) 轮询状态直到终态
curl -s http://127.0.0.1:8000/api/admin/upgrade/status/$TASK -H "Authorization: Bearer $TOKEN"
```

### 判据（逐条核对）

| # | 判据 | 期望 |
| --- | --- | --- |
| 1 | 预检查 | 全 OK；`source_compatibility` 的 `supported_versions=[v0.5.2,v0.5.3,v0.5.4]`、当前 v0.5.3 **在范围内**（不出现 remediation） |
| 2 | 任务终态 | `success`；动作集 = `backup.create / image.load×3 / files.sync / compose.override / compose.apply / health.http`（**8 个动作**），无 `project_migrate`/`filesystem.prepare`/`runner.*`/`legacy.*` |
| 3 | **差异清单** | 任务日志含 `compose.apply 差异清单：…`（A4/W4） |
| 4 | **实际结果** | 任务日志含 `compose.apply 实际结果：重建=[…]`（A4/W4） |
| 5 | **prometheus 容器 ID 不变** | 仍为 `00d97b6f49fb…`（T3 核心判据） |
| 6 | **upgrade-runner 容器 ID 不变** | 仍为 `2f814016f904…`，镜像仍 `…-upgrade-runner:v0.3.1` |
| 7 | runner 未被降级（US-26） | `/app/RUNNER_VERSION` = `v0.3.1`；health `runner_version=v0.3.1`（包基线也是 v0.3.1，属"够用不动"） |
| 8 | 三件套已换 | web-api/collector/frontend 容器 ID **变化**，镜像 tag = `:v0.5.4` |
| 9 | health | `{"ok":true,"version":"v0.5.4","runner_version":"v0.3.1","checks":{三项 true}}` |
| 10 | 数据 | `towers/clusters/vm_latest/vm_volumes` 仍为 0（干净机）；`collection_runs` 允许 +N |
| 11 | `.env` | SHA256 仍 `60fa1ec3…`、权限 0600 |
| 12 | 回滚锚点（A5） | `upgrade-runner-state.json` 出现 `rollback_anchors` 且含本次任务；`previous_version=v0.5.3`、旧镜像 tag + SHA |
| 13 | 守卫投递（A6） | `<project>/compose-guard.sh` 存在、可执行、含 `compose_guard_check`；`.env` 有 `SMARTX_COMPOSE_FILE_ACTIVE` |
| 14 | 场景 B 入口（B8） | `GET /api/admin/upgrade/rollback-availability` → `available=true`、`target_version=v0.5.3`、`scope=application_only` |

### 取证（AI 配合，可直接读）

```bash
cat  /data/smartx-storage-forecast/app/upgrade-runner-state.json | python3 -m json.tool | head -60
cat  /data/smartx-storage-forecast/upgrades/$TASK/task.json | python3 -m json.tool | head -120
docker inspect -f '{{.Name}} {{.Id}} {{.Config.Image}} {{.RestartCount}}' smartx-hci-capacity-insight-{web-api,collector-worker,frontend,prometheus,upgrade-runner}-1
docker logs smartx-hci-capacity-insight-upgrade-runner-1 2>&1 | grep -E "差异清单|实际结果|锚点"
curl -s http://127.0.0.1:8000/api/system/health
```

---

## 3. C2（`.12`）：组件升级 v0.3.1 → v0.3.2（自换链）

> 放在 `.12` 且**先于 C4**：升级后 C4 的平台直升就顺带覆盖「现场 runner v0.3.2 高于包基线 v0.3.1」
> 这一格（US-26 判别最有价值的一格）。

### 操作

```bash
scp .3:/data/r21-out/smartx-upgrade-runner-v0.3.2.tar.gz root@10.20.11.12:/root/   # sha 05d8e015…
curl -s -X POST http://127.0.0.1:8000/api/admin/component-upgrade/upload -H "Authorization: Bearer $TOKEN" \
     -F "file=@/root/smartx-upgrade-runner-v0.3.2.tar.gz"
curl -s -X POST http://127.0.0.1:8000/api/admin/component-upgrade/precheck/$TASK -H "Authorization: Bearer $TOKEN"
curl -s -X POST http://127.0.0.1:8000/api/admin/component-upgrade/start/$TASK   -H "Authorization: Bearer $TOKEN"
```

### 判据

| # | 判据 | 期望 |
| --- | --- | --- |
| 1 | 任务终态 | `success`；`automatic_rollback` **不存在**（组件任务不走平台回滚） |
| 2 | 容器确实被换 | `upgrade-runner` 容器 ID **变化**，`restarts=0` |
| 3 | 版本 | `docker exec … cat /app/RUNNER_VERSION` = `v0.3.2` |
| 4 | 停机 | ≤30s（对比升级前后容器 `StartedAt`，或 task 的 `started_at`/`finished_at`） |
| 5 | presence | ≤60s 内 `runner_presence` 报在场（`GET /api/admin/upgrade/status` 或 state 文件心跳推进） |
| 6 | web-api 零参与 | 升级期间 web-api 容器 ID 不变；日志无 web-api 参与编排的痕迹 |
| 7 | 锚点在 writeback 前 | 锚点 `previous_version=v0.3.1`、`previous_image_tag` 为 v0.3.1（不是 v0.3.2） |
| 8 | 数据 | 升级前后业务库计数逐表一致（`.12` 有真实数据，**必须逐位不变**） |

---

## 4. C4（`.12`）：平台直升回归

### 推荐口径（避免动生产数据）

**不降级到 v0.5.2**（降级要重装、风险高且会动 `.12` 的真实数据）。改为在 C2 之后做
`v0.5.3 → v0.5.4` 直升，从而覆盖两格：
- 「v0.5.3 + runner v0.3.1 → v0.5.4」（若跳过 C2 先做平台）
- 「v0.5.3 + runner v0.3.2 → v0.5.4」（做完 C2 再做平台，**US-26 判别最关键**）

**未覆盖并须如实记录**：`v0.5.2 源` 那格（真要覆盖需在 `.12` 装 v0.5.2 基线，属于降级操作，
需另行授权 + 数据备份）。

### 判据（在 C1 的 14 条基础上加严）

| # | 判据 | 期望 |
| --- | --- | --- |
| A | **runner 未被降级（US-26 关键判别）** | 现场 runner 是 v0.3.2，包基线是 v0.3.1 → 升级后 runner **仍是 v0.3.2**，容器 ID 不变 |
| B | **数据逐位不变** | `towers/clusters/vm_latest/vm_volumes` 与升级前**完全一致**（`.12` 有真实数据，这是本格的核心价值） |
| C | `.env` | SHA256 不变、权限 0600 |
| D | post-cleanup | 若计划含 cleanup 任务，其终态 `success`（v0.5.4 计划不含 cleanup，见 impl-spec §W6.2） |
| E | 幂等 | 同版本重装一次仍 `success`，且三件套镜像 ID 不再变化（收敛证据） |

---

## 5. C3 剩余项：场景 B / C 真机手动回滚（`.14` 上做）

> `.14` **无业务数据**，场景 C（会丢数据）只能在 `.14` 做；`.12` **不要**做场景 C。
> ①④② 已由 `.3` 沙箱实测（`w5sb` / `w3c`），③ post_upgrade 按 2026-10-06 决议**单测覆盖即充分**。

### 5.1 场景 B（应用回滚，保数据）——接着 C1 做

```bash
curl -s http://127.0.0.1:8000/api/admin/upgrade/rollback-availability -H "Authorization: Bearer $TOKEN"
curl -s -X POST http://127.0.0.1:8000/api/admin/upgrade/rollback -H "Authorization: Bearer $TOKEN"
```

| # | 判据 | 期望 |
| --- | --- | --- |
| 1 | 可用性 | `available=true`、`target_version=v0.5.3`、`images` 含三件套旧 tag |
| 2 | 任务 | `manual-rollback-*` 终态 `success`；计划动作 = `compose.override / compose.apply / health.http` |
| 3 | 三件套回到旧版 | 镜像 tag = `:v0.5.3`；health `version=v0.5.3` |
| 4 | **不动 runner / prometheus** | 两者容器 ID 与 C1 结束时一致 |
| 5 | 数据保留 | 计数与回滚前一致（场景 B 不动数据） |

### 5.2 场景 C（整备回滚，数据回到升级前）

```bash
curl -s http://127.0.0.1:8000/api/admin/upgrade/full-rollback-availability -H "Authorization: Bearer $TOKEN"
# 不带确认 → 必须被拒（400），错误里带丢失窗口
curl -s -X POST http://127.0.0.1:8000/api/admin/upgrade/full-rollback \
     -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"confirm_data_loss": false}'
# 确认后再执行
curl -s -X POST http://127.0.0.1:8000/api/admin/upgrade/full-rollback \
     -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"confirm_data_loss": true}'
```

| # | 判据 | 期望 |
| --- | --- | --- |
| 1 | 未确认被拒 | 400，错误文案含 `confirm_data_loss` 与丢失窗口 |
| 2 | 可用性 | `available=true`、`backup.sha256_ok=true`、`data_loss_window` 非空 |
| 3 | 任务 | `manual-full-rollback-*` 终态 `success`；动作 = `rollback.restore / health.http` |
| 4 | 数据回到备份点 | SQLite `integrity_check=ok`，计数与锚点 `pre_upgrade.counts` 一致 |
| 5 | 版本 | health `version=v0.5.3` |

---

## 6. C0（新增，2026-10-06 用户指令）：v0.5.2 源格 + 数据完整性

### 为什么加这一格

`version-skew-matrix.md` 的「v0.5.2 → v0.5.4」格原先只有**静态**证据（已发布 v0.5.2 镜像内
编译器编译同一 manifest，动作集与候选一致）。而 C1/C4 **都从 v0.5.3 出发**，覆盖不到它——
v0.5.2 恰恰是现场存量最大的源版本，这一格不能只靠静态证据就宣称支持。
用户 2026-10-06 指令：**先在 `.14` 测，后在 `.12` 测；数据先备份，恢复到 v0.5.2 时导入，
再走升级流程看数据会不会丢。**

### 6.1 前置物料（`.3` 已就绪，AI 已构建）

| 物料 | 路径 | 说明 |
| --- | --- | --- |
| **v0.5.2 基线交付目录** | `.3:/data/delivery-v052` | 用**已发布** v0.5.2 平台包 + **已发布** v0.3.1 runner 包构建；install compose 落 v0.5.2 + runner v0.3.1，US-33 自洽门禁通过 |
| v0.5.4 交付目录 | `.3:/data/delivery-v054` | 交付用（runner 基线 v0.3.2，`a345362` 决策） |
| r19 平台包 | 见 §1 | 升级用 |
| 备份/导出工具 | `scripts/capture_baseline.py`（VACUUM INTO 快照 + `.env` 配对 + SHA） | `.3` 上对 `.12` 执行 |

> 构建 v0.5.2 交付目录时发现并修掉一个真实缺口：`build_offline_delivery.py` 原本只把 runner tag
> 落基线，平台三件套 tag 沿用仓库当前 `VERSION`（v0.5.4），US-33 自洽门禁当场拦下
> 「compose 要 v0.5.4 / 归档实际含 v0.5.2」。已修为支持任意 `platform_version`（`9fd1be2`，4 例门禁）。

### 6.2 执行顺序（两台机器各自串行，机器之间可并行）

| 机器 | 顺序 | 理由 |
| --- | --- | --- |
| `.14` | **C1 → C3 → C0** | C1 要用当前这台「干净、无业务数据」的 v0.5.3 做 T3 纯净对照；C3 在 v0.5.4 上做回滚；最后重装 v0.5.2 跑 C0 |
| `.12` | **C2 → C4 → C0** | C2/C4 依赖当前 v0.5.3 + 真实数据现场；C0 需要降级重装，破坏性最大，放最后 |

### 6.3 C0-Part 1：`.14`（先做，无真实数据风险）

```bash
# 0) 记录 C0 前的现状（`.14` 上跑取证脚本）
bash ops/evidence.sh c0 before

# 1) 备份：`.14` 无业务数据，但仍按流程留档
#    迁移包导出（产品流程，v0.5.2 就有导出能力）
curl -sS -X POST http://127.0.0.1:8000/api/admin/migration/export \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{}' -o /root/c0-pre-export.tar.gz -w 'HTTP=%{http_code}\n'

# 2) 停止并清理当前 v0.5.3 现场（.14 是干净验证机，允许破坏性演练）
cd /data/delivery-v052/install
bash install.sh --check          # 先自检
# 停旧现场：按 AGENTS §9 红线，只停容器、**不删目标根目录里的数据目录**
#    （install.sh 自带旧现场检测；若需重装，先确认 /data/smartx-storage-forecast 已另行留档）

# 3) 安装 v0.5.2 基线
bash install.sh                   # 走产品安装脚本，不手工 docker compose
# 判据：health ok、platform=v0.5.2、runner=v0.3.1、5 容器、目录结构符合 §9

# 4) 造数据：优先用**导入**（用户指定路径）
#    ⚠️ v0.5.2 的导入**没有** Tower 身份重映射（#63 是 v0.5.3 才加的）。
#    本机身份与包内身份一致时用 full/replace 模式即可；若从 `.12` 导包到 `.14`，
#    身份会随包一起来（full 模式整库替换），因此**可以**导入，但采集时 base_url 也会跟着换，
#    需确认 `.env` 里的凭据与包内 Tower 身份匹配。
curl -sS -X POST http://127.0.0.1:8000/api/admin/migration/import \
  -H "Authorization: Bearer $TOKEN" -F 'file=@/root/<迁移包>.tar.gz' \
  -F 'mode=replace' -F 'confirmed=true' -w 'HTTP=%{http_code}\n'
# 备选：若导入不适用，改为让 `.14` 用 `.env` 里的 Tower 凭据直接采集（`10.20.11.7:4433`）

# 5) 固化基线（VACUUM INTO + .env + SHA）
python3 scripts/capture_baseline.py --help   # 按脚本实际参数执行

# 6) 升级 v0.5.2 → v0.5.4（产品流程）
bash ops/evidence.sh c0 before-upgrade      # 升级前取证
# 上传 r19 平台包 → 预检查 → 启动升级（API/UI）
bash ops/evidence.sh c0 after --task-id <upgrade-xxxx> --token $TOKEN
```

### 6.4 C0-Part 2：`.12`（后做，**破坏性最高，需你确认后才动**）

`.12` 有真实业务数据（上一轮记录 556 台 / 89588 卷），C0 会**删掉目标目录重装**，所以：

```bash
# 1) 两重备份，缺一不可
python3 scripts/capture_baseline.py    # VACUUM INTO 快照 + .env 配对 + SHA（可字节级还原）
curl -sS -X POST .../api/admin/migration/export -o /root/c012-pre-export.tar.gz   # 产品流程导出包
sha256sum /root/c012-pre-export.tar.gz
# 2) 停现场 → 用 /data/delivery-v052 装 v0.5.2 → 导入上面的包（full 模式）
# 3) 核对导入后逐表计数 == 备份时计数（不一致就停，不要继续升级）
# 4) 升级 v0.5.2 → v0.5.4（r19 平台包），再逐表比对
```

### 6.5 判据（数据不丢 = 本格的核心）

| # | 判据 | 期望 |
| --- | --- | --- |
| 1 | 升级前 `PRAGMA integrity_check` | `ok` |
| 2 | **逐表计数逐位不变**（`towers` / `clusters` / `vm_latest` / `vm_volumes` / `collection_runs` 等，用 `evidence.sh` 的 `04-db-counts.txt` 前后对比） | 全部相等；`.12` 上应与 556 / 89588 这一量级一致 |
| 3 | 业务库 SHA | **不要求相同**（升级会写迁移快照/心跳等），但必须能 `VACUUM INTO` 出可还原快照 |
| 4 | `.env` | SHA256 不变、权限 0600 |
| 5 | **prometheus 容器 ID** | 不变（历史目录不被清空、不重建） |
| 6 | prometheus 历史 | 升级后**继续累积**样本（口径说明：迁移包**不含** Prometheus 历史，所以"不丢"指不被清空，不是被迁移过来） |
| 7 | 升级后自动采集 | 成功，且新增样本可查 |
| 8 | Tower 凭据 | 解密正常、采集不报 401/证书错 |

> 口径提醒：SQLite 存业务元数据与最新状态，Prometheus 存历史时序。**"数据不丢"必须分两层说**：
> SQLite 层=逐表计数逐位不变；Prometheus 层=历史目录不被清空且继续累积。不要混成一个"数据全在包里"的误解。

### 6.6 与既有格的边界

- C0 **不替代** C1/C2/C4：它覆盖的是 v0.5.2 源格 + 数据完整性，不覆盖 US-26 的 v0.3.2 源判别。
- C0 不产生新的回滚证据（回滚仍由 C3 覆盖）。
- C0 期间 `.14`/`.12` 的当前平台版本会被改动，**C1/C2/C4 的基线 ID 以各自执行前重新取证为准**。

## 7. 每格执行完请回传这些（AI 侧据此更新 ledger 与勾选）

1. `task_id` 与终态；
2. 上面表格里**逐条**的实测值（失败项照实写，不要只写"通过"）；
3. 若任一判据不成立：失败步骤原文、当时容器/目录/数据库状态、包 SHA。