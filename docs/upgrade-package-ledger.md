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

## 2026-09-13 v0.5.3 Platform Package

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| VALIDATED / DELIVERY CANDIDATE | `v0.5.3` | `/data/upgrade-packages/smartx-capacity-insight-upgrade-v0.5.3.tar.gz` | `e1702435dd95121ee9419f4de8a3514ed71a5b943caa6c645084290cc1d34ab8` | v0.5.3 正式平台包：巨型文件拆分（api.py/ServicePage/export/upgrade.service）、前后端契约对齐、Excel 图表精修、AI 措辞层、测试环境治理。 | `10.20.11.3` v0.5.2 → v0.5.3 升级链路通过：预检查通过、升级成功、health v0.5.3/v0.3.1、5 容器镜像 tag v0.5.3、project/network 保持、SQLite 行数不减少、Prometheus 历史保留、.env 0600、旧目录全清理、升级后全量 310 tests OK。已知限制：.3 的 .env 被覆盖为默认模板导致 Tower 凭据 key 丢失，UPG-042 保护拦截首次升级，备份 DB 后清空测试 Tower 凭据后通过；升级后自动采集因凭据缺失失败（需重新配置 Tower）。 |

## 2026-09-19 v0.5.3 Platform Package（重打包，含 UPG-049 修复）

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| SUPERSEDES 2026-09-13 包 / VALIDATED | `v0.5.3` | `/data/upgrade-packages/v053-rebuild-20260919/smartx-capacity-insight-upgrade-v0.5.3.tar.gz`（10.20.11.3） | `ef10a7c8515b4b0214d8b76e99897dd145e598c8520bbce0c451a36f0335a5f8` | 以 dev2 最新代码（a64a897）重打包：内容同 2026-09-13 包并新增 UPG-049 runner 修复（filesystem.prepare 跳过与在线库同文件的 legacy 候选）；web-api/collector-worker 镜像重建，frontend 镜像与 09-13 构建一致（源码无变化，缓存命中同 ID）。runner v0.3.1 镜像同 tag 重建（.3 ID `7d152590d6fd`，含 UPG-049 修复），已同步 .3 与 .12。 | `10.20.11.12` v0.5.2（目标布局基线）→ v0.5.3 正规升级流程通过（task `upgrade-e1fe8a62ea767ab7`）：上传→预检查→升级→post-cleanup 全部 succeeded；health `v0.5.3/v0.3.1` checks 全 true；5 容器镜像 tag 正确；project/network 保持；SQLite 行数不减少（users=1/towers=1/clusters=1/vm_latest=590/vm_volumes=89636）；Prometheus 历史 block 保留；.env 0600；7 个 legacy 路径全部清理；UI 8080=200。测试证据：.3 全量 310 tests OK（标准方式）、build_tests 26 OK、前端 tsc+vitest 85 passed、engine 测试 66 OK + UPG-049 回归测试。已知限制：升级后自动采集 failed（Tower `10.20.0.6` No route to host，测试网已知限制）；UPG-049 前置失败任务 `upgrade-53549c5fbb93ae7c`、`upgrade-fd1b47c6238ddc17` 留档。 |

## 2026-09-20 v0.5.3 Platform Package（第二次重打包 e940e07c + 全新构建 6accea95）

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| SUPERSEDED by 6accea95 / 门禁通过未走升级验收 | `v0.5.3` | `/data/upgrade-packages/v053-final-20260920` 前序（构建目录 `.3`；本地中转 `/tmp/v053-relay/`） | `e940e07ca2997c95cdbe3bc53475bef7cc7c44104bdb1a0311ed06fb56039825` | 2026-09-19 第二次重打包：纳入报表窗口去 720 档（49-18）、VM 页千台规模加固（49-19）、采集停摆探针（49-20）、预测区间（49-21）。 | 包静态门禁全过；新镜像已部署 .3 运行；**其 v0.5.2→v0.5.3 升级验收暂缓后未再执行，被 2026-09-20 全新构建 6accea95 取代**（历史纠错：本包曾无台账条目，2026-09-20 补记）。 |
| USE / VALIDATED | `v0.5.3` | `/data/upgrade-packages/v053-final-20260920/smartx-capacity-insight-upgrade-v0.5.3.tar.gz`（10.20.11.3） | `6accea95ed817ce95ed7f41fdd90077ed11520eb3c74281a77ddee48a0042c77` | 2026-09-20 全新完整构建（dev2 提交 ff1bd52，非增量重打）：收编 49-3 源码 compose 全字面量化（含 check_versions 门禁重构与 bridge 打包修复）、49-23 载体目录锁脚本（能力保留不默认启用）、此后全部治理改动；web-api/collector-worker/frontend 三镜像全新重建。manifest source_compatibility 覆盖 v0.5.0~v0.5.3（直升能力保持），environment_transitions/directory_transition/legacy_cleanup 齐备；包内 compose 零模板变量（49-3 不变量在真实包上验证）；verify_upgrade_package_identity 全绿。 | `10.20.11.12` v0.5.2（tag 换回重建的基线，数据/env/Prometheus 全部保全：vm_volumes=89636/vm_latest=590/collection_runs=63/tasks=21、.env sha 31a0d456… 0600、Prometheus 210 series、integrity ok）→ v0.5.3 正规升级流程通过（2026-09-20，task `upgrade-b45996653f6955b6`）：上传→预检查→升级 02:13:47-02:19:13 **succeeded**→post-cleanup **succeeded**；health `v0.5.3/v0.3.1` checks 全 true；5 容器镜像 tag 正确（三件套 v0.5.3/runner v0.3.1/prometheus v2.55.1）；project/network 保持 `smartx-hci-capacity-insight(-net)`；SQLite 行数不减少且 integrity ok（collection_runs 63→64、tasks 21→25 为升级任务/采集/告警新增，属预期）；Prometheus 210 series 历史保全（历史时间点查询+head 双验证）；.env 逐字节未动 0600；6 个 legacy 路径全部 missing（app/ 下 dockerd 载体目录按 UPG-050 定案属正常存在）；UI 8080=200；升级后自动采集机制触发（run 66 failed：Tower 10.20.0.6 No route to host，测试网已知限制）；新特性生效确认：采集停摆探针告警 `collection-freshness-stale` 在位、预测带字段在 /api/reports/latest 返回、数据质量告警在位。 |

