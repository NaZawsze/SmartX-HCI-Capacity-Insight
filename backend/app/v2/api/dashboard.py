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

@router.get("/api/dashboard/summary", response_model=DashboardSummaryResponse)
def dashboard_summary(
    _: Annotated[CurrentUser, Depends(require_user)],
    dashboard: Annotated[DashboardService, Depends(get_dashboard_service)],
    tower_id: Optional[int] = None,
    cluster_id: Optional[str] = None,
) -> dict:
    if cluster_id and tower_id is None:
        raise HTTPException(status_code=400, detail="cluster_id requires tower_id.")
    return dashboard.summary(tower_id=tower_id, cluster_id=cluster_id)


