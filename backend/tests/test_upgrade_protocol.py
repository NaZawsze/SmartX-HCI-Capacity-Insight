from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class UpgradeProtocolTest(unittest.TestCase):
    def test_manifest_requires_supported_protocol_and_capabilities(self) -> None:
        from app.upgrade_protocol.constants import RUNNER_CAPABILITIES, RUNNER_PROTOCOL_VERSION
        from app.upgrade_protocol.validation import ProtocolValidationError, validate_manifest_compatibility

        manifest = {
            "schema_version": "3",
            "minimum_runner_protocol": RUNNER_PROTOCOL_VERSION,
            "required_capabilities": ["backup.create", "script.sandbox.v1"],
        }
        validate_manifest_compatibility(manifest, RUNNER_PROTOCOL_VERSION, RUNNER_CAPABILITIES)

        with self.assertRaisesRegex(ProtocolValidationError, "协议版本"):
            validate_manifest_compatibility(
                {**manifest, "minimum_runner_protocol": RUNNER_PROTOCOL_VERSION + 1},
                RUNNER_PROTOCOL_VERSION,
                RUNNER_CAPABILITIES,
            )

        with self.assertRaisesRegex(ProtocolValidationError, "能力"):
            validate_manifest_compatibility(
                {**manifest, "required_capabilities": ["future.action"]},
                RUNNER_PROTOCOL_VERSION,
                RUNNER_CAPABILITIES,
            )

    def test_execution_plan_has_stable_action_contract(self) -> None:
        from app.upgrade_protocol.models import ActionStatus, ExecutionAction, ExecutionPlan

        plan = ExecutionPlan(
            protocol_version=1,
            required_capabilities=["backup.create"],
            actions=[ExecutionAction(id="backup", type="backup.create", params={"scope": "platform"})],
        )

        payload = plan.to_dict()
        self.assertEqual(payload["protocol_version"], 1)
        self.assertEqual(payload["actions"][0]["status"], ActionStatus.PENDING.value)
        self.assertEqual(payload["actions"][0]["attempt"], 0)
        self.assertEqual(payload["actions"][0]["checkpoint"], {})

    def test_task_store_writes_atomically_and_increments_revision(self) -> None:
        from app.upgrade_runner.store import TaskStore

        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir) / "upgrade-1"
            store = TaskStore(task_dir)
            first = store.save({"task_id": "upgrade-1", "status": "pending"})
            second = store.update(lambda task: {**task, "status": "running"}, expected_revision=first["revision"])

            self.assertEqual(first["revision"], 1)
            self.assertEqual(second["revision"], 2)
            self.assertEqual(store.load()["status"], "running")
            self.assertFalse((task_dir / "task.json.tmp").exists())
            json.loads((task_dir / "task.json").read_text(encoding="utf-8"))

    def test_web_api_task_write_rejects_stale_revision(self) -> None:
        from app.upgrade_runner.store import TaskStore
        from app.v2.upgrade.service import HTTPException, _save_task_file

        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir) / "upgrade-1"
            store = TaskStore(task_dir)
            store.save({"task_id": "upgrade-1", "status": "recovery_required"})
            stale = store.load()
            store.update(lambda task: {**task, "status": "running"})

            with self.assertRaises(HTTPException) as raised:
                _save_task_file(task_dir, {**stale, "recovery_command": "rollback"})

            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(store.load()["status"], "running")


class UpgradePersistenceTest(unittest.TestCase):
    def test_database_initializes_runner_state_and_lease_tables(self) -> None:
        from app.v2.config import V2Settings
        from app.v2.database import V2Database

        with tempfile.TemporaryDirectory() as tmpdir:
            database = V2Database(V2Settings(data_root=tmpdir, secret_key="upgrade-protocol"))
            database.initialize()
            with database.connection() as conn:
                tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                lease_columns = {row["name"] for row in conn.execute("PRAGMA table_info(upgrade_task_leases)")}

            self.assertIn("upgrade_runner_state", tables)
            self.assertIn("upgrade_task_leases", tables)
            self.assertTrue({"task_id", "lease_owner", "lease_expires_at", "heartbeat_at", "revision"} <= lease_columns)