## 2026-09-25 v0.5.3 Platform Package（重打包 4a3c7bbd，收编 09-21 批次）

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| SUPERSEDED by 54aa8807 / 门禁通过未走升级验收 | `v0.5.3` | `/data/upgrade-packages/v053-rebuild-20260922/smartx-capacity-insight-upgrade-v0.5.3.tar.gz`（10.20.11.3） | `4a3c7bbd40baa1fe1f88690f504328853b92edd77735f0059af5870cac898db6` | 2026-09-25 重打包（dev2 cdfe600，`ff1bd52..cdfe600` 共 40 提交、非 docs 文件 25 个）：收编迁移页三区重构+恢复密钥密码门控、报表趋势图四档优化/区间缓存/当日节点、Prometheus 查询去重、容量告警与首页新鲜度加固、采集间隔设置、清理 UI 调整等；三镜像全新重建。manifest source_compatibility v0.5.0~v0.5.3 + environment_transitions/directory_transition/legacy_cleanup 齐备；包内三 compose 零模板变量；identity 全绿。 | .3 全门禁通过（2026-09-25）：`--check-version` OK、build_tests 26 OK、全量 337 tests OK (skipped=1)、verify_api_docs 77=76、tsc 0、vitest 94 passed、包 SHA 落盘校验 OK、敏感成员扫描无、verify_release_docs_safe PASS。**`.12` 正规升级验收未执行（需用户授权），2026-09-27 被 54aa8807 取代。** |

## 2026-09-27 v0.5.3 Platform Package（重打包 54aa8807，收编 49-36~49-48 批次）

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| SUPERSEDED BY v0.5.3-r4 / 本包 `.12` 升级验收已于 2026-09-27 完成（见 Validation 列），因方案 A 与 runner 基线口径修正被 r4 取代 | `v0.5.3` | `/data/upgrade-packages/v053-rebuild-20260927/smartx-capacity-insight-upgrade-v0.5.3.tar.gz`（10.20.11.3） | `54aa8807dba18b385f34538d28e23705b830004305b9ff936c6a2ad1fe089487` | 2026-09-27 全新构建（dev2 `0a41775`，`cdfe600..0a41775`）：收编 49-36 已分配容量采集与展示、49-37 手动采集快照合并+看板过期标注、49-39 报表增长窗口口径、49-40~49-45 回收站排除/新建与增长 VM 口径统一/趋势图断档断开、49-46/49-46b 报表与趋势图已分配容量、49-47 回收站 VM 生命周期同步、49-48 趋势图配色互换；三镜像全新重建。manifest source_compatibility v0.5.0~v0.5.3 + environment_transitions/directory_transition/legacy_cleanup 齐备；identity 全绿。 | .3 全门禁通过（2026-09-27）：`--check-version` OK（v0.5.3）、宿主机 build_tests **26 OK**、web-api 容器全量 **362 tests OK (skipped=1)**（235s）、前端 `tsc -b --force` exit 0 + vitest **107 passed（11 files）**、`verify_api_docs` 77 条=76 路由、`verify_release_docs_safe` PASS、`verify_upgrade_package_identity` exit 0、`.sha256` `sha256sum -c` OK、包内敏感成员扫描 **0**、部署后 health `v0.5.3/v0.3.1` 三 checks 全 true + web 200 + 五容器在位。**`10.20.11.12` 升级链路回归 + 正规升级验收已于 2026-09-27 完成**：`.12` 先按 Phase 46 步骤恢复 `v0.5.1 + runner v0.3.0` 真实基线（业务夹具 `b84520c9…`，users1/towers1/vm_latest556/vm_volumes89588）→ `verify_full_upgrade_chain.py` 三步全绿（u2 `d5f27716…` task `upgrade-f4441e61be0ade4a`、runner 新包 `dd096bf2…` task `upgrade-a56ebcfe87b18b0b`、v0.5.2 fix8 `692aca8b…` task `upgrade-13dca81049bd979d`，节点1/2/3 验收通过、post-cleanup succeeded）→ 本包升级 task `upgrade-72bfb3f52317ef7f` **succeeded + post-cleanup succeeded**，8 项验收全过（health 连测两次全 true、5 容器 tag、project/network/subnet `10.249.251.0/24`、SQLite 行数与基线完全一致且 integrity ok、Prometheus 挂载目标目录 200、`.env` 0600 sha 未变、7 个 legacy 路径 missing、UI 200、前端产物含 49-48 配色与「已分配容量」）。自动采集仅因 Tower `10.20.0.6` 不可达失败（已知环境限制）。首轮（用 2026-07 runner 包 `d10e15cf…`）在切换后因 `Runner 不支持动作：post_upgrade.schedule_collection` 失败，根因与待决事项见 findings.md 2026-09-27 两条。** |

## 2026-09-27 runner v0.3.1 Component Package（按当前 dev2 镜像打包）

| Status | Fix ID | Host Path | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| USE（链路第 2 步与后续 v0.5.3 升级必须用这一版） | `runner-v0.3.1-dev2-20260927` | `/data/upgrade-packages/components-v053-20260927/smartx-upgrade-runner-v0.3.1.tar.gz`（10.20.11.3） | `dd096bf239c6023d8997a4a42ff7d71c46b962a5feaeb2dda46d4ade0e25aa1a` | `build_runner_component_package.py --version v0.3.1 --no-build`，直接打包 .3 当前 dev2 构建的 runner 镜像 `0aca32511008`（动作表含 `post_upgrade.schedule_collection`、UPG-049 与 Prometheus legacy 扫描守卫）；不重建镜像，避免改动 .3 运行时。 | `.12` 链路第 2 步 task `upgrade-a56ebcfe87b18b0b` succeeded；用它后 v0.5.3 升级 `upgrade-72bfb3f52317ef7f` succeeded。**旧包对比**：`components/smartx-upgrade-runner-v0.3.1.tar.gz` `a112f6e1…`（2026-06-28）与 `.12` 上的 `d10e15cf…`（2026-07）**均无该动作**（`grep -c schedule_collection` = 0），用它们会在 v0.5.3 切换后失败。 |

## 2026-09-27 DockerHub runner `v0.3.1` / `latest` 补推（内容 = 发行资产 d10e15cf）

| Status | Fix ID | Host Path / 位置 | SHA256 / digest | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| USE / DockerHub 已补齐 | `dockerhub-runner-v0.3.1` | DockerHub `nazawsze/smartx-hci-capacity-insight-upgrade-runner` 的 `v0.3.1` 与 `latest` | 镜像 manifest digest `sha256:90eb5a4239cd9c6863cf7194bfa0bd7fe4935cffb0b5a77467c97ce0b78799fc`（源包 SHA `d10e15cf…`，两者哈希对象不同属正常） | 2026-09-27 在 10.20.11.12 上把**发行资产镜像本体**直接 push 上去（未经 CI，因无任何提交等于该镜像）；同时按用户要求把 `latest` 指到同一镜像。**未动** `v0.3.0`（06-12）与 `runner-sha-31a1209`。 | push 前在容器内核对：`RUNNER_VERSION=v0.3.1`、`schedule_collection=0`、动作 **25**、`actions.py` md5 **`573dd04b3618d2066b0326c2fd183c8d`**（与发行资产逐文件一致）；push 后 DockerHub tags API `v0.3.1`/`latest` 均 200 且 digest 相同（2026-09-27T06:10Z）；`.12` 本地 tag 已还原为 `0aca32511008`（运行容器未受影响）、`docker logout` 后 `auths=[]`。**已知债务：该镜像无对应 git 提交、CI 无法复现（用户 2026-09-27 决定不补源码）。** |

