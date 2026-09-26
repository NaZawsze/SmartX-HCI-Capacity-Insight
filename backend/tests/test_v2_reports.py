import tempfile
import unittest
from pathlib import Path


SECONDS_PER_DAY = 86_400


class FakePrometheus:
    def __init__(self, now_ts: int) -> None:
        self.now_ts = now_ts

    def instant(self, query: str):
        if query.startswith("smartx_cluster_storage_total_bytes"):
            return [
                {"metric": {"tower_id": "9", "cluster_id": "orphan-cluster"}, "value": [self.now_ts, "1000"]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a"}, "value": [self.now_ts, "1000"]},
            ]
        if query.startswith("smartx_cluster_storage_used_bytes"):
            return [
                {"metric": {"tower_id": "9", "cluster_id": "orphan-cluster"}, "value": [self.now_ts, "900"]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a"}, "value": [self.now_ts, "190"]},
            ]
        if query.startswith("smartx_vm_storage_used_bytes"):
            return [
                {"metric": {"tower_id": "9", "cluster_id": "orphan-cluster", "vm_id": "vm-orphan", "vm_name": "Orphan Raw"}, "value": [self.now_ts, "900"]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-old", "vm_name": "Old Raw"}, "value": [self.now_ts, "300"]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-new", "vm_name": "New Raw"}, "value": [self.now_ts, "50"]},
            ]
        return []

    def range(self, query: str, *, start: int, end: int, step: str):
        if query.startswith("smartx_cluster_storage_used_bytes"):
            return [
                {
                    "metric": {"tower_id": "9", "cluster_id": "orphan-cluster"},
                    "values": [[self.now_ts - day * SECONDS_PER_DAY, str(900 - day)] for day in reversed(range(14))],
                },
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a"},
                    "values": [[self.now_ts - day * SECONDS_PER_DAY, str(190 - day * 10)] for day in reversed(range(14))],
                }
            ]
        if query.startswith("smartx_vm_storage_used_bytes"):
            return [
                {
                    "metric": {"tower_id": "9", "cluster_id": "orphan-cluster", "vm_id": "vm-orphan", "vm_name": "Orphan Raw"},
                    "values": [[self.now_ts - 31 * SECONDS_PER_DAY, "10"], [self.now_ts, "900"]],
                },
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-old", "vm_name": "Old Raw"},
                    "values": [[self.now_ts - 31 * SECONDS_PER_DAY, "100"], [self.now_ts, "300"]],
                },
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-new", "vm_name": "New Raw"},
                    "values": [[self.now_ts - 3600, "10"], [self.now_ts, "50"]],
                },
            ]
        return []


class RangeOnlyPrometheus(FakePrometheus):
    def instant(self, query: str):
        return []

    def range(self, query: str, *, start: int, end: int, step: str):
        if query.startswith("smartx_cluster_storage_total_bytes"):
            return [
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a"},
                    "values": [[self.now_ts - 31 * SECONDS_PER_DAY, "1000"], [self.now_ts, "1000"]],
                },
            ]
        return super().range(query, start=start, end=end, step=step)


class DuplicateClusterLabelPrometheus(FakePrometheus):
    def range(self, query: str, *, start: int, end: int, step: str):
        if query.startswith("smartx_cluster_storage_used_bytes"):
            return [
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "cluster": "Cluster A", "tower": "Tower A"},
                    "values": [[self.now_ts - 2 * SECONDS_PER_DAY, "100"], [self.now_ts - SECONDS_PER_DAY, "120"]],
                },
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a"},
                    "values": [[self.now_ts, "150"]],
                },
            ]
        return super().range(query, start=start, end=end, step=step)


