from __future__ import annotations

"""Filesystem helpers for the upgrade service."""

import hashlib
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from ._compat import HTTPException, UploadFile

from .constants import SENSITIVE_NAMES, SENSITIVE_PARTS

def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    try:
        archive.extractall(destination, filter="data")
    except TypeError:  # Python < 3.12 has no extraction filter argument.
        archive.extractall(destination)



def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()



def _backup_existing_project_path(source: Path, backup: Path) -> None:
    if not source.exists() and not source.is_symlink():
        return
    backup.parent.mkdir(parents=True, exist_ok=True)
    _remove_path(backup)
    if source.is_dir() and not source.is_symlink():
        shutil.copytree(source, backup)
        shutil.rmtree(source)
        return
    shutil.copy2(source, backup)
    source.unlink()



def _validate_members(archive: tarfile.TarFile) -> None:
    for member in archive.getmembers():
        path = Path(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise HTTPException(status_code=400, detail="升级包包含非法路径。")
        lower_parts = {part.lower() for part in path.parts}
        if path.name in SENSITIVE_NAMES or any(part in SENSITIVE_PARTS for part in lower_parts):
            raise HTTPException(status_code=400, detail=f"升级包包含敏感路径：{member.name}")



def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()



def _now() -> datetime:
    return datetime.now(timezone.utc)
