"""#36/#37 ②③：回收站判据统一走权威标记 + 详情页显示回收前名字。

- ② series 路径（growth/dashboard/reports 共用 `compute_growth_vms` 等）此前**只用名字前缀**
  判回收站，与展示层"标记优先"的口径不一致——Tower 若调整改名约定，过滤会静默失效。
  现在统一收口到 `vms/recycle.py`：权威标记 `vm_latest.in_recycle_bin` 优先，前缀兜底；
  调用方（dashboard/reports）每请求取一次键集传入。未提供键集时退回前缀判定（兼容旧调用）。
- ③ `VmService.detail` 深链直达回收站 VM 时显示回收前名字（original_name），
  身份名（vm_id/库内 name）不动——列表/统计过滤按三元组，不受显示名影响（#79 口径不变）。
"""

import tempfile
import unittest
from pathlib import Path

SECONDS_PER_DAY = 86_400


def _seed_db(tmpdir: str, *, marker_vm: bool):
    """建库：1 台普通 VM + 1 台"标记为回收站但名字正常"的 VM（marker_vm=True 时）。

    关键点：那台 VM **名字不带前缀**——旧实现（仅前缀判定）抓不到它，新实现（权威标记）必须抓到。
    """
    from app.v2.config import V2Settings
    from app.v2.database import V2Database

    settings = V2Settings(data_root=Path(tmpdir), secret_key="s", app_version="v0.5.3")
    database = V2Database(settings)
    database.initialize()
    with database.connection() as conn:
        conn.execute("INSERT OR REPLACE INTO towers (id, name, base_url) VALUES (1, 't1', 'http://x')")
        conn.execute("INSERT OR REPLACE INTO clusters (tower_id, cluster_id, name) VALUES (1, 'c1', '集群1')")
        conn.execute(
            "INSERT OR REPLACE INTO vm_latest (tower_id, cluster_id, vm_id, name, used_bytes, in_recycle_bin, original_name)"
            " VALUES (1, 'c1', 'vm-normal', 'Normal VM', 100, 0, NULL)"
        )
        if marker_vm:
            conn.execute(
                "INSERT OR REPLACE INTO vm_latest"
                " (tower_id, cluster_id, vm_id, name, used_bytes, in_recycle_bin, original_name, deleted_at)"
                " VALUES (1, 'c1', 'vm-marked', 'Marked VM', 200, 1, '回收前的名字', '2026-10-12 08:00:00')"
            )
    return settings, database


