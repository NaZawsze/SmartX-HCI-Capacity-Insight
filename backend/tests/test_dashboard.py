from app.services.dashboard import (
    _capacity_risk_summary,
    _cluster_capacity_items,
    _latest_vm_label_map,
    _new_vm_reports_from_series,
    _top_growing_vm_reports_from_items,
)


def test_capacity_risk_uses_highest_cluster_not_aggregate() -> None:
    used_items = [
        {"metric": {"tower_id": "1", "cluster_id": "safe", "cluster": "安全集群"}, "value": [0, "5"]},
        {"metric": {"tower_id": "1", "cluster_id": "risk", "cluster": "风险集群"}, "value": [0, "80"]},
    ]
    total_items = [
        {"metric": {"tower_id": "1", "cluster_id": "safe", "cluster": "安全集群"}, "value": [0, "100"]},
        {"metric": {"tower_id": "1", "cluster_id": "risk", "cluster": "风险集群"}, "value": [0, "100"]},
    ]

    summary = _capacity_risk_summary(_cluster_capacity_items(used_items, total_items))

    assert summary["level"] == "danger"
    assert summary["danger_count"] == 1
    assert summary["top_clusters"][0]["cluster"] == "风险集群"
    assert "风险集群" in summary["description"]


def test_capacity_risk_warns_when_any_cluster_exceeds_attention_threshold() -> None:
    summary = _capacity_risk_summary([
        {"metric": {"cluster": "关注集群"}, "used_bytes": 76, "total_bytes": 100, "used_ratio": 0.76},
        {"metric": {"cluster": "正常集群"}, "used_bytes": 10, "total_bytes": 100, "used_ratio": 0.1},
    ])

    assert summary["level"] == "warning"
    assert summary["warning_count"] == 1


def test_capacity_risk_marks_eighty_percent_as_danger() -> None:
    summary = _capacity_risk_summary([
        {"metric": {"cluster": "80集群"}, "used_bytes": 80, "total_bytes": 100, "used_ratio": 0.8},
    ])

    assert summary["level"] == "danger"
    assert summary["danger_count"] == 1


def test_capacity_risk_normal_description_does_not_call_out_highest_cluster() -> None:
    summary = _capacity_risk_summary([
        {"metric": {"cluster": "正常集群"}, "used_bytes": 10, "total_bytes": 100, "used_ratio": 0.1},
    ])

    assert summary["level"] == "normal"
    assert summary["description"] == "当前所有集群暂无明显容量风险。"


def test_month_growth_excludes_vms_with_less_than_thirty_days_of_samples() -> None:
    latest_items = [
        {
            "metric": {"tower_id": "1", "tower": "Tower", "cluster_id": "c1", "cluster": "集群", "vm_id": "old", "vm": "old-name"},
            "value": [1_700_000_000, str(200 * 1024**3)],
        },
        {
            "metric": {"tower_id": "1", "tower": "Tower", "cluster_id": "c1", "cluster": "集群", "vm_id": "new", "vm": "new-name"},
            "value": [1_700_000_000, str(200 * 1024**3)],
        },
    ]
    baseline_by_vm = {
        ("1", "c1", "old"): (1_700_000_000 - 31 * 86_400, 100 * 1024**3),
        ("1", "c1", "new"): (1_700_000_000 - 10 * 86_400, 100 * 1024**3),
    }
    previous_by_vm = {
        ("1", "c1", "old"): 100 * 1024**3,
        ("1", "c1", "new"): 100 * 1024**3,
    }

    reports = _top_growing_vm_reports_from_items(
        latest_items,
        baseline_by_vm,
        previous_by_vm,
        period_days=30,
        limit=100,
        min_sample_days=30,
        latest_label_by_vm={},
    )

    assert [item["labels"]["vm_id"] for item in reports] == ["old"]
    assert reports[0]["sample_span_days"] >= 30


