# 采集新鲜度探针（web-api 跨容器互检）设计

日期：2026-09-19 ｜ 状态：实施中 ｜ 关联 task_plan Phase 49 第 20 项

## 背景

数据质量检查（`DataQualityService.evaluate_and_alert`）接线在 worker 的采集结束路径上，覆盖"worker 活着但链路中段断裂"的场景（最多一个采集间隔内告警）。但当 collector-worker 容器整个挂掉/卡死时，采集、data-quality、容量告警检查全部停止（同进程），任务中心不会有任何新条目，唯一发现方式是人眼注意"数据截至"变陈旧。web-api 是独立容器，在 worker 死亡时仍存活，适合承担跨容器互检：周期性检查"是否太久没有成功采集记录"并主动告警。

## 口径

### 信号

- 数据源：SQLite `collection_runs` 表，`SELECT * FROM collection_runs WHERE status='success' ORDER BY COALESCE(finished_at, started_at) DESC, id DESC LIMIT 1`。
- `started_at/finished_at` 为 SQLite `CURRENT_TIMESTAMP`（UTC，`YYYY-MM-DD HH:MM:SS` 文本）；比较用 `datetime.now(timezone.utc)`，解析失败视为 unknown（不告警，记日志，避免格式漂移误报）。

### 阈值

- 复用 data_quality 的口径：`max(2 × min(启用 Tower 生效采集间隔), 60)` 分钟（daily 模式按 1440 计）。
- 实施方式：把 `DataQualityService._freshness_threshold_minutes` 抽为 `data_quality/service.py` 模块级函数 `freshness_threshold_minutes(database)`，原方法保留为委托（不破坏既有测试与调用）。

### 触发规则（`evaluate()` 三态）

前提：存在启用的 Tower（`towers WHERE enabled=1`）；否则 `skipped`（不告警）。

1. `stale`：存在 success 记录且距今超过阈值；或（无任何 success 记录且探针所在 web-api 进程已运行超过阈值）——后者覆盖"worker 从未成功跑起来"的新部署场景。
2. `ok`：最新 success 距今未超阈值。
3. `unknown`：有记录但时间解析失败；不告警，记日志。

### 告警

- 固定 task_id `collection-freshness-stale`，`TaskType.COLLECTION`，状态 FAILED（复用 `tasks.create_task` 的 INSERT OR REPLACE 语义：持续异常时每周期刷新未读徽标但不刷屏；恢复后不自动消除，与 data-quality 告警口径一致）。
- 明细（明文，可执行）：最近成功采集时间、无记录时说明"从未有成功采集记录"、阈值分钟数、建议检查 collector-worker 容器状态。

### 调度

- web-api `create_app` 的 startup 钩子里启动 daemon 线程：循环 `evaluate_and_alert()` → `Event.wait(interval)`；单轮异常吞掉并记日志（对齐 worker `_run_data_quality_check` 的容错风格）。
- 周期：默认 600 秒；env `SMARTX_FRESHNESS_PROBE_INTERVAL_SECONDS` 覆盖，`<=0` 时不启动线程（运行期关闭开关，也用于测试隔离）。
- shutdown 时 set Event 结束线程。

### 边界与已知重叠

- worker 活着但连续采集失败：探针在 2×间隔后同样告警，与 worker 自身的采集失败告警并存——信号不同（"我在失败" vs "太久没有成功"），属可接受重叠。
- Prometheus 整体故障但不影响采集：探针不关心 Prometheus（中段断裂由 worker 侧 data-quality 覆盖），不做 Prometheus 查询，探针自身零网络依赖。
- 探针只读 SQLite 与写任务中心，不新增容器、不新增第三方依赖（纯 threading）。

## 测试计划

- 单测（新 `backend/tests/test_v2_freshness.py`）：ok/stale/skipped 三态；无 success 记录 + 探针运行超阈值 → 告警；解析失败 → unknown 不告警；阈值函数与 data_quality 口径一致；`evaluate_and_alert` 写入固定 task_id 且重复触发为替换。
- 本地定向测试后进 .3：全量回归 + 部署后确认探针线程日志、`docker compose exec web-api python -c` 手动 `evaluate()` 对真实库返回 ok（不杀 worker 容器做破坏性验证）。

## 回滚

- 单提交独立回滚；或运行期 env `SMARTX_FRESHNESS_PROBE_INTERVAL_SECONDS=0` 关闭线程（compose 加 env 即可，无需回滚代码）。
