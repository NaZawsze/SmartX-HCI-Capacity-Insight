from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.v2.auth.service import AuthService, CurrentUser
from app.v2.config import V2Settings, settings_from_environment
from app.v2.database import V2Database
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


def get_v2_settings() -> V2Settings:
    return settings_from_environment()


def get_v2_database(settings: Annotated[V2Settings, Depends(get_v2_settings)]) -> V2Database:
    return V2Database(settings)


def get_auth_service(
    database: Annotated[V2Database, Depends(get_v2_database)],
    settings: Annotated[V2Settings, Depends(get_v2_settings)],
) -> AuthService:
    return AuthService(database, settings)


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
