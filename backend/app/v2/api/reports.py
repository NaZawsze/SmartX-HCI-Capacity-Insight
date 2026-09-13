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

@router.get("/api/reports/latest", response_model=ReportResponse)
def latest_report(
    _: Annotated[CurrentUser, Depends(require_user)],
    reports: Annotated[ReportService, Depends(get_report_service)],
    tower_id: Optional[int] = None,
    cluster_id: Optional[str] = None,
    period_days: int = 30,
    chart_days: int = 365,
) -> dict:
    if cluster_id and tower_id is None:
        raise HTTPException(status_code=400, detail="cluster_id requires tower_id.")
    return reports.latest_report(tower_id=tower_id, cluster_id=cluster_id, period_days=period_days, chart_days=chart_days)



@router.get("/api/reports/export/word")
def export_report_word(
    _: Annotated[CurrentUser, Depends(require_user)],
    reports: Annotated[ReportService, Depends(get_report_service)],
    settings: Annotated[V2Settings, Depends(get_v2_settings)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
    tower_id: Optional[int] = None,
    cluster_id: Optional[str] = None,
    period_days: int = 30,
) -> Response:
    if cluster_id and tower_id is None:
        raise HTTPException(status_code=400, detail="cluster_id requires tower_id.")
    report = reports.latest_report(tower_id=tower_id, cluster_id=cluster_id, period_days=period_days)
    content, filename, path, download_url = build_report_docx(report, settings, period_days=period_days)
    record_export_task(tasks, filename, path, download_url, "Word")
    return download_response(content, filename, DOCX_MEDIA_TYPE, path=path, download_url=download_url)



@router.get("/api/reports/export/excel")
def export_report_excel(
    _: Annotated[CurrentUser, Depends(require_user)],
    reports: Annotated[ReportService, Depends(get_report_service)],
    settings: Annotated[V2Settings, Depends(get_v2_settings)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
    tower_id: Optional[int] = None,
    cluster_id: Optional[str] = None,
    period_days: int = 30,
) -> Response:
    if cluster_id and tower_id is None:
        raise HTTPException(status_code=400, detail="cluster_id requires tower_id.")
    report = reports.latest_report(tower_id=tower_id, cluster_id=cluster_id, period_days=period_days)
    content, filename, path, download_url = build_report_xlsx(report, settings, period_days=period_days)
    record_export_task(tasks, filename, path, download_url, "Excel")
    return download_response(content, filename, XLSX_MEDIA_TYPE, path=path, download_url=download_url)



@router.post("/api/reports/export/bundle")
def export_report_bundle(
    _: Annotated[CurrentUser, Depends(require_user)],
    reports: Annotated[ReportService, Depends(get_report_service)],
    settings: Annotated[V2Settings, Depends(get_v2_settings)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
    tower_id: Optional[int] = None,
    cluster_id: Optional[str] = None,
    period_days: int = 30,
    task_id: Optional[str] = None,
) -> dict:
    if cluster_id and tower_id is None:
        raise HTTPException(status_code=400, detail="cluster_id requires tower_id.")
    report = reports.latest_report(tower_id=tower_id, cluster_id=cluster_id, period_days=period_days)
    _, word_filename, word_path, word_url = build_report_docx(report, settings, period_days=period_days)
    _, excel_filename, excel_path, excel_url = build_report_xlsx(report, settings, period_days=period_days)
    files = [
        {"label": "Word", "filename": word_filename, "url": word_url, "path": str(word_path)},
        {"label": "Excel", "filename": excel_filename, "url": excel_url, "path": str(excel_path)},
    ]
    task_id = record_export_bundle_task(tasks, files, task_id=task_id)
    return {
        "task_id": task_id,
        "status": "success",
        "files": files,
        "links": files,
        "message": "Word 和 Excel 报表已生成",
    }


