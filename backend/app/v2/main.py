from __future__ import annotations

import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.v2.api import router
from app.v2.auto_backup import start_auto_backup_daemon
from app.v2.config import settings_from_environment
from app.v2.database import V2Database
from app.v2.freshness import start_freshness_probe_daemon


def create_app() -> FastAPI:
    settings = settings_from_environment()
    app = FastAPI(title="SmartX HCI Capacity Insight v2", version=settings.app_version)
    # 默认同源部署（前端经 nginx 代理 /api/），无需 CORS；跨域部署时用 SMARTX_CORS_ORIGINS 显式配置白名单
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(router)
    probe_stop_event: threading.Event | None = None
    backup_stop_event: threading.Event | None = None

    @app.on_event("startup")
    async def startup() -> None:
        nonlocal probe_stop_event, backup_stop_event
        V2Database(settings).initialize()
        # 采集新鲜度探针：web-api 侧跨容器互检，collector-worker 全挂时任务中心告警
        probe_stop_event = start_freshness_probe_daemon(V2Database(settings))
        # 数据库自动备份：SQLite 快照与 .env 成对保管，见 auto_backup.py
        backup_stop_event = start_auto_backup_daemon(V2Database(settings), settings)

    @app.on_event("shutdown")
    async def shutdown() -> None:
        if probe_stop_event is not None:
            probe_stop_event.set()
        if backup_stop_event is not None:
            backup_stop_event.set()

    return app


app = create_app()
