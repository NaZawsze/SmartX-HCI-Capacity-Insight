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
                        self._replace_vm_volumes(
                            tower_id=tower.id,
                            cluster_id=cluster.cluster_id,
                            vm_id=sample.vm_id,
                            volumes=list(vm.get("volumes") or []),
                        )
            metrics_text = render_capacity_metrics(clusters=cluster_samples, vms=vm_samples)
            self._save_metrics_text(metrics_text)
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

    def latest_metrics_text(self) -> str:
        with self.database.connection() as conn:
            row = conn.execute("SELECT metrics_text FROM metric_snapshots WHERE id = 1").fetchone()
        return str(row["metrics_text"]) if row else ""

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

    def _save_metrics_text(self, metrics_text: str) -> None:
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO metric_snapshots (id, metrics_text)
                VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET
                    metrics_text = excluded.metrics_text,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (metrics_text,),
            )

    def _replace_vm_volumes(self, *, tower_id: int, cluster_id: str, vm_id: str, volumes: list[dict]) -> None:
        with self.database.connection() as conn:
            conn.execute("DELETE FROM vm_volumes WHERE tower_id = ? AND cluster_id = ? AND vm_id = ?", (tower_id, cluster_id, vm_id))
            for index, volume in enumerate(volumes):
                conn.execute(
                    """
                    INSERT INTO vm_volumes (
                        tower_id, cluster_id, vm_id, volume_id, name, path, size_bytes,
                        used_bytes, storage_policy, replica_num, thin_provision, ec_k, ec_m
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tower_id,
                        cluster_id,
                        vm_id,
                        str(volume.get("volume_id") or volume.get("id") or f"volume-{index}"),
                        volume.get("name"),
                        volume.get("path"),
                        _int_or_none(volume.get("size_bytes"), volume.get("size")),
                        _int_or_none(volume.get("used_bytes"), volume.get("used_size")),
                        volume.get("storage_policy") or volume.get("elf_storage_policy"),
                        _int_or_none(volume.get("replica_num"), volume.get("elf_storage_policy_replica_num")),
                        _bool_to_int(volume.get("thin_provision", volume.get("elf_storage_policy_thin_provision"))),
                        _int_or_none(volume.get("ec_k"), volume.get("elf_storage_policy_ec_k")),
                        _int_or_none(volume.get("ec_m"), volume.get("elf_storage_policy_ec_m")),
                    ),
                )

    def _mask_secret_material(self, message: str) -> str:
        masked = message
        for tower in self.inventory.list_towers():
            masked = self.inventory.mask_secret_material(tower.id, masked)
        return masked


def _int_or_none(*values: object) -> int | None:
    for value in values:
        if value is None:
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
    return None


def _bool_to_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        return 1 if value.lower() in {"1", "true", "yes"} else 0
    return 1 if bool(value) else 0
