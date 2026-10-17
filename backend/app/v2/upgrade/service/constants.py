from __future__ import annotations

import os

MANIFEST_NAME = "manifest.json"
SENSITIVE_NAMES = {".env", "smartx.db"}
SENSITIVE_PARTS = {"backups", "exports", "compose-runtime", "password", "token", "secret"}
PLATFORM_SERVICES = {"web-api", "collector-worker", "frontend"}
PLATFORM_COMPOSE_SERVICES = PLATFORM_SERVICES | {"prometheus"}
OBSERVABILITY_SERVICES = {"prometheus"}
RUNNER_SERVICES = {"upgrade-runner"}
#: runner 心跳的新鲜窗口（秒）。
#: 30s 对「平台升级重启 runner」这个场景太紧：重启后两条心跳通道都可能短暂不新鲜，
#: 预检查就会报「未检测到心跳」而拒绝升级（2026-10-15/16 全链实测：同一脚本、同一时刻，
#: `.12` 过、`.14` 连续两次失败，重试 90s 仍不过）。90s 覆盖一次重启 + 两个轮询周期，
#: 并允许现场用环境变量覆盖（CI/慢机器）。
RUNNER_HEARTBEAT_STALE_SECONDS = int(os.environ.get("SMARTX_RUNNER_HEARTBEAT_STALE_SECONDS", "90"))
RUNNER_NOT_DETECTED = "未检测到 runner"
