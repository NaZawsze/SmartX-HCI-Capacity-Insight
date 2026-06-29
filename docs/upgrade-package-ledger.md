# Upgrade Package Ledger

This file tracks manually generated upgrade packages during the v0.5.0/v0.5.1 to v0.5.2 upgrade-chain debugging work.

Do not treat a package as usable only because it exists on disk. Use the `Status` column below.

## Upgrade Chain

```text
v0.5.0/v0.5.1 + runner v0.3.0
  -> v0.5.1u2 + runner v0.3.0
  -> v0.5.1u2 + runner v0.3.1 bootstrap
  -> v0.5.2 + runner v0.3.1
```

## Package Status Rules

- `USE`: current candidate for the next validation pass.
- `SUPERSEDED`: replaced by a newer package with a more complete fix.
- `DO NOT USE`: known wrong package or wrong upgrade-chain semantics.
- `UNKNOWN`: exists on a host, but has not been revalidated in this ledger.

## v0.5.1u2 Platform Package Fix Series

The logical version stays `v0.5.1u2`, but every rebuilt tarball must be tracked as a fix attempt.

| Fix ID | Status | Built At | Host Path | SHA256 | Intended Fix | Actual Problem / Result |
| --- | --- | --- | --- | --- | --- | --- |
| `v0.5.1u2-fix0` | DO NOT USE | 2026-06-28 13:38 | `/data/upgrade-packages/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `2b5688b519c86b6ba84cbddb8f8d171b3ffb09c0f6f60e76358c9bf7cb033f2a` | First bridge-package attempt. | Wrong package semantics for this chain: packaged compose used new project name `smartx-hci-capacity-insight`. v0.5.1u2 must stay on old project/network. |
| `v0.5.1u2-fix0-copy` | DO NOT USE | 2026-06-28 16:36 | `/data/upgrades/upgrade-e0e503b6e4d7a3d9/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `2b5688b519c86b6ba84cbddb8f8d171b3ffb09c0f6f60e76358c9bf7cb033f2a` | Copy of `fix0` inside an upgrade task directory. | Same package as `fix0`; same wrong new-project compose issue. |
| `v0.5.1u2-fix1` | DO NOT USE | 2026-06-29 12:55 | `/home/user1/codex-build/packages-101112-fix/v0.5.1u2/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `8777c5b7e041a743435548ee86f81758196b501e7457efcf9ce927a0cbfc0e70` | Attempted to repair 10.20.11.12 upgrade failure. | Still wrong for the bridge: manifest used v0.3.1-style capabilities/min-runner semantics instead of legacy runner v0.3.0 actions. |
| `v0.5.1u2-fix2` | SUPERSEDED | 2026-06-29 13:16 | `/home/user1/codex-build/packages-v051-to-v052-chain/01-v0.5.1u2/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `2b37140767c80fa92641ce1041abb7eb43b959a215b1ab97da686be52e91ddaf` | Rebuilt according to the written chain: `v0.5.1 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2`. | Replaced after runner display/bootstrap problems were found. |
| `v0.5.1u2-fix3` | SUPERSEDED | 2026-06-29 14:29 | `/home/user1/upgrade-packages-v0.5.1u2/fixed-runner-version-display/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `f5fe23d460bc6fd242cfade1a86589d5ebafde3fc1aaf157ead36ad4afe74d2e` | Keep old project/network and fix runner-version display logic. | Did not fully fix the runner v0.3.1 bootstrap step: web-api still generated runner upgrade semantics rather than explicit bootstrap semantics. |
| `v0.5.1u2-fix4` | SUPERSEDED | 2026-06-29 15:43 | `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `4aec00cb074dcdb09d278413a9ffe5140e751164921e80b79912ccf55f822841` | Add `docker-compose.runner-bootstrap.yml` generation in v0.5.1u2 web-api for runner v0.3.1 bootstrap packages. | Replaced after discovering completed tasks with green checks could still project `precheck_ok=true`, causing UI/API contradiction. |
| `v0.5.1u2-fix5` | SUPERSEDED | 2026-06-29 16:06 | `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `d88569c228af182b8648c12f7ffd9d3f4fbf2482b70c7f1f703af1ffae833626` | Include both fixes: runner bootstrap compose generation and strict `precheck_ok = status == precheck_passed` projection. | Failed on 10.20.11.12: bootstrap compose used `/data:/data`, so runner v0.3.1 wrote heartbeat to `/data/smartx.db` instead of app DB. |
| `v0.5.1u2-fix6` | SUPERSEDED | 2026-06-29 16:40 | `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2-fix6/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `a669b1237857fb785720ea2ffd8cfa620a62e6ec086b689682d429e0f6b9c295` | Fix host DB path source for runner bootstrap. Use `SMARTX_HOST_DATA_PATH` instead of container-derived `settings.sqlite_dir`. | Superseded before target validation: it fixes wrong DB mount but does not stop old project runner v0.3.0, which can keep overwriting app DB heartbeat. |
| `v0.5.1u2-fix7` | SUPERSEDED | 2026-06-29 16:50 | `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2-fix7/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `6c9e7eb72ee89fe6ab597784f07dadc872d43e480a69e941a7a86923d5728090` | Fix host DB path and stop old project `upgrade-runner` after bootstrap starts new runner. | Backend/bootstrap result is correct, but v0.5.1u2 frontend can keep showing stale runner `v0.3.0` and missing execution steps after an immediate-success component start. Replaced by `fix8`. |
| `v0.5.1u2-fix8` | SUPERSEDED | 2026-06-29 19:04 CST | `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2-fix8/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `7e1606132166dff191a72cbfea925c981adba82974836e1afbbea9b26dd8cfb2` | Keep all `fix7` backend/bootstrap behavior and fix the v0.5.1u2 frontend component-upgrade refresh path. | Superseded by `fix9`: the test used the wrong task shape and did not catch real runner tasks where `component` is missing and `components=["runner"]`; web-api also still treated its bundled `/app/RUNNER_VERSION` as the current runner fallback. |
| `v0.5.1u2-fix9` | SUPERSEDED | 2026-06-29 20:34 CST | `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2-fix9/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `724265634635c50e079f6e2576c51dc294a83ddfabf4c85a631ee6990cdb6f4b` | Fix active runner version source and real runner component task projection. Current runner version now comes only from fresh heartbeat, running runner container `/app/RUNNER_VERSION`, or running runner image tag; no web-api baseline fallback. Frontend binds `components=["runner"]` tasks to `upgrade-runner` and shows real component steps/progress. | Superseded by `fix10`, which keeps the same runtime fixes and adds `v0.5.1u1` to the v0.5.1u2 bridge package supported source versions. |
| `v0.5.1u2-fix10` | USE | 2026-06-29 20:55 CST | `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2-fix10/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `b976ef8c761271ac06cd8bd3e23d3394a84360ea189e46b1042bc2ced70651df` | Same as `fix9`, plus `source_compatibility.supported_versions` now includes `v0.5.1u1` so `v0.5.1u1 -> v0.5.1u2` is explicitly allowed and shown in the UI. | Built and gated on 10.20.11.3. Manifest now lists `v0.5.0`, `v0.5.1`, `v0.5.1u1`, `v0.5.1u2`; package still has no `minimum_runner_version`, no runner image, and old project/network compose defaults. Current candidate. |

