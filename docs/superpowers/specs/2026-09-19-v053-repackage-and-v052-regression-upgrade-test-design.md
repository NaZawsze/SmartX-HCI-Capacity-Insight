# v0.5.3 第二次重打包与 10.20.11.3 回归 v0.5.2 升级测试设计

日期：2026-09-19 ｜ 状态：实施中 ｜ 关联 task_plan Phase 49 第 22 项

## 背景

v0.5.3 交付包 ef10a7c8（基于 dev2 a64a897）不含其后合入的四批改动：报表图表窗口收紧（49-18，30035ed）、VM 页千台规模加固（49-19，9cabbd3 等）、web-api 采集新鲜度探针（49-20，2f591d9）、预测区间（49-21，34d3eb0），以及 UPG-049 残留卫生的 Prometheus 扫描守卫（beb36d5）。用户指令：重建 v0.5.3 升级包 → 10.20.11.3 回归 v0.5.2 基线 → 走正规升级 API 完成升级测试。

## 与上一轮（.12 演练，progress.md 7169）的差异

（2026-09-20 用户决策：**升级测试改在 10.20.11.12 进行，.3 打包机保持现状不动**——.3 当前已是本轮代码 + v0.5.3 目标态，无需回归。以下差异表按 .12 本轮口径修正。）

| 维度 | 上一轮（.12，ef10a7c8） | 本轮（.12，新包） |
| --- | --- | --- |
| 基线 .env | 模板密钥（演练环境自洽） | 模板密钥，逐字节保留（与 .12 库中凭据配对） |
| 基线 compose 来源 | v0.5.2 包内 compose + 路径重写 | **.12 线上 compose（已为目标路径形态）+ 镜像默认 tag 换回 v0.5.2**（考据：dab2e0f v0.5.2 发布以来 docker-compose.yml 仅默认 tag 变化） |
| UPG-050 | .12 衰减过快 | .12 更凶（急性期全量重建后 2 分钟内也衰减）；演练前记录基线、全程监控 checks.directories，出现衰减先留证再 `bind-mount-recover.sh` 恢复，升级任务判定不受环境衰减干扰 |
| 升级后自动采集 | failed（Tower 10.20.0.6 不可达，已知限制） | 同样 expected failed |

## 口径

### 打包

- 构建提交：dev2 `49739c5`（含 CHANGELOG 更新），`git archive` 打包传输解压至 .3 `/root/build-v053-rebuild2/`（.3 项目目录非 git 检出，不用 push）。
- 构建：`python3 scripts/build_upgrade_package.py --output-dir /data/upgrade-packages/v053-rebuild2-20260919`（三件套镜像全部重建——本轮前端源码有变化，frontend 不再缓存命中）。
- 包门禁：
  1. `sha256sum -c` 通过，记录包 SHA256；
  2. `scripts/verify_upgrade_package_identity.py` 身份核验；
  3. manifest 检查：`source_compatibility` 含 v0.5.2，含 `environment_transitions`/`directory_transition`/`legacy_cleanup`（保持 v0.5.1u2 直升能力），`minimum_runner_version` ≤ v0.3.1；
  4. 包内容检查：不含 runner/Prometheus 镜像 tar，不含 .env/SQLite/凭据等敏感文件，images/ 三件套 tar 齐全。

### .12 回归 v0.5.2 基线

- 前置记录（回归前基线留档）：health JSON、五容器镜像 ID、DB 计数（users/towers/clusters/vm_latest/vm_volumes/tasks）、Prometheus series 数、.env SHA256 与 0600 权限。
- 动作：项目目录整体 tar 备份到 /root（可回滚）；`docker compose stop` 全停（保网络）→ compose 三处默认 tag sed 回 v0.5.2 → `docker compose up -d --force-recreate` 一次性全量起。
- 数据边界：/data/smartx-storage-forecast/{app,prometheus,upgrades,backups,exports} 全程不动；.env 不改写。
- 基线验收：health `{"ok":true,"version":"v0.5.2","runner_version":"v0.3.1",checks.directories/database/prometheus=true}`；五容器镜像 tag 正确（三件套 v0.5.2 + runner v0.3.1 + prometheus v2.55.1）；DB 计数与回归前一致；Prometheus API 200 且 series 数不减。

### 升级测试（正规流程）

- 登录 web-api → 上传新包 → 预检查 → 启动升级 → 轮询任务至 succeeded → post-cleanup succeeded。
- 验收（§10 最低证据 + 本轮特性）：
  1. health.ok=true，platform=v0.5.3，runner=v0.3.1，checks 三项 true；
  2. 主任务、post-cleanup 均 success；
  3. 五容器镜像 tag：三件套 v0.5.3（**新镜像 ID ≠ 基线 v0.5.2 ID**）、runner v0.3.1 不变；
  4. project=smartx-hci-capacity-insight / network=smartx-hci-capacity-insight-net（10.249.251.0/24）保持；
  5. SQLite 计数不减、.env SHA256 升级前后逐字节一致且 0600；
  6. Prometheus 历史 block 保留（series 数不减）；
  7. 升级后自动采集执行（结果 expected failed：Tower 不可达，记录留档）；
  8. 新特性在升级后环境生效：探针线程日志/告警在位、`/api/reports/latest` 含 band 字段。
- 升级后如出现 UPG-050 挂载衰减迹象（checks.directories=false）：先记录现场证据，再全量 force-recreate 恢复，写入 progress。

## 回滚

- 升级失败：包/任务现场留档（task ID、错误、SHA），.3 保持失败现场报告用户，不静默重试。
- 基线备份：/root/project-backup-<ts>.tar.gz 可整体恢复 project 文件；数据目录全程未动，无需数据回滚。
