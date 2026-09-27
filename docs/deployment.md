# Deployment Guide

This guide describes how to deploy SmartX HCI Capacity Insight on a target server with Docker Compose.

## 1. Requirements

Install on the target server:

- Docker
- Docker Compose plugin
- Network access from the target server to CloudTower/Tower

CloudTower/Tower compatibility:

- The platform connects through the CloudTower v2 HTTP API: `/v2/api/login`, `/v2/api/get-clusters`, `/v2/api/get-cluster-storage-info`, `/v2/api/get-vms`, `/v2/api/get-vm-volumes`.
- The target CloudTower (SMTX OS) instance must provide and support these v2 API endpoints and return the expected payload shapes. Validated against a CloudTower instance (`CHINATOWER`); no specific CloudTower minor version is required when these endpoints are available.

No runtime data from a deployed environment should be committed to Git.

## 2. Configure Environment Variables

Copy the template:

```bash
cp .env.example .env
```

Important variables:

```text
SMARTX_SECRET_KEY=replace-with-a-long-random-secret
SMARTX_CREDENTIAL_KEY=replace-with-a-different-long-random-secret
SMARTX_ADMIN_USER=admin
SMARTX_ADMIN_PASSWORD=password
SMARTX_DB_PATH=/data/smartx.db
SMARTX_PROMETHEUS_URL=http://prometheus:9090
SMARTX_COLLECTION_TIMEZONE=Asia/Shanghai
SMARTX_COLLECTION_HOUR=2
SMARTX_COLLECTION_MINUTE=10
SMARTX_COLLECTION_INTERVAL_MINUTES=60
SMARTX_CAPACITY_ALERT_WARNING_RATIO=0.75
SMARTX_CAPACITY_ALERT_CRITICAL_RATIO=0.80
SMARTX_CAPACITY_ALERT_MIN_FREE_BYTES=0
SMARTX_CORS_ORIGINS=*
```

Production recommendations:

- Change `SMARTX_SECRET_KEY`.
- 采集频率在 Tower 设置页按 Tower 配置："采集间隔 - 分钟"默认 `60`（每小时一次），设为 `0` 时按该 Tower 的"每日采集时间"每天执行一次。`SMARTX_COLLECTION_INTERVAL_MINUTES` 仅作为存量数据库迁移时的初始回填值，运行时以 Tower 配置为准（worker 每 60 秒同步一次调度）。
- `SMARTX_FRESHNESS_STALE_MINUTES` 控制数据新鲜度告警阈值（分钟，默认自适应 = 2 × 启用 Tower 最小采集周期且不低于 60）：最近成功采集超过阈值、或 Prometheus 样本滞后最近成功采集 15 分钟以上时，生成"数据质量需关注"告警。
- `SMARTX_CAPACITY_ALERT_*` 控制集群容量告警：使用率 >= `WARNING_RATIO`（默认 75%）生成"需关注"告警，>= `CRITICAL_RATIO`（默认 80%）生成"高风险"告警；`MIN_FREE_BYTES` 大于 0 时，剩余空间低于该值也会生成"需关注"告警。告警在任务中心展示，同一持续条件确认后不会重复弹出，等级升级（需关注→高风险）会生成新告警。
- 定时采集失败时，平台按 Tower 配置只重试失败 Tower/集群；默认每 15 分钟重试一次，最多额外重试 3 次。
- 部分 Tower/集群采集成功时，成功目标仍写入 SQLite 当前态和 Prometheus；失败目标不写新样本，虚拟机趋势图会显示缺采和 `非最新` 提示。
- Change `SMARTX_CREDENTIAL_KEY`.
- Change the platform password from the admin avatar menu after the first login.
- Keep `.env` out of Git.

`SMARTX_CREDENTIAL_KEY` is used to encrypt Tower credentials before storing them in SQLite.

## 3. Prepare Data Directories

Before starting services, initialize the persistent data directories and Prometheus ownership:

```bash
./pre_install.sh
```

The script creates `/data/smartx-storage-forecast/app` and `/data/smartx-storage-forecast/prometheus`, then sets the Prometheus directory owner to `65534:65534` so the Prometheus container can write time series data. It is safe to run multiple times.

## 4. Start Services

