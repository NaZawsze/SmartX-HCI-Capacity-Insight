# API Reference

Base URL:

```text
http://<server-ip>:8000
```

When accessed through the frontend container, API requests are proxied under the same frontend origin.

All business APIs require a Bearer token except `POST /api/auth/login`.

```http
Authorization: Bearer <access_token>
```

## Authentication

### Login

```http
POST /api/auth/login
```

Request:

```json
{
  "username": "admin",
  "password": "password"
}
```

Response:

```json
{
  "access_token": "token",
  "token_type": "bearer",
  "username": "admin"
}
```

### Current User

```http
GET /api/me
```

Response:

```json
{
  "username": "admin",
  "is_admin": true
}
```

### Change Password

```http
PUT /api/me/password
```

Request:

```json
{
  "current_password": "password",
  "new_password": "new-password",
  "confirm_password": "new-password"
}
```

Response:

```json
{
  "ok": true
}
```

## Towers

### List Towers

```http
GET /api/towers
```

Returns configured Tower entries and discovered clusters. Sensitive fields such as passwords and API tokens are never returned.

### Create Tower

```http
POST /api/towers
```

Request:

```json
{
  "name": "Tower name",
  "base_url": "https://tower.example.com",
  "username": "readonly-user",
  "password": "readonly-password",
  "api_token": null,
  "verify_tls": true,
  "enabled": true,
  "collection_hour": 2,
  "collection_minute": 10
}
```

`api_token` is optional. When provided, it is preferred over username/password login.

### Update Tower

```http
PUT /api/towers/{tower_id}
```

All fields are optional. Use this endpoint to update the display name, URL, username, password, API token, TLS verification, enabled state, and collection time.

### Delete Tower

```http
DELETE /api/towers/{tower_id}
```

Response:

```json
{
  "ok": true
}
```

### Test Tower Connection

```http
POST /api/towers/{tower_id}/test
```

The backend connects to the Tower, reads cluster metadata, and stores or updates the local cluster list.

Response:

```json
{
  "ok": true,
  "message": "连接成功，发现 1 个集群。",
  "clusters": [
    {
      "cluster_id": "cluster-id",
      "name": "Cluster name",
      "enabled": true
    }
  ]
}
```

### Update Cluster

```http
PUT /api/towers/{tower_id}/clusters/{cluster_id}
```

Request:

```json
{
  "enabled": true,
  "name": "Display name"
}
```

## Collection

### Run Collection

```http
POST /api/collection/run
```

Starts an asynchronous collection run. If a run is already active, the API returns the active run state.

Response:

```json
{
  "run_id": 1,
  "status": "running",
  "message": "采集任务已开始，页面会自动刷新状态。"
}
```

## Dashboard

### Summary

```http
GET /api/dashboard/summary
```

Optional query parameters:

```text
tower_id=<id>
cluster_id=<cluster-id>
```

Returns KPI data, scope information, latest collection status, Tower-level collection status, cluster capacity items, Tower tree data, and daily top-growing VMs.

### VM List

```http
GET /api/vms
```

Returns up to 500 VMs sorted by actual used storage size. Each item includes labels, actual used bytes, guest used bytes, provisioned bytes, and usage ratios when available.

### VM Trend

```http
GET /api/vms/{vm_id}/trend?metric=used&days=30
```

Supported `days` values:

```text
7, 14, 30, 90, 180, 365
```

Common metrics:

```text
used
guest_used
provisioned
```

Response:

```json
{
  "vm_id": "vm-id",
  "metric": "used",
  "points": [
    [1716307200, 1099511627776]
  ]
}
```

### Current VM Volumes

```http
GET /api/vms/{vm_id}/volumes
```

Returns the latest collected virtual volume details for one VM.

### All VM Volumes

```http
GET /api/vm-volumes
```

Returns the latest collected virtual volume details grouped by Tower, cluster, and VM.

## Reports

### Latest Forecast Report

```http
GET /api/reports/latest
```

Optional query parameters:

```text
tower_id=<id>
cluster_id=<cluster-id>
```

Returns cluster forecast reports, daily top-growing VM reports, monthly top-growing VM reports, cluster total growth rate per day, and forecast window metadata.

The report uses a 30-day historical sample window and forecasts 60 days forward. When there are not enough samples, forecast fields may indicate insufficient data.

### Export Forecast Report as Word

```http
GET /api/reports/export/word
```

Optional query parameters:

```text
tower_id=<id>
cluster_id=<cluster-id>
period_days=30
```

The export scope follows the same rules as the report page: all enabled clusters, one Tower, or one cluster. The Word document includes the export scope, generation time, forecast window, cluster summary, and per-cluster monthly Top 100 VM tables sorted by growth amount and growth ratio. Supported `period_days` values are `7`, `14`, `30`, `90`, `180`, and `365`.

Response content type:

```text
application/vnd.openxmlformats-officedocument.wordprocessingml.document
```

### Export Forecast Report as Excel

```http
GET /api/reports/export/excel
```

Optional query parameters:

```text
tower_id=<id>
cluster_id=<cluster-id>
period_days=30
```

The workbook includes a summary sheet, a combined monthly VM Top 100 sheet, and one sheet per cluster. The VM tables include Tower, cluster, VM, current capacity, previous capacity, monthly growth amount, and growth ratio.

Response content type:

```text
application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
```

## Metrics

### Prometheus Metrics

```http
GET /metrics
```

Returns the latest capacity metrics in Prometheus text format.

The collector worker exposes metrics on port `9108` for Prometheus scraping.
