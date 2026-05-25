from dataclasses import asdict
from datetime import datetime
from typing import Any

from app.collector.collector import latest_run
from app.db import get_conn, rows_to_dicts
from app.services.forecast import forecast_series
from app.services.prometheus import CLUSTER_METRICS, PrometheusQuery, VM_METRICS, load_latest_samples
from app.services.towers import list_towers


async def dashboard_summary(tower_id: int | None = None, cluster_id: str | None = None) -> dict[str, Any]:
    prom = PrometheusQuery()
    latest_samples = load_latest_samples()
    vm_used = _latest_metric_items(latest_samples, "vm", "used") or await _safe_instant(prom, VM_METRICS["used"])
    cluster_used = _latest_metric_items(latest_samples, "cluster", "used") or await _safe_instant(prom, CLUSTER_METRICS["used"])
    cluster_total = _latest_metric_items(latest_samples, "cluster", "total") or await _safe_instant(prom, CLUSTER_METRICS["total"])
    towers = list_towers()
    configured_clusters = _configured_cluster_keys(towers)
    vm_used = _filter_configured_items(vm_used, configured_clusters)
    cluster_used = _filter_configured_items(cluster_used, configured_clusters)
    cluster_total = _filter_configured_items(cluster_total, configured_clusters)
    scope = _scope(towers, tower_id, cluster_id)
    scoped_vm_used = _filter_items(vm_used, tower_id, cluster_id)
    scoped_cluster_used = _filter_items(cluster_used, tower_id, cluster_id)
    scoped_cluster_total = _filter_items(cluster_total, tower_id, cluster_id)
    total_used = sum(_value(item) for item in scoped_cluster_used)
    total_capacity = sum(_value(item) for item in scoped_cluster_total)
    scoped_towers = _filter_towers(towers, tower_id, cluster_id)
    run = latest_run()
    tower_runs = _tower_runs(towers, run, tower_id, cluster_id)
    top_vms = await _top_growing_vms(prom, latest_samples, configured_clusters, tower_id, cluster_id, 1, 100)
    return {
        "scope": scope,
        "kpis": {
            "tower_count": len(scoped_towers),
            "cluster_count": sum(len(tower.clusters) for tower in scoped_towers),
            "vm_count": len(scoped_vm_used),
            "used_bytes": total_used,
            "total_bytes": total_capacity,
            "used_ratio": total_used / total_capacity if total_capacity else 0,
        },
        "latest_run": run,
        "tower_runs": tower_runs,
        "top_vms": top_vms,
        "clusters": _top_items(scoped_cluster_used, 12),
        "towers": [tower.model_dump() for tower in towers],
    }


async def vm_list() -> list[dict[str, Any]]:
    prom = PrometheusQuery()
    latest_samples = load_latest_samples()
    used_items = _latest_metric_items(latest_samples, "vm", "used") or await _safe_instant(prom, VM_METRICS["used"])
    guest_used_items = _latest_metric_items(latest_samples, "vm", "guest_used") or await _safe_instant(prom, VM_METRICS["guest_used"])
    provisioned_items = _latest_metric_items(latest_samples, "vm", "provisioned") or await _safe_instant(prom, VM_METRICS["provisioned"])
    guest_used_by_vm = {_vm_key(item.get("metric", {})): _value(item) for item in guest_used_items}
    provisioned_by_vm = {_vm_key(item.get("metric", {})): _value(item) for item in provisioned_items}
    mapped = []
    for item in used_items:
        metric = item.get("metric", {})
        used = _value(item)
        guest_used = guest_used_by_vm.get(_vm_key(metric))
        provisioned = provisioned_by_vm.get(_vm_key(metric))
        mapped.append(
            {
                "metric": metric,
                "value": used,
                "guest_used": guest_used,
                "provisioned": provisioned,
                "used_ratio": used / provisioned if provisioned else None,
                "guest_used_ratio": guest_used / provisioned if guest_used is not None and provisioned else None,
            }
        )
    return sorted(mapped, key=lambda item: item["value"], reverse=True)[:500]


async def vm_trend(vm_id: str, metric: str = "used", days: int = 90) -> list[tuple[int, float]]:
    metric_name = VM_METRICS.get(metric, VM_METRICS["used"])
    prom = PrometheusQuery()
    result = await prom.range(f'{metric_name}{{vm_id="{vm_id}"}}', days=days)
    points = []
    if result:
        points = [(int(float(ts)), float(value)) for ts, value in result[0].get("values", [])]
    latest = _latest_vm_point(vm_id, metric)
    if latest:
        points = _with_latest_point(points, latest)
    return points


async def latest_report(tower_id: int | None = None, cluster_id: str | None = None) -> dict[str, Any]:
    prom = PrometheusQuery()
    latest_samples = load_latest_samples()
    configured_clusters = _configured_cluster_keys(list_towers())
    clusters = await prom.range(CLUSTER_METRICS["used"], days=30)
    chart_clusters = await _safe_range(prom, CLUSTER_METRICS["used"], days=365)
    totals = _latest_metric_items(latest_samples, "cluster", "total") or await prom.instant(CLUSTER_METRICS["total"])
    latest_cluster_used = _latest_metric_items(latest_samples, "cluster", "used")
    _append_latest_points(clusters, latest_cluster_used)
    _append_latest_points(chart_clusters, latest_cluster_used)
    clusters = _filter_configured_items(clusters, configured_clusters)
    chart_clusters = _filter_configured_items(chart_clusters, configured_clusters)
    totals = _filter_configured_items(totals, configured_clusters)
    clusters = _filter_items(clusters, tower_id, cluster_id)
    chart_clusters = _filter_items(chart_clusters, tower_id, cluster_id)
    totals = _filter_items(totals, tower_id, cluster_id)
    cluster_growth_rate = await _cluster_growth_rate_per_day(prom, latest_samples, configured_clusters, tower_id, cluster_id)
    capacity_by_cluster = {_cluster_key(item.get("metric", {})): _value(item) for item in totals}
    chart_points_by_cluster = {
        _cluster_key(series.get("metric", {})): _series_points(series)
        for series in chart_clusters
    }
    cluster_reports = []
    for series in clusters:
        labels = series.get("metric", {})
        key = _cluster_key(labels)
        points = _series_points(series)
        capacity = capacity_by_cluster.get(key)
        forecast = forecast_series(points, capacity)
        cluster_reports.append(
            {
                "labels": labels,
                "forecast": asdict(forecast),
                "points": chart_points_by_cluster.get(key, points),
                "total": capacity,
                "warning": capacity * 0.9 if capacity else None,
            }
        )
    day_vm_reports = await _top_growing_vm_reports(prom, latest_samples, configured_clusters, tower_id, cluster_id, 1, 100)
    month_vm_reports = await _top_growing_vm_reports(prom, latest_samples, configured_clusters, tower_id, cluster_id, 30, 100)
    return {
        "clusters": cluster_reports,
        "fastest_growing_vms": day_vm_reports,
        "day_fastest_growing_vms": day_vm_reports,
        "month_fastest_growing_vms": month_vm_reports,
        "cluster_growth_rate_per_day": cluster_growth_rate,
        "window_days": 30,
        "forecast_days": 60,
    }


async def _safe_instant(prom: PrometheusQuery, query: str) -> list[dict[str, Any]]:
    try:
        return await prom.instant(query)
    except Exception:  # noqa: BLE001 - dashboard should render empty state when Prometheus is unavailable.
        return []


def _value(item: dict[str, Any]) -> float:
    try:
        return float(item.get("value", [0, 0])[1])
    except (TypeError, ValueError, IndexError):
        return 0.0


