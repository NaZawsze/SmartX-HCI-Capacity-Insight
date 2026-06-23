# v2 API 契约设计

更新时间：2026-06-06

## 1. 通用规则

- 除登录外，所有 API 默认需要鉴权。
- 时间按平台时区展示，内部可使用 UTC 存储。
- scope 参数统一为 `tower_id` 和 `cluster_id`。
- 后台任务统一返回 `task_id`，后续通过 task API 查询。
- 文件下载通过任务 artifact 或专用 download API。

通用错误：

```json
{"detail": "错误说明"}
```

## 2. 认证

### `POST /api/auth/login`

请求：

```json
{"username": "admin", "password": "******"}
```

响应：

```json
{"access_token": "...", "token_type": "bearer", "username": "admin"}
```

### `GET /api/me`

响应：

```json
{"username": "admin", "is_admin": true}
```

### `PUT /api/me/password`

请求：

```json
{"current_password": "...", "new_password": "...", "confirm_password": "..."}
```

响应：

```json
{"ok": true}
```

## 3. Tower 和集群

### `GET /api/towers`

返回 Tower 列表，包含集群摘要，不返回明文凭据。

### `POST /api/towers`

创建 Tower。支持 URL、用户名密码、API token、TLS 校验配置。

### `PUT /api/towers/{tower_id}`

编辑 Tower。凭据为空时表示不修改原凭据。

### `DELETE /api/towers/{tower_id}`

删除 Tower。删除前端需提示会影响该 Tower 的 scope 展示。

### `POST /api/towers/{tower_id}/test`

测试连接并同步集群。

响应：

```json
{"ok": true, "message": "连接成功，发现 3 个集群。", "clusters": []}
```

### `PUT /api/towers/{tower_id}/clusters/{cluster_id}`

启用/禁用集群。

请求：

```json
{"enabled": true, "name": "cluster-a"}
```

## 4. 采集

### `POST /api/collection/run`

手动触发采集。

响应：

```json
{"run_id": 1, "status": "success|partial_failed|failed", "message": "采集完成"}
```

### `GET /api/collection/runs`

返回最近采集记录。`status=partial_failed` 表示部分 Tower/集群成功、部分失败；成功目标已写入 SQLite 当前态和 Prometheus，失败目标不写新样本。

### `GET /api/collection/runs/{run_id}`

返回采集详情、错误摘要和采集数量。新增字段：

```json
{
  "trigger": "manual|scheduled|retry",
  "cycle_id": "collection-xxx",
  "attempt": 0,
  "max_attempts": 3,
  "success_targets": [{"tower_id": 1, "tower_name": "Tower A", "cluster_id": "cluster-a", "cluster_name": "Cluster A"}],
  "failed_targets": [{"tower_id": 1, "tower_name": "Tower A", "cluster_id": "cluster-b", "cluster_name": "Cluster B", "message": "error"}],
  "published_metrics_targets": []
}
```

定时采集失败时按 Tower 配置重试，默认每 15 分钟重试 1 次、最多额外重试 3 次。重试耗尽后仍失败会在任务中心生成 `Tower/集群采集异常` 普通告警。

## 4.1 报表 `data_quality`

平台级自检接口已移除；数据质量只作为报表上下文说明提供。

`GET /api/reports/latest` 在保留旧字段的基础上增加：

```json
{
  "data_quality": {
    "status": "ok|warning|critical",
    "actual_data_window": {"start_at": "...", "end_at": "...", "days": 14},
    "requested_window": {"days": 30, "start_at": "...", "end_at": "..."},
    "sample_sufficient": false,
    "missing_collection_dates": ["2026-06-12"],
    "incomplete_clusters": [
      {"tower": "CHINATOWER", "cluster": "SMARTX-TT-WW", "reason": "prometheus_cluster_sample_missing"}
    ],
    "sqlite_vm_count": 526,
    "prometheus_vm_series_count": 171,
    "sqlite_cluster_count": 1,
    "prometheus_cluster_series_count": 1,
    "latest_collection_status": "partial_failed",
    "latest_success_at": "...",
    "latest_prometheus_sample_at": "...",
    "messages": []
  }
}
```

