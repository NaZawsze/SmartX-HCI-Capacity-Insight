from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.upgrade_runner.engine import UpgradeEngine  # noqa: E402
from app.upgrade_runner.store import RevisionConflict, TaskStore  # noqa: E402


def _task(task_id: str = "upgrade-mirror") -> dict:
    return {
        "task_id": task_id,
        "status": "running",
        "created_at": "2026-09-28T00:00:00+00:00",
        "updated_at": "2026-09-28T00:00:00+00:00",
        "execution_plan": {"actions": []},
    }


class MirrorSaveTest(unittest.TestCase):
    """US-24：mirror 与主 store 指向同一文件时不得双写（否则 revision +2 → 下一次保存必冲突）。"""

    def test_same_file_mirror_does_not_double_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir) / "upgrade-mirror"
            store = TaskStore(task_dir)
            store.save(_task())
            engine = UpgradeEngine(store, handlers={})
            task = store.load()
            # 同版本重装场景：migrate 返回的 mirror 是同一目录的另一个路径视图
            task["task_mirror_dir"] = str(task_dir)
            self.assertEqual(task["revision"], 1)  # setup 的那次 save
            task = engine._save(task)
            self.assertEqual(task["revision"], 2)
            # 连续保存不应冲突（修复前：文件已被 mirror 写推到 3，这里会抛 RevisionConflict）
            task = engine._save(task)
            self.assertEqual(task["revision"], 3)
            self.assertEqual(TaskStore(task_dir).load()["revision"], 3)

    def test_same_file_detected_through_relative_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir) / "upgrade-mirror"
            store = TaskStore(task_dir)
            store.save(_task())
            engine = UpgradeEngine(store, handlers={})
            task = store.load()
            task["task_mirror_dir"] = str(task_dir / "." / ".." / task_dir.name)
            task = engine._save(task)
            task = engine._save(task)
            self.assertEqual(task["revision"], 3)
            self.assertEqual(TaskStore(task_dir).load()["revision"], 3)

    def test_separate_mirror_directory_is_still_written(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir) / "target" / "upgrade-mirror"
            mirror_dir = Path(tmpdir) / "legacy" / "upgrade-mirror"
            store = TaskStore(task_dir)
            store.save(_task())
            engine = UpgradeEngine(store, handlers={})
            task = store.load()
            task["task_mirror_dir"] = str(mirror_dir)
            task = engine._save(task)
            # 主 store 正常 +1（setup 后为 1 → 本次 2）；mirror（不同文件）也写出
            self.assertEqual(TaskStore(task_dir).load()["revision"], 2)
            mirrored = json.loads((mirror_dir / "task.json").read_text(encoding="utf-8"))
            self.assertEqual(mirrored["task_id"], "upgrade-mirror")

    def test_revision_conflict_still_raised_for_foreign_writer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir) / "upgrade-mirror"
            store = TaskStore(task_dir)
            store.save(_task())
            engine = UpgradeEngine(store, handlers={})
            task = store.load()
            # 模拟外部写入者（web-api）推进了 revision
            TaskStore(task_dir).save(store.load())
            with self.assertRaises(RevisionConflict):
                engine._save(task)


if __name__ == "__main__":
    unittest.main()
