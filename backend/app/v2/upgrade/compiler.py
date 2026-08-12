from __future__ import annotations

from typing import Any

from app.upgrade_protocol.constants import ACTION_CAPABILITIES, RUNNER_CAPABILITIES, RUNNER_PROTOCOL_VERSION
from app.upgrade_protocol.models import ExecutionAction, ExecutionPlan
from app.upgrade_protocol.validation import validate_manifest_compatibility


class UpgradeCompilationError(ValueError):
    pass


def _target_runtime_params(directory_transition: dict[str, Any]) -> dict[str, str]:
    target_root = str(directory_transition.get("target_root") or "").rstrip("/")

    def value(key: str, suffix: str) -> str:
        explicit = str(directory_transition.get(key) or "")
        if explicit:
            return explicit
        return f"{target_root}/{suffix}" if target_root else ""

    return {
        "project_path": value("project_path", "project"),
        "app_data_path": value("app_data_path", "app"),
        "upgrades_path": value("upgrades_path", "upgrades"),
        "backups_path": value("backups_path", "backups"),
        "exports_path": value("exports_path", "exports"),
        "compose_runtime_path": value("compose_runtime_path", "compose-runtime"),
        "prometheus_data_path": value("prometheus_data_path", "prometheus"),
    }


def compile_execution_plan(manifest: dict[str, Any]) -> ExecutionPlan:
    component_types = {str(component.get("type")) for component in manifest.get("components") or []}
    if "runner" in component_types:
        raise UpgradeCompilationError("upgrade-runner 组件必须由 web-api 直接升级。")

    actions: list[ExecutionAction] = []
    images = [
        dict(image)
        for component in manifest.get("components") or []
        for image in component.get("images") or []
    ]
    services = sorted(
        {
            str(service)
            for component in manifest.get("components") or []
            for service in component.get("services") or []
            if service
        }
    )
    apply_services = [service for service in services if service != "upgrade-runner"]

    actions.append(
        ExecutionAction(
            id="backup",
            type="backup.create",
            params={
                "scope": (
                    "bundle"
                    if {"platform", "observability"} <= component_types
                    else "observability"
                    if component_types == {"observability"}
                    else "platform"
                )
            },
        )
    )
    for index, image in enumerate(images, start=1):
        if not image.get("archive"):
            continue
        actions.append(
            ExecutionAction(
                id=f"load-image-{index}",
                type="image.load",
                params={
                    "service": image.get("service"),
                    "image": image.get("image"),
                    "archive": image.get("archive"),
                    "sha256": image.get("sha256"),
                },
            )
        )

    directory_transition = manifest.get("directory_transition")
    if isinstance(directory_transition, dict) and directory_transition:
        params = dict(directory_transition)
        helper_image = next((str(image.get("image")) for image in images if image.get("service") == "web-api"), "")
        if helper_image:
            params["helper_image"] = helper_image
        actions.append(
            ExecutionAction(
                id="prepare-filesystem-layout",
                type="filesystem.prepare",
                params=params,
            )
        )

    if manifest.get("project_files"):
        actions.append(
            ExecutionAction(
                id="sync-project-files",
                type="files.sync",
                params={
                    "source": str(manifest.get("project_source") or "project"),
                    "files": list(manifest.get("project_file_list") or []),
                },
            )
        )
    for index, file_set in enumerate(manifest.get("file_sets") or [], start=1):
        actions.append(
            ExecutionAction(
                id=f"sync-file-set-{index}",
                type="files.sync",
                params={
                    "source": str(file_set.get("source") or ""),
                    "target": str(file_set.get("target") or ""),
                    "files": list(file_set.get("files") or []),
                    "checksums": dict(file_set.get("checksums") or {}),
                },
            )
        )

    legacy_cleanup = manifest.get("legacy_cleanup")
    if isinstance(legacy_cleanup, dict) and legacy_cleanup:
        target_upgrades_path = ""
        if isinstance(directory_transition, dict):
            target_upgrades_path = str(directory_transition.get("upgrades_path") or "")
        actions.append(
            ExecutionAction(
                id="migrate-task-state",
                type="task.migrate_runtime_state",
                params={"target_upgrades_path": target_upgrades_path},
            )
        )

    actions.append(
        ExecutionAction(
            id="write-compose-override",
            type="compose.override",
            params={"images": images, "services": services},
        )
    )
    environment_transitions = list(manifest.get("environment_transitions") or [])
    if environment_transitions:
        actions.append(
            ExecutionAction(
                id="migrate-compose-project",
                type="compose.project_migrate",
                params={"transitions": environment_transitions},
            )
        )

    migration = dict(manifest.get("migration") or {})
    if migration.get("required"):
        image_service = migration.get("image_service") or "web-api"
        execution_image = next(
            (str(image.get("image")) for image in images if image.get("service") == image_service),
            "",
        )
        actions.append(
            ExecutionAction(
                id="run-migration",
                type="script.run_sandboxed",
                params={
                    "script": migration.get("script"),
                    "sha256": migration.get("sha256"),
                    "image_service": image_service,
                    "image": execution_image,
                    "mounts": list(migration.get("mounts") or []),
                    "timeout_seconds": min(max(int(migration.get("timeout_seconds") or 900), 1), 3600),
                    "completion_marker": migration.get("completion_marker"),
                    "post_check": migration.get("post_check"),
                },
            )
        )

    actions.append(
        ExecutionAction(
            id="apply-compose",
            type="compose.apply",
            params={"services": apply_services},
        )
    )
    if "observability" in component_types:
        actions.append(
            ExecutionAction(
                id="health-prometheus",
                type="health.prometheus",
                params={
                    "url": "http://prometheus:9090/-/healthy",
                    "attempts": 30,
                    "delay_seconds": 2,
                    "timeout_seconds": 15,
                },
            )
        )
    if "platform" in component_types:
        actions.append(
            ExecutionAction(
                id="health-platform",
                type="health.http",
                params={
                    "url": "http://web-api:8000/api/system/health",
                    "expected_status": 200,
                    "attempts": 30,
                    "delay_seconds": 2,
                    "timeout_seconds": 15,
                },
            )
        )
    post_upgrade = manifest.get("post_upgrade")
    schedule_post_cleanup = bool(
        isinstance(post_upgrade, dict)
        and post_upgrade.get("create_cleanup_task")
        and isinstance(legacy_cleanup, dict)
        and legacy_cleanup
    )
    target_project = ""
    target_network = ""
    legacy_project = ""
    if environment_transitions:
        first_transition = environment_transitions[0]
        if isinstance(first_transition, dict):
            legacy_project = str(first_transition.get("from_project") or "")
            target_project = str(first_transition.get("to_project") or "")
            target_network = str(first_transition.get("to_network") or "")
    runner_image = next((str(image.get("image")) for image in images if image.get("service") == "upgrade-runner"), "")

    if isinstance(legacy_cleanup, dict) and legacy_cleanup:
        actions.append(
            ExecutionAction(
                id="sync-task-state",
                type="task.sync_runtime_state",
                params={},
            )
        )
    schedule_auto_collection = bool(isinstance(post_upgrade, dict) and post_upgrade.get("auto_collection"))
    if schedule_auto_collection:
        target_upgrades_path = ""
        if isinstance(directory_transition, dict):
            target_upgrades_path = str(directory_transition.get("upgrades_path") or "")
        actions.append(
            ExecutionAction(
                id="schedule-post-upgrade-collection",
                type="post_upgrade.schedule_collection",
                params={
                    "target_upgrades_path": target_upgrades_path,
                    "target_version": str(manifest.get("version") or ""),
                },
            )
        )
    if schedule_post_cleanup:
        actions.append(
            ExecutionAction(
                id="schedule-post-upgrade-cleanup",
                type="post_upgrade.schedule_cleanup",
                params={
                    "cleanup_task_type": "post_upgrade_cleanup",
                    "parent_task_status": "success",
                    "failure_severity": str(post_upgrade.get("cleanup_failure_severity") or "warning"),
                },
            )
        )
        if isinstance(directory_transition, dict) and directory_transition:
            runtime_params = _target_runtime_params(directory_transition)
            actions.append(
                ExecutionAction(
                    id="schedule-runner-target-runtime-handoff",
                    type="runner.schedule_target_runtime_handoff",
                    params={
                        "image": runner_image,
                        "compose_project": target_project,
                        "network_name": target_network,
                        **runtime_params,
                    },
                )
            )
    elif isinstance(legacy_cleanup, dict) and legacy_cleanup:
        actions.append(
            ExecutionAction(
                id="handoff-runner-target-runtime",
                type="runner.handoff_target_runtime",
                params={
                    "image": runner_image,
                    "compose_project": target_project,
                    "network_name": target_network,
                },
            )
        )
        if legacy_project:
            actions.append(
                ExecutionAction(
                    id="stop-legacy-runner-runtime",
                    type="runner.stop_legacy_runtime",
                    params={
                        "legacy_project": legacy_project,
                        "legacy_runner_container": f"{legacy_project}-upgrade-runner-1",
                        "target_project": target_project,
                    },
                )
            )
        actions.append(
            ExecutionAction(
                id="cleanup-legacy-runtime",
                type="legacy.cleanup",
                params=dict(legacy_cleanup),
            )
        )

    action_capabilities = {ACTION_CAPABILITIES.get(action.type, action.type) for action in actions}
    required = sorted(action_capabilities | {str(item) for item in manifest.get("required_capabilities") or []})
    compatibility_manifest = {
        **manifest,
        "minimum_runner_protocol": int(manifest.get("minimum_runner_protocol") or 1),
        "required_capabilities": required,
    }
    validate_manifest_compatibility(compatibility_manifest, RUNNER_PROTOCOL_VERSION, RUNNER_CAPABILITIES)
    return ExecutionPlan(
        protocol_version=RUNNER_PROTOCOL_VERSION,
        required_capabilities=required,
        actions=actions,
    )


