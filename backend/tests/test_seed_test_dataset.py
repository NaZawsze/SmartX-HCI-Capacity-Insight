"""标准测试数据集生成器（scripts/seed_test_dataset.py）的画像校验。

数据集是**长期资产**（docs/test-architecture.md §6）：如果它退化成"随手 seed"，
编码/回收站/回落口径的缺陷就又测不出来了。这里用最小库把画像钉死。
"""

from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCHEMA = """
CREATE TABLE towers (id INTEGER PRIMARY KEY, name TEXT, base_url TEXT, enabled INTEGER,
                     collection_hour INTEGER, collection_minute INTEGER, created_at TEXT, updated_at TEXT);
CREATE TABLE clusters (id INTEGER PRIMARY KEY, tower_id INTEGER, cluster_id TEXT, name TEXT,
                       enabled INTEGER, updated_at TEXT);
CREATE TABLE vm_latest (tower_id INTEGER, cluster_id TEXT, vm_id TEXT PRIMARY KEY, name TEXT,
                        used_bytes INTEGER, updated_at TEXT, owner TEXT, folder_name TEXT,
                        in_recycle_bin INTEGER, original_name TEXT, deleted_at TEXT, local_created_at TEXT);
CREATE TABLE vm_volumes (tower_id INTEGER, cluster_id TEXT, vm_id TEXT, volume_id TEXT PRIMARY KEY,
                         name TEXT, path TEXT, size_bytes INTEGER, used_bytes INTEGER,
                         storage_policy TEXT, replica_num INTEGER, thin_provision INTEGER,
                         ec_k INTEGER, ec_m INTEGER, updated_at TEXT);
"""


def load_module():
    spec = importlib.util.spec_from_file_location("seed_test_dataset", ROOT / "scripts" / "seed_test_dataset.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SeedDatasetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "smartx.db"
        conn = sqlite3.connect(self.db)
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _seed(self, **kwargs):
        return self.module.seed(self.db, **kwargs)

    def test_counts_follow_profile(self) -> None:
        counts = self._seed(vms=20, volumes_per_vm=2, towers=2, clusters=3, recycle=3)
        self.assertEqual(counts["towers"], 2)
        self.assertEqual(counts["clusters"], 3)
        self.assertEqual(counts["vm_latest"], 20)
        self.assertEqual(counts["vm_volumes"], 40)
        self.assertEqual(counts["recycle"], 3)

    def test_names_carry_chinese_and_emoji(self) -> None:
        self._seed(vms=20, volumes_per_vm=1)
        conn = sqlite3.connect(self.db)
        names = [row[0] for row in conn.execute("SELECT name FROM vm_latest")]
        volumes = [row[0] for row in conn.execute("SELECT name FROM vm_volumes")]
        conn.close()
        self.assertTrue(any("虚拟机" in name for name in names))
        self.assertTrue(any("🚀" in name for name in names))
        self.assertTrue(any("💾" in name for name in volumes))

    def test_recycle_rows_have_prefix_and_original_name(self) -> None:
        self._seed(vms=20, volumes_per_vm=1, recycle=3)
        conn = sqlite3.connect(self.db)
        rows = list(conn.execute("SELECT name, original_name FROM vm_latest WHERE in_recycle_bin=1"))
        conn.close()
        self.assertEqual(len(rows), 3)
        for name, original in rows:
            self.assertTrue(name.startswith("in-recycle-bin-"))
            self.assertTrue(original and not original.startswith("in-recycle-bin-"))

    def test_local_created_at_covers_all_four_buckets(self) -> None:
        self._seed(vms=40, volumes_per_vm=1)
        conn = sqlite3.connect(self.db)
        missing = conn.execute("SELECT COUNT(*) FROM vm_latest WHERE local_created_at IS NULL").fetchone()[0]
        distinct_days = conn.execute("SELECT COUNT(DISTINCT substr(local_created_at,1,10)) FROM vm_latest").fetchone()[0]
        conn.close()
        self.assertGreater(missing, 0, "必须保留「缺失 local_created_at」的回落样本")
        self.assertGreaterEqual(distinct_days, 3, "应覆盖本日/本月/历史")

    def test_boundary_values_and_no_orphans(self) -> None:
        self._seed(vms=20, volumes_per_vm=2)
        conn = sqlite3.connect(self.db)
        zero = conn.execute("SELECT COUNT(*) FROM vm_latest WHERE used_bytes=0").fetchone()[0]
        big = conn.execute("SELECT COUNT(*) FROM vm_latest WHERE used_bytes>=8589934592").fetchone()[0]
        orphans = conn.execute(
            "SELECT COUNT(*) FROM vm_volumes o LEFT JOIN vm_latest v ON v.vm_id=o.vm_id WHERE v.vm_id IS NULL"
        ).fetchone()[0]
        conn.close()
        self.assertGreater(zero, 0, "需要 used_bytes=0 的边界样本")
        self.assertGreater(big, 0, "需要超大 used_bytes 的边界样本")
        self.assertEqual(orphans, 0, "数据集不得自带孤儿行")

    def test_deterministic_between_runs(self) -> None:
        """同一库上重复生成必须得到同样内容（指纹可比）。"""
        self._seed(vms=20, volumes_per_vm=2)
        conn = sqlite3.connect(self.db)
        first = [tuple(r) for r in conn.execute("SELECT vm_id, name, used_bytes, local_created_at FROM vm_latest ORDER BY vm_id")]
        conn.close()
        self._seed(vms=20, volumes_per_vm=2)
        conn = sqlite3.connect(self.db)
        second = [tuple(r) for r in conn.execute("SELECT vm_id, name, used_bytes, local_created_at FROM vm_latest ORDER BY vm_id")]
        conn.close()
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
