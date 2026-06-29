# Release Acceptance

This document defines the release gate for SmartX HCI Capacity Insight. A release is accepted only after the final tag, final images, deployment compose files, and upgrade package are verified together.

## Environment Roles

- `dev/debug`: use `10.20.11.3`. Local builds, temporary patches, dirty data, container inspection, and quick rebuilds are allowed. This environment is not a release pass.
- `upgrade rehearsal`: use `10.20.11.12`. Use it for upgrade package rehearsal such as `v0.5.0 -> v0.5.2`, `v0.5.1 -> v0.5.2`, and `v0.5.2 -> v0.5.2`. Record the starting version, image tags, upgrade package sha256, and database state before every run.
- `release canary`: use a dedicated clean host when available. It must use the final `main` tag, DockerHub tag images, release compose files, and GitHub Release upgrade packages. Do not treat hot-patched containers as accepted.

Production-like hosts such as `10.20.0.6` are read-only by default. Any file write, container recreate, cleanup, recovery, or deployment action must be listed first and explicitly approved.

## Anti-Pollution Rules

- Do not run `docker compose build` on release canary.
- Do not edit JavaScript, Python, config files, or database records inside running containers.
- Do not validate with untagged images, local-only images, or images built from a dirty source tree.
- If a canary issue requires diagnosis, fix it in `dev2`, push to `main`, create or move the test tag, rebuild images, and redeploy canary from zero.
- Every release pass must record platform version, Runner version, image tags, image digests when available, upgrade package sha256, data source, timestamp, and failed checks.

## v0.5.2 Gate

The `v0.5.2` release gate verifies the compose project/network fix and the upgrade package path.

Expected values:

- Platform version: `v0.5.2`
- Runner version: `v0.3.1`
- Compose project: `smartx-storage-forecast`
- Docker network: `smartx-hci-capacity-insight-net`
- Prometheus version: `v2.55.1`
- Upgrade package: `smartx-capacity-insight-upgrade-v0.5.2.tar.gz`
- Upgrade package sha256: `5544a0e2bf67ea59141312e99630de1f1a3082484e4f70f45646454250c6aef2`

Deployment checks:

1. Place the compose files in a directory whose name is not `smartx-storage-forecast`.
2. Run `docker compose -f docker-compose.offline.yml up -d`.
3. Verify container labels contain `com.docker.compose.project=smartx-storage-forecast`.
4. Verify Docker has exactly one SmartX runtime network named `smartx-hci-capacity-insight-net`.
5. Verify Service Management shows `web-api`, `collector-worker`, `frontend`, `prometheus`, and `upgrade-runner`.
6. Verify the observability component shows Prometheus `v2.55.1`.

Upgrade checks:

1. Start from `v0.5.0`, `v0.5.1`, or `v0.5.2`; the `v0.5.2 -> v0.5.2` path is a repair/re-sync install and must not run duplicate SQLite migrations.
2. Upload the `v0.5.2` upgrade package.
3. Confirm upload and precheck show the package sha256.
4. Start the upgrade and confirm progress reaches completion.
5. Confirm no second compose project or second SmartX network is created.
6. Confirm `/api/system/health` returns the target platform version and Runner version.

## Smoke Command

Use the read-only smoke script for the API and frontend gate:

```bash
python3 scripts/release_smoke_check.py \
  --base-url http://127.0.0.1:8000 \
  --frontend-url http://127.0.0.1:8080 \
  --prometheus-url http://127.0.0.1:9090 \
  --username admin \
  --password 'change-me' \
  --expected-version v0.5.2 \
  --expected-runner-version v0.3.1 \
  --expected-compose-project smartx-storage-forecast \
  --expected-network smartx-hci-capacity-insight-net
```

Without `--username` and `--password`, the script only checks public endpoints such as frontend, Prometheus, and `/api/system/health`.

## Required Smoke Coverage

- Backend health: `/api/system/health`.
- Frontend reachability: HTTP 200 from the configured frontend URL.
- Prometheus health: `/-/healthy`.
- Authenticated API checks when credentials are provided:
  - `/api/tasks`
  - `/api/reports/latest`
  - `/api/admin/upgrade/version`
  - `/api/admin/component-upgrade/version`
  - `/api/admin/component-upgrade/components`
  - `/api/admin/upgrade/verification`
- Report growth contract:
  - Daily and monthly Top VM items must not render empty VM names.
  - Both top-level `vm_name/vm_id` and legacy `labels.vm/labels.vm_id` must remain accepted by the frontend.
