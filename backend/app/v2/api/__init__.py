from fastapi import APIRouter

from app.v2.api import admin, auth, collection, dashboard, reports, system, tasks, towers, vms
from app.v2.api.deps import (
    get_auth_service,
    get_cleanup_service,
    get_cloudtower_service,
    get_collection_service,
    get_dashboard_service,
    get_inventory_service,
    get_migration_service,
    get_report_service,
    get_system_control_service,
    get_task_service,
    get_upgrade_service,
    get_v2_database,
    get_v2_settings,
    get_vm_service,
    require_user,
)

router = APIRouter()
router.include_router(auth.router)
router.include_router(towers.router)
router.include_router(dashboard.router)
router.include_router(vms.router)
router.include_router(reports.router)
router.include_router(collection.router)
router.include_router(tasks.router)
router.include_router(system.router)
router.include_router(admin.router)
