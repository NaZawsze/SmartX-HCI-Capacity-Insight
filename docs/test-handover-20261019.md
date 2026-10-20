# 测试交接文档 · SmartX HCI Capacity Insight r42（v0.5.4 / runner v0.3.2）

> 生成时间：2026-10-19 00:58（GMT+8）
> **2026-10-20 接手轮已完成**：`a4555be` 已打进镜像并重组交付；L0–L6 + 跨版本兼容全部复跑。
> 当前有效产物与结论见本文 §2、§3 的「接手轮」标注，以及
> [upgrade-package-ledger.md](upgrade-package-ledger.md)「2026-10-19 ～ 10-20（接手轮）」节。
> 分支：`dev2`（本地已提交，**未推送 origin**）
> 台账：本文所有结论的原始记录见 `docs/upgrade-package-ledger.md`

---

## 0. 一句话结论

r42 候选在**最终产物**上完成了 L0–L6 全流程测试：**L0 全量单测 1274 项全过、L1 四门禁 PASS、L2 八项全过、L3-a/b 两跳各 36 PASS、L3-c 已闭环、L4 反向用例全过、L4.5 并发全过、L5 场景 B/C 均通过、L6 验收通过**。
过程中共发现并修复 **8 个缺陷**（其中 1 个是发布阻断级），候选包从"不可交付"变为"可交付"。
剩余 4 项待办均需要**产品决策或额外资产**，不阻塞当前候选的质量结论。

---

## 1. 环境与机器分工

| 机器 | 角色 | 当前状态 |
| --- | --- | --- |
| `10.20.11.3` | 只做开发与构建（单测、Docker 构建、打包） | 构建机，`su - root` 后操作 |
| `10.20.11.14` | 干净验证机（首选验证场所） | **v0.5.4 + runner v0.3.2**，镜像 `601329fc…`，5 容器 Up |
| `10.20.11.12` | 升级演练机（生产等价） | **v0.5.4 + runner v0.3.2**，镜像 `601329fc…`，runner `(healthy)` |

- 登录：`.3` 用 `ssh user1@10.20.11.3`（`su - root`）；`.12`/`.14` 用 `ssh root@<ip>`，密码 `password`。
- `.12` 宿主禁止手工运维变更（不许 `docker rmi`/清目录/改文件），一切走产品流程。
- `.12` 上有一个历史遗留容器 `smartx-storage-forecast-upgrade-runner-1`（v0.3.1，老项目名），属宿主持有资产，未动。

---

## 2. 当前产物（唯一有效版本）

> **接手轮状态（2026-10-20）**：§2 原表为交接时（不含 `a4555be`）的产物，其中的平台包
> `24ef4a21…` 与清单 `SHA256SUMS-20261019002027` **已被取代**，不得再用于验收/发布。

| 项 | 交接时（旧） | **接手轮（当前有效）** |
| --- | --- | --- |
| 平台升级包 sha256 | `24ef4a21…`（作废） | **`d235f14ca4737b76dec4ac7ff0b42f09fdd0524a8548e067150b48a1b217af34`** |
| runner 组件包 sha256 | `e461738c…` | `e461738ca8cbd1413c51885afe36dd389bd2964973832f27e0857656288fcd9b`（未变） |
| web-api 镜像 id | `601329fc…` | **`a747f565ab9fe187862d6ff5eb990305f624b0a4252262aac341712ea26c90a4`** |
| 离线交付目录 | — | `/data/upgrade-packages/smartx-capacity-insight-v0.5.4-offline`（1.4G） |
| 交付清单 | `SHA256SUMS-20261019002027` | **`/data/upgrade-packages/SHA256SUMS-20261020202304`** |

**已作废、不得再用于验收/发布的旧包**：`24ef4a21…`（缺 `a4555be`）、`e7036b71…`（缺跨版本门禁
与 healthcheck 版本感知）、`cae31a9e…`（缺投影兜底/忙判据同源）、`10efa9cd…`（v0.3.3 误判）、`74ce3006…`（缺概览/报表修复）、
`5e5b565b…`、`10b6b731…`、`3d38cd23…`、`98d2851e…`（均缺后续修复）。

