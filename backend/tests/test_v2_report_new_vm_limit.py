"""#28 报表 payload 瘦身测试：新建 VM 明细列表按 `new_vm_limit` 裁剪，计数保持全量。

设计：docs/superpowers/specs/2026-10-14-report-payload-slimming-design.md
口径：
- 页面路径默认只返回前 50 条（该列表曾是 payload 最大块，`.3` 实测 month_new_vms 277KB ≈ 63%）；
- **计数（day_new_vm_count / month_new_vm_count）始终是全量口径**；
- `new_vm_limit=all` / 0 / 负值 ⇒ 全量（导出走这条）；非法值回落默认 50。
"""

import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from tests.test_v2_reports import FakePrometheus  # noqa: E402

SECONDS_PER_DAY = 86_400
NEW_VM_COUNT = 60


class ManyNewVmsPrometheus(FakePrometheus):
    """1 台老 VM（31 天前就有样本）+ 60 台今天首次出现的 VM。

    `first_seen_ts` 由调用方按业务时区的「今日 0 点」之后给入——否则样本落在
    零点之前就不会被算成"今日新建"（#28 首版 fixture 就踩了这个边界）。
    """

    def __init__(self, now_ts: int, first_seen_ts: int) -> None:
        super().__init__(now_ts)
        self.first_seen_ts = first_seen_ts

    def _vm_series(self) -> list[dict]:
        series = [
            {
                "metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-old", "vm_name": "Old Raw"},
                "values": [[self.now_ts - 31 * SECONDS_PER_DAY, "100"], [self.now_ts, "300"]],
            }
        ]
        for index in range(NEW_VM_COUNT):
            series.append(
                {
                    "metric": {
                        "tower_id": "1",
                        "cluster_id": "cluster-a",
                        "vm_id": f"vm-new-{index:03d}",
                        "vm_name": f"New {index:03d}",
                    },
                    "values": [[self.first_seen_ts, "10"], [self.now_ts, "50"]],
                }
            )
        return series

    def instant(self, query: str):
        if query.startswith("smartx_vm_storage_used_bytes"):
            items = [
                {"metric": {"tower_id": "1", "cluster_id": "cluster-a", "vm_id": "vm-old", "vm_name": "Old Raw"}, "value": [self.now_ts, "300"]}
            ]
            items += [
                {
                    "metric": {
                        "tower_id": "1",
                        "cluster_id": "cluster-a",
                        "vm_id": f"vm-new-{index:03d}",
                        "vm_name": f"New {index:03d}",
                    },
                    "value": [self.now_ts, "50"],
                }
                for index in range(NEW_VM_COUNT)
            ]
            return items
        return super().instant(query)

    def range(self, query: str, *, start: int, end: int, step: str):
        if query.startswith("smartx_vm_storage_used_bytes"):
            return self._vm_series()
        return super().range(query, start=start, end=end, step=step)


class NewVmLimitNormalizeTest(unittest.TestCase):
    def test_normalization_matrix(self) -> None:
        from app.v2.reports.service import (
            DEFAULT_NEW_VM_LIMIT,
            _limit_new_vms,
            _normalize_new_vm_limit,
        )

        self.assertEqual(_normalize_new_vm_limit(None), DEFAULT_NEW_VM_LIMIT)
        self.assertEqual(_normalize_new_vm_limit("all"), None)
        self.assertEqual(_normalize_new_vm_limit("ALL"), None)
        self.assertEqual(_normalize_new_vm_limit(0), None)
        self.assertEqual(_normalize_new_vm_limit(-3), None)
        self.assertEqual(_normalize_new_vm_limit(7), 7)
        self.assertEqual(_normalize_new_vm_limit("7"), 7)
        self.assertEqual(_normalize_new_vm_limit("abc"), DEFAULT_NEW_VM_LIMIT)
        self.assertEqual(_normalize_new_vm_limit(""), DEFAULT_NEW_VM_LIMIT)
        self.assertEqual(_limit_new_vms([1, 2, 3], None), [1, 2, 3])
        self.assertEqual(_limit_new_vms([1, 2, 3], 2), [1, 2])