class BucketedVmPrometheus(FakePrometheus):
    def instant(self, query: str):
        if query.startswith("smartx_vm_storage_used_bytes"):
            return [
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-new", "vm_name": "New Raw"}, "value": [self.now_ts, "50"]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-mid", "vm_name": "Mid Raw"}, "value": [self.now_ts, "80"]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-old", "vm_name": "Old Raw"}, "value": [self.now_ts, "300"]},
            ]
        return super().instant(query)

    def range(self, query: str, *, start: int, end: int, step: str):
        if query.startswith("smartx_vm_storage_used_bytes"):
            return [
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-new", "vm_name": "New Raw"},
                    "values": [[self.now_ts - 3 * SECONDS_PER_DAY, "10"], [self.now_ts, "50"]],
                },
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-mid", "vm_name": "Mid Raw"},
                    "values": [[self.now_ts - 10 * SECONDS_PER_DAY, "20"], [self.now_ts, "80"]],
                },
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-old", "vm_name": "Old Raw"},
                    "values": [[self.now_ts - 31 * SECONDS_PER_DAY, "100"], [self.now_ts, "300"]],
                },
            ]
        return super().range(query, start=start, end=end, step=step)


class SplitLabelVmPrometheus(FakePrometheus):
    def instant(self, query: str):
        if query.startswith("smartx_vm_storage_used_bytes"):
            return [
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-old", "vm_name": "Old Latest"}, "value": [self.now_ts, "300"]},
            ]
        return super().instant(query)

    def range(self, query: str, *, start: int, end: int, step: str):
        if query.startswith("smartx_vm_storage_used_bytes"):
            return [
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-old", "vm": "Old Display"},
                    "values": [[self.now_ts - 16 * SECONDS_PER_DAY, "100"], [self.now_ts - 15 * SECONDS_PER_DAY, "120"]],
                },
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-old", "vm_name": "Old Latest"},
                    "values": [[self.now_ts - 1 * SECONDS_PER_DAY, "250"], [self.now_ts, "300"]],
                },
            ]
        return super().range(query, start=start, end=end, step=step)


class MixedGrowthPrometheus(FakePrometheus):
    def range(self, query: str, *, start: int, end: int, step: str):
        if query.startswith("smartx_cluster_storage_used_bytes"):
            if step == "1h":
                return [
                    {
                        "metric": {"tower_id": "1", "cluster_id": "cluster-a"},
                        "values": [[self.now_ts - SECONDS_PER_DAY, "200"], [self.now_ts, "180"]],
                    }
                ]
            if start <= self.now_ts - 90 * SECONDS_PER_DAY:
                return [
                    {
                        "metric": {"tower_id": "1", "cluster_id": "cluster-a"},
                        "values": [[self.now_ts - 90 * SECONDS_PER_DAY, "0"], [self.now_ts - 45 * SECONDS_PER_DAY, "90"], [self.now_ts, "180"]],
                    }
                ]
            return [
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a"},
                    "values": [[self.now_ts - 30 * SECONDS_PER_DAY, "120"], [self.now_ts, "180"]],
                }
            ]
        return super().range(query, start=start, end=end, step=step)


class GapRecoveryVmPrometheus(FakePrometheus):
    """全历史窗口能看到老 VM 的旧样本，但近 30 天窗口只在"恢复采集当天"才有样本。

    模拟 2026-08-21~09-11 采集断档后恢复：老 VM 在报表窗口内"首次出现"。
    """

    def instant(self, query: str):
        if query.startswith("smartx_vm_storage_used_bytes"):
            return [
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-gap", "vm_name": "Gap VM"}, "value": [self.now_ts, "50"]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-new", "vm_name": "New VM"}, "value": [self.now_ts, "20"]},
            ]
        return super().instant(query)

    def range(self, query: str, *, start: int, end: int, step: str):
        if query.startswith("smartx_vm_storage_used_bytes"):
            if start <= self.now_ts - 100 * SECONDS_PER_DAY:
                return [
                    {
                        "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-gap", "vm_name": "Gap VM"},
                        "values": [[self.now_ts - 60 * SECONDS_PER_DAY, "10"], [self.now_ts - 50 * SECONDS_PER_DAY, "20"]],
                    },
                    {
                        "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-new", "vm_name": "New VM"},
                        "values": [[self.now_ts - 3600, "0"], [self.now_ts, "20"]],
                    },
                ]
            return [
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-gap", "vm_name": "Gap VM"},
                    "values": [[self.now_ts - 3600, "45"], [self.now_ts, "50"]],
                },
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-new", "vm_name": "New VM"},
                    "values": [[self.now_ts - 3600, "0"], [self.now_ts, "20"]],
                },
            ]
        return super().range(query, start=start, end=end, step=step)


