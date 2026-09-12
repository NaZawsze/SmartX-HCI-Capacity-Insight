# 预计耗尽稳健预测设计（Phase 15 待办落地）

更新时间：2026-09-12
状态：已定稿，待实施
关联：task_plan.md Phase 15 待办；docs/pending-tasks.md P1 #6

## 1. 问题

`forecast_series()` 的 `exhaustion_days = (capacity - current) / slope`，其中 slope 是**全窗口（最长 365 天）线性回归**斜率。当天迁入一个大 VM 时，单日突增被回归吸收，耗尽天数骤降，被误读为持续风险。

## 2. 方案（向后兼容，不改既有字段语义）

`ForecastResult` 新增可选字段（asdict 自动进入 report/dashboard payload）：

| 字段 | 含义 |
| --- | --- |
| `smoothed_slope_per_day` | 近 30 天点位的线性回归斜率（去离群），即"平滑趋势" |
| `exhaustion_days_30d` | 用平滑趋势计算的稳健耗尽天数（平滑斜率 <=0 时为 None，表示"按近 30 天趋势不会耗尽"） |
| `recent_day_delta` | 最近两个样本点的净变化（近似"近 24 小时增长"） |
| `spike_detected` | `recent_day_delta > 0` 且 `recent_day_delta > 3 × max(smoothed_slope, 1 GiB/天)` 时为 True |

- 既有 `exhaustion_days`/`forecast_30d/60d/90d/180d` 保持全窗口回归口径不变（报表正文与 Word/Excel 不改版式）。
- 判定阈值：倍数 3、下限 1 GiB/天（常量 `SPIKE_MULTIPLIER = 3`、`SPIKE_FLOOR_BYTES = 1024**3`），常量放模块顶部便于调整。

## 3. 消费端

- **Dashboard 风险集群行**：优先显示 `exhaustion_days_30d ?? exhaustion_days`；`spike_detected=True` 时追加提示"近 24 小时增长异常，建议观察多日"。
- **ReportsPage 集群预测行**：耗尽天数同样优先取 30d 稳健口径；`spike_detected` 显示同款提示标签。
- Word/Excel：本批次不改（其 90 天预测使用率与建议文案保持全窗口口径）。

## 4. 测试

- 稳定序列：`spike_detected=False`，`exhaustion_days_30d` 与全窗口口径接近。
- 末点突增（前 60 天 +1 GiB/天，最后一天 +50 GiB）：`spike_detected=True`，`exhaustion_days_30d` 明显大于全窗口 `exhaustion_days`。
- 平滑斜率 <=0（容量下降趋势）：`exhaustion_days_30d=None`。
- 数据不足（<2 点）：新字段为默认值且不抛错。

## 5. 验收

- 远端 .3 真实数据调用 `latest_report()`，payload 含四个新字段且类型正确。
- Dashboard 风险集群行与报表页预测行在无突增时不显示异常提示（回归）。
- 既有测试回归通过。
