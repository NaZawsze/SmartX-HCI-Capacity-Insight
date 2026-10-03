# 故障排查手册（Troubleshooting Runbook）

适用版本：平台 v0.5.3（候选，尚未发布；已正式发布 v0.5.2）/ runner v0.3.1（已发布；开发线 v0.3.2 未交付）。读者：运维与接手的开发/AI。

通用原则（详见 AGENTS.md）：

- **先记录后动手**：任何失败先记录 task ID、原始错误、当时容器/目录/数据库状态和包 SHA，再处理；禁止静默重试同一操作。
- **容器内 `/proc/mounts` 是挂载唯一真相**，`docker inspect` 的 Binds/Mounts 不可靠。
- 禁止 `docker compose down -v`；禁止删除目标数据库、Prometheus 数据和 `app/` 下的挂载点目录（见 §2）。
- 业务库在 `/data/smartx-storage-forecast/app/smartx.db`（容器内 `/data/smartx.db`）；宿主机 `/data/smartx.db` 是 v0.5.1 旧残留（无业务表），操作前核对路径。
- compose 命令一律 `su - root` 执行（user1 不在 docker 组）；`.env` 为 root:0600。
- 版本身份以镜像内 `/app/VERSION`、`/app/RUNNER_VERSION`、runner heartbeat 和实际容器为准，`.env` 不是版本真相源。

## 1. 第一分钟：快速分诊

```bash
# 健康与版本（前端代理，免 token）
curl -fsS http://localhost:8080/api/system/health | python3 -m json.tool
# 容器状态（先过守卫取当前实例真正生效的 compose，别照抄文件名——见 §10）
bash /data/smartx-storage-forecast/project/compose-guard.sh check \
     /data/smartx-storage-forecast/project/.env docker-compose.offline.yml \
  && cd /data/smartx-storage-forecast/project \
  && docker compose -f docker-compose.offline.yml ps
# 磁盘
df -h /data
# 挂载体检（UPG-050 专用工具）
bash /tmp/bind-mount-recover.sh check   # 或项目内 scripts/bind-mount-recover.sh
```

health 返回 `checks` 三项的含义：

| check | 含义 | 典型故障方向 |
| --- | --- | --- |
| `directories` | 目标目录（upgrades/backups/exports/compose-runtime 等）可访问 | 挂载衰减（§2）、目录权限 |
| `database` | SQLite 可打开、可查询 | 库文件损坏/路径错（§3） |
| `prometheus` | Prometheus 查询可达 | 容器未起/目标掉线（§5） |

## 2. 挂载"衰减"：app/ 下目录消失或内容畸变（UPG-050）

现象：`/data/smartx-storage-forecast/app/{upgrades,backups,exports,compose-runtime,smartx-storage-forecast}` 目录消失、为空、或出现嵌套畸变副本；升级任务找不到目录、容器内对应挂载点失效。

机制（已定案，详见 findings.md UPG-050）：这些目录是 dockerd 经 app bind 在容器创建时**补建的挂载点载体**（容器内被 `upgrades:/data/upgrades` 等真实 bind 遮蔽）。宿主机 `rm` 会让共享该 bind 的全部容器挂载彻底消失；`mv` 会把挂载搬到新路径。历次"衰减"均为清理操作自伤。

处理：

```bash
# 体检：应为 20 项挂载全部 OK（web-api 7 + collector-worker 5 + runner 7 + prometheus 1）；
# 末尾附带载体目录锁状态报告（仅提示，不影响退出码）
bash scripts/bind-mount-recover.sh check
# 恢复：自动解锁（如带锁）→ 全服务一次性重建 → 验证 → 自动复锁；
# 不带任何服务参数（单服务重建不修复共享 bind）；验证失败会保持解锁并明确提示
bash scripts/bind-mount-recover.sh recover
# 复验
bash scripts/bind-mount-recover.sh check
curl -fsS http://localhost:8080/api/system/health
```

物理锁（可选能力，2026-09-20 验证后按用户决策未默认启用）：

- `lock` 对 6 个载体路径 `chattr +i`：rm/mv 当场报 `Operation not permitted`，与操作者是否读过文档无关；已验证 dockerd 可在锁定目录上正常建立挂载（全停全建 + 写穿透均通过）。需要时可在单台机器单独加锁。
- `unlock` 解锁（幂等）；**加锁机器上合法运维需要动这组目录时（重装/迁移/清理）先 unlock，做完再 lock**。
- `recover` 在锁定状态下可直接跑（自动解锁/复锁）；实测约 20-40 秒中断。
- 锁的边界：只保护 6 个载体目录；`app/` 本身（SQLite WAL 建文件）与真实数据目录刻意不锁；锁防误删载体，**不防删库**（删库靠备份与权限纪律，见 docs/backup-recovery.md）。

红线：容器运行期**禁止 rm/mv** `app/{upgrades,backups,exports,compose-runtime,smartx-storage-forecast}`。这些目录为空是正常态，必须存在；加锁的机器上 rm/mv 会被操作系统直接拒绝。

## 3. 数据库（SQLite）

