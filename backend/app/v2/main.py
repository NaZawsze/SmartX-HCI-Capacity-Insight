from __future__ import annotations

import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.v2.api import router
from app.v2.config import settings_from_environment
from app.v2.database import DatabaseBusyError, V2Database
from app.v2.freshness import start_freshness_probe_daemon
from app.v2.upgrade.backup_retention import start_backup_cleanup_daemon
from app.v2.upgrade.housekeeping import start_upgrade_housekeeping_daemon
from app.v2.upgrade.settlement import start_settlement_daemon


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

    # US-28：SQLite 写锁窗口（upgrade-runner 组件升级后）内的写操作不再裸 500，
    # 改为 503 + 可读提示，便于运维判断"稍后重试"而不是"系统坏了"。
    @app.exception_handler(DatabaseBusyError)
    async def database_busy_handler(_request, exc: DatabaseBusyError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    probe_stop_event: threading.Event | None = None
    housekeeping_stop_event: threading.Event | None = None
    settlement_stop_event: threading.Event | None = None
    backup_cleanup_stop_event: threading.Event | None = None

    @app.on_event("startup")
    async def startup() -> None:
        nonlocal probe_stop_event, housekeeping_stop_event, settlement_stop_event, backup_cleanup_stop_event
        V2Database(settings).initialize()
        # 采集新鲜度探针：web-api 侧跨容器互检，collector-worker 全挂时任务中心告警
        probe_stop_event = start_freshness_probe_daemon(V2Database(settings))
        # 升级产物清理：按 TTL 清掉从未执行过任务（预检失败/仅上传）的包内容（US-09）
        housekeeping_stop_event = start_upgrade_housekeeping_daemon(settings, V2Database(settings))
        # 升级收尾兜底：补建「已成功但清理任务缺失」的 post-cleanup（US-30）——
        # 否则无人轮询 status 接口时清理任务永不创建，旧环境长期残留而任务仍显示成功
        settlement_stop_event = start_settlement_daemon(settings, V2Database(settings))
        # 升级备份保留（US-31）：备份无人回收会随升级次数线性膨胀，
        # 按 TTL + 保留最近 N 份裁剪，避免磁盘被历史快照吃满
        backup_cleanup_stop_event = start_backup_cleanup_daemon(settings, V2Database(settings))

    @app.on_event("shutdown")
    async def shutdown() -> None:
        if probe_stop_event is not None:
            probe_stop_event.set()
        if housekeeping_stop_event is not None:
            housekeeping_stop_event.set()
        if settlement_stop_event is not None:
            settlement_stop_event.set()
        if backup_cleanup_stop_event is not None:
            backup_cleanup_stop_event.set()

    return app


app = create_app()