def test_growth_reports_use_latest_vm_name_from_uuid_identity() -> None:
    latest_items = [
        {
            "metric": {"tower_id": "1", "tower": "Tower", "cluster_id": "c1", "cluster": "集群", "vm_id": "vm-1", "vm": "历史名称"},
            "value": [1_700_000_000, str(200 * 1024**3)],
        }
    ]
    baseline_by_vm = {("1", "c1", "vm-1"): (1_700_000_000 - 31 * 86_400, 100 * 1024**3)}
    previous_by_vm = {("1", "c1", "vm-1"): 100 * 1024**3}
    latest_label_by_vm = {
        ("1", "c1", "vm-1"): {"tower": "Tower", "cluster": "集群", "vm": "最新名称"},
    }

    reports = _top_growing_vm_reports_from_items(
        latest_items,
        baseline_by_vm,
        previous_by_vm,
        period_days=30,
        limit=100,
        min_sample_days=30,
        latest_label_by_vm=latest_label_by_vm,
    )

    assert reports[0]["labels"]["vm"] == "最新名称"
    assert reports[0]["labels"]["vm_id"] == "vm-1"


def test_new_vm_reports_are_based_on_first_metric_appearance_and_latest_name() -> None:
    latest_label_by_vm = {
        ("1", "c1", "vm-new"): {"tower": "Tower", "cluster": "集群", "vm": "新名称"},
        ("1", "c1", "vm-old"): {"tower": "Tower", "cluster": "集群", "vm": "旧名称"},
    }
    latest_value_by_vm = {
        ("1", "c1", "vm-new"): 20 * 1024**3,
        ("1", "c1", "vm-old"): 30 * 1024**3,
    }
    series = [
        {
            "metric": {"tower_id": "1", "tower": "Tower", "cluster_id": "c1", "cluster": "集群", "vm_id": "vm-new", "vm": "曾用名"},
            "values": [[1_700_000_000, str(10 * 1024**3)], [1_700_010_000, str(20 * 1024**3)]],
        },
        {
            "metric": {"tower_id": "1", "tower": "Tower", "cluster_id": "c1", "cluster": "集群", "vm_id": "vm-old", "vm": "旧名称"},
            "values": [[1_699_000_000, str(20 * 1024**3)], [1_700_010_000, str(30 * 1024**3)]],
        },
    ]

    reports = _new_vm_reports_from_series(
        series,
        start_ts=1_699_900_000,
        end_ts=1_700_020_000,
        limit=100,
        latest_label_by_vm=latest_label_by_vm,
        latest_value_by_vm=latest_value_by_vm,
    )

    assert [item["labels"]["vm_id"] for item in reports] == ["vm-new"]
    assert reports[0]["labels"]["vm"] == "新名称"
    assert reports[0]["forecast"]["current"] == 20 * 1024**3


def test_latest_vm_label_map_prefers_newest_collected_sample_name() -> None:
    labels = _latest_vm_label_map(
        [
            {
                "kind": "vm",
                "tower_id": 1,
                "tower": "Tower",
                "cluster_id": "c1",
                "cluster": "集群",
                "vm_id": "vm-1",
                "vm": "旧名称",
                "used": 1,
                "collected_at": "2026-06-01T00:00:00+08:00",
            },
            {
                "kind": "vm",
                "tower_id": 1,
                "tower": "Tower",
                "cluster_id": "c1",
                "cluster": "集群",
                "vm_id": "vm-1",
                "vm": "新名称",
                "used": 2,
                "collected_at": "2026-06-02T00:00:00+08:00",
            },
        ]
    )

    assert labels[("1", "c1", "vm-1")]["vm"] == "新名称"


def test_growth_report_limit_is_applied_after_amount_and_ratio_merge() -> None:
    latest_items = []
    baseline_by_vm = {}
    previous_by_vm = {}
    latest_ts = 1_700_000_000
    for index in range(120):
        vm_id = f"vm-{index}"
        labels = {"tower_id": "1", "tower": "Tower", "cluster_id": "c1", "cluster": "集群", "vm_id": vm_id, "vm": vm_id}
        latest_items.append({"metric": labels, "value": [latest_ts, str((1_000 + index) * 1024**3)]})
        baseline_by_vm[("1", "c1", vm_id)] = (latest_ts - 31 * 86_400, 100 * 1024**3)
        previous_by_vm[("1", "c1", vm_id)] = (100 + index) * 1024**3

    reports = _top_growing_vm_reports_from_items(
        latest_items,
        baseline_by_vm,
        previous_by_vm,
        period_days=30,
        limit=100,
        min_sample_days=30,
        latest_label_by_vm={},
    )

    assert len(reports) == 100
