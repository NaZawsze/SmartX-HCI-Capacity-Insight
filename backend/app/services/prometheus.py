import time
from typing import Any

import httpx
from prometheus_client import CollectorRegistry, Gauge, generate_latest

from app.core.config import get_settings
from app.db import get_conn, rows_to_dicts


VM_METRICS = {
    "used": "smartx_vm_storage_used_bytes",
    "guest_used": "smartx_vm_storage_guest_used_bytes",
    "provisioned": "smartx_vm_storage_provisioned_bytes",
    "logical": "smartx_vm_storage_logical_bytes",
    "unique": "smartx_vm_storage_unique_bytes",
    "used_ratio": "smartx_vm_storage_used_ratio",
}

CLUSTER_METRICS = {
    "used": "smartx_cluster_storage_used_bytes",
    "free": "smartx_cluster_storage_free_bytes",
    "total": "smartx_cluster_storage_total_bytes",
}

_latest_samples: list[dict[str, Any]] = []


def set_latest_samples(samples: list[dict[str, Any]]) -> None:
    global _latest_samples
    _latest_samples = samples
    with get_conn() as conn:
        conn.execute("DELETE FROM metric_samples")
        conn.executemany(
            "INSERT INTO metric_samples (payload_json) VALUES (?)",
            [(json_dumps(sample),) for sample in samples],
        )


def latest_metrics_text() -> bytes:
    samples = load_latest_samples() or _latest_samples
    registry = CollectorRegistry()
    vm_gauges = {
        key: Gauge(
            metric,
            f"SmartX VM storage {key}",
            ["tower_id", "tower", "cluster_id", "cluster", "vm_id", "vm"],
            registry=registry,
        )
        for key, metric in VM_METRICS.items()
    }
    cluster_gauges = {
        key: Gauge(
            metric,
            f"SmartX cluster storage {key}",
            ["tower_id", "tower", "cluster_id", "cluster"],
            registry=registry,
        )
        for key, metric in CLUSTER_METRICS.items()
    }
    for sample in samples:
        if sample.get("kind") == "vm":
            labels = [
                str(sample["tower_id"]),
                sample["tower"],
                sample["cluster_id"],
                sample["cluster"],
                sample["vm_id"],
                sample["vm"],
            ]
            for key, gauge in vm_gauges.items():
                value = sample.get(key)
                if value is not None:
                    gauge.labels(*labels).set(float(value))
        if sample.get("kind") == "cluster":
            labels = [str(sample["tower_id"]), sample["tower"], sample["cluster_id"], sample["cluster"]]
            for key, gauge in cluster_gauges.items():
                value = sample.get(key)
                if value is not None:
                    gauge.labels(*labels).set(float(value))
    return generate_latest(registry)


def load_latest_samples() -> list[dict[str, Any]]:
    import json

    with get_conn() as conn:
        rows = rows_to_dicts(conn.execute("SELECT payload_json FROM metric_samples ORDER BY id").fetchall())
    samples: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            samples.append(payload)
    return samples


def json_dumps(sample: dict[str, Any]) -> str:
    import json

    return json.dumps(sample, ensure_ascii=False, separators=(",", ":"))


class PrometheusQuery:
    def __init__(self) -> None:
        self.base_url = get_settings().prometheus_url.rstrip("/")

    async def instant(self, query: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=20) as client:
            response = await client.get("/api/v1/query", params={"query": query})
            response.raise_for_status()
            return response.json().get("data", {}).get("result", [])

    async def range(self, query: str, days: int = 90, step: str = "1d") -> list[dict[str, Any]]:
        end = int(time.time())
        start = end - days * 86400
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30) as client:
            response = await client.get(
                "/api/v1/query_range",
                params={"query": query, "start": start, "end": end, "step": step},
            )
            response.raise_for_status()
            return response.json().get("data", {}).get("result", [])
