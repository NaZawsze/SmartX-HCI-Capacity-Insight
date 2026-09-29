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

同时承担 US-32 的 compose tag 对账（见 `reconcile_runner_compose_tag`）：平台升级会用包内基线
覆盖项目文件，冲掉组件升级写回的 runner tag，必须按现场实际镜像周期性对齐。

设计：docs/superpowers/specs/2026-09-28-upgrade-settlement-fallback-design.md
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 300
INTERVAL_ENV = "SMARTX_UPGRADE_SETTLEMENT_INTERVAL_SECONDS"

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


def ensure_settlement_once(settings: Any, database: Any) -> dict[str, list[Any]]:
    """对漏网任务补建升级后清理任务。单个失败不影响其余；整体幂等。"""
    created: list[str] = []
    failed: list[dict[str, str]] = []
    targets = scan_missing_settlement(settings)
    if not targets:
        return {"created": created, "failed": failed}

    from app.v2.upgrade.service import UpgradeService
    from app.v2.tasks.service import TaskService

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
    return {"created": created, "failed": failed}


def reconcile_runner_compose_tag(settings: Any, database: Any) -> list[str]:
    """US-32：把 compose 里的 runner tag 对齐到现场实际运行的镜像。

    实测缺陷（`.12` 2026-09-29，先组件升级后平台升级）：runner 组件升级会把新 tag
    回写进 `project/docker-compose.yml`，但紧接着的平台升级会用包内**基线**（v0.3.1）
    覆盖项目文件，把回写冲掉 —— 实际跑 v0.3.2、compose 却写 v0.3.1，多事实源复现。
    任何一次 `docker compose up` 重建都会把 runner 静默降级（与 US-26 同类后果）。

    正常交付顺序（先平台、后 runner）能自愈，但乱序或中途失败就会留下不一致，
    因此这里按现场实际镜像做周期性对账，而不是依赖某条升级路径记得回写。
    """
    from app.v2.tasks.service import TaskService
    from app.v2.upgrade.service import UpgradeService

    service = UpgradeService(settings, TaskService(database), project_path=settings.project_path)
    field_image = service._resolve_field_runner_image({})
    if not field_image:
        return []
    return service._sync_runner_image_into_compose_files(field_image)


def _settlement_loop(settings: Any, database: Any, stop_event: threading.Event, interval_seconds: int) -> None:
    # 启动即跑一次：覆盖 web-api 重启后仍未收尾的历史任务
    while not stop_event.is_set():
        try:
            ensure_settlement_once(settings, database)
        except Exception as exc:  # noqa: BLE001 - 守护线程必须存活
            logger.warning("post-upgrade settlement sweep failed: %s", exc)
        try:
            synced = reconcile_runner_compose_tag(settings, database)
            if synced:
                # 能对齐说明此前不一致（如平台升级覆盖了组件升级的回写），属需留意的状态漂移
                logger.warning("runner compose tag re-aligned to field image: %s", ", ".join(synced))
        except Exception as exc:  # noqa: BLE001 - 守护线程必须存活
            logger.warning("runner compose tag reconcile failed: %s", exc)
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
