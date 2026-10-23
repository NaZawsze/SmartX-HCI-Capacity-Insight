# Upgrade Guide

简体中文 → [upgrade.zh-CN.md](upgrade.zh-CN.md) | English

Version: `v0.5.4`

This guide covers upgrading an existing SmartX HCI Capacity Insight deployment using official offline delivery bundles. Fresh deployment is covered in the [Deployment Guide](deployment.md). For failures during an upgrade, see [troubleshooting](troubleshooting.md).

## 1. What you keep after every upgrade

Every upgrade preserves business data in place:

- SQLite business database under `app/`.
- Prometheus history under `prometheus/`.
- Tower configuration and credentials in `app/` + the paired `project/.env`.
- Report exports and migration files under `exports/`.

The platform upgrade itself generates a backup of the current version before switching, so a same-version reinstall or a rollback path stays available. Still, take your own cold backup of `app/smartx.db` plus `.env` before starting — see [backup-recovery](backup-recovery.md).

## 2. The two-step rule (runner component first)

Within the current release batch (`v0.5.4`), upgrades are executed in **two steps, and the order must not be reversed**:

1. **Step 1 — runner component upgrade** (Web UI first)
2. **Step 2 — platform upgrade** (CLI, after step 1 succeeds)

Why the order is fixed and cannot be flipped:

- The platform upgrade plan contains database migration actions that are executed by the **currently running runner** on the site.
- Newer runner component packages carry the runner build able to execute those actions. The previously published runner baseline (or any older runner) must not execute them; if it does, the migration step fails.
- The runner is only replaced by the **component upgrade** — the platform upgrade never touches or restarts the runner itself.

## 3. Choose your path

| Your current state | What to run | Notes |
| --- | --- | --- |
| Fresh install of `v0.5.4` from the offline bundle (runner `v0.3.1`) | Step 1 once (runner component package from `upgrade/packages/` of the same bundle), then you are aligned | The bundle's install compose pins the published baseline; the component upgrade brings the site to the batch's runner version |
| Deployed `v0.5.3` (runner `v0.3.1`) upgrading to `v0.5.4` | Step 1 (runner component of the `v0.5.4` batch) → Step 2 (platform package) | Both steps use the `v0.5.4` offline delivery bundle |
| Later batches | Follow the same two-step rule whenever the batch's README says it ships a runner component package; if it does not, platform-only | The bundle README always lists what the batch ships |
| `v0.5.2` target-layout site | Go `v0.5.2 → v0.5.3` first (its bundle, online or offline), then apply the `v0.5.4` path above | `v0.5.3` upgrade packages may declare one-step direct upgrade from older sources, only if their source compatibility covers your version |
| `v0.5.1u2` or older layout | Use the historical chain: `v0.5.1u2 → runner bootstrap → v0.5.2 → v0.5.3` documented in earlier release notes, then the `v0.5.4` path | Old-source layouts are not supported by newer bundles |

Rule of thumb: **the delivery bundle README is the authoritative per-batch procedure**. It states which packages the batch ships, what order they must run in, and what source versions are supported.

## 4. Step 1 — runner component upgrade (Web UI)

1. Unpack the offline delivery bundle on the site and locate the runner component package in `upgrade/packages/` (the README lists the exact file names).
2. Open the web UI `http://<server-ip>:8080`, log in as administrator.
3. Go to **Service Management → Component Upgrade** and upload the runner component package.
4. Wait for the prechecks to pass, then start the upgrade and wait for the task to reach `succeeded`.
5. Confirm the component upgrade history shows the new runner version (or check `GET /api/admin/component-upgrade/version`).

Notes:

- Only one upgrade task may run at a time; start the component upgrade only when no other upgrade task is running.
- The runner replaces itself in the last step of the component upgrade task; the platform upgrade never restarts it.
- If the component upgrade fails mid-way, the previously running runner keeps serving; re-upload the package after fixing the root cause.

## 5. Step 2 — platform upgrade (CLI)

After the component upgrade succeeded:

```bash
cd <unpacked-bundle-root>
sudo bash upgrade/upgrade.sh --yes
```

If `upgrade/packages/` contains several platform packages, pick one explicitly:

```bash
sudo bash upgrade/upgrade.sh --package upgrade/packages/<platform-package-name>.tar.gz --yes
```

The script drives the platform upgrade through the upgrade center API (no direct image loading, no manual container restarts), streaming precheck output as it goes.

The same flow is also possible through the web UI (Service Management → upload the platform package → precheck → start → wait for `succeeded`); use whichever interface your team standardizes on — both write to the same task center.

## 6. After the upgrade

1. Health check:

   ```bash
   curl -s http://127.0.0.1:8000/api/system/health | grep -E '"version"|"runner_version"'
   ```

   `"version"` must be the platform version you just installed, and `"runner_version"` must be the runner version of the component package you installed in step 1.

2. All five containers `Up`, `upgrade-runner` `(healthy)`.
3. The web UI at `http://<server-ip>:8080` loads, login works.
4. Business data intact: dashboard and VM pages show the same cluster capacity and VM data as before.
5. Trigger one manual collection and confirm it succeeds.

## 7. Rollback

Two rollback paths exist, depending on what needs to be undone:

| Scenario | What it restores | Data impact |
| --- | --- | --- |
| **Rollback to previous version** — application-only; button label in the UI is “回滚到上一版本（应用回滚，保数据）” | `web-api` / `collector-worker` / `frontend` containers back to the previous version | Business data preserved in place |
| **Full-stack rollback** — button label in the UI is “整备回滚（数据回到升级前）”; covers SQLite and Prometheus with the pre-upgrade snapshot | Previous version container stack plus the full data snapshot taken before the upgrade | Restores to the pre-upgrade snapshot; any collected data after that snapshot is lost |

Service Management shows rollback availability for both and starts them as dedicated tasks. The full-stack rollback shows a data-loss-window confirmation (data collected since the upgrade moment) and requires explicit confirmation before it runs.

Notes:

- The full-stack rollback rewrites the data directories to the snapshot state; anything collected after the upgrade that must survive should be exported first.
- Do not attempt to "hand-roll" a rollback by manually restarting containers with ad-hoc compose commands; use the rollback tasks only.

## 8. Rules and known pitfalls

- **One upgrade task at a time.** While any upgrade/rollback/recovery task exists, starting a new one is rejected.
- **Never run platform upgrade while the runner is stopped or restarting.**
- **Never use a platform upgrade task to update the runner.** Runner versions move through component upgrades only.
- **Do not manually load images or restart containers** as a "fix"; the upgrade center owns container state.
- **Do not delete or move data directories** under `/data/smartx-storage-forecast` while containers are running.
- **Keep `.env` with the database it pairs with** for any migration/export round trip; unpaired packages cannot decrypt Tower credentials.
- If a platform upgrade fails at precheck, read the returned remediation messages first (each check names its finding); do not retry blindly.
- Repeat-run protection: re-submitting the same platform package at the same version is rejected by default so an accidental rerun doesn't skip a failed step; the explicit override flag exists for confirmed reruns.

## 9. Where the other docs live

- [Deployment Guide](deployment.md) — fresh install (bundle / online / custom image tars)
- The offline bundle README — the per-batch authoritative procedure for exactly the bundle you have
- [troubleshooting](troubleshooting.md) — diagnosing failed upgrades, rollback forensics, and other operational failures
- [backup-recovery](backup-recovery.md) — cold backup and the restore five-step
- [Version notes](releases/CHANGELOG.md) — what each release changes