## 2026-09-28 v0.5.3 Platform Package（第六轮 `fc289ff7`，候选）+ runner v0.3.3 组件包

| Status | Fix ID | Host Path / 位置 | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| **CANDIDATE / `.3` 门禁通过；`.12` 现场主路径 + 守卫格已复验（2026-09-28）** | `v0.5.3-r6` | `.3:/data/upgrade-packages/v053-r6-20260928/smartx-capacity-insight-upgrade-v0.5.3.tar.gz`（**11:29 第二次构建，v0.3.2 口径**；11:05 第一次构建基于 v0.3.3 口径已废弃） | `6253810bc7e6dc82880186e7589bc6454a3f6bdb31309697c26044df02a98138` | 相对 r5：①**US-07** 预检查磁盘空间硬校验（`disk_space`）②**US-09** 升级任务产物自动清理（守护线程 + TTL/保留 N）③**US-08** 执行期 runner 在场判定（接受任务租约通道）④**US-25** 卡死 `running` 任务的产品化出路（`recovery/fail` 接受"无活租约的 running"；视图暴露 `runner_lost`）。平台包 runner 基线不变（已发布 `v0.3.1`）；方案 A 口径不变。 | `.3` 门禁（2026-09-28）：`--check-version` OK（v0.5.3）、宿主机构建测试 **26 OK**、identity exit 0、包内敏感成员 **0**；容器内全量见 progress.md（修正 `test_deployment_config` 后应为 461 OK）。**`.12` 复验（2026-09-28，用户授权，全部通过）**：从 v0.5.1 基线经 u2 → 已发布 runner v0.3.1(`d10e15cf…`) → v0.5.2(`692aca8b…`) 重建**客户形态起点**（11 个任务目录占 7.5G、13 悬空镜像、DB 556/89588、`.env` sha `8b644112…`/0600）→ **平台先直升 v0.5.3：task `upgrade-b07795625cf0d681` succeeded（360s）+ 8 项验收全过**（health×2、5 容器 tag、project/network/subnet `10.249.251.0/24`、SQLite `integrity ok` 且 **556/89588 与升级前完全一致**、Prometheus 200 挂目标目录、`.env` 0600 sha 未变、7 条 legacy 路径全清、UI 200）；**重复 start → 400**（`upgrade-925f38527816ae1f` 执行中，第二个 `upgrade-88e7262584becb7c` 被拒，US-23）；**US-25 逃生门**：kill runner → t=35s `runner_lost=True`+`actions=['fail']` → `recovery/fail` 200 → failed → 守卫释放（新 start 放行）。**同版本重装**：装 `c69e2129…` runner 后 `upgrade-26856095c44869d1` 44s succeeded（US-24 ✅，attempt 最大 1 / runner 重启 0）。**本轮新发现 3 条：US-26（平台包把 runner 静默降回 v0.3.1）/US-27（逃生门不清理，legacy 残留）/US-28（组件升级后 ~10 分钟 SQLite 写锁窗口致 web-api 500）**。 |
| **CANDIDATE / US-26 修复轮；`.12` 全部通过** | `v0.5.3-r8` | `.3:/data/upgrade-packages/v053-r8-20260928/smartx-capacity-insight-upgrade-v0.5.3.tar.gz` | `3672e9208f4eb8e82b461d9b242aa205fdb9e7f45267402b5513dd1beae167cb` | 相对 r6（`6253810b…`）：**US-26**——平台包对 runner 只有基线声明（`deploy:false`）无部署指令；web-api 编译期解析现场 runner 镜像注入计划，**现场够用时不降级**；组件升级侧回写 compose 消除 tag 多事实源。**零 runner 改动**（交付一致性 C5 `actions.py md5 matches repo` 证明）。r7（`f772afa5…`）因初版 preserve_current 方案会打挂已发布 runner 的主路径而作废。 | `.3` 门禁（2026-09-28）：后端 **468 tests OK (skipped=2)**、build_tests **26 OK**、`--check-version` OK、identity exit 0、`.sha256` OK、敏感成员 0、交付一致性门禁 C1–C5 全 PASS（C6 DockerHub SKIP）。**`.12` 复验全通过（2026-09-28）**：主路径回归 v0.5.2+v0.3.1 → r8 直升 `upgrade-6f035c3e52b83428` succeeded（188s）+ 8 项验收全过、runner 保持 v0.3.1；组件 v0.3.2 `upgrade-39600ca4b67b75ad` succeeded（存活 90s）；**判别格**同版本重装 `upgrade-7c0720d6207ea942` succeeded、**runner 保持 v0.3.2**（修复前回落 v0.3.1）、attempt 最大 1、重启 0、8 项验收全过、DB 556/89588 不变；US-23 抽查 400。 |
| USE / 已构建（本次**不交付**，随下一版一起发） | `runner-v0.3.2-dev-20260928` | `.3:/data/upgrade-packages/components-v032-20260928/smartx-upgrade-runner-v0.3.2.tar.gz` | `c69e2129223d8401bb8cbc413b582721c52da041ee8c89ac39f66ea23d575be8` | `build_runner_component_package.py --version v0.3.2`：含 **US-24 修复**（`engine._save` 对同文件 mirror 不再双写）。**版本号保持 v0.3.2**（该版本从未交付/发布，按用户 2026-09-28 口径直接并入，不 bump）。 | 交付一致性门禁（`scripts/verify_runner_delivery_consistency.py --package …`）：C1–C5 全 PASS（repo v0.3.3 / 26 动作 / 三个 compose 字面量 v0.3.3 / manifest v0.3.3 / 归档 SHA / 镜像内 `app/RUNNER_VERSION=v0.3.3` + `actions.py` md5 == 仓库）；C6 DockerHub tag **SKIP**（本次不推送——用户 2026-09-28 决定随下一版交付）。**`.12` 复验（2026-09-28）**：组件升级 `upgrade-9fdaff9a349bc257` succeeded（预检查含 `disk_space`=US-07 ✅），runner → v0.3.2（容器 tag / `/app/RUNNER_VERSION` / health 三方一致）、**存活 90s+ 未被停（US-11）**；随后 v0.5.3 同版本重装 `upgrade-26856095c44869d1` **44s succeeded、post-cleanup succeeded、runner 重启 0 次、动作 attempt 最大 1** → **US-24 确认修复**（修复前 attempt=17 崩溃循环）。**遗留 US-26：紧接着的平台升级把 runner 降回 v0.3.1，组件升级不耐受平台升级。** |
| **CANDIDATE / 取代 `c69e2129…`；随下一版交付** | `runner-v0.3.2-r2-20260928` | `.3:/data/upgrade-packages/components-v032-r2-20260928/smartx-upgrade-runner-v0.3.2.tar.gz` | `7f72721fd7ab9b20da88ebc212566ba46aede8ca1f9b35d789b0c82e287a327e` | 在 `c69e2129…`（含 US-24）基础上追加 **US-28 治本**：`lease.py::_connect()` 改为 `@contextmanager` 显式关闭连接——原先 `with self._connect()` 只提交事务不关连接，心跳每 5 秒漏一个，`.12` 实测 52 个 fd / 约 10 分钟 SQLite 写锁窗口，web-api 升级预检查连报 500 `database is locked`。**版本仍 v0.3.2**（从未交付，同 US-24 先例不 bump）。 | **扩展后交付一致性门禁全 PASS**：新增 `runner 源码树指纹 matches repo (2eb5b40d…, 7 个模块)`——证明包内 `lease.py` 修复与仓库同源（C5 原先只校验 `actions.py`，改其它模块抓不到，属门禁漏洞已补）。负向实证：旧包 `c69e2129…` 正确报出 `不一致模块：lease.py`。`.3` 后端 **490 tests OK**、build_tests 26 OK。**`.12` 复验待授权**：组件升级到本包后紧接平台步，预检查应不再 500。 |

