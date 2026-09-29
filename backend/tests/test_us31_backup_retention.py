"""US-31 尾巴：升级备份保留策略。

背景：每次升级产出数据快照 + 项目文件备份，**无人回收**——`.12` 实测累积 13 份 / 98 MiB，
随升级次数线性增长。策略与 US-09 产物清理同构（TTL + 保留最近 N 份）。

**安全约束**：回退需要「数据快照 + 项目文件备份」配对存在，因此宁可多留，
不能出现"只剩一半"的残缺备份。
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path


def _write_data_backup(backups: Path, stamp: str, size: int = 4096) -> Path:
    path = backups / f"upgrade-v0.5.3-before-{stamp}.tar.gz"
    path.write_bytes(b"x" * size)
    return path


def _write_project_files(backups: Path, task_id: str) -> Path:
    path = backups / f"project-files-{task_id}"
    path.mkdir(parents=True, exist_ok=True)
    (path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    return path


def _age(path: Path, days: float) -> None:
    """把 mtime 往回拨，让 TTL 判定生效。"""
    when = time.time() - days * 86400
    os.utime(path, (when, when))


class BackupRetentionTest(unittest.TestCase):
    # ---------- TTL ----------

    def test_expired_backups_are_purged(self) -> None:
        from app.v2.upgrade.backup_retention import purge_backups

        with tempfile.TemporaryDirectory() as tmpdir:
            backups = Path(tmpdir)
            old = _write_data_backup(backups, "20200101000000")
            _age(old, 60)
            fresh = _write_data_backup(backups, "20990101000000")

            result = purge_backups(backups, ttl_days=14, keep_recent=1)

            self.assertFalse(old.exists(), "超过 TTL 的必须删除")
            self.assertTrue(fresh.exists(), "未超期的必须保留")
            self.assertTrue(result["removed"])

    def test_recent_backups_within_ttl_are_kept(self) -> None:
        from app.v2.upgrade.backup_retention import purge_backups

        with tempfile.TemporaryDirectory() as tmpdir:
            backups = Path(tmpdir)
            paths = []
            for index in range(3):
                path = _write_data_backup(backups, f"2099010{index}000000")
                _age(path, 1)  # 1 天前
                paths.append(path)

            purge_backups(backups, ttl_days=14, keep_recent=5)

            for path in paths:
                self.assertTrue(path.exists(), "未超期且未超量，不得删除")

    # ---------- 数量裁剪 ----------

    def test_redundant_backups_are_trimmed_to_keep_recent(self) -> None:
        from app.v2.upgrade.backup_retention import purge_backups

        with tempfile.TemporaryDirectory() as tmpdir:
            backups = Path(tmpdir)
            created = []
            for index in range(8):
                path = _write_data_backup(backups, f"2099010{index}000000")
                _age(path, index)  # 越早的越旧
                created.append(path)

            purge_backups(backups, ttl_days=365, keep_recent=3)

            remaining = sorted(p.name for p in backups.glob("upgrade-*.tar.gz"))
            self.assertEqual(len(remaining), 3, f"应保留 3 份，实际 {remaining}")
            # 保留的必须是最新的 3 份
            self.assertEqual(
                remaining,
                sorted(p.name for p in created[-3:]),
                "必须保留最近 N 份，而不是最旧 N 份",
            )

    def test_never_deletes_below_keep_recent_even_if_all_expired(self) -> None:
        """保留窗口是最小保险：全过期也要保住 keep_recent 份，避免回退无门。"""
        from app.v2.upgrade.backup_retention import purge_backups

        with tempfile.TemporaryDirectory() as tmpdir:
            backups = Path(tmpdir)
            for index in range(4):
                path = _write_data_backup(backups, f"2020010{index}000000")
                _age(path, 365)

            purge_backups(backups, ttl_days=1, keep_recent=2)

            remaining = list(backups.glob("upgrade-*.tar.gz"))
            self.assertEqual(len(remaining), 2, "即使全部超期也必须保留 keep_recent 份")

    # ---------- 安全约束 ----------

    def test_project_files_backups_are_also_cleaned(self) -> None:
        from app.v2.upgrade.backup_retention import purge_backups

        with tempfile.TemporaryDirectory() as tmpdir:
            backups = Path(tmpdir)
            old_dir = _write_project_files(backups, "upgrade-old")
            _age(old_dir, 60)

            purge_backups(backups, ttl_days=14, keep_recent=1)

            self.assertFalse(old_dir.exists(), "项目文件备份同样要按 TTL 清理")

    def test_collect_lists_both_types(self) -> None:
        from app.v2.upgrade.backup_retention import collect_backups

        with tempfile.TemporaryDirectory() as tmpdir:
            backups = Path(tmpdir)
            _write_data_backup(backups, "20990101000000")
            _write_project_files(backups, "upgrade-abc")
            kinds = {entry["type"] for entry in collect_backups(backups)}
            self.assertEqual(kinds, {"data", "project_files"})

    def test_plan_is_read_only(self) -> None:
        from app.v2.upgrade.backup_retention import plan_cleanup

        with tempfile.TemporaryDirectory() as tmpdir:
            backups = Path(tmpdir)
            path = _write_data_backup(backups, "20200101000000")
            _age(path, 365)

            before = sorted(p.name for p in backups.iterdir())
            plan_cleanup(backups, ttl_days=1, keep_recent=0)
            after = sorted(p.name for p in backups.iterdir())

            self.assertEqual(before, after, "plan_cleanup 不得修改任何文件")

    def test_unrelated_files_are_never_touched(self) -> None:
        """只清升级备份；客户手工放的其它文件、导出物一律不动。"""
        from app.v2.upgrade.backup_retention import purge_backups

        with tempfile.TemporaryDirectory() as tmpdir:
            backups = Path(tmpdir)
            keep = backups / "customer-manual-backup.tar.gz"
            keep.write_bytes(b"important")
            other = backups / "export-2026.csv"
            other.write_bytes(b"data")
            _write_data_backup(backups, "20200101000000")
            _write_project_files(backups, "upgrade-old")

            purge_backups(backups, ttl_days=1, keep_recent=0)

            self.assertTrue(keep.exists(), "非本模块命名的备份不得删除")
            self.assertTrue(other.exists(), "导出物不得删除")

    # ---------- 配置与守护 ----------

    def test_zero_config_disables(self) -> None:
        from app.v2.upgrade.backup_retention import cleanup_backups_once

        class _Settings:
            backups_dir = "/nonexistent-backups-dir-for-test"

        result = cleanup_backups_once(_Settings(), None, ttl_days=0, keep_recent=0)
        self.assertTrue(result.get("skipped"), "TTL 与保留数都为 0 时应跳过")

    def test_env_overrides_defaults(self) -> None:
        from app.v2.upgrade.backup_retention import _int_env

        original = os.environ.get("SMARTX_UPGRADE_BACKUP_KEEP_RECENT")
        try:
            os.environ["SMARTX_UPGRADE_BACKUP_KEEP_RECENT"] = "3"
            self.assertEqual(_int_env("SMARTX_UPGRADE_BACKUP_KEEP_RECENT", 5), 3)
            os.environ["SMARTX_UPGRADE_BACKUP_KEEP_RECENT"] = "not-a-number"
            self.assertEqual(_int_env("SMARTX_UPGRADE_BACKUP_KEEP_RECENT", 5), 5, "非法值回退默认")
            os.environ["SMARTX_UPGRADE_BACKUP_KEEP_RECENT"] = "-1"
            self.assertEqual(_int_env("SMARTX_UPGRADE_BACKUP_KEEP_RECENT", 5), 5, "负值回退默认")
        finally:
            if original is None:
                os.environ.pop("SMARTX_UPGRADE_BACKUP_KEEP_RECENT", None)
            else:
                os.environ["SMARTX_UPGRADE_BACKUP_KEEP_RECENT"] = original

    def test_daemon_disabled_by_zero_interval(self) -> None:
        from app.v2.upgrade.backup_retention import start_backup_cleanup_daemon

        with tempfile.TemporaryDirectory() as tmpdir:
            class _Settings:
                backups_dir = tmpdir

            self.assertIsNone(start_backup_cleanup_daemon(_Settings(), None, interval_seconds=0))

    def test_main_wires_backup_cleanup_daemon(self) -> None:
        import inspect

        from app.v2 import main

        source = inspect.getsource(main.create_app)
        self.assertIn("start_backup_cleanup_daemon", source)
        self.assertIn("backup_cleanup_stop_event.set()", source, "shutdown 必须停止该线程")


if __name__ == "__main__":
    unittest.main()
