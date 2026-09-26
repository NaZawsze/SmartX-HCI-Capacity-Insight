# 回收站 VM 生命周期同步：记录 → 彻底删除后本地一并删除（49-47）

- 日期：2026-09-26
- 状态：已实施并验证（2026-09-26，.3 后端 362 tests OK / tsc 0 / vitest 107 passed / 真实库升级验证通过；提交待用户批准；端到端待 Tower 恢复）
- 关联任务：task_plan.md Phase 49 第 47 条；pending-tasks #43；口径修正见 #40
- 触发：用户 2026-09-26 提出：从 Tower 采集 `in_recycle` 信息、后台记录"哪台虚拟机被删了、叫什么"；Tower `retain` 天后自动彻底删除，每天采集时核对，**取不到即彻底删除，我们这边也删除**

## 1. 背景与口径

### 1.1 字段与身份（已由本地 CloudTower API 4.8.0 文档 + 实测确认）

- `Vm.in_recycle_bin`（bool）、`Vm.deleted_at`、`Vm.original_name`、`Vm.local_created_at`
- **VM 进回收站后 `id` 不变**：`MoveVmToRecycleBin` 以 `VmWhereInput`（按 vm id）操作；Prometheus 历史实测 4 台回收 VM「真实名 → `in-recycle-bin-<uuid>`」而 vm_id 不变 → 可直接与本地 `vm_latest.vm_id` 对应，名字里的 uuid 只是展示名
- 回收站没有独立实体（`NestedVmRecycleBin` 只有 `{enabled, retain}`）；`retain`（天）到期后 Tower 自动彻底删除

### 1.2 保留与删除（用户口径，2026-09-26 确认）

- 回收站期间：**记录**（哪台、原名、删除时间）；KPI 继续计入（#40）
- **哪天 `get-vms` 取不到了 = Tower 已彻底删除 → 我们也删本地行**（保留期 = Tower 的 `retain` 天，不是永久保留）
- 展示侧仍不显示删除 VM（列表排除），后台可查

### 2.1 边界（不做）

- 不改 KPI 计数口径（仍含回收站 VM，见 #40）
- 展示/筛选 UI 不做（用户暂无需求）
- 只对**回收站标记行**做"消失即删"；普通行即使从 Tower 清单消失也不删（可能被移动/禁用，无删除语义）

## 3. 实施方案

### 3.1 schema（`backend/app/v2/database.py`）

- `vm_latest` 新增三列：`in_recycle_bin INTEGER NOT NULL DEFAULT 0`、`original_name TEXT`、`deleted_at TEXT`
- 既有库走 `_ensure_column` 升级（与项目既有模式一致）；旧行回填默认 `0`

### 3.2 采集（`cloudtower/client.py` + `collection/service.py`）

- `_normalize_vm` **不再丢弃**回收站 VM（49-40 的丢弃撤回），改为输出 `in_recycle_bin` / `original_name`（仅回收站状态保留，恢复后清空）/ `deleted_at`
- `VmCapacitySample` 增三字段（仅影响落库，不进 metrics 渲染）；`_upsert_latest_vm` 写入并覆盖（恢复采集时标记自动清零）

### 3.3 彻底删除核对（同文件）

- 每个塔/集群**采集成功后**调用 `_purge_missing_recycle_vms(tower_id, cluster_id, kept_vm_ids)`：
  - 删除 `in_recycle_bin = 1` 且不在本次返回清单中的行
  - **安全闸门**：只在 `try` 成功路径调用（`collect_cluster` 抛异常 → 不核对），避免一次采集失败把整集群误判为删除

### 3.4 展示侧

- 无需改动：回收站 VM 的 `name` 被 Tower 改成 `in-recycle-bin-*` 后，49-40 的名称前缀过滤自然生效（此前"49-40 之后被删的 VM 保留旧名"的漏洞也被补齐）

## 4. 测试计划（已执行）

1. `test_normalize_vm_records_recycle_bin_fields`：回收站 VM 不再为 None，标记/原名/删除时间齐全；正常 VM 标记清零
2. `test_collection_records_recycle_bin_vm_lifecycle`：落库三字段正确（`in_recycle_bin=1`、`original_name`、`deleted_at`）
3. `test_collection_purges_recycle_vm_after_tower_deleted_it`：第二轮清单不含回收站 VM → 该行被删；同轮缺失的**普通行不删**
4. `test_collection_does_not_purge_when_target_fails`：采集失败 → 任何行都不删
5. `test_vm_latest_recycle_columns_fresh_and_upgrade`：新库建表 + 既有库（旧 schema）`initialize()` 升级后三列存在、旧行默认值回填
6. 全量回归：.3 后端 **362 tests OK (skipped=1)**；前端 `tsc -b` 0、vitest **107 passed（11 files）**

## 5. 验收与部署证据

- .3 真实库（590 行）重启后 `PRAGMA table_info(vm_latest)` 三列存在（`columns_ok=True`），旧行 `in_recycle_bin` 回填 0
- `health 200` / `web 200`；Tower 恢复采集后：回收站 VM 首次成功采集即被标记，彻底删除后自动清除行（端到端待 Tower 恢复验证）

## 6. 回滚

撤销提交即回到"采集丢弃回收站 VM"（49-40）行为；三列为新增、旧代码忽略，无数据破坏。已删除的行不可自动恢复（语义上其数据在 Tower 已不存在）。