def compile_post_upgrade_cleanup_plan(
    legacy_cleanup: dict[str, Any],
    *,
    parent_task_id: str,
    target_version: str = "v0.5.2",
    target_project: str = "smartx-hci-capacity-insight",
) -> ExecutionPlan:
    legacy_projects = [str(project) for project in legacy_cleanup.get("legacy_projects") or [] if str(project)]
    legacy_networks = [str(network) for network in legacy_cleanup.get("legacy_networks") or [] if str(network)]
    first_legacy_project = legacy_projects[0] if legacy_projects else "smartx-storage-forecast"
    helper_image = str(legacy_cleanup.get("helper_image") or "")
    data_migration_guard = dict(legacy_cleanup.get("data_migration_guard") or {})
    actions = [
        ExecutionAction(
            id="post-cleanup-precheck-target-health",
            type="post_cleanup.precheck_target_health",
            params={
                "parent_task_id": parent_task_id,
                "target_version": target_version,
                "target_project": target_project,
                "required_health": dict(legacy_cleanup.get("required_health") or {}),
                "health_url": str(legacy_cleanup.get("health_url") or "http://web-api:8000/api/system/health"),
                "timeout_seconds": int(legacy_cleanup.get("timeout_seconds") or 15),
                **({"data_migration_guard": data_migration_guard} if data_migration_guard else {}),
            },
        ),
        ExecutionAction(
            id="stop-legacy-runner-runtime",
            type="runner.stop_legacy_runtime",
            params={
                "legacy_project": first_legacy_project,
                "legacy_runner_container": f"{first_legacy_project}-upgrade-runner-1",
                "target_project": target_project,
            },
        ),
        ExecutionAction(
            id="stop-legacy-compose-project",
            type="compose.stop_legacy_project",
            params={"legacy_projects": legacy_projects, "target_project": target_project},
        ),
        ExecutionAction(
            id="remove-legacy-network",
            type="network.remove_legacy",
            params={"legacy_networks": legacy_networks, "legacy_projects": legacy_projects},
        ),
        ExecutionAction(
            id="cleanup-legacy-paths",
            type="filesystem.cleanup_legacy_paths",
            params={
                "paths": list(legacy_cleanup.get("legacy_paths") or []),
                "protected_paths": list(legacy_cleanup.get("protected_paths") or []),
                **({"helper_image": helper_image} if helper_image else {}),
                **({"data_migration_guard": data_migration_guard} if data_migration_guard else {}),
            },
        ),
        ExecutionAction(
            id="cleanup-target-app-residuals",
            type="filesystem.cleanup_target_app_residuals",
            params={
                "paths": list(legacy_cleanup.get("target_app_residual_paths") or []),
                "protected_paths": list(legacy_cleanup.get("protected_paths") or []),
                **({"helper_image": helper_image} if helper_image else {}),
            },
        ),
        ExecutionAction(
            id="post-cleanup-verify",
            type="post_cleanup.verify",
            params={
                "parent_task_id": parent_task_id,
                "legacy_projects": legacy_projects,
                "legacy_networks": legacy_networks,
                "paths": list(legacy_cleanup.get("legacy_paths") or []) + list(legacy_cleanup.get("target_app_residual_paths") or []),
                "required_health": dict(legacy_cleanup.get("required_health") or {}),
                "health_url": str(legacy_cleanup.get("health_url") or "http://web-api:8000/api/system/health"),
                "timeout_seconds": int(legacy_cleanup.get("timeout_seconds") or 15),
                **({"data_migration_guard": data_migration_guard} if data_migration_guard else {}),
            },
        ),
    ]
    action_capabilities = {ACTION_CAPABILITIES.get(action.type, action.type) for action in actions}
    required = sorted(action_capabilities)
    validate_manifest_compatibility(
        {
            "minimum_runner_protocol": RUNNER_PROTOCOL_VERSION,
            "required_capabilities": required,
        },
        RUNNER_PROTOCOL_VERSION,
        RUNNER_CAPABILITIES,
    )
    return ExecutionPlan(
        protocol_version=RUNNER_PROTOCOL_VERSION,
        required_capabilities=required,
        actions=actions,
    )
