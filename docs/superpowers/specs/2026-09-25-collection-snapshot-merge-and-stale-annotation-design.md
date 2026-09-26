# 49-37 手动采集失败清空指标快照修复 + 仪表盘数据过期标注

- 日期：2026-09-25
- 状态：已实施并验证（2026-09-25，.3 部署完成；提交待用户批准）
- 关联任务：task_plan.md 49-37；pending-tasks #23（Tower 不可达）为触发背景

## 1. 背景与根因

用户反馈（2026-09-25）：「有段时间没获取到数据就把我整个看板停了，我认为不合理，应该标注最后更新时间」，随后附截图确认看板数值全空（集群 0、容量 0.00%、已用/总量 0 B，虚拟机仍 244）。

### 1.1 故障链（已在 10.20.11.3 取证）

1. `POST /api/collection/run`（用户点「立即采集」）走 `api/collection.py::run_collection` → 直调 `CollectionService.run_manual_collection`。
2. `run_manual_collection` 末尾 `self._save_metrics_text(metrics_text)`（`collection/service.py:93`）对 `metric_snapshots`（id=1）**整体替换**，只写本次 run 的样本。
3. worker 调度/重试/升级后路径都先抓旧快照、跑完 `_merge_metrics_text(旧, 新)` 合并回写（`worker.py:46/93/138/274/415`，注释明确写了"必须与采集前的旧快照合并"）；**API 手动采集路径没有这层合并**。
4. 2026-09-18 17:43 触发的 `collection_runs` id=65（trigger=manual，全部目标 No route to host，0 成功）→ 快照被替换成仅 357 字节的 HELP/TYPE 表头（`updated_at = 2026-09-18 17:43:48`，与该 run 结束时间一致）。
5. collector-worker `/metrics` 从该次起只输出表头 → Prometheus 抓不到样本 → 仪表盘容量/集群数 instant 查询为空 → 看板归零。
6. 虚拟机数仍显示 244，因为该 KPI 读 SQLite `vm_latest`；容量/集群数读 Prometheus——两者数据源不同，所以出现「虚拟机还在、容量全空」的割裂表现。

### 1.2 影响面

- **每次手动采集只要部分或全部失败，都会抹掉其他成功集群的样本以及历史最后值**（部分失败同样会丢失败目标的旧值）。
- 定时路径不受影响（worker 有合并保护），但只要运维/用户手动点过一次「立即采集」且有失败目标，展示数据即被破坏。
- 已在 .3 造成真实数据展示丢失：Prometheus 内 09-12~09-18 历史样本完好，仅快照指针被抹空。

## 2. 目标与口径

1. **任何调用路径（API 手动、定时、重试、升级后）失败或部分失败时，`metric_snapshots` 都不得丢弃既有样本**——合并语义与 worker 路径完全一致：
   - 同一 sample key（指标名+标签）以本次值为准；
   - 本次未采集到的目标（失败目标 / 被 target_filter 过滤的目标）沿用旧快照最后值；
   - 本次为空（0 成功）时快照原样保留。
2. **看板不因数据过期而清零、不隐藏已有数据**，改为明确标注：
   - 采集状态卡常驻显示「最后成功采集：`<last_success_at>`」；
   - 超过新鲜度停摆阈值（`freshness_threshold_minutes`，与探针同口径）时，看板顶部出现过期提示条 + 采集状态卡显示「数据过期」徽标，文案说明看板为最后一次采集的数据。
3. 不伪造任何数据：过期标注只做时间展示与状态提示，不改写任何指标值。

### 2.1 边界（不做）

- 不改 Prometheus 抓取/查询逻辑，不给 instant 查询加 fallback 到 SQLite。
- 不改采集触发、重试、告警逻辑；不改 `collection_runs` 记录。
- 不改 `freshness` 探针行为（其告警保留）。
- 快照回填（把 Prometheus 09-18 前最后样本写回 `metric_snapshots`）是独立的一次性运维动作，**不在本任务内执行，须单独征得用户确认**。
- 数据源不一致（虚拟机读 SQLite、容量读 Prometheus）的统一属另一议题，不在本任务内。

## 3. 实施方案

### 3.1 快照合并下沉到 `run_manual_collection`

