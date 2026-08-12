from __future__ import annotations

import json
import os
import signal
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from app.v2.cloudtower.service import CloudTowerService
from app.v2.collection.service import CollectionService
from app.v2.config import settings_from_environment
from app.v2.data_quality.service import DataQualityService
from app.v2.database import V2Database
from app.v2.tasks.service import TaskService


def metrics_body(database: V2Database) -> bytes:
    with database.connection() as conn:
        row = conn.execute("SELECT metrics_text FROM metric_snapshots WHERE id = 1").fetchone()
    text = str(row["metrics_text"]) if row else ""
    return text.encode("utf-8")


def build_collection_trigger(*, timezone: str, hour: int, minute: int):
    from apscheduler.triggers.cron import CronTrigger

    return CronTrigger(hour=hour, minute=minute, timezone=timezone)


def run_collection(database: V2Database) -> None:
    settings = database.settings
    cloudtower = CloudTowerService(database, settings)
    tasks = TaskService(database)
    service = CollectionService(database, settings, cloudtower_client=cloudtower)
    result = service.run_manual_collection(trigger="scheduled")
    accumulated_metrics = result.metrics_text
    failed_targets = _failed_targets(database, result.run_id)
    if not failed_targets:
        _run_data_quality_check(database, tasks)
        return
    retry_plan = _retry_plan(database, failed_targets)
    max_attempts = max((plan["max_attempts"] for plan in retry_plan.values()), default=0)
    for attempt in range(1, max_attempts + 1):
        due_targets = {
            key
            for key, plan in retry_plan.items()
            if plan["enabled"] and attempt <= plan["max_attempts"]
        }
        if not due_targets:
            break
        interval_minutes = min((retry_plan[key]["interval_minutes"] for key in due_targets), default=15)
        time.sleep(max(0, interval_minutes) * 60)
        retry_result = service.run_manual_collection(
            trigger="retry",
            attempt=attempt,
            max_attempts=max_attempts,
            target_filter=due_targets,
        )
        accumulated_metrics = _merge_metrics_text(accumulated_metrics, retry_result.metrics_text)
        _save_metrics_text(database, accumulated_metrics)
        failed_targets = _failed_targets(database, retry_result.run_id)
        if not failed_targets:
            break
        retry_plan = {key: retry_plan[key] for key in _target_keys(failed_targets) if key in retry_plan}
    if failed_targets:
        _record_collection_warning(database, tasks, failed_targets, attempt=max_attempts, max_attempts=max_attempts)
    _run_data_quality_check(database, tasks)


