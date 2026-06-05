from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.v2.auth.service import AuthService, CurrentUser
from app.v2.config import V2Settings, settings_from_environment
from app.v2.database import V2Database
from app.v2.inventory.models import ClusterInput, TowerInput
from app.v2.inventory.service import InventoryService
from app.v2.system.health import check_health


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
        return [ClusterResponse(cluster_id=cluster.cluster_id, name=cluster.name, enabled=cluster.enabled) for cluster in clusters]
    except KeyError:
        raise HTTPException(status_code=404, detail="Tower not found.") from None


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
        return ClusterResponse(cluster_id=cluster.cluster_id, name=cluster.name, enabled=cluster.enabled)
    except KeyError:
        raise HTTPException(status_code=404, detail="Cluster not found.") from None


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
