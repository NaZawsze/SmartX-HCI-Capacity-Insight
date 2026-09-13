from __future__ import annotations

from typing import Annotated, Optional, Union

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from app.v2.config import V2Settings
from app.v2.database import V2Database

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



@router.get("/api/vm-volumes", response_model=list[VmVolumeResponse])
def vm_volumes_all(
    _: Annotated[CurrentUser, Depends(require_user)],
    vms: Annotated[VmService, Depends(get_vm_service)],
    tower_id: Optional[int] = None,
    cluster_id: Optional[str] = None,
) -> list[dict]:
    if cluster_id and tower_id is None:
        raise HTTPException(status_code=400, detail="cluster_id requires tower_id.")
    return vms.all_volumes(tower_id=tower_id, cluster_id=cluster_id)


