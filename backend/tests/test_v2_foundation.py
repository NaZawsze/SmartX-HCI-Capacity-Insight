import os
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


if __name__ == "__main__":
    unittest.main()
