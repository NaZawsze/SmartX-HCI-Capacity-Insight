from __future__ import annotations

import json
import shutil
import socket
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException

from app.core.config import get_settings


DOCKER_SOCKET = "/var/run/docker.sock"
RESTART_SERVICES = ["collector-worker", "prometheus", "web-api"]


def schedule_service_restart() -> dict[str, Any]:
    try:
        _docker_request("GET", "/_ping")
    except OSError as exc:
        raise HTTPException(status_code=503, detail="当前环境未挂载 Docker 控制接口，无法自动重启服务。") from exc

    thread = threading.Thread(target=_restart_services_later, daemon=True)
    thread.start()
    return {
        "ok": True,
        "services": RESTART_SERVICES,
        "message": "服务重启任务已提交，预计 10-30 秒内完成。页面可能会短暂断开，请稍后刷新。",
    }


def cleanup_unused_images() -> dict[str, Any]:
    try:
        _docker_request("GET", "/_ping")
    except OSError as exc:
        raise HTTPException(status_code=503, detail="当前环境未挂载 Docker 控制接口，无法清理镜像。") from exc

    status, body = _docker_request("POST", "/images/prune?filters=%7B%7D")
    if status >= 300:
        detail = body.decode("utf-8", errors="ignore") or "清理旧版本镜像失败。"
        raise HTTPException(status_code=500, detail=detail)
    payload = json.loads(body.decode("utf-8") or "{}")
    deleted = payload.get("ImagesDeleted") or []
    reclaimed = int(payload.get("SpaceReclaimed") or 0)
    deleted_count = len(deleted)
    return {
        "ok": True,
        "deleted_count": deleted_count,
        "space_reclaimed": reclaimed,
        "message": f"已清理 {deleted_count} 个未使用镜像，释放 {_format_bytes(reclaimed)}。",
    }


def scan_unused_images() -> dict[str, Any]:
    try:
        _docker_request("GET", "/_ping")
    except OSError as exc:
        raise HTTPException(status_code=503, detail="当前环境未挂载 Docker 控制接口，无法扫描镜像。") from exc

    status, body = _docker_request("GET", "/images/json?all=true")
    if status >= 300:
        detail = body.decode("utf-8", errors="ignore") or "扫描 Docker 镜像失败。"
        raise HTTPException(status_code=500, detail=detail)
    images = json.loads(body.decode("utf-8") or "[]")
    used_image_ids = _used_image_ids()
    unused = []
    for image in images:
        image_id = str(image.get("Id") or "")
        if image_id in used_image_ids:
            continue
        size = int(image.get("Size") or 0)
        repo_tags = [tag for tag in image.get("RepoTags") or [] if tag and tag != "<none>:<none>"]
        unused.append(
            {
                "id": image_id,
                "short_id": image_id.replace("sha256:", "")[:12],
                "repo_tags": repo_tags,
                "display_name": repo_tags[0] if repo_tags else image_id.replace("sha256:", "")[:12],
                "size": size,
                "size_label": _format_bytes(size),
            }
        )
    unused.sort(key=lambda item: item["size"], reverse=True)
    total = sum(item["size"] for item in unused)
    return {
        "ok": True,
        "images": unused,
        "image_count": len(unused),
        "space_reclaimable": total,
        "space_reclaimable_label": _format_bytes(total),
        "message": f"发现 {len(unused)} 个未使用镜像，预计可释放 {_format_bytes(total)}。",
    }


def scan_export_artifacts() -> dict[str, Any]:
    categories = _artifact_categories()
    items = [_scan_artifact_category(item) for item in categories]
    total_size = sum(item["size"] for item in items)
    total_count = sum(item["count"] for item in items)
    return {
        "ok": True,
        "items": items,
        "total_count": total_count,
        "total_size": total_size,
        "total_size_label": _format_bytes(total_size),
        "message": f"发现 {total_count} 项可清理文件，预计可释放 {_format_bytes(total_size)}。",
    }


def cleanup_export_artifacts() -> dict[str, Any]:
    before = scan_export_artifacts()
    deleted_count = 0
    deleted_size = 0
    logs: list[str] = []
    for category in before["items"]:
        path = Path(category["path"])
        if not path.exists():
            logs.append(f"跳过 {category['label']}：目录不存在。")
            continue
        for child in list(path.iterdir()):
            if not _can_delete_artifact_child(path, child):
                continue
            size = _path_size(child)
            try:
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
                deleted_count += 1
                deleted_size += size
            except OSError as exc:
                logs.append(f"删除失败 {child.name}：{exc}")
        logs.append(f"已清理 {category['label']}。")
    return {
        "ok": True,
        "deleted_count": deleted_count,
        "space_reclaimed": deleted_size,
        "space_reclaimed_label": _format_bytes(deleted_size),
        "logs": logs,
        "message": f"已清理 {deleted_count} 项文件，释放 {_format_bytes(deleted_size)}。",
    }


