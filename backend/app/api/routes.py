import asyncio
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from app.api.deps import current_user
from app.collector.collector import Collector, latest_all_vm_volumes, latest_vm_volumes, running_run
from app.core.security import create_token, verify_password
from app.db import get_conn, row_to_dict
from app.models import (
    CollectionRunResponse,
    ClusterUpdate,
    LoginRequest,
    PasswordChangeRequest,
    TestConnectionResponse,
    TokenResponse,
    TowerCreate,
    TowerResponse,
    TowerUpdate,
    UserResponse,
    VmTrendResponse,
    VmVolumeResponse,
    VmVolumeSetResponse,
)
from app.services.cloudtower import CloudTowerClient, normalize_tower
from app.services.data_migration import ARCHIVE_MEDIA_TYPE, build_migration_archive, restore_migration_archive
from app.services.dashboard import dashboard_summary, latest_report, vm_list, vm_trend
from app.services.prometheus import latest_metrics_text
from app.services.report_export import DOCX_MEDIA_TYPE, XLSX_MEDIA_TYPE, build_report_docx, build_report_xlsx
from app.services.system_control import cleanup_unused_images, scan_unused_images, schedule_service_restart
from app.services.towers import create_tower, delete_tower, get_tower, list_towers, update_cluster as save_cluster, update_tower, upsert_clusters
from app.services.upgrade import (
    component_upgrade_history,
    component_upgrade_status,
    delete_component_package,
    delete_upgrade_package,
    precheck_component_upgrade,
    precheck_upgrade,
    rollback_upgrade,
    start_component_upgrade,
    start_upgrade,
    upgrade_history,
    upgrade_status,
    upload_component_package,
    upload_upgrade_package,
    runner_version,
)
from app.services.users import change_password


router = APIRouter()


@router.post("/api/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    with get_conn() as conn:
        user = row_to_dict(conn.execute("SELECT * FROM users WHERE username = ?", (payload.username,)).fetchone())
    if user is None or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    return TokenResponse(access_token=create_token(payload.username), username=payload.username)


@router.get("/api/me", response_model=UserResponse)
def me(user: dict = Depends(current_user)) -> UserResponse:
    return UserResponse(username=user["username"], is_admin=bool(user["is_admin"]))


@router.put("/api/me/password")
def update_password(payload: PasswordChangeRequest, user: dict = Depends(current_user)) -> dict[str, bool]:
    if payload.new_password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="两次输入的新密码不一致。")
    if not change_password(user["username"], payload.current_password, payload.new_password):
        raise HTTPException(status_code=400, detail="当前密码不正确。")
    return {"ok": True}


@router.get("/api/towers", response_model=list[TowerResponse])
def towers(_: dict = Depends(current_user)) -> list[TowerResponse]:
    return list_towers()


@router.post("/api/towers", response_model=TowerResponse)
def add_tower(payload: TowerCreate, _: dict = Depends(current_user)) -> TowerResponse:
    return create_tower(payload)


@router.put("/api/towers/{tower_id}", response_model=TowerResponse)
def edit_tower(tower_id: int, payload: TowerUpdate, _: dict = Depends(current_user)) -> TowerResponse:
    tower = update_tower(tower_id, payload)
    if tower is None:
        raise HTTPException(status_code=404, detail="Tower not found.")
    return tower


@router.delete("/api/towers/{tower_id}")
def remove_tower(tower_id: int, _: dict = Depends(current_user)) -> dict[str, bool]:
    if not delete_tower(tower_id):
        raise HTTPException(status_code=404, detail="Tower not found.")
    return {"ok": True}


@router.post("/api/towers/{tower_id}/test", response_model=TestConnectionResponse)
async def test_tower(tower_id: int, _: dict = Depends(current_user)) -> TestConnectionResponse:
    tower = get_tower(tower_id)
    if tower is None:
        raise HTTPException(status_code=404, detail="Tower not found.")
    try:
        async with CloudTowerClient(normalize_tower(tower)) as client:
            clusters = await client.get_clusters()
        saved = upsert_clusters(tower_id, clusters)
        return TestConnectionResponse(ok=True, message=f"连接成功，发现 {len(saved)} 个集群。", clusters=saved)
    except Exception as exc:  # noqa: BLE001 - expose concise connection failure to UI.
        return TestConnectionResponse(ok=False, message=str(exc), clusters=[])


