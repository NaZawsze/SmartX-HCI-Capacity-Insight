# Phase 75 设计规范：增长排行榜与新建报表排除已删除虚拟机（方案 A）

## 1. 目标与背景

### 1.1 问题现状
用户在审阅导出的「月增长最快虚拟机」报表时发现：
- 排名第 42 名的虚拟机 `LiuYu-Ubuntu`，其 Tower 显示为数字 `3`，集群显示为 ID `cm551tvrv029a0858up57q8qu`，分配空间显示为 `-`。
- **根因分析**：
  1. 该虚拟机在过去 30 天内（9月中旬~10月初）确实存在过且产生了容量增长（15.75 GiB -> 17.88 GiB，净增 +2.13 GiB），因此 Prometheus 历史时序库（`smartx_vm_storage_used_bytes`）留有其增长曲线；
  2. 但该机器目前已被管理员从 SmartX / CloudTower 中**彻底删除**，SQLite 的当前活跃元数据表（`vm_latest` 和 `vm_volumes`）中已经查无此机；
  3. 现行算法 `compute_growth_vms` 是纯基于 Prometheus 时序计算增长量的，当它去 SQLite 补充最新标签时未查到，于是分配空间、所有者全为 `-`，Tower 与集群名降级显示了时序标签上的原始 ID；
  4. 运维核心诉求：报表中的增长排行榜是为了让运维人员排查、治理**当前在线活跃**的高耗存储虚拟机；已删除的虚拟机现实中已不存在，无法治理，且残缺数据显示在报表中严重影响专业度。

### 1.2 决策
用户明确采纳 **方案 A**：**直接将已删除虚拟机从增长榜单和新建列表中排除，确保进入排行榜的 100% 为当前现场真实在跑的活跃虚拟机。**

---

## 2. 详细设计

### 2.1 存活过滤边界（Alive Check）
1. **活跃元数据源**：
   - `service.py` 中的 `self._latest_vm_labels()` 查自 `vm_latest`（当前未删除的最新虚拟机），包含所有当前存活虚拟机的 `(tower_id, cluster_id, vm_id)`。
   - 在 `vm_latest` 的 SQL 查询中，明确加上 `WHERE (deleted_at IS NULL OR deleted_at = '') AND (in_recycle_bin = 0 OR in_recycle_bin IS NULL)`，确保回收站和标记删除的虚拟机不进入活跃集合。
2. **增长计算过滤 (`compute_growth_vms` / `_growth_reports_from_series`)**：
   - 增加 `alive_only: bool = True` 机制（报表模式下强制启用）。
   - 循环 `latest_items` 时，检查 `key = vm_key(labels)`：
     - 若 `key not in latest_label_by_vm`，直接 `continue` 跳过。
     - 若虚拟机名称匹配回收站规则 `is_recycled_vm_name(...)`，直接 `continue` 跳过。
3. **新建虚拟机过滤 (`_new_vm_reports_from_series`)**：
   - 同样检查 `if key not in latest_label_by_vm: continue`，确保即使近期新建但已删除的虚拟机也不进入本日/本月新建 VM 表。
4. **集群与 Tower 名称双重保险（Name Resolution Fallback）**：
   - 在 `_latest_vm_labels()` 中，无论何时，若 `tower` 或 `cluster` 为纯 ID，必须经 `tower_names`（`3 -> CHINATOWER`）与 `cluster_names`（`cm551tvr... -> SMARTX-TT-WW`）进行翻译，从架构上彻底杜绝裸露 ID 的可能性。

---

## 3. 测试与验证计划

1. **单测覆盖 (`test_v2_report_exports.py`)**：
   - 编写针对已删除 VM（在 Prometheus series 中有采样点，但在 `latest_label_by_vm` 中不存在）的过滤测试；
   - 验证其不会出现在 `month_fastest_growing_vms`、`day_fastest_growing_vms`、`day_new_vms` 中；
   - 运行本地全量测试确保所有断言通过。
2. **测试机 `.3` 真机回归**：
   - 将更新代码部署至 `10.20.11.3` 并重启 `web-api`。
   - 重新执行 `verify_remote_exported_reports.py` 导出报表，验证第 42 名的 `LiuYu-Ubuntu` 已被自动过滤，榜单中不再包含任何已删除机器和裸露 ID。
   - 覆盖更新桌面文件 `/Users/nazawsze/Desktop/SmartX_存储容量分析报告_20261010.xlsx` 与 `.docx`。
