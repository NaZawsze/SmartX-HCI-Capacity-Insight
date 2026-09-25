# Release Acceptance

This document defines the release gate for SmartX HCI Capacity Insight. A release is accepted only after the final tag, final images, deployment compose files, and upgrade package are verified together.

## Environment Roles

- `dev/debug`: use `10.20.11.3`. Local builds, temporary patches, dirty data, container inspection, and quick rebuilds are allowed. This environment is not a release pass.
- `upgrade rehearsal`: use `10.20.11.12`. Use it for upgrade package rehearsal such as `v0.5.1u2 -> v0.5.3`, `v0.5.2 -> v0.5.3`, and `v0.5.3 -> v0.5.3`. Record the starting version, image tags, upgrade package sha256, and database state before every run. **Strict real-environment discipline (user, 2026-09-20): no manual host-side changes on .12 — no hand `docker rmi`, no manual directory cleanup, no file edits. Everything on .12 goes through product flows only (upgrade center, in-product features).**
- `release canary`: use a dedicated clean host when available. It must use the final `main` tag, DockerHub tag images, release compose files, and GitHub Release upgrade packages. Do not treat hot-patched containers as accepted. **Current standing (2026-09-20, per user): `10.20.0.6` is the frp Tower host and is NOT a canary target; the upgrade-rehearsal host `10.20.11.12` carries the production-equivalent acceptance duty (Phase 30 fresh-deploy validation plus multiple real upgrade runs) until a dedicated clean canary host exists.**

Production-like hosts are read-only by default. Any file write, container recreate, cleanup, recovery, or deployment action must be listed first and explicitly approved.

## Anti-Pollution Rules

- Do not run `docker compose build` on release canary.
- Do not edit JavaScript, Python, config files, or database records inside running containers.
- Do not validate with untagged images, local-only images, or images built from a dirty source tree.
- If a canary issue requires diagnosis, fix it in `dev2`, push to `main`, create or move the test tag, rebuild images, and redeploy canary from zero.
- Every release pass must record platform version, Runner version, image tags, image digests when available, upgrade package sha256, data source, timestamp, and failed checks.

## v0.5.3 Gate

The `v0.5.3` release gate verifies the compose project/network fix, the single-root directory layout, and the upgrade package path.

Expected values:

- Platform version: `v0.5.3`
- Runner version: `v0.3.1`
- Compose project: `smartx-hci-capacity-insight`
- Docker network: `smartx-hci-capacity-insight-net`
- Prometheus version: `v2.55.1`
- Upgrade package: `smartx-capacity-insight-upgrade-v0.5.3.tar.gz`
- Upgrade package sha256: `4a3c7bbd40baa1fe1f88690f504328853b92edd77735f0059af5870cac898db6` (2026-09-25 rebuild from dev2 `cdfe600`, all package gates passed on 10.20.11.3; **.12 normal-upgrade acceptance pending** — previous validated package `6accea95…` from dev2 `ff1bd52` completed acceptance 2026-09-20 and is the strict ancestor of this build)

Validated on `10.20.11.12` on 2026-09-20 (task `upgrade-b45996653f6955b6`, v0.5.2 baseline restored then normal upgrade path; main task and post-cleanup succeeded, 8-item acceptance passed); earlier validation on 2026-09-19 used `ef10a7c8…` (task `upgrade-e1fe8a62ea767ab7`). Package identity and evidence live in [upgrade-package-ledger.md](upgrade-package-ledger.md).

Deployment checks:

1. Place the compose files in a directory whose name is not `smartx-storage-forecast`.
2. Run `docker compose -f docker-compose.offline.yml up -d`.
3. Verify container labels contain `com.docker.compose.project=smartx-hci-capacity-insight`.
4. Verify Docker has exactly one SmartX runtime network named `smartx-hci-capacity-insight-net`.
5. Verify Service Management shows `web-api`, `collector-worker`, `frontend`, `prometheus`, and `upgrade-runner`.
6. Verify the observability component shows Prometheus `v2.55.1`.

Upgrade checks:

1. Start from `v0.5.0`, `v0.5.1`, `v0.5.1u2`, or `v0.5.2`; the `v0.5.3 -> v0.5.3` path is a repair/re-sync install and must not run duplicate SQLite migrations. From `v0.5.1u2` the upgrade performs the project/network and directory transition in one step.
2. Upload the `v0.5.3` upgrade package.
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
  --expected-version v0.5.3 \
  --expected-runner-version v0.3.1 \
  --expected-compose-project smartx-hci-capacity-insight \
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

## Release Day Steps

Ordered checklist for cutting a platform release. Rules and boundaries live in `AGENTS.md` and `docs/version-governance.md`; this fixes the step order.

1. **Version bump**: root `VERSION`, `backend/app/core/config.py` and `backend/app/v2/config.py` defaults, compose default tags, `README.md` / `README.zh-CN.md`, `docs/releases/CHANGELOG.md`, `docs/version-governance.md`.
2. **Local checks**: backend unittest (environment skips allowed), frontend `npx tsc -b` + vitest.
3. **Build on `10.20.11.3`**: build images, run the full backend suite (current baseline 310 tests), build the upgrade package with `scripts/build_upgrade_package.py`, run `scripts/verify_upgrade_package_identity.py`, record package path and SHA256.
4. **Rehearse on `10.20.11.12`**: real upgrade from a supported source version via the upgrade center (upload → precheck → start → verification → post-cleanup); record task ID, health output, and evidence in `progress.md`; add the package row to `docs/upgrade-package-ledger.md`.
5. **Git release actions (push / tag / GitHub Release) happen only after the user explicitly asks.** Package delivery is complete before any git release action, never because of it.
