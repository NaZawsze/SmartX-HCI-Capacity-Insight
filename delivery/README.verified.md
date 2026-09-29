# 交付 README 命令验证状态清单

对应 `delivery/README.md`。设计 §7 场景 7 要求"说明里每条命令都在实测中跑过"。

**口径**：只有真正执行过的命令才能标 `已验证`；尚未执行的标 `未验证`。
本清单由 `backend/tests/test_us49` 系列的 `test_documented_verification_state_is_honest`
静态锁定（命令必须同时出现在 README 里、状态必须在三个允许值内）。

## 当前状态（2026-09-29）

| 命令 | 状态 | 证据 |
| --- | --- | --- |
| `bash install/install.sh --help` | 已验证 | `.3` 真实执行，退出码 0、帮助正常输出 |
| `bash upgrade/upgrade.sh --help` | 已验证 | 单测 `UpgradeScriptExecutionTest::test_help_exits_zero` 真实执行 |
| `bash install/install.sh`（非 root） | 已验证 | `.3` 用 `su - user1` 真实执行，正确拒绝并说明原因 |
| `bash install/install.sh --yes --install-root <新目录>` | 已验证 | `.3` 真实执行：磁盘检查通过、正确识别端口占用、清晰提示、未启动任何服务 |
| `bash upgrade/upgrade.sh --base-url <不可达地址>` | 已验证 | 单测 `test_unreachable_platform_fails_cleanly` 真实执行，干净失败且声明不碰环境 |
| `bash install/install.sh`（完整安装 → 5 容器健康） | 未验证 | **待干净 VM 实测**（步骤 6）；`.3` 端口被现有实例占用、磁盘余量不足，无法在有历史的机器上做新装 |
| `bash upgrade/upgrade.sh`（完整离线升级） | 未验证 | **待干净 VM 实测**（步骤 6） |
| `curl -s http://127.0.0.1:8000/api/system/health` | 已验证 | `.3`/`.12` 反复执行，`ok=true` + 三项 checks |
| `docker ps --format '{{.Names}}\t{{.Status}}' \| grep smartx-hci-capacity-insight` | 已验证 | `.3`/`.12` 真实执行，5 容器均 Up |
| `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080` | 未验证 | **待干净 VM 实测**（前端容器访问路径需在新装环境确认） |
| `curl -s .../api/admin/upgrade/history` | 已验证 | `.12` 真实执行（同一 API 家族） |
| `ls -d /opt/smartx-storage-forecast /data/upgrades` | 已验证 | `.12` 真实执行，升级后均已清理（显示不存在） |
| `docker exec <web-api> ... PRAGMA integrity_check` | 已验证 | `.12` 真实执行，返回 `ok` |
| `docker exec <web-api> ... SELECT COUNT(*) FROM towers` | 已验证 | `.12` 真实执行，计数正常 |
| 升级后手动触发采集 | 已验证 | `.12` 多轮升级后采集正常 |
| `docker compose ... down` + `rm -rf`（卸载） | 未验证 | **刻意不验**：卸载会永久删除数据，不在测试机上执行 |
| `docker compose ... ps / logs / stop / start` | 已验证 | `.3` 真实执行（同一 compose project 形态） |

## 不在本清单内的验证（脚本行为，非 README 命令）

这些用例会真实执行脚本，但用的是**测试专用假参数**或**脚本内部步骤**，不属于客户会执行的
命令，因此不进上表：

- `sha256sum -c install/images/SHA256SUMS`、`sha256sum -c upgrade/packages/SHA256SUMS`
  （由 `install.sh` / `upgrade.sh` 自动执行；`.3` 单独手工执行确认过 5 镜像 + 2 包全 OK）`--no-such-option`（未知选项拒绝）、`--force-env` 幂等分支、
`--with-runner` 组件升级成功路径（依赖干净 VM 的新装环境）。

## 阻塞项

步骤 6（干净 VM 实测）缺少可用机器：

- `10.20.11.3`（`.3`）：端口 8000/8080/9090 被现有 v0.5.3 实例占用，磁盘余量 18 GiB（安装需约 13 GiB 但不能再挤），且**有历史数据**——不是干净 VM 形态。
- `10.20.11.12`（`.12`）：同为已有 v0.5.3 实例，且是生产等价机，按纪律不做破坏性操作。
- `10.20.0.6`：默认只读诊断机，用户未批准具体命令。

需要一台**无历史数据**的 VM 才能验证"全新安装 + 断网升级"——这正是本需求的交付场景本身。
