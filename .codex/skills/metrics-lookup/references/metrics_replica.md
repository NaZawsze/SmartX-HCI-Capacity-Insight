# 复制（Replica）指标

## Labels 说明

| label | 内容描述 |
|---|---|
| `_tenant_id` | 租户或采集范围 ID，跨租户聚合时需要保留。 |
| `host` | 主机名称或主机标识。 |
| `volume_id` | 卷 ID。 |
| `service` | 服务名称。 |
| `service_id` | 服务 ID。 |
| `instance` | 采集目标地址，通常为 host:port 或 URL。 |
| `job` | Prometheus/VictoriaMetrics 抓取任务名。 |
| `exported_job` | 被联邦或远端导出的原始 job。 |
| `job_uid` | 任务 UID。 |
| `peer_address` | 对端地址。 |
| `result` | 执行结果。 |

## Metrics 说明

| metric_name | 中文说明 | 适用版本 | labels 描述 |
|---|---|---|---|
| read_ahead_cache_size_bytes | 预读缓存的大小 |  | `_tenant_id`、`volume_id`、`service`、`service_id`、`instance`、`job` |
| server_health_results_total | 服务健康状况累计量 |  | `_tenant_id`、`service`、`service_id`、`instance`、`job`、`result` |
| ping_results_total | 客户端 ping 结果的累计数量 |  | `_tenant_id`、`service`、`service_id`、`instance`、`job`、`peer_address`、`result` |
| ping_duration_nanoseconds | ping 响应持续时间 |  |  |
| fp_worker_pool_submit_jobs_total | 已提交的 fp 计算任务累计数量 |  | `_tenant_id`、`service`、`service_id`、`instance`、`job` |
| fp_worker_pool_batch_call_total | BatchGetByWorkerpool 调用的累计次数 |  | `_tenant_id`、`service`、`service_id`、`instance`、`job` |
| sparse_read_time_nanoseconds_total | 按任务 UUID 统计稀疏读取 I/O 所花费的时间 |  | `_tenant_id`、`service`、`service_id`、`instance`、`job`、`exported_job` |
| sparse_write_time_nanoseconds_total | 按任务 UUID 统计稀疏写入 I/O 所花费的时间 |  | `_tenant_id`、`service`、`service_id`、`instance`、`job`、`exported_job` |
| sparse_read_requests_total | 按任务 UUID 处理的稀疏读取 I/O 请求 |  | `_tenant_id`、`service`、`service_id`、`instance`、`job`、`exported_job` |
| sparse_write_requests_total | 按任务 UUID 处理的稀疏写入 I/O 请求 |  | `_tenant_id`、`service`、`service_id`、`instance`、`job`、`exported_job` |
| sparse_read_bytes_total | 按任务 UUID 处理的稀疏读取 I/O 字节数 |  | `_tenant_id`、`service`、`service_id`、`instance`、`job`、`exported_job` |
| sparse_write_bytes_total | 按任务 UUID 处理的稀疏写入 I/O 字节数 |  | `_tenant_id`、`service`、`service_id`、`instance`、`job`、`exported_job` |
| zbs_read_time_nanoseconds_total | ZBS 读取 I/O 所花费的时间，按 ZBS 主机和任务 UID 分类 |  | `_tenant_id`、`host`、`service`、`service_id`、`instance`、`job`、`job_uid` |
| zbs_read_requests_total | ZBS 读取 I/O 请求已处理，由 ZBS 主机和任务 UID 处理。 |  | `_tenant_id`、`host`、`service`、`service_id`、`instance`、`job`、`job_uid` |
| zbs_read_bytes_total | ZBS 读取 IO 已处理字节数（按 ZBS 主机及任务 UID 划分） |  | `_tenant_id`、`host`、`service`、`service_id`、`instance`、`job`、`job_uid` |
| zbs_write_time_nanoseconds_total | ZBS 写入 IO 所花费的时间，按 ZBS 主机和任务 UID 统计 |  | `_tenant_id`、`host`、`service`、`service_id`、`instance`、`job`、`job_uid` |
| zbs_write_requests_total | ZBS 已处理写入 I/O 请求，由 ZBS 主机和任务 UID 处理 |  | `_tenant_id`、`host`、`service`、`service_id`、`instance`、`job`、`job_uid` |
| zbs_write_bytes_total | ZBS 主机和任务 UID 处理的 ZBS 写入 I/O 字节数 |  | `_tenant_id`、`host`、`service`、`service_id`、`instance`、`job`、`job_uid` |
| offset_iterator_total_bytes | 按 volume_id 统计 ValidOffsetIter.NextValidOffsetRange 返回的累计字节数 |  | `_tenant_id`、`volume_id`、`service`、`service_id`、`instance`、`job` |
| offset_iterator_total_requests | 按 volume_id 统计 ValidOffsetIter.NextValidOffsetRange 的累计调用次数 |  | `_tenant_id`、`volume_id`、`service`、`service_id`、`instance`、`job` |
