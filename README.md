# SmartX HCI Capacity Insight

[简体中文](README.zh-CN.md) | English

Version: `v0.2`

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

## Docker Images

GitHub Actions automatically builds Docker images for `main` and `v*` tags, then publishes them to Docker Hub.

```text
docker.io/<dockerhub-namespace>/smartx-hci-capacity-insight-web-api
docker.io/<dockerhub-namespace>/smartx-hci-capacity-insight-frontend
```

Published tags include:

- `latest` for the default branch.
- `main` for the main branch.
- `v0.2` and other `v*` release tags.
- `sha-<commit>` for each pushed commit.

Required GitHub repository secrets:

```text
DOCKERHUB_USERNAME
DOCKERHUB_TOKEN
```

Optional GitHub repository variable:

```text
DOCKERHUB_NAMESPACE
```

If `DOCKERHUB_NAMESPACE` is not set, the workflow uses `DOCKERHUB_USERNAME` as the Docker Hub namespace.

## Documentation

- [Deployment Guide](docs/deployment.md)
- [Usage Guide](docs/usage.md)
- [API Reference](docs/api.md)
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