## 2026-09-27 v0.5.3 Platform Package（第四轮 `e1c0fde8` → 已被 r5 取代）+ runner v0.3.2 组件包

| Status | Fix ID | Host Path / 位置 | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| **USE / 门禁通过，.12 MVP 验收待授权（当前候选）** | `v0.5.3-r5` | `.3:/data/upgrade-packages/v053-r5-20260927/smartx-capacity-insight-upgrade-v0.5.3.tar.gz` | `b9560eeef3e7040825b3a2a3c9b9c79f083b42310370624af240960120bfcd3c` | 相对 r4 `e1c0fde8`（49-52 修复轮）：①US-05 manifest `required_health` 移除 `runner_version` 等值断言（post-cleanup 对升级顺序免疫；manifest 实证仅 `version`+`checks`）②US-23 升级单飞守卫（start/retry/recovery/rollback 互斥 + 类级锁消除并发竞态，cancel/delete 不拦）③新增 `test_upgrade_single_flight.py` 9 用例。`minimum_runner_version=v0.3.1`、方案 A（`auto_collection=false`+`platform_collection=true`）不变。 | `.3` 门禁（2026-09-27）：`--check-version` OK、identity OK（web-api v0.5.3 / runner 基线 v0.3.1）、`.sha256` OK、敏感 0、后端 **386 tests OK (skipped=2)**、build_tests 26 OK、tsc 0、vitest 107 passed、api docs 77=76、release docs PASS。**`.12` 全链路演练（2026-09-27 第二轮，从 u2 起）通过**：`v0.5.1→u2(upgrade-232d290f059296b2)→runner v0.3.1 d10e15cf(upgrade-5a9434b468b332d6)→v0.5.2 692aca8b(upgrade-06922d540ee06f8d + post-cleanup success)→本包(upgrade-da11b14fe60b7ae9 succeeded + post-cleanup succeeded)→runner v0.3.2 3d99599c(upgrade-6a8a543f7da0b761 succeeded)`；数据 users1/towers1/clusters1/vm_latest556/vm_volumes89588 全程未变、integrity ok、`.env` 0600 sha `8b644112e7433b50…` 未变、Prometheus 200；8 项验收在 r5 与 r5+v0.3.2 两次全过；US-23「重复 start → 400」实测通过。演练副产品：发现 US-24（同版本重装卡死）与 US-25（running 卡死无出路），见 pending-tasks #48/#49。**M3-08（u2 × 先 runner 后平台）仍待 v0.3.2 交付决策。** |
| SUPERSEDED BY v0.5.3-r5 / 第四轮验收通过 | `v0.5.3-r4` | `.3:/data/upgrade-packages/v053-r4-20260927/smartx-capacity-insight-upgrade-v0.5.3.tar.gz` | `e1c0fde814f192fa702469fc870b19590dcae5ed39375c116bc64a8690bab009` | 相对第一轮 `54aa8807`：①方案 A（manifest `auto_collection=false`+`platform_collection=true`、compiler 不再下发 `post_upgrade.schedule_collection`、平台侧 5 秒轮询自建标记完成采集）②49-50 动作级预检查 `runner_actions` + runner 镜像缺失提示 ③同 project 原地组件升级不再停掉新 runner ④**平台包 runner 基线回退已发布 `v0.3.1`（恢复直升）** | `.12` 第四轮完整验收：基线 v0.5.1/0.3.0 → 链路 u2 `upgrade-1ea87b5c` / runner `upgrade-2cf232b7` / v0.5.2 `upgrade-5cae8764` 全绿 → **发布版 v0.3.1 直升 v0.5.3 task `upgrade-666284beec04cc87` succeeded**（计划 12 动作无 schedule_collection、post-cleanup succeeded、平台自建标记 `source=target_worker_compatibility`、采集任务已创建[Tower 不可达=环境限制]）→ 8 项验收（runner=v0.3.1）全过 → 组件升级 v0.3.2 后 **runner 存活 90 秒（停机修复生效）**、8 项复验 runner=v0.3.2 全过、新预检查 `runner_actions ok=True（14 动作全部支持）`。`.3` 门禁：`--check-version` OK、identity OK、`.sha256` OK、敏感 0、后端 **377 tests OK**、构建 26 OK。 |
| **SUPERSEDED by `c69e2129…`（2026-09-28 重建的 v0.3.2，含 US-24）** | `runner-v0.3.1-dev2-20260927`（v0.3.2 组件包） | `.3:/data/upgrade-packages/components-v032-20260927/smartx-upgrade-runner-v0.3.2.tar.gz` | `3d99599cd0e8fcebc68381ebc49d6dfd52f01de2608242a1fb21bbb0b80cc6fe` | 从当前 dev2 源码构建；含两处修复：`task.migrate_runtime_state` bind-mount 双视图防自删、（平台侧另含）同 project 不停 runner；动作 26 个 | `.12` 阶段 6：组件升级 task `upgrade-…` succeeded → `component-version=v0.3.2`、容器 tag v0.3.2、**存活 90 秒未被停（修复前 10 秒必死）**、health `v0.5.3/v0.3.2` 三 checks 全绿。**2026-09-27 第二轮链路演练末步复验**：task `upgrade-6a8a543f7da0b761` succeeded、runner 连续存活 120 秒（每 10s 采样心跳均为 v0.3.2）、8 项复验全过（输入为**本地构建包** `3d99599c…`，非 Release 资产）。**交付缺口（2026-09-27）：本组件包仅在 `.3` 本地目录，尚无 `runner-v0.3.2` git tag、无 DockerHub 镜像、未作为 Release 资产交付；三个源码 compose 已写 `upgrade-runner:v0.3.2` —— 三处同源核对未过，是否随发布交付待用户决策。** |

