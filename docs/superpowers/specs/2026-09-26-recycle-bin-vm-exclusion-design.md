# 回收站 VM 排除（本日/本月新建、增长 VM 统计）

- 日期：2026-09-26
- 状态：已实施并验证（2026-09-26，.3 后端 350 tests OK；提交待用户批准）
- 关联任务：task_plan.md Phase 49 第 40 条；pending-tasks #34
- 触发：用户反馈报表「本日新建 VM」「本月新建 VM」里显示一堆 `in-recycle-bin-<uuid>` 的 VM（被当成新建，名字看起来像乱码）

## 1. 背景与根因

1. Tower/CloudTower 把处于**回收站**的 VM 命名为 `in-recycle-bin-<uuid>`。
2. `smartx_vm_storage_used_bytes` 的标签里保存了当时的 VM 名；VM 进入回收站后改名 → Prometheus 出现**新的序列**（新 label set），首次出现时间是改名之后。
3. 报表「本日/本月新建 VM」= 「序列首次出现落在今日/本月」，于是把这些回收站 VM 判成"新建"。
4. `.3` 实测：`day_new_vms` 25 台、`month_new_vms` 228 台，前排全是 `in-recycle-bin-*`。

## 2. 口径

- **回收站 VM 不计入**本日/本月新建 VM、也不计入增长 VM 列表；**采集侧不再入库**。
- 识别口径：显示名（`vm` / `vm_name`）以 `in-recycle-bin-` 开头（常量 `RECYCLE_BIN_VM_PREFIX`，定义在 `cloudtower/client.py`）。
- 只排除这类实体；其他 VM 行为不变。

### 2.1 边界（不做）

- 不改 VM 数量 KPI（看板「虚拟机」仍按 `vm_latest` 计数，**含回收站 VM**）。2026-09-26 用户确认：删除的虚拟机**也应该记录**，暂无显示需求 → 计数保留、记录保留到 Tower 彻底删除（49-47 核对后同步删行）、仅新建/增长列表排除展示；将来需要「查看/筛选已删除 VM」再立项。
- 不清理 SQLite `vm_latest` / Prometheus 中既有的回收站 VM 记录（业务数据不做一次性删除）。
- 不按 `vm_id` 或其它字段猜测回收站状态（Tower 不可达，无法核对是否存在 `in_recycle_bin` 之类字段；名称前缀是当前可验证的口径）。

## 3. 实施方案

1. `backend/app/v2/cloudtower/client.py`
   - 新增常量 `RECYCLE_BIN_VM_PREFIX = "in-recycle-bin-"`；
   - `_normalize_vm`：名字命中前缀 → 返回 `None`（后续采集不再写入该 VM）。
2. `backend/app/v2/reports/service.py`
   - 新增 `_is_recycled_vm_name(name)`、`_vm_display_name(labels)`；
   - `_latest_vm_items`（增长 VM 列表的数据源）过滤回收站 VM；
   - `_new_vm_reports_from_series`（本日/本月新建）用"最新名称"解析后过滤。

## 4. 测试计划

- `test_v2_reports.py` 新增 `RecycledVmPrometheus` + `test_new_vm_lists_exclude_recycle_bin_vms`：本日新出现两个序列（正常 VM + 回收站 VM）→ 只有正常 VM 进入 `day_new_vms` / `month_new_vms`。
- `test_v2_cloudtower_client.py`：既有 `_normalize_vm` 用例回归。
- 全量回归（基线 349 OK）。

## 5. 回滚

撤销本条提交即恢复旧行为（回收站 VM 重新计入新建统计）；采集侧过滤同时失效。无 schema/数据变更。

## 6. 验收标准

- `day_new_vms` / `month_new_vms` 中不再出现名字以 `in-recycle-bin-` 开头的 VM。
- 采集不再写入回收站 VM（新采样）。
- 后端全量测试通过。
