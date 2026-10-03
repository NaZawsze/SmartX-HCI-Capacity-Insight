# 设计：#75 已分配容量终版口径 + #77 残留卷行清理

- 日期：2026-10-03
- 关联任务：`docs/pending-tasks.md` #75、#77
- 取代：`docs/superpowers/specs/2026-10-02-dashboard-migration-five-issues-design.md` §「问题 6：已分配容量口径错位」中
  的「性能层已分配（`perf_allocated_data_space`）+ UI 标签写『性能层已分配』」方案（用户否决：不要性能层指标）
- 事故/实测记录：`progress.md` 2026-10-03 #77 节
- 状态：已实施并在 `.3` 真机验证

## 1. 背景：两个独立缺陷

`已分配` 指标在当时同时有两个问题，前者是**口径错**，后者是**数据残留**，必须一起修，
否则修了口径仍会被残留行撑大。

| # | 现象 | 根因 |
| --- | --- | --- |
| #75 | 页面「已分配」与 CloudTower 界面语义对不上；早期实现取 `perf_allocated_data_space`（性能层），用户明确表示不是他要的 | 取数口径错：用户要的是「所有虚拟机共分配了多少存储」，即 **Σ(每卷供给容量 × 副本数)** |
| #77 | `.3` 界面 `已分配` 172.28 TiB，而库内 Σ 达 214.04 TiB，差 **40.79 TiB** | 49-47 给 `vm_latest` 做了「采集成功后核对删除」，`vm_volumes` **没有**对应机制——Tower 侧 VM/卷早已删除，平台卷行永久残留 |

## 2. #75 终版口径（用户 2026-10-03 决策）

**已分配 = Σ(每台 VM 的每个虚拟卷供给容量 × 该卷副本数)**，EC 卷按 `(k+m)/k` 折算。

- 计算位置：**采集流程内**（`CloudTowerClient.collect_cluster`），卷数据此时都在手上；
  随集群样本落库为 `smartx_cluster_storage_allocated_bytes`。
  **页面访问零计算**：dashboard 直接读已存好的指标值。
- 回收站 VM：**计入**。理由（用户原话「已使用和已分配都用全部数据，包含回收站」）：
  - 回收站卷的物理块仍被 Tower 计入 `used_data_space`（平台无法扣）；
  - 容量预测基于「已使用」（`reports/service.py::_cluster_series` 读 `CLUSTER_USED_METRIC`），
    两个指标必须同口径，否则预测与展示对不齐；
  - 排除会出现 `已分配 < 已使用` 的反常关系。
- 已废弃：`perf_allocated_data_space`（性能层）取数路径与「性能层已分配」标签全部移除。
- 入库保留：回收站 VM 仍写 `vm_latest`（`in_recycle_bin=1`）与 `vm_volumes`，为将来回收站功能留数据。

## 3. #77 残留清理（用户 2026-10-03 决策）

**Tower 是 VM 与卷行的唯一事实源**：某塔/集群**本次采集成功后**，Tower 未返回的 VM 即已删除。

- `_purge_missing_vms`：不限 `in_recycle_bin`，普通 VM 与回收站 VM **同口径**删 VM 行，
  **并删其卷行**。（旧实现只清 `vm_latest`，卷行永久残留 → 40.79 TiB 虚高。）
- `_purge_orphan_vm_volumes`：兜底扫掉「没有对应 VM 行」的卷行，
  覆盖历史遗留（旧版本已删 VM 行但卷行还在）。
- **守卫不变**：只在**该塔/集群采集成功**后调用；采集失败一律不动（防整集群误删，回归测试锁死）。
- 页面展示口径（是否不显示回收站 VM 及其卷）**仍待定**：当前三个卷 API 与 VM 列表都不过滤
  `in_recycle_bin`，要改需另立一项。

## 4. 边界与风险

| 风险 | 处置 |
| --- | --- |
| 采集返回集合为空 = 误删全集群？ | `get_vms` 分页失败会抛错 → 该目标记为 failed，**不进入核对分支**；只有成功采集才核对 |
| 长期断档（如 `.3` 停摆 20 天）后首次采集 | 正常路径：Tower 返回的就是当前全集，缺失即已删除；这正是残留被清掉的原因 |
| 副本数为 0（策略缺失） | `replica_num` 缺失按 0 计（不虚增），EC 卷按 `(k+m)/k` |
| 回滚 | 改动集中在 `cloudtower/client.py::collect_cluster`、`collection/service.py` 两个采集模块，`git revert` 即可；已写库的历史指标值不受影响 |

## 5. 验证（证据）

- `.3` 全量后端 **758 tests OK (skipped=7)**（Python 3.12 容器内，含本设计的 4 个定向用例）。
- `.3` **真机**（r11 实例 + 新代码跑真实采集）：

  ```text
  BEFORE: vm_latest=248 vm_volumes=373 orphan_vol=1 recycle_vm=2 sigma_alloc=213.06 TiB
  collection status = success | 采集完成：1 个集群，197 台虚拟机。
  AFTER : vm_latest=197 vm_volumes=279 orphan_vol=0 recycle_vm=2 sigma_alloc=171.88 TiB
  ```

  即清理 51 台已删 VM 行 + 94 条残留卷行，`已分配` 由 213.06 → **171.88 TiB**（−41.18 TiB）。
- `.3` 看板接口同源读数：`allocated_bytes = 188989298442240`（171.88 TiB），
  `used_bytes = 38593065123840`（35.10 TiB），`total_bytes = 240988182282240`（219.21 TiB）——
  三者关系恢复正常（已使用 < 已分配 < 总容量），回收站 VM（2 台）仍保留在库。
