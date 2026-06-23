# host_* 前缀指标

## Labels 说明

| label | 内容描述 |
|---|---|
| `_tenant_id` | 租户或采集范围 ID，跨租户聚合时需要保留。 |
| `_cluster_uuid` | CloudTower 集群 UUID，集群重命名后保持稳定。 |
| `_host` | 主机内部 UUID。 |
| `hostname` | 主机名称。 |
| `_device` | 物理盘或网络设备名，例如 sda、eth0。 |
| `disk_type` | 磁盘类型，例如 HDD 或 SSD。 |
| `disk_model` | 磁盘型号。 |
| `capacity` | 磁盘容量。 |
| `_network` | 网络接口或网络平面标识。 |
| `_eth` | 以太网接口标识。 |
| `_service` | 主机服务名。 |
| `instance` | 采集目标地址，通常为 host:port 或 URL。 |
| `job` | Prometheus/VictoriaMetrics 抓取任务名。 |
| `_cpu` | CPU 或 CPU 插槽标识。 |
| `_disk_model` | 采集器暴露的原始 label，含义需结合具体指标上下文确认。 |
| `_fan` | 风扇标识。 |
| `_pd_id` | 硬件 RAID 物理盘 ID。 |
| `_serial` | 硬件序列号。 |
| `_serial_number` | 硬件序列号。 |
| `_target_host_uuid` | 探测目标主机 UUID。 |
| `_to_host` | 网络探测目标主机标识。 |
| `_to_uuid` | 网络探测目标 UUID。 |
| `_vd_id` | 硬件 RAID 虚拟盘 ID。 |
| `_vd_name` | 硬件 RAID 虚拟盘名称。 |
| `_vds` | 硬件 RAID 虚拟盘集合。 |
| `bandwidth` | 网卡或链路带宽档位。 |
| `can_not_ping_hostnames` | 不可达目标主机名列表。 |
| `cloudtower` | CloudTower 实例标识。 |
| `cmd_tool` | 执行检测的命令行工具。 |
| `count` | 数量维度或计数分组。 |
| `firmware_version` | 固件版本。 |
| `ip` | IP 地址。 |
| `is_across_zone` | 是否跨故障域或跨可用区。 |
| `le` | Histogram bucket 上界。 |
| `raid_mode` | RAID 模式。 |
| `raw_status` | 设备原始状态字符串。 |
| `role` | 节点、服务或对象角色。 |
| `serial_number` | 硬件序列号。 |
| `state_str` | 状态字符串。 |
| `target_hostname` | 探测目标主机名。 |
| `to_hostname` | 网络探测目标主机名。 |
| `vd_id` | 硬件 RAID 虚拟盘 ID。 |
| `vd_name` | 硬件 RAID 虚拟盘名称。 |
| `vds` | 虚拟盘集合。 |

## Metrics 说明

