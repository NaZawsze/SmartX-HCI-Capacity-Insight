# v0.5.4 发布验证记录（内部）

> **内部文档**：只给研发/交付负责人看。客户看的是 `docs/releases/CHANGELOG.md`。
> 这里放 CHANGELOG 里刻意不写的技术细节：包 SHA、任务 ID、验证机器、门禁明细、数据比对。

- 状态：**候选，未发布**（等用户明确「发布」指令）
- 候选对：平台包 `d235f14c…` + runner 组件包 `e461738c…`（源码 `81a70e2`）
- 组装：2026-10-21，`.3:/home/user1/r42-delivery-final/smartx-capacity-insight-v0.5.4-offline`

## 1. 包身份

| 产物 | SHA256 | 大小 |
| --- | --- | --- |
| 平台包 `smartx-capacity-insight-upgrade-v0.5.4.tar.gz` | `d235f14ca4737b76dec4ac7ff0b42f09fdd0524a8548e067150b48a1b217af34` | 237.1 MiB |
| runner 组件包 `smartx-upgrade-runner-v0.3.2.tar.gz` | `e461738ca8cbd1413c51885afe36dd389bd2964973832f27e0857656288fcd9b` | 77.5 MiB |
| web-api 镜像 | `a747f565ab9fe187862d6ff5eb990305f624b0a4252262aac341712ea26c90a4` | — |
| 交付目录 README | `f29ab5026b8d03a60e0c05d921b12fde` | 21 KB |

安装 compose 的 runner 基线 = **已发布 v0.3.1**；runner v0.3.2 由客户第 1 步组件升级装上。

**已作废候选包**：r34/r35、r36–r42 系列此前各轮候选（最终包出自 r42-final2 构建树，取源码 `81a70e2`）。
所有作废包的验收结论不适用于本发布物。

## 2. 构建与门禁（`.3`，L1）

| 门禁 | 结果 |
| --- | --- |
| G1 镜像身份 | PASS |
| G2 runner 交付一致性（源码与镜像 `actions.py` 指纹逐字节一致） | PASS |
| G3 迁移 expand-only | PASS |
| G4 计划动作词汇冻结 | PASS |
| 对外发布文档脱敏 | PASS |

单测基线：后端全量（容器内）`FAILED (failures=1)`——唯一失败为既有环境限制（需真实 docker socket 的
runner 执行用例），非本包回归；前端 `tsc` 0 错误 + vitest 全过。

## 3. `.12` 验收（生产等价机）

- 全新安装：`INSTALL_EXIT=0`；5 容器 Up、runner `(healthy)`、~210 秒后仍 healthy、restarts=0；
  八项全过（health ok / 5 容器 / UI 200 / legacy 全 ABSENT / `integrity ok` + `fk 0` /
  `.env` 600 常规文件 / compose OK / 镜像 `a747f565…`）
- 数据完整性：注标准数据集（120 VM / 240 卷 / 2 塔 / 3 集群 / 3 回收站）→ `r43-t0s` **36 PASS / 0 FAIL**；
  组件升级（API）succeeded → 平台升级（CLI 同版本重装）成功 → `t0s → t1` **36 PASS / 0 FAIL**
- 复杂场景：`#95` 心跳窗口（pause → `unhealthy` → unpause → `healthy`）；
  场景 B 手动回滚 `manual-rollback-*` → `rolled_back`、数据 36 PASS；
  场景 C 整备回滚 → `succeeded`、数据 36 PASS；
  `#93` `.env` 被建成目录（换交付 runner 后 PASS：`.env` 恢复 600/17 键、两枚密钥逐键一致）

## 4. `.14` 交付物冒烟 + 完整升级链（2026-10-21 晚，新交付目录）

1. 全新安装 `EXIT=0` → 8 项全过（`migrations=0` 属全新库口径）
2. 注入 120 VM / 240 卷
3. **组件升级 v0.3.1→v0.3.2**：task `upgrade-4e75c3a11cb71dfb` succeeded（预检查 9 项全过；
   runner 探针 `docker_host_path(script)`=1、`ensure_env_file`=1）
4. **平台升级 v0.5.4**：task `upgrade-b9233ab5f27c8c1b` succeeded（预检查 10 项全过、
   `runner_actions: 9 个动作 v0.3.2 全部支持`、含「执行数据库迁移脚本」成功）
5. 数据 `t0 vs t1`：**36 PASS / 0 FAIL / 4 WARN**（WARN = 本轮跳过真实采集故无 Prometheus 样本）
6. 终态：health `v0.5.4/v0.3.2` 三 checks、`schema_migrations` 4 条、数据 `2/3/120/240` 逐位不变、UI 200

### `.14` 环境故障（非产品缺陷）

该机在历史硬盘故障后残留两处环境问题，首次冒烟因此失败，均已定位并修复：

1. Docker overlay2 **层文件损坏**：交付 tar 内 `/bin/prometheus` SHA `8d2d4281…` 正确，
   容器内解出 `fae00478…` → `exit 139` 段错误；重置 `/var/lib/docker` 后恢复。
2. **孤儿桥接接口**残留导致 `10.249.251.0/24` 出现三条路由（两条 `linkdown`）→ 宿主访问 8000 被 reset，
   而容器内 health 正常；`ip link delete` 后恢复。

**教训**：验证前应先做「镜像内二进制 SHA 抽检 + `ip route` 重复网段检查」，否则会误判成产品缺陷。

## 5. 跨版本与兼容矩阵

- 跨版本 X1–X7：v0.5.1u2 / v0.5.2 / v0.5.3 各源端、负向拦截（源版本门禁 + 包内 remediation 透传）、
  `component_platform` 真机拒绝；`v0.5.1u2 → v0.5.2 → 组件 → v0.5.4` 多跳链闭环
- 兼容矩阵 M1–M7：M2/M3/M6/M7 真机通过；M1 走已发布路径回归；M4/M5 presence 兼容在对应轮次覆盖；
  M3-08 / M3-10 按用户 2026-09-28 口径 **N/A**（runner-first 非受支持链路）
