"""采集新鲜度探针：web-api 侧跨容器互检。

覆盖 collector-worker 整体挂掉/卡死的盲区——此时 worker 进程内的
data-quality 与容量告警检查一并停摆，任务中心不会有新条目。web-api
独立存活，周期检查"是否太久没有成功采集记录"并主动写任务中心告警。
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any

from app.v2.data_quality.service import freshness_threshold_minutes
from app.v2.database import V2Database
from app.v2.tasks.models import TaskStatus, TaskType
from app.v2.tasks.service import TaskService

logger = logging.getLogger(__name__)

FRESHNESS_TASK_ID = "collection-freshness-stale"
DEFAULT_PROBE_INTERVAL_SECONDS = 600
_PROBE_INTERVAL_ENV = "SMARTX_FRESHNESS_PROBE_INTERVAL_SECONDS"
_TS_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


class CollectionFreshnessService:
    def __init__(
        self,
        database: V2Database,
        tasks: TaskService | None = None,
        *,
        probe_started_at: datetime | None = None,
    ) -> None:
        self.database = database
        self.tasks = tasks
        self.probe_started_at = probe_started_at or datetime.now(timezone.utc)

    def evaluate(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        threshold_minutes = freshness_threshold_minutes(self.database)
        result: dict[str, Any] = {
            "status": "ok",
            "threshold_minutes": threshold_minutes,
            "enabled_tower_count": self._enabled_tower_count(),
            "latest_success_at": None,
            "minutes_since_success": None,
        }
        if not result["enabled_tower_count"]:
            result["status"] = "skipped"
            result["reason"] = "no_enabled_towers"
            return result
        latest = self._latest_success()
        if latest is None:
            probe_age_minutes = max(0.0, (current - self.probe_started_at).total_seconds() / 60)
            result["probe_age_minutes"] = round(probe_age_minutes, 1)
            if probe_age_minutes > threshold_minutes:
                result["status"] = "stale"
                result["reason"] = "no_success_ever"
            return result
        parsed = _parse_db_time(str(latest.get("finished_at") or latest.get("started_at") or ""))
        if parsed is None:
            result["status"] = "unknown"
            result["reason"] = "unparseable_timestamp"
            return result
        minutes_since = (current - parsed).total_seconds() / 60
        result["latest_success_at"] = parsed.isoformat()
        result["minutes_since_success"] = round(minutes_since, 1)
        if minutes_since > threshold_minutes:
            result["status"] = "stale"
        result["reason"] = "no_recent_success"
        return result

    def evaluate_and_alert(self, *, now: datetime | None = None) -> dict[str, Any]:
        result = self.evaluate(now=now)
        if self.tasks is None or result["status"] != "stale":
            return result
        threshold = result["threshold_minutes"]
        minutes = result.get("minutes_since_success")
        if result.get("reason") == "no_success_ever" or minutes is None:
            summary = f"从未有成功采集记录，且 web-api 已运行超过 {threshold} 分钟"
            latest_line = "最近成功采集时间：无"
        else:
            summary = f"已约 {minutes:.0f} 分钟没有成功采集记录（阈值 {threshold} 分钟）"
            latest_line = f"最近成功采集时间：{result.get('latest_success_at') or '无'}"
        detail_lines = [
            "采集新鲜度检查（web-api 侧跨容器互检）",
            latest_line,
            f"停摆阈值：{threshold} 分钟（按启用 Tower 采集间隔自适应）",
            summary,
            "采集器（collector-worker）可能未运行或长时间未成功，请检查容器状态与 Tower 连接。",
        ]
        self.tasks.create_task(
            FRESHNESS_TASK_ID,
            TaskType.COLLECTION,
            "采集停摆告警",
            status=TaskStatus.FAILED,
            progress=100,
            message="\n".join(detail_lines),
            logs=detail_lines,
        )
        return result

    def _latest_success(self) -> dict[str, Any] | None:
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT * FROM collection_runs WHERE status = 'success' "
                "ORDER BY COALESCE(finished_at, started_at) DESC, id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def _enabled_tower_count(self) -> int:
        with self.database.connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM towers WHERE enabled = 1").fetchone()
        return int(row["n"]) if row else 0


def start_freshness_probe_daemon(database: V2Database, *, interval_seconds: int | None = None) -> threading.Event | None:
    """启动采集新鲜度探针后台线程，返回停止信号；间隔 <=0 时不启动（关闭开关）。"""
    if interval_seconds is None:
        raw = os.environ.get(_PROBE_INTERVAL_ENV, "").strip()
        try:
            interval_seconds = int(raw) if raw else DEFAULT_PROBE_INTERVAL_SECONDS
        except ValueError:
            interval_seconds = DEFAULT_PROBE_INTERVAL_SECONDS
    if interval_seconds <= 0:
        logger.info("collection freshness probe disabled (%s<=%s)", _PROBE_INTERVAL_ENV, interval_seconds)
        return None
    stop_event = threading.Event()
    started_at = datetime.now(timezone.utc)
    worker = threading.Thread(
        target=_probe_loop,
        name="collection-freshness-probe",
        args=(database, stop_event, interval_seconds, started_at),
        daemon=True,
    )
    worker.start()
    return stop_event


def _probe_loop(database: V2Database, stop_event: threading.Event, interval_seconds: int, started_at: datetime) -> None:
    tasks = TaskService(database)
    service = CollectionFreshnessService(database, tasks, probe_started_at=started_at)
    logger.info("collection freshness probe started (interval=%ss)", interval_seconds)
    while not stop_event.is_set():
        try:
            result = service.evaluate_and_alert()
            if result["status"] == "stale":
                logger.warning("collection freshness stale: %s", result)
        except Exception:
            logger.exception("collection freshness probe iteration failed")
        stop_event.wait(interval_seconds)


def _parse_db_time(value: str) -> datetime | None:
    return parse_db_time(value)


def parse_db_time(value: str) -> datetime | None:
    """解析 collection_runs 等 DB 时间戳（按 UTC 处理），供看板新鲜度判定共用口径。"""
    text = value.strip().removesuffix("Z")
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
