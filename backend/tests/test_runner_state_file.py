"""W1：runner 状态文件（US-28 / #82 根治）。

工程规格：docs/superpowers/specs/2026-10-05-upgrade-architecture-v054-impl-spec.md §W1

覆盖面：
- T1 状态文件原子写 / 损坏自愈 / schema 演进容错 / 并发；
- LeaseManager 的事实源切换（文件优先）与 DB 镜像失败无害；
- web-api 侧 presence 的文件优先、DB 兜底（M5 格），以及两侧路径推导必须一致。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.upgrade_runner.lease import LeaseManager  # noqa: E402
from app.upgrade_runner.statefile import (  # noqa: E402
    ROLLBACK_ANCHOR_HISTORY,
    STATE_SCHEMA_VERSION,
    RunnerStateStore,
    parse_timestamp,
    state_file_path,
)
from app.v2.upgrade.service.runner_presence import (  # noqa: E402
    HEARTBEAT_SOURCE,
    TASK_LEASE_SOURCE,
    active_task_lease_is_fresh,
    file_task_lease_is_fresh,
    instance_heartbeat_is_fresh,
    presence_source,
    read_state_file,
    state_file_instance_state,
    state_file_path as web_state_file_path,
    task_lease_is_alive,
)


def _iso(delta_seconds: float = 0.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat()


class _Settings:
    """最小 settings 替身：只提供 presence 推导需要的属性。"""

    def __init__(self, sqlite_path: Path) -> None:
        self.sqlite_path = sqlite_path


class _FakeDatabase:
    """最小 database 替身：`connection()` 上下文管理器返回可执行 SQL 的连接。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def connection(self):
        database = self

        class _Ctx:
            def __enter__(self):
                self.conn = sqlite3.connect(database.path)
                self.conn.row_factory = sqlite3.Row
                return self.conn

            def __exit__(self, *_exc):
                self.conn.close()
                return False

        return _Ctx()


MIRROR_SCHEMA = """
CREATE TABLE IF NOT EXISTS upgrade_runner_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    instance_id TEXT NOT NULL,
    runner_version TEXT NOT NULL,
    protocol_version INTEGER NOT NULL,
    capabilities_json TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS upgrade_task_leases (
    task_id TEXT PRIMARY KEY,
    lease_owner TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0
);
"""


@contextmanager
def _rows(path: Path):
    """`sqlite3.connect` 默认返回 tuple 行；这里给 Row 工厂以便按列名取值。"""
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _make_db(tmp: Path) -> Path:
    """建业务库并**预先建好两张镜像表**。

    镜像表的存在不该是测试的前提条件——但反过来，只测「表不存在」这一种情形会漏掉
    「表在、内容旧」的情形，两种都要覆盖，故这里统一先建好表，缺表情形单独用
    `test_missing_mirror_tables_do_not_break_presence` 覆盖。
    """
    path = tmp / "smartx.db"
    connection = sqlite3.connect(path)
    try:
        connection.executescript(MIRROR_SCHEMA)
        connection.commit()
    finally:
        connection.close()
    return path


