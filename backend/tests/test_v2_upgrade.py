import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path


try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local host may not have web deps.
    TestClient = None


def build_package(manifest: dict, files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        manifest_bytes = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_bytes)
        archive.addfile(info, io.BytesIO(manifest_bytes))
        for name, content in files.items():
            item = tarfile.TarInfo(name)
            item.size = len(content)
            archive.addfile(item, io.BytesIO(content))
    return buffer.getvalue()


class V2UpgradeServiceTest(unittest.TestCase):
    def _package(self, manifest: dict, files: dict[str, bytes]) -> bytes:
        return build_package(manifest, files)

    def test_upload_parses_components_and_precheck_validates_archives_sha_and_project_files(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeService

        web_api = b"web-api-image"
        runner = b"runner-image"
        manifest = {
            "schema_version": "2",
            "package_id": "pkg-v2",
            "version": "v2.0.0",
            "project_files": True,
            "components": [
                {"type": "platform", "services": ["web-api"], "images": [{"service": "web-api", "image": "repo/web-api:v2.0.0", "archive": "images/web-api.tar", "sha256": hashlib.sha256(web_api).hexdigest()}]},
                {"type": "runner", "services": ["upgrade-runner"], "images": [{"service": "upgrade-runner", "image": "repo/upgrade-runner:v0.3.0", "archive": "images/upgrade-runner.tar", "sha256": hashlib.sha256(runner).hexdigest()}]},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="upgrade-secret")
            database = V2Database(settings)
            database.initialize()
            service = UpgradeService(settings, TaskService(database))
            task = service.upload_package_bytes(
                self._package(
                    manifest,
                    {
                        "images/web-api.tar": web_api,
                        "images/upgrade-runner.tar": runner,
                        "project/docker-compose.offline.yml": b"services: {}",
                    },
                ),
                filename="upgrade.tar.gz",
            )

            self.assertEqual(task["target_version"], "v2.0.0")
            self.assertEqual(task["components"], ["platform", "runner"])
            self.assertTrue(Path(task["package_path"]).is_dir())

            precheck = service.precheck(task["task_id"])
            self.assertTrue(precheck["ok"])
            self.assertEqual([check["name"] for check in precheck["checks"]], ["manifest", "paths", "images", "project_files"])
            self.assertTrue(all(check["ok"] for check in precheck["checks"]))

            started = service.start(task["task_id"])
            self.assertEqual(started["status"], "backup_completed")
            self.assertTrue(Path(started["backup_path"]).is_file())
            self.assertIn("upgrade-v2.0.0-before", Path(started["backup_path"]).name)
            with tarfile.open(started["backup_path"], mode="r:gz") as backup:
                backup_names = set(backup.getnames())
            self.assertIn("manifest.json", backup_names)
            self.assertIn("app/smartx.db", backup_names)

    def test_upload_rejects_sensitive_paths(self) -> None:
        from fastapi import HTTPException

        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeService

        manifest = {"schema_version": "2", "version": "v2.0.0", "components": []}
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="upgrade-secret")
            database = V2Database(settings)
            database.initialize()
            service = UpgradeService(settings, TaskService(database))
            with self.assertRaises(HTTPException):
                service.upload_package_bytes(self._package(manifest, {".env": b"secret"}), filename="bad.tar.gz")


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed.")
class V2UpgradeApiTest(unittest.TestCase):
    def test_upgrade_api_requires_auth_uploads_and_prechecks_package(self) -> None:
        import os

        from app.v2.main import create_app

        image = b"web-api-image"
        manifest = {
            "schema_version": "2",
            "version": "v2.0.0",
            "components": [
                {"type": "platform", "services": ["web-api"], "images": [{"service": "web-api", "image": "repo/web-api:v2.0.0", "archive": "images/web-api.tar", "sha256": hashlib.sha256(image).hexdigest()}]},
            ],
        }
        package = build_package(manifest, {"images/web-api.tar": image})
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_SECRET_KEY"] = "upgrade-api-secret"
            os.environ["SMARTX_ADMIN_PASSWORD"] = "password"
            try:
                app = create_app()
                with TestClient(app) as client:
                    self.assertEqual(client.post("/api/admin/upgrade/upload").status_code, 401)
                    token = client.post("/api/auth/login", json={"username": "admin", "password": "password"}).json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}
                    uploaded = client.post("/api/admin/upgrade/upload", files={"file": ("upgrade.tar.gz", package, "application/gzip")}, headers=headers)
                    self.assertEqual(uploaded.status_code, 200)
                    payload = uploaded.json()
                    self.assertEqual(payload["target_version"], "v2.0.0")
                    self.assertEqual(payload["components"], ["platform"])

                    precheck = client.post(f"/api/admin/upgrade/precheck/{payload['task_id']}", headers=headers)
                    self.assertEqual(precheck.status_code, 200)
                    self.assertTrue(precheck.json()["ok"])

                    started = client.post(f"/api/admin/upgrade/start/{payload['task_id']}", headers=headers)
                    self.assertEqual(started.status_code, 200)
                    self.assertTrue(Path(started.json()["backup_path"]).is_file())
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_SECRET_KEY", None)
                os.environ.pop("SMARTX_ADMIN_PASSWORD", None)


if __name__ == "__main__":
    unittest.main()
