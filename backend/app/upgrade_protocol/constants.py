from __future__ import annotations


RUNNER_PROTOCOL_VERSION = 1
TASK_SCHEMA_VERSION = 2

RUNNER_CAPABILITIES = frozenset(
    {
        "backup.v1",
        "image.v1",
        "filesystem.v1",
        "files.v1",
        "compose.v1",
        "compose.project.v1",
        "script.sandbox.v1",
        "health.v1",
        "task.recovery.v1",
        "runner.handoff.v1",
        "rollback.v1",
    }
)

LEGACY_CAPABILITY_ALIASES = {
    "backup.create": "backup.v1",
    "image.load": "image.v1",
    "filesystem.prepare": "filesystem.v1",
    "files.sync": "files.v1",
    "compose.override": "compose.v1",
    "compose.apply": "compose.v1",
    "compose.project_migrate.v1": "compose.project.v1",
    "health.http": "health.v1",
    "health.prometheus": "health.v1",
    "task.migrate_runtime_state": "task.recovery.v1",
    "task.sync_runtime_state": "task.recovery.v1",
    "post_upgrade.schedule_cleanup": "task.recovery.v1",
    "post_upgrade.schedule_collection": "task.recovery.v1",
    "post_cleanup.precheck_target_health": "health.v1",
    "runner.handoff_target_runtime": "runner.handoff.v1",
    "runner.schedule_target_runtime_handoff": "runner.handoff.v1",
    "runner.stop_legacy_runtime": "runner.handoff.v1",
    "compose.stop_legacy_project": "compose.v1",
    "network.remove_legacy": "compose.project.v1",
    "filesystem.cleanup_legacy_paths": "filesystem.v1",
    "filesystem.cleanup_target_app_residuals": "filesystem.v1",
    "post_cleanup.verify": "health.v1",
    "legacy.cleanup": "task.recovery.v1",
    "checkpoint.write": "task.recovery.v1",
    "rollback.restore": "rollback.v1",
}

ACTION_CAPABILITIES = {
    "backup.create": "backup.v1",
    "image.load": "image.v1",
    "filesystem.prepare": "filesystem.v1",
    "files.sync": "files.v1",
    "compose.override": "compose.v1",
    "compose.apply": "compose.v1",
    "compose.project_migrate": "compose.project.v1",
    "script.run_sandboxed": "script.sandbox.v1",
    "health.http": "health.v1",
    "health.prometheus": "health.v1",
    "task.migrate_runtime_state": "task.recovery.v1",
    "task.sync_runtime_state": "task.recovery.v1",
    "post_upgrade.schedule_cleanup": "task.recovery.v1",
    "post_upgrade.schedule_collection": "task.recovery.v1",
    "post_cleanup.precheck_target_health": "health.v1",
    "runner.handoff_target_runtime": "runner.handoff.v1",
    "runner.schedule_target_runtime_handoff": "runner.handoff.v1",
    "runner.stop_legacy_runtime": "runner.handoff.v1",
    "compose.stop_legacy_project": "compose.v1",
    "network.remove_legacy": "compose.project.v1",
    "filesystem.cleanup_legacy_paths": "filesystem.v1",
    "filesystem.cleanup_target_app_residuals": "filesystem.v1",
    "post_cleanup.verify": "health.v1",
    "legacy.cleanup": "task.recovery.v1",
    "checkpoint.write": "task.recovery.v1",
    "rollback.restore": "rollback.v1",
}


# ── 动作级 runner 支持表（49-50，2026-09-27） ────────────────────────────────
# 能力级（capabilities）无法区分「同版本不同能力」的 runner：已发布 v0.3.1 声明 task.recovery.v1，
# 却不实现 post_upgrade.schedule_collection，导致升级在 cutover 之后才失败。
# 因此预检查增加动作级比对：升级计划的每个动作必须被当前 runner 支持。
#
# 发行版 v0.3.1 = Release 资产 smartx-upgrade-runner-v0.3.1.tar.gz（SHA d10e15cf…），
# 2026-09-27 在 10.20.11.12 容器内实测：25 个动作、actions.py md5 573dd04b3618d2066b0326c2fd183c8d。
RELEASED_RUNNER_ACTIONS = frozenset(
    {
        "backup.create",
        "checkpoint.write",
        "compose.apply",
        "compose.override",
        "compose.project_migrate",
        "compose.stop_legacy_project",
        "files.sync",
        "filesystem.cleanup_legacy_paths",
        "filesystem.cleanup_target_app_residuals",
        "filesystem.prepare",
        "health.http",
        "health.prometheus",
        "image.load",
        "legacy.cleanup",
        "network.remove_legacy",
        "post_cleanup.precheck_target_health",
        "post_cleanup.verify",
        "post_upgrade.schedule_cleanup",
        "rollback.restore",
        "runner.handoff_target_runtime",
        "runner.schedule_target_runtime_handoff",
        "runner.stop_legacy_runtime",
        "script.run_sandboxed",
        "task.migrate_runtime_state",
        "task.sync_runtime_state",
    }
)


def current_runner_actions() -> frozenset[str]:
    """当前仓库 runner 的动作集（= v0.3.3，随 RUNNER_VERSION 一起 bump）。"""
    try:
        from app.upgrade_runner.actions import default_handlers

        return frozenset(default_handlers())
    except Exception:  # pragma: no cover - 兜底：拿不到就按已发布线保守判定
        return RELEASED_RUNNER_ACTIONS


def _version_key(version: str) -> tuple[int, ...]:
    raw = str(version or "").strip()
    if raw.startswith("v"):
        raw = raw[1:]
    parts: list[int] = []
    for chunk in raw.split("."):
        digits = ""
        for char in chunk:
            if char.isdigit():
                digits += char
            else:
                break
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def runner_supported_actions(version: str) -> frozenset[str] | None:
    """按 runner 版本返回其支持的动作集；无法判定（更旧或空版本）返回 None。

    - 精确命中已发布线 → 用该版本的发行动作集；
    - 高于已发布线（依赖 AGENTS §8 的 bump 纪律）→ 视为当前仓库动作集；
    - 更旧/未知 → None（调用方应判定为不支持并提示先做组件升级）。
    """
    key = str(version or "").strip()
    if not key:
        return None
    if key == "v0.3.1":
        return RELEASED_RUNNER_ACTIONS
    released_max = max(_version_key(item) for item in ("v0.3.1",))
    if _version_key(key) > released_max:
        return current_runner_actions()
    return None