class StateFileAtomicWriteTests(unittest.TestCase):
    """T1：原子写。并发读者任何时刻都只能读到完整 JSON。"""

    def test_state_path_derived_from_database_path(self) -> None:
        self.assertEqual(
            state_file_path("/data/smartx.db"), Path("/data/upgrade-runner-state.json")
        )
        self.assertEqual(
            state_file_path(Path("/data/smartx-storage-forecast/app/smartx.db")),
            Path("/data/smartx-storage-forecast/app/upgrade-runner-state.json"),
        )

    def test_heartbeat_writes_parseable_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RunnerStateStore(Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, ["health.v1"])
            self.assertTrue(store.heartbeat())
            payload = json.loads(store.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], STATE_SCHEMA_VERSION)
        self.assertEqual(payload["instance_id"], "runner-a")
        self.assertEqual(payload["runner_version"], "v0.3.2")
        self.assertEqual(payload["capabilities"], ["health.v1"])
        self.assertEqual(payload["leases"], {})

    def test_no_temporary_file_left_behind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RunnerStateStore(Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, [])
            for _ in range(5):
                store.heartbeat()
            leftovers = [item.name for item in Path(tmp).iterdir() if item.name != store.path.name]
        self.assertEqual(leftovers, [], f"原子写应清理临时文件，实际残留：{leftovers}")

    def test_concurrent_heartbeat_and_lease_writes_always_parse(self) -> None:
        """并发写：读者任一时刻读到的都必须是可解析的完整 JSON（os.replace 的保证）。"""
        with tempfile.TemporaryDirectory() as tmp:
            store = RunnerStateStore(Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, [])
            store.heartbeat()
            errors: list[str] = []
            stop = threading.Event()

            def reader() -> None:
                while not stop.is_set():
                    try:
                        payload = json.loads(store.path.read_text(encoding="utf-8"))
                        if "leases" not in payload or "heartbeat_at" not in payload:
                            errors.append(f"字段缺失：{sorted(payload)}")
                    except FileNotFoundError:
                        errors.append("读取时文件不存在（replace 窗口不应出现）")
                    except ValueError as exc:
                        errors.append(f"半截 JSON：{exc}")

            readers = [threading.Thread(target=reader, daemon=True) for _ in range(3)]
            for item in readers:
                item.start()
            writers = [
                threading.Thread(target=lambda n=n: [store.heartbeat() for _ in range(40)], daemon=True)
                for n in range(2)
            ]
            writers.append(
                threading.Thread(
                    target=lambda: [
                        store.upsert_lease(f"task-{index}", "runner-a", revision=index)
                        for index in range(20)
                    ],
                    daemon=True,
                )
            )
            for item in writers:
                item.start()
            for item in writers:
                item.join(timeout=30)
            stop.set()
            for item in readers:
                item.join(timeout=5)
            payload = json.loads(store.path.read_text(encoding="utf-8"))
        self.assertEqual(errors[:5], [], f"并发读见到不一致状态：{errors[:5]}")
        self.assertEqual(len(payload["leases"]), 20)

    def test_failed_write_does_not_corrupt_existing_file(self) -> None:
        """写失败必须保留上一份完整文件（_mutate 的 mutator 抛异常时不落盘）。"""
        with tempfile.TemporaryDirectory() as tmp:
            store = RunnerStateStore(Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, [])
            store.heartbeat()
            before = store.path.read_text(encoding="utf-8")

            def explode(_payload):
                raise RuntimeError("模拟写入中断")

            with self.assertRaises(RuntimeError):
                store._mutate(explode)
            after = store.path.read_text(encoding="utf-8")
        self.assertEqual(before, after)


class StateFileSelfHealTests(unittest.TestCase):
    """T1：损坏自愈。坏文件改名留证，runner 仍能起来。"""

    def test_corrupt_file_is_quarantined_and_state_rebuilt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = state_file_path(Path(tmp) / "smartx.db")
            path.write_text("{ this is not json", encoding="utf-8")
            store = RunnerStateStore(Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, [])
            payload = store.read()
            leftovers = sorted(item.name for item in Path(tmp).iterdir())
        self.assertEqual(payload["leases"], {})
        self.assertEqual(payload["instance_id"], "runner-a")
        quarantined = [name for name in leftovers if ".corrupt-" in name]
        self.assertEqual(len(quarantined), 1, f"坏文件应改名留证，实际：{leftovers}")

    def test_non_object_json_is_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = state_file_path(Path(tmp) / "smartx.db")
            path.write_text("[1, 2, 3]", encoding="utf-8")
            store = RunnerStateStore(Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, [])
            payload = store.read()
            leftovers = [item.name for item in Path(tmp).iterdir()]
        self.assertEqual(payload["leases"], {})
        self.assertTrue(any(".corrupt-" in name for name in leftovers), leftovers)

    def test_missing_file_reads_as_empty_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RunnerStateStore(Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, [])
            payload = store.read()
        self.assertEqual(payload["leases"], {})
        self.assertTrue(payload["heartbeat_at"])

    def test_heartbeat_after_corruption_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = state_file_path(Path(tmp) / "smartx.db")
            path.write_text("not json at all", encoding="utf-8")
            store = RunnerStateStore(Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, [])
            self.assertTrue(store.heartbeat())
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["runner_version"], "v0.3.2")


