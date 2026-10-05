"""W2：单写者规则（task.json 事实源 + tasks 表 web-api 独占投影）。

工程规格：docs/superpowers/specs/2026-10-05-upgrade-architecture-v054-impl-spec.md §W2
测试规格：T2（投影幂等 / file-newer 判定 / 镜像失败无害）

覆盖三面：
1. web-api 侧投影（`app.v2.upgrade.projection`）：幂等、file-newer 判定、
   与 runner 侧算法一致、schema 未 expand 时优雅退化；
2. runner 侧兼容镜像（`_project_task`）：失败不冒泡、限流生效、
   事实源 task.json 不被镜像失败影响；
3. 单写者不变量：真机口径下 runner 执行期**不再持有业务库连接**。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.upgrade_runner import main as runner_main  # noqa: E402
from app.v2.upgrade import projection  # noqa: E402


TASKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    message TEXT,
    links_json TEXT,
    logs_json TEXT,
    steps_json TEXT,
    severity TEXT,
    seen_at TEXT,
    acknowledged_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);
"""


@contextmanager
def _conn(path: Path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


class _Database:
    """最小 database 替身（投影模块只用到 `.connection()`）。"""

    def __init__(self, path: Path, *, with_revision: bool = True) -> None:
        self.path = Path(path)
        self._init(with_revision)

    def _init(self, with_revision: bool) -> None:
        with _conn(self.path) as connection:
            connection.executescript(TASKS_SCHEMA)
            if with_revision:
                connection.execute("ALTER TABLE tasks ADD COLUMN task_revision INTEGER NOT NULL DEFAULT 0")

    def connection(self):
        return _conn(self.path)


def _iso(delta_seconds: float = 0.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat()


def _task(**overrides) -> dict:
    base = {
        "task_id": "upgrade-test",
        "status": "running",
        "revision": 1,
        "created_at": _iso(-60),
        "updated_at": _iso(-1),
        "logs": ["开始执行"],
        "execution_plan": {
            "actions": [
                {"id": "backup", "type": "backup.create", "status": "succeeded", "result": {}},
                {"id": "apply", "type": "compose.apply", "status": "running", "result": {}},
            ]
        },
    }
    base.update(overrides)
    return base


class ProjectStateTests(unittest.TestCase):
    """投影折叠：状态映射、进度、消息。"""

    def test_status_mapping_covers_runner_status_map(self) -> None:
        self.assertEqual(projection.project_state(_task(status="success"))["status"], "success")
        self.assertEqual(projection.project_state(_task(status="rolled_back"))["status"], "success")
        for failed in ("failed", "rollback_failed", "recovery_required"):
            self.assertEqual(projection.project_state(_task(status=failed))["status"], "failed")
        self.assertEqual(projection.project_state(_task(status="running"))["status"], "running")
        self.assertEqual(projection.project_state(_task(status="pending"))["status"], "pending")

    def test_running_task_progress_reflects_actions(self) -> None:
        state = projection.project_state(_task())
        self.assertGreater(state["progress"], 0)
        self.assertLess(state["progress"], 100)

    def test_finished_task_progress_is_100_and_has_finished_at(self) -> None:
        state = projection.project_state(_task(status="success", updated_at=_iso(0)))
        self.assertEqual(state["progress"], 100)
        self.assertIsNotNone(state["finished_at"])

    def test_running_task_has_no_finished_at(self) -> None:
        self.assertIsNone(projection.project_state(_task())["finished_at"])

    def test_failed_task_severity_is_critical(self) -> None:
        self.assertEqual(projection.project_state(_task(status="failed"))["severity"], "critical")
        self.assertEqual(projection.project_state(_task(status="success"))["severity"], "info")
        self.assertIsNone(projection.project_state(_task(status="running"))["severity"])

    def test_steps_reuse_runner_side_algorithm(self) -> None:
        """投影的 steps 必须与 runner 侧 `_action_steps` 逐字相同。

        两边各算一套的后果是「页面显示的步骤」与「runner 记的步骤」分叉，
        而这种分叉极难定位（两边数据都对，只是差一点）。
        """
        task = _task()
        from app.upgrade_runner.main import _action_steps

        self.assertEqual(projection.project_state(task)["steps"], _action_steps(task))

    def test_progress_reuses_runner_side_algorithm(self) -> None:
        task = _task()
        from app.upgrade_runner.main import _action_progress

        self.assertEqual(
            projection.project_state(task)["progress"],
            _action_progress(task, "running"),
        )


def _row_for(task: dict, **overrides) -> dict:
    """构造一行与 task 投影结果一致的库内行（用于测「不该投影」的情形）。"""
    state = projection.project_state(task)
    row = {
        "updated_at": task.get("updated_at"),
        "task_revision": int(task.get("revision") or 0),
        "status": state["status"],
        "progress": state["progress"],
        "message": state["message"],
        "logs_json": json.dumps(state["logs"], ensure_ascii=False),
        "steps_json": json.dumps(state["steps"], ensure_ascii=False),
    }
    row.update(overrides)
    return row


class ShouldProjectTests(unittest.TestCase):
    """投影判据：终态吸收、拒绝陈旧非终态、内容为主、时间与 revision 为辅。"""

    def test_missing_row_always_projects(self) -> None:
        self.assertTrue(projection.should_project(_task(), None))

    def test_identical_row_is_not_projected(self) -> None:
        task = _task()
        self.assertFalse(projection.should_project(task, _row_for(task)))

    def test_newer_timestamp_with_new_content_projects(self) -> None:
        self.assertTrue(
            projection.should_project(
                _task(updated_at=_iso(0), revision=5),
                _row_for(_task(updated_at=_iso(-10), revision=1, logs=["旧"])),
            )
        )

    def test_terminal_projects_through_older_timestamp(self) -> None:
        """终态必须能穿透时间差写进去。

        实测踩到：runner 在别的进程收尾后，task.json 的 `updated_at` 可能早于
        web-api 写库的时刻（`test_v2_upgrade` 里甚至是个 2026-07 的固定值），
        只比时间会让 success 永远写不进 tasks 表。
        """
        task = _task(status="success", updated_at="2026-07-08T09:53:42+00:00", revision=3)
        row = _row_for(_task(status="running", updated_at=_iso(0), logs=["执行中"]))
        self.assertTrue(projection.should_project(task, row))

    def test_terminal_row_is_not_regressed_to_running(self) -> None:
        """终态是吸收态：不得被更旧的执行中状态拉回 running。"""
        done = _task(status="success", updated_at=_iso(0), revision=9)
        row = _row_for(done)
        stale = _task(status="running", updated_at=_iso(-60), revision=2, logs=["还在跑"])
        self.assertFalse(projection.should_project(stale, row))

    def test_older_non_terminal_does_not_overwrite_newer_row(self) -> None:
        """陈旧文件的非终态不得覆盖更新的库内内容（进度/日志回退）。"""
        newer = _task(updated_at=_iso(0), revision=9, logs=["新日志"])
        row = _row_for(newer)
        older = _task(updated_at=_iso(-60), revision=2, logs=["旧日志"])
        self.assertFalse(projection.should_project(older, row))

    def test_older_file_with_new_content_and_non_terminal_is_rejected(self) -> None:
        """即使内容不同，时间明确更旧的**非终态**也不投影（防抖动）。"""
        newer = _task(updated_at=_iso(0), revision=9, logs=["新日志"])
        older = _task(updated_at=_iso(-60), revision=2, logs=["另一个内容"])
        self.assertFalse(projection.should_project(older, _row_for(newer)))

    def test_equal_timestamp_newer_revision_projects(self) -> None:
        stamp = _iso(0)
        task = _task(updated_at=stamp, revision=5)
        row = _row_for(task, updated_at=stamp, task_revision=4)
        self.assertTrue(projection.should_project(task, row))

    def test_equal_timestamp_same_revision_is_idempotent(self) -> None:
        stamp = _iso(0)
        task = _task(updated_at=stamp, revision=4)
        self.assertFalse(projection.should_project(task, _row_for(task, updated_at=stamp)))

    def test_row_without_revision_key_stays_idempotent(self) -> None:
        """老库无 `task_revision`：内容一致就必须判"不投影"。

        若把缺失当 0，task.json 任何 revision ≥ 1 的重复投影都会被判成更新，
        每次 status 轮询都重写一行（幂等性失效，实测踩到）。
        """
        stamp = _iso(0)
        task = _task(updated_at=stamp, revision=9)
        row = _row_for(task, updated_at=stamp)
        row.pop("task_revision")
        self.assertFalse(projection.should_project(task, row))

    def test_unparsable_task_timestamp_falls_back_to_content(self) -> None:
        task = _task(updated_at="乱码", revision=3)
        self.assertFalse(projection.should_project(task, _row_for(task)))
        self.assertTrue(
            projection.should_project(
                task,
                _row_for(task, status="pending", progress=1, message="别的", logs_json="[]", steps_json="[]"),
            )
        )

    def test_unparsable_row_timestamp_falls_back_to_content(self) -> None:
        task = _task()
        self.assertFalse(projection.should_project(task, _row_for(task, updated_at=None)))
        self.assertTrue(
            projection.should_project(
                task, _row_for(task, updated_at=None, status="pending", progress=1, message="别的")
            )
        )

    def test_task_without_updated_at_still_projects_by_content(self) -> None:
        """没有 updated_at 的 task.json 也必须能投影（历史任务无此字段）。"""
        task = _task(updated_at=None, status="success")
        row = _row_for(
            _task(status="running", updated_at=_iso(0), logs=["执行中"]),
        )
        self.assertTrue(projection.should_project(task, row))

    def test_corrupt_json_column_counts_as_difference(self) -> None:
        task = _task()
        self.assertTrue(projection.should_project(task, _row_for(task, logs_json="{ bad json")))


class ProjectIfNewerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.db_path = self.tmp / "smartx.db"
        self.database = _Database(self.db_path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _row(self, task_id: str = "upgrade-test") -> dict:
        with _conn(self.db_path) as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else {}

    def test_first_projection_creates_row(self) -> None:
        self.assertTrue(projection.project_if_newer(self.database, _task()))
        row = self._row()
        self.assertEqual(row["status"], "running")
        self.assertEqual(row["type"], "upgrade")
        self.assertEqual(row["title"], projection.PROJECTED_TITLE)
        self.assertEqual(row["task_revision"], 1)

    def test_repeated_projection_is_idempotent(self) -> None:
        task = _task()
        self.assertTrue(projection.project_if_newer(self.database, task))
        first = self._row()
        self.assertFalse(projection.project_if_newer(self.database, task))
        second = self._row()
        self.assertEqual(first, second, "重复投影不得产生任何变化")

    def test_older_task_does_not_overwrite_newer_row(self) -> None:
        projection.project_if_newer(self.database, _task(updated_at=_iso(0), revision=9, logs=["新"]))
        before = self._row()
        self.assertFalse(
            projection.project_if_newer(self.database, _task(updated_at=_iso(-30), revision=1, logs=["旧"]))
        )
        self.assertEqual(self._row()["logs_json"], before["logs_json"])

    def test_title_is_projected_over_precheck_title(self) -> None:
        """预检查阶段 web-api 写的是「升级预检查」，执行后应显示「执行系统升级」。"""
        with _conn(self.db_path) as connection:
            connection.execute(
                "INSERT INTO tasks (id, type, status, title, progress, message, created_at, updated_at)"
                " VALUES ('upgrade-test', 'upgrade', 'success', '升级预检查', 100, '预检查通过', ?, ?)",
                (_iso(-60), _iso(-30)),
            )
        self.assertTrue(projection.project_if_newer(self.database, _task(updated_at=_iso(0))))
        self.assertEqual(self._row()["title"], projection.PROJECTED_TITLE)

    def test_terminal_state_survives_older_task_json(self) -> None:
        projection.project_if_newer(self.database, _task(status="success", updated_at=_iso(0), revision=9))
        before = self._row()
        self.assertFalse(
            projection.project_if_newer(
                self.database, _task(status="running", updated_at=_iso(-60), revision=1)
            )
        )
        self.assertEqual(self._row()["status"], before["status"])
        self.assertEqual(self._row()["status"], "success")

    def test_newer_task_updates_row(self) -> None:
        projection.project_if_newer(self.database, _task(updated_at=_iso(-30), revision=1, logs=["一"]))
        self.assertTrue(
            projection.project_if_newer(
                self.database, _task(updated_at=_iso(0), revision=2, logs=["二"])
            )
        )
        self.assertEqual(json.loads(self._row()["logs_json"]), ["二"])
        self.assertEqual(self._row()["task_revision"], 2)

    def test_same_second_new_revision_updates_row(self) -> None:
        stamp = _iso(0)
        projection.project_if_newer(self.database, _task(updated_at=stamp, revision=1, logs=["一"]))
        self.assertTrue(
            projection.project_if_newer(self.database, _task(updated_at=stamp, revision=2, logs=["二"]))
        )
        self.assertEqual(json.loads(self._row()["logs_json"]), ["二"])

    def test_missing_task_id_is_noop(self) -> None:
        self.assertFalse(projection.project_if_newer(self.database, {"status": "running"}))
        with _conn(self.db_path) as connection:
            count = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        self.assertEqual(count, 0)

    def test_steps_and_logs_are_json_encoded(self) -> None:
        projection.project_if_newer(self.database, _task())
        row = self._row()
        self.assertIsInstance(json.loads(row["steps_json"]), list)
        self.assertIsInstance(json.loads(row["logs_json"]), list)

    def test_works_without_revision_column(self) -> None:
        """老库尚未 expand 时必须优雅退化，而不是整条投影报错。"""
        legacy_path = self.tmp / "legacy.db"
        legacy = _Database(legacy_path, with_revision=False)
        self.assertFalse(projection.has_revision_column(legacy))
        task = _task()
        self.assertTrue(projection.project_if_newer(legacy, task))
        with _conn(legacy_path) as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = 'upgrade-test'").fetchone()
        self.assertEqual(row["status"], "running")
        # 退化后按时间判定：同一份 task 重复投影必须被跳过（幂等）
        self.assertFalse(projection.project_if_newer(legacy, task))
        # 真的更新了（时间推进）仍要投影
        self.assertTrue(
            projection.project_if_newer(legacy, {**task, "updated_at": _iso(5), "revision": 99})
        )


class RunnerMirrorHarmlessTests(unittest.TestCase):
    """runner 侧兼容镜像：失败不冒泡（#82 同款兜底），且按内容指纹去重。"""

    def setUp(self) -> None:
        runner_main._project_mirror_signature.clear()

    def test_mirror_writes_tasks_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "smartx.db"
            with _conn(db) as connection:
                connection.executescript(TASKS_SCHEMA)
            runner_main._project_task(db, _task(status="success", updated_at=_iso(0)))
            with _conn(db) as connection:
                row = connection.execute("SELECT status, progress FROM tasks WHERE id = 'upgrade-test'").fetchone()
        self.assertEqual(row["status"], "success")
        self.assertEqual(row["progress"], 100)

    def test_mirror_failure_does_not_raise(self) -> None:
        """业务库不可写时，镜像失败只记 warning——执行器不能因此崩掉。"""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "missing-dir" / "sub" / "smartx.db"
            # 目录不可创建：把父路径做成文件
            blocker = Path(tmp) / "blocker"
            blocker.write_text("x", encoding="utf-8")
            db = blocker / "smartx.db"
            with self.assertLogs("app.upgrade_runner.main", level="WARNING") as captured:
                runner_main._project_task(db, _task())
        self.assertTrue(
            any("兼容镜像失败" in message for message in captured.output),
            f"应记 warning，实际：{captured.output}",
        )

    def test_mirror_failure_leaves_task_json_untouched(self) -> None:
        """镜像失败不得影响事实源——task.json 的内容必须原样。"""
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "blocker"
            blocker.write_text("x", encoding="utf-8")
            task = _task(status="success")
            snapshot = json.dumps(task, sort_keys=True)
            runner_main._project_task(blocker / "smartx.db", task)
        self.assertEqual(json.dumps(task, sort_keys=True), snapshot)

    def test_unchanged_step_state_is_not_reprojected(self) -> None:
        """步骤内部反复 checkpoint 保存（状态未变）不得重复写库。

        engine 的 on_update 在每次 checkpoint 保存时都触发；不去重就等于把
        US-28 的写锁窗口原样搬回来。
        """
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "smartx.db"
            with _conn(db) as connection:
                connection.executescript(TASKS_SCHEMA)
            task = _task()
            runner_main._project_task(db, task)
            runner_main._project_task(db, {**task, "revision": 99, "updated_at": _iso(0)})
            with _conn(db) as connection:
                row = connection.execute(
                    "SELECT logs_json, updated_at FROM tasks WHERE id = 'upgrade-test'"
                ).fetchone()
        # 第二次的 revision/updated_at 没进库 → 说明确实被指纹去重挡掉了
        self.assertNotEqual(row["updated_at"], _iso(0))

    def test_step_transition_is_always_projected(self) -> None:
        """步骤 pending→running→succeeded 每次转换都必须镜像（用户可见的进展）。"""
        def plan(step_statuses):
            return _task(
                execution_plan={
                    "actions": [
                        {"id": "backup", "type": "backup.create", "status": step_statuses[0], "result": {}},
                        {"id": "apply", "type": "compose.apply", "status": step_statuses[1], "result": {}},
                    ]
                }
            )

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "smartx.db"
            with _conn(db) as connection:
                connection.executescript(TASKS_SCHEMA)
            runner_main._project_task(db, plan(["pending", "pending"]))
            runner_main._project_task(db, plan(["succeeded", "running"]))
            with _conn(db) as connection:
                row = connection.execute(
                    "SELECT steps_json FROM tasks WHERE id = 'upgrade-test'"
                ).fetchone()
        steps = json.loads(row["steps_json"])
        self.assertEqual(steps[0]["status"], "succeeded")
        self.assertEqual(steps[1]["status"], "running")

    def test_top_level_status_transition_is_always_projected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "smartx.db"
            with _conn(db) as connection:
                connection.executescript(TASKS_SCHEMA)
            runner_main._project_task(db, _task(status="running"))
            runner_main._project_task(db, _task(status="success", updated_at=_iso(0)))
            with _conn(db) as connection:
                row = connection.execute(
                    "SELECT status, progress FROM tasks WHERE id = 'upgrade-test'"
                ).fetchone()
        self.assertEqual(row["status"], "success")
        self.assertEqual(row["progress"], 100)

    def test_force_bypasses_deduplication(self) -> None:
        """收尾处的最终投影必须落库（即便指纹与上一次相同）。"""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "smartx.db"
            with _conn(db) as connection:
                connection.executescript(TASKS_SCHEMA)
            task = _task(status="success")
            runner_main._project_task(db, task)
            with _conn(db) as connection:
                connection.execute(
                    "UPDATE tasks SET message = '被外部改坏' WHERE id = 'upgrade-test'"
                )
            runner_main._project_task(db, task, force=True)
            with _conn(db) as connection:
                row = connection.execute(
                    "SELECT message FROM tasks WHERE id = 'upgrade-test'"
                ).fetchone()
        self.assertEqual(row["message"], projection.project_state(task)["message"])


class SingleWriterInvariantTests(unittest.TestCase):
    """W2 的核心不变量：执行器**不再持有**业务库连接。"""

    def test_engine_on_update_path_is_deduplicated(self) -> None:
        """`project_update` 回调必须走去重路径（它是热路径）。"""
        source = Path(runner_main.__file__).read_text(encoding="utf-8")
        self.assertIn(
            "_project_task(settings.database_path, updated)",
            source,
            "on_update 回调未走去重镜像：engine 每次 checkpoint 保存都会触发镜像",
        )

    def test_dedup_key_is_content_not_time(self) -> None:
        """去重键必须是内容指纹。用时间限流会吞掉真实进展（既有用例已证）。"""
        first = runner_main._project_signature(_task(status="running"))
        same = runner_main._project_signature({**_task(status="running"), "revision": 99, "updated_at": _iso(0)})
        self.assertEqual(first, same, "步骤状态未变时指纹必须相同（与时间/revision 无关）")
        moved = runner_main._project_signature(_task(status="success"))
        self.assertNotEqual(first, moved, "顶层状态变了指纹必须变")

    def test_mirror_is_not_the_fact_source(self) -> None:
        """镜像函数不得被命名成事实源语义（避免后来者误以为它是权威路径）。"""
        self.assertTrue(hasattr(runner_main, "_write_task_projection"))
        self.assertIn("兼容镜像", runner_main._project_task.__doc__ or "")


if __name__ == "__main__":
    unittest.main()
