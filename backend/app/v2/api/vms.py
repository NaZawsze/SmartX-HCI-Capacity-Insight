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
    VmUsageSummaryResponse,
    VmVolumePageResponse,
    VmVolumeResponse,
)

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


@router.get("/api/vms")
def list_vms(
    _: Annotated[CurrentUser, Depends(require_user)],
    vms: Annotated[VmService, Depends(get_vm_service)],
    tower_id: Optional[int] = None,
    cluster_id: Optional[str] = None,
) -> list[dict]:
    if cluster_id and tower_id is None:
        raise HTTPException(status_code=400, detail="cluster_id requires tower_id.")
    return vms.list_vms(tower_id=tower_id, cluster_id=cluster_id)



@router.get("/api/vms/{vm_id}/trend", response_model=VmTrendResponse)
def vm_trend(
    vm_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    vms: Annotated[VmService, Depends(get_vm_service)],
    tower_id: Optional[int] = None,
    cluster_id: Optional[str] = None,
    days: int = 30,
    period_days: Optional[int] = None,
) -> VmTrendResponse:
    if tower_id is None or not cluster_id:
        raise HTTPException(status_code=400, detail="tower_id and cluster_id are required.")
    days = int(period_days or days)
    if days not in {7, 14, 30, 90, 180, 365}:
        raise HTTPException(status_code=400, detail="Unsupported trend range.")
    return VmTrendResponse(**vms.trend(vm_id=vm_id, tower_id=tower_id, cluster_id=cluster_id, days=days))



@router.get("/api/vms/{vm_id}", response_model=VmDetailResponse)
def vm_detail(
    vm_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    vms: Annotated[VmService, Depends(get_vm_service)],
    tower_id: Optional[int] = None,
    cluster_id: Optional[str] = None,
) -> dict:
    if tower_id is None or not cluster_id:
        raise HTTPException(status_code=400, detail="tower_id and cluster_id are required.")
    return vms.detail(vm_id=vm_id, tower_id=tower_id, cluster_id=cluster_id)



@router.get("/api/vms/{vm_id}/volumes", response_model=list[VmVolumeResponse])
def vm_volumes(
    vm_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    vms: Annotated[VmService, Depends(get_vm_service)],
    tower_id: Optional[int] = None,
    cluster_id: Optional[str] = None,
) -> list[dict]:
    if tower_id is None or not cluster_id:
        raise HTTPException(status_code=400, detail="tower_id and cluster_id are required.")
    return vms.volumes(vm_id=vm_id, tower_id=tower_id, cluster_id=cluster_id)



@router.get("/api/vm-volumes", response_model=Union[list[VmVolumeResponse], VmVolumePageResponse])
def vm_volumes_all(
    _: Annotated[CurrentUser, Depends(require_user)],
    vms: Annotated[VmService, Depends(get_vm_service)],
    tower_id: Optional[int] = None,
    cluster_id: Optional[str] = None,
    page: Optional[int] = None,
    page_size: int = 200,
    sort: Optional[str] = None,
    order: Optional[str] = None,
) -> Union[list[dict], dict]:
    if cluster_id and tower_id is None:
        raise HTTPException(status_code=400, detail="cluster_id requires tower_id.")
    if page is not None and page < 1:
        raise HTTPException(status_code=400, detail="page must be >= 1.")
    if not 1 <= page_size <= 1000:
        raise HTTPException(status_code=400, detail="page_size must be between 1 and 1000.")
    if sort is not None and sort not in {"vm", "used", "occupied"}:
        raise HTTPException(status_code=400, detail="Unsupported volume sort field.")
    if order is not None and order not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="Unsupported volume sort order.")
    return vms.all_volumes(tower_id=tower_id, cluster_id=cluster_id, page=page, page_size=page_size, sort=sort, order=order)


@router.get("/api/vm-volumes/usage-summary", response_model=VmUsageSummaryResponse)
def vm_volumes_usage_summary(
    _: Annotated[CurrentUser, Depends(require_user)],
    vms: Annotated[VmService, Depends(get_vm_service)],
    tower_id: Optional[int] = None,
    cluster_id: Optional[str] = None,
) -> dict:
    if cluster_id and tower_id is None:
        raise HTTPException(status_code=400, detail="cluster_id requires tower_id.")
    return {"usages": vms.usage_summary(tower_id=tower_id, cluster_id=cluster_id)}


