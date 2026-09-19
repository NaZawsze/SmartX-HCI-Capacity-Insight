# API Reference

Base URL:

```text
http://<server-ip>:8000
```

When accessed through the frontend container, API requests are proxied under the same frontend origin.

All business APIs require a Bearer token except `POST /api/auth/login`. `GET /api/system/health` and the collector worker's `GET /metrics` (port `9108`) are public.

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

### Test Tower Connection (Unsaved)

```http
POST /api/towers/test
```

Tests a Tower connection with parameters provided in the request body, so the Settings page can verify a Tower before saving it.

### Sync Clusters

```http
POST /api/towers/{tower_id}/clusters/sync
```

Upserts the provided cluster entries for one Tower and returns the stored clusters.

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

### Collection Runs

```http
GET /api/collection/runs?limit=30
```

Returns recent collection runs (most recent first), including status and per-Tower results.

### Collection Run Detail

```http
GET /api/collection/runs/{run_id}
```

Returns one collection run with its detail state.

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

### VM Detail

```http
GET /api/vms/{vm_id}
```

Returns one VM's capacity summary and labels. Pass `tower_id` (and `cluster_id`) as query parameters to disambiguate the VM identity.

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

### Export Forecast Report Bundle (Word + Excel)

```http
POST /api/reports/export/bundle
```

Optional request parameters:

```text
tower_id=<id>
cluster_id=<cluster-id>
period_days=30
task_id=<task-center-id>
```

Generates both the Word document and the Excel workbook in one call and returns a JSON body with each file's name and download URL. The exports are also recorded in the task center and kept under `exports/reports/`.

## Metrics

### Prometheus Metrics

```http
GET /metrics
```

Returns the latest capacity metrics in Prometheus text format.

The collector worker exposes metrics on port `9108` for Prometheus scraping.

## System

### Health

```http
GET /api/system/health
```

Returns platform/runner identity and dependency checks:

```json
{
  "ok": true,
  "version": "v0.5.3",
  "runner_version": "v0.3.1",
  "checks": {"directories": true, "database": true, "prometheus": true}
}
```

## Tasks

Task center records for upgrades, migrations, cleanups, and collections. Notification state (`severity` = `info|warning|critical`, seen/acknowledged timestamps) is persisted in SQLite; the badge counts unhandled notifications.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/tasks` | List tasks with steps and notification state |
| DELETE | `/api/tasks/finished` | Delete finished tasks |
| POST | `/api/tasks/seen` | Mark info-level notifications as seen |
| POST | `/api/tasks/{task_id}/ack` | Acknowledge a warning/critical task |
| DELETE | `/api/tasks/clearable` | Clear seen info and acknowledged tasks |
| DELETE | `/api/tasks/{task_id}` | Delete one non-active task |

## Admin (Service Management)

Admin endpoints require an admin token. Platform upgrade follows upload → precheck → start → status/verification → post-cleanup.

### Platform upgrade

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/admin/upgrade/upload` | Upload a platform upgrade package |
| POST | `/api/admin/upgrade/precheck/{task_id}` | Run prechecks |
| POST | `/api/admin/upgrade/start/{task_id}` | Start the upgrade |
| GET | `/api/admin/upgrade/status/{task_id}` | Task status, steps, and logs |
| POST | `/api/admin/upgrade/cancel/{task_id}` | Cancel a task |
| POST | `/api/admin/upgrade/rollback/{task_id}` | Trigger rollback |
| POST | `/api/admin/upgrade/recovery/{task_id}/continue` | Continue a `recovery_required` task |
| POST | `/api/admin/upgrade/recovery/{task_id}/rollback` | Roll back a `recovery_required` task |
| POST | `/api/admin/upgrade/recovery/{task_id}/fail` | Fail a `recovery_required` task |
| GET | `/api/admin/upgrade/history` | Upgrade task history |
| DELETE | `/api/admin/upgrade/package/{task_id}` | Delete an uploaded package |
| GET | `/api/admin/upgrade/version` | Current platform/package version info |
| GET | `/api/admin/upgrade/verification` | Post-upgrade service verification |
| GET | `/api/admin/upgrade/post-cleanup/{task_id}` | Legacy cleanup result |
| POST | `/api/admin/upgrade/post-cleanup/{task_id}/retry` | Retry legacy cleanup |

### Component upgrade

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/admin/component-upgrade/upload` | Upload a component package (runner / Prometheus) |
| POST | `/api/admin/component-upgrade/precheck/{task_id}` | Component prechecks |
| POST | `/api/admin/component-upgrade/start/{task_id}` | Start component upgrade |
| GET | `/api/admin/component-upgrade/status/{task_id}` | Component task status |
| POST | `/api/admin/component-upgrade/cancel/{task_id}` | Cancel component task |
| GET | `/api/admin/component-upgrade/history` | Component upgrade history |
| DELETE | `/api/admin/component-upgrade/package/{task_id}` | Delete component package |
| GET | `/api/admin/component-upgrade/version` | Active runner version info |
| GET | `/api/admin/component-upgrade/components` | Component catalog |

### Migration

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/admin/migration/export` | Download migration package (synchronous export) |
| GET | `/api/admin/migration/config/export` | Download configuration export |
| POST | `/api/admin/migration/export/start` | Start asynchronous export task |
| GET | `/api/admin/migration/export/status/{task_id}` | Export task status |
| POST | `/api/admin/migration/import/start` | Start asynchronous import task |
| GET | `/api/admin/migration/import/status/{task_id}` | Import task status |
| POST | `/api/admin/migration/import` | Upload and import a migration package |
| GET | `/api/admin/migration/health` | Migration environment health |

### System administration

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/admin/system/local-storage` | Local storage usage |
| GET | `/api/admin/system/cleanup-artifacts/scan` | Scan cleanable runtime artifacts |
| POST | `/api/admin/system/cleanup-artifacts` | Delete scanned artifacts |
| GET | `/api/admin/system/cleanup-images/scan` | Scan unused images |
| POST | `/api/admin/system/cleanup-images` | Delete scanned images |
| GET | `/api/admin/system/sqlite-vacuum/scan` | Scan SQLite free pages |
| POST | `/api/admin/system/sqlite-vacuum` | Run VACUUM |
| GET | `/api/admin/system/sqlite-backups/scan` | Scan SQLite backups |
| POST | `/api/admin/system/sqlite-backups/delete` | Delete selected backups |
| POST | `/api/admin/system/restart` | Restart data services (web-api / collector-worker) |
| GET | `/api/admin/exports/{category}/{filename}` | Download a server-side export file |
