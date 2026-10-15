from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException

from app.v2.config import V2Settings
from app.v2.database import V2Database, row_to_dict
from app.v2.inventory.models import ClusterRecord, TowerRecord
from app.v2.inventory.service import InventoryService
from app.v2.metrics.formatter import ClusterCapacitySample, VmCapacitySample, merge_metrics_text, render_capacity_metrics
from app.v2.tasks.models import TaskStatus, TaskType
from app.v2.tasks.service import TaskService

logger = logging.getLogger(__name__)


class CloudTowerCollector(Protocol):
    def collect_cluster(self, tower: TowerRecord, cluster: ClusterRecord) -> dict:
        ...

    def version_info(self, tower: TowerRecord) -> dict:
        # 采集顺带刷新版本（2026-10-07）：{"platform": "v4.5.0", "clusters": {cluster_id: "6.1.1"}}。
        # 测试 fake 可不实现（CollectionService 侧做了 best-effort 兜底）。
        ...

    def cluster_allocations(self, tower: TowerRecord) -> dict[str, int]:
        # #75 终版：已分配在 collect_cluster 的 payload 内就计算（Σ 卷供给 × 副本/EC），
        # 本协议桩仅为既有协议形状保留，不再被实现调用。
        ...


@dataclass(frozen=True)
class CollectionResult:
    run_id: int
    status: str
    message: str
    metrics_text: str = ""


