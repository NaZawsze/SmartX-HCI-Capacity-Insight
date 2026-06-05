from __future__ import annotations

from dataclasses import dataclass

from app.v2.config import V2Settings
from app.v2.database import V2Database
from app.v2.metrics.prometheus import PrometheusService


@dataclass(frozen=True)
class HealthResult:
    ok: bool
    version: str
    runner_version: str
    checks: dict[str, bool]


def check_health(settings: V2Settings, database: V2Database, prometheus=None) -> HealthResult:
    checks = {
        "directories": all(directory.exists() and directory.is_dir() for directory in settings.required_directories()),
        "database": False,
        "prometheus": False,
    }
    try:
        with database.connection() as conn:
            conn.execute("SELECT 1").fetchone()
        checks["database"] = True
    except Exception:
        checks["database"] = False
    prometheus_service = prometheus or PrometheusService(settings.prometheus_url)
    try:
        checks["prometheus"] = bool(prometheus_service.health().ok)
    finally:
        close = getattr(prometheus_service, "close", None)
        if callable(close):
            close()
    return HealthResult(
        ok=all(checks.values()),
        version=settings.app_version,
        runner_version=settings.runner_version,
        checks=checks,
    )
