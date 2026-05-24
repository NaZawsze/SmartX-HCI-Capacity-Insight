from typing import Any

from app.core.security import encrypt_secret
from app.db import get_conn, row_to_dict, rows_to_dicts
from app.models import ClusterResponse, TowerCreate, TowerResponse, TowerUpdate


def list_towers() -> list[TowerResponse]:
    with get_conn() as conn:
        towers = rows_to_dicts(conn.execute("SELECT * FROM towers ORDER BY name").fetchall())
        clusters = rows_to_dicts(conn.execute("SELECT * FROM clusters ORDER BY name").fetchall())
    clusters_by_tower: dict[int, list[ClusterResponse]] = {}
    for cluster in clusters:
        clusters_by_tower.setdefault(int(cluster["tower_id"]), []).append(
            ClusterResponse(
                cluster_id=str(cluster["cluster_id"]),
                name=str(cluster["name"]),
                enabled=bool(cluster["enabled"]),
            )
        )
    return [_tower_response(tower, clusters_by_tower.get(int(tower["id"]), [])) for tower in towers]


def get_tower(tower_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        return row_to_dict(conn.execute("SELECT * FROM towers WHERE id = ?", (tower_id,)).fetchone())


def create_tower(payload: TowerCreate) -> TowerResponse:
    username = _clean_optional(payload.username)
    password = _clean_optional(payload.password)
    api_token = _clean_optional(payload.api_token)
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO towers (
                name, base_url, username, password_encrypted, api_token_encrypted,
                verify_tls, enabled, collection_hour, collection_minute
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.name.strip(),
                str(payload.base_url).rstrip("/"),
                username,
                encrypt_secret(password),
                encrypt_secret(api_token),
                int(payload.verify_tls),
                int(payload.enabled),
                payload.collection_hour,
                payload.collection_minute,
            ),
        )
        tower = row_to_dict(conn.execute("SELECT * FROM towers WHERE id = ?", (cur.lastrowid,)).fetchone())
    return _tower_response(tower or {}, [])


def update_tower(tower_id: int, payload: TowerUpdate) -> TowerResponse | None:
    fields: dict[str, Any] = {}
    for name in ("verify_tls", "enabled", "collection_hour", "collection_minute"):
        value = getattr(payload, name)
        if value is not None:
            fields[name] = int(value) if isinstance(value, bool) else value
    if payload.name is not None:
        fields["name"] = payload.name.strip()
    if payload.username is not None:
        fields["username"] = _clean_optional(payload.username)
    if payload.base_url is not None:
        fields["base_url"] = str(payload.base_url).rstrip("/")
    if payload.password is not None:
        fields["password_encrypted"] = encrypt_secret(_clean_optional(payload.password))
    if payload.api_token is not None:
        fields["api_token_encrypted"] = encrypt_secret(_clean_optional(payload.api_token))
    if not fields:
        tower = get_tower(tower_id)
        return _tower_response(tower, _clusters_for_tower(tower_id)) if tower else None
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [tower_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE towers SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
        tower = row_to_dict(conn.execute("SELECT * FROM towers WHERE id = ?", (tower_id,)).fetchone())
    return _tower_response(tower, _clusters_for_tower(tower_id)) if tower else None


def delete_tower(tower_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM towers WHERE id = ?", (tower_id,))
        return cur.rowcount > 0


def upsert_clusters(tower_id: int, clusters: list[dict[str, Any]]) -> list[ClusterResponse]:
    responses: list[ClusterResponse] = []
    with get_conn() as conn:
        for cluster in clusters:
            cluster_id = str(cluster.get("id") or cluster.get("cluster_id") or "")
            if not cluster_id:
                continue
            name = str(cluster.get("name") or cluster.get("cluster_name") or cluster_id)
            existing = row_to_dict(
                conn.execute(
                    "SELECT enabled, name FROM clusters WHERE tower_id = ? AND cluster_id = ?",
                    (tower_id, cluster_id),
                ).fetchone()
            )
            enabled = int(existing["enabled"]) if existing else 1
            display_name = str(existing["name"]) if existing and existing.get("name") else name
            conn.execute(
                """
                INSERT INTO clusters (tower_id, cluster_id, name, enabled, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(tower_id, cluster_id) DO UPDATE SET
                    updated_at = CURRENT_TIMESTAMP
                """,
                (tower_id, cluster_id, display_name, enabled),
            )
            responses.append(ClusterResponse(cluster_id=cluster_id, name=display_name, enabled=bool(enabled)))
    return responses


def update_cluster(tower_id: int, cluster_id: str, enabled: bool | None = None, name: str | None = None) -> ClusterResponse | None:
    fields: dict[str, Any] = {}
    if enabled is not None:
        fields["enabled"] = int(enabled)
    if name is not None:
        fields["name"] = name.strip()
    if fields:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [tower_id, cluster_id]
        with get_conn() as conn:
            conn.execute(
                f"UPDATE clusters SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE tower_id = ? AND cluster_id = ?",
                values,
            )
            row = row_to_dict(
                conn.execute(
                    "SELECT * FROM clusters WHERE tower_id = ? AND cluster_id = ?",
                    (tower_id, cluster_id),
                ).fetchone()
            )
    else:
        with get_conn() as conn:
            row = row_to_dict(
                conn.execute(
                    "SELECT * FROM clusters WHERE tower_id = ? AND cluster_id = ?",
                    (tower_id, cluster_id),
                ).fetchone()
            )
    if row is None:
        return None
    return ClusterResponse(cluster_id=row["cluster_id"], name=row["name"], enabled=bool(row["enabled"]))


def set_cluster_enabled(tower_id: int, cluster_id: str, enabled: bool) -> ClusterResponse | None:
    return update_cluster(tower_id, cluster_id, enabled=enabled)


def _clusters_for_tower(tower_id: int) -> list[ClusterResponse]:
    with get_conn() as conn:
        rows = rows_to_dicts(conn.execute("SELECT * FROM clusters WHERE tower_id = ? ORDER BY name", (tower_id,)).fetchall())
    return [ClusterResponse(cluster_id=row["cluster_id"], name=row["name"], enabled=bool(row["enabled"])) for row in rows]


def _tower_response(tower: dict[str, Any], clusters: list[ClusterResponse]) -> TowerResponse:
    return TowerResponse(
        id=int(tower["id"]),
        name=str(tower["name"]),
        base_url=str(tower["base_url"]),
        username=tower.get("username"),
        verify_tls=bool(tower["verify_tls"]),
        enabled=bool(tower["enabled"]),
        collection_hour=int(tower["collection_hour"]),
        collection_minute=int(tower["collection_minute"]),
        last_error=tower.get("last_error"),
        clusters=clusters,
    )


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