### v0.5.1u2 Fix Details

#### `v0.5.1u2-fix0`

- Purpose: initial v0.5.1u2 bridge package.
- Mistake: compose project/network moved too early to `smartx-hci-capacity-insight`.
- Why it failed: v0.5.1u2 is only the bridge into runner v0.3.1; it must not move platform services to the new project/network.

#### `v0.5.1u2-fix1`

- Purpose: repair upgrade failure on 10.20.11.12.
- Mistake: mixed v0.5.2/runner v0.3.1 assumptions into v0.5.1u2.
- Why it failed: old runner v0.3.0 cannot be required to understand the newer protocol/action set before it has been upgraded.

#### `v0.5.1u2-fix2`

- Purpose: align package with the explicit chain.
- Change: keep v0.5.1u2 as a bridge package.
- Why it was superseded: later investigation found runner-version display/bootstrap behavior was still not fully handled.

#### `v0.5.1u2-fix3`

- Purpose: fix runner version display and keep old project/network.
- Change: web-api reads active runner heartbeat for display.
- Why it was superseded: runner v0.3.1 bootstrap still used confusing runner-upgrade semantics and did not prove correct DB heartbeat wiring.

#### `v0.5.1u2-fix4`

- Purpose: make v0.5.1u2 web-api generate explicit `docker-compose.runner-bootstrap.yml`.
- Change: bootstrap manifest writes new project/network/subnet and mounts app DB as `/data`.
- Why it was superseded: task projection bug remained; completed tasks with green checks could still show as precheck-ready.