class RecycledVmPrometheus(FakePrometheus):
    """本日新出现两个 VM 序列：一个正常 VM、一个回收站 VM（in-recycle-bin-*）。"""

    def instant(self, query: str):
        if query.startswith("smartx_vm_storage_used_bytes"):
            return [
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-new", "vm_name": "New VM"}, "value": [self.now_ts, "50"]},
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-bin", "vm_name": "in-recycle-bin-abc"}, "value": [self.now_ts, "10"]},
            ]
        return super().instant(query)

    def range(self, query: str, *, start: int, end: int, step: str):
        if query.startswith("smartx_vm_storage_used_bytes"):
            today = end - 3600
            return [
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-new", "vm_name": "New VM"},
                    "values": [[today, "0"], [end, "50"]],
                },
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-bin", "vm_name": "in-recycle-bin-abc"},
                    "values": [[today, "0"], [end, "10"]],
                },
            ]
        return super().range(query, start=start, end=end, step=step)


class InsufficientGrowthPrometheus(FakePrometheus):
    def range(self, query: str, *, start: int, end: int, step: str):
        if query.startswith("smartx_cluster_storage_used_bytes"):
            return [{"metric": {"tower_id": "1", "cluster_id": "cluster-a"}, "values": [[self.now_ts, "180"]]}]
        return super().range(query, start=start, end=end, step=step)


class GrowthRecycleTailPrometheus(FakePrometheus):
    """instant 没有 VM 列表（增长列表只能靠 series tail 兜底），序列里含一个有增长的回收站 VM。"""

    def instant(self, query: str):
        if query.startswith("smartx_vm_storage_used_bytes"):
            return []
        return super().instant(query)

    def range(self, query: str, *, start: int, end: int, step: str):
        if query.startswith("smartx_vm_storage_used_bytes"):
            return [
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-real", "vm_name": "Real VM"},
                    "values": [[self.now_ts - 30 * SECONDS_PER_DAY, "100"], [self.now_ts, "200"]],
                },
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-bin", "vm_name": "in-recycle-bin-abc"},
                    "values": [[self.now_ts - 30 * SECONDS_PER_DAY, "10"], [self.now_ts, "90"]],
                },
            ]
        return super().range(query, start=start, end=end, step=step)


class StaleBackfillPrometheus(FakePrometheus):
    """真实样本分布在 20~30 天前 + 14 天前（最后成功采集），其后只有回填平坦值。"""

    def range(self, query: str, *, start: int, end: int, step: str):
        if query.startswith("smartx_cluster_storage_used_bytes"):
            real = [[self.now_ts - day * SECONDS_PER_DAY, str(100 + (30 - day))] for day in range(30, 19, -1)]
            real.append([self.now_ts - 14 * SECONDS_PER_DAY, str(116)])
            backfilled_flat = [[self.now_ts - 1800, "116"], [self.now_ts, "116"]]
            return [{"metric": {"tower_id": "1", "cluster_id": "cluster-a"}, "values": real + backfilled_flat}]
        return super().range(query, start=start, end=end, step=step)


