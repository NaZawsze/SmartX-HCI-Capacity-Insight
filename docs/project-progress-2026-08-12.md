# 项目进度总结（2026-08-12）

## 当前结论

`SmartX HCI Capacity Insight` 的 v0.5.2 升级闭环已经完成验证。正式支持的升级链路是：

```text
v0.5.1 + runner v0.3.0
  -> v0.5.1u2
  -> runner v0.3.1
  -> v0.5.2
```

2026-07-22 已在 `10.20.11.12` 使用正常的 v0.5.1 离线包基线和正常升级 API 完成该链路，不依赖临时 Docker Compose 覆盖或针对该主机的特殊处理。

最终运行状态：

- 平台版本：`v0.5.2`
- 活动 runner 版本：`v0.3.1`
- Docker Compose project：`smartx-hci-capacity-insight`
- Docker network：`smartx-hci-capacity-insight-net`，网段 `10.249.251.0/24`
- 服务：`web-api`、`collector-worker`、`frontend`、`prometheus`、`upgrade-runner` 均为运行状态
- 健康检查：目录、SQLite、Prometheus 均通过
- 主升级、runner 组件升级、升级后清理、升级后自动采集任务均为成功

## 已交付能力

- 离线平台升级、预检查、任务状态、升级历史、升级包删除和升级前备份。
- runner 独立组件升级，runner 的活动版本由 heartbeat 或实际运行容器识别，不再使用 web-api 内置基线版本冒充当前 runner 版本。
- v0.5.2 的 Compose project/network 迁移：从旧 `smartx-storage-forecast` 和 `10.249.249.0/24` 切换到新 project/network，并清理旧容器、旧网络和旧程序目录。
- SQLite、Prometheus、`.env` 及 Tower 加密凭据的成对迁移保护；目标 `.env` 权限要求为 `0600`。
- 升级完成后自动触发一次采集，作为独立任务显示；自动采集失败不改写平台升级成功状态。
- Prometheus 作为平台 Compose 服务随 v0.5.2 重建，不单独拆成组件升级包。
- 升级任务历史排序、verification 包身份读取和任务投影的稳定化。
- 报表导出改为全量虚拟机，并修复部分虚拟机名称刷新问题。

## 当前可用升级包

| 阶段 | 包路径（10.20.11.3） | SHA256 |
| --- | --- | --- |
| v0.5.1 -> v0.5.1u2 | `/home/user1/codex-build/packages-upg036-runner-start-conflict/01-v0.5.1u2-runner-start-conflict/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `d5f277167445e7636ddfba16b4f780b40d59952467bb1c8e72d2469b43ee0a49` |
| runner v0.3.0 -> v0.3.1 | `/home/user1/codex-build/packages-upg032-historyfix/02-runner-v0.3.1-historyfix/smartx-upgrade-runner-v0.3.1.tar.gz` | `d10e15cf7b516d172ebe2f1bc37621f9cf32d8ab3abd548f808ae5c5de151d2c` |
| v0.5.1u2 -> v0.5.2 | `/home/user1/codex-build/packages-upg048-webapi-env-permission-fix8/03-v0.5.2-upg048-fix8/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `692aca8b58ad8199c43c02a3771fa4fd7a62f1d7bbf4f198af4bd2e4b2c67733` |

包与 SHA 的完整谱系、已废弃包及原因见 [upgrade-package-ledger.md](/Users/nazawsze/Documents/Codex/worktrees/devv2/docs/upgrade-package-ledger.md)。

## 验证范围与限制

- `10.20.11.12` 的最终验证基线业务库为空：`towers=0`、`clusters=0`、`vm_latest=0`。因此本次证明了升级、目录迁移、数据文件完整性、任务闭环和自动采集流程；不能把 0 台虚拟机的结果误判为采集或迁移故障。
- 先前在 `10.20.11.3` 已使用有业务数据、Tower 凭据和 Prometheus 历史的基线完成链路验证，验证了凭据迁移、自动采集、真实 VM 名称刷新和历史数据保留。
- `.12` 仍有一条历史遗留的 `running` 任务记录，来自本轮验证之前；不属于本次链路创建的任务。
- Docker Compose 容器标签中的 `config_files` 可能保留迁移前的历史路径；实际运行时环境变量、挂载、project、network 和目标目录均已切换到新目录。这是标签元数据清洁度问题，不影响运行。

