from app.services.dashboard import _capacity_risk_summary, _cluster_capacity_items


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