def _artifact_categories() -> list[dict[str, Any]]:
    settings = get_settings()
    return [
        {"key": "upgrade_packages", "label": "升级包", "path": settings.upgrade_path, "description": "已上传的平台/组件升级包与解析目录"},
        {"key": "migration_exports", "label": "数据迁移导出", "path": settings.export_path / "migrations", "description": "数据迁移导出留档包"},
        {"key": "report_exports", "label": "报表导出", "path": settings.export_path / "reports", "description": "Word/Excel 报表留档文件"},
        {"key": "migration_tasks", "label": "迁移导出任务记录", "path": settings.export_path / "migration-tasks", "description": "迁移导出后台任务状态文件"},
        {"key": "migration_imports", "label": "数据迁移导入", "path": settings.export_path / "imports", "description": "数据迁移导入上传包、解压目录和任务记录"},
    ]


def _scan_artifact_category(category: dict[str, Any]) -> dict[str, Any]:
    path = Path(category["path"])
    children = [child for child in path.iterdir() if _can_delete_artifact_child(path, child)] if path.exists() else []
    size = sum(_path_size(child) for child in children)
    return {
        "key": category["key"],
        "label": category["label"],
        "description": category["description"],
        "path": str(path),
        "count": len(children),
        "size": size,
        "size_label": _format_bytes(size),
    }


def _can_delete_artifact_child(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    if child.name in {".", "..", ".DS_Store"} or child.name.startswith("._"):
        return False
    return child.exists() or child.is_symlink()


def _path_size(path: Path) -> int:
    try:
        if path.is_file() or path.is_symlink():
            return path.stat().st_size
        return sum(child.stat().st_size for child in path.rglob("*") if child.is_file() or child.is_symlink())
    except OSError:
        return 0


def _restart_services_later() -> None:
    time.sleep(1.0)
    for service in RESTART_SERVICES:
        try:
            container_id = _container_id_for_service(service)
            if container_id:
                _docker_request("POST", f"/containers/{container_id}/restart?t=10")
                time.sleep(1.0)
        except Exception:
            # Restart is a best-effort admin action. The caller already received a response.
            continue


def _container_id_for_service(service: str) -> str | None:
    filters = quote(json.dumps({"label": [f"com.docker.compose.service={service}"]}, separators=(",", ":")), safe="")
    status, body = _docker_request("GET", f"/containers/json?all=true&filters={filters}")
    if status >= 300:
        return None
    containers = json.loads(body.decode("utf-8") or "[]")
    if not containers:
        return None
    return str(containers[0].get("Id") or "") or None


def _used_image_ids() -> set[str]:
    status, body = _docker_request("GET", "/containers/json?all=true")
    if status >= 300:
        return set()
    containers = json.loads(body.decode("utf-8") or "[]")
    return {str(container.get("ImageID") or "") for container in containers if container.get("ImageID")}


def _format_bytes(value: int) -> str:
    size = float(value or 0)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    return f"{size:.0f} {units[index]}" if index < 2 else f"{size:.2f} {units[index]}"


def _docker_request(method: str, path: str) -> tuple[int, bytes]:
    request = f"{method} {path} HTTP/1.1\r\nHost: docker\r\nConnection: close\r\nContent-Length: 0\r\n\r\n".encode("utf-8")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(10)
        client.connect(DOCKER_SOCKET)
        client.sendall(request)
        chunks: list[bytes] = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    response = b"".join(chunks)
    header, _, body = response.partition(b"\r\n\r\n")
    status_line = header.splitlines()[0].decode("latin1") if header else "HTTP/1.1 500"
    try:
        status = int(status_line.split()[1])
    except (IndexError, ValueError):
        status = 500
    return status, _decode_http_body(header, body)


def _decode_http_body(header: bytes, body: bytes) -> bytes:
    header_text = header.decode("latin1", errors="ignore").lower()
    if "transfer-encoding: chunked" not in header_text:
        return body
    decoded = bytearray()
    position = 0
    while position < len(body):
        line_end = body.find(b"\r\n", position)
        if line_end < 0:
            break
        size_text = body[position:line_end].split(b";", 1)[0]
        try:
            chunk_size = int(size_text, 16)
        except ValueError:
            break
        position = line_end + 2
        if chunk_size == 0:
            break
        decoded.extend(body[position:position + chunk_size])
        position += chunk_size + 2
    return bytes(decoded)
