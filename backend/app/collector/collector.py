from datetime import datetime, timezone
import json
from typing import Any

from app.db import get_conn, row_to_dict, rows_to_dicts
from app.services.cloudtower import CloudTowerClient, normalize_tower
from app.services.prometheus import set_latest_samples
from app.services.towers import upsert_clusters


class Collector:
    async def run_once(self) -> dict[str, Any]:
        run_id = self.start_run()
        return await self.run_started(run_id)

    async def run_started(self, run_id: int) -> dict[str, Any]:
        samples: list[dict[str, Any]] = []
        errors: list[str] = []
        try:
            towers = self._enabled_towers()
            for tower_row in towers:
                try:
                    tower_samples = await self._collect_tower(tower_row)
                    samples.extend(tower_samples)
                    self._add_item(run_id, tower_row["id"], None, "success", f"Collected {len(tower_samples)} samples.")
                except Exception as exc:  # noqa: BLE001 - collector must isolate tower failures.
                    message = str(exc)
                    errors.append(f"{tower_row['name']}: {message}")
                    self._add_item(run_id, tower_row["id"], None, "failed", message)
                    self._set_tower_error(tower_row["id"], message)
            set_latest_samples(samples)
            status = "failed" if errors and not samples else "partial" if errors else "success"
            self._finish_run(run_id, status, "; ".join(errors) if errors else f"Collected {len(samples)} samples.")
            return {"run_id": run_id, "status": status, "samples": len(samples), "errors": errors}
        except Exception as exc:  # noqa: BLE001 - keep a started run from staying in running forever.
            message = f"Collector crashed: {exc}"
            self._finish_run(run_id, "failed", message)
            return {"run_id": run_id, "status": "failed", "samples": len(samples), "errors": [message]}

    async def _collect_tower(self, tower_row: dict[str, Any]) -> list[dict[str, Any]]:
        tower = normalize_tower(tower_row)
        samples: list[dict[str, Any]] = []
        async with CloudTowerClient(tower) as client:
            clusters = await client.get_clusters()
            known_clusters = upsert_clusters(tower.id, clusters)
            enabled_ids = {cluster.cluster_id for cluster in known_clusters if cluster.enabled}
            cluster_names = {cluster.cluster_id: cluster.name for cluster in known_clusters}
            for cluster in clusters:
                cluster_id = str(cluster.get("id") or cluster.get("cluster_id") or "")
                if not cluster_id or cluster_id not in enabled_ids:
                    continue
                cluster_name = cluster_names.get(cluster_id) or str(cluster.get("name") or cluster.get("cluster_name") or cluster_id)
                storage = await client.get_cluster_storage_info(cluster_id)
                samples.append(_cluster_sample(tower_row, cluster_id, cluster_name, storage))
                for vm in await client.get_vms(cluster_id):
                    sample = _vm_sample(tower_row, cluster_id, cluster_name, vm)
                    if not sample["vm_id"]:
                        continue
                    samples.append(sample)
                    try:
                        volumes = await client.get_vm_volumes(sample["vm_id"])
                    except Exception:  # noqa: BLE001 - VM volume detail should not fail the whole tower snapshot.
                        volumes = []
                    self._save_vm_volumes(tower.id, cluster_id, sample["vm_id"], volumes)
        self._set_tower_error(tower.id, None)
        return samples

    def _enabled_towers(self) -> list[dict[str, Any]]:
        with get_conn() as conn:
            return rows_to_dicts(conn.execute("SELECT * FROM towers WHERE enabled = 1 ORDER BY name").fetchall())

    def start_run(self) -> int:
        with get_conn() as conn:
            cur = conn.execute("INSERT INTO collection_runs (status) VALUES ('running')")
            return int(cur.lastrowid)

    def _finish_run(self, run_id: int, status: str, message: str) -> None:
        with get_conn() as conn:
            conn.execute(
                "UPDATE collection_runs SET status = ?, message = ?, finished_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, message, run_id),
            )

    def _add_item(self, run_id: int, tower_id: int, cluster_id: str | None, status: str, message: str) -> None:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO collection_items (run_id, tower_id, cluster_id, status, message) VALUES (?, ?, ?, ?, ?)",
                (run_id, tower_id, cluster_id, status, message),
            )

    def _set_tower_error(self, tower_id: int, message: str | None) -> None:
        with get_conn() as conn:
            conn.execute("UPDATE towers SET last_error = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (message, tower_id))

    def _save_vm_volumes(self, tower_id: int, cluster_id: str, vm_id: str, volumes: list[dict[str, Any]]) -> None:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO latest_vm_volumes (tower_id, cluster_id, vm_id, payload_json, collected_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(tower_id, cluster_id, vm_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    collected_at = CURRENT_TIMESTAMP
                """,
                (tower_id, cluster_id, vm_id, json.dumps(volumes, ensure_ascii=False)),
            )


def latest_run() -> dict[str, Any] | None:
    with get_conn() as conn:
        return row_to_dict(conn.execute("SELECT * FROM collection_runs ORDER BY id DESC LIMIT 1").fetchone())


def running_run() -> dict[str, Any] | None:
    with get_conn() as conn:
        return row_to_dict(
            conn.execute("SELECT * FROM collection_runs WHERE status = 'running' ORDER BY id DESC LIMIT 1").fetchone()
        )


def latest_vm_volumes(vm_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        row = row_to_dict(
            conn.execute(
                "SELECT payload_json FROM latest_vm_volumes WHERE vm_id = ? ORDER BY collected_at DESC LIMIT 1",
                (vm_id,),
            ).fetchone()
        )
    if row is None:
        return []
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, ValueError):
        return []
    return payload if isinstance(payload, list) else []


def latest_all_vm_volumes() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT tower_id, cluster_id, vm_id, payload_json, collected_at
                FROM latest_vm_volumes
                WHERE EXISTS (
                    SELECT 1
                    FROM towers
                    JOIN clusters ON clusters.tower_id = towers.id
                    WHERE towers.id = latest_vm_volumes.tower_id
                      AND towers.enabled = 1
                      AND clusters.cluster_id = latest_vm_volumes.cluster_id
                      AND clusters.enabled = 1
                )
                ORDER BY collected_at DESC
                """
            ).fetchall()
        )
    volumes: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, list):
            continue
        volumes.append(
            {
                "tower_id": row["tower_id"],
                "cluster_id": row["cluster_id"],
                "vm_id": row["vm_id"],
                "volumes": payload,
            }
        )
    return volumes


