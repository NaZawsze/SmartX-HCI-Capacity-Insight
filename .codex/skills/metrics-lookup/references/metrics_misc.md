# 其他杂项指标（cluster/application/event/access/storage 等）

## Labels 说明

| label | 内容描述 |
|---|---|
| `_tenant_id` | 租户或采集范围 ID，跨租户聚合时需要保留。 |
| `_cluster_uuid` | CloudTower 集群 UUID，集群重命名后保持稳定。 |
| `_cluster` | 集群标识或集群名称，具体格式由采集器决定。 |
| `_host` | 主机内部 UUID。 |
| `hostname` | 主机名称。 |
| `_nic` | 网卡名称。 |
| `instance` | 采集目标地址，通常为 host:port 或 URL。 |
| `job` | Prometheus/VictoriaMetrics 抓取任务名。 |
| `_application` | 高级监控应用标识。 |
| `_brick_name` | 机箱或 brick 名称。 |
| `_power_id` | 电源模块标识。 |
| `host_num` | 采集器暴露的原始 label，含义需结合具体指标上下文确认。 |
| `master_num` | 采集器暴露的原始 label，含义需结合具体指标上下文确认。 |
| `master_num_expected` | 采集器暴露的原始 label，含义需结合具体指标上下文确认。 |

## Metrics 说明

| metric_name | 中文说明 | 适用版本 | labels 描述 |
|---|---|---|---|
| access_nic_fail_after_reset | 主机接入网口出现异常，重置后仍未恢复 |  |  |
| access_nic_isolate | 主机接入网口存在异常且已被隔离 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_nic`、`instance`、`job` |
| access_nic_recover_after_reset | 主机接入网口出现异常，重置后恢复正常 |  |  |
| application_clock_offset | 高级监控时钟偏移 |  |  |
| application_cpu_usage_percent | 高级监控 CPU 使用率 |  |  |
| application_disk_usage_percent | 高级监控磁盘使用率 |  |  |
| application_memory_usage_percent | 高级监控内存使用率 |  |  |
| brick_power_is_on | 机箱电源状态 |  | `_tenant_id`、`_cluster_uuid`、`instance`、`job`、`_brick_name`、`_power_id` |
| cluster_cpu_total_hz | 集群 CPU 总频率 |  | `_tenant_id`、`_cluster_uuid`、`_cluster`、`instance`、`job` |
| cluster_cpu_usage_percent | 集群 CPU 使用率 |  | `_tenant_id`、`_cluster_uuid`、`_cluster`、`instance`、`job` |
| cluster_cpu_used_hz | 集群 CPU 已用频率 |  | `_tenant_id`、`_cluster_uuid`、`_cluster`、`instance`、`job` |
| cluster_hdd_overall_size_bytes | 集群 HDD 磁盘总容量 |  | `_tenant_id`、`_cluster_uuid`、`_cluster`、`instance`、`job` |
| cluster_hp_memory_usage_percent | 集群已用大页内存百分比 |  | `_tenant_id`、`_cluster_uuid`、`_cluster`、`instance`、`job` |
| cluster_hp_memory_used_bytes | 集群已用大页内存量 |  | `_tenant_id`、`_cluster_uuid`、`_cluster`、`instance`、`job` |
| cluster_master_redundancy | 集群主节点数量 |  | `_tenant_id`、`_cluster_uuid`、`_cluster`、`instance`、`job`、`host_num`、`master_num`、`master_num_expected` |
| cluster_memory_total_bytes | 集群内存总量 |  | `_tenant_id`、`_cluster_uuid`、`_cluster`、`instance`、`job` |
| cluster_memory_usage_percent | 集群已用内存百分比 |  | `_tenant_id`、`_cluster_uuid`、`_cluster`、`instance`、`job` |
| cluster_memory_used_bytes | 集群已用内存量 |  | `_tenant_id`、`_cluster_uuid`、`_cluster`、`instance`、`job` |
| cluster_non_hp_memory_usage_percent | 集群已用非大页内存百分比 |  | `_tenant_id`、`_cluster_uuid`、`_cluster`、`instance`、`job` |
| cluster_non_hp_memory_used_bytes | 集群已用非大页内存量 |  | `_tenant_id`、`_cluster_uuid`、`_cluster`、`instance`、`job` |
| cluster_ssd_overall_size_bytes |  |  | `_tenant_id`、`_cluster_uuid`、`_cluster`、`instance`、`job` |
| dolphin_application_health | 高级监控应用是否健康 |  | `_tenant_id`、`_cluster_uuid`、`instance`、`job`、`_application` |
| event_disk_add | 磁盘插入事件 |  |  |
| event_disk_remove | 磁盘拔出事件 |  |  |
| event_slot_disk_add | 有槽位的磁盘插入事件 |  |  |
| event_slot_disk_remove | 有槽位的磁盘拔出事件 |  |  |
| ipmi_account_is_valid | IPMI 账户有效性 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job` |
| node_isolate_status | 主机可能具有较高的延迟或丢包率，甚至无法收发 |  | `_tenant_id`、`_cluster_uuid`、`hostname`、`instance`、`job` |
| os_node_isolate_status | 主机可能具有较高的延迟或丢包率，甚至无法收发 |  | `_tenant_id`、`_cluster_uuid`、`hostname`、`instance`、`job` |
| smtp_config_is_valid | smtp 账户有效性（1：有效，0：无效） |  | `_tenant_id`、`_cluster_uuid`、`instance`、`job` |
| storage_nic_fail_after_reset | 主机存储网口出现异常，重置后仍未恢复 |  |  |
| storage_nic_isolate | 主机存储网口出现异常且已被隔离 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`_nic` |
| storage_nic_recover_after_reset | 主机存储网口出现异常，重置后恢复正常 |  |  |