现象：`database is locked`、写入超时、查询慢。

- v2 已配置 WAL + `busy_timeout` 5s，并在 `tasks.updated_at`、`collection_runs.started_at/finished_at` 建索引（见 findings.md 2026-09-12 治理记录）。偶发锁等待先观察，持续报锁再查：
- 检查：是否有异常长连接/手工 sqlite 会话未提交；web-api 与 collector-worker 双进程并发是设计行为。
- **禁止删除 `-wal`/`-shm` 文件**；不要在业务高峰直接 `VACUUM`（管理页的 SQLite VACUUM 会先扫描再执行）。
- 完整性核对：`sqlite3 /data/smartx-storage-forecast/app/smartx.db 'PRAGMA integrity_check;'`（应返回 `ok`）。
- 行数基线对比用 `scripts/capture_baseline.py verify`（capture 时的 SHA256SUMS + manifest 行数）。

## 4. 采集与 Tower

按 `/api/towers/{id}/test` 与采集任务的报错分类：

| 报错 | 方向 | 处理 |
| --- | --- | --- |
| `No route to host` / 连接超时 | Tower 网络不可达 | 测试网 Tower `10.20.0.6` 不可达是已知环境限制；生产地址核对防火墙/路由 |
| 401/登录失败 | Tower 账号或 API token | Tower 侧核对账号；UI 密码框不回显是设计行为，不代表凭据丢失 |
| `Tower XOR 凭据无法认证密钥` | `.env` 与库中凭据不配对 | 确认 `SMARTX_SECRET_KEY` 与入库时一致；在 Tower 设置重新保存密码即可重建配对 |
| 部分集群成功部分失败 | 单集群数据问题 | 看采集 run 明细（`GET /api/collection/runs/{run_id}`）；部分成功是设计行为，不回滚整体 |

背景结论：升级不会动 `.env`（升级前后逐字节一致）；"升级完密钥丢了"历史上是 UPG-049 误判 legacy 迁移的假阳性（已修复）或 .env 被仓库同步覆盖（9-13 事故），不是升级流程本身丢密钥。

定时采集未触发：Tower 级调度由"采集间隔（分钟）"控制（默认 60，0 = 使用每日采集时间 `collection_hour`）；worker 每 60s 同步一次调度，看 collector-worker 日志与 `collection_runs`。

## 5. Prometheus 与趋势为空

数据链路：worker 采集 → SQLite `metric_snapshots` → worker `:9108 /metrics` 导出 → Prometheus 60s 抓取 → 页面 instant/range 查询。任一环断了趋势就空。

定位顺序：

```bash
curl -fsS http://localhost:9108/metrics | head          # worker 是否在导出
curl -fsS http://localhost:9090/-/healthy               # Prometheus 本体
curl -fsS 'http://localhost:9090/api/v1/targets' | grep -o '"health":"[a-z]*"'   # 抓取目标 up
sqlite3 /data/smartx-storage-forecast/app/smartx.db 'SELECT COUNT(*) FROM metric_snapshots;'
```

- 迁移/导入后趋势为空：迁移包必须包含 Prometheus 历史 block；补全导入后需等一个抓取周期，必要时在服务管理重启数据服务。
- Prometheus 容器循环重启：多为数据目录权限，`pre_install.sh` 负责修正；核对 `PROMETHEUS_DATA` 实际挂载（容器内 `/prometheus`）。

## 6. 平台升级失败

- **先取证再动手**：记录任务 ID（任务中心）、失败步骤、runner 日志、`upgrades/<task_id>/task.json`、包 SHA256；对照 `docs/upgrade-package-ledger.md` 确认包身份。失败后不得在半升级现场反复重跑，修复后从干净基线重新走链路（AGENTS §10）。
- `Tower XOR 凭据无法认证密钥，且未找到可保留来源配对关系的旧环境 .env`：凭据守卫 fail-closed 是设计（UPG-042）；若发生在 v0.5.2→v0.5.3 且从未配置 Tower 凭据可继续，配置过凭据的机器在 Tower 设置重新保存后重试。UPG-049 误判场景已在 v0.5.3 重打包修复（runner 镜像 `7d152590d6fd` 之后）。
- `recovery_required` 状态：用任务中心的恢复入口（`recovery/{task_id}/continue|rollback|fail`）按提示处理，不要手工改 task.json。
- 升级中**不要 recreate upgrade-runner**：会让 running 任务失去执行者（checkpoint/租约可恢复，但应避免）。
- 升级"成功"但版本没变：核对镜像内 `docker exec web-api cat /app/VERSION`、compose 镜像 tag 是否字面量正确、是否用了 `docker compose restart`（restart 不换镜像，必须 build + `up -d`）。

## 7. 前端与 API

- 前端不可达：`docker compose ps` 看 frontend/web-api；容器内 Nginx 代理 `/api` 到 web-api:8000。
- 401：token 过期，重新登录；改密后旧 token 失效属预期。
- 总览数据陈旧：页面会显示"数据截至 HH:mm，刷新失败"；后端 summary 有 60s TTL 缓存，采集完成后按 run id 失效。若长期不刷新，按 §5 查采集与 Prometheus 链路。
- 上传大包报 Request Entity Too Large：使用分块/后台任务上传入口（迁移导入已支持进度与后台任务）。