| metric_name | 中文说明 | 适用版本 | labels 描述 |
|---|---|---|---|
| host_access_network_can_ping | 主机接入网络能否 ping 通 |  |  |
| host_all_service_resident_memory_bytes | 主机所有服务常驻内存占用量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_bond_slave_is_normal | 网口 bonding 状态 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_eth`、`instance`、`job`、`_vds`、`role` |
| host_can_connect_with_ntp_server | 主机与外部 NTP 服务器链接状态 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`cloudtower`、`role` |
| host_can_sync_time_with_ntp_server | 主机时间与外部 NTP 服务器同步状态 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`cloudtower`、`role` |
| host_cpu_fan_is_ok | 主机风扇状态是否正常 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`_fan`、`role` |
| host_cpu_overall_15m_avg_load | 主机 CPU 15 分钟内的平均负载 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_cpu_overall_1m_avg_load | 主机 CPU 1 分钟内的平均负载 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_cpu_overall_5m_avg_load | 主机 CPU 5 分钟内的平均负载 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_cpu_overall_usage_percent | 主机 CPU 使用率 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_cpu_overall_used_hz | 主机 CPU 使用量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_cpu_temperature_celsius | 主机 CPU 温度 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`_cpu`、`role` |
| host_disk_avg_read_latency_ns | 主机磁盘 I/O 平均延时-读 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`disk_type`、`disk_model`、`capacity`、`instance`、`job`、`firmware_version`、`role`、`serial_number` |
| host_disk_avg_read_size_bytes | 主机磁盘 I/O 平均块大小-读 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`disk_type`、`disk_model`、`capacity`、`instance`、`job`、`firmware_version`、`role`、`serial_number` |
| host_disk_avg_readwrite_latency_ns | 主机磁盘 I/O 平均延时-总 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`disk_type`、`disk_model`、`capacity`、`instance`、`job`、`firmware_version`、`role`、`serial_number` |
| host_disk_avg_readwrite_queue_length | 主机磁盘 I/O 等待队列长度 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`disk_type`、`disk_model`、`capacity`、`instance`、`job`、`firmware_version`、`role`、`serial_number` |
| host_disk_avg_readwrite_size_bytes | 主机磁盘 I/O 平均块大小-总 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`disk_type`、`disk_model`、`capacity`、`instance`、`job`、`firmware_version`、`role`、`serial_number` |
| host_disk_avg_write_latency_ns | 主机磁盘 I/O 平均延时-写 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`disk_type`、`disk_model`、`capacity`、`instance`、`job`、`firmware_version`、`role`、`serial_number` |
| host_disk_avg_write_size_bytes | 主机磁盘 I/O 平均块大小-写 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`disk_type`、`disk_model`、`capacity`、`instance`、`job`、`firmware_version`、`role`、`serial_number` |
| host_disk_read_iops | 主机磁盘读 IOPS |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`disk_type`、`disk_model`、`capacity`、`instance`、`job`、`firmware_version`、`role`、`serial_number` |
| host_disk_read_speed_bps | 主机磁盘 I/O 带宽-读 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`disk_type`、`disk_model`、`capacity`、`instance`、`job`、`firmware_version`、`role`、`serial_number` |
| host_disk_readwrite_iops | 主机磁盘总 IOPS |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`disk_type`、`disk_model`、`capacity`、`instance`、`job`、`firmware_version`、`role`、`serial_number` |
| host_disk_readwrite_speed_bps | 主机磁盘 I/O 带宽-总 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`disk_type`、`disk_model`、`capacity`、`instance`、`job`、`firmware_version`、`role`、`serial_number` |
| host_disk_remaining_life_percent | 磁盘剩余寿命百分比 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`_disk_model`、`_serial_number`、`role` |
| host_disk_smart_test_failed | 磁盘 S.M.A.R.T. 检测是否正常 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`_serial_number`、`role` |
| host_disk_temperature_celsius | 磁盘摄氏温度 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`_disk_model`、`_serial_number`、`role` |
| host_disk_utilization_percent | 主机磁盘活动时间百分比 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`disk_type`、`disk_model`、`capacity`、`instance`、`job`、`firmware_version`、`role`、`serial_number` |
| host_disk_write_iops | 主机磁盘写 IOPS |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`disk_type`、`disk_model`、`capacity`、`instance`、`job`、`firmware_version`、`role`、`serial_number` |
| host_disk_write_speed_bps | 主机磁盘 I/O 带宽-写 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`disk_type`、`disk_model`、`capacity`、`instance`、`job`、`firmware_version`、`role`、`serial_number` |
| host_hardware_raid_pd_lifespan | 硬件 RAID 下的物理盘剩余寿命百分比 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`_pd_id`、`_serial`、`role`、`vd_id`、`vd_name` |
| host_hardware_raid_pd_smart_error | 硬件 RAID 下的物理盘 S.M.A.R.T. 自测结果异常 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`_pd_id`、`_serial`、`role`、`vd_id`、`vd_name` |
| host_hardware_raid_vd_num_of_pd | 硬件 RAID 组中的物理盘数量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`_vd_id`、`_vd_name`、`role` |
| host_hardware_raid_vd_status_error | 硬件 RAID 下的虚拟盘状态是否异常 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`_vd_id`、`_vd_name`、`cmd_tool`、`raid_mode`、`raw_status`、`role` |
| host_hdd_overall_size_bytes | 主机 HDD 磁盘总容量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_hp_memory_usage_percent | 主机大页内存使用百分比 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_hp_memory_used_bytes | 主机大页内存使用量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_io_block_disk_offline | 物理盘发生 IO 阻塞，已停止处理 IO |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`_serial_number`、`role` |
| host_management_network_can_ping | 主机管理网络能否 ping 通 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`can_not_ping_hostnames`、`count`、`ip`、`is_across_zone` |
| host_memory_swap_in_speed_bps | 主机内存换入速度 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_memory_swap_out_speed_bps | 主机内存换出速度 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_memory_swap_size_bytes | 主机交换内存总量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_memory_swap_usage_percent | 主机交换内存使用百分比 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_memory_swap_used_bytes | 主机交换内存使用量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_memory_usage_percent | 主机内存使用率 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_memory_used_bytes | 主机内存使用量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_mongo_dir_used_space_bytes | 主机 /var/log/mongodb/ 目录已用量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_network_loss_rate | 主机网口丢包率 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_network_nic_bandwidth_usage_percent | 主机网口带宽使用率百分比 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`bandwidth`、`role`、`vds` |
| host_network_ping_packet_loss_percent | 主机之间 ping 丢包率 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`_network`、`instance`、`job`、`_to_uuid`、`to_hostname` |
| host_network_ping_time_ns | 主机之间 ping 延迟 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`_network`、`instance`、`job`、`_to_uuid`、`to_hostname` |
| host_network_rdma_receive_bytes | 主机 RDMA 网络接收字节数 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_network_rdma_receive_packets | 主机 RDMA 网络接收包数 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_network_rdma_receive_speed_bitps | 主机 RDMA 网络接收速度（比特每秒） |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_network_rdma_transmit_bytes | 主机 RDMA 网络发送字节数 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_network_rdma_transmit_packets | 主机 RDMA 网络发送包数 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_network_rdma_transmit_speed_bitps | 主机 RDMA 网络发送速度（比特每秒） |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_network_receive_bytes | 主机网口数据接收总量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_network_receive_dropped_packets | 主机网口接收数据丢包总数 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_network_receive_errors | 主机网口接收的错误数据包数 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_network_receive_fifo_errors | 主机网口接收 FIFO 错误总数 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_network_receive_packets | 主机网口收包量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_network_receive_speed_bitps | 主机网口数据接收速度（比特每秒） |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_network_receive_speed_bps | 主机网口数据接收速度（字节每秒） |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_network_transmit_bytes | 主机网口数据发送总量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_network_transmit_dropped_packets | 主机网口发送数据丢包总数 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_network_transmit_errors | 主机网口发送的错误数据包数 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_network_transmit_fifo_errors | 主机网口发送 FIFO 错误总数 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_network_transmit_packets | 主机网口发包量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_network_transmit_speed_bitps | 主机网口数据发送速度（比特每秒） |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_network_transmit_speed_bps | 主机网口数据发送速度（字节每秒） |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`role` |
| host_non_hp_memory_usage_percent | 主机非大页内存使用百分比 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_non_hp_memory_used_bytes | 主机非大页内存使用量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_other_service_resident_memory_bytes | 主机其他服务常驻内存占用量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_power_is_on | 主机电源状态 |  | `_tenant_id`、`_cluster_uuid`、`instance`、`job`、`_target_host_uuid`、`target_hostname` |
| host_service_cpu_usage_percent | 主机服务 CPU 占用百分比 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_service`、`instance`、`job`、`role` |
| host_service_health | 主机服务健康状态 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_service`、`instance`、`job`、`role`、`state_str` |
| host_service_is_running | 主机服务运行状态 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_service`、`instance`、`job`、`role` |
| host_service_resident_memory_bytes | 主机服务常驻内存占用量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_service`、`instance`、`job`、`role` |
| host_service_shared_memory_bytes | 主机服务共享内存占用量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_service`、`instance`、`job`、`role` |
| host_service_virtual_memory_bytes | 主机服务虚拟内存占用量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_service`、`instance`、`job`、`role` |
| host_ssd_overall_size_bytes | 主机 SSD 磁盘总容量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_storage_network_can_ping | 主机存储网络能否 ping 通 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`can_not_ping_hostnames`、`count`、`ip`、`is_across_zone` |
| host_sub_healthy_disk_in_isolate | 磁盘是否处于亚健康状态且隔离中 |  |  |
| host_sub_healthy_disk_without_isolate | 磁盘是否处于亚健康状态且未隔离 |  |  |
| host_sys_partition_raid_is_normal | 主机 RAID 状态 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_sys_partition_usage_percent | 主机系统分区已使用百分比 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_sys_partition_used_space_bytes | 主机 / 目录已用量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_time_offset_with_ntp_leader_seconds | 主机与 NTP Leader 的时钟偏移量，单位 秒 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`cloudtower`、`role` |
| host_to_host_max_ping_time_ns_bucket | 主机之间 ping 延迟分布 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`_to_host`、`le`、`to_hostname` |
| host_unhealthy_disk_in_isolate | 磁盘是否处于不健康状态 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`_serial_number`、`role` |
| host_unhealthy_disk_offline | 不健康磁盘是否离线 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`_device`、`instance`、`job`、`_serial_number`、`role` |
| host_unhealthy_disk_with_last_smtx_system | 磁盘是否处于不健康状态，且残留最后一个系统分区或元数据分区 |  |  |
| host_unhealthy_disk_with_left_partition | 磁盘是否处于不健康状态且残留未卸载分区 |  |  |
| host_uptime_seconds | 主机自启动以来的运行时长 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
| host_work_status_is_unknown | 主机工作状态是否未知 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job` |
| host_zbs_log_dir_used_space_bytes | 主机 /var/log/zbs/ 目录已用量 |  | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`role` |
