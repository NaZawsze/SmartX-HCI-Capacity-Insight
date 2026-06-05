from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ClusterInput:
    cluster_id: str
    name: str
    enabled: bool = True


@dataclass(frozen=True)
class ClusterRecord:
    cluster_id: str
    name: str
    enabled: bool = True


@dataclass(frozen=True)
class TowerInput:
    name: str
    base_url: str
    username: str | None = None
    password: str | None = None
    api_token: str | None = None
    verify_tls: bool = True
    enabled: bool = True


@dataclass(frozen=True)
class TowerRecord:
    id: int
    name: str
    base_url: str
    username: str | None
    verify_tls: bool
    enabled: bool
    clusters: list[ClusterRecord] = field(default_factory=list)
