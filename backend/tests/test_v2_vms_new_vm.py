import unittest
from datetime import datetime, timezone

from app.v2.vms.new_vm import is_recycled_vm_name, period_bounds, vm_display_name


class V2NewVmHelpersTest(unittest.TestCase):
    def test_period_bounds_day_and_month_use_business_timezone(self) -> None:
        """49-44：周期边界统一按 settings.timezone 计算（概览与报表同源）。"""
        now_ts = 1_700_000_000  # 2023-11-14 22:13:20 UTC = 2023-11-15 06:13:20 +08:00

        day_start, day_end = period_bounds(now_ts, "day", "Asia/Shanghai")
        self.assertEqual(day_start, int(datetime(2023, 11, 15, 0, 0, tzinfo=timezone.utc).timestamp()) - 8 * 3600)
        self.assertEqual(day_end, now_ts)

        month_start, month_end = period_bounds(now_ts, "month", "Asia/Shanghai")
        self.assertEqual(month_start, int(datetime(2023, 11, 1, 0, 0, tzinfo=timezone.utc).timestamp()) - 8 * 3600)
        self.assertEqual(month_end, now_ts)

        # 无时区名（或解析失败）回退 UTC
        utc_day_start, _ = period_bounds(now_ts, "day", None)
        self.assertEqual(utc_day_start, int(datetime(2023, 11, 14, 0, 0, tzinfo=timezone.utc).timestamp()))
        self.assertEqual(period_bounds(now_ts, "day", "Bad/Zone"), period_bounds(now_ts, "day", None))

    def test_recycle_bin_helpers(self) -> None:
        self.assertTrue(is_recycled_vm_name("in-recycle-bin-abc"))
        self.assertFalse(is_recycled_vm_name("vm-prod-01"))
        self.assertEqual(vm_display_name({"vm_name": "A"}), "A")
        self.assertEqual(vm_display_name({"vm": "B"}), "B")
        self.assertEqual(vm_display_name({"vm_id": "c"}), "c")
        self.assertEqual(vm_display_name({}), "")


if __name__ == "__main__":
    unittest.main()
