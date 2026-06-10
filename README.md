# SmartX HCI Capacity Insight

[简体中文](README.zh-CN.md) | English

Version: `v0.5.0`

> Status: This project is currently in the testing stage and is not recommended for production use without additional validation.

SmartX HCI Capacity Insight is a storage capacity monitoring and forecasting platform for SmartX hyperconverged infrastructure environments. It collects read-only capacity data from CloudTower/Tower datacenters, clusters, virtual machines, and virtual volumes, then provides capacity overviews, VM storage trends, top-growing VM rankings, cluster forecast reports, and capacity risk insights.

> Note: This project was written with AI assistance.

## Features

- Multi-Tower and multi-cluster capacity overview.
- Daily scheduled collection and manual collection trigger.
- VM storage trend charts with 7, 14, 30, 90, 180, and 365 day ranges.
- VM list sorting by storage size and guest usage ratio.
- Current VM volume details and all VM volume details.
- Daily and monthly top-growing VM rankings with sorting by growth amount or growth ratio.
- Click a top-growing VM to jump to the VM page and select the corresponding VM.
- Cluster forecast reports based on recent historical samples, with linked cluster capacity trend charts.
- Forecast report export for all clusters, one Tower, or one cluster, generating Word and Excel files together.
- Export reports with selectable 7, 14, 30, 90, 180, and 365 day historical windows.
- Tower-level collection status, with platform password changes available from the admin avatar menu.

## Screenshots

### Dashboard Overview

![Dashboard overview](docs/assets/dashboard-overview.png)

### VM Storage Trend

![VM storage trend](docs/assets/vm-storage-trend.png)

### Forecast Report

![Forecast report](docs/assets/forecast-report.png)

### Tower Settings

![Tower settings](docs/assets/tower-settings.png)

## Architecture

```text
CloudTower/Tower
      |
      v
collector-worker ----> SQLite (/data/smartx.db)
      |                    |
      v                    v
Prometheus <---------- web-api (FastAPI)
                           |
                           v
frontend (React + TypeScript + ECharts)
```

## Repository Layout

```text
backend/       FastAPI API, collector, CloudTower client, forecast logic, CLI
frontend/      React + TypeScript frontend
prometheus/    Prometheus scrape configuration
docs/          API, deployment, usage documentation, and screenshots
docker-compose.yml
.env.example
```

## Quick Start

Prerequisites on the target server:

- Docker
- Docker Compose

Create environment configuration:

```bash
cp .env.example .env
```

Update production secrets in `.env`:

```text
SMARTX_SECRET_KEY=replace-with-a-long-random-secret
SMARTX_CREDENTIAL_KEY=replace-with-a-different-long-random-secret
SMARTX_ADMIN_PASSWORD=password
```

Start the stack:

```bash
docker compose up -d --build
```

Default access:

```text
Frontend:   http://<server-ip>:8080
Backend:    http://<server-ip>:8000
Prometheus: http://<server-ip>:9090
```

Default platform account:

```text
Username: admin
Password: password
```

Change the password after the first login from the admin avatar menu: `Set Password`.

## Offline Upgrade Package

The platform supports offline `.tar.gz` upgrade packages uploaded from the service management page. An upgrade package replaces service images and can optionally run a migration script. It must not include runtime data, `.env`, SQLite databases, Prometheus data, Tower credentials, or other secrets.

Compatibility: the `v0.5.0` upgrade package targets the v2 upgrade flow only. It is not an in-place upgrade path from v1 or `v0.4.x`; those older systems are supported through data migration instead. For older v1 installations, install the latest version fresh, then export a migration package from the old system with the README command and import it into the new system.

Recommended package structure:

```text
smartx-capacity-insight-v0.5.0-upgrade.tar.gz
├── manifest.json
├── checksums.sha256
├── release-notes.md                 # optional
├── images/
│   ├── web-api.tar
│   ├── frontend.tar
│   └── collector-worker.tar
├── scripts/
│   └── migrate.sh
└── project/
    ├── docker-compose.yml
    ├── docker-compose.offline.yml
    ├── docker-compose.release.yml
    ├── prometheus/
    ├── scripts/
    └── docs/
```

`manifest.json` should describe the target version, minimum compatible version, component list, image SHA256 checksums, project file sync, migration script, services to restart, and package type.

Example fields:

```json
{
  "schema_version": "3",
  "minimum_runner_protocol": 1,
  "required_capabilities": ["backup.create", "image.load", "compose.apply", "health.http"],
  "product": "smartx-storage-forecast",
  "package_id": "smartx-capacity-insight-v0.5.0",
  "version": "v0.5.0",
  "min_version": "v0.5.0",
  "package_type": "platform",
  "project_files": true,
  "migration": {"required": true, "script": "scripts/migrate.sh"},
  "restart_services": ["web-api", "collector-worker", "frontend"],
  "components": [
    {
      "type": "platform",
      "services": ["web-api", "collector-worker", "frontend"],
      "images": [
        {
          "service": "web-api",
          "archive": "images/web-api.tar",
          "image": "nazawsze/smartx-hci-capacity-insight-web-api:v0.5.0",
          "sha256": "<sha256>"
        }
      ]
    }
  ]
}
```

