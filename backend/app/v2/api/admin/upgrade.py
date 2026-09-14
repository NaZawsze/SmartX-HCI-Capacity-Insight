from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from app.v2.auth.service import CurrentUser
from app.v2.upgrade.service import UpgradeService

from app.v2.api.deps import get_upgrade_service, require_user
from app.v2.api.models import (
    AdminTaskResponse,
    ComponentCatalogResponse,
    ComponentVersionResponse,
    UpgradeVerificationResponse,
    UpgradeVersionResponse,
)

router = APIRouter()


@router.post("/api/admin/upgrade/upload")
async def upload_upgrade_package(
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
    file: UploadFile = File(...),
) -> dict:
    return await upgrade.upload_package(file)


@router.post("/api/admin/upgrade/precheck/{task_id}")
def precheck_upgrade_package(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.precheck(task_id)


@router.post("/api/admin/upgrade/start/{task_id}")
def start_upgrade_package(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.start(task_id, submit_to_runner=True)


@router.post("/api/admin/upgrade/rollback/{task_id}")
def rollback_upgrade_package(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.rollback(task_id)


@router.post("/api/admin/upgrade/recovery/{task_id}/continue")
def continue_upgrade_recovery(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.recovery_continue(task_id)


@router.post("/api/admin/upgrade/recovery/{task_id}/rollback")
def rollback_upgrade_recovery(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.recovery_rollback(task_id)


@router.post("/api/admin/upgrade/recovery/{task_id}/fail")
def fail_upgrade_recovery(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.recovery_fail(task_id)


@router.post("/api/admin/upgrade/cancel/{task_id}")
def cancel_upgrade_package(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.cancel(task_id)


@router.get("/api/admin/upgrade/status/{task_id}", response_model=AdminTaskResponse)
def upgrade_status(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.status(task_id)


@router.get("/api/admin/upgrade/history", response_model=list[AdminTaskResponse])
def upgrade_history(
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> list[dict]:
    return upgrade.history()


@router.delete("/api/admin/upgrade/package/{task_id}")
def delete_upgrade_package(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.delete_package(task_id)


@router.get("/api/admin/upgrade/version", response_model=UpgradeVersionResponse)
def upgrade_version(
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.version()


@router.get("/api/admin/upgrade/verification", response_model=UpgradeVerificationResponse)
def upgrade_verification(
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.verification()


@router.get("/api/admin/upgrade/post-cleanup/{task_id}", response_model=AdminTaskResponse)
def upgrade_post_cleanup_status(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.post_upgrade_cleanup_status(task_id)


@router.post("/api/admin/upgrade/post-cleanup/{task_id}/retry")
def retry_upgrade_post_cleanup(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.retry_post_upgrade_cleanup(task_id)


@router.post("/api/admin/component-upgrade/upload")
async def upload_component_upgrade_package(
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
    file: UploadFile = File(...),
) -> dict:
    return await upgrade.upload_package(file)


@router.post("/api/admin/component-upgrade/precheck/{task_id}")
def precheck_component_upgrade_package(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.precheck(task_id)


@router.post("/api/admin/component-upgrade/start/{task_id}")
def start_component_upgrade_package(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    task = upgrade.status(task_id)
    return upgrade.start(task_id, submit_to_runner=task.get("component") != "upgrade-runner")


@router.get("/api/admin/component-upgrade/status/{task_id}", response_model=AdminTaskResponse)
def component_upgrade_status(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.status(task_id)


@router.post("/api/admin/component-upgrade/cancel/{task_id}")
def cancel_component_upgrade_package(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.cancel(task_id)


@router.get("/api/admin/component-upgrade/history", response_model=list[AdminTaskResponse])
def component_upgrade_history(
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
    component: str | None = None,
) -> list[dict]:
    component_type = {"upgrade-runner": "runner", "prometheus": "observability"}.get(component or "", component)
    if component_type:
        return upgrade.history(component_type=component_type)
    return [task for task in upgrade.history() if task.get("kind") == "component"]


@router.delete("/api/admin/component-upgrade/package/{task_id}")
def delete_component_upgrade_package(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.delete_package(task_id)


@router.get("/api/admin/component-upgrade/version", response_model=ComponentVersionResponse)
def component_upgrade_version(
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.component_version()


@router.get("/api/admin/component-upgrade/components", response_model=ComponentCatalogResponse)
def component_upgrade_components(
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.component_catalog()
