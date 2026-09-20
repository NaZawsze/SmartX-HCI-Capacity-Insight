from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from app.v2.auth.service import CurrentUser
from fastapi.responses import FileResponse

from app.v2.migration.service import ARCHIVE_MEDIA_TYPE, MigrationService

from app.v2.api.deps import get_migration_service, require_user
from app.v2.api.models import AdminTaskResponse, MigrationHealthResponse
from app.v2.api.system import download_response

router = APIRouter()


@router.get("/api/admin/migration/export")
def export_migration(
    _: Annotated[CurrentUser, Depends(require_user)],
    migration: Annotated[MigrationService, Depends(get_migration_service)],
) -> Response:
    content, filename, path, download_url = migration.build_export_archive()
    return download_response(content, filename, ARCHIVE_MEDIA_TYPE, path=path, download_url=download_url)


@router.get("/api/admin/migration/config/export")
def export_config_migration(
    _: Annotated[CurrentUser, Depends(require_user)],
    migration: Annotated[MigrationService, Depends(get_migration_service)],
) -> Response:
    content, filename, path, download_url = migration.build_config_export_archive()
    return download_response(content, filename, ARCHIVE_MEDIA_TYPE, path=path, download_url=download_url)


@router.post("/api/admin/migration/export/start")
def start_migration_export(
    _: Annotated[CurrentUser, Depends(require_user)],
    migration: Annotated[MigrationService, Depends(get_migration_service)],
) -> dict:
    return migration.start_export_task()


@router.get("/api/admin/migration/export/status/{task_id}", response_model=AdminTaskResponse)
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


@router.get("/api/admin/migration/import/status/{task_id}", response_model=AdminTaskResponse)
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


@router.get("/api/admin/migration/health", response_model=MigrationHealthResponse)
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


@router.get("/api/admin/migration/env-file")
def download_current_env_file(
    _: Annotated[CurrentUser, Depends(require_user)],
    migration: Annotated[MigrationService, Depends(get_migration_service)],
) -> FileResponse:
    """下载当前 project/.env（管理员显式动作）；恢复历史导出包时按需与包配对使用。"""
    env_path = migration.settings.env_file_path
    if not env_path.is_file():
        raise HTTPException(status_code=404, detail="未找到 project/.env 文件。")
    return FileResponse(env_path, filename="project.env")
