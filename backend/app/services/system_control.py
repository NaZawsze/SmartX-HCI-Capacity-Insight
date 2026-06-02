from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException


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
