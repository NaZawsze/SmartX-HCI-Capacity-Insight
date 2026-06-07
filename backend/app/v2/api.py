from __future__ import annotations

from pathlib import Path
from secrets import token_hex
from typing import Annotated, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

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
    clusters: list[ClusterResponse]


class TowerTestResponse(BaseModel):
    ok: bool
    message: str
    clusters: list[ClusterResponse]


class CollectionRunResponse(BaseModel):
    run_id: int
    status: str
    message: str


class VmTrendResponse(BaseModel):
    tower_id: int
    cluster_id: str
    vm_id: str
    vm_name: str
    points: list[dict]


def get_v2_settings() -> V2Settings:
    return settings_from_environment()


def get_v2_database(settings: Annotated[V2Settings, Depends(get_v2_settings)]) -> V2Database:
    return V2Database(settings)


def get_auth_service(
    database: Annotated[V2Database, Depends(get_v2_database)],
    settings: Annotated[V2Settings, Depends(get_v2_settings)],
) -> AuthService:
    return AuthService(database, settings)


def get_inventory_service(
    database: Annotated[V2Database, Depends(get_v2_database)],
    settings: Annotated[V2Settings, Depends(get_v2_settings)],
) -> InventoryService:
    return InventoryService(database, settings)


def get_cloudtower_service(
    database: Annotated[V2Database, Depends(get_v2_database)],
    settings: Annotated[V2Settings, Depends(get_v2_settings)],
) -> CloudTowerService:
    return CloudTowerService(database, settings)


def get_dashboard_service(
    database: Annotated[V2Database, Depends(get_v2_database)],
    settings: Annotated[V2Settings, Depends(get_v2_settings)],
) -> DashboardService:
    return DashboardService(database, settings)


def get_vm_service(
    database: Annotated[V2Database, Depends(get_v2_database)],
    settings: Annotated[V2Settings, Depends(get_v2_settings)],
) -> VmService:
    return VmService(database, settings)


def get_report_service(
    database: Annotated[V2Database, Depends(get_v2_database)],
    settings: Annotated[V2Settings, Depends(get_v2_settings)],
) -> ReportService:
    return ReportService(database, settings)


def get_task_service(database: Annotated[V2Database, Depends(get_v2_database)]) -> TaskService:
    return TaskService(database)


