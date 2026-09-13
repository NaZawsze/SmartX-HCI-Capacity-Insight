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
    VmVolumeResponse,
)

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


@router.get("/api/tasks", response_model=list[TaskResponse])
def list_tasks(
    _: Annotated[CurrentUser, Depends(require_user)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
) -> list[dict]:
    return tasks.list_tasks()



@router.delete("/api/tasks/finished")
def clear_finished_tasks(
    _: Annotated[CurrentUser, Depends(require_user)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
) -> dict[str, int]:
    return {"deleted": tasks.clear_finished()}



@router.post("/api/tasks/seen")
def mark_tasks_seen(
    payload: TaskSeenRequest,
    _: Annotated[CurrentUser, Depends(require_user)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
) -> dict[str, int]:
    return {"updated": tasks.mark_info_seen(payload.task_ids)}



@router.post("/api/tasks/{task_id}/ack")
def acknowledge_task(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
) -> dict:
    try:
        return tasks.acknowledge(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在。") from None



@router.delete("/api/tasks/clearable")
def clear_clearable_tasks(
    _: Annotated[CurrentUser, Depends(require_user)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
) -> dict[str, int]:
    return {"deleted": tasks.clear_clearable()}



@router.delete("/api/tasks/{task_id}")
def delete_inactive_task(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
) -> dict[str, bool | str]:
    if not tasks.delete_inactive(task_id):
        raise HTTPException(status_code=400, detail="只能手动清除已完成、失败或已取消的任务。")
    return {"ok": True, "task_id": task_id}