def _top_items(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    mapped = [{"metric": item.get("metric", {}), "value": _value(item)} for item in items]
    return sorted(mapped, key=lambda item: item["value"], reverse=True)[:limit]


def _series_points(series: dict[str, Any]) -> list[tuple[int, float]]:
    points = []
    for ts, value in series.get("values", []):
        try:
            points.append((int(float(ts)), float(value)))
        except (TypeError, ValueError):
            continue
    return points


def _latest_metric_items(samples: list[dict[str, Any]], kind: str, field: str) -> list[dict[str, Any]]:
    items = []
    for sample in samples:
        if sample.get("kind") != kind:
            continue
        value = sample.get(field)
        if value is None:
            continue
        labels: dict[str, Any] = {
            "tower_id": str(sample.get("tower_id") or ""),
            "tower": str(sample.get("tower") or ""),
            "cluster_id": str(sample.get("cluster_id") or ""),
            "cluster": str(sample.get("cluster") or ""),
        }
        if kind == "vm":
            labels["vm_id"] = str(sample.get("vm_id") or "")
            labels["vm"] = str(sample.get("vm") or labels["vm_id"])
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            continue
        items.append({"metric": labels, "value": [sample.get("collected_at") or "", str(numeric_value)]})
    return items


def _latest_vm_point(vm_id: str, field: str) -> tuple[int, float] | None:
    for sample in load_latest_samples():
        if sample.get("kind") != "vm" or str(sample.get("vm_id") or "") != vm_id:
            continue
        value = sample.get(field)
        collected_at = sample.get("collected_at")
        if value is None or not collected_at:
            continue
        try:
            ts = int(datetime.fromisoformat(str(collected_at).replace("Z", "+00:00")).timestamp())
            return (ts, float(value))
        except (TypeError, ValueError):
            return None
    return None


def _append_latest_points(series: list[dict[str, Any]], latest_items: list[dict[str, Any]]) -> None:
    series_by_key = {_series_key(item.get("metric", {})): item for item in series}
    for latest in latest_items:
        key = _series_key(latest.get("metric", {}))
        value = latest.get("value", [])
        try:
            ts = int(datetime.fromisoformat(str(value[0]).replace("Z", "+00:00")).timestamp())
            point = [ts, str(float(value[1]))]
        except (TypeError, ValueError, IndexError):
            continue
        existing = series_by_key.get(key)
        if existing is None:
            copied_metric = {k: v for k, v in latest.get("metric", {}).items()}
            series.append({"metric": copied_metric, "values": [point]})
            continue
        values = existing.setdefault("values", [])
        existing["values"] = _with_latest_raw_point(values, point)


def _with_latest_raw_point(values: list[Any], point: list[Any]) -> list[Any]:
    try:
        latest = (int(float(point[0])), float(point[1]))
    except (TypeError, ValueError, IndexError):
        return values
    normalized = []
    for item in values:
        try:
            normalized.append([int(float(item[0])), str(float(item[1]))])
        except (TypeError, ValueError, IndexError):
            continue
    merged = _with_latest_point([(ts, float(value)) for ts, value in normalized], latest)
    return [[ts, str(value)] for ts, value in merged]


def _with_latest_point(points: list[tuple[int, float]], latest: tuple[int, float]) -> list[tuple[int, float]]:
    if not points:
        return [latest]
    if latest[0] > points[-1][0]:
        return [*points, latest]
    next_points = [(ts, value) for ts, value in points if ts < latest[0]]
    latest_ts = latest[0]
    if points and latest_ts <= points[-1][0]:
        latest_ts = points[-1][0] + 1
    next_points.append((latest_ts, latest[1]))
    return next_points


async def _top_growing_vms(
    prom: PrometheusQuery,
    latest_samples: list[dict[str, Any]],
    configured_clusters: set[tuple[str, str]],
    tower_id: int | None,
    cluster_id: str | None,
    period_days: int,
    limit: int,
) -> list[dict[str, Any]]:
    reports = await _top_growing_vm_reports(prom, latest_samples, configured_clusters, tower_id, cluster_id, period_days, limit)
    return [
        {
            "metric": item["labels"],
            "value": item["growth_amount"],
            "growth_amount": item["growth_amount"],
            "previous_value": item["previous_value"],
            "growth_ratio": item["growth_ratio"],
            "period_days": item["period_days"],
            "forecast": item["forecast"],
        }
        for item in reports
    ]


async def _top_growing_vm_reports(
    prom: PrometheusQuery,
    latest_samples: list[dict[str, Any]],
    configured_clusters: set[tuple[str, str]],
    tower_id: int | None,
    cluster_id: str | None,
    period_days: int,
    limit: int,
) -> list[dict[str, Any]]:
    baseline_series = await _safe_range(prom, VM_METRICS["used"], days=2, step="15m")
    latest_items = _latest_metric_items(latest_samples, "vm", "used") or await _safe_instant(prom, VM_METRICS["used"])
    previous_items = await _safe_instant(prom, f'{VM_METRICS["used"]} offset {period_days}d')
    baseline_series = _filter_configured_items(baseline_series, configured_clusters)
    latest_items = _filter_configured_items(latest_items, configured_clusters)
    previous_items = _filter_configured_items(previous_items, configured_clusters)
    baseline_series = _filter_items(baseline_series, tower_id, cluster_id)
    latest_items = _filter_items(latest_items, tower_id, cluster_id)
    previous_items = _filter_items(previous_items, tower_id, cluster_id)

    baseline_by_vm: dict[tuple[str, str, str], tuple[int, float]] = {}
    for series in baseline_series:
        labels = series.get("metric", {})
        values = series.get("values", [])
        if not values:
            continue
        try:
            baseline_by_vm[_vm_key(labels)] = (int(float(values[0][0])), float(values[0][1]))
        except (TypeError, ValueError, IndexError):
            continue

    previous_by_vm: dict[tuple[str, str, str], float] = {}
    for item in previous_items:
        labels = item.get("metric", {})
        previous_by_vm[_vm_key(labels)] = _value(item)

    mapped = []
    for item in latest_items:
        labels = item.get("metric", {})
        key = _vm_key(labels)
        baseline = baseline_by_vm.get(key)
        latest_ts = _item_timestamp(item)
        if baseline is None or latest_ts is None:
            continue
        baseline_ts, baseline_value = baseline
        current = _value(item)
        elapsed_days = max((latest_ts - baseline_ts) / 86_400, 1)
        slope_per_day = max(0.0, (current - baseline_value) / elapsed_days)
        if key not in previous_by_vm:
            continue
        previous_value = previous_by_vm[key]
        growth_amount = max(0.0, current - previous_value)
        if growth_amount <= 0:
            continue
        growth_ratio = growth_amount / previous_value if previous_value > 0 else None
        mapped.append(
            {
                "labels": labels,
                "growth_amount": growth_amount,
                "previous_value": previous_value,
                "growth_ratio": growth_ratio,
                "period_days": period_days,
                "forecast": {
                    "status": "ok",
                    "slope_per_day": slope_per_day,
                    "current": current,
                    "forecast_30d": current + slope_per_day * 30,
                    "forecast_60d": current + slope_per_day * 60,
                    "forecast_90d": current + slope_per_day * 90,
                    "forecast_180d": current + slope_per_day * 180,
                    "exhaustion_days": None,
                    "exhaustion_date": None,
                },
            }
        )
    return _ranked_growth_items(mapped, limit)


async def _cluster_growth_rate_per_day(
    prom: PrometheusQuery,
    latest_samples: list[dict[str, Any]],
    configured_clusters: set[tuple[str, str]],
    tower_id: int | None,
    cluster_id: str | None,
) -> float:
    latest_items = _latest_metric_items(latest_samples, "cluster", "used") or await _safe_instant(prom, CLUSTER_METRICS["used"])
    previous_items = await _safe_instant(prom, f'{CLUSTER_METRICS["used"]} offset 1d')
    latest_items = _filter_items(_filter_configured_items(latest_items, configured_clusters), tower_id, cluster_id)
    previous_items = _filter_items(_filter_configured_items(previous_items, configured_clusters), tower_id, cluster_id)
    previous_by_cluster = {_cluster_key(item.get("metric", {})): _value(item) for item in previous_items}

    total = 0.0
    missing_keys: set[tuple[str, str]] = set()
    for item in latest_items:
        labels = item.get("metric", {})
        key = _cluster_key(labels)
        current = _value(item)
        if key in previous_by_cluster:
            total += max(0.0, current - previous_by_cluster[key])
        else:
            missing_keys.add(key)

    if missing_keys:
        fallback = await _cluster_growth_rate_from_baseline(prom, latest_items, missing_keys, tower_id, cluster_id)
        total += fallback
    return total


async def _cluster_growth_rate_from_baseline(
    prom: PrometheusQuery,
    latest_items: list[dict[str, Any]],
    keys: set[tuple[str, str]],
    tower_id: int | None,
    cluster_id: str | None,
) -> float:
    baseline_series = _filter_items(await _safe_range(prom, CLUSTER_METRICS["used"], days=2, step="15m"), tower_id, cluster_id)
    baseline_by_cluster: dict[tuple[str, str], tuple[int, float]] = {}
    for series in baseline_series:
        labels = series.get("metric", {})
        key = _cluster_key(labels)
        if key not in keys:
            continue
        values = series.get("values", [])
        if not values:
            continue
        try:
            baseline_by_cluster[key] = (int(float(values[0][0])), float(values[0][1]))
        except (TypeError, ValueError, IndexError):
            continue

    total = 0.0
    for item in latest_items:
        labels = item.get("metric", {})
        key = _cluster_key(labels)
        baseline = baseline_by_cluster.get(key)
        latest_ts = _item_timestamp(item)
        if key not in keys or baseline is None or latest_ts is None:
            continue
        baseline_ts, baseline_value = baseline
        elapsed_days = max((latest_ts - baseline_ts) / 86_400, 1)
        total += max(0.0, (_value(item) - baseline_value) / elapsed_days)
    return total


def _ranked_growth_items(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    amount_ranked = sorted(items, key=lambda item: item["growth_amount"], reverse=True)[:limit]
    ratio_ranked = sorted(items, key=lambda item: item["growth_ratio"] or 0, reverse=True)[:limit]
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in [*amount_ranked, *ratio_ranked]:
        merged[_vm_key(item["labels"])] = item
    return sorted(merged.values(), key=lambda item: item["growth_amount"], reverse=True)


async def _safe_range(prom: PrometheusQuery, query: str, days: int, step: str = "1d") -> list[dict[str, Any]]:
    try:
        return await prom.range(query, days=days, step=step)
    except Exception:  # noqa: BLE001 - dashboard should render empty state when Prometheus is unavailable.
        return []


def _configured_cluster_keys(towers: list[Any]) -> set[tuple[str, str]]:
    return {
        (str(tower.id), str(cluster.cluster_id))
        for tower in towers
        for cluster in tower.clusters
    }


def _cluster_key(labels: dict[str, Any]) -> tuple[str, str]:
    return (str(labels.get("tower_id") or ""), str(labels.get("cluster_id") or ""))


def _vm_key(labels: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(labels.get("tower_id") or ""),
        str(labels.get("cluster_id") or ""),
        str(labels.get("vm_id") or ""),
    )


def _item_timestamp(item: dict[str, Any]) -> int | None:
    value = item.get("value", [])
    try:
        raw = value[0]
    except (TypeError, IndexError):
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        pass
    try:
        return int(datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError):
        return None


def _series_key(labels: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(labels.get("tower_id") or ""),
        str(labels.get("cluster_id") or ""),
        str(labels.get("vm_id") or ""),
    )


def _filter_configured_items(items: list[dict[str, Any]], configured_clusters: set[tuple[str, str]]) -> list[dict[str, Any]]:
    if not configured_clusters:
        return []
    return [item for item in items if _cluster_key(item.get("metric", {})) in configured_clusters]


def _filter_items(items: list[dict[str, Any]], tower_id: int | None, cluster_id: str | None) -> list[dict[str, Any]]:
    filtered = items
    if tower_id is not None:
        filtered = [item for item in filtered if str(item.get("metric", {}).get("tower_id")) == str(tower_id)]
    if cluster_id:
        filtered = [item for item in filtered if str(item.get("metric", {}).get("cluster_id")) == cluster_id]
    return filtered


def _filter_towers(towers: list[Any], tower_id: int | None, cluster_id: str | None) -> list[Any]:
    scoped = []
    for tower in towers:
        if tower_id is not None and tower.id != tower_id:
            continue
        if cluster_id:
            clusters = [cluster for cluster in tower.clusters if cluster.cluster_id == cluster_id]
        else:
            clusters = tower.clusters
        if tower_id is not None or clusters:
            tower_copy = tower.model_copy(update={"clusters": clusters})
            scoped.append(tower_copy)
    return scoped


def _scope(towers: list[Any], tower_id: int | None, cluster_id: str | None) -> dict[str, Any]:
    if tower_id is None:
        return {"type": "all", "label": "全部数据中心", "tower_id": None, "cluster_id": None}
    tower = next((item for item in towers if item.id == tower_id), None)
    if tower is None:
        return {"type": "tower", "label": f"Tower {tower_id}", "tower_id": tower_id, "cluster_id": cluster_id}
    if cluster_id:
        cluster = next((item for item in tower.clusters if item.cluster_id == cluster_id), None)
        label = f"{tower.name} / {cluster.name if cluster else cluster_id}"
        return {"type": "cluster", "label": label, "tower_id": tower_id, "cluster_id": cluster_id}
    return {"type": "tower", "label": tower.name, "tower_id": tower_id, "cluster_id": None}


def _tower_runs(
    towers: list[Any],
    run: dict[str, Any] | None,
    tower_id: int | None,
    cluster_id: str | None,
) -> list[dict[str, Any]]:
    scoped_towers = _filter_towers(towers, tower_id, cluster_id)
    if run is None:
        return [
            {
                "tower_id": tower.id,
                "tower_name": tower.name,
                "status": "unknown",
                "message": "暂无采集记录",
            }
            for tower in scoped_towers
        ]

    with get_conn() as conn:
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT collection_items.tower_id, collection_items.status, collection_items.message, towers.name AS tower_name
                FROM collection_items
                LEFT JOIN towers ON towers.id = collection_items.tower_id
                WHERE collection_items.run_id = ?
                ORDER BY collection_items.id
                """,
                (run["id"],),
            ).fetchall()
        )

    items_by_tower: dict[int, dict[str, Any]] = {}
    for row in rows:
        raw_tower_id = row.get("tower_id")
        if raw_tower_id is None:
            continue
        tower_key = int(raw_tower_id)
        if tower_key in items_by_tower:
            continue
        items_by_tower[tower_key] = row

    mapped = []
    for tower in scoped_towers:
        item = items_by_tower.get(tower.id)
        mapped.append(
            {
                "tower_id": tower.id,
                "tower_name": tower.name,
                "status": item.get("status") if item else (run.get("status") or "unknown"),
                "message": item.get("message") if item and item.get("message") else run.get("message") if len(scoped_towers) == 1 else None,
            }
        )
    return mapped
