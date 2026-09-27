"""49-50：task.migrate_runtime_state 在 bind mount 双视图下不得自删任务目录。"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import tempfile
import unittest
from pathlib import Path


class SameDirectoryTest(unittest.TestCase):
    def test_same_directory_by_inode_not_by_string(self) -> None:
        from app.upgrade_runner.actions import _same_directory

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            real = base / "real"
            real.mkdir()
            alias = base / "alias"  # 符号链接别名：resolve() 能折叠，samefile 也能判等
            alias.symlink_to(real, target_is_directory=True)

            self.assertTrue(_same_directory(real, alias))
            self.assertTrue(_same_directory(real, real))
            other = base / "other"
            other.mkdir()
            self.assertFalse(_same_directory(real, other))
            # 路径不存在时必须安全返回 False（不能抛异常）
            self.assertFalse(_same_directory(real, base / "missing"))
            self.assertFalse(_same_directory(base / "missing", real))


class BindMountAliasMigrationTest(unittest.TestCase):
    """真实 bind mount 双视图（/data/upgrades 与 /data/smartx-storage-forecast/upgrades）场景。

    需要 root + CAP_SYS_ADMIN；容器内不具备时自动跳过，在宿主机 python 上必须能跑。
    """

    def _bind(self, source: Path, target: Path) -> None:
        target.mkdir(parents=True, exist_ok=True)
        rc = os.system(f"mount --bind {shlex.quote(str(source))} {shlex.quote(str(target))} 2>/dev/null")
        if rc != 0:
            self.skipTest("环境不支持 bind mount（需要 root + CAP_SYS_ADMIN）")

    def test_migrate_does_not_delete_task_dir_when_source_and_target_are_bind_views(self) -> None:
        from app.upgrade_runner.actions import ActionContext, task_migrate_runtime_state

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            host_dir = base / "host_upgrades"      # 模拟宿主 upgrades 目录
            mount_a = base / "container_upgrades"  # 容器视图 -> /data/upgrades
            mount_b = base / "host_view"           # 宿主视图 -> /data/smartx-storage-forecast/upgrades
            for task_id in ("upgrade-t1", "upgrade-t2"):
                (host_dir / task_id).mkdir(parents=True)
                (host_dir / task_id / "task.json").write_text(
                    json.dumps({"task_id": task_id, "status": "running"}), encoding="utf-8"
                )

            self._bind(host_dir, mount_a)
            try:
                self._bind(host_dir, mount_b)

                context = ActionContext.minimal(base)
                context.upgrades_path = mount_a
                context.host_upgrades_path = mount_b
                context.task_id = "upgrade-t1"

                payload = context.as_dict()
                action = {
                    "type": "task.migrate_runtime_state",
                    "params": {"target_upgrades_path": str(mount_b)},
                }
                result = task_migrate_runtime_state(action, payload)

                # 修复点：两个视图是同一目录 → 只确保存在，禁止 rmtree
                self.assertTrue((mount_a / "upgrade-t1" / "task.json").is_file())
                self.assertTrue((mount_b / "upgrade-t1" / "task.json").is_file())
                # 相邻任务目录（历史迁移分支）也不能被删
                self.assertTrue((mount_a / "upgrade-t2" / "task.json").is_file())
                self.assertEqual(result["source_task_dir"], str(mount_a / "upgrade-t1"))
                self.assertNotIn(str(mount_a / "upgrade-t2"), result.get("migrated_history_dirs", []))
            finally:
                os.system(f"umount {shlex.quote(str(mount_b))} 2>/dev/null")
                os.system(f"umount {shlex.quote(str(mount_a))} 2>/dev/null")
                shutil.rmtree(mount_a, ignore_errors=True)
                shutil.rmtree(mount_b, ignore_errors=True)

    def test_migrate_still_copies_from_legacy_source_to_target(self) -> None:
        """常规 legacy -> target 迁移路径不能被破坏。"""
        from app.upgrade_runner.actions import ActionContext, task_migrate_runtime_state

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            legacy_root = base / "legacy_upgrades"
            target_root = base / "target_upgrades"
            (legacy_root / "upgrade-legacy").mkdir(parents=True)
            (legacy_root / "upgrade-legacy" / "task.json").write_text(
                json.dumps({"task_id": "upgrade-legacy"}), encoding="utf-8"
            )
            target_root.mkdir(parents=True, exist_ok=True)

            context = ActionContext.minimal(base)
            context.upgrades_path = legacy_root
            context.host_upgrades_path = None
            context.task_id = "upgrade-legacy"
            action = {"type": "task.migrate_runtime_state", "params": {"target_upgrades_path": str(target_root)}}

            result = task_migrate_runtime_state(action, context.as_dict())

            self.assertTrue((target_root / "upgrade-legacy" / "task.json").is_file())
            self.assertTrue((legacy_root / "upgrade-legacy" / "task.json").is_file())
            self.assertEqual(result["source_task_dir"], str(legacy_root / "upgrade-legacy"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
