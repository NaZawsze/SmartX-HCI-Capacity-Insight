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
| `v0.5.1u2-fix0-copy` | DO NOT USE | 2026-06-28 16:36 | `/data/smartx-storage-forecast/upgrades/upgrade-e0e503b6e4d7a3d9/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `2b5688b519c86b6ba84cbddb8f8d171b3ffb09c0f6f60e76358c9bf7cb033f2a` | Copy of `fix0` inside an upgrade task directory. | Same package as `fix0`; same wrong new-project compose issue. |
| `v0.5.1u2-fix1` | DO NOT USE | 2026-06-29 12:55 | `/home/user1/codex-build/packages-101112-fix/v0.5.1u2/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `8777c5b7e041a743435548ee86f81758196b501e7457efcf9ce927a0cbfc0e70` | Attempted to repair 10.20.11.12 upgrade failure. | Still wrong for the bridge: manifest used v0.3.1-style capabilities/min-runner semantics instead of legacy runner v0.3.0 actions. |
| `v0.5.1u2-fix2` | SUPERSEDED | 2026-06-29 13:16 | `/home/user1/codex-build/packages-v051-to-v052-chain/01-v0.5.1u2/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `2b37140767c80fa92641ce1041abb7eb43b959a215b1ab97da686be52e91ddaf` | Rebuilt according to the written chain: `v0.5.1 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2`. | Replaced after runner display/bootstrap problems were found. |
| `v0.5.1u2-fix3` | SUPERSEDED | 2026-06-29 14:29 | `/home/user1/upgrade-packages-v0.5.1u2/fixed-runner-version-display/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `f5fe23d460bc6fd242cfade1a86589d5ebafde3fc1aaf157ead36ad4afe74d2e` | Keep old project/network and fix runner-version display logic. | Did not fully fix the runner v0.3.1 bootstrap step: web-api still generated runner upgrade semantics rather than explicit bootstrap semantics. |
| `v0.5.1u2-fix4` | SUPERSEDED | 2026-06-29 15:43 | `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `4aec00cb074dcdb09d278413a9ffe5140e751164921e80b79912ccf55f822841` | Add `docker-compose.runner-bootstrap.yml` generation in v0.5.1u2 web-api for runner v0.3.1 bootstrap packages. | Replaced after discovering completed tasks with green checks could still project `precheck_ok=true`, causing UI/API contradiction. |
| `v0.5.1u2-fix5` | SUPERSEDED | 2026-06-29 16:06 | `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `d88569c228af182b8648c12f7ffd9d3f4fbf2482b70c7f1f703af1ffae833626` | Include both fixes: runner bootstrap compose generation and strict `precheck_ok = status == precheck_passed` projection. | Failed on 10.20.11.12: bootstrap compose used `/data:/data`, so runner v0.3.1 wrote heartbeat to `/data/smartx.db` instead of app DB. |
| `v0.5.1u2-fix6` | SUPERSEDED | 2026-06-29 16:40 | `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2-fix6/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `a669b1237857fb785720ea2ffd8cfa620a62e6ec086b689682d429e0f6b9c295` | Fix host DB path source for runner bootstrap. Use `SMARTX_HOST_DATA_PATH` instead of container-derived `settings.sqlite_dir`. | Superseded before target validation: it fixes wrong DB mount but does not stop old project runner v0.3.0, which can keep overwriting app DB heartbeat. |
| `v0.5.1u2-fix7` | SUPERSEDED | 2026-06-29 16:50 | `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2-fix7/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `6c9e7eb72ee89fe6ab597784f07dadc872d43e480a69e941a7a86923d5728090` | Fix host DB path and stop old project `upgrade-runner` after bootstrap starts new runner. | Backend/bootstrap result is correct, but v0.5.1u2 frontend can keep showing stale runner `v0.3.0` and missing execution steps after an immediate-success component start. Replaced by `fix8`. |
| `v0.5.1u2-fix8` | SUPERSEDED | 2026-06-29 19:04 CST | `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2-fix8/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `7e1606132166dff191a72cbfea925c981adba82974836e1afbbea9b26dd8cfb2` | Keep all `fix7` backend/bootstrap behavior and fix the v0.5.1u2 frontend component-upgrade refresh path. | Superseded by `fix9`: the test used the wrong task shape and did not catch real runner tasks where `component` is missing and `components=["runner"]`; web-api also still treated its bundled `/app/RUNNER_VERSION` as the current runner fallback. |
| `v0.5.1u2-fix9` | SUPERSEDED | 2026-06-29 20:34 CST | `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2-fix9/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `724265634635c50e079f6e2576c51dc294a83ddfabf4c85a631ee6990cdb6f4b` | Fix active runner version source and real runner component task projection. Current runner version now comes only from fresh heartbeat, running runner container `/app/RUNNER_VERSION`, or running runner image tag; no web-api baseline fallback. Frontend binds `components=["runner"]` tasks to `upgrade-runner` and shows real component steps/progress. | Superseded by `fix10`, which keeps the same runtime fixes and adds `v0.5.1u1` to the v0.5.1u2 bridge package supported source versions. |
| `v0.5.1u2-fix10` | SUPERSEDED | 2026-06-29 20:55 CST | `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/01-v0.5.1u2-fix10/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `b976ef8c761271ac06cd8bd3e23d3394a84360ea189e46b1042bc2ced70651df` | Same as `fix9`, plus `source_compatibility.supported_versions` now includes `v0.5.1u1` so `v0.5.1u1 -> v0.5.1u2` is explicitly allowed and shown in the UI. | Superseded by `fix11`: v0.5.1u2 web-api also needs to compile the v0.5.2 execution plan with `runner.handoff_target_runtime`, otherwise v0.5.2 packages cannot trigger runner handoff before cleanup. |
| `v0.5.1u2-fix11` | DO NOT USE | 2026-07-02 21:28 CST | `/home/user1/codex-build/packages-v052-handofffix/01-v0.5.1u2-fix11/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `0482837fdf4a6785801cb27a03bb5a210146fbcb8f92e6abbf63c07e1f8ba0a8` | Keeps fix10 bridge behavior and adds v0.5.2 execution-plan compiler support for `runner.handoff_target_runtime` / `runner.handoff.v1`, plus runner target host path generation for later component upgrades. | Failed on 10.20.11.3 at the first normal-chain step from `v0.5.1 + runner v0.3.0`: manifest incorrectly required `minimum_runner_version=v0.3.1`, v0.3.1 capabilities, and `source_compatibility.supported_versions=[]`. This repeats the `fix1` class bridge error; v0.5.1u2 must remain installable by runner v0.3.0. |
| `v0.5.1u2-fix12-first` | DO NOT USE | 2026-07-02 CST | `/home/user1/codex-build/packages-v051u2-fix12/01-v0.5.1u2-fix12/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `475beeeb2a25f77fcbd29a23b3449474a742fa0cd437ccda4e3bd1d734ccbfc6` | Fix the bridge manifest: no `minimum_runner_version`, legacy runner v0.3.0 action capabilities, non-empty source compatibility. | Static gate failed: manifest is corrected, but packaged project files still come from the current v0.5.2 worktree. `project/docker-compose.release.yml` contains `smartx-hci-capacity-insight`, `smartx-hci-capacity-insight-net`, `/data/smartx-storage-forecast/*`, and `10.249.251.0/24`. v0.5.1u2 project files must stay on legacy layout. |
| `v0.5.1u2-fix12-projectfiles` | DO NOT USE | 2026-07-02 22:45 CST | `/home/user1/codex-build/packages-v051u2-fix12/02-v0.5.1u2-fix12-projectfiles/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `0d992c9cd42e4287db3fb43845e6590b84904d55846de952dadbc9116a2e14d9` | Keeps the corrected bridge manifest and fixes versioned project files: v0.5.1u2 package now generates legacy compose layout for `smartx-storage-forecast`, `smartx-storage-forecast_smartx-net`, `/opt/smartx-storage-forecast`, `/data/upgrades`, `/data/compose-runtime`, `/prometheus-data`, and subnet `10.249.249.0/24`. | Full-chain validation stopped on 10.20.11.3 at the first node: task `upgrade-07eb997948160b33` succeeded, containers used `*:v0.5.1u2` tags and stayed on legacy project/network, but `/api/system/health` reported `version=v0.5.2`. Evidence from `smartx-storage-forecast-web-api-1`: `/app/VERSION=v0.5.2`, `/app/RUNNER_VERSION=v0.3.1`, and `DEFAULT_APP_VERSION = "v0.5.2"` inside the image. The package reused wrongly built `v0.5.1u2` image tags whose contents are v0.5.2. |
| `v0.5.1u2-fix13-imageidentity` | CHAIN PASSED FOR PLATFORM BRIDGE | 2026-07-03 CST | `/home/user1/codex-build/packages-v051u2-fix13/01-v0.5.1u2-fix13-imageidentity/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `aa3b4a4a09410d3f65dbfa8bb85196b8bf81a58b127056be3ce5e6431cdd6c8a` | Add hard image identity gates: rebuild platform images by default, temporarily inject target image version metadata, create temporary empty `.env` only during compose build if missing, forbid silent polluted tag reuse, verify local image internals, and verify final package image tar internals. | Static gates passed and normal-chain first step passed on 10.20.11.3: `v0.5.1 + runner v0.3.0 -> v0.5.1u2 + runner v0.3.0`, task `upgrade-a1eaa16b4bcf22b7` succeeded; health returned `version=v0.5.1u2`, `runner_version=v0.3.0`, platform containers used `*:v0.5.1u2`, and legacy project/network remained unchanged. |
| `v0.5.1u2-fix14-env-postcleanup-compiler` | FIRST STEP PASSED / NEEDS FIXED RUNNER NEXT | 2026-07-06 CST | `/home/user1/codex-build/packages-v051u2-fix14/01-v0.5.1u2-fix14-env-postcleanup-compiler/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `4e40bbe1c02b4226c0f1ad2216d31361af955658e131c4216562f0346ef17078` | Keep all fix13 bridge/image-identity behavior, and add the compiler bridge needed for v0.5.2 postcleanup packages: when v0.5.2 manifest has `post_upgrade.create_cleanup_task=true`, v0.5.1u2 web-api must compile `post_upgrade.schedule_cleanup` instead of same-task `runner.handoff_target_runtime -> legacy.cleanup`. | 10.20.11.3 normal-chain first step passed: task `upgrade-20ada1e4a47ea1bd` succeeded and health became `version=v0.5.1u2`, `runner_version=v0.3.0`, `prometheus=true`. The later v0.5.2 step failed because the runner package used in the chain was still `runner-v0.3.1-handofffix1` and did not include the new action handlers required by this compiler output. |
| `v0.5.1u2-fix15-bootstrap-target-root` | PLANNED / LOCAL TESTS PASSED | 2026-07-06 CST | `/home/user1/codex-build/packages-v051u2-fix15/01-v0.5.1u2-fix15-bootstrap-target-root/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `TBD` | Keep fix14 behavior and fix runner bootstrap compose path topology: runner still scans legacy `/data/upgrades`, but bootstrap compose also mounts `/data/smartx-storage-forecast:/data/smartx-storage-forecast` so v0.5.2 `.env` migration and task mirror write to the real target host root. | Local tests passed. Full chain must be rerun on 10.20.11.3 with a rebuilt runner package containing `bootstrap_runner.target_root`. |

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
- Intended change 3: bootstrap compose mounts `/data/smartx-storage-forecast/app:/data`.
- Change 4: `precheck_ok` is true only when task status is exactly `precheck_passed`.
- Actual failure on 10.20.11.12: generated bootstrap compose mounted `/data:/data` because the generator used container-derived `settings.sqlite_dir`.

#### `v0.5.1u2-fix6`

- Purpose: fix the real 10.20.11.12 runner v0.3.1 display failure.
- Root cause: `settings.sqlite_dir` resolves to `/data` inside web-api when `SMARTX_DB_PATH=/data/smartx.db`.
- Required change: use `SMARTX_HOST_DATA_PATH` as the host DB mount source.
- Required generated compose:
  - `SMARTX_HOST_DATA_PATH: /data/smartx-storage-forecast/app`
  - `- /data/smartx-storage-forecast/app:/data`
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
  - runner bootstrap mounts `/data/smartx-storage-forecast/app:/data`
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

#### `v0.5.1u2-fix13-imageidentity`

- Status: static gated only; full normal-chain validation is blocked by the current 10.20.11.3 baseline.
- Purpose: prevent the exact `fix12-projectfiles` failure class where a Docker tag named `v0.5.1u2` contains v0.5.2 code.
- Required builder behavior:
  - Rebuild platform images by default.
  - Temporarily write target `VERSION`, `RUNNER_VERSION`, and default version constants during Docker build, then restore the source tree.
  - Temporarily create an empty `.env` only while `docker compose build` runs if the build context lacks `.env`, then remove it.
  - Allow existing image reuse only with an explicit opt-in flag.
  - Always verify image internal identity even when older version metadata checks are disabled.
  - Verify the final package's `images/*.tar` content, not only local Docker tags.
- Required identity:
  - `v0.5.1u2` web-api `/app/VERSION` must be `v0.5.1u2`.
  - `v0.5.1u2` web-api `/app/RUNNER_VERSION` must be `v0.3.0`.
  - `v0.5.2` web-api `/app/VERSION` must be `v0.5.2`.
  - `v0.5.2` web-api `/app/RUNNER_VERSION` must be `v0.3.1`.
- Required gates before `USE`:
  - manifest gate.
  - compose/project files gate.
  - local image identity gate.
  - package image tar identity gate.
  - package checksums gate.
  - no sensitive files gate.
  - `10.20.11.3` first-node validation: `v0.5.1 + runner v0.3.0 -> v0.5.1u2-fix13-imageidentity` must return `health.version=v0.5.1u2` and `health.runner_version=v0.3.0`.
- Current package:
  - path: `/home/user1/codex-build/packages-v051u2-fix13/01-v0.5.1u2-fix13-imageidentity/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz`
  - sha256: `aa3b4a4a09410d3f65dbfa8bb85196b8bf81a58b127056be3ce5e6431cdd6c8a`
  - static result: manifest/project files/checksums/no-sensitive-files/package image identity passed.
  - validation gap: 10.20.11.3 is not currently at `v0.5.1 + runner v0.3.0`, so full chain has not started.

## Runner v0.3.1 Packages

| Status | Built At | Host Path | SHA256 | What Changed | Known Result |
| --- | --- | --- | --- | --- | --- |
| SUPERSEDED | 2026-06-29 | `/home/user1/codex-build/packages-v051-to-v052-chain/02-runner-v0.3.1-bootstrap/smartx-upgrade-runner-v0.3.1.tar.gz` | `76d9eb25e4ed5fd2d0b9d952a79be195f7585dd2847bb1c485814a76950c0d57` | Early runner v0.3.1 bootstrap package. | Replaced after DB mount/runner display investigation. |
| SUPERSEDED | 2026-06-29 | `/home/user1/codex-build/packages-v051-to-v052-chain-rebuilt/02-runner-v0.3.1-bootstrap/smartx-upgrade-runner-v0.3.1.tar.gz` | `2dcd14e633512b4a95254ea1dd299b4a2513bd64726e72d4e1cc2e75cdd633aa` | Manifest includes `bootstrap_runner` with target project/network/subnet. | Superseded by `fsdirfix9`, which adds v0.5.2 directory-transition execution fixes. |
| DO NOT USE | 2026-07-02 | `/home/user1/codex-build/packages-v052-layout-fix/02-runner-v0.3.1-fsdirfix4/smartx-upgrade-runner-v0.3.1.tar.gz` | `4779e4bf616a9632170d40de6a611a3dfc66923ed2120d0b6034b9a043d36b7d` | Attempted to handle file-vs-directory project sync. | v0.5.2 still failed because package project copy skipped `prometheus/`, leaving Docker to create `prometheus.yml` as a directory. |
| DO NOT USE | 2026-07-02 | `/home/user1/codex-build/packages-v052-layout-fix/02-runner-v0.3.1-fsdirfix5/smartx-upgrade-runner-v0.3.1.tar.gz` | `d0cfe867de87e3059d5291c25c79a638f31b6cad058c45ff159905fd2ec3a5c0` | Prefer package `project/` source and replace stale directory targets. | Still failed v0.5.2: context path switching was incomplete and `prometheus.yml` could still become a directory. |
| DO NOT USE | 2026-07-02 | `/home/user1/codex-build/packages-v052-layout-fix/02-runner-v0.3.1-fsdirfix6/smartx-upgrade-runner-v0.3.1.tar.gz` | `22c7bf610ec4095ae512664481a996f3360150db4a68bc4ee0861040dd80811e` | Switched directory-transition context to target paths and stopped skipping package `prometheus/`. | Fixed `prometheus.yml` file type, but compose override was written before the runtime path switch and compose apply could not find it. |
| DO NOT USE | 2026-07-02 | `/home/user1/codex-build/packages-v052-layout-fix/02-runner-v0.3.1-fsdirfix7/smartx-upgrade-runner-v0.3.1.tar.gz` | `05919ac5969a56026dba4abeb40651266888ea4e01b8a86dbd4ef392d3ea79aa` | Copied old compose override into the target compose-runtime path. | Wrong model for runner v0.3.1 bootstrap: old runner does not have host `/data` mounted, so writing target `/data/smartx-storage-forecast` inside the runner wrote into the old app data mount. |
| SUPERSEDED | 2026-07-02 | `/home/user1/codex-build/packages-v052-layout-fix/02-runner-v0.3.1-fsdirfix8/smartx-upgrade-runner-v0.3.1.tar.gz` | `a7a5a2296d2215937b05dc0130b4e3c9b7b8e535bd7529565a99b8518bb4f742` | Keep local runner context paths stable, copy package project to host target via helper, and do not skip package `prometheus/`. | v0.5.2 platform started, but final health failed because v0.5.2 did not start new-project `upgrade-runner` and Prometheus data directory permissions were root-owned. |
| SUPERSEDED | 2026-07-02 | `/home/user1/codex-build/packages-v052-layout-fix/02-runner-v0.3.1-fsdirfix9/smartx-upgrade-runner-v0.3.1.tar.gz` | `128571d20ea56fbd5d8684832c398458453a660b5e8d752e5dff5d2c200b1c04` | Adds host Prometheus data permission preparation through helper container while keeping old runner local paths stable and copying package project to host target. | Superseded by `handofffix1`: fsdirfix9 lacks `runner.handoff_target_runtime` and `SMARTX_HOST_UPGRADES_PATH`, so cleanup can still be attempted by a runner mounted on legacy paths. |
| SUPERSEDED | 2026-07-02 21:32 CST | `/home/user1/codex-build/packages-v052-handofffix/02-runner-v0.3.1-handofffix1/smartx-upgrade-runner-v0.3.1.tar.gz` | `678f9acafd90e0c8dafdc0664d251ee29de5f8d0b04eb3796b540ea174a4d16a` | Adds `SMARTX_HOST_UPGRADES_PATH`, host upgrades path mapping before generic `/data`, `runner.handoff_target_runtime`, safe resume for handoff, and cleanup mount guard. | Superseded by `runner-v0.3.1-postcleanupfix2`: normal-chain validation with `v0.5.2-postcleanupfix2` failed because this runner package did not contain `.env` migration or `post_upgrade.schedule_cleanup` handler. |
| SUPERSEDED BY PLAN | 2026-07-06 CST | `/home/user1/codex-build/packages-v052-postcleanupfix2/02-runner-v0.3.1-postcleanupfix2/smartx-upgrade-runner-v0.3.1.tar.gz` | `f99cdb9312fd0f07ab38585ddcf2c29623db8fda34bc989695944458b76190c2` | Keeps handofffix1 behavior and packages the current runner code with `.env` migration in `filesystem.prepare`, `post_upgrade.schedule_cleanup` handler, and stronger package image self-checks. | Static gates passed and handler capability is present, but full-chain validation showed the bootstrap compose path topology still lacks target root exposure. It can execute actions, but writes to `/data/smartx-storage-forecast/*` do not land on the host unless the bootstrap compose mounts the target root. |
| PLANNED / LOCAL TESTS PASSED | 2026-07-06 CST | `/home/user1/codex-build/packages-v052-postcleanupfix3/02-runner-v0.3.1-postcleanupfix3/smartx-upgrade-runner-v0.3.1.tar.gz` | `TBD` | Same runner code and self-checks as postcleanupfix2, plus manifest includes `bootstrap_runner.target_root=/data/smartx-storage-forecast` so v0.5.1u2-fix15 can generate the correct bootstrap compose. | Local builder test passed. Needs remote build/static gate on 10.20.11.3 and full-chain validation. |

## v0.5.2 Platform Package Fix Series

| Status | Fix ID | Built At | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- | --- |
| DO NOT USE | `v0.5.2-phase34-prometheus-compose` | 2026-06-30 12:40 CST | `/home/user1/codex-build/packages-v052-phase34/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `b5487bbd3e96ecda748060ef31247e3528258905215b33265a3350e4fbf85111` | v0.5.2 platform manifest starts Prometheus as part of the platform compose rebuild, without adding `images/prometheus.tar`; precheck verifies `prom/prometheus:v2.55.1` from manifest no-archive declarations or packaged compose. | Functional chain passed on 10.20.11.3, but final directory layout is wrong: the actual package was built before the single-root `/data/smartx-storage-forecast/*` rule. Rebuild v0.5.2 with project, app data, Prometheus data, upgrades, backups, exports, and compose runtime all under `/data/smartx-storage-forecast`. |
| SUPERSEDED | `v0.5.2-layout-fix1` | 2026-07-02 CST | `/home/user1/codex-build/packages-v052-layout-fix/03-v0.5.2/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `c8b5e073203d29ac57fd0996c66ec3df7ac7d5e58a65857ad00dde35b97ef414` | First single-root `/data/smartx-storage-forecast/*` v0.5.2 candidate. | Superseded: after runner fixes, platform services started but final health missed runner and Prometheus permissions because platform services did not include `upgrade-runner` and Prometheus data was root-owned. |
| SUPERSEDED | `v0.5.2-fix2` | 2026-07-02 CST | `/home/user1/codex-build/packages-v052-layout-fix/03-v0.5.2-fix2/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `a224d0de60c688d5d7033b21d3ea00869b253ff3aef6c6b1ecc9a31498aebfbc` | v0.5.2 platform services now include `upgrade-runner` so the new project starts runner v0.3.1 without bundling a runner image. Used with runner `fsdirfix9`, which prepares Prometheus data permissions. | Validated on 10.20.11.3 via normal chain: `v0.5.1 -> v0.5.1u2-fix10 -> runner fsdirfix9 -> v0.5.2-fix2`. Final health passed, but the in-flight v0.5.2 task file remained under legacy `/data/upgrades`, so the new web-api could return 404 for that specific task status after cutover. Superseded by `v0.5.2-cleanupfix1`. |
| SUPERSEDED | `v0.5.2-cleanupfix1` | 2026-07-02 CST | `/home/user1/codex-build/packages-v052-legacy-cleanup/03-v0.5.2-cleanupfix1/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `a314e7d8493c4e926890813e43d6ce7721578aa98a07e706e94f3fc2e26d9e88` | Adds v0.5.2-only `legacy_cleanup` manifest, task-state migration/mirroring before cutover, final task-state sync, and post-health allowlisted cleanup of old project/network/directories. | Superseded by `cleanupfix2`: cleanupfix1 runs `legacy.cleanup` directly after task sync and does not hand off to a target-layout runner first. |
| DO NOT USE FOR FINAL CHAIN | `v0.5.2-cleanupfix2` | 2026-07-02 21:37 CST | `/home/user1/codex-build/packages-v052-handofffix/03-v0.5.2-cleanupfix2/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `6e996dd90637ce02dba0db34430d7e784ff6dedd17437ee74dcfe2c0eb70a48a` | Adds `runner.handoff.v1` requirement and execution action `task.sync_runtime_state -> runner.handoff_target_runtime -> legacy.cleanup`, while still excluding Prometheus and runner image archives. | Full normal-chain validation on 10.20.11.3 reached `v0.5.2 + runner v0.3.1` health, but task `upgrade-47b45bc1aafa0e86` failed at `legacy.cleanup`: old runner `smartx-storage-forecast-upgrade-runner-1` was still running and mounted `/opt/smartx-storage-forecast`; current task also remained under legacy `/data/upgrades`, so new web-api returned 404 for the task. Superseded by planned `v0.5.2-cleanupfix3`, which must add `runner.stop_legacy_runtime` and fix absolute target task-state migration. |
| SUPERSEDED BY PLAN | `v0.5.2-cleanupfix3` | 2026-07-03 CST | `/home/user1/codex-build/packages-v052-cleanupfix3/03-v0.5.2-cleanupfix3/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `TBD` | Planned same-task cleanup fix after cleanupfix2 full-chain failure. | Superseded before package build by `v0.5.2-postcleanupfix1`: same-task cleanup keeps platform success and old environment cleanup coupled too tightly. |
| DO NOT USE FOR FINAL CHAIN | `v0.5.2-postcleanupfix1` | 2026-07-06 CST | `/home/user1/codex-build/packages-v052-postcleanupfix1/03-v0.5.2-postcleanupfix1/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `3ee07fcd6b9fee785e37b9aaf08879afec335c3d11020d336f1acaeb504ec985` | Splits v0.5.2 platform upgrade and old-environment cleanup. Main v0.5.2 execution plan should end with `post_upgrade.schedule_cleanup`; new v0.5.2 web-api creates an independent `post_upgrade_cleanup` runner task. | Same-version validation on 10.20.11.3 uploaded/prechecked successfully, but start used the currently running web-api compiler and generated the old cleanupfix2 plan. The task `upgrade-ad3195dc076fa673` then failed at `compose.apply` because `/data/smartx-storage-forecast/project/.env` was missing. Superseded by planned `v0.5.2-postcleanupfix2` plus `v0.5.1u2-fix14-env-postcleanup-compiler`. |
| DO NOT USE FOR FINAL CHAIN WITH `runner-v0.3.1-handofffix1` | `v0.5.2-postcleanupfix2` | 2026-07-06 CST | `/home/user1/codex-build/packages-v052-postcleanupfix2/03-v0.5.2-postcleanupfix2/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `7cd5f1e3a2d4b677c377f1ef2f1369da56f5ca08ef5b71ba3dda93e95b9f8816` | Adds v0.5.2 manifest support for `.env` migration into `/data/smartx-storage-forecast/project/.env` while preserving existing target env, sanitizing image tag env keys, and excluding `.env` from the package. Keeps post-upgrade cleanup as an independent task. | Static gates passed, but normal-chain validation on 10.20.11.3 failed with the existing runner package. Task `upgrade-4caf98b7f3a368e6` reached healthy `v0.5.2 + runner v0.3.1`, but the task stayed failed in legacy `/data/upgrades` and new web-api returned 404 for status. Failed action: `post_upgrade.schedule_cleanup`, error `Runner 不支持动作：post_upgrade.schedule_cleanup`. The same run also proved `/data/smartx-storage-forecast/project/.env` was not created, because `.env` migration was implemented in runner code but the runner component package was not rebuilt with that code. Next package set must include a new runner v0.3.1 fix containing both `.env` migration and `post_upgrade.schedule_cleanup` support, or move post-cleanup scheduling out of runner-executed actions. |

### Next v0.5.2 Package Requirement

`v0.5.2-cleanupfix1` is the first package that contains both task-state
migration and post-success legacy cleanup. Keep this section as the validation
checklist until the full normal-chain upgrade has been rerun.

Required changes:

- Manifest includes v0.5.2-only `legacy_cleanup`; v0.5.1u2 and runner packages
  must not include it.
- Execution plan migrates the current task state from legacy `/data/upgrades`
  to `/data/smartx-storage-forecast/upgrades` before compose cutover and
  mirrors task saves until the final state is written.
- `legacy.cleanup` runs only after final health passes and after final task
  state exists in the new upgrades directory.
- Cleanup removes old project `smartx-storage-forecast`, old network
  `smartx-storage-forecast_smartx-net`, legacy top-level directories, and known
  target-app residual directories by allowlist.
- Cleanup refuses unsafe paths and must never delete `/data/smartx-storage-forecast`
  or its formal target subdirectories.

Validation required before marking the cleanup work fully complete:

```text
10.20.11.3 only
v0.5.1 + runner v0.3.0
  -> v0.5.1u2-fix10
  -> runner v0.3.1-fsdirfix9
  -> new v0.5.2 package

health.version = v0.5.2
health.runner_version = v0.3.1
health.checks.prometheus = true
final task is readable from /data/smartx-storage-forecast/upgrades
old smartx-storage-forecast containers are gone
old smartx-storage-forecast_smartx-net is gone
legacy cleanup allowlist paths are deleted or explicitly skipped with reason
```

## Current Candidate Validation Gates

Before calling a package fixed, verify all of these on the target host:

```text
health.version = v0.5.1u2 after v0.5.1u2 package
health.runner_version = v0.3.0 before runner bootstrap
docker-compose.runner-bootstrap.yml is generated for runner v0.3.1 bootstrap
runner bootstrap compose uses smartx-hci-capacity-insight / smartx-hci-capacity-insight-net / 10.249.251.0/24
runner bootstrap compose mounts /data/smartx-storage-forecast/app:/data
runner bootstrap compose must not contain /data:/data
health.runner_version = v0.3.1 after runner bootstrap
v0.5.2 package contains task-state migration and legacy cleanup gates
v0.5.2 cleanup runs only after final health and final task-state sync
```

## Maintenance Rule

Whenever a new package is generated, update this ledger in the same turn with:

- build time
- full host path
- SHA256
- exact reason for rebuild
- superseded package
- validation result or explicit validation gap

## 2026-07-06 Fix16 / Postcleanupfix3 Plan

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| PLANNED / LOCAL TESTS PASSED | `v0.5.1u2-fix16-skip-runner-compose-apply` | `/home/user1/codex-build/packages-v051u2-fix16/01-v0.5.1u2-fix16-skip-runner-compose-apply/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `TBD` | Keep fix15 behavior and update the v0.5.2 execution-plan compiler so main platform `compose.apply` excludes `upgrade-runner`. | Required because v0.5.2 execution plans are compiled by the currently running v0.5.1u2 web-api. |
| PLANNED / LOCAL TESTS PASSED | `v0.5.2-postcleanupfix3-skip-runner-compose-apply` | `/home/user1/codex-build/packages-v052-postcleanupfix3/03-v0.5.2-postcleanupfix3-skip-runner-compose-apply/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `TBD` | Same postcleanupfix2 semantics, rebuilt with compiler fix: main `compose.apply` excludes `upgrade-runner` while final compose still declares it. | Required after task `upgrade-bb3a007841e9940d` stuck at `compose.apply` because current target runner was recreated and exited 137. |

## 2026-07-06 Fix17 / Postcleanupfix4 Plan

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| PLANNED | `v0.5.1u2-fix17-runner-cutover` | `/home/user1/codex-build/packages-v051u2-fix17/01-v0.5.1u2-fix17-runner-cutover/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `TBD` | Keep fix16 and compile v0.5.2 post-cleanup manifests with a safe post-success runner cutover action. | Required because v0.5.2 plans are compiled by the active v0.5.1u2 web-api. |
| PLANNED | `runner-v0.3.1-postcleanupfix4-runner-cutover` | `/home/user1/codex-build/packages-v052-postcleanupfix4/02-runner-v0.3.1-postcleanupfix4-runner-cutover/smartx-upgrade-runner-v0.3.1.tar.gz` | `TBD` | Add the runner-side handler that launches a short-lived helper container to recreate runner after the parent task mirror reaches success. | Required because postcleanupfix3 left the running runner in bootstrap env and the new web-api could not see runner heartbeat. |
| PLANNED | `v0.5.2-postcleanupfix4-runner-cutover` | `/home/user1/codex-build/packages-v052-postcleanupfix4/03-v0.5.2-postcleanupfix4-runner-cutover/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `TBD` | Rebuild v0.5.2 with the same runner cutover compiler behavior for future same-version and later chains. | Must be validated by full normal chain on 10.20.11.3. |

## 2026-07-06 Fix18 / Postcleanupfix5 Plan

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| SUPERSEDED BY FIX19 PLAN | `v0.5.1u2-fix18-package-less-cleanup-task` | `/home/user1/codex-build/packages-v051u2-fix18/01-v0.5.1u2-fix18-package-less-cleanup-task/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `c333c45b260b3632801950ff0ee0570975110e441b222f20b0c693d33772887f` | Rebuilt v0.5.1u2 bridge package from current fix18 source. Compiler behavior remains fix17-compatible; v0.5.1u2 still has no `minimum_runner_version` and keeps legacy project/network. | Full chain reached `v0.5.2 + runner v0.3.1`, but post-cleanup deleted target upgrades contents because cleanup interpreted host legacy path `/data/upgrades` in the final runner container namespace. |
| SUPERSEDED BY FIX19 PLAN | `runner-v0.3.1-postcleanupfix5-package-less-cleanup-task` | `/home/user1/codex-build/packages-v052-postcleanupfix5/02-runner-v0.3.1-postcleanupfix5-package-less-cleanup-task/smartx-upgrade-runner-v0.3.1.tar.gz` | `fa62c23c498c406ea28734f2deb0d2e03437dcfe5ac53160d3848b63d6c73b53` | Allow package-less internal `post_upgrade_cleanup` tasks to run by giving the runner a safe placeholder package path instead of crashing on missing `package_path`. | Package-less task crash is fixed, but cleanup path execution still runs in the runner container namespace and can delete target task mirror contents. |
| SUPERSEDED BY FIX19 PLAN | `v0.5.2-postcleanupfix5-package-less-cleanup-task` | `/home/user1/codex-build/packages-v052-postcleanupfix5/03-v0.5.2-postcleanupfix5-package-less-cleanup-task/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `f76857bef15bcd111cab8051acc066bba43337e86455a63723c32e86ab1fbb10` | Rebuilt v0.5.2 with the same postcleanupfix4 manifest semantics and current packaged project files. | Full chain failed in post-cleanup with `OSError: [Errno 16] Device or resource busy: PosixPath('/data/upgrades')`; target task files were removed from `/data/smartx-storage-forecast/upgrades`. |

## 2026-07-06 Fix19 / Postcleanupfix6 Plan

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| CANDIDATE / STATIC GATE PASSED | `v0.5.1u2-fix19-host-cleanup-helper` | `/home/user1/codex-build/packages-v051u2-fix19/01-v0.5.1u2-fix19-host-cleanup-helper/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `fcb8d63cb561f0e11790d7ca4ff2086c7ee2d16ddcc5280bb60d3244b35094a4` | Rebuild bridge package from source that knows how to pass post-cleanup helper image through the v0.5.2 compiler. | 10.20.11.3 unit tests passed; static gate confirmed bridge semantics remain legacy and source versions include `v0.5.0/v0.5.1/v0.5.1u1/v0.5.1u2`. Full chain pending. |
| CANDIDATE / STATIC GATE PASSED | `runner-v0.3.1-postcleanupfix6-host-cleanup-helper` | `/home/user1/codex-build/packages-v052-postcleanupfix6/02-runner-v0.3.1-postcleanupfix6-host-cleanup-helper/smartx-upgrade-runner-v0.3.1.tar.gz` | `ad24904b79255968632119db1773f10f0cf41185b3c7b8f02f00763c3f99577c` | Runner cleanup now treats `legacy_paths` as host paths and deletes them via a short-lived helper container mounted at `/host`; it refuses to directly delete active runner mount points without `helper_image`. | 10.20.11.3 unit tests passed; runner image gate printed `RUNNER_IMAGE_HOST_CLEANUP_HELPER_OK`. Full chain pending. |
| CANDIDATE / STATIC GATE PASSED | `v0.5.2-postcleanupfix6-host-cleanup-helper` | `/home/user1/codex-build/packages-v052-postcleanupfix6/03-v0.5.2-postcleanupfix6-host-cleanup-helper/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `2bcc7bb6534aae05538777aa7822dc6d48a4ac27ed0a787add68a5180d1501a1` | v0.5.2 manifest now includes `legacy_cleanup.helper_image`, and post-cleanup child task passes that helper to file cleanup actions. | 10.20.11.3 unit tests passed; static gate confirmed `legacy_cleanup.helper_image`, target compose layout, no Prometheus tar, no runner image tar, and no packaged `.env`. Full chain pending. |

## 2026-07-06 Fix20 / Postcleanupfix7 Plan

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| VALIDATED / CHAIN OK | `v0.5.1u2-fix20-skip-active-target-mountpoints` | `/home/user1/codex-build/packages-v051u2-fix20/01-v0.5.1u2-fix20-skip-active-target-mountpoints/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `249c54884b4195ed25feeb0ef21f0dedc5039de7cdaabaf9ec5e172c1c0b790d` | Rebuild bridge package so v0.5.1u2 compiler carries the updated cleanup semantics forward. | 10.20.11.3 remote tests passed; static gate confirmed legacy project/network/source compatibility. Full chain task `upgrade-1cb2b21f905a0df2` succeeded. |
| VALIDATED / CHAIN OK | `runner-v0.3.1-postcleanupfix7-skip-active-target-mountpoints` | `/home/user1/codex-build/packages-v052-postcleanupfix7/02-runner-v0.3.1-postcleanupfix7-skip-active-target-mountpoints/smartx-upgrade-runner-v0.3.1.tar.gz` | `43f6a5fbc2150cfb6511f67e4104613c9bdb995fd5c78186bf4fcbd6a12bccf2` | Runner skips host_data_path mountpoint directories such as `app/upgrades` when they back active final runtime mounts. | 10.20.11.3 remote tests passed; runner image gate printed `RUNNER_IMAGE_ACTIVE_MOUNTPOINT_SKIP_OK`. Full chain task `upgrade-0f881a8f584ca943` succeeded and health showed runner `v0.3.1`. |
| VALIDATED / CHAIN OK | `v0.5.2-postcleanupfix7-skip-active-target-mountpoints` | `/home/user1/codex-build/packages-v052-postcleanupfix7/03-v0.5.2-postcleanupfix7-skip-active-target-mountpoints/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `5e2aaff6ac0ebe97993b2499169eecd951e9c9683bb7e579de201f6371b3a1b9` | v0.5.2 manifest no longer generates `target_app_residual_paths`; old packages are guarded by runner-side skip logic. | Full chain task `upgrade-edc9d233736cf967` succeeded; post-cleanup succeeded; final health `v0.5.2 + runner v0.3.1 + prometheus=true`; old `/opt` and legacy `/data/*` runtime paths were missing as expected. |

## 2026-07-07 Phase45 Envfixed Tags Candidate

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| STATIC GATE PASSED / CHAIN BLOCKED AT BASELINE RESET | `v0.5.1u2-envfixed-tags` | `/home/user1/codex-build/packages-phase45-env-fixed-tags/01-v0.5.1u2-envfixed/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `7047d2593dbe855472950c61b5a8f164121c0daca3b71a14f91b1922e221c615` | Package compose is rendered with fixed image tags; no `SMARTX_IMAGE_TAG`, `SMARTX_RUNNER_IMAGE_TAG`, `SMARTX_APP_VERSION`, or `SMARTX_RUNNER_VERSION`; bridge package keeps legacy project/network and runner `v0.3.0`. | Static gate passed on 10.20.11.3. Full chain did not start because baseline reset failed before v0.5.1u2 upload: legacy v0.5.1 compose references old `nazawsze/smartx-storage-forecast-*` repositories while rebuilt images exist as `nazawsze/smartx-hci-capacity-insight-*`. |
| STATIC GATE PASSED / CHAIN BLOCKED AT BASELINE RESET | `runner-v0.3.1-envfixed-tags` | `/home/user1/codex-build/packages-phase45-env-fixed-tags/02-runner-v0.3.1-envfixed/smartx-upgrade-runner-v0.3.1.tar.gz` | `423facbc4346eea63e03aa4d817bf15dbb62218358b69cbac5ab1c326c9cc4c9` | Rebuilt runner with current Phase45 code, including `.env` sanitize behavior and Prometheus chown hard-failure behavior; bootstrap manifest keeps `target_root=/data/smartx-storage-forecast`. | Static gate passed on 10.20.11.3. Not chain-validated because baseline reset failed before component upgrade. |
| STATIC GATE PASSED / CHAIN BLOCKED AT BASELINE RESET | `v0.5.2-envfixed-tags` | `/home/user1/codex-build/packages-phase45-env-fixed-tags/03-v0.5.2-envfixed/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `123a2603e751f718bf4ced4991a17bc809b206e73dacbd1fb8a79b8d4f79d0d5` | Package compose is rendered with fixed platform `v0.5.2` and runner `v0.3.1` tags; manifest retains `minimum_runner_version`, `environment_transitions`, `directory_transition`, `legacy_cleanup`, and `post_upgrade`. | Static gate passed on 10.20.11.3. Not chain-validated because baseline reset failed before platform upgrade. |
| HELPER ONLY / NOT A RELEASE CANDIDATE | `v0.5.1-baseline-helper` | `/home/user1/codex-build/packages-phase45-env-fixed-tags/00-v0.5.1-baseline/smartx-capacity-insight-upgrade-v0.5.1.tar.gz` | `6353e2102700326a999e41c0bb10bc439cc3cb5236179243540a37dfb10e56bb` | Temporary helper package used to rebuild clean `v0.5.1` baseline platform images and project files for 10.20.11.3 testing. | Build passed image identity gates, but using its legacy compose for reset exposed a repository-name mismatch: compose references `nazawsze/smartx-storage-forecast-*`, while available rebuilt images are `nazawsze/smartx-hci-capacity-insight-*`. |

## 2026-07-08 UPG-032 History Migration Fix

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| REUSED / CHAIN OK WITH UPG-032 RUNNER | `v0.5.1u2-envfixed-tags` | `/home/user1/codex-build/packages-phase45-env-fixed-tags/01-v0.5.1u2-envfixed/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `7047d2593dbe855472950c61b5a8f164121c0daca3b71a14f91b1922e221c615` | Same phase45 bridge package. Keeps legacy project/network, fixed image tags, and runner baseline `v0.3.0`. | 10.20.11.3 full chain task `upgrade-06220c473a9718b6` succeeded. Health after step: `v0.5.1u2 + runner v0.3.0 + prometheus=true`. |
| VALIDATED / CHAIN OK | `runner-v0.3.1-upg032-historyfix` | `/home/user1/codex-build/packages-upg032-historyfix/02-runner-v0.3.1-historyfix/smartx-upgrade-runner-v0.3.1.tar.gz` | `d10e15cf7b516d172ebe2f1bc37621f9cf32d8ab3abd548f808ae5c5de151d2c` | Runner `task.migrate_runtime_state` now migrates existing old `/data/upgrades/*/task.json` task directories into the v0.5.2 target upgrades root before post-cleanup deletes the legacy root. | 10.20.11.3 full chain task `upgrade-8ee2b5c0b110944e` succeeded. Final v0.5.2 `component-upgrade/history` retained this runner task. |
| REUSED / CHAIN OK WITH UPG-032 RUNNER | `v0.5.2-envfixed-tags` | `/home/user1/codex-build/packages-phase45-env-fixed-tags/03-v0.5.2-envfixed/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `123a2603e751f718bf4ced4991a17bc809b206e73dacbd1fb8a79b8d4f79d0d5` | Same phase45 platform package with fixed image tags, target project/network, directory transition, legacy cleanup, and runner handoff. | 10.20.11.3 full chain task `upgrade-a4a200b28bc83d17` succeeded. Final health `v0.5.2 + runner v0.3.1 + prometheus=true`; post-cleanup task `post-cleanup-upgrade-a4a200b28bc83d17` succeeded; old legacy paths and old network were removed; target upgrades retained v0.5.1u2, runner, v0.5.2, and post-cleanup task files. |