def _number(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _vm_sample(tower: dict[str, Any], cluster_id: str, cluster_name: str, vm: dict[str, Any]) -> dict[str, Any]:
    vm_id = str(vm.get("id") or vm.get("vm_id") or "")
    vm_name = str(vm.get("name") or vm.get("vm_name") or vm_id)
    return {
        "kind": "vm",
        "tower_id": tower["id"],
        "tower": tower["name"],
        "cluster_id": cluster_id,
        "cluster": cluster_name,
        "vm_id": vm_id,
        "vm": vm_name,
        "used": _number(vm.get("used_size"), vm.get("used_size_bytes")),
        "guest_used": _number(vm.get("guest_used_size"), vm.get("guest_used_size_bytes")),
        "provisioned": _number(vm.get("provisioned_size"), vm.get("provisioned_size_bytes")),
        "logical": _number(vm.get("logical_size_bytes"), vm.get("logical_size")),
        "unique": _number(vm.get("unique_size"), vm.get("unique_size_bytes")),
        "used_ratio": _number(vm.get("used_size_usage"), vm.get("used_ratio")),
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


def _cluster_sample(tower: dict[str, Any], cluster_id: str, cluster_name: str, storage: dict[str, Any]) -> dict[str, Any]:
    total = _number(
        storage.get("total_data_capacity"),
        storage.get("total_capacity"),
        storage.get("total_size"),
        storage.get("capacity_total"),
    )
    used = _number(
        storage.get("used_data_space"),
        storage.get("used_capacity"),
        storage.get("used_size"),
        storage.get("capacity_used"),
    )
    free = _number(
        storage.get("free_data_space"),
        storage.get("free_capacity"),
        storage.get("free_size"),
        storage.get("capacity_free"),
    )
    if free is None and total is not None and used is not None:
        free = total - used
    return {
        "kind": "cluster",
        "tower_id": tower["id"],
        "tower": tower["name"],
        "cluster_id": cluster_id,
        "cluster": cluster_name,
        "used": used,
        "free": free,
        "total": total,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }
