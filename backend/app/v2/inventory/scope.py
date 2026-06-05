from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ScopeType(str, Enum):
    ALL = "all"
    TOWER = "tower"
    CLUSTER = "cluster"


@dataclass(frozen=True)
class DashboardScope:
    type: ScopeType
    tower_id: int | None = None
    cluster_id: str | None = None

    @classmethod
    def from_query(cls, tower_id: int | None, cluster_id: str | None) -> "DashboardScope":
        if cluster_id and tower_id is None:
            raise ValueError("cluster scope requires tower_id")
        if cluster_id:
            return cls(type=ScopeType.CLUSTER, tower_id=tower_id, cluster_id=cluster_id)
        if tower_id is not None:
            return cls(type=ScopeType.TOWER, tower_id=tower_id)
        return cls(type=ScopeType.ALL)