报表页和 Word/Excel 导出使用该字段展示“数据质量说明”。质量异常不会阻止导出，但客户版文件会明确写出实际采集窗口、缺采天数、样本是否足够和数据不完整集群。

## 5. Dashboard

### `GET /api/dashboard/summary?tower_id=&cluster_id=`

响应关键字段：

```json
{
  "scope": {"tower_id": 1, "cluster_id": "cluster-id"},
  "capacity_risk": {"level": "normal|warning|high", "message": "当前所有集群暂无明显容量风险"},
  "totals": {"towers": 1, "clusters": 3, "vms": 175},
  "storage": {"total_bytes": 0, "used_bytes": 0, "used_ratio": 0.72},
  "collection": {"last_success_at": "...", "status": "success"},
  "day_fastest_growing_vms": [],
  "day_new_vms": [],
  "clusters": []
}
```

风险规则：

- 任一集群使用率 `>= 80%` 为 `high`。
- 任一集群使用率 `75%-80%` 为 `warning`。
- 否则为 `normal`。

## 6. VM

### `GET /api/vms?tower_id=&cluster_id=`

返回 VM 列表。VM 展示名称使用最新采集名称。

### `GET /api/vms/{vm_id}/trend`

参数：

- `tower_id`
- `cluster_id`
- `metric=used`
- `days=7|14|30|90|180|365`

必须同时传 `tower_id` 和 `cluster_id`，避免跨 Tower/集群混合。

响应除 `points` 外包含采集新鲜度字段：

```json
{
  "latest_success_at": "2026-06-12 02:10:00",
  "latest_collection_status": "success|failed|unknown",
  "has_collection_gap": true,
  "gap_dates": ["2026-06-13"],
  "data_freshness": "fresh|stale|partial"
}
```

缺采判断按该 VM 所属 Tower/集群计算。缺采日期不补 0、不复制旧值，前端以断点和 `非最新` 提示展示。

### `GET /api/vms/{vm_id}/volumes`

返回结构化卷列表，不返回 Tower 原始 payload。

## 7. 报表

### `GET /api/reports/latest`

参数：

- `tower_id`
- `cluster_id`
- `chart_days=7|30|90|365|720`

响应关键字段：

```json
{
  "forecast_days": 90,
  "growth_rate_window_days": 7,
  "chart_days": 90,
  "clusters": [],
  "day_fastest_growing_vms": [],
  "month_fastest_growing_vms": [],
  "day_new_vms": [],
  "month_new_vms": [],
  "statistics_window": {"start": "2026-05-06", "end": "2026-06-05"}
}
```

### `POST /api/reports/export`

请求：

```json
{"tower_id": 1, "cluster_id": null, "days": 90, "formats": ["docx", "xlsx"]}
```

响应：

```json
{"task_id": "report-..."}
```

导出文件保存到 `/data/exports/reports`，任务完成后通过 task artifact 下载。

## 8. 数据迁移

### `POST /api/admin/migration/export/start`

创建迁出任务。

响应：

```json
{
  "task_id": "migration-export-...",
  "status": "running",
  "progress": 10,
  "processed_bytes": 0,
  "total_bytes": 123456,
  "steps": [],
  "logs": []
}
```

任务状态：

- `GET /api/admin/migration/export/status/{task_id}`
- 成功后返回 `download_url`、`saved_path`、`filename`
- 任务中心提供迁移包下载链接

### `POST /api/admin/migration/import/start`

上传迁移包并启动后台导入任务。

表单字段：

- `file`：`.tar.gz` 或 `.tgz` 迁移包
- `mode`：`merge` 或 `overwrite`
- `confirmed`：覆盖导入时必须为 `true`

响应：

