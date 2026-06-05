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
{"task_id": "collect-...", "status": "running", "message": "采集任务已开始"}
```

### `GET /api/collection/runs`

返回最近采集记录。

### `GET /api/collection/runs/{run_id}`

返回采集详情、错误摘要和采集数量。

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

### `POST /api/migration/export`

创建迁出任务。

响应：

```json
{"task_id": "migration-export-..."}
```

### `POST /api/migration/import/upload`

上传迁移包，保存到 `/data/exports/imports`。

### `POST /api/migration/import/start`

请求：

```json
{"package_id": "pkg-...", "mode": "merge"}
```

响应：

```json
{"task_id": "migration-import-..."}
```

### `GET /api/migration/health`

返回迁移后健康验证结果。

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
