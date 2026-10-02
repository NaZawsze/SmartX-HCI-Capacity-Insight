# 备份与恢复手册（Backup & Recovery Runbook）

适用版本：平台 v0.5.3（候选，尚未发布；已正式发布 v0.5.2）/ runner v0.3.1。目标目录布局：`/data/smartx-storage-forecast/{project,app,prometheus,upgrades,backups,exports,compose-runtime}`（详见 [deployment.md](deployment.md) §6）。

核心原则：

- **业务数据 = SQLite + Prometheus 历史 + 配套 `.env` 三位一体**。只备份 SQLite 不算完整备份：趋势/增长/预测依赖 Prometheus 历史 block；Tower 凭据是 XOR 加密存储，解密依赖 `.env` 中的 `SMARTX_SECRET_KEY`，`.env` 必须与数据库同代保管（0600）。
- 禁止 `docker compose down -v`；恢复操作前先记录基线（容器状态、目录、数据库行数），恢复后逐项比对并报告。
- 在 10.20.11.3 之外的环境（尤其 10.20.0.6）执行任何写操作前必须获得用户对具体命令的批准。

## 1. 平台已有的备份机制

| 机制 | 触发 | 产物位置 | 说明 |
| --- | --- | --- | --- |
| 平台升级前备份 | 升级流程自动 | `backups/upgrade-<版本>-before-<时间>.tar.gz` | 升级包执行 `backup.create` 生成；回滚依赖它 |
| 迁移导入前备份 | 导入任务自动 | 导入任务记录的备份路径 | 备份失败默认阻止导入；导入结果与任务中心显示备份路径 |
| 数据迁移导出包 | 服务管理 → 数据迁移 → 导出 | 下载 + `exports/migrations/` 留档 | **业务库 + Prometheus 历史 block 成对全量导出**，推荐的全量备份手段；导出时自动生成与迁移包同名的 `.env` 配对快照（0600），任务中心附「配对 .env」下载链接 |
| SQLite 备份扫描/删除 | 服务管理 → 清理 | — | 管理**已有**备份文件的清理，不创建备份 |
| 标准基线产物 | `scripts/capture_baseline.py capture` | 快照 + `SHA256SUMS` + manifest 行数 | 升级/大改前固化"SQLite + 配套 .env + Prometheus"可校验基线（Phase 49 第 7 项） |

## 2. 推荐备份策略

- **常规（每周或大变更前）**：走产品正规流程生成迁移导出包并下载到异地（自动含配对 `.env` 快照，可一并转存）。迁移包恢复时必须与同代 `.env` 配对，才能解密 Tower 凭据；产品内也可单独下载当前 `.env`（数据迁移页「下载当前 .env」）。
- **升级前**：升级流程自带备份即可，另用 `capture_baseline.py capture` 固化基线，升级后 `verify` 比对。
- **保留期**：`backups/` 与 `exports/` 会持续增长，用服务管理 → 清理定期回收；不要手工 rm（尤其不要碰 `app/` 下的挂载点目录，见 troubleshooting.md §2）。
- **周期性自动备份**：暂不启用（用户 2026-09-20 决策）。能力已完成设计与实现验证（SQLite 快照 + 同代 .env 成对滚动保管，见 docs/superpowers/specs/2026-09-20-auto-backup-and-env-pairing-design.md 与 progress.md 49-25），代码已撤下待后续按需恢复；现阶段自动化备份需求由迁移导出包 + 基线脚本覆盖。

## 3. 手工冷备步骤（不依赖页面）

```bash
cd /data/smartx-storage-forecast/project
D=/backup/manual-$(date +%Y%m%d-%H%M)   # 目标盘自行确认空间
mkdir -p $D

# 1) SQLite 一致性快照（在线 VACUUM INTO，等价 capture_baseline 的快照方式）
docker compose exec -T web-api python -c \
  "import sqlite3; sqlite3.connect('/data/smartx.db').execute(\"VACUUM INTO '/data/backups/manual-snapshot.db'\")"
cp -a /data/smartx-storage-forecast/backups/manual-snapshot.db $D/smartx.db && rm /data/smartx-storage-forecast/backups/manual-snapshot.db

# 2) Prometheus 历史（停 collector-worker 可避免备份窗口内新写入，可选）
docker compose -f docker-compose.offline.yml stop collector-worker
cp -a /data/smartx-storage-forecast/prometheus $D/prometheus

# 3) 项目配置（compose、脚本；.env 必含且保持 0600）
cp -a /data/smartx-storage-forecast/project $D/project
chmod 600 $D/project/.env

# 4) 基线信息与校验
sqlite3 $D/smartx.db 'PRAGMA integrity_check;'
for t in users towers clusters vm_latest vm_volumes metric_snapshots; do
  echo "$t $(sqlite3 $D/smartx.db "SELECT COUNT(*) FROM $t;")"
done > $D/counts.txt
( cd $D && sha256sum smartx.db project/.env > SHA256SUMS )

docker compose -f docker-compose.offline.yml start collector-worker
```