```json
{
  "task_id": "migration-import-...",
  "status": "running",
  "progress": 5,
  "saved_path": "/data/exports/imports/migration-import-.../package.tar.gz",
  "steps": []
}
```

任务步骤：

1. 保存上传包。
2. 解压并校验迁移包。
3. 生成导入前备份。
4. 导入 SQLite。
5. 导入 Prometheus 历史 block。
6. 执行导入后健康检查。

任务状态：

- `GET /api/admin/migration/import/status/{task_id}`
- 成功后返回 `backup_path`、`saved_path`、`summary`

旧同步接口 `/api/admin/migration/import` 仅作兼容，前端默认不再使用。

### `GET /api/admin/migration/health`

返回迁移后健康验证结果。

### `GET /api/admin/system/sqlite-vacuum/scan`

扫描 SQLite 当前大小、总页数、空闲页、预计可释放空间和运行态缓存候选数量。

返回 `runtime_cache`：

- `metric_snapshots.delete_count`：超过最新 1 条的指标快照数量。
- `collection_runs.delete_count`：超过 7 天的采集记录数量。
- `tasks.delete_count`：超过 30 天且允许清理的任务记录数量。

### `POST /api/admin/system/sqlite-vacuum`

执行 SQLite 清理并整理。

执行前必须备份 `smartx.db` 到 `/data/backups/sqlite-before-cleanup-*.db`。随后清理运行态缓存并执行 VACUUM，返回 `runtime_cache` 删除统计、整理前后大小和释放空间。

### `GET /api/admin/system/sqlite-backups/scan`

扫描 `/data/backups` 顶层 SQLite 数据库备份。

只返回符合 SQLite 备份命名和扩展名的文件，例如：

- `sqlite-before-cleanup-*.db`
- `sqlite-before-vacuum-*.db`
- `smartx-db-before-*.db`
- `smartx-before-*.db`

不递归子目录，不返回升级前备份、导入前备份、Prometheus 备份或 `.tar.gz` 文件。

响应字段：

- `items[]`：`filename`、`path`、`size`、`size_label`、`modified_at`
- `total_count`
- `total_size`
- `total_size_label`
- `message`

### `POST /api/admin/system/sqlite-backups/delete`

删除用户勾选的 SQLite 数据库备份文件。

请求体：

```json
{
  "filenames": ["sqlite-before-cleanup-20260607133053.db"]
}
```

后端只接受文件名，自动丢弃路径穿越部分，并再次校验文件必须位于 `/data/backups` 顶层且符合 SQLite 备份识别规则。不存在或不符合规则的文件会跳过并写入日志。

响应字段：

- `deleted_count`
- `space_reclaimed`
- `space_reclaimed_label`
- `logs[]`
- `message`

## 9. 升级中心

### `POST /api/upgrade/upload`

上传升级包。后端保存、解包、解析 manifest。

### `GET /api/upgrade/packages`

列出已上传升级包和识别到的组件。

### `POST /api/upgrade/precheck`

请求：

```json
{"package_id": "pkg-..."}
```

响应包含步骤化检查结果。

### `POST /api/upgrade/start`

创建升级任务。

### `GET /api/upgrade/status/{task_id}`

查询升级状态、步骤、日志和回滚入口。

### `POST /api/upgrade/rollback/{task_id}`

执行手动回滚。

### `GET /api/upgrade/history`

返回升级历史。

## 10. 任务中心

### `GET /api/tasks`

返回最近任务列表。

### `GET /api/tasks/{task_id}`

返回任务详情。

任务字段：

```json
{
  "task_id": "task-...",
  "type": "report|migration_export|migration_import|upgrade|cleanup|collection",
  "status": "pending|running|success|failed|cancelled",
  "progress": 42,
  "message": "正在处理",
  "steps": [],
  "artifacts": []
}
```

### `GET /api/tasks/{task_id}/logs`

返回任务日志。

### `GET /api/tasks/{task_id}/artifacts/{artifact_id}`

下载任务产物。