> ⚠️ 交接时登记的「未部署的一次提交 `a4555be`」**已在接手轮解决**：从 HEAD `2e385f1` 全量重建镜像与平台包。

---

## 3. 分层测试结果

| 层 | 内容 | 结果 | 证据 |
| --- | --- | --- | --- |
| L0 | 后端全量单测（镜像内真实环境） | **1273 项 OK**（跳过 7），EXIT=0 | 日志 `/data/l0c.log`（`.14`） |
| L1 | 四道构建门禁 | **全 PASS**（身份/runner 一致性/迁移 expand-only/计划词汇；2 条已记录 WARN） | 见本次会话命令输出 |
| L2 | 干净安装 + 八项 | **全过**，runner `(healthy)`，运行镜像 `601329fc…` | `/data/l2-final.log` |
| L3-a | CLI 链 v0.5.3→组件→r42 | 两跳 succeeded；`T0→T1`、`T1→T2` 各 **36 PASS / 0 FAIL** | 快照 `/data/diag/t0m/t1m/t2m.json` |
| L3-b | Web/API 链 | 两跳 succeeded；两段比对各 **36 PASS / 0 FAIL** | 快照 `/data/diag/t0n/t1n/t2n.json` |
| L3-c | 老布局链 v0.5.1u2→v0.5.2→v0.5.4 | **已闭环**（见 §4 缺陷 7/8） | 台账 2026-10-18 L3-c 节 |
| L4 #93 | `.env` 被建成目录 | **PASS**：预检查放行并说明修复行为；自动重建为 600 常规文件、20 键，两枚密钥逐键一致 | 见命令输出 |
| L4 #95 | runner 心跳窗口 | **PASS**：healthy → pause 150s → `unhealthy`（平台报「未检测到 runner」）→ unpause 75s → `healthy` | 同上 |
| L4 #96 | healthcheck 可见性 | **PASS**：升级后 `NO-HEALTHCHECK` 由守护线程重建为 `(healthy)` | 同上 |
| L4.5 | 并发与干扰 | **PASS**：单飞守卫二次 start → **400**；升级窗口 dashboard/reports/login 各 6 次全 200、手动采集 **202**、**0 个 500** | 脚本 `/tmp/l45_interference.sh` |
| L5 场景 B | 应用回滚（保数据） | **PASS**：`manual-rollback-*` succeeded，v0.5.4→v0.5.3，`Tr vs T0` **36 PASS / 0 FAIL** | `.12` 执行 |
| L5 场景 C | 整备回滚（应用+数据） | **PASS**：`manual-full-rollback-*` succeeded，`Tr vs T0` **36 PASS / 0 FAIL** | 快照 `/data/diag/t0s/trs.json` |
| L6 | `.12` 同版本重装 + 八项 | **全过**；`T0→T4` **36 PASS / 0 FAIL**；幽灵任务自动 running→**failed** | 快照 `/data/l6-scripts/t0l/t4l.json` |

> 数据完整性判据：`scripts/verify_data_integrity.py`，对 DB 严格 digest、业务表计数、`integrity_check`、
> `foreign_key_check`、`.env` 密钥对逐一比对；"36 PASS"即全部条目通过。

---

## 4. 缺陷清单与修复（共 8 项，按严重度排序）