## 2026-07-08 UPG-033 Health Runner Fallback Fix

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| REUSED / CHAIN OK WITH UPG-033 V0.5.2 | `v0.5.1u2-envfixed-tags` | `/home/user1/codex-build/packages-phase45-env-fixed-tags/01-v0.5.1u2-envfixed/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `7047d2593dbe855472950c61b5a8f164121c0daca3b71a14f91b1922e221c615` | Same phase45 bridge package. Keeps legacy project/network, fixed image tags, and runner baseline `v0.3.0`. | 10.20.11.3 full chain task `upgrade-f7bdd6a188ee5d78` succeeded. Health after step: `v0.5.1u2 + runner v0.3.0 + prometheus=true`. |
| REUSED / CHAIN OK WITH UPG-033 V0.5.2 | `runner-v0.3.1-upg032-historyfix` | `/home/user1/codex-build/packages-upg032-historyfix/02-runner-v0.3.1-historyfix/smartx-upgrade-runner-v0.3.1.tar.gz` | `d10e15cf7b516d172ebe2f1bc37621f9cf32d8ab3abd548f808ae5c5de151d2c` | Runner keeps UPG-032 history migration so old `/data/upgrades/*/task.json` task dirs survive v0.5.2 post-cleanup. | 10.20.11.3 full chain task `upgrade-900f6735e0d76fac` succeeded. Final v0.5.2 `component-upgrade/history` retained this runner task. |
| VALIDATED / CHAIN OK | `v0.5.2-upg033-healthfix` | `/home/user1/codex-build/packages-upg033-healthfix/03-v0.5.2-healthfix/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `b1b0aff943bd208cc4aed57c0488abccfd0405cbdbadf443253cfad91e1def20` | Health API now falls back from stale/missing runner heartbeat to the running `upgrade-runner` container `/app/RUNNER_VERSION`, then image tag. It still does not fall back to web-api baseline `RUNNER_VERSION`. | 10.20.11.3 full chain task `upgrade-0b23bb79cc9dc869` succeeded; post-cleanup task `post-cleanup-upgrade-0b23bb79cc9dc869` succeeded; immediate health samples 1..8 all returned `version=v0.5.2`, `runner_version=v0.3.1`, `checks.prometheus=true`; old legacy paths and old network were removed; target upgrades retained v0.5.1u2, runner, v0.5.2, and post-cleanup task files. |

## 2026-07-08 UPG-034 Report Export All-VM v0.5.2 Rebuild

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| REUSED / CHAIN OK WITH UPG-034 V0.5.2 | `v0.5.1u2-envfixed-tags` | `/home/user1/codex-build/packages-phase45-env-fixed-tags/01-v0.5.1u2-envfixed/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `7047d2593dbe855472950c61b5a8f164121c0daca3b71a14f91b1922e221c615` | Same validated bridge package. Keeps legacy project/network, fixed image tags, and runner baseline `v0.3.0`. | 10.20.11.3 full chain task `upgrade-761854a403bd06bb` succeeded. Health after step: `v0.5.1u2 + runner v0.3.0 + prometheus=true`. |
| REUSED / CHAIN OK WITH UPG-034 V0.5.2 | `runner-v0.3.1-upg032-historyfix` | `/home/user1/codex-build/packages-upg032-historyfix/02-runner-v0.3.1-historyfix/smartx-upgrade-runner-v0.3.1.tar.gz` | `d10e15cf7b516d172ebe2f1bc37621f9cf32d8ab3abd548f808ae5c5de151d2c` | Same validated runner package. Keeps UPG-032 migration of old task history into the v0.5.2 target upgrades root. | 10.20.11.3 full chain task `upgrade-4c404ec5d16ca511` succeeded. Component upgrade history retained this runner task. |
| VALIDATED / CHAIN OK | `v0.5.2-report-all-vms` | `/home/user1/codex-build/packages-upg034-report-all-vms/03-v0.5.2-report-all-vms/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `23d275a3e44bc9b45c083f33cac505107f9a03ac53b42120a4cf9a67f2236cf3` | Rebuilt v0.5.2 with UPG-033 health fallback plus report export all-VM optimization: export code no longer truncates VM growth/new-VM rows to TOP100 and headings show `全部虚拟机`. | 10.20.11.3 full chain task `upgrade-d2607588845d142a` succeeded; post-cleanup task `post-cleanup-upgrade-d2607588845d142a` succeeded; final health `v0.5.2 + runner v0.3.1 + prometheus=true`; old network and legacy paths were removed; target task files retained all three upgrade tasks plus post-cleanup; release smoke passed with `critical_count=0`, `warning_count=0`. |

## 2026-07-08 UPG-036 Runner Start Conflict Fix

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| VALIDATED / CHAIN OK | `v0.5.1u2-upg036-runner-start-conflict` | `/home/user1/codex-build/packages-upg036-runner-start-conflict/01-v0.5.1u2-runner-start-conflict/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `d5f277167445e7636ddfba16b4f780b40d59952467bb1c8e72d2469b43ee0a49` | Rebuilt bridge package so the active v0.5.1u2 web-api returns success when runner-only bootstrap is completed first by the newly started runner and the old web-api final task save hits a revision conflict. | Local regression passed: 144 tests OK, 1 skipped. Remote dependency-complete regression passed: 175 tests OK. Static gate passed. Full chain task `upgrade-1e3345094fc9c4dc` succeeded; health after step was `v0.5.1u2 + runner v0.3.0 + prometheus=true`. |
| VALIDATED / CHAIN OK | `runner-v0.3.1-upg032-historyfix` | `/home/user1/codex-build/packages-upg032-historyfix/02-runner-v0.3.1-historyfix/smartx-upgrade-runner-v0.3.1.tar.gz` | `d10e15cf7b516d172ebe2f1bc37621f9cf32d8ab3abd548f808ae5c5de151d2c` | Reuse the latest validated runner component package; UPG-036 changes are in the bridge web-api start path, not in runner code. | Full chain task `upgrade-a31572ffb4d37e54` succeeded. Crucial UPG-036 check passed: component start returned HTTP 200 with `status=succeeded`, not false HTTP 409. Final component history retained this runner task. |
| VALIDATED / CHAIN OK | `v0.5.2-upg035-upg036` | `/home/user1/codex-build/packages-upg036-runner-start-conflict/03-v0.5.2-upg035-upg036/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `5ab9d41d1192efb794c9a43db4d340ef86bbeb0e5a4755118e517f715cdca2cc` | Rebuilt v0.5.2 with UPG-035 verification latest-package filtering and UPG-036 codebase state. | Full chain task `upgrade-f3e7160e4397acf0` succeeded; post-cleanup succeeded; final health `v0.5.2 + runner v0.3.1 + prometheus=true`; old paths and old network were removed; verification latest package points to this real platform package; release smoke passed with `critical_count=0`, `warning_count=0`. |

## 2026-07-09 UPG-039 Cleanup Guard Pathmap Fix

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| REUSED / CHAIN OK WITH UPG-039 | `v0.5.1u2-upg036-runner-start-conflict` | `/home/user1/codex-build/packages-upg036-runner-start-conflict/01-v0.5.1u2-runner-start-conflict/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `d5f277167445e7636ddfba16b4f780b40d59952467bb1c8e72d2469b43ee0a49` | Same validated bridge package. It keeps legacy project/network, runs on runner v0.3.0, and compiles v0.5.2 handoff/post-cleanup actions. | Full chain task `upgrade-528d1f42aa5b62dd` succeeded. Health after step was `v0.5.1u2 + runner v0.3.0 + prometheus=true`; business DB counts remained unchanged. |
| VALIDATED / CHAIN OK | `runner-v0.3.1-upg039-guard-pathmap` | `/home/user1/codex-build/packages-upg039-guard-pathmap/02-runner-v0.3.1-upg039-guard-pathmap/smartx-upgrade-runner-v0.3.1.tar.gz` | `fff608aed4c59069ed870858a3c64ccdca62f52d7d3b6faee3c47e2675d22e9d` | Runner data migration guard now normalizes host target DB paths into the active runner container namespace after handoff. Legacy paths that resolve to the target DB are skipped with `same_as_target_after_handoff`; target-with-business-data plus unavailable legacy sources is allowed with `legacy_sources_unavailable_after_handoff`, while readable legacy DBs with higher counts still fail hard. | Local regression passed: 151 tests OK, 1 skipped. Remote regression on 10.20.11.3 passed: 151 tests OK, 1 skipped. Full chain component task `upgrade-4b1c542232cce245` succeeded and final component history retained this runner task. |
| VALIDATED / CHAIN OK | `v0.5.2-upg039-guard-pathmap` | `/home/user1/codex-build/packages-upg039-guard-pathmap/03-v0.5.2-upg039-guard-pathmap/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `04e557c04ea1d63bcc512122ed10a59eca105c186edcf15ef8f8ed4acc081419` | Rebuilt v0.5.2 package with UPG-039 codebase and existing directory transition/post-cleanup manifest. Static gate confirmed `minimum_runner_version=v0.3.1`, directory transition, legacy cleanup, post-upgrade cleanup, data migration guard, no packaged `.env`, and no bundled runner/Prometheus image. | Full chain task `upgrade-37fbd66390f39880` succeeded; post-cleanup task `post-cleanup-upgrade-37fbd66390f39880` succeeded; final health `v0.5.2 + runner v0.3.1 + prometheus=true`; final DB counts were `users=1,towers=1,clusters=1,collection_runs=37,vm_latest=523,vm_volumes=89530`; old `/opt`, legacy `/data/*` runtime paths, `/data/smartx-capacity-insight-data`, and `/prometheus-data` were removed. |

## 2026-07-10 UPG-040 Empty Source Database Guard Fix

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| REUSED / CHAIN OK | `v0.5.1u2-upg036-runner-start-conflict` | `/home/user1/codex-build/packages-upg036-runner-start-conflict/01-v0.5.1u2-runner-start-conflict/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `d5f277167445e7636ddfba16b4f780b40d59952467bb1c8e72d2469b43ee0a49` | Existing validated bridge package. | Both empty-source chains reached `v0.5.1u2 + runner v0.3.0`. |
| VALIDATED / CHAIN OK | `runner-v0.3.1-upg040-empty-source` | `/home/user1/codex-build/packages-upg040-empty-source/02-runner-v0.3.1-upg040-empty-source/smartx-upgrade-runner-v0.3.1.tar.gz` | `ed416b97b7afab6c06359d3b74aa6e03256c8f41e5b7313b4dc3a85634d475d1` | `data_migration_guard` reads the parent `filesystem.prepare` checkpoint. It only allows an empty target after handoff when the parent source DB also proved empty. | 152 local and 152 remote tests passed. Full empty-source chain runner tasks succeeded on 10.20.11.3 (`upgrade-52f6c7c53b89ad53`) and 10.20.11.12 (`upgrade-3ec9762ff81c5101`). |
| VALIDATED / CHAIN OK | `v0.5.2-upg040-empty-source` | `/home/user1/codex-build/packages-upg040-empty-source/03-v0.5.2-upg040-empty-source/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `0b2166d36a7fd0ccc54416ba4ac1d0f749eeb9cbbce1b979b2735957de207b4d` | Rebuilt v0.5.2 with UPG-040 codebase. | Empty-source main tasks and post-cleanup succeeded on 10.20.11.3 (`upgrade-a3734551cbbaff02`) and 10.20.11.12 (`upgrade-5a22d9f11248f7f3`); final health v0.5.2/runner v0.3.1/Prometheus true and legacy paths removed. |

## 2026-07-10 UPG-041 Post-Upgrade Auto Collection

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| BUILT / CHAIN BLOCKED BY FIXTURE CREDENTIAL | `v0.5.1u2-upg041-auto-collection` | `/home/user1/codex-build/packages-upg041-auto-collection/01-v0.5.1u2-upg041-auto-collection/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `111095012bc2047a84a4c5cd841024e429a29a8a70cb3792c309dd6b4a4fae8f` | Compile the v0.5.2 post-upgrade collection marker action while retaining legacy bridge semantics. | 96 targeted tests passed; task `upgrade-16243cd1de457060` succeeded. |
| BUILT / CHAIN BLOCKED BY FIXTURE CREDENTIAL | `runner-v0.3.1-upg041-auto-collection` | `/home/user1/codex-build/packages-upg041-auto-collection/02-runner-v0.3.1-upg041-auto-collection/smartx-upgrade-runner-v0.3.1.tar.gz` | `6bb891e5088cbcc4c188e055daf56bd0eb6b695f299e9caec87eb3dbbacea2ff` | Write the idempotent target-runtime collection marker. | Task `upgrade-d4f926f88ec295ca` succeeded. |
| BUILT / AUTO COLLECTION EXECUTED BUT FIXTURE PAIR MISSING | `v0.5.2-upg041-auto-collection` | `/home/user1/codex-build/packages-upg041-auto-collection/03-v0.5.2-upg041-auto-collection/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `54e67555d06688491ad2c2d2f25a9a47a7e2639aa76f420aee6f7113acd86b94` | Consume the marker in collector-worker and expose the collection in task center. | Main task `upgrade-d50ecdcf5a316b1f` succeeded. Auto task was created with progress 100 and warning severity, then failed because the test restore omitted the `.env` paired with the restored DB. Do not require credential re-entry; superseded by UPG-042 guard packages. |

## 2026-07-10 UPG-042 Tower Credential / Env Pair Migration Guard

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| REUSED / PREVIOUS TWO STAGES SUCCEEDED | `v0.5.1u2-upg041-auto-collection` | `/home/user1/codex-build/packages-upg041-auto-collection/01-v0.5.1u2-upg041-auto-collection/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz` | `111095012bc2047a84a4c5cd841024e429a29a8a70cb3792c309dd6b4a4fae8f` | No UPG-042 code is executed by the bridge image; it already compiles the UPG-041 post-upgrade collection action and passes directory-transition fields through to runner. | Previous UPG-041 bridge task succeeded. Reuse pending final UPG-042 chain. |
| BUILT / REVIEW BLOCKED / DO NOT DELIVER | `runner-v0.3.1-upg042-credential-migration` | `/home/user1/codex-build/packages-upg042-credential-migration/02-runner-v0.3.1-upg042-credential-migration/smartx-upgrade-runner-v0.3.1.tar.gz` | `6db414b85c4a789918fd2a10c4238e383ffc3ae24e7320d130be0c875c9a7c37` | `filesystem.prepare` now migrates/selects DB before `.env`, validates candidate env files with the target web-api runtime, and hard-fails encrypted credentials without a matching key. | Tests/static gates passed, but review found `.env` mode 0644, fail-open schema handling, and unauthenticated XOR false-positive risk. Supersede after fixes. |
| BUILT / REVIEW BLOCKED / DO NOT DELIVER | `v0.5.2-upg042-credential-migration` | `/home/user1/codex-build/packages-upg042-credential-migration/03-v0.5.2-upg042-credential-migration/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `ed70d52e726f5275aed76ebd645298a8c5c2f6c2dc19061c1221203d93f521a2` | Manifest enables `env_file_migration.require_credential_decryption=true` while retaining UPG-041 auto collection and all prior directory/data/cleanup guards. | Identity/static gates passed, but package embeds the review-blocked runner action code in platform images. Supersede after fixes; do not deliver. |
| CHAIN FAILED / DO NOT DELIVER | `runner-v0.3.1-upg042-fix2` | `/home/user1/codex-build/packages-upg042-credential-migration-fix2/02-runner-v0.3.1-upg042-fix2/smartx-upgrade-runner-v0.3.1.tar.gz` | `509472c7f99efe63628549532e989e8506fb1a679730b84d51caa2f772a71908` | Fixes env 0600, XOR source-pair policy, and credential schema fail-closed behavior. | Unit/static/Docker gates passed and component task succeeded, but v0.5.2 chain exposed UPG-043 target-root path remapping. Supersede after UPG-043. |
| CHAIN FAILED / DO NOT DELIVER | `v0.5.2-upg042-fix2` | `/home/user1/codex-build/packages-upg042-credential-migration-fix2/03-v0.5.2-upg042-fix2/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `d341eec29cb7950bdaecc13c2b115b6efc6c306d213df8fe779440a7aa7874fd` | Carries UPG-041 auto collection plus UPG-042 credential guard review fixes. | Task `upgrade-5abf32abd0faa85b` failed safely in filesystem.prepare because helper DB host path was remapped incorrectly. No compose/cleanup occurred. Supersede after UPG-043. |

## 2026-07-14 UPG-043 Target Root Credential Helper Path Fix

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| VALIDATED / REUSED WITH UPG-044 FIX4 | `runner-v0.3.1-upg043-fix3` | `/home/user1/codex-build/packages-upg043-target-root-fix3/02-runner-v0.3.1-upg043-fix3/smartx-upgrade-runner-v0.3.1.tar.gz` | `e424fdca91c17a34328f22f7c79d4dfc2de13edb259a8eedde16b584445e999f` | Credential helper DB and `.env` paths under manifest `target_root` now retain the same host absolute path instead of being remapped through the legacy `/data` bind. | Tests/static gates passed; component task `upgrade-b91262afa445f0e8` succeeded and running image ID matched the loaded fix3 tag. Runner code did not change in UPG-044, so this is the runner paired with fix4. |
| SUPERSEDED BY UPG-044 FIX4 | `v0.5.2-upg043-fix3` | `/home/user1/codex-build/packages-upg043-target-root-fix3/03-v0.5.2-upg043-fix3/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `3722d788a3bcb89cd2e5b94a099ce843f6ad470edfac34c5bdf67232c33663a4` | Rebuilds v0.5.2 with UPG-041 auto collection, UPG-042 credential pairing guards, and UPG-043 target-root path protection. | Main task `upgrade-7d86beb3c459bc0a`, auto collection, and post-cleanup succeeded; env/data/runtime checks passed. Superseded because its history/verification read path can select an older package after mutating task mtimes. |

## 2026-07-15 UPG-044 Read-Only History / Stable Verification Fix

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| VALIDATED / REUSED | `runner-v0.3.1-upg043-fix3` | `/home/user1/codex-build/packages-upg043-target-root-fix3/02-runner-v0.3.1-upg043-fix3/smartx-upgrade-runner-v0.3.1.tar.gz` | `e424fdca91c17a34328f22f7c79d4dfc2de13edb259a8eedde16b584445e999f` | No UPG-044 runner change. | Reuses the runner that passed the UPG-043 full chain and all credential/data/cleanup gates. |
| VALIDATED QUERY FIX / DELIVERY CANDIDATE | `v0.5.2-upg044-fix4` | `/home/user1/codex-build/packages-upg044-verification-history-fix4/03-v0.5.2-upg044-fix4/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `29fa1ca308ab41db999a58c6d93908f601d1b355822cab6c6c66ac5a2c8390b7` | Makes history read-only, sorts history by business creation time, and selects the latest successful real platform package by completion time instead of mutable file mtime. | Local and 10.20.11.3 each passed 165 tests. Identity/manifest/checksum/sensitive/bundled-image gates passed. Isolated fix4 service and HTTP validation kept `upgrade-7d86... / 3722d788...` stable, preserved all 10 historical task SHA/mtimes, created no cleanup, and passed release smoke with health fully true. Full chain not rerun because runner/compiler/migration/compose behavior is unchanged. |
## 2026-07-17 UPG-047 / UPG-048 v0.5.2 Environment Permission Compatibility

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| DO NOT USE | `v0.5.2-upg047-fix7` | `/home/user1/codex-build/packages-upg047-env-permission-fix7/03-v0.5.2-upg047-fix7/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `1cde8e34617fcddc00e1a334516694ab0e34fc2997f164a91c718f5f17317497` | Tried to repair `.env` mode through the formal compose runner command. | Full chain proved the command unreachable after released runner handoff; final mode stayed `0644`. |
| VALIDATED / DELIVERY CANDIDATE | `v0.5.2-upg048-fix8` | `/home/user1/codex-build/packages-upg048-webapi-env-permission-fix8/03-v0.5.2-upg048-fix8/smartx-capacity-insight-upgrade-v0.5.2.tar.gz` | `692aca8b58ad8199c43c02a3771fa4fd7a62f1d7bbf4f198af4bd2e4b2c67733` | Repairs target `.env` mode from web-api main apply using a narrow RW file bind and startup chmod; released u2/runner remain unchanged. | `10.20.11.3` full immutable chain passed: all three main tasks, post-cleanup and auto collection succeeded; env SHA preserved at `0600 root:root`; task idempotence/history/verification, data, five containers, layout/cleanup and release smoke `0/0` passed. |

Current execution rule: Python, dependencies, tests, builds and full-chain validation run only on `10.20.11.3`; `10.20.11.12` is out of scope.