class UpgradeCompilerTest(unittest.TestCase):
    def test_compiler_translates_platform_manifest_to_generic_actions(self) -> None:
        from app.v2.upgrade.compiler import compile_execution_plan

        manifest = {
            "schema_version": "3",
            "minimum_runner_protocol": 1,
            "required_capabilities": ["script.sandbox.v1"],
            "project_files": True,
            "project_file_list": ["docker-compose.offline.yml"],
            "components": [
                {
                    "type": "platform",
                    "services": ["web-api", "frontend"],
                    "images": [
                        {
                            "service": "web-api",
                            "image": "repo/web-api:v0.6.0",
                            "archive": "images/web-api.tar",
                            "sha256": "a" * 64,
                        }
                    ],
                }
            ],
            "migration": {
                "required": True,
                "script": "migrations/migrate.py",
                "sha256": "b" * 64,
                "image_service": "web-api",
                "mounts": [{"source": "/data", "target": "/data", "mode": "rw"}],
            },
        }

        plan = compile_execution_plan(manifest).to_dict()

        self.assertEqual(plan["protocol_version"], 1)
        self.assertEqual(
            [action["type"] for action in plan["actions"]],
            [
                "backup.create",
                "image.load",
                "files.sync",
                "compose.override",
                "script.run_sandboxed",
                "compose.apply",
                "health.http",
            ],
        )
        self.assertEqual(plan["actions"][1]["params"]["sha256"], "a" * 64)
        self.assertEqual(plan["actions"][4]["params"]["timeout_seconds"], 900)
        self.assertEqual(plan["actions"][-1]["params"]["attempts"], 30)
        self.assertEqual(plan["actions"][-1]["params"]["delay_seconds"], 2)

    def test_compiler_adds_prometheus_health_check_and_rejects_runner_component(self) -> None:
        from app.v2.upgrade.compiler import UpgradeCompilationError, compile_execution_plan

        prometheus = {
            "schema_version": "3",
            "components": [
                {
                    "type": "observability",
                    "services": ["prometheus"],
                    "images": [
                        {
                            "service": "prometheus",
                            "image": "prom/prometheus:v3.0.0",
                            "archive": "images/prometheus.tar",
                            "sha256": "c" * 64,
                        }
                    ],
                }
            ],
        }
        plan = compile_execution_plan(prometheus).to_dict()
        self.assertEqual(plan["actions"][-1]["type"], "health.prometheus")

        with self.assertRaisesRegex(UpgradeCompilationError, "web-api"):
            compile_execution_plan(
                {
                    "schema_version": "3",
                    "components": [{"type": "runner", "services": ["upgrade-runner"], "images": []}],
                }
            )

    def test_service_submission_persists_compiled_execution_plan(self) -> None:
        import hashlib
        import io
        import tarfile

        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeService

        image = b"web-api"
        manifest = {
            "schema_version": "3",
            "minimum_runner_protocol": 1,
            "version": "v0.6.0",
            "components": [
                {
                    "type": "platform",
                    "services": ["web-api"],
                    "images": [
                        {
                            "service": "web-api",
                            "image": "repo/web-api:v0.6.0",
                            "archive": "images/web-api.tar",
                            "sha256": hashlib.sha256(image).hexdigest(),
                        }
                    ],
                }
            ],
        }
        manifest_bytes = json.dumps(manifest).encode()
        checksums = (
            f"{hashlib.sha256(manifest_bytes).hexdigest()}  manifest.json\n"
            f"{hashlib.sha256(image).hexdigest()}  images/web-api.tar\n"
        ).encode()
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for name, content in {
                "manifest.json": manifest_bytes,
                "images/web-api.tar": image,
                "checksums.sha256": checksums,
            }.items():
                info = tarfile.TarInfo(name)
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=tmpdir, secret_key="upgrade-compiler")
            database = V2Database(settings)
            database.initialize()
            service = UpgradeService(settings, TaskService(database), project_path=Path(tmpdir) / "project")
            uploaded = service.upload_package_bytes(buffer.getvalue(), filename="platform.tar.gz")
            prechecked = service.precheck(uploaded["task_id"])
            self.assertIn("checksums", [check["name"] for check in prechecked["checks"]])
            submitted = service.start(uploaded["task_id"], submit_to_runner=True)

            self.assertEqual(submitted["status"], "pending")
            self.assertEqual(submitted["task_schema_version"], 2)
            self.assertEqual(submitted["execution_plan"]["protocol_version"], 1)
            self.assertEqual(submitted["execution_plan"]["actions"][0]["type"], "backup.create")


class UpgradeRecoveryServiceTest(unittest.TestCase):
    def test_recovery_commands_are_persisted_and_fail_marks_critical_task(self) -> None:
        from app.upgrade_runner.store import TaskStore
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.models import TaskStatus, TaskType
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=tmpdir, secret_key="upgrade-recovery")
            database = V2Database(settings)
            database.initialize()
            tasks = TaskService(database)
            task_id = "upgrade-recovery"
            TaskStore(settings.upgrades_dir / task_id).save(
                {
                    "task_id": task_id,
                    "status": "recovery_required",
                    "components": ["platform"],
                    "execution_plan": {"protocol_version": 1, "required_capabilities": [], "actions": []},
                    "available_recovery_actions": ["continue", "rollback", "fail"],
                }
            )
            tasks.create_task(task_id, TaskType.UPGRADE, "执行系统升级", status=TaskStatus.FAILED, progress=100)
            service = UpgradeService(settings, tasks)

            continued = service.recovery_continue(task_id)
            self.assertEqual(continued["recovery_command"], "continue")
            rollback = service.recovery_rollback(task_id)
            self.assertEqual(rollback["recovery_command"], "rollback")
            failed = service.recovery_fail(task_id)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(tasks.get_task(task_id)["severity"], "critical")

    def test_component_catalog_exposes_runner_protocol_state(self) -> None:
        from app.upgrade_runner.lease import LeaseManager
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(data_root=tmpdir, secret_key="runner-state", runner_version="v0.3.0")
            database = V2Database(settings)
            database.initialize()
            LeaseManager(settings.sqlite_path, "runner-a").update_runner_state("v0.3.0")
            runner = UpgradeService(settings, TaskService(database)).component_catalog()["components"][0]

            self.assertEqual(runner["protocol_version"], 1)
            self.assertIn("backup.create", runner["capabilities"])
            self.assertTrue(runner["compatible"])
            self.assertTrue(runner["heartbeat_at"])


if __name__ == "__main__":
    unittest.main()