def get_migration_service(
    database: Annotated[V2Database, Depends(get_v2_database)],
    settings: Annotated[V2Settings, Depends(get_v2_settings)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
) -> MigrationService:
    return MigrationService(database, settings, tasks)


def get_cleanup_service(
    settings: Annotated[V2Settings, Depends(get_v2_settings)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
) -> CleanupService:
    return CleanupService(settings, tasks)


def get_system_control_service() -> SystemControlService:
    return SystemControlService()


def get_upgrade_service(
    settings: Annotated[V2Settings, Depends(get_v2_settings)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
) -> UpgradeService:
    return UpgradeService(settings, tasks)


def get_collection_service(
    database: Annotated[V2Database, Depends(get_v2_database)],
    settings: Annotated[V2Settings, Depends(get_v2_settings)],
    cloudtower: Annotated[CloudTowerService, Depends(get_cloudtower_service)],
) -> CollectionService:
    return CollectionService(database, settings, cloudtower_client=cloudtower)


def require_user(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(bearer)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录。")
    user = auth.current_user(credentials.credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录。")
    return user


def tower_response(tower) -> TowerResponse:
    return TowerResponse(
        id=tower.id,
        name=tower.name,
        base_url=tower.base_url,
        username=tower.username,
        verify_tls=tower.verify_tls,
        enabled=tower.enabled,
        clusters=[ClusterResponse(cluster_id=cluster.cluster_id, name=cluster.name, enabled=cluster.enabled) for cluster in tower.clusters],
    )


def cluster_response(cluster) -> ClusterResponse:
    return ClusterResponse(cluster_id=cluster.cluster_id, name=cluster.name, enabled=cluster.enabled)


def cluster_input_from_any(cluster) -> ClusterInput:
    if isinstance(cluster, ClusterInput):
        return cluster
    if isinstance(cluster, dict):
        return ClusterInput(
            cluster_id=str(cluster.get("cluster_id") or cluster.get("id") or ""),
            name=str(cluster.get("name") or cluster.get("cluster_name") or cluster.get("cluster_id") or cluster.get("id") or ""),
            enabled=bool(cluster.get("enabled", True)),
        )
    return ClusterInput(cluster_id=str(cluster.cluster_id), name=str(cluster.name), enabled=bool(getattr(cluster, "enabled", True)))


@router.post("/api/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, auth: Annotated[AuthService, Depends(get_auth_service)]) -> TokenResponse:
    result = auth.login(payload.username, payload.password)
    if result is None:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    return TokenResponse(access_token=result.access_token, token_type=result.token_type, username=result.username)


@router.get("/api/me", response_model=UserResponse)
def me(user: Annotated[CurrentUser, Depends(require_user)]) -> UserResponse:
    return UserResponse(username=user.username, is_admin=user.is_admin)


@router.put("/api/me/password")
def change_password(
    payload: PasswordChangeRequest,
    user: Annotated[CurrentUser, Depends(require_user)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict[str, bool]:
    if payload.new_password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="两次输入的新密码不一致。")
    if not auth.change_password(user.username, payload.current_password, payload.new_password):
        raise HTTPException(status_code=400, detail="当前密码不正确。")
    return {"ok": True}


@router.get("/api/towers", response_model=list[TowerResponse])
def list_towers(
    _: Annotated[CurrentUser, Depends(require_user)],
    inventory: Annotated[InventoryService, Depends(get_inventory_service)],
) -> list[TowerResponse]:
    return [tower_response(tower) for tower in inventory.list_towers()]


@router.post("/api/towers", response_model=TowerResponse)
def create_tower(
    payload: TowerPayload,
    _: Annotated[CurrentUser, Depends(require_user)],
    inventory: Annotated[InventoryService, Depends(get_inventory_service)],
) -> TowerResponse:
    tower = inventory.create_tower(
        TowerInput(
            name=payload.name,
            base_url=payload.base_url,
            username=payload.username,
            password=payload.password,
            api_token=payload.api_token,
            verify_tls=payload.verify_tls,
            enabled=payload.enabled,
        )
    )
    return tower_response(tower)


@router.put("/api/towers/{tower_id}", response_model=TowerResponse)
def update_tower(
    tower_id: int,
    payload: TowerPayload,
    _: Annotated[CurrentUser, Depends(require_user)],
    inventory: Annotated[InventoryService, Depends(get_inventory_service)],
) -> TowerResponse:
    try:
        return tower_response(
            inventory.update_tower(
                tower_id,
                TowerInput(
                    name=payload.name,
                    base_url=payload.base_url,
                    username=payload.username,
                    password=payload.password,
                    api_token=payload.api_token,
                    verify_tls=payload.verify_tls,
                    enabled=payload.enabled,
                ),
            )
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Tower not found.") from None


@router.delete("/api/towers/{tower_id}")
def delete_tower(
    tower_id: int,
    _: Annotated[CurrentUser, Depends(require_user)],
    inventory: Annotated[InventoryService, Depends(get_inventory_service)],
) -> dict[str, bool]:
    if not inventory.delete_tower(tower_id):
        raise HTTPException(status_code=404, detail="Tower not found.")
    return {"ok": True}


@router.post("/api/towers/{tower_id}/clusters/sync", response_model=list[ClusterResponse])
def sync_clusters(
    tower_id: int,
    payload: list[ClusterPayload],
    _: Annotated[CurrentUser, Depends(require_user)],
    inventory: Annotated[InventoryService, Depends(get_inventory_service)],
) -> list[ClusterResponse]:
    try:
        clusters = inventory.sync_clusters(
            tower_id,
            [ClusterInput(cluster_id=cluster.cluster_id, name=cluster.name, enabled=cluster.enabled) for cluster in payload],
        )
        return [cluster_response(cluster) for cluster in clusters]
    except KeyError:
        raise HTTPException(status_code=404, detail="Tower not found.") from None


@router.post("/api/towers/{tower_id}/test", response_model=TowerTestResponse)
def test_tower(
    tower_id: int,
    _: Annotated[CurrentUser, Depends(require_user)],
    inventory: Annotated[InventoryService, Depends(get_inventory_service)],
    cloudtower: Annotated[CloudTowerService, Depends(get_cloudtower_service)],
) -> TowerTestResponse:
    try:
        cluster_inputs = [cluster_input_from_any(cluster) for cluster in cloudtower.test_connection(tower_id)]
        clusters = inventory.sync_clusters(tower_id, cluster_inputs)
        return TowerTestResponse(ok=True, message=f"连接成功，发现 {len(clusters)} 个集群。", clusters=[cluster_response(cluster) for cluster in clusters])
    except KeyError:
        raise HTTPException(status_code=404, detail="Tower not found.") from None
    except Exception as exc:  # noqa: BLE001 - UI needs a concise connection summary.
        message = inventory.mask_secret_material(tower_id, str(exc))
        return TowerTestResponse(ok=False, message=message, clusters=[])


@router.put("/api/towers/{tower_id}/clusters/{cluster_id}", response_model=ClusterResponse)
def update_cluster(
    tower_id: int,
    cluster_id: str,
    payload: ClusterUpdatePayload,
    _: Annotated[CurrentUser, Depends(require_user)],
    inventory: Annotated[InventoryService, Depends(get_inventory_service)],
) -> ClusterResponse:
    try:
        cluster = inventory.update_cluster(tower_id, cluster_id, enabled=payload.enabled, name=payload.name)
        return cluster_response(cluster)
    except KeyError:
        raise HTTPException(status_code=404, detail="Cluster not found.") from None


@router.post("/api/collection/run", response_model=CollectionRunResponse)
def run_collection(
    _: Annotated[CurrentUser, Depends(require_user)],
    collection: Annotated[CollectionService, Depends(get_collection_service)],
) -> CollectionRunResponse:
    result = collection.run_manual_collection()
    return CollectionRunResponse(run_id=result.run_id, status=result.status, message=result.message)


@router.get("/api/collection/runs")
def collection_runs(
    _: Annotated[CurrentUser, Depends(require_user)],
    collection: Annotated[CollectionService, Depends(get_collection_service)],
    limit: int = 30,
) -> list[dict]:
    return collection.list_runs(limit=limit)


@router.get("/api/collection/runs/{run_id}")
def collection_run_detail(
    run_id: int,
    _: Annotated[CurrentUser, Depends(require_user)],
    collection: Annotated[CollectionService, Depends(get_collection_service)],
) -> dict:
    result = collection.run_detail(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="采集记录不存在。")
    return result


@router.get("/api/dashboard/summary")
def dashboard_summary(
    _: Annotated[CurrentUser, Depends(require_user)],
    dashboard: Annotated[DashboardService, Depends(get_dashboard_service)],
    tower_id: Optional[int] = None,
    cluster_id: Optional[str] = None,
) -> dict:
    if cluster_id and tower_id is None:
        raise HTTPException(status_code=400, detail="cluster_id requires tower_id.")
    return dashboard.summary(tower_id=tower_id, cluster_id=cluster_id)


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


@router.get("/api/vms/{vm_id}")
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


@router.get("/api/vms/{vm_id}/volumes")
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


@router.get("/api/vm-volumes")
def vm_volumes_all(
    _: Annotated[CurrentUser, Depends(require_user)],
    vms: Annotated[VmService, Depends(get_vm_service)],
    tower_id: Optional[int] = None,
    cluster_id: Optional[str] = None,
) -> list[dict]:
    if cluster_id and tower_id is None:
        raise HTTPException(status_code=400, detail="cluster_id requires tower_id.")
    return vms.all_volumes(tower_id=tower_id, cluster_id=cluster_id)


@router.get("/api/reports/latest")
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
        raise HTTPException(status_code=404, detail="导出文件不存在。")
    return FileResponse(path, filename=Path(filename).name)


@router.get("/api/admin/migration/export")
def export_migration(
    _: Annotated[CurrentUser, Depends(require_user)],
    migration: Annotated[MigrationService, Depends(get_migration_service)],
) -> Response:
    content, filename, path, download_url = migration.build_export_archive()
    return download_response(content, filename, ARCHIVE_MEDIA_TYPE, path=path, download_url=download_url)


@router.post("/api/admin/migration/export/start")
def start_migration_export(
    _: Annotated[CurrentUser, Depends(require_user)],
    migration: Annotated[MigrationService, Depends(get_migration_service)],
) -> dict:
    return migration.start_export_task()


@router.get("/api/admin/migration/export/status/{task_id}")
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


@router.get("/api/admin/migration/import/status/{task_id}")
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


@router.get("/api/admin/migration/health")
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


@router.get("/api/tasks")
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


@router.delete("/api/tasks/{task_id}")
def delete_inactive_task(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
) -> dict[str, bool | str]:
    if not tasks.delete_inactive(task_id):
        raise HTTPException(status_code=400, detail="只能手动清除已完成、失败或已取消的任务。")
    return {"ok": True, "task_id": task_id}


@router.get("/api/admin/system/cleanup-artifacts/scan")
def scan_cleanup_artifacts(
    _: Annotated[CurrentUser, Depends(require_user)],
    cleanup: Annotated[CleanupService, Depends(get_cleanup_service)],
) -> dict:
    return cleanup.scan_artifacts()


@router.get("/api/admin/system/local-storage")
def local_storage_usage(
    _: Annotated[CurrentUser, Depends(require_user)],
    cleanup: Annotated[CleanupService, Depends(get_cleanup_service)],
) -> dict:
    return cleanup.local_storage_usage()


@router.get("/api/admin/system/sqlite-vacuum/scan")
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


@router.post("/api/admin/system/cleanup-artifacts")
def cleanup_artifacts(
    _: Annotated[CurrentUser, Depends(require_user)],
    cleanup: Annotated[CleanupService, Depends(get_cleanup_service)],
) -> dict:
    return cleanup.cleanup_artifacts()


@router.get("/api/admin/system/cleanup-images/scan")
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


@router.post("/api/admin/upgrade/cancel/{task_id}")
def cancel_upgrade_package(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.cancel(task_id)


@router.get("/api/admin/upgrade/status/{task_id}")
def upgrade_status(
    task_id: str,
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.status(task_id)


@router.get("/api/admin/upgrade/history")
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


@router.get("/api/admin/upgrade/version")
def upgrade_version(
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.version()


@router.get("/api/admin/upgrade/verification")
def upgrade_verification(
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.verification()


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


@router.get("/api/admin/component-upgrade/status/{task_id}")
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


@router.get("/api/admin/component-upgrade/history")
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


@router.get("/api/admin/component-upgrade/version")
def component_upgrade_version(
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.component_version()


@router.get("/api/admin/component-upgrade/components")
def component_upgrade_components(
    _: Annotated[CurrentUser, Depends(require_user)],
    upgrade: Annotated[UpgradeService, Depends(get_upgrade_service)],
) -> dict:
    return upgrade.component_catalog()


@router.get("/api/system/health")
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
