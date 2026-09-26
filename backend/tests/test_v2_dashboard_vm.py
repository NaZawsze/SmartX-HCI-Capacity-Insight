import tempfile
import unittest
from pathlib import Path


class FakePrometheus:
    def __init__(self) -> None:
        self.instant_queries: list[str] = []
        self.range_calls: list[dict] = []

    def instant(self, query: str):
        self.instant_queries.append(query)
        if query == "smartx_cluster_storage_used_bytes":
            return [
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a"}, "value": [100, "81"]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-b"}, "value": [100, "10"]},
            ]
        if query == "smartx_cluster_storage_total_bytes":
            return [
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a"}, "value": [100, "100"]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-b"}, "value": [100, "100"]},
            ]
        if query == "smartx_cluster_storage_allocated_bytes":
            return [{"metric": {"tower_id": "1", "cluster_id": "cluster-a"}, "value": [100, "270"]}]
        if query.startswith("smartx_vm_storage_used_bytes"):
            return [
                {"metric": {"tower_id": "9", "cluster_id": "orphan-cluster", "vm_id": "vm-orphan", "vm_name": "Orphan VM"}, "value": [100, "999"]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-1", "vm_name": "VM One Latest"}, "value": [100, "70"]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-2", "vm_name": "VM Two"}, "value": [100, "10"]},
            ]
        return []

    def range(self, query: str, *, start: int, end: int, step: str):
        self.range_calls.append({"query": query, "start": start, "end": end, "step": step})
        if end - start >= 2_500_000:
            return [
                {"metric": {"tower_id": "9", "cluster_id": "orphan-cluster", "vm_id": "vm-orphan", "vm_name": "Orphan VM"}, "values": [[start, "1"], [end, "999"]]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-1", "vm_name": "VM One Old"}, "values": [[start, "50"], [end, "70"]]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-2", "vm_name": "VM Two"}, "values": [[start, "10"], [end, "100"]]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-b", "vm_id": "vm-b", "vm_name": "Cluster B VM"}, "values": [[start, "1"], [end, "500"]]},
            ]
        if 'vm_id="vm-1"' in query:
            return [{"metric": {"vm_id": "vm-1"}, "values": [[start, "50"], [end, "70"]]}]
        if 'vm_id="vm-2"' in query:
            return [{"metric": {"vm_id": "vm-2"}, "values": [[end, "10"]]}]
        return [
            {"metric": {"tower_id": "9", "cluster_id": "orphan-cluster", "vm_id": "vm-orphan", "vm_name": "Orphan VM"}, "values": [[start, "1"], [end, "999"]]},
            {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-1", "vm_name": "VM One Old"}, "values": [[start, "50"], [end, "70"]]},
            {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-2", "vm_name": "VM Two"}, "values": [[end, "10"]]},
        ]


class EmptyPrometheus(FakePrometheus):
    def instant(self, query: str):
        self.instant_queries.append(query)
        return []


class RangeOnlyNewVmPrometheus(FakePrometheus):
    def instant(self, query: str):
        self.instant_queries.append(query)
        if query == "smartx_cluster_storage_used_bytes":
            return [{"metric": {"tower_id": "1", "cluster_id": "cluster-a"}, "value": [200, "81"]}]
        if query == "smartx_cluster_storage_total_bytes":
            return [{"metric": {"tower_id": "1", "cluster_id": "cluster-a"}, "value": [200, "100"]}]
        if query.startswith("smartx_vm_storage_used_bytes"):
            return []
        return []

    def range(self, query: str, *, start: int, end: int, step: str):
        self.range_calls.append({"query": query, "start": start, "end": end, "step": step})
        if query == "smartx_cluster_storage_used_bytes":
            return [{"metric": {"tower_id": "1", "cluster_id": "cluster-a"}, "values": [[start, "70"], [end, "81"]]}]
        if query.startswith("smartx_vm_storage_used_bytes"):
            today = end - 3600
            return [
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-1", "vm_name": "Existing VM"}, "values": [[start, "50"], [end, "70"]]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-new-a", "vm_name": "Range New A"}, "values": [[today, "0"], [end, "8"]]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-new-b", "vm_name": "Range New B"}, "values": [[today + 60, "0"], [end, "4"]]},
            ]
        return []


class GapAndRecycleVmPrometheus(FakePrometheus):
    """全历史窗口能看到老 VM 的旧样本，但 30 天窗口内它"看起来"今天才出现；另含一个回收站 VM。

    模拟采集断档恢复（49-42）与回收站改名（49-40）两类"假新建"。
    """

    def range(self, query: str, *, start: int, end: int, step: str):
        self.range_calls.append({"query": query, "start": start, "end": end, "step": step})
        if query.startswith("smartx_vm_storage_used_bytes"):
            if end - start > 100 * 86_400:
                return [
                    {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-gap", "vm_name": "Gap VM"}, "values": [[end - 60 * 86_400, "10"], [end - 50 * 86_400, "20"]]},
                    {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-new", "vm_name": "New VM"}, "values": [[end, "20"]]},
                    {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-bin", "vm_name": "in-recycle-bin-abc"}, "values": [[end, "10"]]},
                ]
            return [
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-gap", "vm_name": "Gap VM"}, "values": [[end, "45"]]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-new", "vm_name": "New VM"}, "values": [[end - 3600, "10"], [end, "20"]]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-bin", "vm_name": "in-recycle-bin-abc"}, "values": [[end - 3600, "5"], [end, "10"]]},
            ]
        return super().range(query, start=start, end=end, step=step)


class MultiRiskPrometheus(FakePrometheus):
    def instant(self, query: str):
        self.instant_queries.append(query)
        if query == "smartx_cluster_storage_used_bytes":
            return [
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a"}, "value": [100, str(880)]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-b"}, "value": [100, str(760)]},
            ]
        if query == "smartx_cluster_storage_total_bytes":
            return [
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a"}, "value": [100, str(1000)]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-b"}, "value": [100, str(1000)]},
            ]
        if query.startswith("smartx_vm_storage_used_bytes"):
            return []
        return []

    def range(self, query: str, *, start: int, end: int, step: str):
        self.range_calls.append({"query": query, "start": start, "end": end, "step": step})
        if query == "smartx_cluster_storage_used_bytes":
            return [
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a"}, "values": [[start, str(700)], [end, str(880)]]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-b"}, "values": [[start, str(680)], [end, str(760)]]},
            ]
        return []


