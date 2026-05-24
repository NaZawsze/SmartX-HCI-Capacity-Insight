from dataclasses import dataclass
from typing import Any

import httpx

from app.core.security import decrypt_secret


class CloudTowerError(RuntimeError):
    pass


@dataclass(slots=True)
class TowerAuth:
    id: int
    name: str
    base_url: str
    username: str | None
    password_encrypted: str | None
    api_token_encrypted: str | None
    verify_tls: bool


class CloudTowerClient:
    def __init__(self, tower: TowerAuth, timeout: float = 30.0) -> None:
        self.tower = tower
        self.base_url = tower.base_url.rstrip("/")
        self.timeout = timeout
        self._token: str | None = decrypt_secret(tower.api_token_encrypted)

    async def __aenter__(self) -> "CloudTowerClient":
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            verify=self.tower.verify_tls,
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def login(self) -> None:
        if self._token:
            return
        password = decrypt_secret(self.tower.password_encrypted)
        if not self.tower.username or not password:
            raise CloudTowerError("Tower requires either an API token or username/password.")
        response = await self._client.post(
            "/v2/api/login",
            json={"username": self.tower.username, "source": "LOCAL", "password": password},
            headers={"accept": "application/json", "content-language": "en-US"},
        )
        if response.status_code >= 400:
            detail = response.text.replace("\n", " ")[:300]
            raise CloudTowerError(f"Login failed with HTTP {response.status_code}: {detail}")
        payload = response.json()
        self._token = _extract_token(payload)
        if not self._token:
            raise CloudTowerError("Login response did not include a token.")

    async def post(self, path: str, payload: dict[str, Any] | None = None, retry: bool = True) -> Any:
        await self.login()
        response = await self._client.post(
            path,
            json=payload or {},
            headers={
                "Authorization": str(self._token),
                "accept": "application/json",
                "content-language": "en-US",
            },
        )
        if response.status_code in {401, 403} and retry and not self.tower.api_token_encrypted:
            self._token = None
            await self.login()
            return await self.post(path, payload, retry=False)
        if response.status_code >= 400:
            raise CloudTowerError(f"{path} failed with HTTP {response.status_code}: {response.text[:240]}")
        data = response.json()
        if isinstance(data, dict):
            return data.get("data", data)
        return data

    async def paged_post(self, path: str, query: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        limit = 100
        offset = 0
        while True:
            payload = dict(query or {})
            payload.setdefault("first", limit)
            payload.setdefault("skip", offset)
            data = await self.post(path, payload)
            page = _extract_items(data)
            items.extend(page)
            if len(page) < limit:
                break
            offset += limit
        return items

    async def get_clusters(self) -> list[dict[str, Any]]:
        return await self.paged_post("/v2/api/get-clusters")

    async def get_cluster_storage_info(self, cluster_id: str) -> dict[str, Any]:
        data = await self.post("/v2/api/get-cluster-storage-info", {"where": {"id": cluster_id}, "effect": {}})
        if isinstance(data, list):
            return data[0] if data else {}
        return data

    async def get_vms(self, cluster_id: str | None = None) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if cluster_id:
            where["cluster"] = {"id": cluster_id}
        return await self.paged_post("/v2/api/get-vms", {"where": where})

    async def get_vm_volumes(self, vm_id: str) -> list[dict[str, Any]]:
        return await self.paged_post("/v2/api/get-vm-volumes", {"where": {"vm_disks_some": {"vm": {"id": vm_id}}}})


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


def normalize_tower(row: dict[str, Any]) -> TowerAuth:
    return TowerAuth(
        id=int(row["id"]),
        name=str(row["name"]),
        base_url=str(row["base_url"]),
        username=row.get("username"),
        password_encrypted=row.get("password_encrypted"),
        api_token_encrypted=row.get("api_token_encrypted"),
        verify_tls=bool(row.get("verify_tls")),
    )