#### `v0.5.1u2-fix5`

- Purpose: combine bootstrap generation fix and precheck projection fix.
- Change 1: `bootstrap_runner.enabled=true` writes `docker-compose.runner-bootstrap.yml`.
- Change 2: bootstrap compose uses target project/network/subnet.
- Intended change 3: bootstrap compose mounts `/data/smartx-capacity-insight-data/app:/data`.
- Change 4: `precheck_ok` is true only when task status is exactly `precheck_passed`.
- Actual failure on 10.20.11.12: generated bootstrap compose mounted `/data:/data` because the generator used container-derived `settings.sqlite_dir`.

#### `v0.5.1u2-fix6`

- Purpose: fix the real 10.20.11.12 runner v0.3.1 display failure.
- Root cause: `settings.sqlite_dir` resolves to `/data` inside web-api when `SMARTX_DB_PATH=/data/smartx.db`.
- Required change: use `SMARTX_HOST_DATA_PATH` as the host DB mount source.
- Required generated compose:
  - `SMARTX_HOST_DATA_PATH: /data/smartx-capacity-insight-data/app`
  - `- /data/smartx-capacity-insight-data/app:/data`
- Rejection rule: if `docker-compose.runner-bootstrap.yml` contains `- /data:/data`, fix6 fails.
- Package SHA256: `a669b1237857fb785720ea2ffd8cfa620a62e6ec086b689682d429e0f6b9c295`.
- Package path: `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2-fix6/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz`.
- 10.20.11.3 verification:
  - manifest has no `minimum_runner_version`
  - required capabilities remain legacy runner v0.3.0 actions
  - compose project remains `smartx-storage-forecast`
  - image contains `_host_data_path()` and `SMARTX_HOST_DATA_PATH`
- Superseded reason: 10.20.11.12 also had old project runner v0.3.0 still running. After DB mount is fixed, that old runner could still overwrite app DB heartbeat unless it is stopped.

#### `v0.5.1u2-fix7`

- Purpose: complete runner bootstrap handoff.
- Change 1: keep fix6 host DB path behavior.
- Change 2: after starting new project runner v0.3.1, run `docker compose -f <current compose> --project-name smartx-storage-forecast stop upgrade-runner`.
- Required result:
  - new runner v0.3.1 writes app DB
  - old runner v0.3.0 stops and cannot overwrite app DB
  - health reports `runner_version=v0.3.1`
- Package SHA256: `6c9e7eb72ee89fe6ab597784f07dadc872d43e480a69e941a7a86923d5728090`.
- Package path: `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2-fix7/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz`.
- 10.20.11.3 verification:
  - manifest has no `minimum_runner_version`
  - required capabilities remain legacy runner v0.3.0 actions
  - compose project remains `smartx-storage-forecast`
  - image contains `_host_data_path()`, `SMARTX_HOST_DATA_PATH`, and old runner stop command
- Superseded reason: backend/bootstrap handoff is correct, but the v0.5.1u2 frontend can keep stale component state when runner bootstrap returns `success` immediately. Because the polling effect only starts for running states, the page may not reload `/api/admin/component-upgrade/components`, so it can still display runner `v0.3.0` and hide final execution steps until a manual refresh.

