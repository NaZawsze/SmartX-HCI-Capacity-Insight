# P2 运维批次设计（基线产物化 / 新鲜度告警 / 重试调度化）

更新时间：2026-09-12
状态：已定稿，待实施
关联：task_plan.md Phase 49-7/49-10；docs/pending-tasks.md P2 #9/#10/#11

## 1. 标准业务基线产物化（#9）

新增 `scripts/capture_baseline.py`（仅标准库，宿主机 python3 可直接运行）：

- **capture 模式**：
  ```bash
  python3 scripts/capture_baseline.py capture \
    --name upg-baseline-20260912 \
    --db /data/smartx.db \
    --env /data/smartx-storage-forecast/project/.env \
    --output /home/user1/codex-build/baselines \
    [--prometheus /data/smartx-storage-forecast/prometheus | --skip-prometheus]
  ```
  - SQLite 用 `VACUUM INTO`（只读 URI 打开源库）生成一致性快照，**不需要停服务**。
  - `.env` 复制为 `tower.env` 并 `chmod 600`。
  - Prometheus 目录整目录复制（默认包含；`--skip-prometheus` 可跳过）；manifest 标注 `prometheus_copy: "live"`——Prometheus 运行中直接复制，head block 可能在变化，恢复后建议立即触发一次采集对齐。
  - 产物目录：`<output>/<name>/{smartx.db, tower.env, prometheus/, SHA256SUMS, manifest.json}`。
  - `manifest.json`：created_at、源路径、`db_counts`（users/towers/clusters/vm_latest/vm_volumes/collection_runs 行数）、文件清单。
  - `SHA256SUMS`：产物内每个文件一条（排除自身）。
- **verify 模式**：
  ```bash
  python3 scripts/capture_baseline.py verify --dir <产物目录>
  ```
  校验：SHA256 全部一致、`PRAGMA integrity_check` = ok、`db_counts` 与 manifest 一致；全过输出 `baseline ok` 退出码 0。
- 与 `verify_full_upgrade_chain.py` 的关系：该脚本"基线恢复需在执行前单独完成"，本脚本提供恢复前的标准产物与恢复后校验输入；恢复动作（停服→拷回→起服）仍按既有手册执行，不在本脚本范围。

## 2. 数据新鲜度链路告警（#10）

`DataQualityService.evaluate()` 增加两项检查（结果进 `freshness` 字段与 messages，走既有"数据质量需关注"告警通道）：

| 检查 | 条件 | 结果 |
| --- | --- | --- |
| 采集停摆 | 最近一次成功采集 `finished_at` 距今 > `SMARTX_FRESHNESS_STALE_MINUTES`（默认 180） | warning：`最近成功采集距今 X 小时，超过新鲜度阈值 N 分钟。` |
| Prometheus 滞后 | 最近成功采集时间 − Prometheus 最新样本时间 > 15 分钟（两者都存在时） | warning：`Prometheus 样本滞后最近成功采集 X 分钟，导出/抓取链路可能中断。` |

- 语义：只解释可信度并告警，不修改数据、不影响预测算法。
- 注意：首次部署/刚清空采集记录时不误报（无成功采集记录时跳过采集停摆检查，由既有"最近采集状态"逻辑覆盖）。

## 3. worker 采集重试调度化（#11）

现状：`run_collection()` 内联 for 循环 + `time.sleep(interval×60)`，最长阻塞调度线程约 45 分钟，且重试期间数据质量检查被推迟。

变更：

- `run_collection(database, scheduler=None)`：计划采集后仅在**有失败目标**时调用 `_schedule_retry_cycle(scheduler, ...)` 注册一次性重试 job；数据质量检查改为**每次计划采集后立即执行**（不再等重试结束）。
- `_schedule_retry_cycle(scheduler, database, *, attempt, max_attempts, targets)`：
  - 取重试计划最小间隔，`DateTrigger(run_date=now + interval)` 注册 job `collection-retry-{attempt}-{run_at_ts}`（`max_instances=1`、`replace_existing=True`）。
  - `scheduler=None` 时退回内联 `time.sleep` 循环（兼容单测与无调度器调用路径）。
- `_run_retry_cycle(scheduler, database, *, attempt, max_attempts, targets)`：
  - 执行 `run_manual_collection(trigger="retry", attempt=..., max_attempts=..., target_filter=targets)`；
  - 合并指标：`_merge_metrics_text(metrics_body(database).decode(), retry.metrics_text)` 后 `_save_metrics_text`（保留此前成功目标的样本）；
  - 仍失败且 `attempt < max_attempts` → 继续注册下一轮；终态失败 → `_record_collection_warning`；终态（成功或最终失败）→ `_run_data_quality_check`。
- 重试 job 在内存中（BackgroundScheduler 不持久化）：worker 重启丢失未执行的重试属可接受行为——下一次计划采集会对全部目标重试。
- `record warning` 时机变化：从"首跑后固定在重试结束"变为"终态时"，任务中心语义不变。

## 4. 测试

- `scripts/capture_baseline.py`：unittest 通过 subprocess 调 capture + verify（临时目录内构造假 db/env），断言 SHA、integrity、counts。
- DataQuality：旧 finished_at → 停摆告警消息；Prometheus 滞后 → 滞后消息；无成功记录不误报。
- worker：FakeScheduler + mock service 断言——失败时注册 date job、重试成功不再注册、终态失败记录 warning、数据质量检查立即执行。
- 远端 .3：全量回归 + 三镜像部署 + 健康检查；基线脚本在 .3 真机 capture + verify 一轮（产物存 `/home/user1/codex-build/baselines/`）。

## 5. 验收

- [ ] capture → verify 闭环在 .3 真机通过，manifest 含 counts 与 SHA。
- [ ] 把系统时间感知的新鲜度检查用旧记录触发一次"数据质量需关注"告警（测试机 DB 注入旧 finished_at 后恢复）。
- [ ] 制造一次采集失败（临时改错一个 Tower 地址后恢复），观察重试 job 注册且调度线程不再阻塞。
- [ ] 全量回归通过。
