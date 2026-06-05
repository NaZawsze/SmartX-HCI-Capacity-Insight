from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClusterCapacitySample:
    tower_id: int
    cluster_id: str
    used_bytes: int
    total_bytes: int


@dataclass(frozen=True)
class VmCapacitySample:
    tower_id: int
    cluster_id: str
    vm_id: str
    vm_name: str
    used_bytes: int


def render_capacity_metrics(*, clusters: list[ClusterCapacitySample], vms: list[VmCapacitySample]) -> str:
    lines = [
        "# HELP smartx_cluster_storage_used_bytes SmartX cluster used storage bytes.",
        "# TYPE smartx_cluster_storage_used_bytes gauge",
        "# HELP smartx_cluster_storage_total_bytes SmartX cluster total storage bytes.",
        "# TYPE smartx_cluster_storage_total_bytes gauge",
        "# HELP smartx_vm_storage_used_bytes SmartX VM used storage bytes.",
        "# TYPE smartx_vm_storage_used_bytes gauge",
    ]
    for cluster in clusters:
        labels = _labels(tower_id=str(cluster.tower_id), cluster_id=cluster.cluster_id)
        lines.append(f"smartx_cluster_storage_used_bytes{{{labels}}} {cluster.used_bytes}")
        lines.append(f"smartx_cluster_storage_total_bytes{{{labels}}} {cluster.total_bytes}")
    for vm in vms:
        labels = _labels(tower_id=str(vm.tower_id), cluster_id=vm.cluster_id, vm_id=vm.vm_id, vm_name=vm.vm_name)
        lines.append(f"smartx_vm_storage_used_bytes{{{labels}}} {vm.used_bytes}")
    return "\n".join(lines) + "\n"


def _labels(**items: str) -> str:
    return ",".join(f'{key}="{_escape_label(value)}"' for key, value in items.items())


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
