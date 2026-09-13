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
    tasks: Annotated[TaskService, Depends(get_task_service)],
) -> CollectionService:
    return CollectionService(database, settings, cloudtower_client=cloudtower, tasks=tasks)


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


