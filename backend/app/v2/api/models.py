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


router = APIRouter()
bearer = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class UserResponse(BaseModel):
    username: str
    is_admin: bool


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1)
    confirm_password: str = Field(min_length=1)


class ClusterPayload(BaseModel):
    cluster_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    enabled: bool = True


class ClusterUpdatePayload(BaseModel):
    enabled: Optional[bool] = None
    name: Optional[str] = Field(default=None, min_length=1)


class TowerPayload(BaseModel):
    name: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    username: Optional[str] = None
    password: Optional[str] = None
    api_token: Optional[str] = None
    verify_tls: bool = True
    enabled: bool = True
    collection_hour: int = Field(default=2, ge=0, le=23)
    collection_minute: int = Field(default=10, ge=0, le=59)
    collection_interval_minutes: int = Field(default=60, ge=0, le=10080)
    collection_mode: str = Field(default="interval", pattern="^(interval|daily)$")
    collection_retry_enabled: bool = True
    collection_retry_interval_minutes: int = Field(default=15, ge=1, le=1440)
    collection_retry_max_attempts: int = Field(default=3, ge=0, le=10)


class ClusterResponse(BaseModel):
    cluster_id: str
    name: str
    enabled: bool


class TowerResponse(BaseModel):
    id: int
    name: str
    base_url: str
    username: Optional[str]
    verify_tls: bool
    enabled: bool
    collection_hour: int
    collection_minute: int
    collection_interval_minutes: int
    collection_mode: str
    collection_retry_enabled: bool
    collection_retry_interval_minutes: int
    collection_retry_max_attempts: int
    clusters: list[ClusterResponse]
    last_collection: Optional[TowerCollectionStatus] = None


class TowerTestPayload(BaseModel):
    base_url: str
    username: Optional[str] = None
    password: Optional[str] = None
    api_token: Optional[str] = None
    verify_tls: bool = True


class TowerCollectionStatus(BaseModel):
    status: str
    finished_at: Optional[str] = None


class TowerTestResponse(BaseModel):
    ok: bool
    message: str
    clusters: list[ClusterResponse]


class CollectionRunResponse(BaseModel):
    run_id: int
    status: str
    message: str
    task_id: Optional[str] = None


class CollectionRunRequest(BaseModel):
    task_id: Optional[str] = None


class CollectionRunDetailResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: int
    status: str
    message: Optional[str] = None
    trigger: Optional[str] = None
    cycle_id: Optional[str] = None
    attempt: int = 0
    max_attempts: int = 0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    success_targets: list[dict] = []
    failed_targets: list[dict] = []
    published_metrics_targets: list[dict] = []


class TaskResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    task_id: Optional[str] = None
    type: Optional[str] = None
    kind: Optional[str] = None
    title: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[int] = None
    message: Optional[str] = None
    detail: Optional[str] = None
    severity: Optional[str] = None
    unhandled: Optional[bool] = None
    clearable: Optional[bool] = None
    seen_at: Optional[str] = None
    acknowledged_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    finished_at: Optional[str] = None
    links: list[dict] = []
    logs: list[str] = []
    steps: list[dict] = []


class SystemHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    ok: bool
    version: str
    runner_version: str
    checks: dict


class VmTrendResponse(BaseModel):
    tower_id: int
    cluster_id: str
    vm_id: str
    vm_name: str
    points: list[dict]
    latest_success_at: Optional[str] = None
    latest_collection_status: str = "unknown"
    has_collection_gap: bool = False
    gap_dates: list[str] = []
    data_freshness: str = "fresh"


class TaskSeenRequest(BaseModel):
    task_ids: list[str] = Field(default_factory=list)


class SqliteBackupDeleteRequest(BaseModel):
    filenames: list[str] = Field(default_factory=list)


class CleanupArtifactsRequest(BaseModel):
    keep_recent_upgrades: int = Field(default=0, ge=0, le=100)


class CleanupImagesRequest(BaseModel):
    image_ids: list[str] = Field(default_factory=list)


class EnvFileDownloadRequest(BaseModel):
    password: str = ""




# ---- Dashboard summary response models（49-14 批次 2；extra=allow 过渡期保证零字段丢失）----


class DashboardScopeModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    tower_id: Optional[int] = None
    cluster_id: Optional[str] = None
    cluster_enabled: Optional[bool] = None


class DashboardTotalsModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    towers: int = 0
    clusters: int = 0
    vms: int = 0


class DashboardStorageModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    used_bytes: float = 0.0
    total_bytes: float = 0.0
    used_ratio: float = 0.0


class DashboardCollectionModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    last_success_at: Optional[str] = None
    message: Optional[str] = None
    status: Optional[str] = None


class RiskThresholdsModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    warning_ratio: float = 0.75
    danger_ratio: float = 0.80


class RiskClusterModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    tower_id: Optional[Union[str, int]] = None
    cluster_id: Optional[str] = None
    cluster: Optional[str] = None
    used_bytes: Optional[float] = None
    total_bytes: Optional[float] = None
    used_ratio: Optional[float] = None
    forecast_90d: Optional[float] = None
    exhaustion_days: Optional[float] = None
    exhaustion_days_30d: Optional[float] = None
    spike_detected: Optional[bool] = None
    risk_level: Optional[str] = None


class TopClusterModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    tower_id: Optional[Union[str, int]] = None
    tower: Optional[str] = None
    cluster_id: Optional[str] = None
    cluster: Optional[str] = None
    used_bytes: Optional[float] = None
    total_bytes: Optional[float] = None
    used_ratio: Optional[float] = None
    top_growth_vms: list[dict] = []


class CapacityRiskModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    level: str = "normal"
    title: str = ""
    message: Optional[str] = None
    description: str = ""
    cluster_count: int = 0
    warning_count: int = 0
    danger_count: int = 0
    evaluated_at: Optional[str] = None
    thresholds: Optional[RiskThresholdsModel] = None
    risk_clusters: list[RiskClusterModel] = []
    top_clusters: list[TopClusterModel] = []


class DashboardClusterModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    tower_id: int = 0
    cluster_id: str = ""
    name: str = ""
    used_bytes: float = 0.0
    total_bytes: float = 0.0
    used_ratio: float = 0.0


class DashboardTowerModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: int = 0
    name: str = ""
    base_url: str = ""
    username: Optional[str] = None
    verify_tls: bool = True
    enabled: bool = True
    collection_hour: int = 2
    collection_minute: int = 10
    collection_retry_enabled: bool = True
    collection_retry_interval_minutes: int = 15
    collection_retry_max_attempts: int = 3
    clusters: list[ClusterResponse] = []


class DashboardVmItemModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    tower_id: Optional[Union[str, int]] = None
    cluster_id: Optional[str] = None
    vm_id: Optional[str] = None
    vm_name: Optional[str] = None
    current_bytes: Optional[float] = None
    previous_bytes: Optional[float] = None
    growth_amount: Optional[float] = None
    growth_ratio: Optional[float] = None


class DashboardSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    scope: DashboardScopeModel = DashboardScopeModel()
    capacity_risk: CapacityRiskModel = CapacityRiskModel()
    totals: DashboardTotalsModel = DashboardTotalsModel()
    storage: DashboardStorageModel = DashboardStorageModel()
    collection: Optional[DashboardCollectionModel] = None
    day_fastest_growing_vms: list[DashboardVmItemModel] = []
    day_new_vms: list[DashboardVmItemModel] = []
    clusters: list[DashboardClusterModel] = []
    towers: list[DashboardTowerModel] = []




# ---- Batch 3: vms / volumes / reports response models（49-14 批次 3，extra=allow 过渡）----


class VmDetailResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    vm_id: Optional[str] = None
    name: Optional[str] = None
    tower_id: Optional[Union[str, int]] = None
    cluster_id: Optional[str] = None
    used_bytes: Optional[float] = None
    volumes: list[dict] = []


class VmVolumeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    volume_id: Optional[str] = None
    name: Optional[str] = None
    path: Optional[str] = None
    size_bytes: Optional[float] = None
    used_bytes: Optional[float] = None
    storage_policy: Optional[str] = None
    replica_num: Optional[int] = None
    thin_provision: Optional[bool] = None
    ec_k: Optional[int] = None
    ec_m: Optional[int] = None


class VmVolumePageResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    volumes: list[VmVolumeResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 200


class VmUsageItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    tower_id: int
    cluster_id: str
    vm_id: str
    used_bytes: float = 0
    provisioned_bytes: float = 0


class VmUsageSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    usages: list[VmUsageItem] = Field(default_factory=list)


class ReportScopeModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    tower_id: Optional[int] = None
    cluster_id: Optional[str] = None


class ForecastModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: Optional[str] = None
    slope_per_day: Optional[float] = None
    current: Optional[float] = None
    forecast_30d: Optional[float] = None
    forecast_60d: Optional[float] = None
    forecast_90d: Optional[float] = None
    forecast_180d: Optional[float] = None
    exhaustion_days: Optional[float] = None
    exhaustion_date: Optional[str] = None
    exhaustion_days_30d: Optional[float] = None
    smoothed_slope_per_day: Optional[float] = None
    recent_day_delta: Optional[float] = None
    spike_detected: Optional[bool] = None
    band_half_width_now: Optional[float] = None
    band_half_width_per_day: Optional[float] = None


class ReportClusterModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    labels: dict = {}
    forecast: ForecastModel = ForecastModel()
    points: list[list] = []
    total: Optional[float] = None
    warning: Optional[float] = None


class ReportGrowthItemModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    labels: dict = {}
    forecast: ForecastModel = ForecastModel()
    growth_amount: Optional[float] = None
    growth_ratio: Optional[float] = None
    previous_value: Optional[float] = None
    period_days: Optional[float] = None
    sample_span_days: Optional[float] = None
    window_start_at: Optional[str] = None
    window_end_at: Optional[str] = None


class ClusterGrowthRateModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    per_day: Optional[float] = None
    per_month: Optional[float] = None
    per_quarter: Optional[float] = None
    day_sample_sufficient: Optional[bool] = None
    month_sample_sufficient: Optional[bool] = None
    quarter_sample_sufficient: Optional[bool] = None
    day_window_days: Optional[int] = None
    month_window_days: Optional[int] = None
    quarter_window_days: Optional[int] = None


class DataQualityModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: Optional[str] = None
    sample_sufficient: Optional[bool] = None
    sqlite_vm_count: Optional[int] = None
    prometheus_vm_series_count: Optional[int] = None
    sqlite_cluster_count: Optional[int] = None
    prometheus_cluster_series_count: Optional[int] = None
    latest_collection_status: Optional[str] = None
    latest_success_at: Optional[str] = None
    latest_prometheus_sample_at: Optional[str] = None
    missing_collection_dates: list[str] = []
    incomplete_clusters: list[dict] = []
    messages: list[str] = []
    freshness: Optional[dict] = None


class ReportResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    scope: ReportScopeModel = ReportScopeModel()
    clusters: list[ReportClusterModel] = []
    window_fastest_growing_vms: list[ReportGrowthItemModel] = []
    fastest_growing_vms: list[ReportGrowthItemModel] = []
    day_fastest_growing_vms: list[ReportGrowthItemModel] = []
    month_fastest_growing_vms: list[ReportGrowthItemModel] = []
    day_new_vms: list[ReportGrowthItemModel] = []
    month_new_vms: list[ReportGrowthItemModel] = []
    cluster_growth_rate_per_day: Optional[float] = None
    cluster_growth_rate: Optional[ClusterGrowthRateModel] = None
    window_days: Optional[int] = None
    chart_days: Optional[int] = None
    growth_rate_window_days: Optional[int] = None
    forecast_days: Optional[int] = None
    period_window: Optional[dict] = None
    data_window: Optional[dict] = None
    data_quality: Optional[DataQualityModel] = None
    timezone: Optional[str] = None




# ---- Batch 4: admin read response models（49-14 批次 4，extra=allow 过渡）----


class UpgradeVerificationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    app_version: Optional[str] = None
    runner_version: Optional[str] = None
    prometheus_version: Optional[str] = None
    compose_file: Optional[str] = None
    compose_project: Optional[str] = None
    service_status_error: Optional[str] = None
    services: list[dict] = []
    package: Optional[dict] = None


class UpgradeVersionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    version: Optional[str] = None


class ComponentVersionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    component: Optional[str] = None
    version: Optional[str] = None


class MigrationHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    checks: dict = {}
    message: Optional[str] = None
    prometheus: Optional[dict] = None
    sqlite: Optional[dict] = None


class LocalStorageResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    path: Optional[str] = None
    total_bytes: Optional[float] = None
    used_bytes: Optional[float] = None
    free_bytes: Optional[float] = None
    total_label: Optional[str] = None
    used_label: Optional[str] = None
    free_label: Optional[str] = None
    used_ratio: Optional[float] = None
    free_ratio: Optional[float] = None


class CleanupScanResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    ok: Optional[bool] = None
    message: Optional[str] = None
    image_count: Optional[int] = None
    images: list[dict] = []
    space_reclaimable: Optional[float] = None
    space_reclaimable_label: Optional[str] = None


class ComponentCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    components: list[dict] = []


class AdminTaskResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[int] = None
    message: Optional[str] = None
    detail: Optional[str] = None
    severity: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    finished_at: Optional[str] = None