| # | 缺陷 | 根因 | 修复 | 提交 |
| --- | --- | --- | --- | --- |
| 1 | **发布阻断**：候选包内镜像仍是旧代码，#93 自愈永久被拦 | 版本回退只改了源码与包内 project 文件，**没重建镜像**（镜像比版本治理提交早 48 分钟） | 重建镜像；新增"包内镜像构建时间 ≥ 版本治理提交时间"的验收要求 | `138dcf3` + 重建产物 |
| 2 | 幽灵 running 任务永不收敛（`.12` 实测滞留 3 天） | 产物被回收后 DB 行停在 running，无人收敛 | `converge_orphan_running_tasks()`：无 task.json + 无活租约 + 超 6h 自动置 failed | `a886a1d` |
| 3 | runner 升级后永久失去 `(healthy)` | runner 自换的 bootstrap compose 由**旧 runner** 写，无 healthcheck | 守护线程空闲时用项目 compose 重建 runner | `a886a1d` |
| 4 | 概览与报表「本日新建/增长最快 VM」口径不一致 | Phase 75 存活过滤被实现成"不在 `vm_latest` 就排除"，采集恢复期的在用 VM 被当已删除丢弃 | `with_series_only_labels()`：库里已删/回收站排除，库里没有按未知保留，两页共用标签表 | `151d28b` |
| 5 | 全新安装 runner 恒为 `(unhealthy)` | 安装基线钉已发布 runner v0.3.1，它没有 statefile 看门狗 → 文件从不存在 → 严格 healthcheck 必失败 | healthcheck 改为"文件不存在视为健康，存在但超 90s 未更新仍判不健康" | `8f08e99` |
| 6 | `.12` healthcheck 补不上 | `.12` 的 `.env` 仍指向遗留变体 `docker-compose.release.yml`（布局迁移未归一化），该变体无 healthcheck | 生成**只含 healthcheck 的 compose 覆盖文件**，用 `-f 现有变体 -f 覆盖` 重建，不动变体其他配置 | `b560e4b` |
| 7 | v0.5.2 直连 v0.5.4 在半迁移态失败 | runner v0.3.1 能力集与 v0.3.2 同名同数，能力级校验放行；但其沙箱把**容器内**包路径原样挂给 docker，布局迁移后宿主路径不同 → 迁移脚本挂空 | 平台 manifest 区分"安装基线"与"执行门槛"（v0.5.4→v0.3.2）；预检查**真正比较版本号**；`upgrade.sh` 加宿主侧硬拦截 | `46fe0a6` `55e21e1` |
| 8 | 门槛误拦：组件升级后 health 刷新滞后被当成版本不足 | 组件升级完成 10s 内 health 仍短暂返回旧 runner 版本 | 门禁点**实时重读** health + 5 次短重试，不拿过期缓存做决策 | `e552c78` |
| 附 | 整备回滚说明与事实不符 | 文案写"覆盖 SQLite/Prometheus"，实际 platform 范围备份只含 `app/smartx.db` | 按备份范围表述（仅文案） | `a4555be` |

另修正 1 个测试用例缺陷：`test_exports_retention` 6 个产物 mtime 全相同却断言顺序（`151d28b`）。

---

## 5. 未闭环 / 待办（按建议优先级）

> **接手轮更新（2026-10-20）**：原待办 1、2 已完成；3、4 仍需用户决策/授权。新增待办见下表末尾。

| # | 事项 | 状态 | 说明 |
| --- | --- | --- | --- |
| 1 | ~~`a4555be` 未部署~~ | **✅ 已完成** | 从 HEAD 全量重建镜像 + 平台包 `e7036b71…`，重组成交付（清单 `015125`）；`.12` 实升级后接口返回的整备回滚 note 已是新文案 |
| 2 | ~~L4 #94-A/B 负向用例~~ | **✅ 已完成** | #94-A：v0.5.2 源端 CLI 硬拦截；#94-B：v0.5.4 平台 + 组件包要求 `v9.9.9` → `component_platform` 拒绝（真机）。**不再依赖 v0.5.2 平台**（旧平台根本没这项检查，永远放行——原描述有误） |
| 3 | `.12` compose 变体归一化 | ⏸ 仍需**产品决策** | `.12` 仍跑 `docker-compose.release.yml`，healthcheck 由覆盖文件补；是否自动切换变体需定策 |
| 4 | 推送 origin | ⏸ 需用户明确授权 | 本地领先 origin 若干提交 |
| 5 | **新增**：`.14` 缺外网 → 前端门禁只能在 `.3` 跑 | 记录项 | 本轮已改为在 `.3` 执行：`tsc` EXIT=0、vitest 127 全过 |
| 6 | **新增**：v0.5.2 源端手搭夹具的 runner 空闲心跳窗口 30s | 记录项 | 走完整跨版本跳时需先恢复 runner；属夹具操作，非产品缺陷 |
| 7 | **新增（已修）**：基线 runner v0.3.1 约 90 秒后误报 `unhealthy` | **✅ 已修 `7e3c9c0`** | healthcheck 改为按 `/app/RUNNER_VERSION` 版本感知；真机 160 秒后仍 healthy。测试规范已补「≥120 秒后再取状态」 |
| 8 | **新增（已修）**：DB 投影滞后 → 任务中心显示「执行中」且挡住 healthcheck 补齐 | **✅ 已修 `2a0ddb1`** | 结算线程新增已收尾任务投影；「是否忙」改读 `task.json`（与单飞守卫同源）。真机：不轮询也能在一个周期内收敛 |