class CollectionService:
    #: 单飞守卫的陈旧阈值（#87 加固）：`running` 记录超过该秒数即判定为**中断残留**
    #: （服务重启/进程被杀留下的脏状态），允许新采集并把它收敛为 `failed`。
    #: 依据：真实一轮采集 ≤ ~2 分钟（`.3` 实测 22~111s）、定时间隔 60 分钟 ⇒
    #: 1 小时足以区分「真在跑」与「卡死」。`.3` 曾有一条 2026-10-03 起卡 12 天的
    #: `post_upgrade` running 记录，令手动采集**永久** 409（2026-10-15 部署级复验发现）。
    STALE_RUNNING_SECONDS = 3600

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
        """**同步**执行一轮采集（调度/worker、升级后采集与回退路径用）。

        API 手动采集默认走异步（`submit_manual_collection`，#87）；
        `SMARTX_COLLECTION_RUN_ASYNC=0` 时 API 才回退到本方法。
        """
        cycle_id = cycle_id or f"collection-{uuid.uuid4().hex[:12]}"
        if max_attempts is None:
            max_attempts = self._default_max_attempts()
        run_id = self._start_run(trigger=trigger, cycle_id=cycle_id, attempt=attempt, max_attempts=max_attempts)
        return self._execute_collection(
            run_id,
            trigger=trigger,
            cycle_id=cycle_id,
            attempt=attempt,
            max_attempts=max_attempts,
            target_filter=target_filter,
            task_id=task_id,
        )

    def submit_manual_collection(self, *, task_id: str | None = None) -> int:
        """#87 异步化：提交后**立即返回 run_id**，采集在后台线程执行（前端轮询既有 `/runs/{id}`）。

        单飞：已有 `running` 采集记录时拒绝（409）——语义与升级单飞一致，**不排队**。
        中断残留（超过 `STALE_RUNNING_SECONDS` 仍为 running）先收敛为 failed 再放行，
        否则一条卡死的记录会让手动采集**永久** 409。
        """
        self._converge_stale_runs()
        running = self._running_run_id()
        if running is not None:
            raise HTTPException(
                status_code=409,
                detail=f"已有采集任务在执行中（采集记录 #{running}），请等待其完成后再试。",
            )
        cycle_id = f"collection-{uuid.uuid4().hex[:12]}"
        run_id = self._start_run(
            trigger="manual",
            cycle_id=cycle_id,
            attempt=0,
            max_attempts=self._default_max_attempts(),
        )
        threading.Thread(
            target=self._execute_collection_async,
            args=(run_id, cycle_id, task_id),
            name=f"collection-run-{run_id}",
            daemon=True,
        ).start()
        return run_id

    def _execute_collection_async(self, run_id: int, cycle_id: str, task_id: str | None) -> None:
        """后台执行一轮采集；任何未捕获异常都必须落 `failed` 终态（不允许线程静默死掉）。"""
        try:
            self._execute_collection(
                run_id,
                trigger="manual",
                cycle_id=cycle_id,
                attempt=0,
                max_attempts=None,
                target_filter=None,
                task_id=task_id,
            )
        except Exception as exc:  # noqa: BLE001 - 后台线程异常必须落终态，否则前端永远等不到结果
            logger.exception("collection: 后台执行异常（run=%s）", run_id)
            message = f"采集异常：后台执行失败：{type(exc).__name__}: {exc}"
            try:
                self._finish_run(
                    run_id,
                    "failed",
                    message,
                    success_targets=[],
                    failed_targets=[],
                    published_targets=[],
                )
            except Exception:  # noqa: BLE001 - 落终态再失败只能记录
                logger.exception("collection: 后台终态落库失败（run=%s）", run_id)

    def _default_max_attempts(self) -> int:
        towers = [tower for tower in self.inventory.list_towers() if tower.enabled]
        return max((tower.collection_retry_max_attempts for tower in towers), default=0)

    def _running_run_id(self) -> int | None:
        """最近一条仍在执行的采集记录（单飞判据）。"""
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT id FROM collection_runs WHERE status = 'running' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return int(row["id"]) if row else None

    def _stale_running_run_ids(self) -> list[int]:
        """超过陈旧阈值仍为 `running` 的采集记录 id（中断残留）。

        时间比较放在 SQL 里做（`started_at` 与 `CURRENT_TIMESTAMP` 同为 UTC 字符串），
        避免 Python 侧时区解析口径分歧。
        """
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT id FROM collection_runs"
                " WHERE status = 'running' AND started_at < datetime('now', ?)",
                (f"-{int(self.STALE_RUNNING_SECONDS)} seconds",),
            ).fetchall()
        return [int(row["id"]) for row in rows]

    def _converge_stale_runs(self) -> list[int]:
        """把中断残留的 running 记录收敛为 failed（连同其任务行），返回收敛的 id 列表。

        幂等：无残留时空操作。守卫（手动路径）与 `_start_run`（覆盖定时路径）都会调用——
        后者让脏状态在下一轮采集自愈，而不是只在用户点「立即采集」时才被清理。
        """
        run_ids = self._stale_running_run_ids()
        for run_id in run_ids:
            self._finish_run(
                run_id,
                "failed",
                f"采集记录超过 {self.STALE_RUNNING_SECONDS // 60} 分钟仍为执行中，"
                "判定为中断残留（服务重启或进程异常退出），已自动标记失败。",
            )
            if self.tasks is not None:
                try:
                    self.tasks.update_task(
                        f"collection-run-{run_id}",
                        status=TaskStatus.FAILED,
                        progress=100,
                        message="采集中断（服务重启或异常退出），已标记失败",
                    )
                except Exception:  # noqa: BLE001 - 定时采集无任务行 / 任务行已被清理
                    logger.debug("collection: 收敛残留 run 时未更新任务行（run=%s）", run_id)
            logger.warning("collection: 收敛中断残留的 running 采集记录 #%s", run_id)
        return run_ids

    def _execute_collection(
        self,
        run_id: int,
        *,
        trigger: str,
        cycle_id: str,
        attempt: int,
        max_attempts: int | None,
        target_filter: set[tuple[int, str]] | None,
        task_id: str | None,
    ) -> CollectionResult:
        towers = [tower for tower in self.inventory.list_towers() if tower.enabled]
        if max_attempts is None:
            max_attempts = max((tower.collection_retry_max_attempts for tower in towers), default=0)
        task_id = self._start_task(run_id, trigger=trigger, task_id=task_id)
        # 采集前抓旧快照：落库时合并（49-37），失败/被过滤目标沿用最后已知样本，
        # 否则 API 手动采集路径会整体替换快照，把历史样本抹空导致看板归零。
        previous_metrics = self.latest_metrics_text()
        cluster_samples: list[ClusterCapacitySample] = []
        vm_samples: list[VmCapacitySample] = []
        success_targets: list[dict[str, object]] = []
        failed_targets: list[dict[str, object]] = []
        for tower in towers:
            self._refresh_tower_versions(tower)
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
                            allocated_bytes=int(cluster_payload.get("allocated_bytes") or 0),
                        )
                    )
                    for vm in payload.get("vms", []):
                        sample = VmCapacitySample(
                            tower_id=tower.id,
                            cluster_id=cluster.cluster_id,
                            vm_id=str(vm["vm_id"]),
                            vm_name=str(vm.get("name") or vm["vm_id"]),
                            used_bytes=int(vm.get("used_bytes") or 0),
                            in_recycle_bin=1 if vm.get("in_recycle_bin") else 0,
                            original_name=vm.get("original_name"),
                            deleted_at=vm.get("deleted_at"),
                            owner=vm.get("owner"),
                            folder_name=vm.get("folder_name"),
                        )
                        vm_samples.append(sample)
                        self._upsert_latest_vm(sample)
                        self._replace_vm_volumes(
                            tower_id=tower.id,
                            cluster_id=cluster.cluster_id,
                            vm_id=sample.vm_id,
                            volumes=list(vm.get("volumes") or []),
                        )
                    # 49-47/#77：本次采集成功才核对。用户口径（2026-10-03）：
                    # Tower 取不到的 VM 就是已删除——普通 VM 与回收站 VM 同口径，
                    # 一律删本地 VM 行与卷行；再兜底清掉历史孤儿卷行。
                    kept_vm_ids = {str(vm.get("vm_id")) for vm in payload.get("vms", [])}
                    self._purge_missing_vms(
                        tower_id=tower.id,
                        cluster_id=cluster.cluster_id,
                        kept_vm_ids=kept_vm_ids,
                    )
                    self._purge_orphan_vm_volumes(tower_id=tower.id, cluster_id=cluster.cluster_id)
                    success_targets.append(_target_payload(tower, cluster, attempt=attempt))
                except Exception as exc:  # noqa: BLE001 - collector failures are summarized for UI.
                    failed_targets.append(_target_payload(tower, cluster, attempt=attempt, message=self._collection_error_message(exc)))
        metrics_text = merge_metrics_text(previous_metrics, render_capacity_metrics(clusters=cluster_samples, vms=vm_samples))
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
        if failed_targets and self.tasks is not None and trigger not in {"manual", "post_upgrade"}:
            self._record_collection_warning(run_id, status, message, success_targets, failed_targets, attempt=attempt, max_attempts=max_attempts)
        return CollectionResult(run_id=run_id, status=status, message=message, metrics_text=metrics_text)

    def _refresh_tower_versions(self, tower: TowerRecord) -> None:
        """采集顺带刷新版本信息（2026-10-07 需求）：Tower 平台版本 + 各集群 SMTX OS 版本。

        用途：设置页 Tower 列表展示；后续按 Tower 版本选择不同 API 的依据。
        best-effort——版本读取/落库失败只跳过（老 fake 客户端没有该方法也必须无害）。
        """
        try:
            info = self.cloudtower_client.version_info(tower)
            self.inventory.record_versions(
                tower_id=tower.id,
                tower_version=info.get("platform"),
                cluster_versions=dict(info.get("clusters") or {}),
            )
        except Exception:  # noqa: BLE001 - 版本是附加信息，任何失败都不影响采集
            return

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
        # 任何一轮采集开始前先收敛中断残留（定时路径也走这里 ⇒ 脏状态自愈，不依赖用户点击）
        self._converge_stale_runs()
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
                INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes, in_recycle_bin, original_name, deleted_at, owner, folder_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tower_id, cluster_id, vm_id) DO UPDATE SET
                    name = excluded.name,
                    used_bytes = excluded.used_bytes,
                    in_recycle_bin = excluded.in_recycle_bin,
                    original_name = excluded.original_name,
                    deleted_at = excluded.deleted_at,
                    owner = excluded.owner,
                    folder_name = excluded.folder_name,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    sample.tower_id,
                    sample.cluster_id,
                    sample.vm_id,
                    sample.vm_name,
                    sample.used_bytes,
                    int(sample.in_recycle_bin or 0),
                    sample.original_name,
                    sample.deleted_at,
                    sample.owner,
                    sample.folder_name,
                ),
            )

    def _purge_missing_vms(self, *, tower_id: int, cluster_id: str, kept_vm_ids: set[str]) -> int:
        """VM 行核对（49-47 扩展 + #77 用户口径 2026-10-03）：采集成功后，Tower 未返回的
        VM 即已删除 —— 删本地 VM 行与其卷行。普通 VM 与回收站 VM **同口径**。

        Tower 是这些行的唯一事实源：本次成功采集的返回集合就是全集。
        必须在该塔/集群本次采集成功后调用；采集失败一律不动（避免整集群被误判删除）。
        """
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT vm_id FROM vm_latest WHERE tower_id = ? AND cluster_id = ?",
                (tower_id, cluster_id),
            ).fetchall()
            missing = [row["vm_id"] for row in rows if row["vm_id"] not in kept_vm_ids]
            for vm_id in missing:
                conn.execute(
                    "DELETE FROM vm_latest WHERE tower_id = ? AND cluster_id = ? AND vm_id = ?",
                    (tower_id, cluster_id, vm_id),
                )
                conn.execute(
                    "DELETE FROM vm_volumes WHERE tower_id = ? AND cluster_id = ? AND vm_id = ?",
                    (tower_id, cluster_id, vm_id),
                )
        return len(missing)

    def _purge_orphan_vm_volumes(self, *, tower_id: int, cluster_id: str) -> int:
        """卷行兜底核对（#77）：删除没有对应 VM 行的卷行。

        覆盖本次 `_purge_missing_vms` 触及不到的历史孤儿卷——旧实现对 vm_latest 做了
        核对删除、vm_volumes 却没有，Tower 删卷后卷行永久残留（`.3` 实测 93 条 / 40.79 TiB
        虚高「已分配」）。同样只在采集成功后调用。返回删除的卷行数。
        """
        with self.database.connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM vm_volumes
                WHERE tower_id = ? AND cluster_id = ? AND vm_id NOT IN (
                    SELECT vm_id FROM vm_latest WHERE tower_id = ? AND cluster_id = ?
                )
                """,
                (tower_id, cluster_id, tower_id, cluster_id),
            )
        return cursor.rowcount or 0

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
        if self.tasks is None or trigger not in {"manual", "post_upgrade"}:
            return None
        task_id = task_id or f"collection-run-{run_id}"
        title = "升级后自动采集" if trigger == "post_upgrade" else "执行采集"
        message = "升级完成，正在刷新 Tower/集群容量数据" if trigger == "post_upgrade" else "正在采集 Tower/集群容量数据"
        self.tasks.create_task(
            task_id,
            TaskType.COLLECTION,
            title,
            status=TaskStatus.RUNNING,
            progress=10,
            message=message,
            logs=[f"采集记录：{run_id}", "开始采集启用 Tower/集群", f"触发来源：{trigger}"],
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


# 语义与 parsing.int_or_none 不同：不跳过空串，保持独立实现。
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