## 2026-09-30 runner v0.3.2 r7 / r8（US-32 组件路径闭环轮；随下一版交付）

| Status | Fix ID | Host Path / 位置 | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| SUPERSEDED BY `cedbf4c4…`（r7 含回写但不触发，见 Validation） | `runner-v0.3.2-r7-20260930` | `.3:/data/upgrade-packages/components-v032-r7-20260930/smartx-upgrade-runner-v0.3.2.tar.gz` | `b3f85f0d10b14ac0094292033ff0e17a59c9694f68031e2a6bc399728496586b` | 完整构建（非 `--no-build`），含 US-32 第一版 runner-side 回写：`_writeback_runner_compose_tag()` 挂在 `_finish_runner_component_steps()` 的两个 `runner_resume_pending` 收尾点。 | 交付一致性门禁 **12 PASS / 0 FAIL**（C6 SKIP）；`.3` 后端 **647 tests OK (skipped=6)**、build_tests 26 OK。**`.14` 实测回写未生效**：task `upgrade-ead521581ad91115` succeeded、runner=v0.3.2，但 `project/docker-compose.yml` 仍写 `v0.3.1`——两条回写路径都以「任务未收尾」为前提，而组件任务步骤已被 web-api 收尾为全部 succeeded、`status=success`、无 `execution_plan`，两条都不触发。**该包不作为交付物**。 |
| **CANDIDATE / US-32 组件路径闭环；`.14` 完整判别通过；随下一版交付** | `runner-v0.3.2-r8-20260930` | `.3:/data/upgrade-packages/components-v032-r8-20260930/smartx-upgrade-runner-v0.3.2.tar.gz` | `cedbf4c4a77a38b719f19df2328e56de86716459f12ab6a87439121848856907` | 相对 r7（`b3f85f0d…`）修 US-32 第三层根因：新增**幂等兜底路径**，判据由「任务状态」改为「compose tag 是否已对齐」——`_compose_runner_tag_now()` / `_runner_tag_aligned()` / `_apply_tag_writeback_if_needed()`。compose 读不到时视为已对齐（不反复扰动现场）；已对齐则不追加日志（避免每次轮询刷一遍）。**不新增动作、不改能力集**（仍 26 actions），平台包 `minimum_runner_version` 无需变更。版本仍 v0.3.2（从未交付，按既有口径不 bump）。 | 交付一致性门禁 **12 PASS / 0 FAIL**（源码树指纹 `b956e4c2e1a3…` 7 模块、`actions.py` md5 `944378c3…`、动作 26、C6 SKIP）。`.3` 后端 **647 tests OK (skipped=6)**、build_tests 26 OK、US-32 定向 **21 OK**（原 15 + success 终态 6 例）、离线交付脚本 **54 OK**、api docs 77=76、release docs PASS。**`.14` 闭环判别（2026-09-30）**：包传 `/opt/staging/runner-r8.tar.gz`（SHA 三方一致）→ 走产品 API 预检查 7 项全 ok（含 `runner_first_order`：源端 v0.5.3 已含同 project 守卫）→ 启动 → **task `upgrade-8c90bbc7bd52290c` succeeded** → `project/docker-compose.yml` **v0.3.1 → v0.3.2**、`compose-runtime/docker-compose.runner-bootstrap.yml` v0.3.2、容器镜像与容器内 `RUNNER_VERSION` 均 v0.3.2、health `ok=True v0.5.3/v0.3.2`、5/5 容器 Up、任务日志留痕「已对齐 compose runner tag：…v0.3.1 -> …v0.3.2」、**幂等：40 秒（3 个轮询周期）后日志条数稳定在 5**。**同轮附带**：`upgrade.sh --with-runner` 改为先等 `GET /api/admin/upgrade/post-cleanup/{task_id}` 收敛再发起 runner 升级（消除 US-23 单飞 400 竞态，commit `4a8ad77`）。 |

## 2026-10-01 v0.5.3 第七轮候选（收编 09-30~10-01 全部修复；待 `.12` 补升级验收后发布）