class RecycleMarkerUnitTest(unittest.TestCase):
    """`vms/recycle.py` 单元：判据与键集。"""

    def test_is_recycled_row_marker_and_prefix(self):
        from app.v2.vms.recycle import is_recycled_row

        # 权威标记优先
        self.assertTrue(is_recycled_row("普通名", 1))
        # 名字前缀兜底（历史行可能只有前缀）
        self.assertTrue(is_recycled_row("in-recycle-bin-abc123", 0))
        self.assertTrue(is_recycled_row("in-recycle-bin-abc123", None))
        # 正常行
        self.assertFalse(is_recycled_row("普通名", 0))
        self.assertFalse(is_recycled_row("普通名", None))
        self.assertFalse(is_recycled_row(None, None))

    def test_recycled_vm_keys_includes_marker_only_row(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _, database = _seed_db(tmpdir, marker_vm=True)
            from app.v2.vms.recycle import recycled_vm_keys

            keys = recycled_vm_keys(database)
            self.assertIn((1, "c1", "vm-marked"), keys)
            self.assertNotIn((1, "c1", "vm-normal"), keys)

    def test_recycled_vm_keys_failure_returns_empty(self):
        class _Broken:
            def connection(self):
                raise RuntimeError("db down")

        from app.v2.vms.recycle import recycled_vm_keys

        self.assertEqual(recycled_vm_keys(_Broken()), set())


class _GrowthProm:
    """1 台普通 VM + 1 台"标记回收站但名字正常"的 VM，均有序列与 instant。"""

    def __init__(self, now_ts: int):
        self.now_ts = now_ts

    def _series(self, vm_id: str, name: str, value: float) -> dict:
        return {
            "metric": {"tower_id": "1", "cluster_id": "c1", "vm_id": vm_id, "vm_name": name},
            "values": [
                [self.now_ts - 2 * SECONDS_PER_DAY, str(value * 0.5)],
                [self.now_ts, str(value)],
            ],
        }

    def instant(self, _query: str):
        return [
            {"metric": {"tower_id": "1", "cluster_id": "c1", "vm_id": "vm-normal", "vm_name": "Normal VM"}, "value": [self.now_ts, "100"]},
            {"metric": {"tower_id": "1", "cluster_id": "c1", "vm_id": "vm-marked", "vm_name": "Marked VM"}, "value": [self.now_ts, "200"]},
        ]

    def range(self, _query: str, *, start: int, end: int, step: str):
        return [
            self._series("vm-normal", "Normal VM", 100.0),
            self._series("vm-marked", "Marked VM", 200.0),
        ]


class GrowthSeriesMarkerFilterTest(unittest.TestCase):
    """② 核心：series 路径按权威标记排除——名字正常的回收站 VM 也必须被过滤。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.settings, self.database = _seed_db(self._tmp.name, marker_vm=True)
        self.now_ts = 1_760_000_000

    def tearDown(self):
        self._tmp.cleanup()

    def _growth(self, recycled_keys):
        from app.v2.vms.growth import compute_growth_vms, latest_vm_items, merge_latest_items, series_tail_items

        prom = _GrowthProm(self.now_ts)
        latest_items = merge_latest_items(
            latest_vm_items(prom, enabled_scope={(1, "c1")}, recycled_keys=recycled_keys),
            series_tail_items(prom.range("smartx_vm_storage_used_bytes", start=0, end=self.now_ts, step="1h"), recycled_keys),
        )
        labels = {
            (1, "c1", "vm-normal"): {"vm": "Normal VM", "vm_name": "Normal VM"},
            (1, "c1", "vm-marked"): {"vm": "Marked VM", "vm_name": "Marked VM"},
        }
        return compute_growth_vms(
            series_list=prom.range("smartx_vm_storage_used_bytes", start=0, end=self.now_ts, step="1h"),
            latest_items=latest_items,
            latest_label_by_vm=labels,
            recycled_keys=recycled_keys,
        )

    def test_marker_vm_excluded_with_authoritative_keys(self):
        from app.v2.vms.recycle import recycled_vm_keys

        keys = recycled_vm_keys(self.database)
        names = [record["vm_id"] for record in self._growth(keys)]
        self.assertEqual(names, ["vm-normal"], "标记回收站（名字正常）的 VM 必须被排除")

    def test_prefix_fallback_when_keys_not_provided(self):
        # recycled_keys=None ⇒ 旧兜底行为：名字正常 → 不排除（兼容未升级的调用点）
        names = [record["vm_id"] for record in self._growth(None)]
        self.assertEqual(sorted(names), ["vm-marked", "vm-normal"])

    def test_prefix_only_row_still_caught_by_key_set(self):
        from app.v2.vms.recycle import recycled_vm_keys

        # 历史行：无标记但名字带前缀 → 键集仍应收录
        with self.database.connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO vm_latest"
                " (tower_id, cluster_id, vm_id, name, used_bytes, in_recycle_bin, original_name)"
                " VALUES (1, 'c1', 'vm-prefix', 'in-recycle-bin-deadbeef', 300, 0, 'Old Name')"
            )
        keys = recycled_vm_keys(self.database)
        self.assertIn((1, "c1", "vm-prefix"), keys)
        names = [record["vm_id"] for record in self._growth(keys)]
        self.assertEqual(names, ["vm-normal"])


class VmDetailOriginalNameTest(unittest.TestCase):
    """③：详情页对回收站 VM 显示回收前名字，并带 in_recycle_bin 标记。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.settings, self.database = _seed_db(self._tmp.name, marker_vm=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _detail(self, vm_id: str) -> dict:
        from app.v2.vms.service import VmService

        class _NoProm:
            def instant(self, *_a, **_k):
                return []

            def range(self, *_a, **_k):
                return []

        return VmService(self.database, self.settings, prometheus=_NoProm()).detail(
            vm_id=vm_id, tower_id=1, cluster_id="c1"
        )

    def test_recycled_vm_shows_original_name(self):
        detail = self._detail("vm-marked")
        self.assertTrue(detail["in_recycle_bin"])
        self.assertEqual(detail["vm_name"], "回收前的名字")
        # 身份字段不动
        self.assertEqual(detail["vm_id"], "vm-marked")

    def test_normal_vm_untouched(self):
        detail = self._detail("vm-normal")
        self.assertFalse(detail["in_recycle_bin"])
        self.assertEqual(detail["vm_name"], "Normal VM")

    def test_missing_vm_still_defaults(self):
        detail = self._detail("vm-ghost")
        self.assertFalse(detail["in_recycle_bin"])
        self.assertEqual(detail["vm_name"], "vm-ghost")
        self.assertEqual(detail["used_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