class StateFileSchemaEvolutionTests(unittest.TestCase):
    """T1：schema 演进容错。字段只增补，reader 容忍缺失与多余键。"""

    def test_unknown_keys_are_tolerated_and_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = state_file_path(Path(tmp) / "smartx.db")
            path.write_text(
                json.dumps({"schema": 99, "heartbeat_at": _iso(), "future_field": {"a": 1}}),
                encoding="utf-8",
            )
            store = RunnerStateStore(Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, [])
            payload = store.read()
        self.assertEqual(payload["future_field"], {"a": 1})
        self.assertEqual(payload["leases"], {})

    def test_missing_fields_get_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = state_file_path(Path(tmp) / "smartx.db")
            path.write_text(json.dumps({"schema": 1}), encoding="utf-8")
            store = RunnerStateStore(Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, ["x.v1"])
            payload = store.read()
        self.assertEqual(payload["runner_version"], "v0.3.2")
        self.assertEqual(payload["protocol_version"], 1)
        self.assertEqual(payload["leases"], {})

    def test_leases_of_wrong_type_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = state_file_path(Path(tmp) / "smartx.db")
            path.write_text(json.dumps({"schema": 1, "leases": ["oops"]}), encoding="utf-8")
            store = RunnerStateStore(Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, [])
            payload = store.read()
        self.assertEqual(payload["leases"], {})

    def test_parse_timestamp_accepts_naive_and_zulu(self) -> None:
        self.assertIsNotNone(parse_timestamp("2026-10-05T08:00:00"))
        self.assertIsNotNone(parse_timestamp("2026-10-05T08:00:00Z"))
        self.assertIsNotNone(parse_timestamp("2026-10-05T08:00:00+00:00"))
        self.assertIsNone(parse_timestamp(""))
        self.assertIsNone(parse_timestamp("not a time"))
        self.assertIsNone(parse_timestamp(None))


