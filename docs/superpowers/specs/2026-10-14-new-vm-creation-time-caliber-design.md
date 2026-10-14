# 「新建 VM」口径升级设计（pending #36 / #37）

- 日期：2026-10-14
- 来源：pending-tasks #36 / #37（49-40/49-42 折中口径的遗留）；探针 `scripts/probe_tower_vm_created_at.py`
- 状态：**设计（待确认两处口径 + Tower 探针恢复后实施 ①）**

## 1. 背景与现状

**问题**：现在判断「本日/本月新建 VM」用的是**平台侧近似口径**——"该 vm_id 在 Prometheus 全历史
（400 天）窗口内的最早样本时间"（`vms/new_vm.py::collect_vm_first_seen`，49-42/49-43 折中）。
采集断档（Tower 不可达）期间创建的 VM，其"最早样本"只能落在恢复采集当天，于是被整批判成"新建"
（`.3` 实测：本月新建 199 台 → 折中后 6 台，但断档期创建的机器仍无法归到真实创建日）。

**Tower 侧可用字段**（CloudTower API 文档已确认，2026-09-26）：
- `Vm.local_created_at` —— VM 真实创建时间
- `Vm.in_recycle_bin` —— 权威回收站标记（`VmWhereInput` 可服务端过滤）
- `Vm.original_name` —— 回收前名字

**`.3` 实测（2026-10-14，只读 DB 诊断）**：
- `vm_latest` 203 行；`in_recycle_bin=1` 3 行，与"名字带 `in-recycle-bin-`"**完全一致**（3 行）；
  `original_name` / `deleted_at` 各 3 行有值（如 `内部软件测试机1-推广组`，deleted `2026-10-12T03:53:34Z`）。
- `vm_latest` **没有** `local_created_at` 列 → ① 需要新增列 + 采集侧取字段。
- 展示过滤已是"**标记优先 + 名字前缀兜底**"（`vms/service.py::_recycled_vm_keys`、
  SQL `(r.in_recycle_bin = 1 OR r.name LIKE 'in-recycle-bin-%')`）→ ② 在**展示层已基本落地**；
  剩余是 **series 路径**（`dashboard/service.py:469/519`、`vms/growth.py`）**只用名字前缀**。

**探针受阻（2026-10-14）**：Tower `10.20.11.7:4433` 当前连接被重置
（`.3` 宿主 `curl` 8s 超时 000；容器 TCP 可连但 HTTPS 登录 `[Errno 104] Connection reset by peer`；
同日 13:15 的采集 #544 还是成功的 → 端点间歇性不可用）。**① 的字段格式（是否存在/时区/精度）
必须等 Tower 恢复后用探针确认**：
`docker exec -i <web-api 容器> python - --configured --tower-id 3 < scripts/probe_tower_vm_created_at.py`

## 2. 目标与口径

| 项 | 目标 | 口径 |
| --- | --- | --- |
| **①** | 「本日/本月新建 VM」改用 Tower 真实创建时间 | 以 `local_created_at` 落在 `[周期起点, now]` 判定；**取不到该字段时回落现有"全历史首见"口径**（不猜、不填假值） |
| **②** | 回收站过滤统一用权威标记 | 以 `vm_latest.in_recycle_bin` 为**唯一权威**；名字前缀仅作**兜底**（兼容历史行） |
| **③** | 展示回收前名字 | 展示层用 `original_name`（缺失回落 `name`），**但不改变用于过滤的"身份名"** |

## 3. 两个必须先定的口径问题（阻塞实施）

**Q1：series 路径怎么拿到权威标记？** Prometheus 指标标签里**没有** `in_recycle_bin`
（它是 DB 列）。要在这条路径按标记过滤，三选一：
- **A（推荐）**：从 `vm_latest` 取"回收站 vm_id 集合"，作为参数传入 `compute_growth_vms` /
  新建 VM 收集函数（与 `vms/service.py::_recycled_vm_keys` 同源，零指标变更）；
- B：把标记加进 Prometheus 指标标签——**不推荐**（改指标基数与 schema，历史数据无法回填）；
- C：维持前缀判定——**接受局限**（Tower 改名规则变化即失效）。

**Q2：「身份名」与「显示名」如何分离？** 直接让 `_latest_vm_names()` 返回 `original_name` 会
**破坏按前缀过滤的 series 路径**（回收站 VM 会被判成"非回收站"而混进新建/增长列表）。
故 ③ 必须**只改 API 输出层**（新增 `display_name` 或仅在展示 DTO 里替换），
内部过滤仍用 `name`。

## 4. 实施面（待 Q1/Q2 确认后开工）

| 步骤 | 文件 | 内容 |
| --- | --- | --- |
| ①-a | `cloudtower/client.py` | `_normalize_vm` 增加 `local_created_at`（探针确认字段名/格式后） |
| ①-b | `v2/database.py` | `vm_latest` 增加列 `local_created_at TEXT`（expand-only 迁移，随下版计划） |
| ①-c | `v2/collection/service.py` | upsert 写入该列（缺失写 NULL） |
| ①-d | `v2/vms/new_vm.py` + `dashboard/service.py` + `reports/service.py` | 新建 VM 判定优先用 `local_created_at`，缺失回落首见口径；**概览与报表同源**（延续 49-43 纪律） |
| ② | `dashboard/service.py`、`vms/growth.py` | 按 Q1 选定方案统一过滤口径 |
| ③ | `v2/vms/service.py` 等展示层 | 按 Q2 输出 `original_name`（回落 `name`） |
| 测试 | `backend/tests/test_v2_dashboard_vm.py` 等 | ① 三种形态（有字段/无字段/字段为空）+ ② 标记与前缀不一致时以标记为准 + ③ 显示名不影响过滤 |

## 5. 边界与不做

- **不动统计口径**：已使用/已分配/容量预测继续含回收站（用户 2026-10-03 口径，见 #75/#77）；
  本任务只动"新建 VM 判定"与"展示名"。
- **不改 Prometheus 指标 schema**（除非 Q1 选 B，且需另立设计）。
- **不伪造**：字段缺失一律回落 + 如实记录，不猜创建时间。
- 回滚：纯增量（新列可留空、判定有回落），`git revert` 即可；无数据破坏风险。

## 6. 验收（草案）

1. `.3`：`local_created_at` 落库非空率与 Tower 侧一致；「本月新建 VM」数与 Tower 界面口径吻合
   （断档期创建的 VM 归到真实创建日）。
2. 概览与报表「本日/本月新建 VM」两页数字一致（延续 49-43）。
3. 回收站 VM 不出现在新建/增长列表（标记与前缀故意不一致时**以标记为准**）。
4. 后端全量无新增失败；前端零改动（本任务无 UI 结构变更）。
