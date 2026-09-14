from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.v2.auth.service import CurrentUser
from app.v2.config import V2Settings

from app.v2.api.deps import get_v2_settings, require_user

router = APIRouter()


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
        raise HTTPException(status_code=404, detail="导出文件已失效，请重新生成。")
    return FileResponse(path, filename=Path(filename).name)
