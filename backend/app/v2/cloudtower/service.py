from __future__ import annotations

from app.v2.cloudtower.client import CloudTowerClient, CloudTowerCredentials
from app.v2.cloudtower.profiles import profile_for_version
from app.v2.config import V2Settings
from app.v2.database import V2Database
from app.v2.inventory.models import ClusterInput
from app.v2.inventory.service import InventoryService


class CloudTowerService:
    def __init__(self, database: V2Database, settings: V2Settings) -> None:
        self.database = database
        self.settings = settings
        self.inventory = InventoryService(database, settings)

    def test_connection_params(
        self,
        *,
        base_url: str,
        username: str | None,
        password: str | None,
        api_token: str | None,
        verify_tls: bool,
    ) -> list[ClusterInput]:
        """用临时凭据测试连接（不落盘），用于创建 Tower 前的连通性验证。"""
        client = CloudTowerClient(
            CloudTowerCredentials(
                base_url=base_url,
                username=username or None,
                password=password or None,
                api_token=api_token or None,
                verify_tls=verify_tls,
            )
        )
        try:
            return client.get_clusters()
        finally:
            client.close()

    def test_connection(self, tower_id: int) -> list[ClusterInput]:
        tower = self.inventory.get_tower(tower_id)
        if tower is None:
            raise KeyError(f"tower {tower_id} not found")
        secrets = self.inventory.get_tower_secret_material(tower_id)
        client = CloudTowerClient(
            CloudTowerCredentials(
                base_url=tower.base_url,
                username=tower.username,
                password=secrets.get("password"),
                api_token=secrets.get("api_token"),
                verify_tls=tower.verify_tls,
            )
        )
        try:
            clusters = client.get_clusters()
            # 连接测试顺带刷新版本（设置页展示；版本读取失败不影响连接测试结论）
            try:
                info = client.version_info()
                self.inventory.record_versions(
                    tower_id=tower_id,
                    tower_version=info.get("platform"),
                    cluster_versions=dict(info.get("clusters") or {}),
                )
            except Exception:  # noqa: BLE001 - 版本是附加信息，取不到不报错
                pass
            return clusters
        finally:
            client.close()

    def version_info(self, tower) -> dict:
        """Tower 平台版本 + 各集群 SMTX OS 版本（采集顺带刷新，见 CollectionService）。"""
        secrets = self.inventory.get_tower_secret_material(tower.id)
        client = CloudTowerClient(
            CloudTowerCredentials(
                base_url=tower.base_url,
                username=tower.username,
                password=secrets.get("password"),
                api_token=secrets.get("api_token"),
                verify_tls=tower.verify_tls,
            )
        )
        try:
            return client.version_info()
        finally:
            client.close()

    def collect_cluster(self, tower, cluster) -> dict:
        secrets = self.inventory.get_tower_secret_material(tower.id)
        client = CloudTowerClient(
            CloudTowerCredentials(
                base_url=tower.base_url,
                username=tower.username,
                password=secrets.get("password"),
                api_token=secrets.get("api_token"),
                verify_tls=tower.verify_tls,
            )
        )
        try:
            # #84：按塔的平台版本选画像（版本未知 → None → 客户端用最新画像 + 能力探测兜底）
            profile = profile_for_version(getattr(tower, "tower_version", None))
            return client.collect_cluster(cluster.cluster_id, profile=profile)
        finally:
            client.close()

