# v0.5.2 升级后自动采集设计

## 背景

v0.5.2 可以完整迁移 SQLite 和 Prometheus 历史目录，但升级成功后不会立即采集。若恢复数据的最后样本早于当前 30 天窗口，概览会显示 `0 B`、趋势为空，`vm_latest.name` 中遗留的 VM ID 也不会刷新为 CloudTower 当前名称。

## 目标

平台升级主任务成功后自动执行一次采集。该采集必须作为独立任务出现在任务中心；失败只产生采集告警，不回滚或改写已经成功的平台升级任务。

## 架构

1. v0.5.1u2 web-api 编译 v0.5.2 manifest 时，在平台健康检查和任务状态同步之后加入 `post_upgrade.schedule_collection`。
2. runner v0.3.1 执行动作，在目标升级目录的父任务下原子写入 `post-upgrade-collection.json`。标记包含父升级 task ID、独立采集 task ID、目标版本、状态和时间。
3. v0.5.2 collector-worker 每 5 秒扫描目标升级目录。只有父任务状态为 `success`/`succeeded` 时才消费 `pending` 标记。
4. worker 使用现有 `CollectionService` 执行 `trigger=post_upgrade` 采集，并通过 `TaskService` 创建 `post-upgrade-collection-<upgrade_task_id>` 任务。
5. 采集完成后标记写入终态，避免 worker 或主机重启后重复采集。运行中断时任务转为失败并进入告警，不自动重复写业务数据。

## 行为约束

- 仅 v0.5.2 及以后声明 `post_upgrade.auto_collection=true` 的平台包触发；v0.5.1u2 和 runner 组件升级不触发。
- 平台主任务以自身健康检查为成功条件，自动采集失败不回滚平台。
- 手动采集行为保持不变；每日定时采集成功仍不进入任务中心。
- 自动采集任务标题为“升级后自动采集”，进度从 10% 更新到 100%，结果包含采集的集群数和 VM 数。
- 自动采集失败按普通采集失败处理，严重级别为 warning，并可由用户确认；升级任务仍保持 success。
- 标记写入、状态更新使用临时文件加 `os.replace`，禁止出现半写 JSON。

## 版本与打包边界

- v0.5.1u2：包含新执行计划编译能力，仍保持旧 project/network 和 runner v0.3.0 兼容。
- runner v0.3.1：包含新动作处理器和安全恢复声明。
- v0.5.2：manifest 声明自动采集，collector-worker 消费标记并写任务中心。

三个包必须作为 UPG-041 同一候选集构建和验证，不得混用 UPG-040 runner/v0.5.2 包。

## UPG-045 已发布桥包兼容补充

`v0.5.1u2` GitHub Release 资产已经发布，SHA256 为
`d5f277167445e7636ddfba16b4f780b40d59952467bb1c8e72d2469b43ee0a49`，不得重打或替换。
2026-07-15 在 `10.20.11.12` 使用该正式资产验证时，v0.5.2 主任务、runner handoff 和
post-cleanup 全部成功，但正式桥包生成的 execution plan 不包含
`post_upgrade.schedule_collection`。因此仅依赖旧编译器和 runner marker 会让
`post_upgrade.auto_collection=true` 在已发布链路中静默失效。

兼容规则：

1. 显式 runner marker 仍是首选路径，原协议和消费逻辑保持不变。
2. v0.5.2 collector-worker 每轮扫描前，检查业务时间最新的成功平台升级任务。
3. 只有任务 manifest 明确声明 `post_upgrade.auto_collection=true`、任务为真实平台包、
   且 marker 与 `post-upgrade-collection-<parent>` 任务都不存在时，worker 才原子补建
   schema 1 pending marker。
4. worker 随后使用既有消费逻辑执行一次采集；marker 或任务只要存在就禁止再次补建。
5. 候选排序只使用 `finished_at`、`uploaded_at`、`created_at`、`started_at`、`updated_at`
   和 task id，不使用文件 mtime。
6. 该兼容层只修改 v0.5.2，不改变已发布 v0.5.1u2 或 runner v0.3.1 资产。

此规则把“升级后自动采集”的最终保证放在目标版本 worker 中，避免目标功能是否生效
取决于不可再修改的来源版本编译器，同时保留显式 marker 的可恢复性和幂等性。

## 验收

10.20.11.3 从正常业务库执行：

```text
v0.5.1 + runner v0.3.0
-> v0.5.1u2
-> runner v0.3.1
-> v0.5.2
-> post-cleanup success
-> post-upgrade auto collection success
```

最终必须满足：主任务成功、清理任务成功、自动采集任务成功；概览存在当前容量；Prometheus 出现当前时间样本；`vm_latest.name` 不再全部等于 `vm_id`；旧目录和旧网络清理完成；业务库、Tower 凭据和 Prometheus 历史 block 保留。
