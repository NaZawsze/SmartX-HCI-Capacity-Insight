"""#36/#37 ① 测试：新建 VM 判定优先用 Tower 真实创建时间（`local_created_at`）。

口径（设计 §2 ①）：以 `vm_latest.local_created_at`（Tower `Vm.local_created_at`，
探针实测格式 `2026-10-07T13:05:20.000Z`）判定「本日/本月新建」；**缺失/不可解析时回落**
Prometheus 全历史首见口径（49-42/49-43）——不猜、不填假值。

核心回归场景（采集断档恢复）：
- `vm-tower-old`：Tower 说 30 天前创建，但序列**今天才首次出现**（断档期创建）→ 旧口径会误判成
  「本日新建」，新口径必须**不**计入；
- `vm-tower-new-late`：序列 30 天前就有（vm_id 复用/历史序列），Tower 说**今天**创建 →
  新口径必须计入（Tower 优先）。
"""

import tempfile
import unittest
from pathlib import Path

SECONDS_PER_DAY = 86_400
# 2023-11-14 22:13:20 UTC；UTC 当日 0 点 = now_ts - 80000 秒，故 now_ts-3600 仍在「本日」窗口内
NOW_TS = 1_700_000_000


class CreatedAtPrometheus:
    """五台 VM，覆盖「Tower 时间 vs 序列首见」四种组合。"""

    VMS = (
        # vm_id, 名称, 序列最早样本偏移（秒，相对 NOW_TS）, instant 当前值
        ("vm-tower-old", "Tower Old", 0, 100.0),          # 序列今天首见，Tower 说 30 天前创建
        ("vm-truly-new", "Truly New", -3600, 50.0),       # 序列今天首见，Tower 说今天创建
        ("vm-tower-new-late", "Tower New Late", -30 * SECONDS_PER_DAY, 30.0),  # 序列很老，Tower 说今天创建
        ("vm-no-tower-field", "No Tower Field", -3600, 20.0),  # Tower 字段缺失 → 回落首见
        ("vm-old-both", "Old Both", -30 * SECONDS_PER_DAY, 10.0),  # 两边都老 → 不是新建
    )

    def __init__(self) -> None:
        self.range_calls: list[dict] = []

    def instant(self, query: str):
        if query.startswith("smartx_vm_storage_used_bytes"):
            return [
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": vm_id, "vm_name": name},
                    "value": [NOW_TS, str(value)],
                }
                for vm_id, name, _offset, value in self.VMS
            ]
        return []

    def range(self, query: str, *, start: int, end: int, step: str):
        self.range_calls.append({"query": query, "start": start, "end": end, "step": step})
        if not query.startswith("smartx_vm_storage_used_bytes"):
            return []
        # 全历史首见查询（400 天窗口）：返回各 VM 序列的**真实最早样本**
        if end - start > 100 * SECONDS_PER_DAY:
            return [
                {
                    "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": vm_id, "vm_name": name},
                    "values": [[NOW_TS + offset, str(value)]],
                }
                for vm_id, name, offset, value in self.VMS
            ]
        # 30 天窗口：所有 VM 都有点（否则不会进入新建候选）
        return [
            {
                "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": vm_id, "vm_name": name},
                "values": [[NOW_TS + offset, str(value * 0.5)], [NOW_TS, str(value)]],
            }
            for vm_id, name, offset, value in self.VMS
        ]


def _seed(tmpdir: str, created_at: dict[str, str | None]):
    """建库：tower/cluster + 五台 VM（vm_latest 带 local_created_at），供概览/报表共用。"""
    from app.v2.config import V2Settings
    from app.v2.database import V2Database
    from app.v2.inventory.models import ClusterInput, TowerInput
    from app.v2.inventory.service import InventoryService

    settings = V2Settings(data_root=Path(tmpdir), secret_key="created-at-secret")
    database = V2Database(settings)
    database.initialize()
    inventory = InventoryService(database, settings)
    tower = inventory.create_tower(TowerInput(name="Tower A", base_url="https://tower.example.com", username="admin"))
    inventory.sync_clusters(tower.id, [ClusterInput(cluster_id="cluster-a", name="Cluster A", enabled=True)])
    with database.connection() as conn:
        for vm_id, name, _offset, value in CreatedAtPrometheus.VMS:
            conn.execute(
                "INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes, local_created_at)"
                " VALUES (1, 'cluster-a', ?, ?, ?, ?)",
                (vm_id, name, int(value), created_at.get(vm_id)),
            )
    return settings, database


