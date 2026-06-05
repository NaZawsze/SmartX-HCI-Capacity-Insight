from __future__ import annotations

from app.v2.cloudtower.client import CloudTowerClient, CloudTowerCredentials
from app.v2.config import V2Settings
from app.v2.database import V2Database
from app.v2.inventory.models import ClusterInput
from app.v2.inventory.service import InventoryService


class CloudTowerService:
    def __init__(self, database: V2Database, settings: V2Settings) -> None:
        self.database = database
        self.settings = settings
        self.inventory = InventoryService(database, settings)

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
            return client.get_clusters()
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
            return client.collect_cluster(cluster.cluster_id)
        finally:
            client.close()
