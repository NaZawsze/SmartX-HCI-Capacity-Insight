# task-worker 第 6 容器评估报告

更新时间：2026-09-13
关联：task_plan.md Phase 16 设计重点；docs/pending-tasks.md P3 #16；docs/architecture-v2.md

## 1. 评估背景

Phase 16 设计重点：后续如果后台耗时任务明显影响 web-api，再评估新增第 6 个容器 task-worker（报表生成、迁移导入导出、空间清理、批量健康检查）。本次在测试机 10.20.11.3（v0.5.2 + runner v0.3.1）实测评估。

## 2. 后台任务实现现状

| 任务 | 实现 | 是否阻塞 web-api 请求 |
| --- | --- | --- |
| 报表导出（Word/Excel） | 同步（build_report_docx/xlsx 在请求内执行） | 是 |
| 空间清理扫描 | 同步（scan_artifacts 等） | 是 |
| 迁移导出/导入 | `threading.Thread(daemon=True)` 后台线程 | 否 |
| 升级任务 | 提交给 upgrade-runner 执行，web-api 只监督 | 否 |

## 3. 实测数据（10.20.11.3）

基线（无后台任务）：health 平均 0.056s；summary 平均 0.179s。

| 场景 | health 平均响应 | 相对基线 delta |
| --- | --- | --- |
| 基线 | 0.056s | — |
| Word 报表导出期间（同步，导出 5.26s） | 0.096s | +0.040s |
| 空间清理扫描期间（同步，扫描 0.04s） | 0.052s | -0.004s |
| 迁移导出期间（后台线程，导出 0.96s） | 0.053s | -0.002s |

## 4. 结论

- 最可能阻塞的同步任务（Word 报表导出）执行期间，web-api health 响应仅上升约 40ms（0.056s → 0.096s），仍远低于"明显影响"阈值（百毫秒级）。
- 空间清理扫描、迁移导出（后台线程）对 web-api 响应无影响。
- 当前后台任务对 web-api 响应**无明显影响**。

**结论：当前不新增 task-worker 第 6 容器**，保持 5 容器模块化单体（web-api/collector-worker/frontend/prometheus/upgrade-runner），符合 AGENTS.md 架构边界与 architecture-v2.md 的评估触发条件（"后台任务明显影响 web-api 响应时才评估"）。

## 5. 后续触发条件

当出现以下任一情况时，重新评估新增 task-worker：
- 报表导出耗时显著增长（如大数据量下 > 30s）且用户可感知页面卡顿。
- 迁移导入导出、空间清理等后台任务与正常 API 请求并发时，web-api 响应超过可接受阈值。
- 单 web-api 进程 CPU/内存成为瓶颈。
