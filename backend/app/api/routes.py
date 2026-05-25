import asyncio
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response

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
from app.services.dashboard import dashboard_summary, latest_report, vm_list, vm_trend
from app.services.prometheus import latest_metrics_text
from app.services.report_export import DOCX_MEDIA_TYPE, XLSX_MEDIA_TYPE, build_report_docx, build_report_xlsx
from app.services.towers import create_tower, delete_tower, get_tower, list_towers, update_cluster as save_cluster, update_tower, upsert_clusters
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
async def report(tower_id: int | None = None, cluster_id: str | None = None, period_days: int = 30, _: dict = Depends(current_user)) -> dict:
    return await latest_report(tower_id=tower_id, cluster_id=cluster_id, period_days=period_days)


@router.get("/api/reports/export/word")
async def export_report_word(tower_id: int | None = None, cluster_id: str | None = None, period_days: int = 30, _: dict = Depends(current_user)) -> Response:
    content, filename = await build_report_docx(tower_id=tower_id, cluster_id=cluster_id, period_days=period_days)
    return _download_response(content, filename, DOCX_MEDIA_TYPE)


@router.get("/api/reports/export/excel")
async def export_report_excel(tower_id: int | None = None, cluster_id: str | None = None, period_days: int = 30, _: dict = Depends(current_user)) -> Response:
    content, filename = await build_report_xlsx(tower_id=tower_id, cluster_id=cluster_id, period_days=period_days)
    return _download_response(content, filename, XLSX_MEDIA_TYPE)


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
