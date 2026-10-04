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



#: 升级任务目录里**必须保留**的记录文件。定义在此处而非各服务，
#: 使 `delete_package`（intake.py）与 `cleanup_artifacts`（cleanup/service.py）
#: 共用同一份清单——2026-10-04 前两者分叉：前者 rmtree 整个目录连记录一起删，
#: 后者只删体积产物，导致同一问题两条路径做法相反。
UPGRADE_RECORD_FILES = frozenset({"task.json"})

#: 小于该体积的 `.json` 视为运行标记（post-upgrade-cleanup.json /
#: post-upgrade-collection.json 等）而非包产物，清理时保留。
_UPGRADE_MARKER_MAX_BYTES = 64 * 1024


def purge_upgrade_payload(task_dir: Path) -> int:
    """只删升级任务目录里的**体积产物**，保留记录。返回删除条目数。

    用户口径 2026-10-04：「宁留记录不留包」——
    升级中心历史只读 `task.json`（`intake.py::history` 扫 `*/task.json`），
    不读 `package/`；而单个任务的包占 200M~853M，是磁盘堆积的主因。

    保留：`task.json`（历史记录）、`post-upgrade-*.json` 等小标记。
    删除：`package/`（解包副本）、`*.tar.gz` / `*.sha256`（上传的包本体）。

    目录本身保留（`post-cleanup-*` 的 `task.json` 也在同层）。
    """
    if not task_dir.is_dir():
        # 不是升级任务目录（如散落在 upgrades/ 下的单个 .tar.gz 包）→ 整删
        if task_dir.exists():
            task_dir.unlink()
            return 1
        return 0
    removed = 0
    for child in sorted(task_dir.iterdir(), key=lambda c: c.name):
        if child.name in UPGRADE_RECORD_FILES:
            continue
        if (
            child.is_file()
            and child.stat().st_size < _UPGRADE_MARKER_MAX_BYTES
            and child.suffix == ".json"
        ):
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed += 1
    return removed


def upgrade_payload_size(task_dir: Path) -> int:
    """任务目录里**体积产物**占用的字节数（用于回报释放量，不含记录）。

    刻意不按 `st_size` 累加目录项，而是递归 `rglob` 求和——`package/` 是解包后的
    目录树，只看目录本身的大小（通常只有 4 KiB）会严重低估。
    """
    if not task_dir.is_dir():
        try:
            return task_dir.stat().st_size
        except OSError:
            return 0
    total = 0
    for child in task_dir.iterdir():
        if child.name in UPGRADE_RECORD_FILES:
            continue
        if (
            child.is_file()
            and child.stat().st_size < _UPGRADE_MARKER_MAX_BYTES
            and child.suffix == ".json"
        ):
            continue
        if child.is_dir():
            total += sum(f.stat().st_size for f in child.rglob("*") if f.is_file())
        else:
            try:
                total += child.stat().st_size
            except OSError:
                continue
    return total


def has_upgrade_payload(task_dir: Path) -> bool:
    """该任务目录是否还留有体积产物（`package/` 或包本体）。

    供 API 告知前端「记录仍在但包已清理」，避免删包后按钮仍显示、点了没反应。
    """
    if not task_dir.is_dir():
        return False
    if (task_dir / "package").exists():
        return True
    return any(task_dir.glob("*.tar.gz")) or any(task_dir.glob("*.sha256"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()



def _now() -> datetime:
    return datetime.now(timezone.utc)