def _write_collection_marker(path: Path, marker: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _task_timestamp(task: dict) -> float:
    for field in ("finished_at", "uploaded_at", "created_at", "started_at", "updated_at"):
        value = str(task.get(field) or "").strip()
        if not value:
            continue
        if value.endswith("Z"):
            value = f"{value[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    return float("-inf")


def _auto_collection_platform_task(task: dict) -> bool:
    if str(task.get("status") or "") not in {"success", "succeeded"}:
        return False
    manifest = task.get("manifest") if isinstance(task.get("manifest"), dict) else {}
    if str(manifest.get("package_type") or "") != "platform":
        return False
    components = manifest.get("components") if isinstance(manifest.get("components"), list) else []
    if not any(isinstance(component, dict) and component.get("type") == "platform" for component in components):
        return False
    post_upgrade = manifest.get("post_upgrade") if isinstance(manifest.get("post_upgrade"), dict) else {}
    return bool(post_upgrade.get("auto_collection"))


def _ensure_post_upgrade_collection_marker(database: V2Database, tasks: TaskService) -> Path | None:
    settings = database.settings
    candidates: list[tuple[float, str, Path, dict]] = []
    for task_file in settings.upgrades_dir.glob("*/task.json"):
        try:
            task = json.loads(task_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        task_id = str(task.get("task_id") or "").strip()
        if task_id != task_file.parent.name or not _auto_collection_platform_task(task):
            continue
        candidates.append((_task_timestamp(task), task_id, task_file.parent, task))
    if not candidates:
        return None
    _, task_id, task_dir, task = max(candidates, key=lambda item: (item[0], item[1]))
    marker_path = task_dir / "post-upgrade-collection.json"
    if marker_path.is_file():
        return marker_path
    collection_task_id = f"post-upgrade-collection-{task_id}"
    if tasks.get_task(collection_task_id) is not None:
        return None
    marker = {
        "schema_version": 1,
        "parent_upgrade_task_id": task_id,
        "task_id": collection_task_id,
        "target_version": str(task.get("target_version") or (task.get("manifest") or {}).get("version") or settings.app_version),
        "status": "pending",
        "scheduled_at": datetime.now(timezone.utc).isoformat(),
        "source": "target_worker_compatibility",
    }
    _write_collection_marker(marker_path, marker)
    return marker_path


def run_pending_post_upgrade_collection(database: V2Database):
    settings = database.settings
    tasks = TaskService(database)
    _ensure_post_upgrade_collection_marker(database, tasks)
    for marker_path in sorted(settings.upgrades_dir.glob("*/post-upgrade-collection.json")):
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker_status = str(marker.get("status") or "pending")
        if marker_status in {"success", "failed"}:
            continue
        task_id = str(marker.get("task_id") or "")
        parent_id = str(marker.get("parent_upgrade_task_id") or "")
        if not task_id or not parent_id:
            marker["status"] = "failed"
            marker["error"] = "升级后采集标记缺少 task_id 或 parent_upgrade_task_id"
            _write_collection_marker(marker_path, marker)
            continue
        parent_path = settings.upgrades_dir / parent_id / "task.json"
        if not parent_path.is_file():
            continue
        parent = json.loads(parent_path.read_text(encoding="utf-8"))
        if str(parent.get("status") or "") not in {"success", "succeeded"}:
            continue
        if marker_status == "running":
            existing = tasks.get_task(task_id)
            if existing and existing.get("status") in {"pending", "running"}:
                tasks.update_task(
                    task_id,
                    status="failed",
                    progress=100,
                    message="升级后自动采集被 worker 重启中断，请手动重新采集。",
                    logs=[*(existing.get("logs") or []), "检测到未完成的 running 标记，停止自动重试。"],
                )
            marker["status"] = "failed"
            marker["error"] = "collector-worker restarted during post-upgrade collection"
            _write_collection_marker(marker_path, marker)
            continue
        marker["status"] = "running"
        _write_collection_marker(marker_path, marker)
        service = CollectionService(
            database,
            settings,
            cloudtower_client=CloudTowerService(database, settings),
            tasks=tasks,
        )
        result = service.run_manual_collection(trigger="post_upgrade", task_id=task_id)
        marker["status"] = "success" if result.status == "success" else "failed"
        marker["collection_status"] = result.status
        marker["message"] = result.message
        marker["run_id"] = result.run_id
        _write_collection_marker(marker_path, marker)
        return result
    return None


class MetricsHandler(BaseHTTPRequestHandler):
    database: V2Database

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API.
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        body = metrics_body(self.database)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        return


def start_metrics_server(database: V2Database, host: str = "0.0.0.0", port: int = 9108) -> ThreadingHTTPServer:
    MetricsHandler.database = database
    server = ThreadingHTTPServer((host, port), MetricsHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _run_data_quality_check(database: V2Database, tasks: TaskService) -> None:
    try:
        DataQualityService(database, database.settings, tasks=tasks).evaluate_and_alert(period_days=30)
    except Exception:
        return


def main() -> None:
    settings = settings_from_environment()
    database = V2Database(settings)
    database.initialize()
    metrics_server = start_metrics_server(database)
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone=settings.timezone)
    hour = int(__import__("os").environ.get("SMARTX_COLLECTION_HOUR", "2"))
    minute = int(__import__("os").environ.get("SMARTX_COLLECTION_MINUTE", "10"))
    scheduler.add_job(
        lambda: run_collection(database),
        build_collection_trigger(timezone=settings.timezone, hour=hour, minute=minute),
        id="daily-smartx-v2-collector",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        lambda: run_pending_post_upgrade_collection(database),
        "interval",
        seconds=5,
        id="post-upgrade-auto-collection",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()

    stop = False

    def request_stop(*_: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        while not stop:
            signal.pause()
    finally:
        scheduler.shutdown(wait=False)
        metrics_server.shutdown()


def _failed_targets(database: V2Database, run_id: int) -> list[dict]:
    service = CollectionService(database, database.settings, cloudtower_client=CloudTowerService(database, database.settings))
    detail = service.run_detail(run_id) or {}
    failed = detail.get("failed_targets") or []
    return [item for item in failed if isinstance(item, dict)]


def _target_keys(targets: list[dict]) -> set[tuple[int, str]]:
    keys: set[tuple[int, str]] = set()
    for target in targets:
        try:
            keys.add((int(target.get("tower_id")), str(target.get("cluster_id"))))
        except (TypeError, ValueError):
            continue
    return keys


def _retry_plan(database: V2Database, failed_targets: list[dict]) -> dict[tuple[int, str], dict[str, int | bool]]:
    failed_keys = _target_keys(failed_targets)
    plan: dict[tuple[int, str], dict[str, int | bool]] = {}
    with database.connection() as conn:
        rows = conn.execute(
            """
            SELECT t.id AS tower_id, c.cluster_id, t.collection_retry_enabled,
                   t.collection_retry_interval_minutes, t.collection_retry_max_attempts
            FROM towers t
            JOIN clusters c ON c.tower_id = t.id
            WHERE t.enabled = 1 AND c.enabled = 1
            """
        ).fetchall()
    for row in rows:
        key = (int(row["tower_id"]), str(row["cluster_id"]))
        if key not in failed_keys:
            continue
        plan[key] = {
            "enabled": bool(row["collection_retry_enabled"]),
            "interval_minutes": int(row["collection_retry_interval_minutes"] or 15),
            "max_attempts": int(row["collection_retry_max_attempts"] or 0),
        }
    return plan


def _save_metrics_text(database: V2Database, metrics_text: str) -> None:
    with database.connection() as conn:
        conn.execute(
            """
            INSERT INTO metric_snapshots (id, metrics_text)
            VALUES (1, ?)
            ON CONFLICT(id) DO UPDATE SET metrics_text = excluded.metrics_text, updated_at = CURRENT_TIMESTAMP
            """,
            (metrics_text,),
        )


def _merge_metrics_text(previous: str, current: str) -> str:
    comments: list[str] = []
    samples: dict[str, str] = {}
    for text in (previous, current):
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                if stripped not in comments:
                    comments.append(stripped)
                continue
            samples[_sample_key(stripped)] = stripped
    return "\n".join([*comments, *samples.values()]) + ("\n" if comments or samples else "")


def _sample_key(line: str) -> str:
    return line.split(" ", 1)[0]


def _record_collection_warning(database: V2Database, tasks: TaskService, failed_targets: list[dict], *, attempt: int, max_attempts: int) -> None:
    names = "，".join(f"{item.get('tower_name')} / {item.get('cluster_name')}" for item in failed_targets)
    message = f"采集异常：重试 {attempt}/{max_attempts} 后仍有 {len(failed_targets)} 个集群失败。失败目标：{names}"
    logs = [
        f"失败目标：{len(failed_targets)} 个",
        f"重试次数：{attempt}/{max_attempts}",
        *[f"{item.get('tower_name')} / {item.get('cluster_name')}：{item.get('message')}" for item in failed_targets],
    ]
    tasks.create_task(
        "collection-warning-latest",
        "collection",
        "Tower/集群采集异常",
        status="failed",
        progress=100,
        message=message,
        logs=logs,
    )


if __name__ == "__main__":
    main()
