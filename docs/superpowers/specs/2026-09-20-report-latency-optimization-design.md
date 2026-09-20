# 报表接口延迟优化（第一阶段：请求内查询去重）设计

日期：2026-09-20 ｜ 任务：pending-tasks #28 第一阶段 ｜ 状态：已实施

## 背景与基线

2026-09-20 在 .3（1 Tower / 1 集群 / 590 VM）实测 `GET /api/reports/latest`：

- 总耗时 593-732ms，四档 chart_days 无差异；
- Prometheus 调用 15 次、共 471ms，其中**三次几乎相同的 VM 序列查询占 395ms**：
  1. `ReportService._vm_series(days=30, step=6h)`（vm_series，130ms）
  2. 同一方法再来一次（window_vm_series，window_days=30 时与上者完全同参，149ms）
  3. `DataQualityService.evaluate` 内部第三次发起同一查询（裸指标名，116ms）
- 集群 30d/1d 步长查询同样存在 3 份重复（窗口序列、月增速序列、数据质量各自拉一遍，~26ms）；
- payload 292KB（HTTP 层 463KB），其中 `month_new_vms` 288KB 占 99%（当月新增 VM 全量明细，前端只展示前 20）。

## 口径

- **本阶段只做延迟优化，零行为变化**：同一请求内对 Prometheus 的相同查询（相同 query/start/end/step）只发起一次网络调用，命中请求内 memo。
- 不改响应结构、不改列表数量、不改预测/数据质量语义——memo 返回与原查询逐字节相同的结果对象。
- payload 瘦身（month_new_vms 288KB）涉及 `/api/reports/latest` 契约决策（limit 参数），留给第二阶段，本设计不做。

## 方案

`backend/app/v2/reports/service.py`：

1. 新增模块级 `_MemoPrometheus` 装饰器类：包装现有 prometheus 客户端，`range`/`instant` 以 `(query, start, end, step)` / `query` 为键做请求内缓存，其余属性 `__getattr__` 透传。
2. `latest_report` 进入时把 `self.prometheus` 换成 memo 实例、`finally` 恢复原实例。ReportService 为每请求实例化（FastAPI Depends），无并发共享问题；DataQualityService 在方法内以 `prometheus=self.prometheus` 构造，自动共享同一 memo——三处重复 VM 查询与两处重复集群查询天然命中。
3. 命中安全性：核查 reports service 与 data_quality 全部下游消费均为重建新列表（comprehension），无对 Prometheus 返回列表/序列字典的原地修改，共享同一对象安全。

## 预期

- .3 基线 593ms → 约 300ms（省去 2 次 VM 查询 ~265ms + 2 次集群查询 ~23ms），`docker exec` 内复测对比。
- 后续可选（不在本阶段）：剩余串行调用并行化（预估再省 ~50ms）；payload 瘦身第二阶段（limit 契约）。

## 测试与回滚

- 新增单测：包装计数 fake，断言同参 range 查询只触达底层一次、结果一致。
- 全量回归（.3，335 tests 基线）+ 报表三套件定向。
- 回滚：单提交 revert 即可，无数据/契约影响。

## 任务项

- [x] 设计（本文档）
- [x] 实施 `_MemoPrometheus` + latest_report 接线
- [x] 单测（同参查询去重断言）
- [x] .3 验证：reports 三套件 + 全量回归 + 基线复测对比
