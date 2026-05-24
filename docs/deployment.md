# Deployment Guide

This guide describes how to deploy SmartX HCI Capacity Insight on a target server with Docker Compose.

## 1. Requirements

Install on the target server:

- Docker
- Docker Compose plugin
- Network access from the target server to CloudTower/Tower

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
SMARTX_CORS_ORIGINS=*
```

Production recommendations:

- Change `SMARTX_SECRET_KEY`.
- Change `SMARTX_CREDENTIAL_KEY`.
- Change the platform password after the first login.
- Keep `.env` out of Git.

`SMARTX_CREDENTIAL_KEY` is used to encrypt Tower credentials before storing them in SQLite.

## 3. Start Services

```bash
docker compose up -d --build
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

## 4. Docker Compose Services

```text
web-api
  FastAPI backend. Stores platform configuration and latest metadata in SQLite.

collector-worker
  Background collector. Runs scheduled Tower collection and exposes latest metrics on port 9108.

frontend
  React frontend served by nginx.

prometheus
  Stores capacity time series and provides query data for trends and reports.
```

## 5. Persistent Data

Docker Compose defines two named volumes:

```text
smartx-data
  Mounted to /data in web-api and collector-worker.
  Contains SQLite data, including platform users, Tower configuration, encrypted credentials,
  cluster metadata, collection runs, latest metric samples, and latest VM volume details.

prometheus-data
  Mounted to /prometheus in the Prometheus container.
  Contains Prometheus time series data. Retention is configured as 400 days.
```

These volumes are runtime data and must not be pushed to Git.

## 6. Configure Tower

In the web UI, open `Settings` and add a Tower:

- Name: display name in the sidebar.
- URL: CloudTower/Tower base URL.
- Username/password: optional when API token is used.
- API token: optional.
- TLS verification: keep enabled in production.
- Collection time: Tower-level daily collection schedule.

After saving, test the connection. The platform reads cluster metadata and stores enabled clusters locally.

Use a read-only CloudTower account or read-only API token whenever possible.

## 7. Collection

Collection can happen in two ways:

- Scheduled collection by `collector-worker`.
- Manual collection from the dashboard.

After each successful collection:

- Latest samples are written to SQLite.
- Prometheus metrics are exposed for scraping.
- Dashboard, VM trends, and reports can use the newest data.
- Daily and monthly top-growing VM data is recalculated from the same growth logic.

## 8. Password Management

Users can change their password in:

```text
Settings -> Platform Password
```

If the password is lost, reset it on the target server:

```bash
docker compose exec web-api python -m app.cli reset-password --username admin
```

Or pass the password directly:

```bash
docker compose exec web-api python -m app.cli reset-password --username admin --password password
```

## 9. Upgrade

Pull or copy the updated source code, then rebuild:

```bash
docker compose build
docker compose up -d
```

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

## 10. Security Checklist

- Do not commit `.env`.
- Do not commit SQLite databases.
- Do not commit Prometheus data directories.
- Do not commit Tower URLs, tokens, usernames, passwords, VM names, or collected capacity data.
- Use read-only CloudTower credentials.
- Restrict access to backend and Prometheus ports in production networks.
- Rotate `SMARTX_SECRET_KEY` and `SMARTX_CREDENTIAL_KEY` before production use.
