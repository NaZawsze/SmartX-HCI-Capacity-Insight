# SKS（Kubernetes 服务）指标

## Labels 说明

| label | 内容描述 |
|---|---|
| `_tenant_id` | 租户或采集范围 ID，跨租户聚合时需要保留。 |
| `_cluster_uuid` | CloudTower 集群 UUID，集群重命名后保持稳定。 |
| `cluster` | 集群名称或集群标识。 |
| `_host` | 主机内部 UUID。 |
| `hostname` | 主机名称。 |
| `sfs_hostname` | SFS 节点主机名。 |
| `device` | 设备名称。 |
| `instance` | 采集目标地址，通常为 host:port 或 URL。 |
| `instance_id` | 采集实例 ID。 |
| `job` | Prometheus/VictoriaMetrics 抓取任务名。 |
| `To` | 接收方或目标地址。 |
| `access_mode` | Kubernetes PVC 访问模式。 |
| `build_date` | 组件构建日期。 |
| `cloudtower` | CloudTower 实例标识。 |
| `compiler` | 构建使用的编译器。 |
| `condition` | Kubernetes 资源状态条件。 |
| `cpu` | CPU 核或 CPU 模式维度。 |
| `created_by_kind` | 创建 Pod 的 Kubernetes 控制器类型。 |
| `created_by_name` | 创建 Pod 的 Kubernetes 控制器名称。 |
| `daemonset` | Kubernetes DaemonSet 名称。 |
| `deployment` | Kubernetes Deployment 名称。 |
| `effect` | 策略生效方式或效果。 |
| `fstype` | 文件系统类型。 |
| `git_commit` | 组件构建 Git commit。 |
| `git_tree_state` | 组件构建时 Git 工作树状态。 |
| `git_version` | 组件 Git 版本。 |
| `go_version` | 组件构建使用的 Go 版本。 |
| `host_ip` | 节点或 Pod 所在主机 IP。 |
| `host_network` | Pod 是否使用 hostNetwork。 |
| `key` | 键名或属性名。 |
| `le` | Histogram bucket 上界。 |
| `major` | 主版本号。 |
| `minor` | 次版本号。 |
| `mode` | CPU、权限或运行模式。 |
| `monitor` | 监控项或探测器名称。 |
| `mountpoint` | 文件系统挂载点。 |
| `namespace` | Kubernetes Namespace。 |
| `node` | Kubernetes Node 名称。 |
| `persistentvolume` | Kubernetes PersistentVolume 名称。 |
| `persistentvolumeclaim` | Kubernetes PersistentVolumeClaim 名称。 |
| `phase` | Kubernetes 资源阶段。 |
| `platform` | 平台类型。 |
| `pod` | Kubernetes Pod 名称。 |
| `pod_ip` | Pod IP 地址。 |
| `priority_class` | Kubernetes Pod PriorityClass。 |
| `resource` | Kubernetes 资源类型，例如 cpu、memory。 |
| `role` | 节点、服务或对象角色。 |
| `status` | 状态值。 |
| `uid` | Kubernetes 资源 UID。 |
| `unit` | 资源单位。 |
| `value` | 标签型取值。 |

## Metrics 说明

