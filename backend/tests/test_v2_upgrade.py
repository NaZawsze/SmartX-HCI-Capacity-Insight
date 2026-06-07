from __future__ import annotations

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
        from app.v2.upgrade.service import UpgradeCommandExecutor, UpgradeService

        class FakeExecutor(UpgradeCommandExecutor):
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def run(self, command: list[str], *, cwd: Path | None = None) -> None:
                self.commands.append(command)

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
            settings = V2Settings(data_root=Path(tmpdir), secret_key="upgrade-secret", compose_project_name="custom-project")
            database = V2Database(settings)
            database.initialize()
            executor = FakeExecutor()
            service = UpgradeService(settings, TaskService(database), executor=executor, project_path=Path(tmpdir) / "project")
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
            self.assertTrue(Path(started["backup_path"]).is_file())
            self.assertIn("upgrade-v2.0.0-before", Path(started["backup_path"]).name)
            with tarfile.open(started["backup_path"], mode="r:gz") as backup:
                backup_names = set(backup.getnames())
            self.assertIn("manifest.json", backup_names)
            self.assertIn("app/smartx.db", backup_names)
            self.assertEqual(started["status"], "succeeded")
            self.assertTrue((settings.compose_runtime_dir / "docker-compose.upgrade.yml").is_file())
            self.assertIn("repo/web-api:v2.0.0", (settings.compose_runtime_dir / "docker-compose.upgrade.yml").read_text(encoding="utf-8"))
            self.assertTrue((Path(tmpdir) / "project" / "docker-compose.offline.yml").is_file())
            self.assertTrue(any(command[:2] == ["docker", "load"] for command in executor.commands))
            self.assertTrue(any(command[:3] == ["docker", "compose", "-f"] for command in executor.commands))
            compose_commands = [command for command in executor.commands if command[:3] == ["docker", "compose", "-f"]]
            self.assertIn("custom-project", compose_commands[-1])
            stored_task = TaskService(database).get_task(task["task_id"])
            self.assertEqual(stored_task["status"], "success")
            self.assertTrue(stored_task["steps"])

    def test_rollback_restores_project_files_and_removes_runtime_override(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeCommandExecutor, UpgradeService

        class FakeExecutor(UpgradeCommandExecutor):
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def run(self, command: list[str], *, cwd: Path | None = None) -> None:
                self.commands.append(command)

        image = b"web-api-image"
        manifest = {
            "schema_version": "2",
            "version": "v2.0.1",
            "project_files": True,
            "components": [
                {"type": "platform", "services": ["web-api"], "images": [{"service": "web-api", "image": "repo/web-api:v2.0.1", "archive": "images/web-api.tar", "sha256": hashlib.sha256(image).hexdigest()}]},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="upgrade-secret")
            database = V2Database(settings)
            database.initialize()
            project_path = Path(tmpdir) / "project"
            project_path.mkdir()
            (project_path / "docker-compose.offline.yml").write_text("old-compose\n", encoding="utf-8")
            service = UpgradeService(settings, TaskService(database), executor=FakeExecutor(), project_path=project_path)
            task = service.upload_package_bytes(
                self._package(manifest, {"images/web-api.tar": image, "project/docker-compose.offline.yml": b"new-compose\n"}),
                filename="upgrade.tar.gz",
            )
            self.assertTrue(service.precheck(task["task_id"])["ok"])
            started = service.start(task["task_id"])
            self.assertEqual((project_path / "docker-compose.offline.yml").read_text(encoding="utf-8"), "new-compose\n")
            self.assertTrue(Path(started["override_path"]).exists())

            rolled_back = service.rollback(task["task_id"])
            self.assertEqual(rolled_back["status"], "rolled_back")
            self.assertEqual((project_path / "docker-compose.offline.yml").read_text(encoding="utf-8"), "old-compose\n")
            self.assertFalse(Path(started["override_path"]).exists())
            self.assertTrue(any(command[-1:] == ["web-api"] for command in service.executor.commands if command[:3] == ["docker", "compose", "-f"]))

    def test_cancel_pending_upgrade_prevents_runner_execution_and_marks_task_cancelled(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.runner import run_pending_once
        from app.v2.upgrade.service import UpgradeCommandExecutor, UpgradeService

        class FakeExecutor(UpgradeCommandExecutor):
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def run(self, command: list[str], *, cwd: Path | None = None) -> None:
                self.commands.append(command)

        image = b"web-api-image"
        manifest = {
            "schema_version": "2",
            "version": "v2.0.2",
            "components": [
                {
                    "type": "platform",
                    "services": ["web-api"],
                    "images": [{"service": "web-api", "image": "repo/web-api:v2.0.2", "archive": "images/web-api.tar", "sha256": hashlib.sha256(image).hexdigest()}],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="upgrade-secret")
            database = V2Database(settings)
            database.initialize()
            task_service = TaskService(database)
            executor = FakeExecutor()
            service = UpgradeService(settings, task_service, executor=executor, project_path=Path(tmpdir) / "project")
            task = service.upload_package_bytes(self._package(manifest, {"images/web-api.tar": image}), filename="upgrade.tar.gz")
            self.assertTrue(service.precheck(task["task_id"])["ok"])
            started = service.start(task["task_id"], submit_to_runner=True)
            self.assertEqual(started["status"], "pending")

            cancelled = service.cancel(task["task_id"])
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertFalse(cancelled.get("runner_requested", False))
            stored_task = task_service.get_task(task["task_id"])
            self.assertEqual(stored_task["status"], "cancelled")
            self.assertEqual(stored_task["progress"], 100)

            executed = run_pending_once(settings, task_service, executor=executor, project_path=Path(tmpdir) / "project")
            self.assertEqual(executed, 0)
            self.assertEqual(executor.commands, [])

    def test_cancel_orphaned_pending_upgrade_task_marks_task_cancelled(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.models import TaskStatus, TaskType
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="upgrade-secret")
            database = V2Database(settings)
            database.initialize()
            task_service = TaskService(database)
            task_service.create_task("upgrade-orphan", TaskType.UPGRADE, "执行系统升级", status=TaskStatus.PENDING, progress=1, message="升级任务已提交，等待 upgrade-runner 执行")
            service = UpgradeService(settings, task_service, project_path=Path(tmpdir) / "project")

            cancelled = service.cancel("upgrade-orphan")

            self.assertEqual(cancelled["task_id"], "upgrade-orphan")
            self.assertEqual(cancelled["status"], "cancelled")
            stored_task = task_service.get_task("upgrade-orphan")
            self.assertEqual(stored_task["status"], "cancelled")
            self.assertEqual(stored_task["progress"], 100)
            self.assertEqual(stored_task["message"], "升级任务已取消")

    def test_start_can_submit_task_for_runner_and_runner_executes_it(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.runner import run_pending_once
        from app.v2.upgrade.service import UpgradeCommandExecutor, UpgradeService

        class FakeExecutor(UpgradeCommandExecutor):
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def run(self, command: list[str], *, cwd: Path | None = None) -> None:
                self.commands.append(command)

        image = b"web-api-image"
        manifest = {
            "schema_version": "2",
            "version": "v2.0.0",
            "components": [
                {"type": "platform", "services": ["web-api"], "images": [{"service": "web-api", "image": "repo/web-api:v2.0.0", "archive": "images/web-api.tar", "sha256": hashlib.sha256(image).hexdigest()}]},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="upgrade-secret")
            database = V2Database(settings)
            database.initialize()
            executor = FakeExecutor()
            service = UpgradeService(settings, TaskService(database), executor=executor, project_path=Path(tmpdir) / "project")
            task = service.upload_package_bytes(self._package(manifest, {"images/web-api.tar": image}), filename="upgrade.tar.gz")
            self.assertTrue(service.precheck(task["task_id"])["ok"])

            submitted = service.start(task["task_id"], submit_to_runner=True)
            self.assertEqual(submitted["status"], "pending")
            self.assertTrue(submitted["runner_requested"])
            self.assertEqual(executor.commands, [])

            executed = run_pending_once(settings, TaskService(database), executor=executor, project_path=Path(tmpdir) / "project")
            self.assertEqual(executed, 1)
            final = json.loads((settings.upgrades_dir / task["task_id"] / "task.json").read_text(encoding="utf-8"))
            self.assertEqual(final["status"], "success")
            self.assertTrue(any(command[:2] == ["docker", "load"] for command in executor.commands))

    def test_observability_upgrade_only_restarts_prometheus_and_checks_permissions(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeCommandExecutor, UpgradeService

        class FakeExecutor(UpgradeCommandExecutor):
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def run(self, command: list[str], *, cwd: Path | None = None) -> None:
                self.commands.append(command)

        prometheus_image = b"prometheus-image"
        manifest = {
            "schema_version": "2",
            "version": "v2.55.2",
            "components": [
                {
                    "type": "observability",
                    "services": ["prometheus"],
                    "images": [{"service": "prometheus", "image": "prom/prometheus:v2.55.2", "archive": "images/prometheus.tar", "sha256": hashlib.sha256(prometheus_image).hexdigest()}],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="upgrade-secret")
            database = V2Database(settings)
            database.initialize()
            (settings.prometheus_data_dir / "01ABC").mkdir(parents=True)
            (settings.prometheus_data_dir / "01ABC" / "meta.json").write_text("{}", encoding="utf-8")
            executor = FakeExecutor()
            service = UpgradeService(settings, TaskService(database), executor=executor, project_path=Path(tmpdir) / "project")
            task = service.upload_package_bytes(self._package(manifest, {"images/prometheus.tar": prometheus_image}), filename="observability.tar.gz")

            precheck = service.precheck(task["task_id"])
            self.assertTrue(precheck["ok"])
            self.assertIn("prometheus_permissions", [check["name"] for check in precheck["checks"]])

            started = service.start(task["task_id"])
            self.assertEqual(started["status"], "succeeded")
            override = (settings.compose_runtime_dir / "docker-compose.upgrade.yml").read_text(encoding="utf-8")
            self.assertIn("prometheus:", override)
            self.assertIn("prom/prometheus:v2.55.2", override)
            self.assertNotIn("web-api:", override)
            self.assertTrue(any(command[-1:] == ["prometheus"] for command in executor.commands if command[:3] == ["docker", "compose", "-f"]))

    def test_component_history_defaults_to_runner_and_prometheus_packages(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeService

        runner_image = b"runner-image"
        prometheus_image = b"prometheus-image"
        runner_manifest = {
            "schema_version": "2",
            "version": "v0.3.0",
            "components": [
                {
                    "type": "runner",
                    "services": ["upgrade-runner"],
                    "images": [{"service": "upgrade-runner", "image": "repo/upgrade-runner:v0.3.0", "archive": "images/upgrade-runner.tar", "sha256": hashlib.sha256(runner_image).hexdigest()}],
                }
            ],
        }
        prometheus_manifest = {
            "schema_version": "2",
            "version": "v2.55.2",
            "components": [
                {
                    "type": "observability",
                    "services": ["prometheus"],
                    "images": [{"service": "prometheus", "image": "prom/prometheus:v2.55.2", "archive": "images/prometheus.tar", "sha256": hashlib.sha256(prometheus_image).hexdigest()}],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="upgrade-secret")
            database = V2Database(settings)
            database.initialize()
            service = UpgradeService(settings, TaskService(database), project_path=Path(tmpdir) / "project")
            service.upload_package_bytes(self._package(runner_manifest, {"images/upgrade-runner.tar": runner_image}), filename="runner.tar.gz")
            service.upload_package_bytes(self._package(prometheus_manifest, {"images/prometheus.tar": prometheus_image}), filename="prometheus.tar.gz")

            self.assertEqual({task["component"] for task in service.history()}, {"upgrade-runner", "prometheus"})
            self.assertEqual({task["component"] for task in service.history(component_type="observability")}, {"prometheus"})

    def test_runner_component_upgrade_writes_runtime_override_and_only_restarts_runner(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.runner import run_pending_once
        from app.v2.upgrade.service import UpgradeCommandExecutor, UpgradeService

        class FakeExecutor(UpgradeCommandExecutor):
            def __init__(self) -> None:
                self.commands: list[list[str]] = []
                self.restart_calls = 0

            def run(self, command: list[str], *, cwd: Path | None = None) -> None:
                self.commands.append(command)
                if command[:3] == ["docker", "compose", "-f"]:
                    self.restart_calls += 1
                    if self.restart_calls == 1:
                        raise SystemExit("runner restarted")

        runner_image = b"runner-image"
        manifest = {
            "schema_version": "2",
            "version": "v0.3.0",
            "components": [
                {
                    "type": "runner",
                    "services": ["upgrade-runner"],
                    "images": [{"service": "upgrade-runner", "image": "repo/upgrade-runner:v0.3.0", "archive": "images/upgrade-runner.tar", "sha256": hashlib.sha256(runner_image).hexdigest()}],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="upgrade-secret")
            database = V2Database(settings)
            database.initialize()
            executor = FakeExecutor()
            service = UpgradeService(settings, TaskService(database), executor=executor, project_path=Path(tmpdir) / "project")
            task = service.upload_package_bytes(self._package(manifest, {"images/upgrade-runner.tar": runner_image}), filename="runner.tar.gz")

            precheck = service.precheck(task["task_id"])
            self.assertTrue(precheck["ok"])
            self.assertEqual(precheck["components"], ["runner"])

            started = service.start(task["task_id"])
            self.assertEqual(started["status"], "running")
            restart_state = json.loads((settings.upgrades_dir / task["task_id"] / "task.json").read_text(encoding="utf-8"))
            self.assertEqual(restart_state["status"], "runner_restarting")
            override = (settings.compose_runtime_dir / "docker-compose.runner-upgrade.yml").read_text(encoding="utf-8")
            self.assertIn("upgrade-runner:", override)
            self.assertIn("repo/upgrade-runner:v0.3.0", override)
            self.assertNotIn("web-api:", override)
            self.assertFalse((settings.compose_runtime_dir / "docker-compose.upgrade.yml").exists())
            compose_commands = [command for command in executor.commands if command[:3] == ["docker", "compose", "-f"]]
            self.assertTrue(any("docker-compose.runner-upgrade.yml" in part for command in compose_commands for part in command))
            self.assertTrue(any(command[-1:] == ["upgrade-runner"] for command in compose_commands))

            resumed = run_pending_once(settings, TaskService(database), executor=executor, project_path=Path(tmpdir) / "project")
            self.assertEqual(resumed, 1)
            final = json.loads((settings.upgrades_dir / task["task_id"] / "task.json").read_text(encoding="utf-8"))
            self.assertEqual(final["status"], "success")
            self.assertEqual(executor.restart_calls, 1)

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

    def test_component_catalog_includes_runner_and_prometheus_versions(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeCommandExecutor, UpgradeService

        class FakeExecutor(UpgradeCommandExecutor):
            def output(self, command: list[str], *, cwd: Path | None = None) -> str:
                if command[:2] == ["docker", "inspect"]:
                    return json.dumps([
                        {
                            "Config": {"Image": "prom/prometheus:v2.55.1"},
                            "State": {"Status": "running", "Running": True},
                        }
                    ])
                return ""

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="upgrade-secret", runner_version="v0.3.0")
            database = V2Database(settings)
            database.initialize()
            service = UpgradeService(settings, TaskService(database), executor=FakeExecutor(), project_path=Path(tmpdir) / "project")

            components = service.component_catalog()["components"]

            self.assertEqual([component["service"] for component in components], ["upgrade-runner", "prometheus"])
            self.assertEqual(components[0]["display_name"], "升级中心组件")
            self.assertEqual(components[0]["version"], "v0.3.0")
            self.assertEqual(components[1]["display_name"], "观测组件")
            self.assertEqual(components[1]["version"], "v2.55.1")

    def test_verification_reads_runtime_services_and_prometheus_version(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeCommandExecutor, UpgradeService

        class FakeExecutor(UpgradeCommandExecutor):
            def output(self, command: list[str], *, cwd: Path | None = None) -> str:
                if command[:4] == ["docker", "compose", "-f", "docker-compose.offline.yml"]:
                    return "\n".join(
                        [
                            json.dumps({"Service": "web-api", "Name": "smartx-web-api-1", "State": "running"}),
                            json.dumps({"Service": "prometheus", "Name": "smartx-prometheus-1", "State": "running"}),
                        ]
                    )
                if command[:2] == ["docker", "inspect"] and command[-1] == "smartx-web-api-1":
                    return json.dumps([
                        {
                            "Config": {
                                "Image": "repo/web-api:v0.5.0",
                                "Env": ["SMARTX_APP_VERSION=v0.5.0"],
                            },
                            "Image": "sha256:webapi",
                            "State": {"Status": "running", "Running": True, "StartedAt": "2026-06-07T01:00:00Z"},
                        }
                    ])
                if command[:2] == ["docker", "inspect"] and command[-1] == "smartx-prometheus-1":
                    return json.dumps([
                        {
                            "Config": {"Image": "prom/prometheus:v2.55.1", "Env": []},
                            "Image": "sha256:prom",
                            "State": {"Status": "running", "Running": True, "StartedAt": "2026-06-07T01:01:00Z"},
                        }
                    ])
                return ""

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=Path(tmpdir), secret_key="upgrade-secret", compose_file="docker-compose.offline.yml", compose_project_name="smartx-test")
            database = V2Database(settings)
            database.initialize()
            service = UpgradeService(settings, TaskService(database), executor=FakeExecutor(), project_path=Path(tmpdir) / "project")

            verification = service.verification()

            self.assertEqual(verification["prometheus_version"], "v2.55.1")
            self.assertIsNone(verification["service_status_error"])
            self.assertEqual([item["service"] for item in verification["services"]], ["web-api", "prometheus"])
            self.assertEqual(verification["services"][0]["app_version"], "v0.5.0")
            self.assertEqual(verification["services"][1]["app_version"], "v2.55.1")


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
            previous_dry_run = os.environ.get("SMARTX_UPGRADE_DRY_RUN")
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_SECRET_KEY"] = "upgrade-api-secret"
            os.environ["SMARTX_ADMIN_PASSWORD"] = "password"
            os.environ["SMARTX_UPGRADE_DRY_RUN"] = "1"
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
                    self.assertFalse(payload["precheck_ok"])

                    precheck = client.post(f"/api/admin/upgrade/precheck/{payload['task_id']}", headers=headers)
                    self.assertEqual(precheck.status_code, 200)
                    self.assertTrue(precheck.json()["ok"])

                    started = client.post(f"/api/admin/upgrade/start/{payload['task_id']}", headers=headers)
                    self.assertEqual(started.status_code, 200)
                    self.assertEqual(started.json()["status"], "pending")
                    self.assertTrue(started.json()["runner_requested"])

                    status = client.get(f"/api/admin/upgrade/status/{payload['task_id']}", headers=headers)
                    self.assertEqual(status.status_code, 200)
                    self.assertEqual(status.json()["status"], "pending")

                    history = client.get("/api/admin/upgrade/history", headers=headers)
                    self.assertEqual(history.status_code, 200)
                    self.assertEqual(history.json()[0]["task_id"], payload["task_id"])

                    version = client.get("/api/admin/upgrade/version", headers=headers)
                    self.assertEqual(version.status_code, 200)
                    self.assertTrue(version.json()["version"])

                    component_version = client.get("/api/admin/component-upgrade/version", headers=headers)
                    self.assertEqual(component_version.status_code, 200)
                    self.assertEqual(component_version.json()["component"], "upgrade-runner")

                    component_catalog = client.get("/api/admin/component-upgrade/components", headers=headers)
                    self.assertEqual(component_catalog.status_code, 200)
                    self.assertEqual([component["service"] for component in component_catalog.json()["components"]], ["upgrade-runner", "prometheus"])

                    verification = client.get("/api/admin/upgrade/verification", headers=headers)
                    self.assertEqual(verification.status_code, 200)
                    self.assertIn("app_version", verification.json())
                    self.assertIn("runner_version", verification.json())
                    self.assertIn("prometheus_version", verification.json())
                    self.assertIsNone(verification.json()["package"])

                    delete_blocked = client.delete(f"/api/admin/upgrade/package/{payload['task_id']}", headers=headers)
                    self.assertEqual(delete_blocked.status_code, 400)

                    component_upload = client.post("/api/admin/component-upgrade/upload", files={"file": ("upgrade.tar.gz", package, "application/gzip")}, headers=headers)
                    self.assertEqual(component_upload.status_code, 200)
                    component_payload = component_upload.json()
                    component_deleted = client.delete(f"/api/admin/component-upgrade/package/{component_payload['task_id']}", headers=headers)
                    self.assertEqual(component_deleted.status_code, 200)

                    runner_image = b"runner-image"
                    runner_manifest = {
                        "schema_version": "2",
                        "version": "v0.3.0",
                        "components": [
                            {
                                "type": "runner",
                                "services": ["upgrade-runner"],
                                "images": [
                                    {
                                        "service": "upgrade-runner",
                                        "image": "repo/upgrade-runner:v0.3.0",
                                        "archive": "images/upgrade-runner.tar",
                                        "sha256": hashlib.sha256(runner_image).hexdigest(),
                                    }
                                ],
                            }
                        ],
                    }
                    runner_package = build_package(runner_manifest, {"images/upgrade-runner.tar": runner_image})
                    runner_upload = client.post("/api/admin/component-upgrade/upload", files={"file": ("runner.tar.gz", runner_package, "application/gzip")}, headers=headers)
                    self.assertEqual(runner_upload.status_code, 200)
                    runner_payload = runner_upload.json()
                    runner_precheck = client.post(f"/api/admin/component-upgrade/precheck/{runner_payload['task_id']}", headers=headers)
                    self.assertEqual(runner_precheck.status_code, 200)
                    self.assertTrue(runner_precheck.json()["ok"])

                    runner_started = client.post(f"/api/admin/component-upgrade/start/{runner_payload['task_id']}", headers=headers)
                    self.assertEqual(runner_started.status_code, 200)
                    self.assertEqual(runner_started.json()["status"], "succeeded")
                    self.assertFalse(runner_started.json().get("runner_requested", False))

                    prometheus_image = b"prometheus-image"
                    prometheus_manifest = {
                        "schema_version": "2",
                        "version": "v2.55.1",
                        "components": [
                            {
                                "type": "observability",
                                "services": ["prometheus"],
                                "images": [
                                    {
                                        "service": "prometheus",
                                        "image": "prom/prometheus:v2.55.1",
                                        "archive": "images/prometheus.tar",
                                        "sha256": hashlib.sha256(prometheus_image).hexdigest(),
                                    }
                                ],
                            }
                        ],
                    }
                    prometheus_package = build_package(prometheus_manifest, {"images/prometheus.tar": prometheus_image})
                    prometheus_upload = client.post("/api/admin/component-upgrade/upload", files={"file": ("prometheus.tar.gz", prometheus_package, "application/gzip")}, headers=headers)
                    self.assertEqual(prometheus_upload.status_code, 200)
                    prometheus_payload = prometheus_upload.json()
                    self.assertEqual(prometheus_payload["kind"], "component")
                    self.assertEqual(prometheus_payload["component"], "prometheus")
                    component_history = client.get("/api/admin/component-upgrade/history", headers=headers)
                    self.assertEqual(component_history.status_code, 200)
                    self.assertIn("prometheus", [task.get("component") for task in component_history.json()])
                    prometheus_precheck = client.post(f"/api/admin/component-upgrade/precheck/{prometheus_payload['task_id']}", headers=headers)
                    self.assertEqual(prometheus_precheck.status_code, 200)
                    self.assertTrue(prometheus_precheck.json()["ok"])

                    prometheus_started = client.post(f"/api/admin/component-upgrade/start/{prometheus_payload['task_id']}", headers=headers)
                    self.assertEqual(prometheus_started.status_code, 200)
                    self.assertEqual(prometheus_started.json()["status"], "pending")
                    self.assertTrue(prometheus_started.json()["runner_requested"])
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_SECRET_KEY", None)
                os.environ.pop("SMARTX_ADMIN_PASSWORD", None)
                if previous_dry_run is None:
                    os.environ.pop("SMARTX_UPGRADE_DRY_RUN", None)
                else:
                    os.environ["SMARTX_UPGRADE_DRY_RUN"] = previous_dry_run


if __name__ == "__main__":
    unittest.main()
