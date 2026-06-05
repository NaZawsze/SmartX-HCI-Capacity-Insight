from __future__ import annotations

from app.v2.config import V2Settings
from app.v2.database import V2Database
from app.v2.inventory.models import ClusterInput, ClusterRecord, TowerInput, TowerRecord
from app.v2.security import decrypt_secret, encrypt_secret


class InventoryService:
    def __init__(self, database: V2Database, settings: V2Settings) -> None:
        self.database = database
        self.settings = settings

    def create_tower(self, payload: TowerInput) -> TowerRecord:
        with self.database.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO towers (
                    name, base_url, username, password_encrypted, api_token_encrypted,
                    verify_tls, enabled
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.name,
                    payload.base_url,
                    payload.username,
                    encrypt_secret(payload.password, self.settings.secret_key),
                    encrypt_secret(payload.api_token, self.settings.secret_key),
                    int(payload.verify_tls),
                    int(payload.enabled),
                ),
            )
            tower_id = int(cursor.lastrowid)
        tower = self.get_tower(tower_id)
        if tower is None:
            raise RuntimeError("created tower is not readable")
        return tower

    def list_towers(self) -> list[TowerRecord]:
        with self.database.connection() as conn:
            rows = conn.execute("SELECT * FROM towers ORDER BY id").fetchall()
            clusters = {
                int(row["id"]): [
                    ClusterRecord(cluster_id=cluster["cluster_id"], name=cluster["name"], enabled=bool(cluster["enabled"]))
                    for cluster in conn.execute(
                        "SELECT cluster_id, name, enabled FROM clusters WHERE tower_id = ? ORDER BY name, cluster_id",
                        (int(row["id"]),),
                    ).fetchall()
                ]
                for row in rows
            }
        return [self._tower_from_row(row, clusters.get(int(row["id"]), [])) for row in rows]

    def get_tower(self, tower_id: int) -> TowerRecord | None:
        with self.database.connection() as conn:
            row = conn.execute("SELECT * FROM towers WHERE id = ?", (tower_id,)).fetchone()
            if row is None:
                return None
            cluster_rows = conn.execute(
                "SELECT cluster_id, name, enabled FROM clusters WHERE tower_id = ? ORDER BY name, cluster_id",
                (tower_id,),
            ).fetchall()
        clusters = [ClusterRecord(cluster_id=item["cluster_id"], name=item["name"], enabled=bool(item["enabled"])) for item in cluster_rows]
        return self._tower_from_row(row, clusters)

    def update_tower(self, tower_id: int, payload: TowerInput) -> TowerRecord:
        updates = [
            "name = ?",
            "base_url = ?",
            "username = ?",
            "verify_tls = ?",
            "enabled = ?",
            "updated_at = CURRENT_TIMESTAMP",
        ]
        values: list[object] = [payload.name, payload.base_url, payload.username, int(payload.verify_tls), int(payload.enabled)]
        if payload.password:
            updates.append("password_encrypted = ?")
            values.append(encrypt_secret(payload.password, self.settings.secret_key))
        if payload.api_token:
            updates.append("api_token_encrypted = ?")
            values.append(encrypt_secret(payload.api_token, self.settings.secret_key))
        values.append(tower_id)
        with self.database.connection() as conn:
            conn.execute(f"UPDATE towers SET {', '.join(updates)} WHERE id = ?", values)
        tower = self.get_tower(tower_id)
        if tower is None:
            raise KeyError(f"tower {tower_id} not found")
        return tower

    def delete_tower(self, tower_id: int) -> bool:
        with self.database.connection() as conn:
            cursor = conn.execute("DELETE FROM towers WHERE id = ?", (tower_id,))
            return cursor.rowcount > 0

    def sync_clusters(self, tower_id: int, clusters: list[ClusterInput]) -> list[ClusterRecord]:
        with self.database.connection() as conn:
            for cluster in clusters:
                conn.execute(
                    """
                    INSERT INTO clusters (tower_id, cluster_id, name, enabled)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(tower_id, cluster_id) DO UPDATE SET
                        name = excluded.name,
                        enabled = excluded.enabled,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (tower_id, cluster.cluster_id, cluster.name, int(cluster.enabled)),
                )
        tower = self.get_tower(tower_id)
        if tower is None:
            raise KeyError(f"tower {tower_id} not found")
        return tower.clusters

    def update_cluster(self, tower_id: int, cluster_id: str, *, enabled: bool | None = None, name: str | None = None) -> ClusterRecord:
        updates: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
        values: list[object] = []
        if enabled is not None:
            updates.append("enabled = ?")
            values.append(int(enabled))
        if name is not None:
            updates.append("name = ?")
            values.append(name)
        values.extend([tower_id, cluster_id])
        with self.database.connection() as conn:
            conn.execute(
                f"UPDATE clusters SET {', '.join(updates)} WHERE tower_id = ? AND cluster_id = ?",
                values,
            )
            row = conn.execute(
                "SELECT cluster_id, name, enabled FROM clusters WHERE tower_id = ? AND cluster_id = ?",
                (tower_id, cluster_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"cluster {cluster_id} not found")
        return ClusterRecord(cluster_id=row["cluster_id"], name=row["name"], enabled=bool(row["enabled"]))

    def get_tower_secret_material(self, tower_id: int) -> dict[str, str | None]:
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT password_encrypted, api_token_encrypted FROM towers WHERE id = ?",
                (tower_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"tower {tower_id} not found")
        return {
            "password": decrypt_secret(row["password_encrypted"], self.settings.secret_key),
            "api_token": decrypt_secret(row["api_token_encrypted"], self.settings.secret_key),
        }

    def mask_secret_material(self, tower_id: int, message: str) -> str:
        masked = message
        try:
            secrets = self.get_tower_secret_material(tower_id)
        except KeyError:
            return masked
        for secret in secrets.values():
            if secret:
                masked = masked.replace(secret, "******")
        return masked

    def _tower_from_row(self, row, clusters: list[ClusterRecord]) -> TowerRecord:
        return TowerRecord(
            id=int(row["id"]),
            name=row["name"],
            base_url=row["base_url"],
            username=row["username"],
            verify_tls=bool(row["verify_tls"]),
            enabled=bool(row["enabled"]),
            clusters=clusters,
        )
