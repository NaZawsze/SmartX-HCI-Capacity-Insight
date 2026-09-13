from __future__ import annotations

from typing import Annotated, Optional, Union

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field

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

@router.get("/api/system/health", response_model=SystemHealthResponse)
def health(
    settings: Annotated[V2Settings, Depends(get_v2_settings)],
    database: Annotated[V2Database, Depends(get_v2_database)],
) -> dict:
    result = check_health(settings, database)
    return {
        "ok": result.ok,
        "version": result.version,
        "runner_version": result.runner_version,
        "checks": result.checks,
    }


def download_response(content: bytes, filename: str, media_type: str, *, path: Path, download_url: str) -> Response:
    quoted = quote(filename)
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename={quoted}; filename*=UTF-8''{quoted}",
            "X-SmartX-Export-Path": str(path),
            "X-SmartX-Export-Url": download_url,
        },
    )


def record_export_task(tasks: TaskService, filename: str, path: Path, download_url: str, label: str) -> None:
    task_id = f"report-{token_hex(8)}"
    tasks.create_task(task_id, TaskType.REPORT, "导出预测报表", status=TaskStatus.SUCCESS, progress=100, message=f"{label} 报表已生成", links=[{"label": label, "filename": filename, "url": download_url, "path": str(path)}])


def record_export_bundle_task(tasks: TaskService, files: list[dict], task_id: Optional[str] = None) -> str:
    task_id = task_id or f"report-{token_hex(8)}"
    tasks.create_task(task_id, TaskType.REPORT, "导出预测报表", status=TaskStatus.SUCCESS, progress=100, message="Word 和 Excel 报表已生成", links=files)
    return task_id