## 关键目录约定

v0.5.2 统一使用以下根目录，不再以 `/opt/smartx-storage-forecast` 作为运行目录：

```text
/data/smartx-storage-forecast/
├── project/
├── app/
├── prometheus/
├── upgrades/
├── backups/
├── exports/
└── compose-runtime/
```

对应的 target `.env` 是：
`/data/smartx-storage-forecast/project/.env`。

## 计划文档位置

- 总体升级计划：[v0.5.0-to-v0.5.2-upgrade-plan.md](/Users/nazawsze/Documents/Codex/worktrees/devv2/docs/v0.5.0-to-v0.5.2-upgrade-plan.md)
- v0.5.1u2 -> v0.5.2 问题修复计划：[v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md](/Users/nazawsze/Documents/Codex/worktrees/devv2/docs/v0.5.1u2-to-v0.5.2-upgrade-plan-issue.md)
- 升级后自动采集实施计划：[2026-07-10-post-upgrade-auto-collection.md](/Users/nazawsze/Documents/Codex/worktrees/devv2/docs/superpowers/plans/2026-07-10-post-upgrade-auto-collection.md)
- verification 与任务历史修复计划：[2026-07-15-upg044-verification-history.md](/Users/nazawsze/Documents/Codex/worktrees/devv2/docs/superpowers/plans/2026-07-15-upg044-verification-history.md)
- 已发布 v0.5.1u2 兼容计划：[2026-07-15-upg045-released-u2-auto-collection-compatibility.md](/Users/nazawsze/Documents/Codex/worktrees/devv2/docs/superpowers/plans/2026-07-15-upg045-released-u2-auto-collection-compatibility.md)
- 根任务摘要：[task_plan.md](/Users/nazawsze/Documents/Codex/worktrees/devv2/task_plan.md)

## 功能实现与设计文档位置

- 升级链路详细执行记录：[v0.5.1-to-v0.5.2-upgrade-chain-worklog.md](/Users/nazawsze/Documents/Codex/worktrees/devv2/docs/v0.5.1-to-v0.5.2-upgrade-chain-worklog.md)
- 升级链路任务与发现归档：[v0.5.1-to-v0.5.2-upgrade-chain-task-findings.md](/Users/nazawsze/Documents/Codex/worktrees/devv2/docs/v0.5.1-to-v0.5.2-upgrade-chain-task-findings.md)
- 升级问题台账：[upgrade-issues.md](/Users/nazawsze/Documents/Codex/worktrees/devv2/docs/upgrade-issues.md)
- v0.5.1u2 -> v0.5.2 专项问题台账：[v0.5.1u2-to-v0.5.2-upgrade-issues.md](/Users/nazawsze/Documents/Codex/worktrees/devv2/docs/v0.5.1u2-to-v0.5.2-upgrade-issues.md)
- 升级 runner 生命周期与协议：[upgrade-runner-lifecycle.md](/Users/nazawsze/Documents/Codex/worktrees/devv2/docs/upgrade-runner-lifecycle.md)
- 升级后自动采集设计：[2026-07-10-post-upgrade-auto-collection-design.md](/Users/nazawsze/Documents/Codex/worktrees/devv2/docs/superpowers/specs/2026-07-10-post-upgrade-auto-collection-design.md)
- v2 架构：[architecture-v2.md](/Users/nazawsze/Documents/Codex/worktrees/devv2/docs/architecture-v2.md)
- 功能模块说明：[functional-modules.md](/Users/nazawsze/Documents/Codex/worktrees/devv2/docs/functional-modules.md)
- 接口契约：[v2-api-contracts.md](/Users/nazawsze/Documents/Codex/worktrees/devv2/docs/v2-api-contracts.md)
- 发布变更记录：[CHANGELOG.md](/Users/nazawsze/Documents/Codex/worktrees/devv2/docs/releases/CHANGELOG.md)

## 后续建议

1. 发布或现场使用前，始终从完整的 v0.5.1 正常业务基线执行三段升级，不用旧残留目录或手工 Compose 覆盖来模拟基线。
2. 每次构建升级包后，在台账记录包路径、SHA256、来源兼容版本、runner 需求和验证结论；废弃包必须保留原因并明确标记不可使用。
3. 对有 Tower 凭据的真实业务库，继续将 `.env`、SQLite 和 Prometheus 作为同一份迁移基线验证，避免只验证空库升级。