class SplitClusterSeriesPrometheus(MultiRiskPrometheus):
    def range(self, query: str, *, start: int, end: int, step: str):
        self.range_calls.append({"query": query, "start": start, "end": end, "step": step})
        if query == "smartx_cluster_storage_used_bytes":
            return [
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "source": "usable"}, "values": [[start, str(700)], [end, str(880)]]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "source": "duplicate-tail"}, "values": [[start + 1, str(900)], [end, str(879)]]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-b"}, "values": [[start, str(680)], [end, str(760)]]},
            ]
        return []


class V2DashboardVmTest(unittest.TestCase):
    def _seed_inventory(self, tmpdir: str):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService

        settings = V2Settings(data_root=Path(tmpdir), secret_key="dashboard-secret")
        db = V2Database(settings)
        db.initialize()
        inventory = InventoryService(db, settings)
        tower = inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com", username="admin"))
        inventory.sync_clusters(
            tower.id,
            [
                ClusterInput(cluster_id="cluster-a", name="Cluster A", enabled=True),
                ClusterInput(cluster_id="cluster-b", name="Cluster B", enabled=True),
            ],
        )
        with db.connection() as conn:
            conn.execute(
                "INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (1, 'cluster-a', 'vm-1', 'VM One Latest', 70)"
            )
            conn.execute("INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (1, 'cluster-a', 'vm-2', 'VM Two', 10)")
            conn.execute("INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (9, 'orphan-cluster', 'vm-orphan', 'Orphan VM', 999)")
            conn.execute(
                """
                INSERT INTO vm_volumes (
                    tower_id, cluster_id, vm_id, volume_id, name, path, size_bytes,
                    used_bytes, storage_policy, replica_num, thin_provision
                )
                VALUES (1, 'cluster-a', 'vm-1', 'vol-1', 'Root', '/root', 100, 60, 'Replica-2', 2, 1)
                """
            )
            conn.execute("INSERT INTO collection_runs (status, message, finished_at) VALUES ('success', 'ok', '2026-06-06 02:00:00')")
        return settings, db

    def test_dashboard_summary_uses_single_cluster_risk_and_latest_vm_names(self) -> None:
        from app.v2.dashboard.service import DashboardService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            summary = DashboardService(db, settings, prometheus=FakePrometheus(), now_ts=200).summary()

            self.assertEqual(summary["capacity_risk"]["level"], "high")
            self.assertEqual(summary["capacity_risk"]["title"], "容量高风险")
            self.assertEqual(summary["capacity_risk"]["danger_count"], 1)
            self.assertEqual(summary["capacity_risk"]["warning_count"], 0)
            self.assertIn("Cluster A", summary["capacity_risk"]["message"])
            self.assertEqual(summary["capacity_risk"]["top_clusters"][0]["cluster"], "Cluster A")
            self.assertEqual(summary["capacity_risk"]["top_clusters"][0]["used_ratio"], 0.81)
            self.assertEqual(summary["capacity_risk"]["risk_clusters"][0]["cluster"], "Cluster A")
            self.assertEqual(summary["capacity_risk"]["risk_clusters"][0]["risk_level"], "high")
            # 49-45：增长列表改用报表同一实现（当前值取 instant 而非序列末端），vm-2 的
            # instant(10) 与基线(10)相同 → 增长为 0 不再入列；vm-1 增长 70-50=20。
            self.assertEqual([vm["vm_id"] for vm in summary["capacity_risk"]["top_clusters"][0]["top_growth_vms"]], ["vm-1"])
            self.assertEqual(summary["capacity_risk"]["top_clusters"][0]["top_growth_vms"][0]["growth_amount"], 20)
            self.assertEqual(summary["capacity_risk"]["top_clusters"][0]["top_growth_vms"][0]["vm_name"], "VM One Latest")
            self.assertEqual(summary["totals"], {"towers": 1, "clusters": 2, "vms": 2})
            self.assertEqual(summary["storage"]["used_bytes"], 91)
            self.assertEqual(summary["storage"]["total_bytes"], 200)
            self.assertEqual(summary["day_fastest_growing_vms"][0]["vm_name"], "VM One Latest")
            self.assertEqual(summary["day_fastest_growing_vms"][0]["growth_amount"], 20)
            self.assertEqual(summary["day_new_vms"], [])

    def test_dashboard_summary_exposes_allocated_capacity_ratio_over_total(self) -> None:
        """49-36：已分配容量与比例（分母为总容量，可 > 100%）。"""
        from app.v2.dashboard.service import DashboardService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            summary = DashboardService(db, settings, prometheus=FakePrometheus(), now_ts=200).summary()

            self.assertEqual(summary["storage"]["allocated_bytes"], 270)
            self.assertEqual(summary["storage"]["allocated_ratio"], 270 / 200)
            self.assertEqual(summary["kpis"]["allocated_bytes"], 270)
            self.assertEqual(summary["kpis"]["allocated_ratio"], 270 / 200)
            clusters = {cluster["cluster_id"]: cluster for cluster in summary["clusters"]}
            self.assertEqual(clusters["cluster-a"]["allocated_bytes"], 270)
            self.assertEqual(clusters["cluster-b"]["allocated_bytes"], 0)

    def test_dashboard_capacity_risk_summarizes_multiple_risk_clusters(self) -> None:
        from app.v2.dashboard.service import DashboardService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            summary = DashboardService(db, settings, prometheus=MultiRiskPrometheus(), now_ts=30 * 86400).summary()

            risk = summary["capacity_risk"]
            self.assertEqual(risk["level"], "high")
            self.assertEqual(risk["danger_count"], 1)
            self.assertEqual(risk["warning_count"], 1)
            self.assertIn("1 个集群高风险，1 个集群需关注", risk["message"])
            self.assertIn("最短 20 天后存储耗尽", risk["message"])
            self.assertEqual([cluster["cluster"] for cluster in risk["risk_clusters"]], ["Cluster A", "Cluster B"])
            self.assertEqual(risk["risk_clusters"][0]["risk_level"], "high")
            self.assertEqual(round(risk["risk_clusters"][0]["exhaustion_days"]), 20)
            self.assertEqual(risk["risk_clusters"][1]["risk_level"], "warning")

    def test_dashboard_day_new_vms_uses_range_series_when_instant_vm_list_is_empty(self) -> None:
        from app.v2.dashboard.service import DashboardService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            with db.connection() as conn:
                conn.execute(
                    "INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (1, 'cluster-a', 'vm-new-a', 'Range New A Latest', 8)"
                )
                conn.execute(
                    "INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (1, 'cluster-a', 'vm-new-b', 'Range New B Latest', 4)"
                )

            summary = DashboardService(db, settings, prometheus=RangeOnlyNewVmPrometheus(), now_ts=200).summary()

            self.assertEqual([vm["vm_id"] for vm in summary["day_new_vms"]], ["vm-new-b", "vm-new-a"])
            self.assertEqual([vm["vm_name"] for vm in summary["day_new_vms"]], ["Range New B Latest", "Range New A Latest"])
            self.assertEqual([vm["current_bytes"] for vm in summary["day_new_vms"]], [4.0, 8.0])

    def test_dashboard_and_report_day_new_vms_share_first_seen_and_recycle_rules(self) -> None:
        """49-43：概览与报表的「本日新建 VM」必须同源（vm_id 全历史首见 + 排除回收站）。"""
        from app.v2.dashboard.service import DashboardService
        from app.v2.reports.service import ReportService

        now_ts = 1_700_000_000
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            fake = GapAndRecycleVmPrometheus()
            summary = DashboardService(db, settings, prometheus=fake, now_ts=now_ts).summary()
            report = ReportService(db, settings, prometheus=fake, now_ts=now_ts).latest_report(period_days=30, chart_days=90)

            dashboard_ids = [vm["vm_id"] for vm in summary["day_new_vms"]]
            report_ids = [item["vm_id"] for item in report["day_new_vms"]]
            self.assertEqual(dashboard_ids, ["vm-new"])
            self.assertEqual(report_ids, ["vm-new"])
            self.assertEqual(dashboard_ids, report_ids)
            self.assertNotIn("vm-gap", dashboard_ids)
            self.assertNotIn("vm-bin", dashboard_ids)

            # 概览「增长最快 VM」也必须排除回收站 VM（49-44 审计项）；
            # 概览 payload 只暴露日增长（month 列表仅用于风险计算，同一实现）
            for key in ("day_fastest_growing_vms", "top_vms"):
                growth_ids = [vm["vm_id"] for vm in summary[key]]
                self.assertIn("vm-new", growth_ids, key)
                self.assertNotIn("vm-bin", growth_ids, key)

    def test_dashboard_and_report_growth_vms_share_same_implementation(self) -> None:
        """49-45：概览与报表的「增长最快 VM」结果（vm_id、顺序、增长值）必须一致。"""
        from app.v2.dashboard.service import DashboardService
        from app.v2.reports.service import ReportService

        now_ts = 1_700_000_000

        def pairs(items):
            return [(item["vm_id"], round(float(item["growth_amount"]), 6)) for item in items]

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            fake = GapAndRecycleVmPrometheus()
            dashboard = DashboardService(db, settings, prometheus=fake, now_ts=now_ts)
            summary = dashboard.summary()
            report = ReportService(db, settings, prometheus=fake, now_ts=now_ts).latest_report(period_days=30, chart_days=90)

            dash_day = pairs(summary["day_fastest_growing_vms"])
            self.assertEqual(dash_day, pairs(report["day_fastest_growing_vms"]))

            enabled = dashboard._enabled_cluster_scope(tower_id=None, cluster_id=None)
            dash_month = pairs(dashboard._period_fastest_growing_vms(tower_id=None, cluster_id=None, enabled_scope=enabled, days=30, limit=100))
            self.assertEqual(dash_month, pairs(report["month_fastest_growing_vms"]))

            # 回收站 VM 在两边都不出现
            for items in (summary["day_fastest_growing_vms"], report["day_fastest_growing_vms"], report["month_fastest_growing_vms"]):
                self.assertTrue(all("in-recycle-bin" not in (item.get("vm_name") or "") for item in items))

    def test_dashboard_capacity_risk_uses_merged_cluster_series_for_exhaustion_days(self) -> None:
        from app.v2.dashboard.service import DashboardService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            summary = DashboardService(db, settings, prometheus=SplitClusterSeriesPrometheus(), now_ts=30 * 86400).summary()

            risk = summary["capacity_risk"]
            self.assertIn("天后存储耗尽", risk["message"])
            self.assertIsNotNone(risk["risk_clusters"][0]["exhaustion_days"])

    def test_dashboard_and_vm_list_ignore_metrics_outside_enabled_clusters_by_default(self) -> None:
        from app.v2.dashboard.service import DashboardService
        from app.v2.vms.service import VmService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            prometheus = FakePrometheus()

            summary = DashboardService(db, settings, prometheus=prometheus, now_ts=200).summary()
            vms = VmService(db, settings, prometheus=prometheus, now_ts=200).list_vms()

            self.assertEqual(summary["totals"], {"towers": 1, "clusters": 2, "vms": 2})
            self.assertNotIn("vm-orphan", {vm["vm_id"] for vm in summary["day_fastest_growing_vms"]})
            self.assertEqual([vm["vm_id"] for vm in vms], ["vm-1", "vm-2"])

    def test_vm_list_and_trend_use_stable_identity_and_latest_names(self) -> None:
        from app.v2.vms.service import VmService

        prometheus = FakePrometheus()
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            service = VmService(db, settings, prometheus=prometheus, now_ts=200)

            vms = service.list_vms(tower_id=1, cluster_id="cluster-a")
            trend = service.trend(vm_id="vm-1", tower_id=1, cluster_id="cluster-a", days=1)

            self.assertEqual(vms[0]["vm_name"], "VM One Latest")
            self.assertEqual(vms[0]["cluster_name"], "Cluster A")
            self.assertEqual(trend["vm_name"], "VM One Latest")
            self.assertEqual(trend["points"], [{"timestamp": -86200, "used_bytes": 50.0}, {"timestamp": 200, "used_bytes": 70.0}])
            self.assertIn('tower_id="1"', prometheus.range_calls[-1]["query"])
            self.assertIn('cluster_id="cluster-a"', prometheus.range_calls[-1]["query"])
            self.assertIn('vm_id="vm-1"', prometheus.range_calls[-1]["query"])

    def test_vm_trend_marks_collection_gap_only_for_vm_cluster_scope(self) -> None:
        from app.v2.vms.service import VmService

        base_ts = 1_765_065_600  # 2025-12-07 00:00:00 UTC

        class GapPrometheus(FakePrometheus):
            def range(self, query: str, *, start: int, end: int, step: str):
                self.range_calls.append({"query": query, "start": start, "end": end, "step": step})
                return [{"metric": {"vm_id": "vm-1"}, "values": [[base_ts - 2 * 86400, "50"], [base_ts - 86400, "60"], [base_ts, "70"]]}]

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            with db.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO collection_runs (
                        status, message, started_at, finished_at, trigger, success_targets_json, failed_targets_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "partial_failed",
                        "cluster b failed",
                        "2025-12-06 02:10:00",
                        "2025-12-06 02:11:00",
                        "scheduled",
                        '[{"tower_id": 1, "tower_name": "Tower A", "cluster_id": "cluster-a", "cluster_name": "Cluster A"}]',
                        '[{"tower_id": 1, "tower_name": "Tower A", "cluster_id": "cluster-b", "cluster_name": "Cluster B", "message": "failed"}]',
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO collection_runs (
                        status, message, started_at, finished_at, trigger, success_targets_json, failed_targets_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "partial_failed",
                        "cluster a failed",
                        "2025-12-07 02:10:00",
                        "2025-12-07 02:11:00",
                        "scheduled",
                        '[{"tower_id": 1, "tower_name": "Tower A", "cluster_id": "cluster-b", "cluster_name": "Cluster B"}]',
                        '[{"tower_id": 1, "tower_name": "Tower A", "cluster_id": "cluster-a", "cluster_name": "Cluster A", "message": "failed"}]',
                    ),
                )

            trend = VmService(db, settings, prometheus=GapPrometheus(), now_ts=base_ts).trend(vm_id="vm-1", tower_id=1, cluster_id="cluster-a", days=7)

            self.assertEqual(trend["latest_success_at"], "2025-12-06 02:11:00")
            self.assertEqual(trend["latest_collection_status"], "failed")
            self.assertEqual(trend["data_freshness"], "stale")
            self.assertTrue(trend["has_collection_gap"])
            self.assertEqual(trend["gap_dates"], ["2025-12-07"])

    def test_vm_list_and_dashboard_fall_back_to_sqlite_latest_when_prometheus_instant_is_empty(self) -> None:
        from app.v2.dashboard.service import DashboardService
        from app.v2.vms.service import VmService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            prometheus = EmptyPrometheus()
            vms = VmService(db, settings, prometheus=prometheus, now_ts=200).list_vms(tower_id=1, cluster_id="cluster-a")
            summary = DashboardService(db, settings, prometheus=prometheus, now_ts=200).summary(tower_id=1, cluster_id="cluster-a")

            self.assertEqual([item["vm_id"] for item in vms], ["vm-1", "vm-2"])
            self.assertEqual(vms[0]["vm_name"], "VM One Latest")
            self.assertEqual(vms[0]["used_bytes"], 70)
            self.assertEqual(summary["totals"], {"towers": 1, "clusters": 1, "vms": 2})
            self.assertEqual(len(summary["towers"]), 1)
            self.assertEqual(summary["towers"][0]["clusters"][0]["cluster_id"], "cluster-a")
            self.assertEqual(summary["day_new_vms"], [])

    def test_vm_detail_and_volumes_return_structured_latest_data(self) -> None:
        from app.v2.vms.service import VmService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            service = VmService(db, settings, prometheus=FakePrometheus(), now_ts=200)

            detail = service.detail(vm_id="vm-1", tower_id=1, cluster_id="cluster-a")
            volumes = service.volumes(vm_id="vm-1", tower_id=1, cluster_id="cluster-a")

            self.assertEqual(detail["vm_name"], "VM One Latest")
            self.assertEqual(detail["used_bytes"], 70)
            self.assertEqual(volumes[0]["volume_id"], "vol-1")
            self.assertEqual(volumes[0]["storage_policy"], "Replica-2")
            self.assertEqual(volumes[0]["replica_num"], 2)
            self.assertTrue(volumes[0]["thin_provision"])

    def test_all_volumes_return_vm_and_cluster_context(self) -> None:
        from app.v2.vms.service import VmService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            service = VmService(db, settings, prometheus=FakePrometheus(), now_ts=200)

            volume_sets = service.all_volumes(tower_id=1, cluster_id="cluster-a")

            self.assertEqual(len(volume_sets), 1)
            self.assertEqual(volume_sets[0]["tower_id"], 1)
            self.assertEqual(volume_sets[0]["cluster_id"], "cluster-a")
            self.assertEqual(volume_sets[0]["cluster_name"], "Cluster A")
            self.assertEqual(volume_sets[0]["vm_id"], "vm-1")
            self.assertEqual(volume_sets[0]["vm_name"], "VM One Latest")
            self.assertEqual(volume_sets[0]["volumes"][0]["used_bytes"], 60)

    def test_all_volumes_pagination_sort_and_total(self) -> None:
        from app.v2.vms.service import VmService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            with db.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO vm_volumes (tower_id, cluster_id, vm_id, volume_id, name, path, size_bytes, used_bytes, storage_policy, ec_k, ec_m)
                    VALUES (1, 'cluster-a', 'vm-2', 'vol-big', 'Big', '/big', 300, 90, 'EC-2+1', 2, 1)
                    """
                )
            service = VmService(db, settings, prometheus=FakePrometheus(), now_ts=200)

            page = service.all_volumes(tower_id=1, cluster_id="cluster-a", page=1, page_size=1, sort="used", order="desc")
            self.assertEqual(page["total"], 2)
            self.assertEqual(page["page"], 1)
            self.assertEqual(page["page_size"], 1)
            self.assertEqual([row["volume_id"] for row in page["volumes"]], ["vol-big"])
            self.assertEqual(page["volumes"][0]["vm_name"], "VM Two")
            self.assertEqual(page["volumes"][0]["cluster_name"], "Cluster A")

            page2 = service.all_volumes(tower_id=1, cluster_id="cluster-a", page=2, page_size=1, sort="used", order="desc")
            self.assertEqual([row["volume_id"] for row in page2["volumes"]], ["vol-1"])
            self.assertEqual(page2["volumes"][0]["vm_name"], "VM One Latest")

            # occupied 口径：vol-big EC2+1 → 90*1.5=135；vol-1 2 副本 → 60*2=120；vol-thin 1 副本 → 100*1=100。
            # used 降序是 [vol-thin(100), vol-big(90), vol-1(60)]，occupied 降序是 [vol-big, vol-1, vol-thin]——排序键独立生效。
            with db.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO vm_volumes (tower_id, cluster_id, vm_id, volume_id, name, path, size_bytes, used_bytes, storage_policy, replica_num, thin_provision)
                    VALUES (1, 'cluster-a', 'vm-1', 'vol-thin', 'Thin', '/thin', 400, 100, 'Replica-1', 1, 1)
                    """
                )
            used_desc = service.all_volumes(tower_id=1, cluster_id="cluster-a", page=1, page_size=3, sort="used", order="desc")
            self.assertEqual([row["volume_id"] for row in used_desc["volumes"]], ["vol-thin", "vol-big", "vol-1"])
            occupied_desc = service.all_volumes(tower_id=1, cluster_id="cluster-a", page=1, page_size=3, sort="occupied", order="desc")
            self.assertEqual(occupied_desc["total"], 3)
            self.assertEqual([row["volume_id"] for row in occupied_desc["volumes"]], ["vol-big", "vol-1", "vol-thin"])

            vm_sorted = service.all_volumes(tower_id=1, cluster_id="cluster-a", page=1, page_size=3, sort="vm", order="asc")
            self.assertEqual([row["vm_name"] for row in vm_sorted["volumes"]], ["VM One Latest", "VM One Latest", "VM Two"])

            unfiltered = service.all_volumes(page=1, page_size=1000)
            self.assertEqual(unfiltered["total"], 3)

    def test_usage_summary_aggregates_per_vm_with_frontend_skip_semantics(self) -> None:
        from app.v2.vms.service import VmService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            with db.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO vm_volumes (tower_id, cluster_id, vm_id, volume_id, name, path, size_bytes, used_bytes)
                    VALUES (1, 'cluster-a', 'vm-2', 'vol-a', 'A', '/a', 200, 40)
                    """
                )
                # 应跳过的行：size 为 NULL、used 为负（与前端逐卷 skip 口径一致）。
                conn.execute(
                    """
                    INSERT INTO vm_volumes (tower_id, cluster_id, vm_id, volume_id, name, path, size_bytes, used_bytes)
                    VALUES (1, 'cluster-a', 'vm-2', 'vol-invalid-size', 'Bad', '/bad', NULL, 999)
                    """
                )
                conn.execute(
                    """
                    INSERT INTO vm_volumes (tower_id, cluster_id, vm_id, volume_id, name, path, size_bytes, used_bytes)
                    VALUES (1, 'cluster-a', 'vm-2', 'vol-negative', 'Neg', '/neg', 100, -5)
                    """
                )
            service = VmService(db, settings, prometheus=FakePrometheus(), now_ts=200)

            usages = {item["vm_id"]: item for item in service.usage_summary(tower_id=1, cluster_id="cluster-a")}

            self.assertEqual(usages["vm-1"]["used_bytes"], 60.0)
            self.assertEqual(usages["vm-1"]["provisioned_bytes"], 100.0)
            self.assertEqual(usages["vm-2"]["used_bytes"], 40.0)
            self.assertEqual(usages["vm-2"]["provisioned_bytes"], 200.0)

            all_usages = {item["vm_id"] for item in service.usage_summary()}
            self.assertEqual(all_usages, {"vm-1", "vm-2"})


    def test_dashboard_collection_freshness_exposes_last_success_and_stale_state(self) -> None:
        """49-37：看板 collection payload 需带最后成功采集时间与新鲜度三态。"""
        from datetime import datetime, timezone

        from app.v2.dashboard.service import DashboardService
        from app.v2.data_quality.service import freshness_threshold_minutes

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            last_success = datetime(2026, 6, 6, 2, 0, tzinfo=timezone.utc)
            threshold = freshness_threshold_minutes(db)

            fresh = DashboardService(db, settings, prometheus=FakePrometheus(), now_ts=int(last_success.timestamp()) + 60).summary()["collection"]
            self.assertEqual(fresh["last_success_at"], "2026-06-06 02:00:00")
            self.assertEqual(fresh["threshold_minutes"], threshold)
            self.assertEqual(fresh["data_freshness"], "fresh")

            stale = DashboardService(db, settings, prometheus=FakePrometheus(), now_ts=int(last_success.timestamp()) + (threshold + 1) * 60).summary()["collection"]
            self.assertEqual(stale["data_freshness"], "stale")

            with db.connection() as conn:
                conn.execute("UPDATE collection_runs SET status = 'failed' WHERE id = (SELECT MAX(id) FROM collection_runs)")
            unknown = DashboardService(db, settings, prometheus=FakePrometheus(), now_ts=int(last_success.timestamp())).summary()["collection"]
            self.assertIsNone(unknown["last_success_at"])
            self.assertEqual(unknown["data_freshness"], "unknown")


if __name__ == "__main__":
    unittest.main()
