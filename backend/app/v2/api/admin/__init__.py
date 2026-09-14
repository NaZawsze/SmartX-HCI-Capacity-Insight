"""Admin domain routers (split from the original admin.py).

Aggregates the per-domain sub-routers; the public ``router`` keeps the
same paths so ``from app.v2.api import admin`` + ``admin.router`` work
unchanged.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.security import HTTPBearer

from .exports import router as exports_router
from .migration import router as migration_router
from .system_admin import router as system_admin_router
from .upgrade import router as upgrade_router

router = APIRouter()
bearer = HTTPBearer(auto_error=False)
router.include_router(exports_router)
router.include_router(migration_router)
router.include_router(system_admin_router)
router.include_router(upgrade_router)
