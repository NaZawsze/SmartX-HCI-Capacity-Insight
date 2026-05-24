from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class LoginRequest(BaseModel):
    username: str
    password: str


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


class TowerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: HttpUrl
    username: str | None = None
    password: str | None = None
    api_token: str | None = None
    verify_tls: bool = True
    enabled: bool = True
    collection_hour: int = Field(default=2, ge=0, le=23)
    collection_minute: int = Field(default=10, ge=0, le=59)


class TowerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: HttpUrl | None = None
    username: str | None = None
    password: str | None = None
    api_token: str | None = None
    verify_tls: bool | None = None
    enabled: bool | None = None
    collection_hour: int | None = Field(default=None, ge=0, le=23)
    collection_minute: int | None = Field(default=None, ge=0, le=59)


class ClusterResponse(BaseModel):
    cluster_id: str
    name: str
    enabled: bool


class ClusterUpdate(BaseModel):
    enabled: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)


class TowerResponse(BaseModel):
    id: int
    name: str
    base_url: str
    username: str | None
    verify_tls: bool
    enabled: bool
    collection_hour: int
    collection_minute: int
    last_error: str | None = None
    clusters: list[ClusterResponse] = []


class TestConnectionResponse(BaseModel):
    ok: bool
    message: str
    clusters: list[ClusterResponse] = []


class CollectionRunResponse(BaseModel):
    run_id: int
    status: str
    message: str


class VmTrendResponse(BaseModel):
    vm_id: str
    metric: str
    points: list[tuple[int, float]]


class VmVolumeResponse(BaseModel):
    vm_id: str
    volumes: list[dict[str, Any]]


class VmVolumeSetResponse(BaseModel):
    tower_id: int
    cluster_id: str
    vm_id: str
    volumes: list[dict[str, Any]]


class ApiEnvelope(BaseModel):
    data: Any
