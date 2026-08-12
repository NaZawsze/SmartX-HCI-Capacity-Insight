# UPG-044 Verification 与历史查询无副作用设计

## 问题

`UpgradeService.history()` 以 `task.json` 的文件 mtime 倒序，并在读取每个历史任务时调用有副作用的 `_normalize_completed_runner_task()`。历史任务被补归一化或补建 post-cleanup 后，旧 `task.json` 的 mtime 会刷新到当前时间。`verification()` 再取 `history()` 中第一个成功平台包，因此可能把旧包显示为“最近成功包”。

历史 GET 请求还可能创建 cleanup 任务并执行旧环境清理，违反查询接口应只读的边界。

## 设计边界

1. `status(task_id)` 保持当前职责：收敛当前 runner 任务、持久化终态、投影任务中心，并按现有协议创建 post-cleanup。
2. `history()` 改为纯读：读取 task.json 后只生成内存中的历史视图，不保存文件、不更新任务中心、不创建 cleanup。
3. 如果历史任务的 raw status 尚未收敛，但 execution plan 的 action 全部为 `succeeded/skipped`，历史视图可在内存中显示为 `success`；磁盘内容保持不变。
4. history 使用稳定业务时间排序：优先 `created_at`，其次 `uploaded_at`、`started_at`、`finished_at`、`updated_at`，最后使用 task id 保证确定性；不得读取文件 mtime。
5. verification 不依赖 history 当前顺序。它在真实成功平台包中按 `finished_at` 排序，缺失时依次回退 `uploaded_at`、`created_at`、`started_at`、`updated_at`，最后使用 task id；不得读取文件 mtime。

## 实现结构

- 新增纯函数/纯方法，将“全部 action 已完成”的 runner task 转换为只读 success 视图。
- `_normalize_completed_runner_task()` 继续作为当前任务持久化路径，复用纯视图判断后执行 save、task projection 和 cleanup scheduling。
- `history()` 使用纯视图并在读取全部任务后按业务时间排序。
- `verification()` 对 success platform candidates 显式使用成功包时间键选择最大值。

## 错误处理

- 时间字段为空或格式无效时视为最早时间，不抛出 500。
- naive datetime 按 UTC 处理，带时区 datetime 转为 UTC。
- 所有时间均无效时以 task id 作为稳定排序兜底。
- 不删除、不改写历史任务，也不修改现有任务数据来修饰 verification 结果。

## 测试

1. 旧包 task.json mtime 晚于新包，但新包 `finished_at` 更晚时，verification 必须选择新包。
2. history 读取带 cleanup 配置的历史成功任务时，不创建 cleanup task，不改变 task.json mtime/内容。
3. raw status 为 running、全部 actions 已完成的历史任务在返回值中显示 succeeded，但磁盘仍保持 running，且不创建 cleanup。
4. history 在 mtime 与业务创建时间相反时，按业务创建时间倒序。
5. 既有 status 路径仍能持久化完成任务并创建 post-cleanup。

## 验收

- 10.20.11.3 当前 verification 始终返回本次 fix3：`upgrade-7d86beb3c459bc0a` / SHA `3722d788...`。
- 连续调用 history、verification 和 release smoke 后，结果不回退。
- 调用前后历史 task.json SHA/mtime 不变，不新增旧任务 post-cleanup。
- 当前 v0.5.2、runner v0.3.1、Prometheus、业务数据和自动采集状态保持不变。
