"""数据完整性快照/比对脚本（scripts/verify_data_integrity.py）的判定逻辑。

为什么要有它：升级验证最容易走过场的就是"数据看起来还在"。规范
（docs/test-process-and-scope.md §4）要求逐表指纹 + 可增长表"旧行不变" + 引用完整性 +
`.env` 密钥配对，这里用最小数据库把这些判定钉死，防止脚本自己写错。
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module():
    spec = importlib.util.spec_from_file_location(
        "verify_data_integrity", ROOT / "scripts" / "verify_data_integrity.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


SCHEMA = """
CREATE TABLE towers (id TEXT PRIMARY KEY, name TEXT, url TEXT, username TEXT,
                     password_encrypted TEXT, api_token_encrypted TEXT);
CREATE TABLE clusters (tower_id TEXT, cluster_id TEXT PRIMARY KEY, name TEXT);
CREATE TABLE vm_latest (tower_id TEXT, cluster_id TEXT, vm_id TEXT PRIMARY KEY, name TEXT, used_bytes INTEGER);
CREATE TABLE vm_volumes (tower_id TEXT, cluster_id TEXT, vm_id TEXT, volume_id TEXT PRIMARY KEY, name TEXT, used_bytes INTEGER);
CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT);
CREATE TABLE tasks (id TEXT PRIMARY KEY, type TEXT, status TEXT, created_at TEXT);
CREATE TABLE collection_runs (id INTEGER PRIMARY KEY, status TEXT, started_at TEXT);
CREATE TABLE metric_snapshots (id INTEGER PRIMARY KEY, tower_id TEXT, collected_at TEXT);
CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT);
CREATE TABLE upgrade_runner_state (id INTEGER PRIMARY KEY, heartbeat_at TEXT);
CREATE TABLE upgrade_task_leases (task_id TEXT PRIMARY KEY, heartbeat_at TEXT);
"""

SEED = """
INSERT INTO towers VALUES ('t1', '塔一', 'https://tower', 'admin', 'enc-pass', 'enc-token');
INSERT INTO clusters VALUES ('t1', 'c1', '集群一');
INSERT INTO vm_latest VALUES ('t1', 'c1', 'vm1', '虚拟机-甲', 100);
INSERT INTO vm_latest VALUES ('t1', 'c1', 'vm2', 'vm-乙', 200);
INSERT INTO vm_volumes VALUES ('t1', 'c1', 'vm1', 'v1', '卷-1', 100);
INSERT INTO users VALUES (1, 'admin', 'hash-1');
INSERT INTO tasks VALUES ('upgrade-1', 'upgrade', 'succeeded', '2026-10-17T00:00:00');
INSERT INTO collection_runs VALUES (1, 'success', '2026-10-17T00:00:00');
INSERT INTO metric_snapshots VALUES (1, 't1', '2026-10-17T00:00:00');
INSERT INTO schema_migrations VALUES ('001', '2026-10-01');
INSERT INTO upgrade_runner_state VALUES (1, '2026-10-17T00:00:00');
INSERT INTO upgrade_task_leases VALUES ('upgrade-1', '2026-10-17T00:00:00');
"""


class DataIntegrityScriptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "smartx.db"
        conn = sqlite3.connect(self.db)
        conn.executescript(SCHEMA)
        conn.executescript(SEED)
        conn.commit()
        conn.close()
        self.env = self.root / ".env"
        self.env.write_text(
            "SMARTX_SECRET_KEY=" + "a" * 40 + "\n"
            "SMARTX_CREDENTIAL_KEY=" + "b" * 40 + "\n"
            "SMARTX_ADMIN_USER=admin\n",
            encoding="utf-8",
        )
        self.compose = self.root / "docker-compose.offline.yml"
        self.compose.write_text("services: {}\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _snapshot(self, name: str) -> Path:
        out = self.root / f"{name}.json"
        with contextlib.redirect_stdout(io.StringIO()):
            code = self.module.main(
                [
                    "snapshot",
                    "--db", str(self.db),
                    "--env", str(self.env),
                    "--compose", str(self.compose),
                    "--label", name,
                    "--out", str(out),
                ]
            )
        self.assertEqual(code, 0)
        return out

    def _compare(self, before: Path, after: Path) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = self.module.main(["compare", "--before", str(before), "--after", str(after)])
        return code, buffer.getvalue()

    def _assert_fail(self, output: str, check: str) -> None:
        self.assertRegex(output, rf"FAIL\s+{re.escape(check)}")

    def test_unchanged_data_passes(self) -> None:
        before = self._snapshot("t0")
        after = self._snapshot("t1")
        code, output = self._compare(before, after)
        self.assertEqual(code, 0, output)
        self.assertIn("table.vm_latest", output)
        # 没有提供 Prometheus → 必须是 WARN，不能静默 PASS
        self.assertIn("WARN", output)

    def test_business_row_change_fails(self) -> None:
        before = self._snapshot("t0")
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE vm_latest SET name='被改名' WHERE vm_id='vm1'")
        conn.commit()
        conn.close()
        after = self._snapshot("t1")
        code, output = self._compare(before, after)
        self.assertEqual(code, 1, output)
        self._assert_fail(output, "table.vm_latest")

    def test_credential_wipe_fails(self) -> None:
        """凭据列被清空必须被抓到（只比 name/url 是测不出来的）。"""
        before = self._snapshot("t0")
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE towers SET password_encrypted='' WHERE id='t1'")
        conn.commit()
        conn.close()
        after = self._snapshot("t1")
        code, output = self._compare(before, after)
        self.assertEqual(code, 1, output)
        self._assert_fail(output, "table.towers")

    def test_growth_is_allowed_but_old_rows_must_hold(self) -> None:
        before = self._snapshot("t0")
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO tasks VALUES ('upgrade-2', 'upgrade', 'running', '2026-10-17T01:00:00')")
        conn.execute("INSERT INTO schema_migrations VALUES ('002', '2026-10-17')")
        conn.execute("INSERT INTO collection_runs VALUES (2, 'success', '2026-10-17T01:00:00')")
        conn.commit()
        conn.close()
        after = self._snapshot("t1")
        code, output = self._compare(before, after)
        self.assertEqual(code, 0, output)
        self.assertIn("table.tasks", output)

    def test_old_growable_row_change_fails(self) -> None:
        """新增行允许，但升级前已有的行被改必须 FAIL（id 集合指纹）。

        注意稳定列口径：`tasks.status` 不在稳定列里（升级中 running→succeeded 是正常
        业务语义，2026-10-17 修正），所以这里改 `type` 这种稳定列才算"内容被改"。
        """
        before = self._snapshot("t0")
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO tasks VALUES ('upgrade-2', 'upgrade', 'running', '2026-10-17T01:00:00')")
        conn.execute("UPDATE tasks SET type='collection' WHERE id='upgrade-1'")
        conn.commit()
        conn.close()
        after = self._snapshot("t1")
        code, output = self._compare(before, after)
        self.assertEqual(code, 1, output)
        self._assert_fail(output, "table.tasks")

    def test_env_key_removal_fails(self) -> None:
        before = self._snapshot("t0")
        self.env.write_text("SMARTX_ADMIN_USER=admin\n", encoding="utf-8")
        after = self._snapshot("t1")
        code, output = self._compare(before, after)
        self.assertEqual(code, 1, output)
        self._assert_fail(output, "env.keys")
        self._assert_fail(output, "env.secret_pair")

    def test_env_reordering_is_not_a_change(self) -> None:
        before = self._snapshot("t0")
        lines = self.env.read_text(encoding="utf-8").splitlines()
        self.env.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")
        after = self._snapshot("t1")
        code, output = self._compare(before, after)
        self.assertEqual(code, 0, output)

    def test_orphan_rows_fail(self) -> None:
        before = self._snapshot("t0")
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO vm_volumes VALUES ('t1', 'c1', 'vm-missing', 'v9', '孤儿卷', 1)")
        conn.commit()
        conn.close()
        after = self._snapshot("t1")
        code, output = self._compare(before, after)
        self.assertEqual(code, 1, output)
        self._assert_fail(output, "refs.vm_volumes.vm_id->vm_latest.vm_id")

    def test_new_row_with_smaller_id_is_not_mistaken_for_old_row_change(self) -> None:
        """新行 id 字典序小于 T0 max_pk 时，不得误报"旧行指纹变化"。

        2026-10-17 P3 实测：升级产生的新任务 id（`upgrade-5b25…`）字典序小于 T0 的
        `max_pk`（`upgrade-fdb5…`），边界法把它算进旧行 → 假 FAIL；按 id 集合界定后通过。
        """
        before = self._snapshot("t0")
        conn = sqlite3.connect(self.db)
        # 新行 id 刻意取字典序更小的值（模拟 upgrade-5b25… < upgrade-fdb5…）
        conn.execute(
            "INSERT INTO tasks VALUES ('upgrade-0new', 'upgrade', 'succeeded', '2026-10-17T01:00:00')"
        )
        conn.commit()
        conn.close()
        after = self._snapshot("t1")
        code, output = self._compare(before, after)
        self.assertEqual(code, 0, output)
        self.assertIn("PASS  table.tasks", output)

    def test_old_row_change_still_fails_with_id_set(self) -> None:
        """同一把尺子的另一面：T0 集合里的旧行真被改，必须 FAIL。"""
        before = self._snapshot("t0")
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE tasks SET created_at='2026-10-18T00:00:00' WHERE id='upgrade-1'")
        conn.commit()
        conn.close()
        after = self._snapshot("t1")
        code, output = self._compare(before, after)
        self.assertEqual(code, 1, output)
        self._assert_fail(output, "table.tasks")


if __name__ == "__main__":
    unittest.main()
