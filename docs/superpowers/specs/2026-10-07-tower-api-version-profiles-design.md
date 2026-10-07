# Tower API 版本画像（#84）设计：按平台版本选择不同 API 行为

- 状态：已实施（2026-10-07），`.3` 真机验证通过
- 来源：2026-10-07 用户需求「后面要根据不同的 tower 版本号，选择不同的 tower api」
- 证据源：官方文档站 `https://code-site.smartx.com/specs/<version>-swagger.json`
  （探针 `scripts/probe_cloudtower_api_versions.py --all`，覆盖 4.4.0+，用户 2026-10-07 指定范围）
- 关联：**[cloudtower-api-version-matrix.md](../cloudtower-api-version-matrix.md)（版本对接矩阵，长期维护件）**、
  findings.md 2026-10-07（版本取法 / 策略串 / 文档站 / 差异矩阵）、task_plan Phase 70、pending #84

## 1. 背景与问题

平台调用 CloudTower 的 6 个接口：`login`、`get-version`、`get-clusters`、`get-vms`、
`get-vm-volumes`、`get-cluster-storage-info`。2026-10-07 实测发现不同版本的塔返回**不同形态**：
v4.5.0 的塔在 `get-vm-volumes` 里只给策略串 `elf_storage_policy`，没有扁平副本字段，
导致「已分配」恒为 0（详见 findings.md）。若继续"一套代码假设一个响应形态"，
更老的塔会出现更硬的问题（例如 4.4.x **根本没有容量端点**，直接采集失败）。

## 2. 证据（官方 4.4.0+ 规范矩阵，实测）

| 差异 | 版本边界（实测） | 影响 |
| --- | --- | --- |
| `get-cluster-storage-info` 端点 | 4.5.0+ 有；**4.4.0 / 4.4.1 无** | 4.4.x 调用该端点必然失败 → 采集整体失败 |
| 卷扁平字段 `elf_storage_policy_replica_num` / `_thin_provision` / `_ec_k` / `_ec_m` | 4.7.0+ 有；4.6.0 / 4.5.0 / 4.4.x 无 | 缺字段 → 已分配会乘 0（v4.5.0 塔实测形态） |
| `Vm.used_size` / `VmVolume.used_size` | 4.6.0+ 有；4.5.0 / 4.4.x 无 | 旧的"已使用"只能按未上报处理 |
| `Cluster.used_data_space` / `total_data_capacity` | 4.4.0+ **全有** | 容量兜底来源 |
| `GET /v2/api/get-version` | 4.4.0+ 全有 | 版本探测在支持面内始终可用 |

注：`4.7.1 / 4.6.2 / 4.6.1 / 4.4.2` 在文档站 `specs/` 目录下没有规范文件（返回 HTML），
矩阵用相邻版本覆盖；不影响结论（每个断点的两侧都有实测版本）。

旁证：`.3` 可达测试塔 = **v4.5.0**，其卷响应确实没有扁平副本字段（与矩阵一致）；
生产塔返回扁平字段 → 预测其平台版本 **≥ 4.7.0**（塔可达后用 `GET /v2/api/get-version` 可验证）。

## 3. 设计

### 3.1 版本 → 画像（纯函数）

新模块 `backend/app/v2/cloudtower/profiles.py`：

```text
ApiProfile(version_floor, cluster_storage_info_endpoint, volume_flat_policy_fields,
           volume_used_size, vm_used_size)
PROFILES = 4.7.0 → 全 True
           4.6.0 → 无扁平策略字段
           4.5.0 → 且无 used_size
           4.4.0（下限）→ 且无容量端点
profile_for_version(text)  # 逐档向下取第一个 version >= floor
```

### 3.2 运行时规则（关键：读不到版本也必须可用）

1. 版本可解析 → 用对应画像；
2. 版本未知（塔不可达 / 尚未采集 / 字符串不可解析）→ **最新画像 + 能力探测兜底**；
3. 低于下限 4.4.0 → 不阻断，按最旧画像处理。

容量取值分派（本版唯一的**功能性**分支）：

| 情形 | 行为 |
| --- | --- |
| 画像说端点可用（4.5.0+） | 走 `get-cluster-storage-info`；**端点报错就报错**，不静默降级（否则会掩盖真实故障） |
| 画像说端点不可用（4.4.x） | 直接读 `get-clusters` 的集群记录容量，不请求该端点 |
| 版本未知 | 先试端点；端点失败自动回退集群记录（能力探测） |

采集结果里新增 `capacity_source`（`cluster-storage-info` / `cluster-record`），便于运维判读与取证。

卷副本数保持**字段优先 + 策略串推导**的容错读取（与画像一致，不引入第二套判断），
`used_size` 缺失仍按"未上报"处理（页面显示 `-`）。

### 3.3 明确不做（本版）

- 不把 `volume_flat_policy_fields` / `*_used_size` 做成硬分支：容错读取等价且更稳，
  这两个标志用于**记录边界 + 测试钉住矩阵**，以及未来真正的端点级差异时接入。
- 不改 `VmCapacitySample.used_bytes` 的口径（≤4.5 塔的 VM "已使用"仍按 0 展示）——
  改成 None 会牵动增长计算与 Prometheus 指标口径，单独立项。

## 4. 测试计划（已执行）

- `tests/test_v2_cloudtower_client.py::TowerApiProfileTest`：版本解析变体、四档 floor 选择、
  未知/低于下限回退、**4.4.x 走集群记录且不请求容量端点**、未知版本端到端探测回退、
  「画像说端点可用时失败必须上报」。
- 既有断言同步补 `capacity_source`。
- `.3` 定向：`test_v2_cloudtower_client + test_v2_collection + test_v2_migration` 60 项 OK；
  全量见 progress.md 2026-10-07 轮（1142+ 项）。
- `.3` 真机：测试塔（v4.5.0）重采集后已分配仍为 320 GiB，`capacity_source=cluster-storage-info`。

## 5. 风险与回滚

- 风险：对 4.4.x 塔多一次 `get-clusters`（每集群一次；老塔集群数少，可接受）；
  画像表是纯数据，读不到版本时行为与修前一致（保守）。
- 回滚：纯代码改动（无 schema 变更）；回滚 = 还原提交，或在
  `profile_for_version` 恒返回 `NEWEST_PROFILE`（行为退化为修前 + 容错读取）。