| Status | Fix ID | Host Path / 位置 | SHA256 | What Changed | Validation Result |
| --- | --- | --- | --- | --- | --- |
| **CANDIDATE（取代 r15；`.3`/`.12`/`.14` 三机验收均通过，发布等用户指令）** | `v0.5.3-r16-20261004` | .3:/data/r16-build/packages/latest/smartx-capacity-insight-upgrade-v0.5.3.tar.gz | `fbb0f9ce523567542bfa500110dbd10bce8ae7fb915818b588aee563ae368343` | 源码 = dev2 `5dc4429`（`git archive`；记录在 `/data/r16-build.meta`），runner 组件包 SHA `669a60f9739b59679b549dbc27a4610dc3548a26f0237df26d84b86a1e3cd55e`。相对 r15 收编 Phase 66 两个修复：**① `ec8fa40` 删除升级包只删体积产物、保留 `task.json`**（原 `rmtree` 整个任务目录，连历史记录一起删；与 r14「宁留记录不留包」矛盾、组件包同源受影响）。新增 14 例（删包 7 + 守卫 7）；**变异测试**：还原 `rmtree` 后删包 7 例中 5 例失败，确认测试有效。**② `f09c3f0` `.env` 变更重建前告警**（US-42 守卫 `SMARTX_ENV_FILE_SHA256` + 依赖闭包解析；不改代码，因消除它需改 5 个服务的环境变量传递，判为过度工程）。**`.3` 门禁全过**：版本 EXIT=0；包身份 EXIT=0；**runner 交付一致性 12 PASS 0 FAIL**；对外文档脱敏 EXIT=0；**后端全量 793 tests / 1 既有失败 / skipped=7**；前端 tsc=0、108 tests。**包内代码核对**：web-api 与 collector-worker 两镜像内 `fs.py`/`intake.py`/`taskfile.py`/`cleanup/service.py` 四文件 md5 与源码**逐位一致**。**`.12` 生产等价（PASS）**：预检查 9/9 → 升级 succeeded → post-cleanup succeeded → health ok（3/3）、runner v0.3.2 **未降级**、**数据逐位不变（3 towers/1 cluster/197 VM/total_bytes 240988182282240）**、5 容器全 running 且镜像为 r16（web-api `b7909a84…`）。**核心验证**：走产品 API 删包 → `deleted_count=2 space_reclaimed=893226479 kept_record=True`，宿主侧目录 **853M → 188K**、**`task.json` 保留**、历史仍可查到、`has_package=False`、`status` 仍 200（**r15 下此处记录会消失**）。**`.14` 干净机（PASS）**：预检查 9/9 → 升级 succeeded → post-cleanup succeeded → health ok、runner 未降级、5 容器 running 且镜像为 r16；删包同样释放 893226479 字节且记录保留。**⚠️ 遗留观察（已登记 pending #82，非本轮引入）**：`.12` 的 `upgrade-runner` `RestartCount=1`，日志为心跳更新抛 `sqlite3.OperationalError: database is locked` （升级期间写库持锁）→ 进程退出 → `restart: unless-stopped` 自愈。本次升级结果不受影响，但**属 runner 能力问题，须先 bump `RUNNER_VERSION` 并经用户同意**方可修（AGENTS §6） |
| **CANDIDATE（取代 r14；`.12`/`.14` 生产级验收均通过，发布等用户指令）** | `v0.5.3-r15-20261004` | .3:/data/r15-build/packages/latest/smartx-capacity-insight-upgrade-v0.5.3.tar.gz | `fe53470999bf7a3e33d62f69ef393523ab84a50becac19a9fb0995c8cdfa0e3b` | 源码 = dev2 `a10bad3`（`git archive` 传输；构建树记录在 `/data/r15-build.meta`），runner 组件包 SHA `b6b3b981333a25899cf97203d6ac15f14871e31689d5f0a4db7ccadf6cc58ccd`。相对 r14 收编 3 个提交：**① `1b0c3dd` 上传失败回滚**（不再留「有包无 task.json」残缺目录）；**② `0f8b19f`+`efce7da` 磁盘占用告警**（新 `capacity_alerts/disk.py`，80%/90% + 绝对下限 2 GiB，修「集群告警失败连带跳过磁盘告警」的静默失效）；**③ 上传前置空间检查**（只判物理空间 `包×3`，不含 headroom，避免与 precheck 判定分叉）。**`.3` 门禁全过**：版本门禁 EXIT=0；包身份 EXIT=0（web-api 归档已 load 校验）；**runner 交付一致性 12 PASS 0 FAIL**（仓库 v0.3.2 / 三个 compose 字面量 / manifest / 包内 RUNNER_VERSION / 源码树指纹 / actions.py md5 / 26 动作集全一致）；对外文档脱敏 EXIT=0；包内敏感文件严格命中 0。**包内代码已核对**：web-api 与 collector-worker 两个镜像内 `disk.py`/`worker.py`/`intake.py` 的 md5 与源码**逐位一致**（8f9d1459…/e977222d…/a4df918a…）。**后端全量 779 tests / 1 既有失败 / skipped=7**（唯一失败为环境性 `test_start_can_submit_task_for_runner_and_runner_executes_it`）；前端 tsc=0、vitest 11 files 108 tests。**真容器功能验证（`.3`）**：①磁盘告警——64MiB tmpfs 真实写到 75%，容器 env `SMARTX_DISK_ALERT_*` 覆盖生效（warning=0.5），产出 warning 告警并**落库到任务中心**（`disk-alert-warning-1c91635e`），二次评估不重复（去重有效）；②上传前置检查——真 web-api + 真鉴权 + 真 multipart，tmpfs 写到 97%（剩 1.90 MiB）后上传 2.001 MiB 包，返回 400 且提示为「磁盘空间不足：/data/upgrades 可用 1.90 MiB，上传该升级包需要 6.00 MiB（含解包空间）。请先到「系统 → 空间清理」释放空间」，且 `/data/upgrades` **零写入**（前置拦截而非事后回滚）；反向验证磁盘充足时**不误拦**（已放行到后续校验）。**`.12` 生产等价（PASS）**：走产品 API 全流程（同版本重装）。基线 health ok / v0.5.3 / runner v0.3.2 / 3 towers / 1 cluster / 197 VM / total_bytes 240988182282240 → 上传 r15 242M 包 **HTTP 200**（`upgrade-99cf673d0c8318fd`，**证明前置检查在真实包 + 健康盘上不误拦**）→ 预检查 **9/9 OK**（disk_space 13.53 GiB ≥ 2.60 GiB）→ 升级 **succeeded** → post-cleanup **succeeded** → 升级后 health ok、**runner 仍 v0.3.2 未降级**、**数据逐位不变 197 VM / total_bytes 240988182282240**、5 容器全 running 且镜像为 r15 （web-api `3e0fab8bff24`、collector-worker `39ae342339a1`，**已确认 r14 旧镜像 `e87172328e07`/`fb3300fb22c3` 不再被任何服务使用**）、compose_file=offline、project 名正确。**`.14` 干净机（PASS）**：基线 health ok / v0.5.3 / **无业务数据**（towers/clusters/vms 全 0）→ 上传 200 → 预检查 **9/9 OK**（disk_space 32.41 GiB）→ 升级 **succeeded** → post-cleanup **succeeded** → 升级后 health ok、runner v0.3.2 未降级、5 容器全 running 且镜像为 r15、r14 旧镜像不再使用。两台均已用产品 API 的 `DELETE /api/admin/upgrade/package/{task_id}` 删除本次测试包。**残留验证缺口（如实记录）**：磁盘告警「真实触发」只在 `.3` 用 64MiB tmpfs 证明过（真落库 `disk-alert-warning-1c91635e` + 去重有效）；`.12`/`.14` 上磁盘健康（分别剩 13.53/32.41 GiB），告警**正确地不触发**，而**在不登录宿主、不改 `.env` 的前提下无法在真机压出高占用**（AGENTS 禁止在 `.12` 做手工运维变更）。故「真机触发」这一项仍只有 `.3` 证据 |
| **CANDIDATE（取代 r13；发布等用户指令）** | `v0.5.3-r14-20261004` | .3:/data/r14-build/packages/latest/smartx-capacity-insight-upgrade-v0.5.3.tar.gz | `08400bc6ff7259f12505c58a41cc739579990f9c2524f53d0e17ad81cf6d60f5` | 源码 = dev2 `d378bf0`（构建树 git 检出，commit `d378bf0`；runner 组件包 SHA `474bc457efd3de17c93114bd7ca3471ed8b4067c5ded7cb3d5a22342871cebf3`）。相对 r13 收编 2 个清理修复：**① 僵尸任务不再锁死空间清理**（`.12` 实测该功能自7 月起因两个 7 月的 running 僵尸任务被永久拒绝，磁盘堆到 94%、`/tmp` tmpfs 100% 满；现按「目录缺失 **且** 状态陈旧 > 6h」双重条件放行，单看目录会误放行刚创建的真任务）；**② 只删包保留升级记录**（`task.json` 172K vs `package/`+tar.gz 853M，`intake.py::history` 只读前者）；**③ 散落迁移包不再占用保留名额**（原先按 mtime 混排会让迁移包挤掉真正的最近一次升级目录，清理显示成功而回滚能力已丢）；默认 `keep_recent` 0→1 且下限强制为 1（回滚需旧镜像来源）。构建：`ops/package.sh --branch dev2 --no-fetch`，三项门禁 EXIT=0（runner 一致性 12 PASS 0 FAIL），交付物与包内字节级一致。**包内验证**：web-api 镜像 `docker load` 后取出容器内 `app/v2/cleanup/service.py`，确认含 `_purge_upgrade_payload`、僵尸判定、散落包处理、默认参数 = 1、下限 = 1。**`.3` 门禁**：后端全量 764 tests / 1 既有失败（`test_v2_upgrade...runner_executes_it`，已在 `9da006d` 对照确认为既有环境限制）/ skipped=7；前端 tsc=0、vitest 11 files 108 tests。**`.12` 生产等价**（同版本重装，任务 `upgrade-2edaac0a1838be34`）：预检查 9/9、14 动作 succeeded、8 项验收全过（**数据逐位不变 90098=90098**、`.env` sha 未变、三件套镜像 ID 全换、runner v0.3.2 未降级）。**r14 专项实测**：两个 7 月僵尸任务仍在库中，但清理**不再被锁死**——扫描 2.58GB/23 项 → 清理 `ok=True deleted=9 kept=1`，日志区分「保留最近 1 个升级任务」/「清理 2 个散落包」，清理后 `upgrades/` 仅剩 853M（本次升级完整包）+ 184K + 44K（仅记录），**历史记录 18 个一个没丢**、散落迁移包 0 个。**`.14` 干净机全流程**：T5 全新安装（步骤 11/11、标记与容器标签一致、守卫已装、.env 600）、**T6 事故判别通过**（错变体 exit=2、容器 ID `725458d724c18b71c8d` 与 health 前后完全一致、restarts=0）、离线升级 runner v0.3.1→v0.3.2、8 项全过、清理功能同样可用（1.12GB → kept=1、清理后 299M、历史记录 3 个）。 |
| SUPERSEDED（被 r14 取代；清理功能存在缺陷，磁盘会持续堆积） | `v0.5.3-r13-20261003` | .3:/data/r13-build/packages/latest/smartx-capacity-insight-upgrade-v0.5.3.tar.gz | `f4ab3b2acab289a8f3ae518875ed73d08f860788cb0e1bb45d805930f3b0ca26` | 源码 = dev2 `733801d`（构建树为 git 检出，commit `733801d`；runner 组件包 SHA `c7be3cb23d560e9e2af82b41d83bd11d3cea39af938dc707b1dfa29f2c983a78`）。相对 r12 收编 6 个提交：`21625bb` 前端已分配色调淡两档（`#6ba6ea`→`#a3c8f0`→`#c2dcf5`，用户两次反馈后定稿，并顺带把图表里硬编码的 `#0f9fbf` 改为走 `--blue-mid` 变量、修正 frontend-style-guide 里失效的 `--blue-soft` 引用）、`e393fff` 站点验收 9 项脚本、其余 4 个为文档（#55 补 r12、#77 补证据、台账一致性、pending 计划态清理）。**代码实质变更仅前端色值一项**。构建：`ops/package.sh --branch dev2 --no-fetch` EXIT=0，平台包身份门禁 / runner 交付一致性（12 PASS 0 FAIL）/ 敏感文件扫描 三项 EXIT=0，交付物镜像与包内解包**字节级一致**。**包内验证已确认 frontend 镜像 CSS 为 `c2dcf5`**（`docker load` 后从容器内 `/usr/share/nginx/html/assets/` 取值，旧色值 `6ba6ea`/`a3c8f0` 均不存在）。`.3` 门禁：后端全量 **758 tests / 1 failure / skipped=7**（唯一失败 `test_v2_upgrade...runner_executes_it` 为既有环境限制、已在 `9da006d` 上同环境对照确认非回归）、前端 tsc=0 + vitest 11 files/108 tests。**余：`.12` 发布机同版本重装验收、`.14` 干净机全流程复核**（后者需用户重输 Tower 密码）。 |
| SUPERSEDED（被 r13 取代；仅文档与验收脚本变更，代码同 r12） | `v0.5.3-r12-20261003` | .3:/data/us37-verify/packages/latest/smartx-capacity-insight-upgrade-v0.5.3.tar.gz | `a4cdd1543ca357bfbff46bf206fdf43345f43bfcdbb0b2e103a9bb53a42b1743` | 源码 = dev2 `c3c4676`（构建树为 git 检出，构建日志记载 commit；runner 组件包 SHA `a2a38dbd…`）。相对 r11 `a5f93524…` 仅收编 **#77 残留卷行清理**：(1) 采集核对统一为 VM 维度——单塔/集群采集成功后 Tower 未返回的 VM（普通与回收站**同口径**）一律删 VM 行**与卷行**（`_purge_missing_vms`），采集失败一律不核对；(2) 新增孤儿卷兜底清扫 `_purge_orphan_vm_volumes`（清掉无对应 VM 行的历史卷行）；(3) 回收站 VM 计入已分配的口径（`0950cb9`）一并落在本包内（r11 构建于 12:33，早于该口径确认，故 r11 的采集代码与终版口径不一致——这是必须重打的原因）。构建：`ops/package.sh` EXIT=0（完整构建）、身份门禁 PASS、runner 一致性门禁 12 项 PASS（含包内镜像 `/app/RUNNER_VERSION`、actions.py md5、26 动作与源码同源）、敏感 0、离线交付目录已生成（平台三件套与 runner 镜像字节级一致）。 | `.3` 后端全量 **758 tests OK (skipped=7)**（Python 3.12 容器内，含本改动 4 个定向用例）；**`.3` 真机数据复验**：`BEFORE vm_latest=248 vm_volumes=373 orphan=1 Σ已分配=213.06 TiB` → 采集 success（197 VM）→ `AFTER vm_latest=197 vm_volumes=279 orphan=0 Σ=171.88 TiB`；看板接口 `allocated_bytes=188989298442240`（171.88 TiB）位于 `used_bytes`（35.10 TiB）与 `total_bytes`（219.21 TiB）之间，回收站 VM 2 台仍入库。**`.3` 已重装为本包**（load r12 镜像后 recreate 三件套；`/api/system/health` = v0.5.3/v0.3.1 三 checks true；实例内端到端采集 success：`已分配 171.88 TiB`、行数稳定 197/279、回收站 VM 2 台保留；重装前快照 `/data/pre-r12-backup/`（integrity ok、197/279 行、SHA 已记））。**`.12` 同版本重装验收已过（2026-10-03，用户授权，全部走产品流程）**：上传 r12 平台包（`uploaded_sha256=a4cdd154…`）→ 预检查 **8/8 OK**（含 `v0.5.3 -> v0.5.3` 修复路径、runner 动作 14/14 由 v0.3.2 支持、checksums 147 项、磁盘余量 4.59 GiB ≥ 2.60 GiB）→ 任务 `upgrade-b86faa353520af27` **succeeded**（08:38:38Z→08:47:24Z，11 个动作全 succeeded：backup/load_images/prepare_filesystem/project_files/task_state/write_override/project_migrate/restart/healthcheck/post_upgrade/runner_handoff），post-cleanup `post-cleanup-upgrade-b86faa353520af27` **succeeded**；8 项验收：①health `v0.5.3`/`v0.3.2` 三 checks true；②三件套运行镜像 ID 与新 tag **逐一 MATCH**、runner 镜像 MATCH v0.3.2（**未被包基线 v0.3.1 降级**，US-26 判别）；③project 仍为 `smartx-hci-capacity-insight`、仅一个 `smartx-hci-capacity-insight-net`；④SQLite integrity ok 且数据**逐位不变**（towers 3 / clusters 3 / vm_latest 583 / vm_volumes 89624 / metric_snapshots 1，与升级前一致）；⑤`.env` sha `8b644112…` 全程未变、0600 root:root；⑥7 条 legacy 路径全 absent；⑦frontend 200 / prometheus 200；⑧镜像内实查含本包新代码（`_purge_missing_vms`/`_purge_orphan_vm_volumes`）。**余**：`.14` 干净机全流程复核（需用户重输 Tower 密码才能恢复采集验证）。 |
| SUPERSEDED（被 r12 取代；采集代码与终版口径不一致） | `v0.5.3-r11-20261003` | .3:/data/us37-verify/packages/latest/smartx-capacity-insight-upgrade-v0.5.3.tar.gz | `a5f935249fe1c8352be52791c28c55f156b8f619814ab8e698b6eaa57c4bdeba` | 相对 r10 收编 2026-10-02~03 全部修复：**#72 定时采集调度停摆自愈**（worker 启动即同步+重试+异常落日志+logging 配置；APScheduler Job 禁止 setattr 的签名缓存修复——.3 实证停摆 20 天根因）、**#75 已分配口径=Σ(每卷供给×副本/EC)** 且计算挪进采集流程（页面零计算；旧 perf 层路径废弃）、**#73 新鲜度横幅自解释**（已约 X 小时未成功采集+阈值）、**#74 迁移页三处说明合并为对比表+相邻卡片间距+密钥弹窗写明本系统密码**、**US-38 导入与 prometheus 压实竞态容错**、**#65 整库替换缓解**（-wal/-shm 清理+先拷后清）、**#66 数据包 404 友好提示**。runner 组件包 v0.3.2 开发线（不随本次交付，源 `be0c0fde…`）。构建：ops/package.sh EXIT=0（完整构建）、身份/一致性门禁 PASS、敏感 0。 | .3 全量 **755 tests / 1 failure（既有环境限制，同断言确认）/ 7 skipped**；前端 tsc 0 / vitest 108；打包门禁（README 7 章节/身份/一致性/敏感）全过。r10 验收结论对不变代码部分沿用；发布前建议 .12 补一次同版本重装验收。 |
| SUPERSEDED（被 r11 取代） | `v0.5.3-r10-20261002` | .3:/data/us37-verify/packages/latest/smartx-capacity-insight-upgrade-v0.5.3.tar.gz | `41304c3a353ab3568b063a6b444449efa447540e0790faa0b623131dfb3022b7` | 相对 r9 仅增量：CLI 客户文档修复（#71）——README 版本无关化（不再写死/宣传未交付组件包）、补「数据迁移与恢复密钥」章节与新选项表、打包脚本强制校验 README 7 章节（缺即构建失败）、交付手册补第 4 件必带事项。代码与 r9 相同（r9 的 .12/.14 验收结论对代码部分全部有效）。构建：ops/package.sh EXIT=0、门禁全过、README 校验在构建链内生效。 | .3 builder/us37/ops 136 tests OK；交付目录 README 实查：含「数据迁移与恢复密钥」、--allow-same-version 4 处、硬编码组件包文件名 0 处。 |
| SUPERSEDED（交付目录 README 过时，#71；代码与 r10 相同，其 .12/.14 验收结论由 r10 沿用） | `v0.5.3-r9-20261001` | `.3:/data/us37-verify/packages/latest/smartx-capacity-insight-upgrade-v0.5.3.tar.gz` | `cf2172a4b012e8dc63623d40283e2d8f11f5072a85298c5524c82f71632072ee` | 相对 r6（`6253810b…`，09-28）收编：**US-37 compose 变体守卫**（标记+守卫+纪律，`.14` 真机验证）、**迁移数据包「仅导出存储监测数据」**（#61）、**#63 合并导入 Tower 身份重映射**（跨系统导入不再照搬源自增 ID）、**#68 导出迁移包名实相符**（SQLite 全量业务拷贝，「迁移包+恢复密钥=完整恢复」成立）、**#65 整库替换最小缓解**（-wal/-shm 清理 + Prometheus 先拷后清）、**upgrade.sh 重复升级防呆 + force-env 拒绝恢复 .env**。runner 组件包仍为 v0.3.2 开发线（不随本次交付，源 `b3f630f4…`）。构建：`ops/package.sh` 端到端 EXIT=0（完整构建非 --no-build）、平台身份门禁 PASS、runner 一致性门禁 PASS、敏感 0。 | `.3` 全量 **737 tests / 1 failure（既有环境限制，同断言确认）/ 7 skipped**；前端 tsc 0 / vitest 108。**`.12` 验收已过（2026-10-01，用户授权）**：发布机同版本重装 v0.5.3→r9（task `upgrade-922fab7a0ecca1a8` **succeeded**，预检查 9 项 OK、14 动作含 post_upgrade/runner_handoff 全 succeeded、post-cleanup succeeded）；**8 项验收全过**：health `v0.5.3`/`v0.3.2` 三 checks true、5 容器正常且 **runner 保持 v0.3.2 未降级（US-26 现场判别：包基线 v0.3.1 < 现场 v0.3.2，未被动）**、project 正确、SQLite integrity ok 且数据 **556/89588/1 逐位不变**、Prometheus ready 200、`.env` sha `8b644112…` 全程未变、7 条 legacy 全清、UI 200。另 `.14` 干净机全流程闭环（全清→安装→CLI 升级→8 项验收全绿，交付 tar `36077eba…`）。 |