class V2ReportsTest(unittest.TestCase):
    def _seed_inventory(self, tmpdir: str, success_at: str | list[str] | None = None):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService

        settings = V2Settings(data_root=Path(tmpdir), secret_key="reports-secret")
        db = V2Database(settings)
        db.initialize()
        inventory = InventoryService(db, settings)
        tower = inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com", username="admin"))
        inventory.sync_clusters(tower.id, [ClusterInput(cluster_id="cluster-a", name="Cluster A", enabled=True)])
        with db.connection() as conn:
            conn.execute("INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (1, 'cluster-a', 'vm-old', 'Old Latest', 300)")
            conn.execute("INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (1, 'cluster-a', 'vm-new', 'New Latest', 50)")
            if success_at is not None:
                times = [success_at] if isinstance(success_at, str) else list(success_at)
                for finished_at in times:
                    conn.execute(
                        "INSERT INTO collection_runs (status, message, finished_at, success_targets_json) VALUES ('success', 'ok', ?, '[{}]')",
                        (finished_at,),
                    )
        return settings, db

    def test_latest_report_uses_v2_growth_and_forecast_contract(self) -> None:
        from app.v2.reports.service import ReportService

        now_ts = 1_700_000_000
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(
                tmpdir,
                success_at=["2023-09-15 22:13:20", "2023-10-25 22:13:20", "2023-11-13 23:13:20", "2023-11-14 22:13:20"],
            )
            report = ReportService(db, settings, prometheus=FakePrometheus(now_ts), now_ts=now_ts).latest_report(period_days=30, chart_days=90)

            self.assertEqual(report["forecast_days"], 90)
            self.assertEqual(report["window_days"], 30)
            self.assertEqual(report["chart_days"], 90)
            self.assertEqual(report["growth_rate_window_days"], 1)
            self.assertEqual(report["period_window"]["days"], 30)
            self.assertEqual(report["clusters"][0]["labels"]["tower"], "Tower A")
            self.assertEqual(report["clusters"][0]["labels"]["cluster"], "Cluster A")
            self.assertEqual(report["clusters"][0]["forecast"]["forecast_90d"], 1090.0)
            self.assertEqual(report["cluster_growth_rate"]["per_day"], 10.0)
            self.assertEqual(report["month_fastest_growing_vms"][0]["labels"]["tower"], "Tower A")
            self.assertEqual([item["labels"]["vm_id"] for item in report["month_fastest_growing_vms"]], ["vm-new"])
            ninety_day_report = ReportService(db, settings, prometheus=FakePrometheus(now_ts), now_ts=now_ts).latest_report(period_days=90, chart_days=90)
            self.assertEqual(ninety_day_report["month_fastest_growing_vms"][0]["labels"]["vm"], "Old Latest")
            self.assertEqual([item["labels"]["vm_id"] for item in ninety_day_report["month_fastest_growing_vms"]], ["vm-old", "vm-new"])
            self.assertEqual([item["labels"]["vm_id"] for item in report["day_new_vms"]], ["vm-new"])
            self.assertEqual([item["labels"]["cluster_id"] for item in report["clusters"]], ["cluster-a"])
            self.assertEqual(report["data_quality"]["status"], "warning")
            self.assertIn("actual_data_window", report["data_quality"])
            self.assertEqual(report["data_quality"]["sqlite_vm_count"], 2)

    def test_chart_days_normalization_caps_at_365(self) -> None:
        from app.v2.reports.service import _normalize_chart_days

        self.assertEqual(_normalize_chart_days(7), 7)
        self.assertEqual(_normalize_chart_days(30), 30)
        self.assertEqual(_normalize_chart_days(90), 90)
        self.assertEqual(_normalize_chart_days(365), 365)
        # Prometheus retention 400d：720 天档已移除，旧客户端传 720 回退 365。
        self.assertEqual(_normalize_chart_days(720), 365)
        self.assertEqual(_normalize_chart_days(None), 365)
        self.assertEqual(_normalize_chart_days(45), 365)
        self.assertEqual(_normalize_chart_days("bad"), 365)

    def test_latest_report_uses_range_tail_when_current_vm_instant_is_empty(self) -> None:
        from app.v2.reports.service import ReportService

        now_ts = 1_700_000_000
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            report = ReportService(db, settings, prometheus=RangeOnlyPrometheus(now_ts), now_ts=now_ts).latest_report(period_days=30, chart_days=90)

            self.assertIn("vm-old", [item["labels"]["vm_id"] for item in report["day_fastest_growing_vms"]])
            self.assertIn("vm-new", [item["labels"]["vm_id"] for item in report["month_fastest_growing_vms"]])
            ninety_day_report = ReportService(db, settings, prometheus=RangeOnlyPrometheus(now_ts), now_ts=now_ts).latest_report(period_days=90, chart_days=90)
            self.assertEqual([item["labels"]["vm_id"] for item in ninety_day_report["month_fastest_growing_vms"]], ["vm-old", "vm-new"])
            self.assertEqual(ninety_day_report["month_fastest_growing_vms"][0]["labels"]["vm"], "Old Latest")
            self.assertEqual(report["clusters"][0]["total"], 1000.0)

    def test_latest_report_merges_duplicate_cluster_series_by_identity(self) -> None:
        from app.v2.reports.service import ReportService

        now_ts = 1_700_000_000
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir, success_at="2023-11-14 22:13:20")
            report = ReportService(db, settings, prometheus=DuplicateClusterLabelPrometheus(now_ts), now_ts=now_ts).latest_report(period_days=30, chart_days=90)

            self.assertEqual(len(report["clusters"]), 1)
            self.assertEqual(report["clusters"][0]["labels"]["cluster"], "Cluster A")
            self.assertEqual(len(report["clusters"][0]["points"]), 3)
            self.assertEqual(report["clusters"][0]["forecast"]["current"], 150.0)

    def test_latest_report_uses_available_vm_growth_up_to_export_period(self) -> None:
        from app.v2.reports.service import ReportService

        now_ts = 1_700_000_000
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            with db.connection() as conn:
                conn.execute("INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (1, 'cluster-a', 'vm-mid', 'Mid Latest', 80)")
            service = ReportService(db, settings, prometheus=BucketedVmPrometheus(now_ts), now_ts=now_ts)

            seven_day = service.latest_report(period_days=7)
            fourteen_day = service.latest_report(period_days=14)
            thirty_day = service.latest_report(period_days=30)
            year_day = service.latest_report(period_days=365)

            self.assertEqual([item["labels"]["vm_id"] for item in seven_day["month_fastest_growing_vms"]], ["vm-new"])
            self.assertEqual([item["labels"]["vm_id"] for item in fourteen_day["month_fastest_growing_vms"]], ["vm-mid", "vm-new"])
            self.assertEqual([item["labels"]["vm_id"] for item in thirty_day["month_fastest_growing_vms"]], ["vm-mid", "vm-new"])
            self.assertEqual([item["labels"]["vm_id"] for item in year_day["month_fastest_growing_vms"]], ["vm-old", "vm-mid", "vm-new"])
            self.assertEqual(seven_day["vm_growth_sample_bucket"], {"min_days": 0, "max_days": 7})
            self.assertEqual(fourteen_day["vm_growth_sample_bucket"], {"min_days": 0, "max_days": 14})

    def test_latest_report_keeps_all_export_growth_vms_without_top100_truncation(self) -> None:
        from app.v2.reports.service import ReportService

        now_ts = 1_700_000_000

        class ManyVmPrometheus(FakePrometheus):
            def instant(self, query: str):
                if query.startswith("smartx_vm_storage_used_bytes"):
                    return [
                        {
                            "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": f"vm-{index:03d}", "vm_name": f"VM {index:03d}"},
                            "value": [now_ts, str((1000 + index) * 1024**3)],
                        }
                        for index in range(1, 106)
                    ]
                return super().instant(query)

            def range(self, query: str, *, start: int, end: int, step: str):
                if query.startswith("smartx_vm_storage_used_bytes"):
                    return [
                        {
                            "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": f"vm-{index:03d}", "vm_name": f"VM {index:03d}"},
                            "values": [[now_ts - 30 * SECONDS_PER_DAY, str(1000 * 1024**3)], [now_ts, str((1000 + index) * 1024**3)]],
                        }
                        for index in range(1, 106)
                    ]
                return super().range(query, start=start, end=end, step=step)

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            with db.connection() as conn:
                for index in range(1, 106):
                    conn.execute(
                        "INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (?, ?, ?, ?, ?)",
                        (1, "cluster-a", f"vm-{index:03d}", f"VM {index:03d}", (1000 + index) * 1024**3),
                    )

            report = ReportService(db, settings, prometheus=ManyVmPrometheus(now_ts), now_ts=now_ts).latest_report(period_days=30, chart_days=90)

            self.assertEqual(len(report["month_fastest_growing_vms"]), 105)
            self.assertEqual(report["month_fastest_growing_vms"][0]["labels"]["vm_id"], "vm-105")
            self.assertEqual(report["month_fastest_growing_vms"][-1]["labels"]["vm_id"], "vm-001")

    def test_latest_report_merges_split_prometheus_vm_series_for_baseline(self) -> None:
        from app.v2.reports.service import ReportService

        now_ts = 1_700_000_000
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            report = ReportService(db, settings, prometheus=SplitLabelVmPrometheus(now_ts), now_ts=now_ts).latest_report(period_days=30, chart_days=90)
            vm = report["month_fastest_growing_vms"][0]
            self.assertEqual(vm["labels"]["vm_id"], "vm-old")
            self.assertEqual(vm["previous_value"], 100.0)
            self.assertEqual(vm["growth_amount"], 200.0)
            self.assertAlmostEqual(vm["sample_span_days"], 16.0)

    def test_cluster_growth_rate_uses_day_month_and_quarter_windows_with_negative_day(self) -> None:
        from app.v2.reports.service import ReportService

        now_ts = 1_700_000_000
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(
                tmpdir,
                success_at=["2023-09-15 22:13:20", "2023-10-25 22:13:20", "2023-11-13 23:13:20", "2023-11-14 22:13:20"],
            )
            report = ReportService(db, settings, prometheus=MixedGrowthPrometheus(now_ts), now_ts=now_ts).latest_report(period_days=30, chart_days=90)

            rate = report["cluster_growth_rate"]
            self.assertEqual(rate["per_day"], -20.0)
            self.assertEqual(rate["per_month"], 60.0)
            self.assertEqual(rate["per_quarter"], 180.0)
            self.assertTrue(rate["day_sample_sufficient"])
            self.assertTrue(rate["month_sample_sufficient"])
            self.assertTrue(rate["quarter_sample_sufficient"])
            self.assertEqual(rate["day_window_days"], 1)
            self.assertEqual(rate["month_window_days"], 30)
            self.assertEqual(rate["quarter_window_days"], 90)
            self.assertEqual(report["cluster_growth_rate_per_day"], -20.0)
            self.assertEqual(report["growth_rate_window_days"], 1)

    def test_growth_vm_lists_exclude_recycle_bin_vms_from_series_tail(self) -> None:
        """49-44：增长 VM 列表也必须排除回收站 VM（series tail 兜底路径会把它们带回来）。"""
        from app.v2.reports.service import ReportService

        now_ts = 1_700_000_000
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir, success_at="2023-11-14 22:13:20")
            report = ReportService(db, settings, prometheus=GrowthRecycleTailPrometheus(now_ts), now_ts=now_ts).latest_report(period_days=30, chart_days=90)

            for key in ("day_fastest_growing_vms", "month_fastest_growing_vms", "window_fastest_growing_vms"):
                vm_ids = [item["vm_id"] for item in report[key]]
                self.assertIn("vm-real", vm_ids, key)
                self.assertNotIn("vm-bin", vm_ids, key)

    def test_new_vm_uses_full_history_first_seen_not_window_first_point(self) -> None:
        """49-42：新建判定按 vm_id 全历史最早样本，断档恢复不会把老 VM 判成新建。"""
        from app.v2.reports.service import ReportService

        now_ts = 1_700_000_000
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir, success_at="2023-11-14 22:13:20")
            report = ReportService(db, settings, prometheus=GapRecoveryVmPrometheus(now_ts), now_ts=now_ts).latest_report(period_days=30, chart_days=90)

            for key in ("day_new_vms", "month_new_vms"):
                vm_ids = [item["vm_id"] for item in report[key]]
                self.assertEqual(vm_ids, ["vm-new"], key)

    def test_new_vm_lists_exclude_recycle_bin_vms(self) -> None:
        """49-40：回收站 VM（in-recycle-bin-*）不计入本日/本月新建 VM。"""
        from app.v2.reports.service import ReportService

        now_ts = 1_700_000_000
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir, success_at="2023-11-14 22:13:20")
            report = ReportService(db, settings, prometheus=RecycledVmPrometheus(now_ts), now_ts=now_ts).latest_report(period_days=30, chart_days=90)

            for key in ("day_new_vms", "month_new_vms"):
                vm_ids = [item["vm_id"] for item in report[key]]
                self.assertIn("vm-new", vm_ids, key)
                self.assertNotIn("vm-bin", vm_ids, key)
                self.assertNotIn("in-recycle-bin-abc", [item["vm_name"] for item in report[key]], key)

    def test_cluster_growth_rate_marks_windows_insufficient_when_all_clusters_have_one_point(self) -> None:
        from app.v2.reports.service import ReportService

        now_ts = 1_700_000_000
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            report = ReportService(db, settings, prometheus=InsufficientGrowthPrometheus(now_ts), now_ts=now_ts).latest_report(period_days=30, chart_days=90)

            rate = report["cluster_growth_rate"]
            self.assertIsNone(rate["per_day"])
            self.assertIsNone(rate["per_month"])
            self.assertIsNone(rate["per_quarter"])
            self.assertFalse(rate["day_sample_sufficient"])
            self.assertFalse(rate["month_sample_sufficient"])
            self.assertFalse(rate["quarter_sample_sufficient"])

    def test_cluster_growth_rate_anchors_windows_on_last_success_and_ignores_backfilled_tail(self) -> None:
        """49-39：增长窗口锚定最后一次成功采集、只用真实样本，且窗口内采集要覆盖两端。

        回归背景：快照回填让 14 天前的旧值以当前时间戳重新进入 Prometheus，
        从"现在"回算会被平坦重复算成假的 0；只在窗口末尾有采集（断档后恢复）
        则会把跨期跳变当成该窗口的增长。
        本用例：成功采集在 60/30/14 天前，真实样本 30~20 天前 + 14 天前，其后是平坦回填值。
        期望：日窗口内采集跨度只有 4 小时（< 半个窗口）→ 样本不足；
        月/季度窗口内采集覆盖两端且真实样本充足 → 非 0 的真实增长。
        """
        from app.v2.reports.service import ReportService

        now_ts = 1_700_000_000
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir, success_at=["2023-09-15 22:13:20", "2023-10-15 22:13:20", "2023-10-31 22:13:20"])
            report = ReportService(db, settings, prometheus=StaleBackfillPrometheus(now_ts), now_ts=now_ts).latest_report(period_days=30, chart_days=90)

            rate = report["cluster_growth_rate"]
            self.assertIsNone(rate["per_day"])
            self.assertFalse(rate["day_sample_sufficient"])
            self.assertIsNotNone(rate["per_month"])
            self.assertTrue(rate["month_sample_sufficient"])
            self.assertNotEqual(rate["per_month"], 0.0)
            self.assertIsNotNone(rate["per_quarter"])
            self.assertTrue(rate["quarter_sample_sufficient"])

    def test_forecast_preserves_observed_current_when_latest_point_is_filtered_for_trend(self) -> None:
        from app.v2.reports.service import SECONDS_PER_DAY, forecast_series

        points = [(index * SECONDS_PER_DAY, 100.0 + index) for index in range(10)]
        points.append((10 * SECONDS_PER_DAY, 200.0))

        forecast = forecast_series(points, capacity=1000.0)

        self.assertEqual(forecast.current, 200.0)
        self.assertGreater(forecast.slope_per_day, 0)
        self.assertGreater(forecast.forecast_90d or 0, 200.0)

    def test_forecast_band_positive_and_brackets_noisy_actuals(self) -> None:
        from app.v2.reports.service import SECONDS_PER_DAY, forecast_series

        # 60 天线性增长 + 有界噪声（±0.1），预测带应为正且随时间展宽
        noise = [0.1 if index % 2 == 0 else -0.1 for index in range(60)]
        points = [(index * SECONDS_PER_DAY, 1000.0 + 5.0 * index + noise[index]) for index in range(60)]
        # 90 天预测从最后一个样本（第 59 天）起算，未来真值在第 149 天
        future_value = 1000.0 + 5.0 * (59 + 90) + 0.1

        forecast = forecast_series(points, capacity=100000.0)

        self.assertIsNotNone(forecast.band_half_width_now)
        self.assertIsNotNone(forecast.band_half_width_per_day)
        assert forecast.band_half_width_now is not None and forecast.band_half_width_per_day is not None
        self.assertGreater(forecast.band_half_width_now, 0)
        self.assertGreater(forecast.band_half_width_per_day, 0)
        # 90 天处区间半宽大于当前半宽（随时间展宽）
        self.assertGreater(forecast.band_half_width_now + 90 * forecast.band_half_width_per_day, forecast.band_half_width_now)
        hw_90 = forecast.band_half_width_now + 90 * forecast.band_half_width_per_day
        forecast_90 = forecast.forecast_90d or 0.0
        self.assertLessEqual(forecast_90 - hw_90, future_value)
        self.assertGreaterEqual(forecast_90 + hw_90, future_value)

    def test_forecast_band_zero_for_perfect_line(self) -> None:
        from app.v2.reports.service import SECONDS_PER_DAY, forecast_series

        points = [(index * SECONDS_PER_DAY, 500.0 + 10.0 * index) for index in range(20)]

        forecast = forecast_series(points, capacity=100000.0)

        self.assertEqual(forecast.band_half_width_now, 0.0)
        self.assertEqual(forecast.band_half_width_per_day, 0.0)

    def test_forecast_band_none_when_samples_insufficient(self) -> None:
        from app.v2.reports.service import SECONDS_PER_DAY, forecast_series

        points = [(0, 100.0), (SECONDS_PER_DAY, 110.0)]

        forecast = forecast_series(points, capacity=100000.0)

        self.assertIsNone(forecast.band_half_width_now)
        self.assertIsNone(forecast.band_half_width_per_day)

    def test_report_payload_includes_forecast_band_fields(self) -> None:
        from app.v2.reports.service import ReportService

        now_ts = 1_700_000_000
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            report = ReportService(db, settings, prometheus=FakePrometheus(now_ts), now_ts=now_ts).latest_report(period_days=30, chart_days=90)

            forecast = report["clusters"][0]["forecast"]
            self.assertIn("band_half_width_now", forecast)
            self.assertIn("band_half_width_per_day", forecast)