def _created_at_values() -> dict[str, str | None]:
    """Tower 侧时间：30 天前 / 今天 / 今天 / 缺失 / 30 天前。"""
    from datetime import datetime, timezone

    def iso(offset_seconds: int) -> str:
        return datetime.fromtimestamp(NOW_TS + offset_seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    return {
        "vm-tower-old": iso(-30 * SECONDS_PER_DAY),
        "vm-truly-new": iso(-600),
        "vm-tower-new-late": iso(-600),
        "vm-no-tower-field": None,
        "vm-old-both": iso(-30 * SECONDS_PER_DAY),
    }


class ParseTimestampTest(unittest.TestCase):
    def test_parses_tower_format(self):
        from app.v2.vms.new_vm import parse_iso_timestamp

        self.assertEqual(parse_iso_timestamp("1970-01-01T00:00:10.000Z"), 10)
        self.assertIsNotNone(parse_iso_timestamp("2026-10-07T13:05:20.000Z"))

    def test_returns_none_for_empty_or_invalid(self):
        from app.v2.vms.new_vm import parse_iso_timestamp

        for value in (None, "", "   ", "not-a-date", "2026-13-45T99:99:99Z"):
            self.assertIsNone(parse_iso_timestamp(value), value)


class TowerCreatedAtMapTest(unittest.TestCase):
    def test_map_reads_only_parseable_rows(self):
        from app.v2.vms.new_vm import tower_created_at_map

        with tempfile.TemporaryDirectory() as tmpdir:
            _, database = _seed(tmpdir, _created_at_values())
            with database.connection() as conn:
                conn.execute(
                    "INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes, local_created_at)"
                    " VALUES (1, 'cluster-a', 'vm-bad', 'Bad', 1, 'not-a-date')"
                )
            created = tower_created_at_map(database)
            self.assertIn((1, "cluster-a", "vm-truly-new"), created)
            self.assertNotIn((1, "cluster-a", "vm-no-tower-field"), created, "NULL 不应进表")
            self.assertNotIn((1, "cluster-a", "vm-bad"), created, "不可解析不应进表")

    def test_map_returns_empty_on_db_failure(self):
        from app.v2.vms.new_vm import tower_created_at_map

        class _Broken:
            def connection(self):
                raise RuntimeError("db down")

        self.assertEqual(tower_created_at_map(_Broken()), {})


class MergeTowerCreatedAtTest(unittest.TestCase):
    def test_tower_value_wins_and_missing_keys_keep_first_seen(self):
        from app.v2.vms.new_vm import merge_tower_created_at

        first_seen = {(1, "c", "a"): (100, 5.0), (1, "c", "b"): (200, 7.0)}
        merged = merge_tower_created_at(first_seen, {(1, "c", "a"): 999})
        self.assertEqual(merged[(1, "c", "a")], (999, 5.0), "Tower 值优先且保留首见样本值")
        self.assertEqual(merged[(1, "c", "b")], (200, 7.0), "缺失的 VM 保留首见口径")

    def test_empty_map_returns_input(self):
        from app.v2.vms.new_vm import merge_tower_created_at

        first_seen = {(1, "c", "a"): (100, 5.0)}
        self.assertIs(merge_tower_created_at(first_seen, {}), first_seen)


class NewVmCaliberIntegrationTest(unittest.TestCase):
    """概览与报表共用：Tower 创建时间优先，缺失回落首见（49-43 同源纪律保持）。"""

    def _summary_and_report(self, tmpdir: str):
        from app.v2.dashboard.service import DashboardService
        from app.v2.reports.service import ReportService

        settings, database = _seed(tmpdir, _created_at_values())
        prometheus = CreatedAtPrometheus()
        summary = DashboardService(database, settings, prometheus=prometheus, now_ts=NOW_TS).summary()
        report = ReportService(database, settings, prometheus=prometheus, now_ts=NOW_TS).latest_report(
            period_days=30, chart_days=90
        )
        return summary, report

    def test_tower_created_at_decides_new_vm_membership(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary, report = self._summary_and_report(tmpdir)
            dashboard_ids = [vm["vm_id"] for vm in summary["day_new_vms"]]
            report_ids = [item["vm_id"] for item in report["day_new_vms"]]

            # Tower 说今天创建 → 计入（含「序列很老但今天创建」的 vm-tower-new-late）
            self.assertIn("vm-truly-new", dashboard_ids)
            self.assertIn("vm-tower-new-late", dashboard_ids, "Tower 时间必须优先于序列首见")
            # Tower 字段缺失 → 回落首见口径，今天首见 ⇒ 计入
            self.assertIn("vm-no-tower-field", dashboard_ids)
            # 断档期创建的 VM（序列今天首见、Tower 说 30 天前）⇒ 不得计入
            self.assertNotIn("vm-tower-old", dashboard_ids, "断档期创建的 VM 不得误判为新建")
            self.assertNotIn("vm-old-both", dashboard_ids)
            # 概览与报表同源（49-43）
            self.assertEqual(sorted(dashboard_ids), sorted(report_ids))

    def test_first_seen_fallback_when_tower_field_absent(self):
        """所有行都无 local_created_at 时，行为必须与旧口径一致（纯回落）。"""
        created_at = {vm_id: None for vm_id, _n, _o, _v in CreatedAtPrometheus.VMS}
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.v2.dashboard.service import DashboardService

            settings, database = _seed(tmpdir, created_at)
            prometheus = CreatedAtPrometheus()
            summary = DashboardService(database, settings, prometheus=prometheus, now_ts=NOW_TS).summary()
            ids = [vm["vm_id"] for vm in summary["day_new_vms"]]
            # 回落首见：序列今天首见的三台计入（vm-tower-old / vm-truly-new / vm-no-tower-field）
            self.assertIn("vm-tower-old", ids)
            self.assertIn("vm-truly-new", ids)
            self.assertNotIn("vm-old-both", ids)


class CollectionWritesCreatedAtTest(unittest.TestCase):
    """采集侧：`local_created_at` 必须落库（含回收站 VM——创建事实不随删除失效）。"""

    def test_normalize_vm_keeps_local_created_at(self):
        from app.v2.cloudtower.client import _normalize_vm

        vm = _normalize_vm(
            {
                "id": "vm-1",
                "name": "VM 1",
                "used_size": 10,
                "local_created_at": "2026-10-07T13:05:20.000Z",
                "in_recycle_bin": True,
                "original_name": "VM 1 原名",
            }
        )
        self.assertEqual(vm["local_created_at"], "2026-10-07T13:05:20.000Z")
        self.assertIsNone(_normalize_vm({"id": "vm-2", "name": "VM 2"})["local_created_at"])

    def test_upsert_persists_local_created_at(self):
        from app.v2.collection.service import CollectionService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.metrics.formatter import VmCapacitySample

        class _NoTower:
            def collect_cluster(self, *_a, **_k):
                return {}

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="s")
            database = V2Database(settings)
            database.initialize()
            service = CollectionService(database, settings, _NoTower())
            service._upsert_latest_vm(
                VmCapacitySample(
                    tower_id=1,
                    cluster_id="c1",
                    vm_id="vm-1",
                    vm_name="VM 1",
                    used_bytes=10,
                    local_created_at="2026-10-07T13:05:20.000Z",
                )
            )
            with database.connection() as conn:
                row = conn.execute(
                    "SELECT local_created_at FROM vm_latest WHERE tower_id = 1 AND cluster_id = 'c1' AND vm_id = 'vm-1'"
                ).fetchone()
            self.assertEqual(row["local_created_at"], "2026-10-07T13:05:20.000Z")


if __name__ == "__main__":
    unittest.main()