Source build mode:

```bash
docker compose up -d --build
```

Release image mode, for servers that can pull images from the registry:

```bash
docker compose -f docker-compose.release.yml up -d
```

`docker-compose.release.yml` uses the Docker images built by GitHub Actions and does not contain `build:` sections. Use it when the target server should not build images locally, but can access the image registry.

Offline image mode, for servers that already have the images loaded locally and should not pull from the registry:

```bash
docker compose -f docker-compose.offline.yml up -d
```

The Compose files define `name: smartx-hci-capacity-insight`, so the normal `docker compose ... up -d` command uses the same project regardless of the source directory name. The runtime network has the explicit Docker network name `smartx-hci-capacity-insight-net`, so manual compose operations and upgrades use the same network instead of creating directory-derived networks. If an older Compose implementation ignores top-level `name`, use `--project-name smartx-hci-capacity-insight` explicitly. `docker-compose.offline.yml` sets `pull_policy: never` and uses explicit local version tags by default. Before starting, make sure these images exist on the target server:

```text
nazawsze/smartx-hci-capacity-insight-web-api:v0.5.3
nazawsze/smartx-hci-capacity-insight-collector-worker:v0.5.3
nazawsze/smartx-hci-capacity-insight-frontend:v0.5.3
nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.2
prom/prometheus:v2.55.1
```

If you export GitHub Actions images as tar files, load them first:

```bash
docker load -i smartx-hci-capacity-insight-web-api.tar
docker load -i smartx-hci-capacity-insight-collector-worker.tar
docker load -i smartx-hci-capacity-insight-frontend.tar
docker load -i smartx-hci-capacity-insight-upgrade-runner.tar
```

Image references in the compose files are fully literal (registry and tag both fixed, following `VERSION` / `RUNNER_VERSION`); they cannot be overridden via `.env`:

```text
nazawsze/smartx-hci-capacity-insight-web-api:v0.5.3        # docker-compose.yml / docker-compose.offline.yml
docker.io/nazawsze/smartx-hci-capacity-insight-web-api:v0.5.3   # docker-compose.release.yml
```

Service ports:

```text
frontend:   8080 -> 80
web-api:    8000 -> 8000
prometheus: 9090 -> 9090
```

Open the frontend:

```text
http://<server-ip>:8080
```

Default platform account:

```text
admin / password
```

## 5. Docker Compose Services

```text
web-api
  FastAPI backend. Stores platform configuration and latest metadata in SQLite.

collector-worker
  Background collector. Runs scheduled Tower collection and exposes latest metrics on port 9108.

frontend
  React frontend served by nginx.

prometheus
  Stores capacity time series and provides query data for trends and reports.

upgrade-runner
  Runs platform upgrade tasks outside web-api, including image loading, service restart, health checks, and rollback commands.
```

## 6. Persistent Data

Docker Compose stores persistent data under the project data directory on the host:

```text
/data/smartx-storage-forecast/project
  Contains project files, Compose files, scripts, docs, and Prometheus config.

/data/smartx-storage-forecast/app
  Mounted to /data in web-api, collector-worker, and upgrade-runner.
  Contains SQLite data, platform users, Tower configuration, encrypted credentials,
  cluster metadata, collection runs, latest metric samples, and latest VM volume details.

/data/smartx-storage-forecast/prometheus
  Mounted to /prometheus in the Prometheus container and /prometheus-data in backend services.
  Contains Prometheus time series data. Retention is configured as 400 days.

/data/smartx-storage-forecast/upgrades
  Uploaded upgrade packages and upgrade task state.

/data/smartx-storage-forecast/backups
  Upgrade and import backups.

/data/smartx-storage-forecast/exports
  Report exports, migration exports, migration imports, and migration task state.

/data/smartx-storage-forecast/compose-runtime
  Runtime compose override files generated by the upgrade center.
```

This directory is runtime data and must not be pushed to Git. Back it up before changing storage paths.

## 7. Configure Tower

In the web UI, open `Settings` and add a Tower:

- Name: display name in the sidebar.
- URL: CloudTower/Tower base URL.
- Username/password: optional when API token is used.
- API token: optional.
- TLS verification: keep enabled in production.
- Collection time: Tower-level daily collection schedule.