| metric_name | 中文说明 | 适用版本 | labels 描述 |
|---|---|---|---|
| node_cpu_seconds_total | 节点各模式 CPU 占用秒数 | v1.4.0 及以上 | `_tenant_id`、`_cluster_uuid`、`instance`、`job`、`cloudtower`、`cpu`、`mode` |
| node_memory_MemAvailable_bytes | 节点可用内存字节数 | v1.4.0 及以上 | `_tenant_id`、`_cluster_uuid`、`instance`、`job`、`cloudtower` |
| node_memory_MemTotal_bytes | 节点总内存字节数 | v1.4.0 及以上 | `_tenant_id`、`_cluster_uuid`、`instance`、`job`、`cloudtower` |
| node_filesystem_files_free | 文件系统空闲 inode 数 | v1.4.0 及以上 | `_tenant_id`、`_cluster_uuid`、`device`、`instance`、`job`、`cloudtower`、`fstype`、`mountpoint` |
| node_filesystem_files | 文件系统总 inode 数 | v1.4.0 及以上 | `_tenant_id`、`_cluster_uuid`、`device`、`instance`、`job`、`cloudtower`、`fstype`、`mountpoint` |
| node_filesystem_readonly | 文件系统只读状态 | v1.4.0 及以上 | `_tenant_id`、`_cluster_uuid`、`device`、`instance`、`job`、`cloudtower`、`fstype`、`mountpoint` |
| node_filesystem_avail_bytes | 文件系统可用空间（非 root 用户） | v1.4.0 及以上 | `_tenant_id`、`_cluster_uuid`、`device`、`instance`、`job`、`cloudtower`、`fstype`、`mountpoint` |
| node_filesystem_size_bytes | 文件系统总容量 | v1.4.0 及以上 | `_tenant_id`、`_cluster_uuid`、`device`、`instance`、`job`、`cloudtower`、`fstype`、`mountpoint` |
| node_network_receive_errs_total | 网络设备接收错误总数 | v1.4.0 及以上 | `_tenant_id`、`_cluster_uuid`、`device`、`instance`、`job`、`cloudtower` |
| node_network_receive_packets_total | 网络设备接收包总数 | v1.4.0 及以上 | `_tenant_id`、`_cluster_uuid`、`device`、`instance`、`job`、`cloudtower` |
| node_network_transmit_errs_total | 网络设备发送错误总数 | v1.4.0 及以上 | `_tenant_id`、`_cluster_uuid`、`device`、`instance`、`job`、`cloudtower` |
| node_network_transmit_packets_total | 网络设备发送包总数 | v1.4.0 及以上 | `_tenant_id`、`_cluster_uuid`、`device`、`instance`、`job`、`cloudtower` |
| node_timex_sync_status | 时钟是否已同步到可靠服务器（1=是, 0=否） | v1.4.0 及以上 | `_tenant_id`、`_cluster_uuid`、`instance`、`job`、`cloudtower` |
| node_timex_maxerror_seconds | 时钟最大误差（秒） | v1.4.0 及以上 | `_tenant_id`、`_cluster_uuid`、`instance`、`job`、`cloudtower` |
| node_network_up | 网络接口操作状态（1=up, 0=down） | v1.4.0 及以上 | `_tenant_id`、`_cluster_uuid`、`device`、`instance`、`job`、`cloudtower` |
| host_time_offset_with_ntp_leader_seconds | 主机与 NTP 服务器的时间偏移量（秒） | v1.4.0 及以上 | `_tenant_id`、`_cluster_uuid`、`_host`、`hostname`、`instance`、`job`、`cloudtower`、`role` |
| up | Prometheus 采集目标存活状态 | v1.4.0 及以上 | `_tenant_id`、`_cluster_uuid`、`instance`、`job`、`cloudtower`、`namespace`、`pod` |
| kube_node_status_condition | 集群节点的状态条件 | v1.4.0 及以上 | `_tenant_id`、`instance`、`job`、`cloudtower`、`condition`、`node`、`status` |
| kube_node_spec_taint | 集群节点的污点（taint）信息 | v1.4.0 及以上 | `_tenant_id`、`instance`、`job`、`cloudtower`、`effect`、`key`、`node`、`value` |
| kube_pod_status_phase | Pod 当前所处阶段 | v1.4.0 及以上 | `_tenant_id`、`instance`、`job`、`cloudtower`、`namespace`、`phase`、`pod`、`uid` |
| kube_pod_info | Pod 基本信息 | v1.4.0 及以上 | `_tenant_id`、`instance`、`job`、`cloudtower`、`created_by_kind`、`created_by_name`、`host_ip`、`host_network`、`namespace`、`node`、`pod`、`pod_ip`、`priority_class`、`uid` |
| kube_node_status_capacity | 节点各类资源的容量 | v1.4.0 及以上 | `_tenant_id`、`instance`、`job`、`cloudtower`、`node`、`resource`、`unit` |
| kube_persistentvolume_status_phase | PersistentVolume 当前阶段 | v1.4.0 及以上 | `_tenant_id`、`instance`、`job`、`cloudtower`、`persistentvolume`、`phase` |
| kubelet_volume_stats_available_bytes | 卷可用空间字节数 | v1.4.0 及以上 |  |
| kubelet_volume_stats_capacity_bytes | 卷总容量字节数 | v1.4.0 及以上 |  |
| kubelet_volume_stats_used_bytes | 卷已用空间字节数 | v1.4.0 及以上 |  |
| kube_persistentvolumeclaim_access_mode | PVC 访问模式 | v1.4.0 及以上 | `_tenant_id`、`instance`、`job`、`access_mode`、`cloudtower`、`namespace`、`persistentvolumeclaim` |
| kube_persistentvolumeclaim_labels | PVC 的 Kubernetes 标签 | v1.4.0 及以上 | `_tenant_id`、`instance`、`job`、`cloudtower`、`namespace`、`persistentvolumeclaim` |
| kubelet_volume_stats_inodes_free | 卷空闲 inode 数 | v1.4.0 及以上 |  |
| kubelet_volume_stats_inodes | 卷最大 inode 数 | v1.4.0 及以上 |  |
| kubelet_volume_stats_inodes_used | 卷已用 inode 数 | v1.4.0 及以上 |  |
| kubernetes_build_info | Kubernetes 构建版本信息 | v1.4.0 及以上 | `_tenant_id`、`instance`、`job`、`build_date`、`cloudtower`、`compiler`、`git_commit`、`git_tree_state`、`git_version`、`go_version`、`major`、`minor`、`platform` |
| kube_resourcequota | 资源配额（ResourceQuota）信息 | v1.4.0 及以上 |  |
| harbor_up | Harbor 镜像仓库存活状态 | v1.4.0 及以上 |  |
| kube_deployment_spec_replicas | Deployment 期望副本数 | v1.4.0 及以上 | `_tenant_id`、`instance`、`job`、`cloudtower`、`deployment`、`namespace` |
| kube_deployment_status_replicas_available | Deployment 可用副本数 | v1.4.0 及以上 | `_tenant_id`、`instance`、`job`、`cloudtower`、`deployment`、`namespace` |
| kube_deployment_status_replicas_updated | Deployment 已更新副本数 | v1.4.0 及以上 | `_tenant_id`、`instance`、`job`、`cloudtower`、`deployment`、`namespace` |
| kube_daemonset_status_current_number_scheduled | DaemonSet 当前已调度节点数 | v1.4.0 及以上 | `_tenant_id`、`instance`、`job`、`cloudtower`、`daemonset`、`namespace` |
| kube_daemonset_status_number_ready | DaemonSet 就绪节点数 | v1.4.0 及以上 | `_tenant_id`、`instance`、`job`、`cloudtower`、`daemonset`、`namespace` |
| kube_daemonset_status_updated_number_scheduled | DaemonSet 已更新调度节点数 | v1.4.0 及以上 |  |
| sks_cluster_kube_apiserver_certificate_expiry_date | kubeSmartCluster 集kube-apiserver证书过期时间 | v1.4.0 及以上 |  |
| sks_cluster_status_phase | kubeSmartCluster 集群状态 | v1.4.0 及以上 |  |
| etcd_network_peer_sent_failures_total | etcd 节点间发送失败总数 | v1.4.0 及以上 | `_tenant_id`、`cluster`、`sfs_hostname`、`instance`、`instance_id`、`job`、`To`、`monitor` |
| etcd_server_has_leader | etcd 是否存在 leader（1=存在, 0=不存在） | v1.4.0 及以上 | `_tenant_id`、`cluster`、`sfs_hostname`、`instance`、`instance_id`、`job`、`monitor` |
| etcd_server_leader_changes_seen_total | etcd leader 变更次数 | v1.4.0 及以上 | `_tenant_id`、`cluster`、`sfs_hostname`、`instance`、`instance_id`、`job`、`monitor` |
| etcd_disk_wal_fsync_duration_seconds_bucket | etcd WAL fsync 延迟分布（直方图） | v1.4.0 及以上 | `_tenant_id`、`cluster`、`sfs_hostname`、`instance`、`instance_id`、`job`、`le`、`monitor` |
| etcd_disk_backend_commit_duration_seconds_bucket | etcd 后端存储 commit 延迟分布（直方图） | v1.4.0 及以上 | `_tenant_id`、`cluster`、`sfs_hostname`、`instance`、`instance_id`、`job`、`le`、`monitor` |
| sks_license_status_expiry_date | SKS 许可证过期时间 | v1.4.0 及以上 |  |
| kubesmart_clusterresourcequota | SKS 项目配额状态 | v1.6.0 及以上 |  |
| sks_multus_ipam_allocated_count | multus cni插件已分配的IP地址数量 | v1.6.0 及以上 |  |
| sks_multus_ipam_total_count | multus cni插件可分配的IP地址总量，包含已分配和未分配 | v1.6.0 及以上 |  |
