from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.v2.api import router
from app.v2.config import settings_from_environment
from app.v2.database import V2Database


def create_app() -> FastAPI:
    settings = settings_from_environment()
    app = FastAPI(title="SmartX HCI Capacity Insight v2", version=settings.app_version)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.on_event("startup")
    async def startup() -> None:
        V2Database(settings).initialize()

    return app


app = create_app()