#### `v0.5.1u2-fix8`

- Purpose: make the v0.5.1u2 bridge UI reflect the already-correct runner bootstrap result.
- Keeps fix7 behavior:
  - runner bootstrap compose uses `SMARTX_HOST_DATA_PATH`
  - runner bootstrap mounts `/data/smartx-capacity-insight-data/app:/data`
  - new runner uses `smartx-hci-capacity-insight` / `smartx-hci-capacity-insight-net` / `10.249.251.0/24`
  - old project `upgrade-runner` is stopped after the new runner starts
- Frontend change:
  - after `startComponentUpgrade()`, the page now refreshes component task status, component history, component list, and runner version together
  - the same refresh path is used when polling observes a component task complete
  - `success` is normalized as a completed task status, matching backend task status
- Regression test:
  - `ServicePage` now covers runner bootstrap returning `success` immediately
  - the test asserts the page refreshes from runner `v0.3.0` to `v0.3.1`
  - the test asserts final execution steps are visible
- Package SHA256: `7e1606132166dff191a72cbfea925c981adba82974836e1afbbea9b26dd8cfb2`.
- Package path: `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2-fix8/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz`.
- 10.20.11.3 verification:
  - frontend `ServicePage.test.tsx`: 21 tests passed
  - backend target tests passed:
    - `test_runner_bootstrap_uses_target_project_network_and_app_database`
    - `test_completed_task_with_green_checks_is_not_precheck_ready`
  - `python3 -m py_compile backend/app/v2/upgrade/service.py backend/tests/test_v2_upgrade.py` passed
  - manifest has no `minimum_runner_version`
  - required capabilities remain legacy runner v0.3.0 actions
  - package contains `images/web-api.tar`, `images/collector-worker.tar`, and `images/frontend.tar` only
  - compose project remains `smartx-storage-forecast`
  - compose network remains `smartx-storage-forecast_smartx-net`
  - compose subnet remains `10.249.249.0/24`
  - web-api image contains `_host_data_path()`, `SMARTX_HOST_DATA_PATH`, `docker-compose.runner-bootstrap.yml`, and old runner stop command
  - frontend image contains component-upgrade status assets

#### `v0.5.1u2-fix9`

- Purpose: fix the actual cause of runner still displaying `v0.3.0` after runner bootstrap.
- Root cause 1: web-api used its own bundled `/app/RUNNER_VERSION` as the fallback for current runner version. In v0.5.1u2 that file is intentionally `v0.3.0`, so it can falsely report runner `v0.3.0` even after active runner is `v0.3.1`.
- Root cause 2: the frontend fix8 test assumed public tasks had `component="upgrade-runner"`, but real completed runner bootstrap tasks can have no top-level `component` and only `components=["runner"]`.
- Backend changes:
  - active runner version source order is fresh `upgrade_runner_state` heartbeat, then running `upgrade-runner` container `/app/RUNNER_VERSION`, then running runner image tag.
  - heartbeat older than 30 seconds is stale.
  - no active runner returns `未检测到 runner`; it does not fall back to web-api baseline.
  - runner protocol precheck only treats fresh heartbeat as capability evidence.
  - `_public_task()` and `history(component_type="runner")` derive component type from `task.components`, then manifest components, then legacy `task.component`.
- Frontend changes:
  - `upgrade-runner` task matching accepts `task.component === "upgrade-runner"` or `task.components` containing `runner`.
  - component package selection, details, target version, selected package, action buttons, and execution steps all use the same component matcher.
  - component mode no longer creates platform default execution steps when backend returns no real steps.
  - current/running component packages remain visible in the package area with a progress bar.
