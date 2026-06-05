from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.v2.config import V2Settings
from app.v2.database import V2Database, row_to_dict
from app.v2.inventory.models import ClusterRecord, TowerRecord
from app.v2.inventory.service import InventoryService
from app.v2.metrics.formatter import ClusterCapacitySample, VmCapacitySample, render_capacity_metrics


class CloudTowerCollector(Protocol):
    def collect_cluster(self, tower: TowerRecord, cluster: ClusterRecord) -> dict:
        ...


@dataclass(frozen=True)
class CollectionResult:
    run_id: int
    status: str
    message: str
    metrics_text: str = ""


class CollectionService:
    def __init__(self, database: V2Database, settings: V2Settings, cloudtower_client: CloudTowerCollector) -> None:
        self.database = database
        self.settings = settings
        self.cloudtower_client = cloudtower_client
        self.inventory = InventoryService(database, settings)

    def run_manual_collection(self) -> CollectionResult:
        run_id = self._start_run()
        cluster_samples: list[ClusterCapacitySample] = []
        vm_samples: list[VmCapacitySample] = []
        try:
            for tower in self.inventory.list_towers():
                if not tower.enabled:
                    continue
                for cluster in tower.clusters:
                    if not cluster.enabled:
                        continue
                    payload = self.cloudtower_client.collect_cluster(tower, cluster)
                    cluster_payload = payload.get("cluster", {})
                    cluster_samples.append(
                        ClusterCapacitySample(
                            tower_id=tower.id,
                            cluster_id=cluster.cluster_id,
                            used_bytes=int(cluster_payload.get("used_bytes") or 0),
                            total_bytes=int(cluster_payload.get("total_bytes") or 0),
                        )
                    )
                    for vm in payload.get("vms", []):
                        sample = VmCapacitySample(
                            tower_id=tower.id,
                            cluster_id=cluster.cluster_id,
                            vm_id=str(vm["vm_id"]),
                            vm_name=str(vm.get("name") or vm["vm_id"]),
                            used_bytes=int(vm.get("used_bytes") or 0),
                        )
                        vm_samples.append(sample)
                        self._upsert_latest_vm(sample)
            metrics_text = render_capacity_metrics(clusters=cluster_samples, vms=vm_samples)
            message = f"采集完成：{len(cluster_samples)} 个集群，{len(vm_samples)} 台虚拟机。"
            self._finish_run(run_id, "success", message)
            return CollectionResult(run_id=run_id, status="success", message=message, metrics_text=metrics_text)
        except Exception as exc:  # noqa: BLE001 - collector failures are summarized for UI.
            message = self._mask_secret_material(str(exc))
            self._finish_run(run_id, "failed", message)
            return CollectionResult(run_id=run_id, status="failed", message=message)

    def latest_vm(self, tower_id: int, cluster_id: str, vm_id: str) -> dict | None:
        with self.database.connection() as conn:
            return row_to_dict(
                conn.execute(
                    "SELECT tower_id, cluster_id, vm_id, name, used_bytes FROM vm_latest WHERE tower_id = ? AND cluster_id = ? AND vm_id = ?",
                    (tower_id, cluster_id, vm_id),
                ).fetchone()
            )

    def _start_run(self) -> int:
        with self.database.connection() as conn:
            cursor = conn.execute("INSERT INTO collection_runs (status, message) VALUES ('running', '采集中')")
            return int(cursor.lastrowid)

    def _finish_run(self, run_id: int, status: str, message: str) -> None:
        with self.database.connection() as conn:
            conn.execute(
                "UPDATE collection_runs SET status = ?, message = ?, finished_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, message, run_id),
            )

    def _upsert_latest_vm(self, sample: VmCapacitySample) -> None:
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tower_id, cluster_id, vm_id) DO UPDATE SET
                    name = excluded.name,
                    used_bytes = excluded.used_bytes,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (sample.tower_id, sample.cluster_id, sample.vm_id, sample.vm_name, sample.used_bytes),
            )

    def _mask_secret_material(self, message: str) -> str:
        masked = message
        for tower in self.inventory.list_towers():
            secrets = self.inventory.get_tower_secret_material(tower.id)
            for secret in secrets.values():
                if secret:
                    masked = masked.replace(secret, "******")
        return masked