class CountingPrometheus:
    """记录底层调用次数的包装，用于验证 latest_report 的请求内查询去重。"""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.range_calls: list[tuple[str, int, int, str]] = []
        self.instant_calls: list[str] = []

    def range(self, query: str, *, start: int, end: int, step: str):
        self.range_calls.append((query, int(start), int(end), step))
        return self.inner.range(query, start=start, end=end, step=step)

    def instant(self, query: str):
        self.instant_calls.append(query)
        return self.inner.instant(query)


class V2ReportsQueryDedupTest(unittest.TestCase):
    def _seed_inventory(self, tmpdir: str):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService

        settings = V2Settings(data_root=Path(tmpdir), secret_key="reports-secret")
        db = V2Database(settings)
        db.initialize()
        inventory = InventoryService(db, settings)
        tower = inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com", username="admin"))
        inventory.sync_clusters(tower.id, [ClusterInput(cluster_id="cluster-a", name="Cluster A", enabled=True)])
        with db.connection() as conn:
            conn.execute("INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (1, 'cluster-a', 'vm-old', 'Old Latest', 300)")
            conn.execute("INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (1, 'cluster-a', 'vm-new', 'New Latest', 50)")
        return settings, db

    def test_latest_report_deduplicates_identical_prometheus_queries(self) -> None:
        from app.v2.reports.service import ReportService

        now_ts = 1_700_000_000
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            counting = CountingPrometheus(FakePrometheus(now_ts))
            report = ReportService(db, settings, prometheus=counting, now_ts=now_ts).latest_report(period_days=30, chart_days=90)

            self.assertTrue(counting.range_calls)
            self.assertEqual(len(counting.range_calls), len(set(counting.range_calls)), "identical range queries must hit Prometheus once per request")
            self.assertEqual(len(counting.instant_calls), len(set(counting.instant_calls)), "identical instant queries must hit Prometheus once per request")
            # 去重不得改变输出：与不包装的裸调用结果一致
            plain = ReportService(db, settings, prometheus=FakePrometheus(now_ts), now_ts=now_ts).latest_report(period_days=30, chart_days=90)
            self.assertEqual(report, plain)

    def test_latest_report_restores_original_prometheus_after_call(self) -> None:
        from app.v2.reports.service import ReportService

        now_ts = 1_700_000_000
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed_inventory(tmpdir)
            inner = FakePrometheus(now_ts)
            service = ReportService(db, settings, prometheus=inner, now_ts=now_ts)
            service.latest_report(period_days=30, chart_days=90)

            self.assertIs(service.prometheus, inner)


if __name__ == "__main__":
    unittest.main()