@router.put("/api/towers/{tower_id}/clusters/{cluster_id}")
def update_cluster(tower_id: int, cluster_id: str, payload: ClusterUpdate, _: dict = Depends(current_user)) -> dict:
    cluster = save_cluster(tower_id, cluster_id, enabled=payload.enabled, name=payload.name)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found.")
    return cluster.model_dump()


@router.post("/api/collection/run", response_model=CollectionRunResponse)
async def run_collection(_: dict = Depends(current_user)) -> CollectionRunResponse:
    running = running_run()
    if running is not None:
        return CollectionRunResponse(
            run_id=running["id"],
            status=running["status"],
            message="采集任务正在运行，请稍后刷新状态。",
        )
    collector = Collector()
    run_id = collector.start_run()
    asyncio.create_task(collector.run_started(run_id))
    return CollectionRunResponse(
        run_id=run_id,
        status="running",
        message="采集任务已开始，页面会自动刷新状态。",
    )


@router.get("/api/dashboard/summary")
async def summary(tower_id: int | None = None, cluster_id: str | None = None, _: dict = Depends(current_user)) -> dict:
    return await dashboard_summary(tower_id=tower_id, cluster_id=cluster_id)


@router.get("/api/vms")
async def vms(tower_id: int | None = None, cluster_id: str | None = None, _: dict = Depends(current_user)) -> list[dict]:
    return await vm_list(tower_id=tower_id, cluster_id=cluster_id)


@router.get("/api/vms/{vm_id}/trend", response_model=VmTrendResponse)
async def trend(
    vm_id: str,
    metric: str = "used",
    days: int = 30,
    tower_id: int | None = None,
    cluster_id: str | None = None,
    _: dict = Depends(current_user),
) -> VmTrendResponse:
    if days not in {7, 14, 30, 90, 180, 365}:
        raise HTTPException(status_code=400, detail="Unsupported trend range.")
    return VmTrendResponse(vm_id=vm_id, metric=metric, points=await vm_trend(vm_id, metric, days, tower_id=tower_id, cluster_id=cluster_id))


@router.get("/api/vms/{vm_id}/volumes", response_model=VmVolumeResponse)
def volumes(vm_id: str, tower_id: int | None = None, cluster_id: str | None = None, _: dict = Depends(current_user)) -> VmVolumeResponse:
    return VmVolumeResponse(vm_id=vm_id, volumes=latest_vm_volumes(vm_id, tower_id=tower_id, cluster_id=cluster_id))


@router.get("/api/vm-volumes", response_model=list[VmVolumeSetResponse])
def all_volumes(tower_id: int | None = None, cluster_id: str | None = None, _: dict = Depends(current_user)) -> list[VmVolumeSetResponse]:
    return [VmVolumeSetResponse(**item) for item in latest_all_vm_volumes(tower_id=tower_id, cluster_id=cluster_id)]


@router.get("/api/reports/latest")
async def report(tower_id: int | None = None, cluster_id: str | None = None, period_days: int = 30, chart_days: int = 365, _: dict = Depends(current_user)) -> dict:
    return await latest_report(tower_id=tower_id, cluster_id=cluster_id, period_days=period_days, chart_days=chart_days)


@router.get("/api/reports/export/word")
async def export_report_word(tower_id: int | None = None, cluster_id: str | None = None, period_days: int = 30, _: dict = Depends(current_user)) -> Response:
    content, filename = await build_report_docx(tower_id=tower_id, cluster_id=cluster_id, period_days=period_days)
    return _download_response(content, filename, DOCX_MEDIA_TYPE)


@router.get("/api/reports/export/excel")
async def export_report_excel(tower_id: int | None = None, cluster_id: str | None = None, period_days: int = 30, _: dict = Depends(current_user)) -> Response:
    content, filename = await build_report_xlsx(tower_id=tower_id, cluster_id=cluster_id, period_days=period_days)
    return _download_response(content, filename, XLSX_MEDIA_TYPE)