- 新增公共函数 `merge_metrics_text(previous: str, current: str) -> str`（含 sample key 逻辑）到 `app/v2/metrics/formatter.py`（该模块已是 metrics 文本的归属地，且 `collection/service.py` 已依赖它，无循环导入）。
- `worker.py` 删除本地 `_merge_metrics_text`/`_sample_key`，改为 `from app.v2.metrics.formatter import merge_metrics_text as _merge_metrics_text`，既有调用点不变。
- `collection/service.py::run_manual_collection`：
  - 在开始采集循环前 `previous_metrics = self.latest_metrics_text()`；
  - 保存时 `saved = merge_metrics_text(previous_metrics, metrics_text)`，`self._save_metrics_text(saved)`；
  - `CollectionResult.metrics_text = saved`（即"实际落库的文本"）。
- worker 外层 `_save_run_metrics(旧, result.metrics_text)` 保留不动：merge 幂等（`merge(P, merge(P, C)) == merge(P, C)`），双保险且不改变既有结果。

### 3.2 仪表盘过期标注（后端）

- `dashboard/service.py::_latest_collection()` 在现有 `status/message/last_success_at` 基础上追加：
  - `threshold_minutes`：`freshness_threshold_minutes(self.database)`；
  - `data_freshness`：`"fresh" | "stale" | "unknown"`——无成功记录为 `unknown`；时间戳解析失败为 `unknown`；`now - last_success_at > threshold` 为 `stale`，否则 `fresh`。时间解析复用 `freshness._parse_db_time` 的口径（DB 时间按 UTC 解析），为避免跨模块私有调用，在 `freshness.py` 暴露公共别名 `parse_db_time`。
- `api/models.py::DashboardCollectionModel` 补 `threshold_minutes: Optional[int]`、`data_freshness: Optional[str]`（`extra="allow"`，向后兼容）。

### 3.3 仪表盘过期标注（前端）

- `types.ts::DashboardSummary` 补 `collection?: { status?; message?; last_success_at?; data_freshness?; threshold_minutes? }`。
- `DashboardPage.tsx`：
  - 采集状态卡：列表下方常驻一行「最后成功采集：`<格式化时间>`」；`data_freshness === "stale"` 时该行带 `.freshness-badge.stale` 徽标（复用 VM 趋势页既有样式）。
  - 看板顶部（与现有 `cluster-disabled-message` 并列位置）：`stale` 时显示提示条「数据未更新：最近成功采集于 `<时间>`，当前看板显示的是最后一次采集的数据」，复用 `.inline-message` 样式，不新增硬编码色值。
  - 时间格式：无时区后缀的 DB 时间按现有前端惯例 `new Date(...)` 渲染；解析失败回退显示原始字符串。

## 4. 测试计划

后端（本地无法跑 fastapi/pytest，基线测试在 10.20.11.3 执行）：

1. `test_v2_collection.py` 新增：
   - 全失败 run 不清空既有快照（先成功采集 A，再让所有目标失败，断言快照仍含 A 样本、`result.metrics_text` 含 A）；
   - 部分失败保留失败目标旧样本、更新成功目标样本；
   - target_filter 重试只更新目标、不过滤丢弃其他目标旧样本；
   - `merge_metrics_text` 单测（注释去重、同 key 覆盖、空 current 不丢 previous、双方都空返回空）。
2. `test_v2_dashboard_vm.py`/`test_v2_dashboard_vm_api.py`：`collection.data_freshness` 三种状态（fresh / stale / 无成功记录 unknown）+ `threshold_minutes` 透出。
3. 回归：全量 `python -m pytest`（基线 338 OK）。

前端（.3 执行）：

1. `tsc --noEmit` 0 错误；`vitest`（基线 94 passed）。
2. `DashboardPage.test.tsx` 新增：summary 带 `collection.last_success_at` → 渲染「最后成功采集」；`data_freshness: "stale"` → 渲染顶部过期提示条与徽标。
3. `.3` 重建部署后目视：采集状态卡时间行 + 过期提示条（当前 Tower 不可达，预期显示 stale + 09-12 时间）。

## 5. 回滚

- 后端合并逻辑：撤销提交即回到旧行为（worker 路径本就有合并保护，API 路径退回覆盖式）；无 schema 变更，无迁移。
- `DashboardCollectionModel` 新字段 `extra="allow"`，回滚后前端读不到字段走兜底（不显示标注），无破坏。
- 前端仅新增展示行/提示条，回滚即消失。

## 6. 验收标准

- 手动触发一次失败采集（Tower 不可达即为天然条件），`metric_snapshots` 仍含上一次成功样本，`/metrics` 仍有样本，看板不归零。
- 看板采集状态卡显示「最后成功采集：…」，超过阈值时出现过期提示条与徽标。
- 全量后端测试通过、`tsc` 0 错误、vitest 通过。