- Package SHA256: `724265634635c50e079f6e2576c51dc294a83ddfabf4c85a631ee6990cdb6f4b`.
- Package path: `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2-fix9/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz`.
- 10.20.11.3 verification:
  - `PYTHONPATH=backend python3 -m unittest backend.tests.test_v2_upgrade`: 28 tests passed, 1 skipped.
  - `python3 -m py_compile backend/app/v2/upgrade/service.py backend/app/v2/system/health.py backend/tests/test_v2_upgrade.py`: passed.
  - package manifest: `version=v0.5.1u2`, `min_version=v0.5.0`, no `minimum_runner_version`, legacy runner v0.3.0 capabilities only.
  - package components: platform only; no runner image archive.
  - package compose defaults: `SMARTX_COMPOSE_PROJECT_NAME=smartx-storage-forecast`, network `smartx-storage-forecast_smartx-net`, no `smartx-hci-capacity-insight-net`.
  - web-api image contains `RUNNER_NOT_DETECTED`, `_active_runner_state_from_docker`, and `_component_types_from_task`.
- Local code verification:
  - `frontend/src/pages/ServicePage.test.tsx`: 21 tests passed.
  - `frontend` `tsc -b`: passed.

#### `v0.5.1u2-fix10`

- Purpose: include `v0.5.1u1` as a valid source for the `v0.5.1u2` bridge package.
- Change:
  - `source_compatibility.supported_versions` now lists `v0.5.0`, `v0.5.1`, `v0.5.1u1`, and `v0.5.1u2`.
  - UI “兼容来源版本” therefore shows `v0.5.1u1`.
- Keeps fix9 runtime behavior:
  - active runner version source fix.
  - real `components=["runner"]` component task projection.
  - frontend component task binding and steps/progress display.
- Package SHA256: `b976ef8c761271ac06cd8bd3e23d3394a84360ea189e46b1042bc2ced70651df`.
- Package path: `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2-fix10/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz`.
- 10.20.11.3 manifest gates:
  - `version=v0.5.1u2`
  - `min_version=v0.5.0`
  - `source_compatibility.supported_versions=["v0.5.0","v0.5.1","v0.5.1u1","v0.5.1u2"]`
  - no `minimum_runner_version`
  - required capabilities remain legacy runner v0.3.0 actions
  - package components are platform only
  - no runner image archive
  - compose defaults remain `smartx-storage-forecast` / `smartx-storage-forecast_smartx-net`

## Runner v0.3.1 Packages

| Status | Built At | Host Path | SHA256 | What Changed | Known Result |
| --- | --- | --- | --- | --- | --- |
| SUPERSEDED | 2026-06-29 | `/home/user1/codex-build/packages-v051-to-v052-chain/02-runner-v0.3.1-bootstrap/smartx-upgrade-runner-v0.3.1.tar.gz` | `76d9eb25e4ed5fd2d0b9d952a79be195f7585dd2847bb1c485814a76950c0d57` | Early runner v0.3.1 bootstrap package. | Replaced after DB mount/runner display investigation. |
| USE | 2026-06-29 | `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/02-runner-v0.3.1-bootstrap/smartx-upgrade-runner-v0.3.1.tar.gz` | `2dcd14e633512b4a95254ea1dd299b4a2513bd64726e72d4e1cc2e75cdd633aa` | Manifest includes `bootstrap_runner` with target project/network/subnet. | Use after `v0.5.1u2-fix10`. The bridge package provides the required bootstrap compose generation, DB mount, old-runner stop, frontend/backend active runner display behavior, and `v0.5.1u1` source compatibility. |

## Current Candidate Validation Gates

Before calling a package fixed, verify all of these on the target host:

```text
health.version = v0.5.1u2 after v0.5.1u2 package
health.runner_version = v0.3.0 before runner bootstrap
docker-compose.runner-bootstrap.yml is generated for runner v0.3.1 bootstrap
runner bootstrap compose uses smartx-hci-capacity-insight / smartx-hci-capacity-insight-net / 10.249.251.0/24
runner bootstrap compose mounts /data/smartx-capacity-insight-data/app:/data
runner bootstrap compose must not contain /data:/data
health.runner_version = v0.3.1 after runner bootstrap
```

## Maintenance Rule

Whenever a new package is generated, update this ledger in the same turn with:

- build time
- full host path
- SHA256
- exact reason for rebuild
- superseded package
- validation result or explicit validation gap
