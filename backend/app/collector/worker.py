import asyncio
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.collector.collector import Collector
from app.core.config import get_settings
from app.db import init_db
from app.services.prometheus import latest_metrics_text


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API.
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        body = latest_metrics_text()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        return


def start_metrics_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", 9108), MetricsHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


async def main() -> None:
    settings = get_settings()
    init_db()
    metrics_server = start_metrics_server()
    scheduler = AsyncIOScheduler(timezone=settings.collection_timezone)
    scheduler.add_job(
        Collector().run_once,
        CronTrigger(hour=settings.collection_hour, minute=settings.collection_minute),
        id="daily-smartx-collector",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    await stop.wait()
    scheduler.shutdown(wait=False)
    metrics_server.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
