"""升级收尾兜底（US-30）：post-cleanup 不再依赖客户端轮询。

实测缺陷（`.12` task `upgrade-0de5b6ad24d41c56`）：14 个动作全部 succeeded、状态 `success`，
但 legacy 路径 `/data/smartx-capacity-insight-data`、`/prometheus-data`、`/data/upgrades` 至今残留。

代码链条：
    post_upgrade.schedule_cleanup 动作  → 只写标记文件，不建清理任务
    _maybe_schedule_post_upgrade_cleanup()  (execution.py)
        └─ 由 _normalize_completed_runner_task() 调用
            └─ 只在 execution.py:151（status 接口 = 客户端轮询）与 cleanup.py:104 被触发
                └─ worker 侧无任何后台兜底
    ⇒ 没人调用 status 接口，清理任务就永远不会创建，而任务仍显示"成功"。

本模块提供后台兜底：定期扫描「已成功但清理任务缺失」的升级任务并补建，使其不再依赖客户端行为。
只保证 **成功** 升级的收尾；失败态收尾走 US-27 的 `cleanup_required` 提示（不自动执行）。

设计：docs/superpowers/specs/2026-09-28-upgrade-settlement-fallback-design.md
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 300
INTERVAL_ENV = "SMARTX_UPGRADE_SETTLEMENT_INTERVAL_SECONDS"

#: runner 容器 healthcheck 补齐的开关（默认开启；设 0 关闭）。
HEALTHCHECK_RECONCILE_ENV = "SMARTX_RUNNER_HEALTHCHECK_RECONCILE"

#: 补齐用的覆盖文件名（只含 upgrade-runner 的 healthcheck，不动其他配置）。
HEALTHCHECK_OVERRIDE_NAME = "docker-compose.healthcheck-reconcile.yml"

#: 与交付 compose 保持一致的判据：状态文件不存在视为健康（基线 runner 没有看门狗），
#: 存在但超过 90s 未更新才判不健康（#96 语义）。
_HEALTHCHECK_TEST = (
    "f=/data/upgrade-runner-state.json; "
    "[ ! -f $$f ] || test $(( $$(date +%s) - $$(stat -c %Y $$f) )) -lt 90"
)


def _healthcheck_override_candidates(settings: Any) -> list[Path]:
    """可写目录候选：容器内 compose-runtime 挂载点 → data_root 下的 compose-runtime → 项目目录。"""
    candidates = [Path("/data/compose-runtime")]
    data_root = getattr(settings, "data_root", None)
    if data_root:
        candidates.append(Path(data_root) / "compose-runtime")
    project_path = getattr(settings, "project_path", None)
    if project_path:
        candidates.append(Path(project_path))
    return candidates


def _write_healthcheck_override(settings: Any) -> Path | None:
    """写一份只含 runner healthcheck 的 compose 覆盖文件，返回路径（失败返回 None）。

    为什么不直接改项目 compose：项目目录在 web-api 里是**只读挂载**，且遗留布局可能
    仍在用 `docker-compose.release.yml` 这类不含 healthcheck 的老变体（`.12` 实测）。
    用 `-f <现有变体> -f <覆盖>` 叠加，既补上 healthcheck，又不动该变体的其他配置。
    """
    content = (
        "services:\n"
        "  upgrade-runner:\n"
        "    healthcheck:\n"
        f"      test: [\"CMD-SHELL\", \"{_HEALTHCHECK_TEST}\"]\n"
        "      interval: 30s\n"
        "      timeout: 5s\n"
        "      retries: 3\n"
        "      start_period: 60s\n"
    )
    for directory in _healthcheck_override_candidates(settings):
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / HEALTHCHECK_OVERRIDE_NAME
            path.write_text(content, encoding="utf-8")
            return path
        except OSError:
            continue
    return None

# 只有「执行成功」才兜底建清理任务；failed/rolled_back/rollback_failed 属取证链，不动。
SETTLED_STATUSES = frozenset({"success", "succeeded"})


def _read_task(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _needs_settlement(settings: Any, task: dict[str, Any]) -> bool:
    """该任务是否「成功但清理任务缺失」。

    判定与 `_maybe_schedule_post_upgrade_cleanup` 保持一致：manifest 要
    `post_upgrade.create_cleanup_task` 且 `legacy_cleanup` 非空。
    """
    if str(task.get("status") or "") not in SETTLED_STATUSES:
        return False
    manifest = task.get("manifest") or {}
    if not isinstance(manifest, dict):
        return False
    post_upgrade = manifest.get("post_upgrade")
    legacy_cleanup = manifest.get("legacy_cleanup")
    if not (isinstance(post_upgrade, dict) and post_upgrade.get("create_cleanup_task")):
        return False
    if not (isinstance(legacy_cleanup, dict) and legacy_cleanup):
        return False
    task_id = str(task.get("task_id") or "")
    if not task_id:
        return False
    # 清理任务已存在（父任务记录了 id 且目录里有 task.json）→ 不需要补建
    recorded_id = str(task.get("post_upgrade_cleanup_task_id") or "")
    cleanup_id = recorded_id or f"post-cleanup-{task_id}"
    return not (settings.upgrades_dir / cleanup_id / "task.json").is_file()


def scan_missing_settlement(settings: Any) -> list[tuple[str, dict[str, Any]]]:
    """只读扫描：返回 [(task_id, manifest.legacy_cleanup)]，不修改任何东西。"""
    missing: list[tuple[str, dict[str, Any]]] = []
    upgrades_dir = Path(settings.upgrades_dir)
    if not upgrades_dir.is_dir():
        return missing
    for task_file in sorted(upgrades_dir.glob("*/task.json")):
        task = _read_task(task_file)
        if not task:
            continue
        if _needs_settlement(settings, task):
            missing.append((str(task.get("task_id") or task_file.parent.name), task.get("manifest", {}).get("legacy_cleanup") or {}))
    return missing


def _runner_container_name(settings: Any) -> str:
    return f"{getattr(settings, 'compose_project_name', 'smartx-hci-capacity-insight')}-upgrade-runner-1"


def _has_active_upgrade(database: Any) -> bool:
    with database.connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE type = 'upgrade' AND status IN ('running','pending')"
        ).fetchone()
    return bool(row and row[0])


def reconcile_runner_healthcheck_once(settings: Any, database: Any) -> dict[str, Any]:
    """给 runner 容器补上 #96 healthcheck（升级路径「滞后一跳」的兜底）。

    背景：runner 自换时，`compose-runtime/docker-compose.runner-bootstrap.yml` 由**旧** runner
    写入。v0.3.1 的模板没有 healthcheck（#101 才加进模板），于是 v0.3.1→v0.3.2 升级后，
    新 runner 容器继承的是这份无 healthcheck 的 compose —— `docker ps` 永远看不到
    `(healthy)`/`(unhealthy)`，要等到下一次 runner 跳变才恢复。
    实测（`.14`，2026-10-18）：组件升级后 `docker inspect .State.Health` 直接无此键。

    修法：平台在**空闲**时（无 running/pending 升级任务）检查 runner 容器是否缺 healthcheck，
    缺则用**项目 compose**（含 #96 healthcheck）重建该服务。任务已结束，重建不影响执行。
    任何异常都只记日志、不抛——兜底线程必须存活。
    """
    if os.environ.get(HEALTHCHECK_RECONCILE_ENV, "1") == "0":
        return {"skipped": "disabled"}
    try:
        if _has_active_upgrade(database):
            return {"skipped": "active_upgrade"}
    except Exception as exc:  # noqa: BLE001
        return {"skipped": f"db_error: {exc}"}

    container = _runner_container_name(settings)
    try:
        probe = subprocess.run(
            ["docker", "inspect", "--format", "{{if .State.Health}}1{{else}}0{{end}}", container],
            capture_output=True, text=True, timeout=15,
        )
    except Exception as exc:  # noqa: BLE001
        return {"skipped": f"inspect_error: {exc}"}
    if probe.returncode != 0:
        return {"skipped": "container_absent"}
    if probe.stdout.strip() == "1":
        return {"skipped": "already_healthy"}

    project_path = Path(getattr(settings, "project_path"))
    compose_name = str(getattr(settings, "compose_file", "docker-compose.offline.yml"))
    compose_file = project_path / compose_name
    command = [
        "docker", "compose",
        "-p", str(getattr(settings, "compose_project_name", "smartx-hci-capacity-insight")),
        "-f", compose_name,
    ]
    try:
        has_healthcheck = "healthcheck" in compose_file.read_text(encoding="utf-8")
    except OSError as exc:
        return {"skipped": f"compose_unreadable: {exc}"}
    if not has_healthcheck:
        # 遗留布局可能仍指向不含 healthcheck 的老变体（`.12` 实测：docker-compose.release.yml）
        override = _write_healthcheck_override(settings)
        if override is None:
            return {"skipped": "compose_without_healthcheck"}
        command += ["-f", str(override)]
    command += ["up", "-d", "--no-deps", "upgrade-runner"]

    try:
        result = subprocess.run(
            command,
            cwd=str(project_path), capture_output=True, text=True, timeout=180,
        )
    except Exception as exc:  # noqa: BLE001
        return {"skipped": f"compose_error: {exc}"}
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "").strip()[:400]
        logger.warning("runner healthcheck reconcile failed for %s: %s", container, error)
        return {"recreated": False, "error": error}
    logger.warning("runner container recreated to attach #96 healthcheck: %s", container)
    return {"recreated": True}


def ensure_settlement_once(settings: Any, database: Any) -> dict[str, Any]:
    """对漏网任务补建升级后清理任务。单个失败不影响其余；整体幂等。

    同时**事件驱动**地投递升级后采集（US-06）：过去只能靠 worker 每 5 秒扫 `upgrades/*/`
    来发现"该采集了"——事件驱动的事用高频轮询，链路隐蔽、难观测、难关闭。
    这里在守护线程扫到成功任务时顺手投递，5 秒轮询降级为兜底。
    """
    created: list[str] = []
    failed: list[dict[str, str]] = []
    targets = scan_missing_settlement(settings)
    if targets:
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeService

        service = UpgradeService(settings, TaskService(database), project_path=settings.project_path)
        for task_id, legacy_cleanup in targets:
            try:
                # 二次确认（与客户端轮询并发时收敛，避免重复创建）
                current = _read_task(Path(settings.upgrades_dir) / task_id / "task.json")
                if not _needs_settlement(settings, current):
                    continue
                service.create_post_upgrade_cleanup_task(task_id, legacy_cleanup)
                created.append(task_id)
            except Exception as exc:  # noqa: BLE001 - 兜底线程不得因单个任务失败而中断
                logger.warning("post-upgrade settlement failed for %s: %s", task_id, exc)
                failed.append({"task_id": task_id, "error": str(exc)})
        if created:
            # 走到这里说明有升级任务"成功却没清理干净"，属需人工留意的异常，用 warning 才可见
            logger.warning("post-upgrade settlement created cleanup task for: %s", ", ".join(created))

    # US-06：投递升级后采集（幂等；worker 侧仍有兜底轮询）
    try:
        from app.v2.worker import ensure_post_upgrade_collection_for

        dispatched = ensure_post_upgrade_collection_for(settings, database)
        if dispatched:
            logger.info("post-upgrade collection dispatched: %s", dispatched)
    except Exception as exc:  # noqa: BLE001 - 采集投递失败不得影响清理兜底
        logger.warning("post-upgrade collection dispatch failed: %s", exc)

    # #89 自动化：产物已被回收、任务行却停在执行中的升级任务，超时后自动收敛为失败
    converged: list[str] = []
    try:
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeService

        sweep_service = UpgradeService(settings, TaskService(database), project_path=settings.project_path)
        converged = sweep_service.converge_orphan_running_tasks()
    except Exception as exc:  # noqa: BLE001 - 兜底线程不得因单个扫描失败而中断
        logger.warning("orphan running sweep failed: %s", exc)

    # #96 收尾：升级后 runner 容器可能继承「旧 runner 写的、无 healthcheck 的 bootstrap compose」
    reconcile = reconcile_runner_healthcheck_once(settings, database)

    return {"created": created, "failed": failed, "converged": converged, "healthcheck": reconcile}


def _settlement_loop(settings: Any, database: Any, stop_event: threading.Event, interval_seconds: int) -> None:
    # 启动即跑一次：覆盖 web-api 重启后仍未收尾的历史任务
    while not stop_event.is_set():
        try:
            ensure_settlement_once(settings, database)
        except Exception as exc:  # noqa: BLE001 - 守护线程必须存活
            logger.warning("post-upgrade settlement sweep failed: %s", exc)
        stop_event.wait(interval_seconds)


def start_settlement_daemon(
    settings: Any,
    database: Any,
    *,
    interval_seconds: int | None = None,
    stop_event: threading.Event | None = None,
) -> threading.Event | None:
    if interval_seconds is None:
        interval_seconds = getattr(settings, "upgrade_settlement_interval_seconds", DEFAULT_INTERVAL_SECONDS)
    try:
        interval_seconds = int(interval_seconds)
    except (TypeError, ValueError):
        interval_seconds = DEFAULT_INTERVAL_SECONDS
    if interval_seconds <= 0:
        logger.info("post-upgrade settlement disabled (%s<=%s)", INTERVAL_ENV, interval_seconds)
        return None
    event = stop_event or threading.Event()
    worker = threading.Thread(
        target=_settlement_loop,
        name="upgrade-settlement-fallback",
        args=(settings, database, event, interval_seconds),
        daemon=True,
    )
    worker.start()
    return event