class ReportNewVmLimitTest(unittest.TestCase):
    def _seed(self, tmpdir: str):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.inventory.models import ClusterInput, TowerInput
        from app.v2.inventory.service import InventoryService

        settings = V2Settings(data_root=Path(tmpdir), secret_key="reports-secret")
        db = V2Database(settings)
        db.initialize()
        inventory = InventoryService(db, settings)
        tower = inventory.create_tower(
            TowerInput(name="Tower A", base_url="https://tower.example.com", username="admin")
        )
        inventory.sync_clusters(tower.id, [ClusterInput(cluster_id="cluster-a", name="Cluster A", enabled=True)])
        with db.connection() as conn:
            conn.execute(
                "INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (1, 'cluster-a', 'vm-old', 'Old Latest', 300)"
            )
            # Phase 75：新建 VM 也必须在活跃列表里（否则会被"非活跃虚机"过滤掉）
            for index in range(NEW_VM_COUNT):
                conn.execute(
                    "INSERT INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes) VALUES (1, 'cluster-a', ?, ?, 50)",
                    (f"vm-new-{index:03d}", f"New {index:03d}"),
                )
            conn.execute(
                "INSERT INTO collection_runs (status, message, finished_at, success_targets_json)"
                " VALUES ('success', 'ok', '2026-10-14 00:00:00', '[{}]')"
            )
        return settings, db

    def _report(self, db, settings, now_ts: int, **kwargs):
        from app.v2.reports.service import ReportService
        from app.v2.vms.new_vm import period_bounds

        # 首见时刻取「业务时区的今日 0 点」之后 1 秒——与服务的判定口径同源
        today_start = period_bounds(now_ts, "day", settings.timezone)[0]
        fake = ManyNewVmsPrometheus(now_ts, today_start + 1)
        return ReportService(db, settings, prometheus=fake, now_ts=now_ts).latest_report(
            period_days=30, chart_days=90, **kwargs
        )

    def test_default_limit_trims_detail_but_keeps_full_counts(self) -> None:
        now_ts = 1_800_000_000
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed(tmpdir)
            report = self._report(db, settings, now_ts)

            # 详情被裁剪到默认 50
            self.assertEqual(len(report["day_new_vms"]), 50)
            self.assertEqual(len(report["month_new_vms"]), 50)
            # 计数是全量口径（60 台新建，老 VM 不算）
            self.assertEqual(report["day_new_vm_count"], NEW_VM_COUNT)
            self.assertEqual(report["month_new_vm_count"], NEW_VM_COUNT)
            # 裁剪顺序稳定：默认列表是全量列表的前缀
            full = self._report(db, settings, now_ts, new_vm_limit="all")
            self.assertEqual(len(full["day_new_vms"]), NEW_VM_COUNT)
            self.assertEqual(full["day_new_vm_count"], NEW_VM_COUNT)
            self.assertEqual(
                [item["labels"]["vm_id"] for item in report["day_new_vms"]],
                [item["labels"]["vm_id"] for item in full["day_new_vms"]][:50],
            )

    def test_explicit_limits(self) -> None:
        now_ts = 1_800_000_000
        with tempfile.TemporaryDirectory() as tmpdir:
            settings, db = self._seed(tmpdir)
            five = self._report(db, settings, now_ts, new_vm_limit=5)
            self.assertEqual(len(five["day_new_vms"]), 5)
            self.assertEqual(five["day_new_vm_count"], NEW_VM_COUNT)
            # 0 / 负值 / "all" 都表示全量
            for token in ("all", 0, -1):
                full = self._report(db, settings, now_ts, new_vm_limit=token)
                self.assertEqual(len(full["day_new_vms"]), NEW_VM_COUNT)
                self.assertEqual(full["day_new_vm_count"], NEW_VM_COUNT)


if __name__ == "__main__":
    unittest.main()
