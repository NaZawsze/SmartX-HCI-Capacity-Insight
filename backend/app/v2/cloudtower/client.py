from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.v2.inventory.models import ClusterInput


class CloudTowerError(RuntimeError):
    pass


@dataclass(frozen=True)
class CloudTowerCredentials:
    base_url: str
    username: str | None = None
    password: str | None = None
    api_token: str | None = None
    verify_tls: bool = True


class CloudTowerClient:
    def __init__(self, credentials: CloudTowerCredentials, http_client: Any | None = None, timeout: float = 30.0) -> None:
        self.credentials = credentials
        self.base_url = credentials.base_url.rstrip("/")
        self._token = credentials.api_token
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(base_url=self.base_url, timeout=timeout, verify=credentials.verify_tls)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def login(self) -> None:
        if self._token:
            return
        if not self.credentials.username or not self.credentials.password:
            raise CloudTowerError("Tower requires either an API token or username/password.")
        response = self._client.post(
            "/v2/api/login",
            json={"username": self.credentials.username, "source": "LOCAL", "password": self.credentials.password},
            headers={"accept": "application/json", "content-language": "en-US"},
        )
        if response.status_code >= 400:
            detail = response.text.replace("\n", " ")[:300]
            raise CloudTowerError(f"Login failed with HTTP {response.status_code}: {detail}")
        token = _extract_token(response.json())
        if not token:
            raise CloudTowerError("Login response did not include a token.")
        self._token = token

    def post(self, path: str, payload: dict[str, Any] | None = None, retry: bool = True) -> Any:
        self.login()
        response = self._client.post(
            path,
            json=payload or {},
            headers={
                "Authorization": str(self._token),
                "accept": "application/json",
                "content-language": "en-US",
            },
        )
        if response.status_code in {401, 403} and retry and not self.credentials.api_token:
            self._token = None
            self.login()
            return self.post(path, payload, retry=False)
        if response.status_code >= 400:
            raise CloudTowerError(f"{path} failed with HTTP {response.status_code}: {response.text[:240]}")
        data = response.json()
        if isinstance(data, dict):
            return data.get("data", data)
        return data

    def paged_post(self, path: str, query: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        limit = 100
        offset = 0
        while True:
            payload = dict(query or {})
            payload.setdefault("first", limit)
            payload.setdefault("skip", offset)
            page = _extract_items(self.post(path, payload))
            items.extend(page)
            if len(page) < limit:
                break
            offset += limit
        return items

    def get_clusters(self) -> list[ClusterInput]:
        return [cluster for cluster in (_normalize_cluster(item) for item in self.paged_post("/v2/api/get-clusters")) if cluster is not None]

    def get_cluster_storage_info(self, cluster_id: str) -> dict[str, Any]:
        data = self.post("/v2/api/get-cluster-storage-info", {"where": {"id": cluster_id}, "effect": {}})
        if isinstance(data, list):
            return data[0] if data else {}
        return data if isinstance(data, dict) else {}

    def get_vms(self, cluster_id: str | None = None) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if cluster_id:
            where["cluster"] = {"id": cluster_id}
        return self.paged_post("/v2/api/get-vms", {"where": where})

    def get_vm_volumes(self, vm_id: str) -> list[dict[str, Any]]:
        return self.paged_post("/v2/api/get-vm-volumes", {"where": {"vm_disks_some": {"vm": {"id": vm_id}}}})

    def collect_cluster(self, cluster_id: str) -> dict[str, Any]:
        storage = self.get_cluster_storage_info(cluster_id)
        return {
            "cluster": {
                "used_bytes": int(_number(storage.get("used_data_space"), storage.get("used_capacity"), storage.get("used_size"), storage.get("capacity_used")) or 0),
                "total_bytes": int(
                    _number(storage.get("total_data_capacity"), storage.get("total_capacity"), storage.get("total_size"), storage.get("capacity_total")) or 0
                ),
            },
            "vms": [
                normalized_vm
                for normalized_vm in (_normalize_vm(vm) for vm in self.get_vms(cluster_id))
                if normalized_vm is not None
            ],
        }


def _normalize_cluster(raw: dict[str, Any]) -> ClusterInput | None:
    cluster_id = str(raw.get("id") or raw.get("cluster_id") or "")
    if not cluster_id:
        return None
    return ClusterInput(cluster_id=cluster_id, name=str(raw.get("name") or raw.get("cluster_name") or cluster_id), enabled=True)


def _normalize_vm(raw: dict[str, Any]) -> dict[str, Any] | None:
    vm_id = str(raw.get("id") or raw.get("vm_id") or "")
    if not vm_id:
        return None
    return {
        "vm_id": vm_id,
        "name": str(raw.get("name") or raw.get("vm_name") or vm_id),
        "used_bytes": int(_number(raw.get("used_size"), raw.get("used_size_bytes"), raw.get("capacity_used")) or 0),
    }


def _extract_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("items", "data", "nodes", "records"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _extract_token(payload: Any) -> str | None:
    if isinstance(payload, list):
        for item in payload:
            token = _extract_token(item)
            if token:
                return token
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("token", "access_token"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return _extract_token(payload.get("data"))


def _number(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
