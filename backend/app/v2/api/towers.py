from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.v2.auth.service import CurrentUser
from app.v2.api.deps import get_cloudtower_service, get_inventory_service, require_user
from app.v2.api.models import (
    ClusterPayload,
    ClusterResponse,
    ClusterUpdatePayload,
    TowerCollectionStatus,
    TowerPayload,
    TowerResponse,
    TowerTestPayload,
    TowerTestResponse,
)
from app.v2.inventory.models import ClusterInput
from app.v2.inventory.service import InventoryService
from app.v2.cloudtower.service import CloudTowerService

def tower_last_collection(inventory: InventoryService, tower_id: int) -> TowerCollectionStatus | None:
    import json as _json

    with inventory.database.connection() as conn:
        rows = conn.execute(
            """SELECT success_targets_json, failed_targets_json, status, finished_at, started_at
               FROM collection_runs ORDER BY id DESC LIMIT 20"""
        ).fetchall()
    for row in rows:
        try:
            success = _json.loads(row["success_targets_json"] or "[]")
            failed = _json.loads(row["failed_targets_json"] or "[]")
        except (TypeError, ValueError):
            continue
        finished = row["finished_at"] or row["started_at"]
        if any(int(item.get("tower_id") or -1) == int(tower_id) for item in success if isinstance(item, dict)):
            return TowerCollectionStatus(status="success", finished_at=finished)
        if any(int(item.get("tower_id") or -1) == int(tower_id) for item in failed if isinstance(item, dict)):
            return TowerCollectionStatus(status="failed", finished_at=finished)
    return None


def tower_response(tower, last_collection: TowerCollectionStatus | None = None) -> TowerResponse:
    return TowerResponse(
        id=tower.id,
        name=tower.name,
        base_url=tower.base_url,
        username=tower.username,
        verify_tls=tower.verify_tls,
        enabled=tower.enabled,
        collection_hour=tower.collection_hour,
        collection_minute=tower.collection_minute,
        collection_interval_minutes=tower.collection_interval_minutes,
        collection_mode=tower.collection_mode,
        collection_retry_enabled=tower.collection_retry_enabled,
        collection_retry_interval_minutes=tower.collection_retry_interval_minutes,
        collection_retry_max_attempts=tower.collection_retry_max_attempts,
        clusters=[ClusterResponse(cluster_id=cluster.cluster_id, name=cluster.name, enabled=cluster.enabled) for cluster in tower.clusters],
        last_collection=last_collection,
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



router = APIRouter()

@router.get("/api/towers", response_model=list[TowerResponse])
def list_towers(
    _: Annotated[CurrentUser, Depends(require_user)],
    inventory: Annotated[InventoryService, Depends(get_inventory_service)],
) -> list[TowerResponse]:
    towers = inventory.list_towers()
    return [tower_response(tower, tower_last_collection(inventory, tower.id)) for tower in towers]



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
            collection_hour=payload.collection_hour,
            collection_minute=payload.collection_minute,
            collection_interval_minutes=payload.collection_interval_minutes,
            collection_mode=payload.collection_mode,
            collection_retry_enabled=payload.collection_retry_enabled,
            collection_retry_interval_minutes=payload.collection_retry_interval_minutes,
            collection_retry_max_attempts=payload.collection_retry_max_attempts,
        )
    )
    return tower_response(tower, tower_last_collection(inventory, tower.id))



@router.put("/api/towers/{tower_id}", response_model=TowerResponse)
def update_tower(
    tower_id: int,
    payload: TowerPayload,
    _: Annotated[CurrentUser, Depends(require_user)],
    inventory: Annotated[InventoryService, Depends(get_inventory_service)],
) -> TowerResponse:
    try:
        updated = inventory.update_tower(
                tower_id,
                TowerInput(
                    name=payload.name,
                    base_url=payload.base_url,
                    username=payload.username,
                    password=payload.password,
                    api_token=payload.api_token,
                    verify_tls=payload.verify_tls,
                    enabled=payload.enabled,
                    collection_hour=payload.collection_hour,
                    collection_minute=payload.collection_minute,
                    collection_interval_minutes=payload.collection_interval_minutes,
                    collection_mode=payload.collection_mode,
                    collection_retry_enabled=payload.collection_retry_enabled,
                    collection_retry_interval_minutes=payload.collection_retry_interval_minutes,
                    collection_retry_max_attempts=payload.collection_retry_max_attempts,
                ),
            )
        return tower_response(updated, tower_last_collection(inventory, updated.id))
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



@router.post("/api/towers/test", response_model=TowerTestResponse)
def test_tower_params(
    payload: TowerTestPayload,
    _: Annotated[CurrentUser, Depends(require_user)],
    cloudtower: Annotated[CloudTowerService, Depends(get_cloudtower_service)],
) -> TowerTestResponse:
    if not payload.base_url:
        raise HTTPException(status_code=422, detail="base_url is required.")
    if not payload.api_token and not (payload.username and payload.password):
        return TowerTestResponse(ok=False, message="请填写用户名+密码或 API Token。", clusters=[])
    try:
        cluster_inputs = cloudtower.test_connection_params(
            base_url=payload.base_url,
            username=payload.username,
            password=payload.password,
            api_token=payload.api_token,
            verify_tls=payload.verify_tls,
        )
    except Exception as exc:  # noqa: BLE001 - 连接失败要返回原因而不是 500
        return TowerTestResponse(ok=False, message=str(exc)[:300], clusters=[])
    clusters = [cluster_response(cluster_input_from_any(cluster)) for cluster in cluster_inputs]
    return TowerTestResponse(ok=True, message=f"连接成功，发现 {len(clusters)} 个集群。", clusters=clusters)



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


