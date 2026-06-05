from __future__ import annotations

import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.v2.cloudtower.service import CloudTowerService
from app.v2.collection.service import CollectionService
from app.v2.config import settings_from_environment
from app.v2.database import V2Database


def metrics_body(database: V2Database) -> bytes:
    with database.connection() as conn:
        row = conn.execute("SELECT metrics_text FROM metric_snapshots WHERE id = 1").fetchone()
    text = str(row["metrics_text"]) if row else ""
    return text.encode("utf-8")


def build_collection_trigger(*, timezone: str, hour: int, minute: int) -> CronTrigger:
    return CronTrigger(hour=hour, minute=minute, timezone=timezone)


def run_collection(database: V2Database) -> None:
    settings = database.settings
    cloudtower = CloudTowerService(database, settings)
    CollectionService(database, settings, cloudtower_client=cloudtower).run_manual_collection()


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


def main() -> None:
    settings = settings_from_environment()
    database = V2Database(settings)
    database.initialize()
    metrics_server = start_metrics_server(database)
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


if __name__ == "__main__":
    main()
