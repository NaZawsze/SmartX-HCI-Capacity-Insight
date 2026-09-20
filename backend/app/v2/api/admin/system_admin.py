from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.v2.auth.service import CurrentUser
from app.v2.cleanup.service import CleanupService
from app.v2.system.control import SystemControlService

from app.v2.api.deps import get_cleanup_service, get_system_control_service, require_user
from app.v2.api.models import (
    CleanupArtifactsRequest,
    CleanupImagesRequest,
    CleanupScanResponse,
    LocalStorageResponse,
    SqliteBackupDeleteRequest,
)

router = APIRouter()


@router.get("/api/admin/system/cleanup-artifacts/scan", response_model=CleanupScanResponse)
def scan_cleanup_artifacts(
    _: Annotated[CurrentUser, Depends(require_user)],
    cleanup: Annotated[CleanupService, Depends(get_cleanup_service)],
) -> dict:
    return cleanup.scan_artifacts()


@router.get("/api/admin/system/local-storage", response_model=LocalStorageResponse)
def local_storage_usage(
    _: Annotated[CurrentUser, Depends(require_user)],
    cleanup: Annotated[CleanupService, Depends(get_cleanup_service)],
) -> dict:
    return cleanup.local_storage_usage()


@router.get("/api/admin/system/sqlite-vacuum/scan", response_model=CleanupScanResponse)
def scan_sqlite_vacuum(
    _: Annotated[CurrentUser, Depends(require_user)],
    cleanup: Annotated[CleanupService, Depends(get_cleanup_service)],
) -> dict:
    return cleanup.scan_sqlite_vacuum()


@router.post("/api/admin/system/sqlite-vacuum")
def sqlite_vacuum(
    _: Annotated[CurrentUser, Depends(require_user)],
    cleanup: Annotated[CleanupService, Depends(get_cleanup_service)],
) -> dict:
    return cleanup.vacuum_sqlite()


@router.get("/api/admin/system/sqlite-backups/scan", response_model=CleanupScanResponse)
def scan_sqlite_backups(
    _: Annotated[CurrentUser, Depends(require_user)],
    cleanup: Annotated[CleanupService, Depends(get_cleanup_service)],
) -> dict:
    return cleanup.scan_sqlite_backups()


@router.post("/api/admin/system/sqlite-backups/delete")
def delete_sqlite_backups(
    payload: SqliteBackupDeleteRequest,
    _: Annotated[CurrentUser, Depends(require_user)],
    cleanup: Annotated[CleanupService, Depends(get_cleanup_service)],
) -> dict:
    return cleanup.cleanup_sqlite_backups(payload.filenames)


@router.post("/api/admin/system/cleanup-artifacts")
def cleanup_artifacts(
    _: Annotated[CurrentUser, Depends(require_user)],
    cleanup: Annotated[CleanupService, Depends(get_cleanup_service)],
    payload: CleanupArtifactsRequest | None = None,
) -> dict:
    return cleanup.cleanup_artifacts(keep_recent_upgrades=payload.keep_recent_upgrades if payload else 0)


@router.get("/api/admin/system/cleanup-images/scan", response_model=CleanupScanResponse)
def scan_cleanup_images(
    _: Annotated[CurrentUser, Depends(require_user)],
    cleanup: Annotated[CleanupService, Depends(get_cleanup_service)],
) -> dict:
    return cleanup.scan_unused_images()


@router.post("/api/admin/system/cleanup-images")
def cleanup_images(
    _: Annotated[CurrentUser, Depends(require_user)],
    cleanup: Annotated[CleanupService, Depends(get_cleanup_service)],
    payload: CleanupImagesRequest | None = None,
) -> dict:
    return cleanup.cleanup_unused_images(image_ids=payload.image_ids if payload else None)


@router.post("/api/admin/system/restart")
def restart_system_services(
    _: Annotated[CurrentUser, Depends(require_user)],
    system: Annotated[SystemControlService, Depends(get_system_control_service)],
) -> dict:
    return system.restart_data_services()
