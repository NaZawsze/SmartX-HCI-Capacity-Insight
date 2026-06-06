from __future__ import annotations

from typing import Any


def metric_value(series: dict[str, Any]) -> float:
    value = series.get("value")
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return _float(value[1])
    return 0.0


def range_values(series: dict[str, Any]) -> list[tuple[int, float]]:
    values = series.get("values")
    if not isinstance(values, list):
        return []
    points: list[tuple[int, float]] = []
    for item in values:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            points.append((int(float(item[0])), _float(item[1])))
    return points


def labels_match(metric: dict[str, Any], *, tower_id: int | None = None, cluster_id: str | None = None) -> bool:
    if tower_id is not None and str(metric.get("tower_id")) != str(tower_id):
        return False
    if cluster_id and str(metric.get("cluster_id")) != cluster_id:
        return False
    return True


def scoped_query(metric: str, *, tower_id: int | None = None, cluster_id: str | None = None, vm_id: str | None = None) -> str:
    labels: list[str] = []
    if tower_id is not None:
        labels.append(f'tower_id="{tower_id}"')
    if cluster_id:
        labels.append(f'cluster_id="{_escape_label(cluster_id)}"')
    if vm_id:
        labels.append(f'vm_id="{_escape_label(vm_id)}"')
    return f"{metric}{{{','.join(labels)}}}" if labels else metric


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
