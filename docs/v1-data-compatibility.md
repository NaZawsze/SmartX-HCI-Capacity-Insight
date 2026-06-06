# v1 数据迁入 v2 兼容设计

更新时间：2026-06-06

## 1. 兼容目标

v2 不兼容 v1 的旧升级路径，但必须兼容 v1 现场数据迁入。推荐迁移方式是：全新部署 v2，然后通过数据迁移功能导入 v1 迁移包。

必须迁入：

- Tower 和集群配置。
- VM 最新元数据。
- 必要的 VM 卷结构化字段。
- 采集记录。
- Prometheus 历史容量指标。

不要求迁入：

- v1 升级任务历史。
- v1 临时运行目录。
- v1 完整 Tower 原始 payload。
- v1 旧 compose override。

## 2. v1 数据来源

v1 迁移包应包含：

```text
manifest.json
smartx-data/smartx.db
prometheus-data/<block_id>/meta.json
prometheus-data/<block_id>/chunks/*
prometheus-data/<block_id>/index
```

不应包含：

```text
.env
prometheus-data/wal
upgrades/
backups/
exports/
compose-runtime/
Tower 明文凭据
```

如果迁移包只有 SQLite，没有 Prometheus 历史 block，v2 必须提示“迁移包不完整”，因为趋势图、日增长、月增长和预测报表会缺少历史数据。

## 3. 导入模式

### merge

默认模式。用于把测试服务器或旧平台数据补充到当前系统。

规则：

- 当前系统已有 Tower 不覆盖。
- 当前系统已有集群不覆盖启用状态。
- 当前系统已有 VM 最新信息以当前系统为准。
- 缺失的 Tower、集群、VM、采集记录补入。
- Prometheus 已存在 block 跳过，缺失 block 补入。

### overwrite

危险模式。用于恢复备份或明确替换当前系统。

规则：

- 必须由用户显式选择。
- 开始前必须生成当前系统备份。
- 备份失败阻止导入。
- UI 必须提示会替换当前业务库和历史指标。

## 4. 导入前备份

导入前必须生成备份：

```text
/data/backups/import-before-YYYYMMDDHHMMSS.tar.gz
```

备份内容：

- `/data/smartx-capacity-insight-data/app/smartx.db`
- `/data/smartx-capacity-insight-data/prometheus` 下的历史 block

跳过内容：

- `/data/upgrades`
- `/data/backups`
- `/data/exports`
- `/data/compose-runtime`
- Prometheus `wal`

失败规则：

- 备份失败时导入任务直接失败。
- 不允许在没有备份的情况下继续写入。
- 任务中心显示备份失败原因和当前文件。

## 5. SQLite 兼容映射

v2 导入 v1 SQLite 时，按“需要什么迁什么”的原则处理。

| v1 数据 | v2 处理 |
| --- | --- |
| users | 可选择不导入，v2 使用当前系统用户 |
| towers | 导入 Tower 元数据，凭据按安全策略处理 |
| clusters | 导入集群元数据和启用状态，merge 模式不覆盖当前状态 |
| collection_runs | 导入采集历史摘要 |
| latest VM metadata | 导入 VM 最新元数据 |
| latest_vm_volumes.payload_json | 抽取必要字段，写入 v2 结构化卷表 |

Tower 凭据处理：

- v1 迁移包不应包含明文凭据。
- 如果 v1 数据中存在加密凭据，v2 不假设可以解密。
- 导入后需要用户重新验证 Tower 连接。

## 6. 旧 VM 卷 payload 处理

v1 曾在 `latest_vm_volumes.payload_json` 中保存 Tower 返回的较完整原始卷对象，体积很大。v2 不继续保存完整 payload。

v2 只抽取：

- VM 身份：`tower_id`、`cluster_id`、`vm_id`
- VM 最新名称
- 卷 ID
- 卷名称
- 卷大小
- 卷已用容量
- 存储策略名称
- 副本或 EC 信息
- 最近采集时间

丢弃：

- Tower 原始嵌套对象。
- 不用于页面、报表、导出、分析的 labels/path/lun/vm_disks 原始细节。
- 重复的 cluster/vm 大对象。

导入后验收：

- VM 页面能显示卷列表。
- 报表导出能读取 VM/卷必要字段。
- SQLite 文件不会因为完整 payload 继续膨胀。

## 7. Prometheus 历史指标兼容

Prometheus 是趋势和增长的核心数据源。

导入要求：

- 复制历史 block。
- 不复制 `wal`。
- 已存在 block 跳过。
- 复制后修正目录权限为 Prometheus 可写。

导入后检查：

```text
/-/ready
/api/v1/query?query=smartx_vm_storage_used_bytes
/api/v1/query_range?query=smartx_vm_storage_used_bytes
```

如果 Prometheus 无法启动或没有 series，导入任务应提示：

- 是否缺少历史 block。
- 是否目录权限错误。
- 是否 Prometheus 容器未重启。

报表和增长榜兼容规则：

- VM 趋势、日增长、集群预测报表必须能从 Prometheus 历史 block 恢复。
- 如果导入后 Prometheus 当前 instant 样本暂时为空，报表服务使用历史窗口中每条 series 的最后一个样本作为当前值回退，避免刚导入后增长榜和预测报表空白。
- 集群总容量同样优先使用当前 instant 样本；instant 为空时使用历史 `smartx_cluster_storage_total_bytes` 尾点回退。
- 月增长最快 VM 固定要求该 VM 样本跨度满 30 天；迁移包历史不足 30 天时，月增长榜为空属于符合口径的结果。

## 8. 导入后健康验证

导入完成后提供一键健康验证。

检查项：

- SQLite 中 Tower 数量。
- SQLite 中集群数量。
- SQLite 中 VM 数量。
- Prometheus VM series 数量。
- 最近 7 天 `query_range` 是否有点。
- Dashboard summary 是否有数据。
- VM trend 是否有数据。
- 日增长是否有数据。
- 月增长是否符合 30 天样本规则；不足 30 天时应明确显示为空而不是误判为导入失败。
- 集群预测报表是否有集群数据。

验证结果写入任务结果，前端展示摘要。

## 9. 失败处理

导入失败时：

- 保留导入前备份路径。
- 保留导入任务日志。
- 不自动删除上传包。
- 不自动回滚 Prometheus 历史 block，除非 overwrite 模式后续设计明确支持。

推荐提示：

```text
数据导入失败，当前系统导入前备份已保留：<backup_path>。请查看任务日志，必要时从备份人工恢复。
```
