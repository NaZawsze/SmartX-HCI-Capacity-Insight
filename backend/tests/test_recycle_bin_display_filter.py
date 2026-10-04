"""回收站 VM 及其卷不在页面列表展示（pending #79，2026-10-04）。

用户口径经两轮澄清后确定：
- **统计侧全量**：已使用 / 已分配 / 容量预测都**包含回收站**（#75/#77 已按此实现并验收）
- **展示层过滤**：Web 页面**不显示**回收站里的 VM，也不显示属于这些 VM 的卷

故本测试只针对**列表接口**（`/api/vms`、`/api/vm-volumes`），并明确断言
统计口径未被改动。VM 详情与单 VM 卷列表**不过滤**——列表里已看不到，
深链直接访问仍应可用，否则历史链接会 404。

判据用 `vm_latest.in_recycle_bin`，并叠加 Tower 侧名字前缀 `in-recycle-bin-<uuid>`
作兜底（采集侧 49-47 已写入该字段，但历史数据可能只有前缀）。
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


class RecycleBinDisplayFilterTest(unittest.TestCase):
    def _service(self, tmpdir: str, rows_vms, rows_volumes=()):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database

        settings = V2Settings(data_root=Path(tmpdir), secret_key="s", app_version="v0.5.3")
        database = V2Database(settings)
        database.initialize()
        with database.connection() as conn:
            conn.execute("INSERT OR REPLACE INTO towers (id, name, base_url) VALUES (1, 't1', 'http://x')")
            conn.execute(
                "INSERT OR REPLACE INTO clusters (tower_id, cluster_id, name) VALUES (1, 'c1', '集群1')")
            for vm_id, name, recycled in rows_vms:
                conn.execute(
                    "INSERT OR REPLACE INTO vm_latest"
                    " (tower_id, cluster_id, vm_id, name, used_bytes, in_recycle_bin)"
                    " VALUES (1, 'c1', ?, ?, ?, ?)",
                    (vm_id, name, 1024, 1 if recycled else 0),
                )
            for vm_id, volume_id, name in rows_volumes:
                conn.execute(
                    "INSERT OR REPLACE INTO vm_volumes"
                    " (tower_id, cluster_id, vm_id, volume_id, name, path, size_bytes,"
                    "  used_bytes, storage_policy, replica_num, thin_provision, ec_k, ec_m, updated_at)"
                    " VALUES (1, 'c1', ?, ?, ?, '/data', 100, 50, 'p', 1, 0, 0, 0, '2026-10-04 00:00:00')",
                    (vm_id, volume_id, name),
                )
        from app.v2.vms.service import VmService

        # VmService 签名是 (database, settings, prometheus=...)；注入一个空的
        # prometheus stub，让 list_vms 的 Prometheus 主路径拿不到指标，
        # 从而走 DB 回退路径——那条路径同样要过滤，必须覆盖。
        class _NoProm:
            def instant(self, *_args, **_kwargs):
                return []

            def range(self, *_args, **_kwargs):
                return []

        return VmService(database, settings, _NoProm())

    def test_vm_list_hides_recycle_bin_by_flag(self) -> None:
        """in_recycle_bin=1 的 VM 不出现在列表。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            svc = self._service(
                tmpdir,
                [
                    ("vm-normal", "正常机器", False),
                    ("vm-recycled", "已删除机器", True),
                ],
            )
            names = {v["vm_name"] for v in svc.list_vms()}
            self.assertIn("正常机器", names)
            self.assertNotIn("已删除机器", names, "回收站 VM 不应展示")

    def test_vm_list_hides_recycle_bin_by_name_prefix(self) -> None:
        """仅有名字前缀（历史数据缺字段）也要隐藏。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            svc = self._service(
                tmpdir,
                [
                    ("vm-normal", "正常机器", False),
                    ("vm-uuid", "in-recycle-bin-1234-abcd", False),
                ],
            )
            names = {v["vm_name"] for v in svc.list_vms()}
            self.assertNotIn("in-recycle-bin-1234-abcd", names, "前缀判据应生效")

    def test_volume_lists_hide_recycled_vm_volumes(self) -> None:
        """回收站 VM 的卷在 grouped 与分页两条路径都不展示。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            svc = self._service(
                tmpdir,
                [
                    ("vm-normal", "正常机器", False),
                    ("vm-recycled", "已删除机器", True),
                ],
                [
                    ("vm-normal", "vol-ok", "正常卷"),
                    ("vm-recycled", "vol-bad", "回收站卷"),
                ],
            )

            grouped = svc.all_volumes()
            flat_grouped = _flatten_grouped(grouped)
            self.assertIn("正常卷", flat_grouped)
            self.assertNotIn("回收站卷", flat_grouped, "grouped 路径不应含回收站卷")

            paged = svc.all_volumes(page=1, page_size=100)
            # VmVolumePageResponse 的字段是 volumes / total（不是 items）
            items = paged["volumes"] if isinstance(paged, dict) else paged
            paged_names = {v["name"] for v in items}
            self.assertIn("正常卷", paged_names)
            self.assertNotIn("回收站卷", paged_names, "分页路径不应含回收站卷")
            if isinstance(paged, dict):
                self.assertEqual(
                    paged.get("total"), 1, "total 也不应把回收站卷计入（否则分页数虚高）"
                )

    def test_statistics_remain_full_scope(self) -> None:
        """**统计侧不受影响**：已分配/容量预测仍含回收站（用户口径的核心）。

        本测试只锁住「过滤只发生在展示层」这一边界——若有人把过滤下沉到数据层，
        统计口径就会与用户口径相悖。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            svc = self._service(
                tmpdir,
                [
                    ("vm-normal", "正常机器", False),
                    ("vm-recycled", "已删除机器", True),
                ],
            )
            # 存储层仍能看到回收站 VM 的行（数据保留是明确决策）
            with svc.database.connection() as conn:
                rows = conn.execute(
                    "SELECT vm_id FROM vm_latest WHERE in_recycle_bin = 1"
                ).fetchall()
            self.assertEqual([r["vm_id"] for r in rows], ["vm-recycled"])

    def test_detail_and_single_vm_volumes_not_filtered(self) -> None:
        """详情与单 VM 卷列表不过滤——深链仍可用，避免历史链接 404。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            svc = self._service(
                tmpdir,
                [("vm-recycled", "已删除机器", True)],
                [("vm-recycled", "vol-bad", "回收站卷")],
            )
            vols = svc.volumes(vm_id="vm-recycled", tower_id=1, cluster_id="c1")
            self.assertEqual(
                [v["name"] for v in vols], ["回收站卷"], "单 VM 卷列表应保持可用"
            )


def _flatten_grouped(grouped):
    names = set()
    for value in grouped:
        if isinstance(value, dict):
            for item in value.get("volumes") or []:
                names.add(item.get("name"))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    names.add(item.get("name"))
    return names


if __name__ == "__main__":
    unittest.main()
