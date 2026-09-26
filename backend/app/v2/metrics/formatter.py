from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClusterCapacitySample:
    tower_id: int
    cluster_id: str
    used_bytes: int
    total_bytes: int
    allocated_bytes: int = 0


@dataclass(frozen=True)
class VmCapacitySample:
    tower_id: int
    cluster_id: str
    vm_id: str
    vm_name: str
    used_bytes: int
    # 回收站生命周期（49-47）：仅影响 vm_latest 落库，不参与 metrics 渲染
    in_recycle_bin: int = 0
    original_name: str | None = None
    deleted_at: str | None = None


def render_capacity_metrics(*, clusters: list[ClusterCapacitySample], vms: list[VmCapacitySample]) -> str:
    lines = [
        "# HELP smartx_cluster_storage_used_bytes SmartX cluster used storage bytes.",
        "# TYPE smartx_cluster_storage_used_bytes gauge",
        "# HELP smartx_cluster_storage_total_bytes SmartX cluster total storage bytes.",
        "# TYPE smartx_cluster_storage_total_bytes gauge",
        "# HELP smartx_cluster_storage_allocated_bytes SmartX cluster allocated (provisioned) storage bytes.",
        "# TYPE smartx_cluster_storage_allocated_bytes gauge",
        "# HELP smartx_vm_storage_used_bytes SmartX VM used storage bytes.",
        "# TYPE smartx_vm_storage_used_bytes gauge",
    ]
    for cluster in clusters:
        labels = _labels(tower_id=str(cluster.tower_id), cluster_id=cluster.cluster_id)
        lines.append(f"smartx_cluster_storage_used_bytes{{{labels}}} {cluster.used_bytes}")
        lines.append(f"smartx_cluster_storage_total_bytes{{{labels}}} {cluster.total_bytes}")
        lines.append(f"smartx_cluster_storage_allocated_bytes{{{labels}}} {cluster.allocated_bytes}")
    for vm in vms:
        labels = _labels(tower_id=str(vm.tower_id), cluster_id=vm.cluster_id, vm_id=vm.vm_id, vm_name=vm.vm_name)
        lines.append(f"smartx_vm_storage_used_bytes{{{labels}}} {vm.used_bytes}")
    return "\n".join(lines) + "\n"


def _labels(**items: str) -> str:
    return ",".join(f'{key}="{_escape_label(value)}"' for key, value in items.items())


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def merge_metrics_text(previous: str, current: str) -> str:
    """合并两份 metrics 文本：同 sample key（指标名+标签）以 current 为准。

    采集结果整体替换快照会让失败/被过滤目标的历史样本消失（49-37），
    所有采集路径落库前必须先与旧快照合并。
    """
    comments: list[str] = []
    samples: dict[str, str] = {}
    for text in (previous, current):
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                if stripped not in comments:
                    comments.append(stripped)
                continue
            samples[_sample_key(stripped)] = stripped
    return "\n".join([*comments, *samples.values()]) + ("\n" if comments or samples else "")


def _sample_key(line: str) -> str:
    return line.split(" ", 1)[0]