After saving, test the connection. The platform reads cluster metadata and stores enabled clusters locally.

Use a read-only CloudTower account or read-only API token whenever possible.

## 8. Collection

Collection can happen in two ways:

- Scheduled collection by `collector-worker`.
- Manual collection from the dashboard.

After each successful collection:

- Latest samples are written to SQLite.
- Prometheus metrics are exposed for scraping.
- Dashboard, VM trends, and reports can use the newest data.
- Daily and monthly top-growing VM data is recalculated from the same growth logic.

## 8.1 Operational Checks

The previous heavyweight platform self-check panel and `scripts/verify_platform.py` CLI have been removed. After deployment or upgrade, use the service management page to check platform version, component version, container status, and cleanup scans. Report pages and exported Word/Excel files still include data quality notes based on the actual collection window, missing collection dates, and incomplete clusters.

## 9. Password Management

Users can change their password in:

```text
admin avatar menu -> Set Password
```

If the password is lost, reset it on the target server.

Go to the deployment directory:

```bash
cd /data/smartx-storage-forecast/project
```

Interactive reset:

```bash
docker compose exec web-api python -m app.cli reset-password --username admin
```

The command asks for the new password and confirmation.

Non-interactive reset:

```bash
docker compose exec web-api python -m app.cli reset-password --username admin --password password
```

Replace `admin` with the actual platform username when needed. After reset, log in again with the new password.

## 10. Upgrade

Pull or copy the updated source code, then rebuild:

```bash
docker compose build
docker compose up -d
```

The default compose file builds and runs the same versioned image names used by
upgrade packages. Image tags are written literally in the compose files
(web-api/collector-worker/frontend `v0.5.3`, `upgrade-runner` `v0.3.2`) and change
only through version commits, never through `.env` overrides. Do not switch
runtime services back to `:local` tags, otherwise upgrade packages and the
running compose state can drift.

To rebuild only the frontend:

```bash
docker compose build frontend
docker compose up -d frontend
```

To rebuild backend services:

```bash
docker compose build web-api collector-worker
docker compose up -d web-api collector-worker
```

The v2 upgrade center uses manifest schema 3 and a stable Runner protocol. Platform and Prometheus packages are compiled by `web-api` into an atomic `task.json` execution plan; `upgrade-runner v0.3.1` executes generic actions and can recover after restart. Runner self-upgrade is executed directly by the old `web-api`.

Package builders:

```bash
python scripts/build_upgrade_package.py
python scripts/build_runner_component_package.py --version v0.3.2
python scripts/build_prometheus_component_package.py --version v2.55.1
python scripts/build_bundle_upgrade_package.py --platform-version v0.5.3 --prometheus-version v2.55.1
```

The official platform version for this release line is `v0.5.3`. Temporary package target versions used in a test environment do not change the release version documented here.

Every package requires `manifest.json` and `checksums.sha256`. Bundle packages contain `platform/` and `observability/` sections and do not contain Runner by default. Prometheus component and bundle packages do not export Prometheus historical data; they may reference a repository image tag, and include `prometheus.tar` only when explicitly built for offline image delivery. Never package `.env`, SQLite databases, Prometheus data blocks, backups, exports, credentials, or tokens.

## 11. OVA Artifacts

An OVA appliance image may be delivered for fresh deployment. The OVA is not an upgrade-center package and must not be uploaded to the service management upgrade page.

Recommended OVA artifacts:

```text
smartx-capacity-insight-v0.5.3.ova
smartx-capacity-insight-v0.5.3.ova.sha256
```

OVA exports must not contain production `.env`, SQLite databases, Prometheus data blocks, backups, exports, Tower credentials, tokens, or customer data. See [OVA 交付说明](ova-delivery.md) for the full checklist.

## 12. Security Checklist

- Do not commit `.env`.
- Do not commit SQLite databases.
- Do not commit Prometheus data directories.
- Do not commit Tower URLs, tokens, usernames, passwords, VM names, or collected capacity data.
- Use read-only CloudTower credentials.
- Restrict access to backend and Prometheus ports in production networks.
- Rotate `SMARTX_SECRET_KEY` and `SMARTX_CREDENTIAL_KEY` before production use.
