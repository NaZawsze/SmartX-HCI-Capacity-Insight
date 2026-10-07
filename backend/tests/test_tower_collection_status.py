"""Tower 列表的采集状态判定：问题优先（部分失败必须可见）。

2026-10-07 用户实测：列表只在问题态显示状态行；若该塔既有成功目标又有失败目标
（部分失败）而判定返回 success，问题就会被静默吞掉。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.v2.api.towers import tower_last_collection, tower_last_success_at  # noqa: E402
from app.v2.config import V2Settings  # noqa: E402
from app.v2.database import V2Database  # noqa: E402
from app.v2.inventory.service import InventoryService  # noqa: E402


class TowerCollectionStatusTest(unittest.TestCase):
    def _inventory(self, root: Path) -> InventoryService:
        settings = V2Settings(data_root=root, secret_key="tower-status")
        database = V2Database(settings)
        database.initialize()
        return InventoryService(database, settings)

    def _insert_run(self, inventory: InventoryService, *, run_id: int, success: list[int], failed: list[int]) -> None:
        with inventory.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO collection_runs (id, status, message, started_at, finished_at,
                                             success_targets_json, failed_targets_json)
                VALUES (?, ?, '', '2026-10-07 14:00:00', '2026-10-07 14:00:05', ?, ?)
                """,
                (
                    run_id,
                    "partial_failed" if failed else "success",
                    json.dumps([{"tower_id": tid} for tid in success]),
                    json.dumps([{"tower_id": tid} for tid in failed]),
                ),
            )

    def test_partial_failure_is_reported_as_failed(self) -> None:
        """该塔同时出现在 success 与 failed → 必须 failed（问题不可被静默标成成功）。"""
        with tempfile.TemporaryDirectory() as tmp:
            inventory = self._inventory(Path(tmp))
            self._insert_run(inventory, run_id=1, success=[3, 4], failed=[3])
            self.assertEqual(tower_last_collection(inventory, 3).status, "failed")
            self.assertEqual(tower_last_collection(inventory, 4).status, "success")

    def test_newest_run_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inventory = self._inventory(Path(tmp))
            self._insert_run(inventory, run_id=1, success=[3], failed=[])
            self._insert_run(inventory, run_id=2, success=[], failed=[3])
            self.assertEqual(tower_last_collection(inventory, 3).status, "failed")
            self.assertEqual(tower_last_collection(inventory, 3).finished_at, "2026-10-07 14:00:05")

    def test_last_success_is_not_refreshed_by_failed_runs(self) -> None:
        """用户口径（2026-10-07）：超期提示以上一次**成功**采集为准——
        失败运行也会写时间戳，若按"最近一次跑到它的运行"算，刚失败的塔会被显示成"刚刚采集"。"""
        with tempfile.TemporaryDirectory() as tmp:
            inventory = self._inventory(Path(tmp))
            self._insert_run(inventory, run_id=1, success=[3], failed=[])
            self._insert_run(inventory, run_id=2, success=[], failed=[3])
            self.assertEqual(tower_last_success_at(inventory, 3), "2026-10-07 14:00:05")

    def test_last_success_returns_newest_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inventory = self._inventory(Path(tmp))
            self._insert_run(inventory, run_id=1, success=[3], failed=[])
            with inventory.database.connection() as conn:
                conn.execute("UPDATE collection_runs SET finished_at = '2026-10-06 10:00:00' WHERE id = 1")
            self._insert_run(inventory, run_id=2, success=[3], failed=[])
            self.assertEqual(tower_last_success_at(inventory, 3), "2026-10-07 14:00:05")

    def test_last_success_none_when_never_succeeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inventory = self._inventory(Path(tmp))
            self._insert_run(inventory, run_id=1, success=[], failed=[3])
            self.assertIsNone(tower_last_success_at(inventory, 3))

    def test_none_when_never_mentioned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inventory = self._inventory(Path(tmp))
            self._insert_run(inventory, run_id=1, success=[9], failed=[])
            self.assertIsNone(tower_last_collection(inventory, 3))


if __name__ == "__main__":
    unittest.main()
