from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "capture_baseline.py"


class CaptureBaselineTest(unittest.TestCase):
    def _make_source(self, tmpdir: Path) -> tuple[Path, Path]:
        db = tmpdir / "smartx.db"
        conn = sqlite3.connect(db)
        conn.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT);
            CREATE TABLE towers (id INTEGER PRIMARY KEY, enabled INTEGER);
            CREATE TABLE clusters (id INTEGER PRIMARY KEY);
            CREATE TABLE vm_latest (id INTEGER PRIMARY KEY);
            CREATE TABLE vm_volumes (id INTEGER PRIMARY KEY);
            CREATE TABLE collection_runs (id INTEGER PRIMARY KEY);
            INSERT INTO users VALUES (1, 'admin');
            INSERT INTO towers VALUES (1, 1);
            INSERT INTO clusters VALUES (1);
            INSERT INTO vm_latest VALUES (1);
            INSERT INTO vm_volumes VALUES (1);
            INSERT INTO collection_runs VALUES (1);
            """
        )
        conn.commit()
        conn.close()
        env = tmpdir / "project.env"
        env.write_text("SMARTX_SECRET_KEY=baseline-secret\n", encoding="utf-8")
        return db, env

    def test_capture_and_verify_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            db, env = self._make_source(tmpdir)
            output = tmpdir / "baselines"
            capture = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "capture",
                    "--name",
                    "b1",
                    "--db",
                    str(db),
                    "--env",
                    str(env),
                    "--output",
                    str(output),
                    "--skip-prometheus",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(capture.returncode, 0, capture.stderr)
            baseline = output / "b1"
            self.assertTrue((baseline / "smartx.db").is_file())
            self.assertTrue((baseline / "tower.env").is_file())
            self.assertTrue((baseline / "SHA256SUMS").is_file())
            manifest = json.loads((baseline / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["db_counts"]["users"], 1)
            self.assertEqual(manifest["db_integrity"], "ok")

            verify = subprocess.run(
                [sys.executable, str(SCRIPT), "verify", "--dir", str(baseline)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(verify.returncode, 0, verify.stderr)
            self.assertIn("baseline ok", verify.stdout)

    def test_verify_detects_tampered_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            db, env = self._make_source(tmpdir)
            output = tmpdir / "baselines"
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "capture",
                    "--name",
                    "b2",
                    "--db",
                    str(db),
                    "--env",
                    str(env),
                    "--output",
                    str(output),
                    "--skip-prometheus",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            baseline = output / "b2"
            conn = sqlite3.connect(baseline / "smartx.db")
            conn.execute("INSERT INTO users VALUES (2, 'intruder')")
            conn.commit()
            conn.close()
            # SHA 未更新，verify 必须失败
            verify = subprocess.run(
                [sys.executable, str(SCRIPT), "verify", "--dir", str(baseline)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(verify.returncode, 0)


if __name__ == "__main__":
    unittest.main()
