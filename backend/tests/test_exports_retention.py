"""报表导出 / 迁移包 / 导入留档的自动保留（pending #78，2026-10-04）。

## 缺口（追查中纠正了自己的错误描述）

我最初把 #78 写成「空间清理只覆盖 upgrades/backups，报表导出物与迁移包无任何清理」。
**这是错的**——`CleanupService._targets()` 本就包含 reports / migrations / imports，
手动清理**会**删它们。真实缺口是两条：

1. **无自动清理**：`upgrade/housekeeping.py` 的 TTL 守护只管 `upgrades/`，
   这四类目录没有任何后台清理。`.12` 约 450 MiB 即由此堆积——客户不会主动点清理。
2. **手动清理会全删**：`keep_recent` 只对 `upgrades/` 生效，其余三类走
   `elif child.is_dir(): rmtree` 一次清空。对 `imports`/`migrations` 尤其危险：
   **迁移包可能是客户唯一的重导入凭据**。

本模块按 TTL + 保留数自动清理，且**保留下限 3 个**，绝不因后台任务清空客户凭据。
"""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


class ExportRetentionTest(unittest.TestCase):
    def _settings(self, tmpdir: str, **overrides):
        from app.v2.config import V2Settings

        return V2Settings(
            data_root=Path(tmpdir), secret_key="s", app_version="v0.5.3", **overrides
        )

    def _service(self, tmpdir: str, **overrides):
        from app.v2.exports_retention import ExportRetentionService

        return ExportRetentionService(
            self._settings(tmpdir, **overrides), now_fn=lambda: NOW
        )

    def _seed(self, settings, label_dir: str, count: int, ages_days: list[int]):
        """造 count 个产物，第 i 个的 mtime 设为 ages_days[i] 天前。"""
        target = {
            "报表导出": settings.reports_dir,
            "数据迁出包": settings.migrations_dir,
            "数据迁入留档": settings.imports_dir,
            "迁移任务工作目录": settings.migration_tasks_dir,
        }[label_dir]
        target.mkdir(parents=True, exist_ok=True)
        made = []
        for i in range(count):
            item = target / f"item-{i}"
            item.mkdir()
            (item / "data.bin").write_bytes(b"x" * 1024)
            stamp = (NOW - timedelta(days=ages_days[i])).timestamp()
            import os

            os.utime(item, (stamp, stamp))
            made.append(item)
        return made

    def test_deletes_expired_beyond_keep(self) -> None:
        """超过 TTL 且超出保留数的应被删。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            svc = self._service(tmpdir, upgrade_artifact_ttl_days=7)
            settings = svc.settings
            # 最新 3 个在保留窗口内，更早的 3 个既超 TTL 又超保留数
            items = self._seed(settings, "报表导出", 6, [0, 1, 2, 30, 60, 90])

            result = svc.cleanup()

            self.assertEqual(result["deleted_count"], 3, result["logs"])
            self.assertFalse(items[3].exists())
            self.assertFalse(items[5].exists())
            for keep in items[:3]:
                self.assertTrue(keep.exists(), f"{keep.name} 应被保留")

    def test_keeps_minimum_even_if_all_expired(self) -> None:
        """全部过期也至少保留 MIN_KEEP 个——迁移包可能是唯一重导入凭据。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            svc = self._service(tmpdir, upgrade_artifact_ttl_days=1)
            settings = svc.settings
            items = self._seed(settings, "数据迁出包", 2, [100, 200])

            result = svc.cleanup()

            self.assertEqual(result["deleted_count"], 0, "低于下限时不得删除")
            self.assertTrue(result["keep_recent"] >= 3)
            for item in items:
                self.assertTrue(item.exists())

    def test_migration_and_import_archives_never_auto_emptied(self) -> None:
        """核心安全断言：迁出/迁入留档不得被自动清空。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            svc = self._service(tmpdir, upgrade_artifact_ttl_days=1, upgrade_artifact_keep_recent=0)
            settings = svc.settings
            mig = self._seed(settings, "数据迁出包", 2, [365, 400])
            imp = self._seed(settings, "数据迁入留档", 2, [365, 400])

            svc.cleanup()

            self.assertTrue(all(p.exists() for p in mig), "迁出包不得被清空")
            self.assertTrue(all(p.exists() for p in imp), "迁入留档不得被清空")

    def test_ttl_zero_only_trims_by_count(self) -> None:
        """TTL=0 → 不按时间删，只按保留数裁剪。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            svc = self._service(tmpdir, upgrade_artifact_ttl_days=0)
            settings = svc.settings
            items = self._seed(settings, "报表导出", 6, [0, 0, 0, 0, 0, 0])

            result = svc.cleanup()

            # _seed 用 ages_days 递增 → mtime 越晚的 index 越大；
            # cleanup 按 mtime 倒序保留前 keep 个，故被删的是**尾部**（最旧的）。
            self.assertEqual(result["deleted_count"], 3, "只应按保留数裁剪")
            self.assertFalse(items[5].exists(), "最旧的应被裁掉")
            self.assertFalse(items[3].exists())
            self.assertTrue(items[0].exists(), "最新的必须保留")

    def test_reports_without_history_untouched(self) -> None:
        """不误删：未超 TTL 的一律保留。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            svc = self._service(tmpdir, upgrade_artifact_ttl_days=30)
            settings = svc.settings
            items = self._seed(settings, "报表导出", 4, [0, 1, 2, 3])

            result = svc.cleanup()

            self.assertEqual(result["deleted_count"], 0)
            self.assertTrue(all(p.exists() for p in items))

    def test_missing_dirs_are_skipped(self) -> None:
        """目录不存在时不得报错（首次安装还没有这些目录）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            svc = self._service(tmpdir)
            result = svc.cleanup()
            self.assertTrue(result["ok"])
            self.assertEqual(result["deleted_count"], 0)

    def test_daemon_disabled_when_interval_non_positive(self) -> None:
        """间隔 <=0 → 不启动守护（与 backup_cleanup 同一约定）。"""
        from app.v2.exports_retention import start_export_retention_daemon

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = self._settings(tmpdir)
            self.assertIsNone(start_export_retention_daemon(settings, interval_seconds=0))

    def test_daemon_returns_stop_event(self) -> None:
        """返回 stop_event 供 shutdown 优雅停止（与 backup_cleanup 同一契约）。"""
        from app.v2.exports_retention import start_export_retention_daemon

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = self._settings(tmpdir)
            evt = start_export_retention_daemon(settings, interval_seconds=3600)
            try:
                self.assertIsNotNone(evt)
                self.assertFalse(evt.is_set())
            finally:
                if evt is not None:
                    evt.set()


if __name__ == "__main__":
    unittest.main()