## 8. 磁盘与空间

- 先用服务管理 → 清理：四类扫描（运行产物 artifacts、未使用镜像、SQLite 备份）+ SQLite VACUUM，先扫描后删除。
- 大头通常在 `/data/smartx-storage-forecast/{upgrades,backups,exports}`（升级包、升级前备份、报表/迁移留档）。
- `app/` 下的同名目录是挂载点载体（§2），**不是清理对象**。

## 9. 管理员密码重置

```bash
cd /data/smartx-storage-forecast/project
docker compose exec web-api python -m app.cli reset-password --username admin            # 交互式
docker compose exec web-api python -m app.cli reset-password --username admin --password '<new>'  # 非交互
```

重置后重新登录。

## 10. 容器被 SIGKILL：exit 137 且 OOMKilled=false（US-37）

**这是「被人为杀掉」，不是内存不足。** 判据是 `OOMKilled=false`：
内核 OOM 会把它置为 `true`。

```bash
docker inspect --format '{{.State.ExitCode}} OOM={{.State.OOMKilled}}' <容器名>
# 137 OOM=false  → 人为 SIGKILL，继续往下查
# 137 OOM=true   → 真 OOM，查内存与 limit
```

### 10.1 最常见成因：同一 project 混用不同 compose 变体（2026-09-30 .3 事故）

仓库有 4 个 compose 变体共享同一个 project 名，但服务定义不同
（`build:` vs `image:`、`pull_policy`、额外挂载），因此 `config-hash` 必然不同。
用错变体执行 `up/down/restart` → Docker 判定「配置变了」→ **recreate** →
旧容器被 SIGKILL → 服务中断。

```bash
# ① 确认是谁在用哪份 compose（容器标签 = 地面真相）
docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' \
  <project>-web-api-1

# ② 与 .env 里记录的生效变体比对（不一致返回 exit 2）
bash /data/smartx-storage-forecast/project/compose-guard.sh check \
     /data/smartx-storage-forecast/project/.env <你要用的-compose> <project>
```

守卫返回 **exit 2** 就是这个问题。三条出路见守卫自身输出：
改用正确的 compose / 加 `--force-compose-switch`（先完整 down 再换，会中断服务）/
先手工 `down --remove-orphans` 再换。

**若 `.env` 里没有标记**（旧环境）：重跑一次 `install/install.sh` 即可补上。
它会从**运行中容器的 compose 标签**回填地面真相，不靠猜。

### 10.2 其他成因

| 成因 | 判别 |
| --- | --- |
| 卡死任务被标记失败 / 升级回滚 | 查升级中心任务时间点是否与容器重启时间吻合 |
| 宿主机内存压力 | `dmesg -T | grep -i "killed process"`，有记录才是真 OOM |
| 人工 `docker kill` / `docker compose down` | 查 bash history 与任务记录 |

### 10.3 预防

- 任何 `docker compose` 操作前先过守卫，不要凭文件名猜。
- 交付物里的 `compose-guard.sh` 与 install/upgrade 脚本放在一起，就是给这件事用的。
- 升级中心已把「预检查 → 执行 → post-cleanup」串起来，正常升级路径不会碰 compose 变体。

## 11. 快速自检：站点验收 9 项

排障前先跑一次标准验收，把「哪里坏了」变成清单：

```bash
bash scripts/verify_site_acceptance.sh --expected-version v0.5.3 --expected-runner v0.3.1
```

只读、不改任何状态（除登录换 token），凭据只从 `.env` 读、不回显。
9 项逐条打印 OK/FAIL，退出码 0 表示全过。

| 项 | 检查什么 | FAIL 时的方向 |
| --- | --- | --- |
| ① health + 三项 checks | 平台可达、`directories`/`database`/`prometheus` | 见 §1 快速分诊 |
| ② 容器数 5 | 五个容器均 Up | 见 §1、§2 |
| ③ 镜像内版本文件 | `/app/VERSION`、`/app/RUNNER_VERSION` 与期望一致 | 镜像与包不匹配，重装 |
| ④ compose project/network | project 标签与唯一网络名 | 用了错 compose 变体，见 §10 |
| ⑤ `.env` 权限与 compose 标记 | 0600、`SMARTX_COMPOSE_FILE_ACTIVE` 存在 | 权限被改会读不到凭据；缺标记见 §10.1 |
| ⑥ SQLite 完整性与计数 | `integrity_check=ok` 与各表行数 | 见 §3 |
| ⑦ 旧路径清理 | `/opt/smartx-storage-forecast` 等 6 条已不存在 | 升级收尾未完成，看升级中心 post-cleanup |
| ⑧ 前端/Prometheus | 8080 首页 200、9090 health 200 | 见 §5、§7 |
| ⑨ 升级任务历史 | 最近任务状态与消息 | 有 failed 就按 §6 排查 |