完成后把 `$D` 传输到异地存储，并记录日期、版本（`docker exec web-api cat /app/VERSION`）、各表行数。

## 4. 恢复步骤

前置：新环境先按 `pre_install.sh` 与 `docs/deployment.md` 完成目录与镜像准备；记录恢复前基线（容器、目录、如目标库存在则记行数）。**目标机器上已有业务数据时，先确认要被覆盖的范围并报告用户，不得静默覆盖。**

```bash
cd /data/smartx-storage-forecast/project

# 1) 停平台写入方（保留目录与数据）
docker compose -f docker-compose.offline.yml stop web-api collector-worker frontend prometheus

# 2) 恢复 SQLite（先移走旧库留证，不直接删除）
mv /data/smartx-storage-forecast/app/smartx.db /data/smartx-storage-forecast/app/smartx.db.pre-restore-$(date +%Y%m%d-%H%M)
cp -a <备份目录>/smartx.db /data/smartx-storage-forecast/app/smartx.db
chown root:root /data/smartx-storage-forecast/app/smartx.db
sqlite3 /data/smartx-storage-forecast/app/smartx.db 'PRAGMA integrity_check;'   # 必须 ok

# 3) 恢复 .env（与数据库同代；0600）
cp -a <备份目录>/project/.env /data/smartx-storage-forecast/project/.env
chmod 600 /data/smartx-storage-forecast/project/.env

# 4) 恢复 Prometheus 历史（整目录替换前先移走旧目录留证）
mv /data/smartx-storage-forecast/prometheus /data/smartx-storage-forecast/prometheus.pre-restore-$(date +%Y%m%d-%H%M)
cp -a <备份目录>/prometheus /data/smartx-storage-forecast/prometheus
chown -R 65534:65534 /data/smartx-storage-forecast/prometheus   # 必做：容器以 uid 65534 运行，
                                                                # 属主为 root 时 prometheus panic 循环（queries.active permission denied）

# 5) 起服务并重建容器（保证挂载齐全）
docker compose -f docker-compose.offline.yml up -d --force-recreate
```

### 恢复后验证清单

1. `curl -fsS http://localhost:8080/api/system/health` → `ok=true`，`checks` 三项全 `true`，版本符合预期。
2. `PRAGMA integrity_check` 返回 `ok`；`counts.txt` 与备份时行数一致（`users/towers/clusters/vm_latest/vm_volumes` 不减少）。
3. Tower 连接测试通过（证明 `.env` 与凭据配对正确；若报 XOR 解密错误，说明 `.env` 与库不同代）。
3b. Prometheus 容器稳定运行（若反复重启且日志 `queries.active permission denied`，是恢复时漏了
    `chown -R 65534:65534`，见上方第 4 步）。
4. 手动采集一次成功，`collection_runs` 产生新记录。
5. Prometheus 历史可查：任选一个历史时间点的容量序列能返回旧样本。
6. 登录 UI 抽查总览/虚拟机/报表页面数据；确认旧库备份（`*.pre-restore-*`）妥善留存后再决定清理。

## 5. 红线与事故口径

- 禁止 `docker compose down -v`；禁止删除目标根目录、目标数据库、Prometheus 数据。
- 恢复类操作先确认目标路径与基线，完成后报告：动了什么、删了什么（及是否可从 `*.pre-restore-*` 挽回）。
- 测试机 `10.20.11.3` 仅用于本项目测试；`10.20.0.6` 默认只读。
- 升级链路失败的恢复不在本手册范围，见 `docs/troubleshooting.md` §6 与升级链路 worklog。
