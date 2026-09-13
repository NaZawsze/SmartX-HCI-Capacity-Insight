from __future__ import annotations

from pathlib import Path
from secrets import token_hex
from typing import Annotated, Optional, Union
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from app.v2.auth.service import AuthService, CurrentUser
from app.v2.cloudtower.service import CloudTowerService
from app.v2.cleanup.service import CleanupService
from app.v2.collection.service import CollectionService
from app.v2.config import V2Settings, settings_from_environment
from app.v2.dashboard.service import DashboardService
from app.v2.database import V2Database
from app.v2.inventory.models import ClusterInput, TowerInput
from app.v2.inventory.service import InventoryService
from app.v2.migration.service import ARCHIVE_MEDIA_TYPE, MigrationService
from app.v2.reports.export import DOCX_MEDIA_TYPE, XLSX_MEDIA_TYPE, build_report_docx, build_report_xlsx
from app.v2.reports.service import ReportService
from app.v2.system.control import SystemControlService
from app.v2.system.health import check_health
from app.v2.tasks.models import TaskStatus, TaskType
from app.v2.tasks.service import TaskService
from app.v2.upgrade.service import UpgradeService
from app.v2.vms.service import VmService

from app.v2.api.system import download_response, record_export_bundle_task, record_export_task

from app.v2.api.deps import (
    get_auth_service,
    get_cleanup_service,
    get_cloudtower_service,
    get_collection_service,
    get_dashboard_service,
    get_inventory_service,
    get_migration_service,
    get_report_service,
    get_system_control_service,
    get_task_service,
    get_upgrade_service,
    get_v2_database,
    get_v2_settings,
    get_vm_service,
    require_user,
)
from app.v2.api.models import (
    AdminTaskResponse,
    CapacityRiskModel,
    CleanupScanResponse,
    ClusterGrowthRateModel,
    ClusterPayload,
    ClusterResponse,
    ClusterUpdatePayload,
    CollectionRunDetailResponse,
    CollectionRunRequest,
    CollectionRunResponse,
    ComponentCatalogResponse,
    ComponentVersionResponse,
    DashboardClusterModel,
    DashboardCollectionModel,
    DashboardScopeModel,
    DashboardStorageModel,
    DashboardSummaryResponse,
    DashboardTowerModel,
    DashboardTotalsModel,
    DashboardVmItemModel,
    DataQualityModel,
    ForecastModel,
    LocalStorageResponse,
    LoginRequest,
    MigrationHealthResponse,
    PasswordChangeRequest,
    ReportClusterModel,
    ReportGrowthItemModel,
    ReportResponse,
    ReportScopeModel,
    RiskClusterModel,
    RiskThresholdsModel,
    SqliteBackupDeleteRequest,
    SystemHealthResponse,
    TaskResponse,
    TaskSeenRequest,
    TokenResponse,
    TopClusterModel,
    TowerCollectionStatus,
    TowerPayload,
    TowerTestPayload,
    TowerTestResponse,
    UpgradeVerificationResponse,
    UpgradeVersionResponse,
    UserResponse,
    VmDetailResponse,
    VmTrendResponse,
    VmVolumeResponse,
)

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


@router.get("/api/admin/exports/{category}/{filename}")
def download_saved_export(
    category: str,
    filename: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    settings: Annotated[V2Settings, Depends(get_v2_settings)],
) -> FileResponse:
    if category == "reports":
        base_dir = settings.reports_dir
    elif category == "migrations":
        base_dir = settings.migrations_dir
    else:
        raise HTTPException(status_code=404, detail="导出文件不存在。")
    path = base_dir / Path(filename).name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="导出文件已失效，请重新生成。")
    return FileResponse(path, filename=Path(filename).name)



@router.get("/api/admin/migration/export")
def export_migration(
    _: Annotated[CurrentUser, Depends(require_user)],
    migration: Annotated[MigrationService, Depends(get_migration_service)],
) -> Response:
    content, filename, path, download_url = migration.build_export_archive()
    return download_response(content, filename, ARCHIVE_MEDIA_TYPE, path=path, download_url=download_url)



@router.get("/api/admin/migration/config/export")
def export_config_migration(
    _: Annotated[CurrentUser, Depends(require_user)],
    migration: Annotated[MigrationService, Depends(get_migration_service)],
) -> Response:
    content, filename, path, download_url = migration.build_config_export_archive()
    return download_response(content, filename, ARCHIVE_MEDIA_TYPE, path=path, download_url=download_url)



@router.post("/api/admin/migration/export/start")
def start_migration_export(
    _: Annotated[CurrentUser, Depends(require_user)],
    migration: Annotated[MigrationService, Depends(get_migration_service)],
) -> dict:
    return migration.start_export_task()



@router.get("/api/admin/migration/export/status/{task_id}", response_model=AdminTaskResponse)
def migration_export_status(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    migration: Annotated[MigrationService, Depends(get_migration_service)],
) -> dict:
    return migration.export_task_status(task_id)



@router.post("/api/admin/migration/import/start")
async def start_migration_import(
    _: Annotated[CurrentUser, Depends(require_user)],
    migration: Annotated[MigrationService, Depends(get_migration_service)],
    mode: str = Form("merge"),
    confirmed: bool = Form(False),
    file: UploadFile = File(...),
) -> dict:
    content = await file.read()
    return migration.start_import_task(content, filename=file.filename or "migration.tar.gz", mode=mode, confirmed=confirmed, run_inline=False)



@router.get("/api/admin/migration/import/status/{task_id}", response_model=AdminTaskResponse)
def migration_import_status(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    migration: Annotated[MigrationService, Depends(get_migration_service)],
) -> dict:
    return migration.import_task_status(task_id)



@router.post("/api/admin/migration/import")
async def import_migration(
    _: Annotated[CurrentUser, Depends(require_user)],
    migration: Annotated[MigrationService, Depends(get_migration_service)],
    mode: str = Form("merge"),
    confirmed: bool = Form(False),
    file: UploadFile = File(...),
) -> dict:
    return await migration.restore_upload(file, mode=mode, confirmed=confirmed)



@router.get("/api/admin/migration/health", response_model=MigrationHealthResponse)
def migration_health(
    _: Annotated[CurrentUser, Depends(require_user)],
    migration: Annotated[MigrationService, Depends(get_migration_service)],
) -> dict:
    health = migration.health_check()
    return {
        "checks": {
            "sqlite": bool(health["sqlite"]["exists"]),
            "prometheus": bool(health["prometheus"]["exists"]),
            "prometheus_history": bool(health["prometheus"]["block_count"]),
        },
        "message": health["message"],
        "sqlite": health["sqlite"],
        "prometheus": health["prometheus"],
    }



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
) -> dict:
    return cleanup.cleanup_artifacts()



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
) -> dict:
    return cleanup.cleanup_unused_images()



@router.post("/api/admin/system/restart")
def restart_system_services(
    _: Annotated[CurrentUser, Depends(require_user)],
    system: Annotated[SystemControlService, Depends(get_system_control_service)],
) -> dict:
    return system.restart_data_services()



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


