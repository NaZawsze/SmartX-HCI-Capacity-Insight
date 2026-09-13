from __future__ import annotations

MANIFEST_NAME = "manifest.json"
SENSITIVE_NAMES = {".env", "smartx.db"}
SENSITIVE_PARTS = {"backups", "exports", "compose-runtime", "password", "token", "secret"}
PLATFORM_SERVICES = {"web-api", "collector-worker", "frontend"}
PLATFORM_COMPOSE_SERVICES = PLATFORM_SERVICES | {"prometheus"}
OBSERVABILITY_SERVICES = {"prometheus"}
RUNNER_SERVICES = {"upgrade-runner"}
RUNNER_HEARTBEAT_STALE_SECONDS = 30
RUNNER_NOT_DETECTED = "未检测到 runner"
