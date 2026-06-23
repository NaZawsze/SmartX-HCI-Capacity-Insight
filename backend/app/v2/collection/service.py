from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Protocol

from app.v2.config import V2Settings
from app.v2.database import V2Database, row_to_dict
from app.v2.inventory.models import ClusterRecord, TowerRecord
from app.v2.inventory.service import InventoryService
from app.v2.metrics.formatter import ClusterCapacitySample, VmCapacitySample, render_capacity_metrics
from app.v2.tasks.models import TaskStatus, TaskType
from app.v2.tasks.service import TaskService


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
    def __init__(self, database: V2Database, settings: V2Settings, cloudtower_client: CloudTowerCollector, tasks: TaskService | None = None) -> None:
        self.database = database
        self.settings = settings
        self.cloudtower_client = cloudtower_client
        self.inventory = InventoryService(database, settings)
        self.tasks = tasks

    def run_manual_collection(
        self,
        *,
        trigger: str = "manual",
        cycle_id: str | None = None,
        attempt: int = 0,
        max_attempts: int | None = None,
        target_filter: set[tuple[int, str]] | None = None,
        task_id: str | None = None,
    ) -> CollectionResult:
        towers = [tower for tower in self.inventory.list_towers() if tower.enabled]
        max_attempts = max_attempts if max_attempts is not None else max((tower.collection_retry_max_attempts for tower in towers), default=0)
        run_id = self._start_run(trigger=trigger, cycle_id=cycle_id or f"collection-{uuid.uuid4().hex[:12]}", attempt=attempt, max_attempts=max_attempts)
        task_id = self._start_task(run_id, trigger=trigger, task_id=task_id)
        cluster_samples: list[ClusterCapacitySample] = []
        vm_samples: list[VmCapacitySample] = []
        success_targets: list[dict[str, object]] = []
        failed_targets: list[dict[str, object]] = []
        for tower in towers:
            for cluster in tower.clusters:
                if not cluster.enabled:
                    continue
                if target_filter is not None and (tower.id, cluster.cluster_id) not in target_filter:
                    continue
                try:
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
                    success_targets.append(_target_payload(tower, cluster, attempt=attempt))
                except Exception as exc:  # noqa: BLE001 - collector failures are summarized for UI.
                    failed_targets.append(_target_payload(tower, cluster, attempt=attempt, message=self._collection_error_message(exc)))
        metrics_text = render_capacity_metrics(clusters=cluster_samples, vms=vm_samples)
        self._save_metrics_text(metrics_text)
        if failed_targets and success_targets:
            status = "partial_failed"
            message = f"采集异常：成功 {len(success_targets)} 个集群，失败 {len(failed_targets)} 个集群。"
        elif failed_targets:
            status = "failed"
            message = f"采集异常：成功 0 个集群，失败 {len(failed_targets)} 个集群。"
        else:
            status = "success"
            message = f"采集完成：{len(cluster_samples)} 个集群，{len(vm_samples)} 台虚拟机。"
        if failed_targets:
            message = f"{message} 失败目标：{_target_names(failed_targets)}。最后错误：{failed_targets[-1].get('message', '')}"
        self._finish_run(
            run_id,
            status,
            message,
            success_targets=success_targets,
            failed_targets=failed_targets,
            published_targets=success_targets,
        )
        self._finish_task(task_id, status=status, message=message)
        if failed_targets and self.tasks is not None and trigger != "manual":
            self._record_collection_warning(run_id, status, message, success_targets, failed_targets, attempt=attempt, max_attempts=max_attempts)
        return CollectionResult(run_id=run_id, status=status, message=message, metrics_text=metrics_text)

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

    def list_runs(self, limit: int = 30) -> list[dict]:
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, status, message, started_at, finished_at, trigger, cycle_id, attempt, max_attempts,
                       success_targets_json, failed_targets_json, published_metrics_targets_json
                FROM collection_runs
                ORDER BY started_at DESC, id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [_run_row(row) for row in rows]

    def run_detail(self, run_id: int) -> dict | None:
        with self.database.connection() as conn:
            row = conn.execute(
                """
                SELECT id, status, message, started_at, finished_at, trigger, cycle_id, attempt, max_attempts,
                       success_targets_json, failed_targets_json, published_metrics_targets_json
                FROM collection_runs WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        return _run_row(row) if row else None

    def _start_run(self, *, trigger: str, cycle_id: str, attempt: int, max_attempts: int) -> int:
        with self.database.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO collection_runs (status, message, trigger, cycle_id, attempt, max_attempts)
                VALUES ('running', '采集中', ?, ?, ?, ?)
                """,
                (trigger, cycle_id, int(attempt), int(max_attempts)),
            )
            return int(cursor.lastrowid)

    def _finish_run(
        self,
        run_id: int,
        status: str,
        message: str,
        *,
        success_targets: list[dict[str, object]] | None = None,
        failed_targets: list[dict[str, object]] | None = None,
        published_targets: list[dict[str, object]] | None = None,
    ) -> None:
        with self.database.connection() as conn:
            conn.execute(
                """
                UPDATE collection_runs
                SET status = ?, message = ?, finished_at = CURRENT_TIMESTAMP,
                    success_targets_json = ?, failed_targets_json = ?, published_metrics_targets_json = ?
                WHERE id = ?
                """,
                (
                    status,
                    message,
                    _json(success_targets or []),
                    _json(failed_targets or []),
                    _json(published_targets or []),
                    run_id,
                ),
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

    def _collection_error_message(self, exc: Exception) -> str:
        return self._mask_secret_material(_normalize_collection_error(str(exc)))

    def _start_task(self, run_id: int, *, trigger: str, task_id: str | None = None) -> str | None:
        if self.tasks is None or trigger != "manual":
            return None
        task_id = task_id or f"collection-run-{run_id}"
        self.tasks.create_task(
            task_id,
            TaskType.COLLECTION,
            "执行采集",
            status=TaskStatus.RUNNING,
            progress=10,
            message="正在采集 Tower/集群容量数据",
            logs=[f"采集记录：{run_id}", "开始采集启用 Tower/集群"],
        )
        return task_id

    def _finish_task(self, task_id: str | None, *, status: str, message: str) -> None:
        if self.tasks is None or task_id is None:
            return
        task_status = TaskStatus.SUCCESS if status == "success" else TaskStatus.FAILED
        logs = ["采集已完成" if status == "success" else "采集完成但存在异常", f"结果：{status}", message]
        self.tasks.update_task(
            task_id,
            status=task_status,
            progress=100,
            message=message,
            logs=logs,
        )

    def _record_collection_warning(
        self,
        run_id: int,
        status: str,
        message: str,
        success_targets: list[dict[str, object]],
        failed_targets: list[dict[str, object]],
        *,
        attempt: int,
        max_attempts: int,
    ) -> None:
        if self.tasks is None:
            return
        logs = [
            f"采集状态：{status}",
            f"成功目标：{len(success_targets)} 个",
            f"失败目标：{len(failed_targets)} 个",
            f"重试次数：{attempt}/{max_attempts}",
            *[f"{item.get('tower_name')} / {item.get('cluster_name')}：{item.get('message')}" for item in failed_targets],
        ]
        self.tasks.create_task(
            f"collection-warning-{run_id}",
            TaskType.COLLECTION,
            "Tower/集群采集异常",
            status=TaskStatus.FAILED,
            progress=100,
            message=message,
            logs=logs,
        )


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


def _target_payload(tower: TowerRecord, cluster: ClusterRecord, *, attempt: int, message: str | None = None) -> dict[str, object]:
    item: dict[str, object] = {
        "tower_id": tower.id,
        "tower_name": tower.name,
        "cluster_id": cluster.cluster_id,
        "cluster_name": cluster.name,
        "attempt": attempt,
    }
    if message is not None:
        item["message"] = message
    else:
        item["success_at"] = "CURRENT_TIMESTAMP"
    return item


def _target_names(targets: list[dict[str, object]]) -> str:
    return "，".join(f"{item.get('tower_name')} / {item.get('cluster_name')}" for item in targets)


def _normalize_collection_error(message: str) -> str:
    lowered = message.lower()
    if "requires either an api token or username/password" in lowered:
        return "账号凭据未配置或未保存，请在 Tower 设置中重新填写 API Token 或 LOCAL 账号密码。"
    if "login failed" in lowered or "password is incorrect" in lowered or "user not found" in lowered or "unauthorized" in lowered:
        return f"账号或密码错误，或账号已禁用/锁定/密码过期。原始错误：{message}"
    if "connection refused" in lowered or "connecterror" in lowered or "failed to establish a new connection" in lowered:
        return f"CloudTower 地址或端口连接失败，请检查地址、端口和网络连通性。原始错误：{message}"
    if "timeout" in lowered or "timed out" in lowered:
        return f"CloudTower 连接超时，请检查网络延迟、防火墙或 CloudTower 服务状态。原始错误：{message}"
    return message


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load_json(value: str | None, default: object) -> object:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _run_row(row) -> dict:
    result = dict(row)
    result["success_targets"] = _load_json(result.pop("success_targets_json", None), [])
    result["failed_targets"] = _load_json(result.pop("failed_targets_json", None), [])
    result["published_metrics_targets"] = _load_json(result.pop("published_metrics_targets_json", None), [])
    return result
