from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class PrometheusHealth:
    ok: bool
    message: str


class PrometheusService:
    def __init__(self, base_url: str, http_client: Any | None = None, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def health(self) -> PrometheusHealth:
        try:
            response = self._client.get("/-/ready")
        except Exception as exc:  # noqa: BLE001 - health check should report concise UI text.
            return PrometheusHealth(ok=False, message=str(exc))
        if response.status_code < 400:
            return PrometheusHealth(ok=True, message="Prometheus ready.")
        return PrometheusHealth(ok=False, message=response.text[:300] or f"Prometheus HTTP {response.status_code}")

    def instant(self, query: str) -> list[dict[str, Any]]:
        response = self._client.get("/api/v1/query", params={"query": query})
        response.raise_for_status()
        return _result_array(response.json())

    def range(self, query: str, *, start: int, end: int, step: str) -> list[dict[str, Any]]:
        response = self._client.get(
            "/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": step},
        )
        response.raise_for_status()
        return _result_array(response.json())


def _result_array(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    result = payload.get("data", {}).get("result", [])
    return [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []
