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
| **r19 平台包** | `.3:/data/r19-out/latest/smartx-capacity-insight-upgrade-v0.5.4.tar.gz`<br>SHA256 `52df80b7bca7cbf3d1d93205a6dc281731b6a9601da23b69107f5231b6b5c3a9` |
| **r19 runner 组件包** | `.3:/data/r19-out/latest/smartx-upgrade-runner-v0.3.2.tar.gz`<br>SHA256 `f0c87265ba765b0e4d2a6f11366300601971ceb70577f95d92f14b68bab404bf` |
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
scp .3:/data/r19-out/latest/smartx-capacity-insight-upgrade-v0.5.4.tar.gz root@10.20.11.14:/root/
sha256sum /root/smartx-capacity-insight-upgrade-v0.5.4.tar.gz    # 必须 = 52df80b7…

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
scp .3:/data/r19-out/latest/smartx-upgrade-runner-v0.3.2.tar.gz root@10.20.11.12:/root/   # sha f0c87265…
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

## 6. 每格执行完请回传这些（AI 侧据此更新 ledger 与勾选）

1. `task_id` 与终态；
2. 上面表格里**逐条**的实测值（失败项照实写，不要只写"通过"）；
3. 若任一判据不成立：失败步骤原文、当时容器/目录/数据库状态、包 SHA。