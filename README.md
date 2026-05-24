# SmartX HCI Capacity Insight

**SmartX 超融合容量洞察平台**

Version: `v0.1`

SmartX HCI Capacity Insight is a storage capacity monitoring and forecasting platform for SmartX hyperconverged infrastructure environments. It collects read-only capacity data from CloudTower/Tower datacenters, clusters, virtual machines, and virtual volumes, then provides capacity overview, VM storage trends, top-growing VM rankings, cluster forecast reports, and capacity risk insights.

SmartX 超融合容量洞察平台面向 SmartX 超融合环境，用于采集 CloudTower/Tower 下的数据中心、集群、虚拟机与虚拟卷容量数据，展示容量概览、虚拟机存储趋势、Top 增长 VM、集群预测报表和容量风险提示，帮助运维人员持续跟踪资源使用变化并提前识别容量压力。

> Note: This project was written with AI assistance.  
> 说明：本项目由 AI 辅助编写。

## Features

- Multi-Tower and multi-cluster capacity overview.
- Daily collection and manual collection trigger.
- VM storage trend charts with 7, 14, 30, 90, 180, and 365 day ranges.
- VM list sorting by storage size and guest usage ratio.
- Current VM volume details and all VM volume details.
- Daily and monthly top-growing VM rankings with sorting by growth amount or growth ratio.
- Click a top-growing VM to jump to the VM page and select the corresponding VM.
- Cluster forecast reports based on recent historical samples.
- Tower-level collection status and platform password management.

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
docs/          API, deployment, and usage documentation
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

Change the password after the first login from `Settings -> Platform Password`.

## Documentation

- [Deployment Guide](docs/deployment.md)
- [Usage Guide](docs/usage.md)
- [API Reference](docs/api.md)

## CloudTower Permissions

Use a read-only CloudTower account or a read-only API token whenever possible. The collector only needs read access to cluster, VM, volume, and storage capacity data.

Related CloudTower API operations:

- `/v2/api/login`
- `/v2/api/get-clusters`
- `/v2/api/get-cluster-storage-info`
- `/v2/api/get-vms`
- `/v2/api/get-vm-volumes`

## Password Reset

If the platform password is lost, reset it on the target server:

```bash
docker compose exec web-api python -m app.cli reset-password --username admin
```

Or pass the new password non-interactively:

```bash
docker compose exec web-api python -m app.cli reset-password --username admin --password password
```

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