@router.get("/api/admin/migration/export")
def export_migration(_: dict = Depends(current_user)) -> Response:
    content, filename = build_migration_archive()
    return _download_response(content, filename, ARCHIVE_MEDIA_TYPE)


@router.post("/api/admin/migration/import")
async def import_migration(
    mode: str = Form("merge"),
    confirmed: bool = Form(False),
    file: UploadFile = File(...),
    _: dict = Depends(current_user),
) -> dict:
    return await restore_migration_archive(file, confirmed=confirmed, mode=mode)


@router.post("/api/admin/system/restart")
def restart_system_services(_: dict = Depends(current_user)) -> dict:
    return schedule_service_restart()


@router.post("/api/admin/system/cleanup-images")
def cleanup_system_images(_: dict = Depends(current_user)) -> dict:
    return cleanup_unused_images()


@router.get("/api/admin/system/cleanup-images/scan")
def scan_system_images(_: dict = Depends(current_user)) -> dict:
    return scan_unused_images()


@router.get("/api/admin/upgrade/version")
def get_upgrade_version(_: dict = Depends(current_user)) -> dict[str, str]:
    from app.core.config import get_settings

    return {"version": get_settings().app_version}


@router.get("/api/admin/component-upgrade/version")
def get_component_upgrade_version(_: dict = Depends(current_user)) -> dict[str, str]:
    return {"component": "upgrade-runner", "version": runner_version()}


@router.post("/api/admin/upgrade/upload")
async def upload_upgrade(file: UploadFile = File(...), _: dict = Depends(current_user)) -> dict:
    return await upload_upgrade_package(file)


@router.post("/api/admin/upgrade/precheck/{task_id}")
def precheck_upgrade_task(task_id: str, _: dict = Depends(current_user)) -> dict:
    return precheck_upgrade(task_id)


@router.post("/api/admin/upgrade/start/{task_id}")
def start_upgrade_task(task_id: str, _: dict = Depends(current_user)) -> dict:
    return start_upgrade(task_id)


@router.get("/api/admin/upgrade/status/{task_id}")
def get_upgrade_status(task_id: str, _: dict = Depends(current_user)) -> dict:
    return upgrade_status(task_id)


@router.post("/api/admin/upgrade/rollback/{task_id}")
def rollback_upgrade_task(task_id: str, _: dict = Depends(current_user)) -> dict:
    return rollback_upgrade(task_id)


@router.delete("/api/admin/upgrade/package/{task_id}")
def delete_upgrade_task(task_id: str, _: dict = Depends(current_user)) -> dict:
    return delete_upgrade_package(task_id)


@router.get("/api/admin/upgrade/history")
def get_upgrade_history(_: dict = Depends(current_user)) -> list[dict]:
    return upgrade_history()


@router.post("/api/admin/component-upgrade/upload")
async def upload_component_upgrade(file: UploadFile = File(...), _: dict = Depends(current_user)) -> dict:
    return await upload_component_package(file)


@router.post("/api/admin/component-upgrade/precheck/{task_id}")
def precheck_component_upgrade_task(task_id: str, _: dict = Depends(current_user)) -> dict:
    return precheck_component_upgrade(task_id)


@router.post("/api/admin/component-upgrade/start/{task_id}")
def start_component_upgrade_task(task_id: str, _: dict = Depends(current_user)) -> dict:
    return start_component_upgrade(task_id)


@router.get("/api/admin/component-upgrade/status/{task_id}")
def get_component_upgrade_status(task_id: str, _: dict = Depends(current_user)) -> dict:
    return component_upgrade_status(task_id)


@router.delete("/api/admin/component-upgrade/package/{task_id}")
def delete_component_upgrade_task(task_id: str, _: dict = Depends(current_user)) -> dict:
    return delete_component_package(task_id)


@router.get("/api/admin/component-upgrade/history")
def get_component_upgrade_history(_: dict = Depends(current_user)) -> list[dict]:
    return component_upgrade_history()


@router.get("/metrics")
def metrics() -> Response:
    return Response(content=latest_metrics_text(), media_type="text/plain; version=0.0.4")


def _download_response(content: bytes, filename: str, media_type: str) -> Response:
    quoted = quote(filename)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={quoted}; filename*=UTF-8''{quoted}"},
    )
