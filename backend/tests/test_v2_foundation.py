import os
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


class V2FoundationTest(unittest.TestCase):
    def test_version_file_has_priority_over_environment(self) -> None:
        from app.v2.config import read_version

        with tempfile.TemporaryDirectory() as tmpdir:
            version_file = Path(tmpdir) / "VERSION"
            version_file.write_text("v2.0.0\n", encoding="utf-8")
            os.environ["SMARTX_APP_VERSION"] = "v0.0.0-env"
            try:
                self.assertEqual(read_version(version_file, "SMARTX_APP_VERSION", "v0-default"), "v2.0.0")
            finally:
                os.environ.pop("SMARTX_APP_VERSION", None)

    def test_version_uses_environment_when_version_file_is_missing(self) -> None:
        from app.v2.config import read_version

        with tempfile.TemporaryDirectory() as tmpdir:
            missing_version_file = Path(tmpdir) / "VERSION"
            os.environ["SMARTX_APP_VERSION"] = "v9.9.9-test"
            try:
                self.assertEqual(read_version(missing_version_file, "SMARTX_APP_VERSION", "v0-default"), "v9.9.9-test")
            finally:
                os.environ.pop("SMARTX_APP_VERSION", None)

    def test_settings_define_required_runtime_directories(self) -> None:
        from app.v2.config import V2Settings

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir))
            self.assertEqual(settings.sqlite_dir, Path(tmpdir) / "smartx-capacity-insight-data" / "app")
            self.assertEqual(settings.prometheus_data_dir, Path(tmpdir) / "smartx-capacity-insight-data" / "prometheus")
            self.assertIn(Path(tmpdir) / "exports" / "reports", settings.required_directories())
            self.assertIn(Path(tmpdir) / "compose-runtime", settings.required_directories())

    def test_settings_from_environment_reads_current_environment(self) -> None:
        from app.v2.config import settings_from_environment

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_SECRET_KEY"] = "current-secret"
            os.environ["SMARTX_APP_VERSION"] = "v9.9.9-test"
            try:
                settings = settings_from_environment()
                self.assertEqual(settings.data_root, Path(tmpdir))
                self.assertEqual(settings.secret_key, "current-secret")
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_SECRET_KEY", None)
                os.environ.pop("SMARTX_APP_VERSION", None)

    def test_settings_ignore_default_compose_db_path_when_data_root_is_overridden(self) -> None:
        from app.v2.config import settings_from_environment

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_DB_PATH"] = "/data/smartx.db"
            try:
                settings = settings_from_environment()
                self.assertEqual(settings.sqlite_path, Path(tmpdir) / "smartx-capacity-insight-data" / "app" / "smartx.db")
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_DB_PATH", None)

    def test_settings_respect_compose_mounted_data_paths(self) -> None:
        from app.v2.config import settings_from_environment

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "smartx.db"
            prometheus_path = Path(tmpdir) / "prometheus-data"
            os.environ["SMARTX_DATA_ROOT"] = "/data"
            os.environ["SMARTX_DB_PATH"] = str(db_path)
            os.environ["SMARTX_PROMETHEUS_DATA_PATH"] = str(prometheus_path)
            try:
                settings = settings_from_environment()
                self.assertEqual(settings.sqlite_path, db_path)
                self.assertEqual(settings.sqlite_dir, db_path.parent)
                self.assertEqual(settings.prometheus_data_dir, prometheus_path)
                self.assertIn(db_path.parent, settings.required_directories())
                self.assertIn(prometheus_path, settings.required_directories())
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_DB_PATH", None)
                os.environ.pop("SMARTX_PROMETHEUS_DATA_PATH", None)

    def test_database_initializes_default_admin_and_auth_flow(self) -> None:
        from app.v2.auth.service import AuthService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="unit-secret", admin_password="password")
            db = V2Database(settings)
            db.initialize()
            auth = AuthService(db, settings)

            login = auth.login("admin", "password")
            self.assertEqual(login.username, "admin")
            self.assertEqual(login.token_type, "bearer")
            self.assertTrue(login.access_token)
            self.assertEqual(auth.current_user(login.access_token).username, "admin")

            self.assertFalse(auth.change_password("admin", "wrong", "new-password"))
            self.assertTrue(auth.change_password("admin", "password", "new-password"))
            self.assertIsNone(auth.login("admin", "password"))
            self.assertEqual(auth.login("admin", "new-password").username, "admin")

    def test_database_adds_users_updated_at_for_existing_schema(self) -> None:
        from app.v2.auth.service import AuthService
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.security import hash_password

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="schema-secret", admin_password="password")
            db = V2Database(settings)
            settings.sqlite_dir.mkdir(parents=True, exist_ok=True)
            with db.connection() as conn:
                conn.execute(
                    """
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        is_admin INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
                    ("admin", hash_password("password")),
                )

            db.initialize()
            with db.connection() as conn:
                columns = [row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
            self.assertIn("updated_at", columns)

            auth = AuthService(db, settings)
            self.assertTrue(auth.change_password("admin", "password", "new-password"))

    def test_database_initialization_backfills_v1_latest_vm_payloads(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="compat-secret")
            settings.sqlite_dir.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(settings.sqlite_path) as conn:
                conn.executescript(
                    """
                    CREATE TABLE towers (
                        id INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        base_url TEXT NOT NULL,
                        username TEXT,
                        password_encrypted TEXT,
                        api_token_encrypted TEXT,
                        verify_tls INTEGER NOT NULL DEFAULT 1,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT,
                        updated_at TEXT
                    );
                    CREATE TABLE clusters (
                        id INTEGER PRIMARY KEY,
                        tower_id INTEGER NOT NULL,
                        cluster_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        updated_at TEXT
                    );
                    CREATE TABLE latest_vm_volumes (
                        tower_id INTEGER NOT NULL,
                        cluster_id TEXT NOT NULL,
                        vm_id TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        collected_at TEXT,
                        PRIMARY KEY (tower_id, cluster_id, vm_id)
                    );
                    """
                )
                conn.execute("INSERT INTO towers (id, name, base_url) VALUES (3, 'Tower A', 'https://tower.example.com')")
                conn.execute("INSERT INTO clusters (tower_id, cluster_id, name) VALUES (3, 'cluster-a', 'Cluster A')")
                conn.execute(
                    "INSERT INTO latest_vm_volumes (tower_id, cluster_id, vm_id, payload_json, collected_at) VALUES (3, 'cluster-a', 'vm-1', ?, '2026-06-01T00:00:00Z')",
                    (
                        json.dumps(
                            [
                                {
                                    "id": "vol-1",
                                    "name": "Root",
                                    "path": "/root",
                                    "size": 1000,
                                    "used_size": 450,
                                    "elf_storage_policy": "Replica-2",
                                    "elf_storage_policy_replica_num": 2,
                                    "elf_storage_policy_thin_provision": True,
                                    "cluster": {"raw": "discard"},
                                }
                            ]
                        ),
                    ),
                )

            V2Database(settings).initialize()

            with sqlite3.connect(settings.sqlite_path) as conn:
                latest = conn.execute("SELECT tower_id, cluster_id, vm_id, name, used_bytes FROM vm_latest").fetchone()
                volume = conn.execute("SELECT volume_id, name, path, size_bytes, used_bytes, storage_policy, replica_num, thin_provision FROM vm_volumes").fetchone()
            self.assertEqual(latest, (3, "cluster-a", "vm-1", "vm-1", 450))
            self.assertEqual(volume, ("vol-1", "Root", "/root", 1000, 450, "Replica-2", 2, 1))

    def test_health_check_reports_database_and_directories(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.metrics.prometheus import PrometheusHealth
        from app.v2.system.health import check_health

        class ReadyPrometheus:
            def health(self):
                return PrometheusHealth(ok=True, message="ready")

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="unit-secret")
            db = V2Database(settings)
            db.initialize()
            result = check_health(settings, db, prometheus=ReadyPrometheus())

            self.assertTrue(result.ok)
            self.assertTrue(result.checks["database"])
            self.assertTrue(result.checks["directories"])
            self.assertTrue(result.checks["prometheus"])
            self.assertEqual(result.version, settings.app_version)

    def test_health_check_reports_required_directory_writeability(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.metrics.prometheus import PrometheusHealth
        from app.v2.system.health import check_health

        class ReadyPrometheus:
            def health(self):
                return PrometheusHealth(ok=True, message="ready")

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="unit-secret")
            db = V2Database(settings)
            db.initialize()
            blocked = settings.prometheus_data_dir
            blocked.mkdir(parents=True, exist_ok=True)
            marker = blocked / ".smartx-healthcheck"
            marker.mkdir()

            result = check_health(settings, db, prometheus=ReadyPrometheus())

            self.assertFalse(result.ok)
            self.assertFalse(result.checks["directories"])


if __name__ == "__main__":
    unittest.main()