class StateFileLeaseTests(unittest.TestCase):
    """租约语义必须与原 `LeaseManager` 一致（只换存储，不改语义）。"""

    def test_acquire_then_renew_then_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RunnerStateStore(Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, [])
            self.assertTrue(store.upsert_lease("t1", "runner-a", revision=1))
            self.assertTrue(store.renew_lease("t1", revision=2))
            lease = store.lease("t1")
            self.assertEqual(lease["lease_owner"], "runner-a")
            self.assertEqual(lease["revision"], 2)
            store.release_lease("t1")
            self.assertIsNone(store.lease("t1"))

    def test_other_owner_holds_unexpired_lease_blocks_acquire(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RunnerStateStore(Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, [])
            self.assertTrue(store.upsert_lease("t1", "runner-b", revision=1))
            self.assertFalse(store.upsert_lease("t1", "runner-a", revision=1))

    def test_expired_lease_of_other_owner_can_be_taken_over(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RunnerStateStore(
                Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, [], ttl_seconds=30
            )
            past = datetime.now(timezone.utc) - timedelta(seconds=120)
            self.assertTrue(store.upsert_lease("t1", "runner-b", revision=1, now=past))
            self.assertTrue(store.upsert_lease("t1", "runner-a", revision=2))

    def test_renew_returns_false_for_foreign_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RunnerStateStore(Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, [])
            store.upsert_lease("t1", "runner-b", revision=1)
            self.assertFalse(store.renew_lease("t1"))
            self.assertEqual(store.lease("t1")["lease_owner"], "runner-b")

    def test_release_does_not_clear_other_owner_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RunnerStateStore(Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, [])
            store.upsert_lease("t1", "runner-b", revision=1)
            store.release_lease("t1")
            self.assertIsNotNone(store.lease("t1"), "别人的租约不能被本实例清掉")

    def test_renew_unknown_task_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RunnerStateStore(Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, [])
            self.assertFalse(store.renew_lease("never-seen"))

    def test_save_checkpoint_roundtrips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RunnerStateStore(Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, [])
            store.upsert_lease("t1", "runner-a", revision=1)
            store.save_checkpoint("t1", {"rollback_anchor": {"previous_version": "v0.5.3"}})
            self.assertEqual(
                store.lease("t1")["checkpoint"]["rollback_anchor"]["previous_version"], "v0.5.3"
            )

    def test_save_checkpoint_creates_lease_entry_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RunnerStateStore(Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, [])
            store.save_checkpoint("t-new", {"note": "x"})
            self.assertEqual(store.lease("t-new")["checkpoint"], {"note": "x"})

    def test_rollback_anchor_survives_lease_release(self) -> None:
        """A5：租约条目在 release 时被 pop，锚点必须活在持久段里。"""
        with tempfile.TemporaryDirectory() as tmp:
            store = RunnerStateStore(Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, [])
            store.upsert_lease("t1", "runner-a", revision=1)
            store.save_rollback_anchor("t1", {"previous_version": "v0.5.3", "captured_at": "2026-01-01T00:00:00+00:00"})
            store.release_lease("t1")
            self.assertIsNone(store.lease("t1"), "租约本身应被释放")
            self.assertEqual(store.rollback_anchor("t1")["previous_version"], "v0.5.3")

    def test_rollback_anchor_history_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RunnerStateStore(Path(tmp) / "smartx.db", "runner-a", "v0.3.2", 1, [])
            for index in range(ROLLBACK_ANCHOR_HISTORY + 5):
                store.save_rollback_anchor(
                    f"t{index}", {"captured_at": f"2026-01-01T00:00:{index:02d}+00:00"}
                )
            anchors = store.read()["rollback_anchors"]
            self.assertEqual(len(anchors), ROLLBACK_ANCHOR_HISTORY)
            newest = max(anchors.items(), key=lambda item: item[1]["captured_at"])
            self.assertEqual(newest[0], f"t{ROLLBACK_ANCHOR_HISTORY + 4}")

    def test_lease_manager_exposes_anchor_roundtrip(self) -> None:
        from app.upgrade_runner.lease import LeaseManager

        with tempfile.TemporaryDirectory() as tmp:
            manager = LeaseManager(Path(tmp) / "smartx.db", "runner-a", ttl_seconds=30)
            manager.save_rollback_anchor("t1", {"previous_version": "v0.5.2"})
            self.assertEqual(manager.rollback_anchor("t1")["previous_version"], "v0.5.2")


class LeaseManagerStateFileTests(unittest.TestCase):
    """LeaseManager：事实源 = 状态文件，DB 只剩兼容镜像。"""

    def test_state_file_is_written_on_construction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(Path(tmp))
            lease = LeaseManager(db, "runner-a")
            payload = json.loads(state_file_path(db).read_text(encoding="utf-8"))
        self.assertEqual(payload["instance_id"], "runner-a")

    def test_acquire_renew_release_reach_both_channels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(Path(tmp))
            lease = LeaseManager(db, "runner-a")
            self.assertTrue(lease.acquire("t1", revision=1))
            payload = json.loads(state_file_path(db).read_text(encoding="utf-8"))
            self.assertIn("t1", payload["leases"])
            with _rows(db) as conn:
                row = conn.execute(
                    "SELECT lease_owner FROM upgrade_task_leases WHERE task_id = 't1'"
                ).fetchone()
            self.assertEqual(row["lease_owner"], "runner-a")

            self.assertTrue(lease.heartbeat("t1", revision=2))
            lease.release("t1")
            payload = json.loads(state_file_path(db).read_text(encoding="utf-8"))
            self.assertNotIn("t1", payload["leases"])
            with _rows(db) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM upgrade_task_leases WHERE task_id = 't1'"
                ).fetchone()
            self.assertEqual(row["c"], 0)

    def test_runner_state_reported_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(Path(tmp))
            lease = LeaseManager(db, "runner-a")
            lease.update_runner_state("v0.3.2")
            state = lease.runner_state()
        self.assertEqual(state["runner_version"], "v0.3.2")
        self.assertEqual(state["instance_id"], "runner-a")

    def test_get_falls_back_to_db_when_file_has_no_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(Path(tmp))
            lease = LeaseManager(db, "runner-a")
            with sqlite3.connect(db) as conn:
                conn.execute(
                    "INSERT INTO upgrade_task_leases VALUES (?, ?, ?, ?, ?)",
                    ("legacy-task", "runner-old", _iso(60), _iso(5), 3),
                )
            found = lease.get("legacy-task")
        self.assertEqual(found["lease_owner"], "runner-old")
        self.assertEqual(found["revision"], 3)

    def test_save_checkpoint_goes_to_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(Path(tmp))
            lease = LeaseManager(db, "runner-a")
            lease.acquire("t1", revision=1)
            lease.save_checkpoint("t1", {"anchor": "v0.5.3"})
            payload = json.loads(state_file_path(db).read_text(encoding="utf-8"))
        self.assertEqual(payload["leases"]["t1"]["checkpoint"], {"anchor": "v0.5.3"})


class DbMirrorFailureHarmlessTests(unittest.TestCase):
    """#82 兜底语义升级为「镜像失败无害」：DB 写失败不得冒泡、不得影响主流程。"""

    def test_heartbeat_survives_db_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(Path(tmp))
            lease = LeaseManager(db, "runner-a")
            lease.acquire("t1", revision=1)  # 先取得租约，否则续租本就应当返回 False

            def boom():
                raise sqlite3.OperationalError("database is locked")

            # 逐条替换**每一条**镜像写路径：只替换建表路径会漏掉「续租镜像失败」这一情形，
            # 而那正是升级执行期每 5 秒发生的写。
            lease._mirror_write_state = boom  # type: ignore[method-assign]
            lease._mirror_renew = boom  # type: ignore[method-assign]
            with self.assertLogs("app.upgrade_runner.lease", level="WARNING") as captured:
                lease.update_runner_state("v0.3.2")
                self.assertTrue(lease.heartbeat("t1", revision=1))
                mid_run = json.loads(state_file_path(db).read_text(encoding="utf-8"))
                lease.release("t1")
            after_release = json.loads(state_file_path(db).read_text(encoding="utf-8"))
        self.assertTrue(
            any("镜像" in message for message in captured.output),
            f"镜像失败应记 warning，实际日志：{captured.output}",
        )
        self.assertEqual(mid_run["runner_version"], "v0.3.2")
        self.assertIn("t1", mid_run["leases"])
        self.assertNotIn("t1", after_release["leases"])

    def test_mirror_table_creation_failure_does_not_block_startup(self) -> None:
        """为一张兼容镜像表建表失败就让 runner 起不来，代价与收益不成比例。"""
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(Path(tmp))

            def boom():
                raise sqlite3.OperationalError("database is locked")

            original_create = LeaseManager._create_mirror_tables
            try:
                LeaseManager._create_mirror_tables = boom  # type: ignore[method-assign]
                with self.assertLogs("app.upgrade_runner.lease", level="WARNING"):
                    lease = LeaseManager(db, "runner-a")
            finally:
                LeaseManager._create_mirror_tables = original_create  # type: ignore[method-assign]
            self.assertTrue(state_file_path(db).is_file())
            lease.update_runner_state("v0.3.2")
            payload = json.loads(state_file_path(db).read_text(encoding="utf-8"))
        self.assertEqual(payload["runner_version"], "v0.3.2")

    def test_acquire_returns_file_result_when_mirror_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(Path(tmp))
            lease = LeaseManager(db, "runner-a")

            def boom():
                raise sqlite3.OperationalError("database is locked")

            lease._mirror_acquire = boom  # type: ignore[method-assign]
            with self.assertLogs("app.upgrade_runner.lease", level="WARNING"):
                self.assertTrue(lease.acquire("t1", revision=1))
            payload = json.loads(state_file_path(db).read_text(encoding="utf-8"))
        self.assertIn("t1", payload["leases"])

    def test_release_survives_db_failure(self) -> None:
        """释放租约的镜像写失败同样不得冒泡——状态文件已清即达目的。"""
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(Path(tmp))
            lease = LeaseManager(db, "runner-a")
            lease.acquire("t1", revision=1)

            def boom():
                raise sqlite3.OperationalError("database is locked")

            lease._mirror_release = boom  # type: ignore[method-assign]
            with self.assertLogs("app.upgrade_runner.lease", level="WARNING"):
                lease.release("t1")  # 冒泡即为缺陷
            payload = json.loads(state_file_path(db).read_text(encoding="utf-8"))
        self.assertNotIn("t1", payload["leases"])


class PresenceFileFirstTests(unittest.TestCase):
    """web-api 侧：presence 文件优先、DB 兜底（M5 = v0.5.4 + v0.3.1 必须行为一致）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.db = _make_db(self.tmp)
        self.database = _FakeDatabase(self.db)
        self.settings = _Settings(self.db)
        self.state = state_file_path(self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_state_file(self, payload: dict) -> dict:
        """写状态文件并**回读**（回读才是 web-api 侧真正看到的内容）。"""
        self.state.write_text(json.dumps(payload), encoding="utf-8")
        return read_state_file(self.settings)

    def _seed_db_lease(self, task_id: str, owner: str, expires_in: float, heartbeat_in: float) -> None:
        # 必须显式关闭：`with sqlite3.connect(...)` 只提交事务、**不关连接**（US-28 的坑）。
        # 测试里复现同一个错误会让后续用例撞 `database is locked`，掩盖真实失败原因。
        with _rows(self.db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO upgrade_task_leases VALUES (?, ?, ?, ?, ?)",
                (task_id, owner, _iso(expires_in), _iso(heartbeat_in), 1),
            )

    def _seed_db_state(
        self, instance_id: str, runner_version: str, heartbeat_in: float
    ) -> None:
        with _rows(self.db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO upgrade_runner_state VALUES (1, ?, ?, 1, '[]', ?, ?)",
                (instance_id, runner_version, _iso(heartbeat_in), _iso(heartbeat_in)),
            )

    def test_state_file_path_matches_runner_derivation(self) -> None:
        """两侧各算各的必然漂移（US-26 同源），必须断言结果相同。"""
        self.assertEqual(web_state_file_path(self.settings), state_file_path(self.db))

    def test_m5_no_state_file_falls_back_to_db(self) -> None:
        """v0.5.4 + v0.3.1：文件缺失必须干净回落 DB，不能当成「不在场」。"""
        self.assertFalse(self.state.exists())
        self._seed_db_state("runner-old", "v0.3.1", -1)
        self._seed_db_lease("t1", "runner-old", 20, 0)
        db_state = {"instance_id": "runner-old", "runner_version": "v0.3.1", "heartbeat_at": _iso(-1)}
        self.assertEqual(presence_source(self.database, db_state), HEARTBEAT_SOURCE)
        self.assertTrue(task_lease_is_alive(self.database, "t1"))
        self.assertTrue(active_task_lease_is_fresh(self.database))

    def test_state_file_heartbeat_wins_over_db(self) -> None:
        state_file = self._write_state_file(
            {"schema": 1, "instance_id": "runner-new", "runner_version": "v0.3.2", "heartbeat_at": _iso(-1), "leases": {}}
        )
        db_state = {"instance_id": "runner-old", "runner_version": "v0.3.1", "heartbeat_at": _iso(-1)}
        self.assertEqual(presence_source(self.database, db_state, state_file=state_file), HEARTBEAT_SOURCE)
        # 实例字段应取自给出证据的文件通道，而不是 DB 里那个陈旧 runner
        self.assertEqual(state_file_instance_state(state_file)["runner_version"], "v0.3.2")

    def test_frozen_instance_heartbeat_still_detected_via_file_lease(self) -> None:
        """US-08 的原始场景在文件通道上必须同样成立：实例心跳冻结、租约有效 → 仍在场。"""
        state_file = self._write_state_file(
            {
                "schema": 1,
                "instance_id": "runner-new",
                "runner_version": "v0.3.2",
                "heartbeat_at": _iso(-90),  # 执行期冻结
                "leases": {"t1": {"lease_owner": "runner-new", "lease_expires_at": _iso(20), "heartbeat_at": _iso(0)}},
            },
        )
        self.assertEqual(presence_source(self.database, None, state_file=state_file), TASK_LEASE_SOURCE)
        self.assertTrue(task_lease_is_alive(self.database, "t1", state_file=state_file))

    def test_expired_file_lease_and_no_heartbeat_means_absent(self) -> None:
        state_file = self._write_state_file(
            {
                "schema": 1,
                "heartbeat_at": _iso(-90),
                "leases": {"t1": {"lease_owner": "x", "lease_expires_at": _iso(-60), "heartbeat_at": _iso(-60)}},
            }
        )
        self.assertFalse(file_task_lease_is_fresh(state_file))
        self.assertIsNone(presence_source(self.database, None, state_file=state_file))

    def test_corrupt_state_file_reads_as_none_not_exception(self) -> None:
        """坏文件不能让升级中心整体 500——必须按「没有文件」处理并回落 DB。"""
        self.state.write_text("{ broken", encoding="utf-8")
        self.assertIsNone(read_state_file(self.settings))
        self._seed_db_lease("t1", "runner-old", 20, 0)
        self.assertTrue(task_lease_is_alive(self.database, "t1", state_file=read_state_file(self.settings)))

    def test_non_object_state_file_reads_as_none(self) -> None:
        self.state.write_text("[1,2,3]", encoding="utf-8")
        self.assertIsNone(read_state_file(self.settings))

    def test_state_file_with_bad_lease_type_is_tolerated(self) -> None:
        state_file = self._write_state_file({"schema": 1, "heartbeat_at": _iso(-90), "leases": ["oops"]})
        self.assertFalse(file_task_lease_is_fresh(state_file))

    def test_file_lease_wins_over_stale_db_row(self) -> None:
        """文件说租约有效、DB 镜像行已过期 → 必须判为在场（事实源是文件）。"""
        state_file = self._write_state_file(
            {
                "schema": 1,
                "heartbeat_at": _iso(-90),
                "leases": {"t1": {"lease_owner": "runner-new", "lease_expires_at": _iso(15), "heartbeat_at": _iso(0)}},
            }
        )
        self._seed_db_lease("t1", "runner-new", -120, -120)
        self.assertTrue(task_lease_is_alive(self.database, "t1", state_file=state_file))
        self.assertEqual(presence_source(self.database, None, state_file=state_file), TASK_LEASE_SOURCE)

    def test_no_file_no_db_state_means_absent(self) -> None:
        self.assertIsNone(presence_source(self.database, None))
        self.assertFalse(active_task_lease_is_fresh(self.database))
        self.assertFalse(task_lease_is_alive(self.database, "t1"))


class StateFileMatchesRunnerClockTests(unittest.TestCase):
    """状态文件与 web-api 读的是同一个心跳时间，且判定一致。"""

    def test_same_heartbeat_value_yields_same_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(Path(tmp))
            store = RunnerStateStore(db, "runner-a", "v0.3.2", 1, [])
            store.heartbeat()
            payload = read_state_file(_Settings(db))
        self.assertIsNotNone(payload)
        self.assertTrue(instance_heartbeat_is_fresh(state_file_instance_state(payload)))

    def test_utc_iso_roundtrip_without_timezone_shift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(Path(tmp))
            store = RunnerStateStore(db, "runner-a", "v0.3.2", 1, [])
            store.heartbeat()
            raw = json.loads(state_file_path(db).read_text(encoding="utf-8"))["heartbeat_at"]
        self.assertTrue(raw.endswith("+00:00"), f"心跳必须写 UTC ISO：{raw}")
        parsed = parse_timestamp(raw)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.utcoffset(), timedelta(0))


if __name__ == "__main__":
    unittest.main()
