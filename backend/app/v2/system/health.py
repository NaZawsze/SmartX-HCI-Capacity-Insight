from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.v2.config import V2Settings
from app.v2.database import V2Database
from app.v2.metrics.prometheus import PrometheusService


RUNNER_HEARTBEAT_STALE_SECONDS = 30
RUNNER_NOT_DETECTED = "未检测到 runner"


@dataclass(frozen=True)
class HealthResult:
    ok: bool
    version: str
    runner_version: str
    checks: dict[str, bool]


def _directory_ready(directory: Path) -> bool:
    if not directory.exists() or not directory.is_dir():
        return False
    marker = directory / ".smartx-healthcheck"
    try:
        marker.write_text("ok", encoding="utf-8")
        marker.unlink()
        return True
    except Exception:
        return False


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            try:
                parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _active_runner_version(settings: V2Settings, database: V2Database) -> str:
    try:
        with database.connection() as conn:
            row = conn.execute("SELECT runner_version, heartbeat_at, updated_at FROM upgrade_runner_state WHERE id = 1").fetchone()
    except Exception:
        row = None
    if row:
        version = str(row["runner_version"] if hasattr(row, "keys") else row[0]).strip()
        heartbeat_at = row["heartbeat_at"] if hasattr(row, "keys") else row[1]
        updated_at = row["updated_at"] if hasattr(row, "keys") else row[2]
        heartbeat = _parse_datetime(heartbeat_at or updated_at)
        if version and heartbeat and datetime.now(timezone.utc) - heartbeat <= timedelta(seconds=RUNNER_HEARTBEAT_STALE_SECONDS):
            return version
    return RUNNER_NOT_DETECTED


def check_health(settings: V2Settings, database: V2Database, prometheus=None) -> HealthResult:
    checks = {
        "directories": all(_directory_ready(directory) for directory in settings.required_directories()),
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
        runner_version=_active_runner_version(settings, database),
        checks=checks,
    )