For normal platform upgrades, do not restart `upgrade-runner` in the same package that is executing the upgrade. Use a component upgrade package when `upgrade-runner` itself needs to be replaced.

Component upgrade packages for `upgrade-runner` are separate and use the runner component version, for example `v0.3.0`, not the platform version.

```text
smartx-upgrade-runner-v0.3.0.tar.gz
├── manifest.json
├── checksums.sha256
├── release-notes.md
└── images/
    └── upgrade-runner.tar
```

The old `web-api` updates Runner directly; Runner never updates itself. A normal platform package does not require a Runner upgrade when its protocol and capability requirements are already satisfied.

Prometheus is upgraded as an `observability` component package. It is separate from normal platform packages and contains only the Prometheus image:

```text
smartx-prometheus-v2.55.1.tar.gz
├── manifest.json
├── checksums.sha256
├── release-notes.md
└── images/
    └── prometheus.tar
```

Platform and Prometheus can also be delivered as one bundle:

```text
smartx-capacity-insight-bundle-v0.6.0.tar.gz
├── manifest.json
├── checksums.sha256
├── release-notes.md
├── platform/
│   ├── images/
│   ├── project/
│   └── migrations/
└── observability/
    └── images/
```

Build it with `python scripts/build_bundle_upgrade_package.py --platform-version v0.6.0`. Bundle packages do not contain Runner by default.

### Recommended Migration Path: Fresh Install + CLI Data Export

If the old upgrade flow is unreliable, install the latest storage forecast platform on the target server first. Then run the following command on the old system CLI to export a migration package, and import that package from the new system page: `Service Management -> Data Migration`.

Run on the old system server:

```bash
WEB_API_CONTAINER="${WEB_API_CONTAINER:-$(docker ps --format '{{.Names}}' | grep -E 'web-api' | head -n 1)}"
if [ -z "$WEB_API_CONTAINER" ]; then
  echo "web-api container not found. Set WEB_API_CONTAINER manually." >&2
  exit 1
fi

filename="$(
  docker exec "$WEB_API_CONTAINER" python - <<'PY'
from app.services.data_migration import build_migration_archive
_, filename = build_migration_archive(save_export=True)
print(filename)
PY
)"

export_root="$(docker inspect "$WEB_API_CONTAINER" --format '{{range .Mounts}}{{if eq .Destination "/data/exports"}}{{.Source}}{{end}}{{end}}')"
if [ -z "$export_root" ]; then
  data_root="$(docker inspect "$WEB_API_CONTAINER" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}')"
  export_root="${data_root}/exports"
fi

host_path="${export_root}/migrations/${filename}"
ls -lh "$host_path"
sha256sum "$host_path"
```

The printed `host_path` is the migration package path. The package includes the business database and Prometheus historical metrics. After importing it into the new system, restart data services from the service management page.

## Documentation

- [Deployment Guide](docs/deployment.md)
- [Usage Guide](docs/usage.md)
- [API Reference](docs/api.md)
- [upgrade-runner Lifecycle and Component Upgrade Policy](docs/upgrade-runner-lifecycle.md)
- [Version Governance](docs/version-governance.md)
- [v0.2 Release Notes](docs/releases/v0.2.md)

## CloudTower Permissions

Use a read-only CloudTower account or a read-only API token whenever possible. The collector only needs read access to cluster, VM, volume, and storage capacity data.

Related CloudTower API operations:

- `/v2/api/login`
- `/v2/api/get-clusters`
- `/v2/api/get-cluster-storage-info`
- `/v2/api/get-vms`
- `/v2/api/get-vm-volumes`

## Password Reset

If the platform password is lost, reset it on the target server from the project directory:

```bash
cd /opt/smartx-storage-forecast
```

Reset interactively:

```bash
docker compose exec web-api python -m app.cli reset-password --username admin
```

Or pass the new password non-interactively:

```bash
docker compose exec web-api python -m app.cli reset-password --username admin --password password
```

Then log in again with the new password.

## Data and Security Notes

Do not commit runtime data or secrets. The repository intentionally excludes:

- `.env`
- SQLite databases
- Prometheus data
- collected Tower, cluster, VM, and volume data
- SSH keys, certificates, and temporary diagnostic scripts

## Tests

After dependencies are available in a development or CI environment:

```bash
cd backend
pytest
```

```bash
cd frontend
npm test
```

## License

MIT License.