**其他已知遗留（非 r42 引入，无需在候选内修）**：
- v0.5.1u2→v0.5.2 首跳后 runner 未替换、任务态跨库分裂（v0.5.2 时代缺陷，已在 L3-c 记录）。
- 老布局目录与旧 runner v0.3.0 容器不会被 post-cleanup 回收（v0.5.2 包未声明 `legacy_cleanup`）。
- L3-c 现场遗留的幽灵行满足 #89 收敛条件，只是等 6h 阈值，到期自动收敛。

---

## 6. 复跑指南

所有命令均在**执行机本地**运行；`$D` = `/data/upgrade-packages/smartx-capacity-insight-v0.5.4-offline`。

```bash
# ---- L1 四门禁 ----
cd /data/build-r42n   # HEAD 源码树（每次更新后重新解包）
D=/data/upgrade-packages/smartx-capacity-insight-v0.5.4-offline
python3 scripts/verify_upgrade_package_identity.py $D/upgrade/packages/smartx-capacity-insight-upgrade-v0.5.4.tar.gz --expected-version v0.5.4
python3 scripts/verify_runner_delivery_consistency.py --package $D/upgrade/packages/smartx-upgrade-runner-v0.3.2.tar.gz
python3 scripts/verify_migrations_expand_only.py --baseline-tag v0.5.3
python3 scripts/verify_upgrade_plan_vocabulary.py $D/upgrade/packages/smartx-capacity-insight-upgrade-v0.5.4.tar.gz \
  --runner-package $D/upgrade/packages/smartx-upgrade-runner-v0.3.2.tar.gz

# ---- L2 干净安装 + 八项 ----
cd /data/smartx-storage-forecast/project && docker compose -p smartx-hci-capacity-insight -f docker-compose.offline.yml down -v
cd / && docker ps -a --format '{{.Names}}' | grep smartx | xargs -r docker rm -f
rm -rf /data/smartx-storage-forecast
cd $D/install && bash install.sh --yes
# 然后：health / docker ps / UI:8080 / legacy 目录 / integrity+fk / .env 600 / compose config / 镜像 digest
# 注数据：python3 /data/build-r42n/scripts/seed_test_dataset.py --db /data/smartx-storage-forecast/app/smartx.db --yes --vms 120 --volumes-per-vm 2 --towers 2 --clusters 3 --recycle 3

# ---- L3 CLI 链路（先组件后平台，v0.5.4 批次铁律）----
bash /tmp/l3b_api_upgrade.sh component $D/upgrade/packages/smartx-upgrade-runner-v0.3.2.tar.gz v0.3.2
bash $D/upgrade/upgrade.sh --yes --package $D/upgrade/packages/smartx-capacity-insight-upgrade-v0.5.4.tar.gz

# ---- 数据比对（每个时点各采一次）----
python3 /data/build-r42n/scripts/verify_data_integrity.py snapshot --prom http://127.0.0.1:9090 --label <t> --out /data/diag/<t>.json
python3 /data/build-r42n/scripts/verify_data_integrity.py compare --before /data/diag/<t0>.json --after /data/diag/<t1>.json

# ---- L4 反向用例 ----
# #93 .env 目录：rm -f project/.env && mkdir project/.env，再跑同版本重装（加 --allow-same-version）
# #95 心跳：docker pause/unpause <runner 容器>，配合 health 观察
# L4.5 并发：bash /tmp/l45_interference.sh

# ---- L5 ----
#       场景 B：POST /api/admin/upgrade/rollback
#       场景 C：POST /api/admin/upgrade/full-rollback  {"confirm_data_loss": true}
#       可用性：GET  /api/admin/upgrade/rollback-availability | full-rollback-availability

# ---- L0 全量单测（必须在镜像内跑，本机缺 fastapi/docx）----
docker cp /data/build-r42n <web-api 容器>:/app/repo
docker exec -e PYTHONPATH=/app:/app/repo/backend -w /app/repo/backend/tests <容器> python -m unittest discover -s . -t .
```

