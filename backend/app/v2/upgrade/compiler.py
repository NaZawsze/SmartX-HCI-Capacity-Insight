from __future__ import annotations

from typing import Any

from app.upgrade_protocol.constants import RUNNER_CAPABILITIES, RUNNER_PROTOCOL_VERSION
from app.upgrade_protocol.models import ExecutionAction, ExecutionPlan
from app.upgrade_protocol.validation import validate_manifest_compatibility


class UpgradeCompilationError(ValueError):
    pass


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

    actions.append(
        ExecutionAction(
            id="write-compose-override",
            type="compose.override",
            params={"images": images, "services": services},
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
            params={"services": services},
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

    action_capabilities = {
        "script.sandbox.v1" if action.type == "script.run_sandboxed" else action.type
        for action in actions
    }
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