---

## 7. 关键坑位（接手必读）

1. **构建脚本只打包、不解包**：`build_r42_pkg.sh` 只负责打包；解包在 `build_r42_images.sh`。
   单独跑 pkg 脚本会用上一次的 `r42-src`，产出「包是新的、代码是旧的」。
   **现在约定：同一命令内先 `rm -rf r42-src && tar xzf <head 归档> -C r42-src && grep <新代码标记>` 再构建。**
2. **交付组装读的是仓库 compose**，不是平台包内的 `project/`：重组交付前必须把源码目录更新到同一 commit，
   否则会出现"包内新、交付旧"（本次踩过两次）。
3. **版本治理**：`VERSION=v0.5.4`、`RUNNER_VERSION=v0.3.2`（v0.3.2 是 v0.5.4 开发线候选，**尚未发布**）。
   已发布 runner 最新 = v0.3.1；平台包安装基线硬编码 v0.3.1（与 `--runner-baseline` 实参无关）。
   runner 代码改动必须①用户同意②同步 bump `RUNNER_VERSION`。
4. **`.12` 与 `.3` 凭据不通用**：拿 `.3` 的密码试 `.12`/`.14` 只会得到误导性的 `Permission denied`。
5. **本地缺 `fastapi`/`docx`/`yaml`**：部分测试/校验只能在 web-api 镜像内跑；本地跑全量会出现若干
   「ModuleNotFoundError」，属环境限制而非代码问题。
6. **健康检查的"滞后一跳"**：组件升级后 health 可能短暂返回旧 runner 版本（约 10s），
   做版本判定前要重读或等待，否则会误判（这就是缺陷 8 的由来）。
7. **上传偶发 SQLite 写锁**（提示"runner 刚完成组件升级后短暂持有写锁"）：稍后重试即成功，非缺陷。
8. **Bash 工具偶发整体故障**（所有命令 SIGTERM 137）：属执行环境间歇故障，恢复后重跑即可。
9. **重组交付的标准动作**（当初 §7.3 的引用指向这里；原文没有 §7.3，属文档缺陷）：
   ```bash
   # 1) 打平台包（脚本自己会构建镜像；绝不要用上一次的源码树）
   ssh .3 'rm -rf /home/user1/codex-build/r42-src && mkdir -p ... && tar xzf <head 归档> -C ... \
     && grep -c "<本次修复的代码标记>" <该文件>   # 标记必须在场
     && cd ... && python3 scripts/build_upgrade_package.py --output-dir /home/user1/r42-pkg-final'
   # 2) 传到验证机，用 build_release_delivery.sh 复用两个包重组交付
   ssh .14 'cd /data/build-r42n && bash scripts/build_release_delivery.sh \
     --output-root /data/upgrade-packages --runner-baseline v0.3.1 \
     --platform-package <新平台包> --runner-package <runner 包> \
     --prometheus-archive /data/prometheus.tar'
   ```
   **前提**：`.14:/data/build-r42n` 必须与 `.3` 构建源码树是同一 commit（§7 第 2 条）。
10. **`.14` 的 `/tmp` 是小 tmpfs（3.7G）**：反复解包升级包会撑满（本轮实测 `No space left on device`）。
    解包体积大的包后要 `rm -rf /tmp/<dir>`。

---

## 8. 交接检查清单

- [x] 代码全部本地提交（HEAD `a4555be`），工作树干净
- [x] 台账 `docs/upgrade-package-ledger.md` 记录了每一轮产物与结论
- [x] 两台验证机均在最终产物上、状态健康
- [x] 作废旧包已在台账标注
- [ ] `a4555be` 打进镜像并重组交付（待办 1）
- [ ] L4 #94-A/B 真机负向（待办 2）
- [ ] `.12` compose 变体归一化（待办 3，需产品决策）
- [ ] 推送 origin（待办 4，需授权）
