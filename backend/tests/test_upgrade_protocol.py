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

    def test_broad_runner_capabilities_satisfy_legacy_action_capabilities(self) -> None:
        from app.upgrade_protocol.constants import RUNNER_PROTOCOL_VERSION
        from app.upgrade_protocol.validation import validate_manifest_compatibility

        manifest = {
            "schema_version": "3",
            "minimum_runner_protocol": RUNNER_PROTOCOL_VERSION,
            "required_capabilities": [
                "backup.create",
                "image.load",
                "files.sync",
                "compose.override",
                "compose.project_migrate.v1",
                "compose.apply",
                "health.http",
                "health.prometheus",
                "checkpoint.write",
                "rollback.restore",
                "script.sandbox.v1",
            ],
        }
        broad_capabilities = {
            "backup.v1",
            "image.v1",
            "files.v1",
            "compose.v1",
            "compose.project.v1",
            "health.v1",
            "rollback.v1",
            "task.recovery.v1",
            "script.sandbox.v1",
        }

        validate_manifest_compatibility(manifest, RUNNER_PROTOCOL_VERSION, broad_capabilities)

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

    def test_compiler_starts_prometheus_when_platform_compose_rebuild_declares_it(self) -> None:
        from app.v2.upgrade.compiler import compile_execution_plan

        manifest = {
            "schema_version": "3",
            "components": [
                {
                    "type": "platform",
                    "services": ["web-api", "collector-worker", "frontend", "prometheus", "upgrade-runner"],
                    "images": [
                        {
                            "service": "web-api",
                            "image": "repo/web-api:v0.5.2",
                            "archive": "images/web-api.tar",
                            "sha256": "a" * 64,
                        }
                    ],
                }
            ],
        }

        plan = compile_execution_plan(manifest).to_dict()

        compose_apply = next(action for action in plan["actions"] if action["type"] == "compose.apply")
        compose_override = next(action for action in plan["actions"] if action["type"] == "compose.override")
        self.assertEqual(compose_apply["params"]["services"], ["collector-worker", "frontend", "prometheus", "web-api"])
        self.assertEqual(compose_override["params"]["services"], ["collector-worker", "frontend", "prometheus", "upgrade-runner", "web-api"])
        self.assertEqual(plan["actions"][-1]["id"], "health-platform")

    def test_compiler_places_task_state_migration_and_legacy_cleanup_around_v052_cutover(self) -> None:
        from app.v2.upgrade.compiler import compile_execution_plan

        manifest = {
            "schema_version": "3",
            "components": [
                {
                    "type": "platform",
                    "services": ["web-api", "frontend", "prometheus", "upgrade-runner"],
                    "images": [],
                }
            ],
            "project_files": True,
            "project_file_list": ["docker-compose.release.yml"],
            "directory_transition": {
                "target_root": "/data/smartx-storage-forecast",
                "upgrades_path": "/data/smartx-storage-forecast/upgrades",
            },
            "environment_transitions": [
                {
                    "from_project": "smartx-storage-forecast",
                    "from_network": "smartx-storage-forecast_smartx-net",
                    "to_project": "smartx-hci-capacity-insight",
                    "to_network": "smartx-hci-capacity-insight-net",
                }
            ],
            "legacy_cleanup": {
                "legacy_projects": ["smartx-storage-forecast"],
                "legacy_networks": ["smartx-storage-forecast_smartx-net"],
                "legacy_paths": ["/data/upgrades"],
                "target_app_residual_paths": ["/data/smartx-storage-forecast/app/upgrades"],
                "protected_paths": ["/data/smartx-storage-forecast"],
            },
        }

        plan = compile_execution_plan(manifest).to_dict()
        action_types = [action["type"] for action in plan["actions"]]

        self.assertEqual(
            action_types,
            [
                "backup.create",
                "filesystem.prepare",
                "files.sync",
                "task.migrate_runtime_state",
                "compose.override",
                "compose.project_migrate",
                "compose.apply",
                "health.http",
                "task.sync_runtime_state",
                "runner.handoff_target_runtime",
                "runner.stop_legacy_runtime",
                "legacy.cleanup",
            ],
        )
        self.assertIn("task.recovery.v1", plan["required_capabilities"])
        self.assertIn("runner.handoff.v1", plan["required_capabilities"])
        stop_runner = plan["actions"][-2]
        self.assertEqual(
            stop_runner["params"],
            {
                "legacy_project": "smartx-storage-forecast",
                "legacy_runner_container": "smartx-storage-forecast-upgrade-runner-1",
                "target_project": "smartx-hci-capacity-insight",
            },
        )
        cleanup = plan["actions"][-1]
        self.assertEqual(cleanup["params"]["legacy_paths"], ["/data/upgrades"])
        self.assertEqual(cleanup["params"]["protected_paths"], ["/data/smartx-storage-forecast"])

    def test_compiler_schedules_post_upgrade_cleanup_when_manifest_requests_it(self) -> None:
        from app.v2.upgrade.compiler import compile_execution_plan

        manifest = {
            "schema_version": "3",
            "components": [
                {
                    "type": "platform",
                    "services": ["web-api", "frontend", "prometheus", "upgrade-runner"],
                    "images": [],
                }
            ],
            "project_files": True,
            "project_file_list": ["docker-compose.release.yml"],
            "directory_transition": {
                "target_root": "/data/smartx-storage-forecast",
                "upgrades_path": "/data/smartx-storage-forecast/upgrades",
                "env_file_migration": {
                    "target": "/data/smartx-storage-forecast/project/.env",
                    "legacy_candidates": ["/opt/smartx-storage-forecast/.env"],
                    "preserve_existing": True,
                    "sanitize_image_tags": True,
                    "fallback_defaults": True,
                },
            },
            "environment_transitions": [
                {
                    "from_project": "smartx-storage-forecast",
                    "from_network": "smartx-storage-forecast_smartx-net",
                    "to_project": "smartx-hci-capacity-insight",
                    "to_network": "smartx-hci-capacity-insight-net",
                }
            ],
            "legacy_cleanup": {
                "legacy_projects": ["smartx-storage-forecast"],
                "legacy_networks": ["smartx-storage-forecast_smartx-net"],
                "legacy_paths": ["/data/upgrades"],
                "target_app_residual_paths": ["/data/smartx-storage-forecast/app/upgrades"],
                "protected_paths": ["/data/smartx-storage-forecast"],
            },
            "post_upgrade": {
                "create_cleanup_task": True,
                "cleanup_task_policy": "after_platform_health_success",
                "cleanup_failure_severity": "warning",
            },
        }

        plan = compile_execution_plan(manifest).to_dict()
        action_types = [action["type"] for action in plan["actions"]]

        self.assertIn("post_upgrade.schedule_cleanup", action_types)
        self.assertIn("runner.schedule_target_runtime_handoff", action_types)
        self.assertNotIn("runner.handoff_target_runtime", action_types)
        self.assertNotIn("runner.stop_legacy_runtime", action_types)
        self.assertNotIn("legacy.cleanup", action_types)
        self.assertLess(action_types.index("task.sync_runtime_state"), action_types.index("post_upgrade.schedule_cleanup"))
        self.assertLess(action_types.index("post_upgrade.schedule_cleanup"), action_types.index("runner.schedule_target_runtime_handoff"))
        cutover = next(action for action in plan["actions"] if action["type"] == "runner.schedule_target_runtime_handoff")
        self.assertEqual(
            cutover["params"],
            {
                "image": "",
                "compose_project": "smartx-hci-capacity-insight",
                "network_name": "smartx-hci-capacity-insight-net",
                "project_path": "/data/smartx-storage-forecast/project",
                "app_data_path": "/data/smartx-storage-forecast/app",
                "upgrades_path": "/data/smartx-storage-forecast/upgrades",
                "backups_path": "/data/smartx-storage-forecast/backups",
                "exports_path": "/data/smartx-storage-forecast/exports",
                "compose_runtime_path": "/data/smartx-storage-forecast/compose-runtime",
                "prometheus_data_path": "/data/smartx-storage-forecast/prometheus",
            },
        )

    def test_compiler_prepares_single_root_layout_before_project_sync(self) -> None:
        from app.v2.upgrade.compiler import compile_execution_plan

        transition = {
            "target_root": "/data/smartx-storage-forecast",
            "project_path": "/data/smartx-storage-forecast/project",
            "app_data_path": "/data/smartx-storage-forecast/app",
            "prometheus_data_path": "/data/smartx-storage-forecast/prometheus",
            "compose_runtime_path": "/data/smartx-storage-forecast/compose-runtime",
            "legacy_app_data_paths": ["/data/smartx-capacity-insight-data/app", "/data"],
            "legacy_prometheus_data_paths": ["/data/smartx-capacity-insight-data/prometheus", "/prometheus-data"],
        }
        manifest = {
            "schema_version": "3",
            "project_files": True,
            "project_file_list": ["docker-compose.release.yml"],
            "directory_transition": transition,
            "components": [
                {
                    "type": "platform",
                    "services": ["web-api"],
                    "images": [],
                }
            ],
        }

        plan = compile_execution_plan(manifest).to_dict()

        action_types = [action["type"] for action in plan["actions"]]
        self.assertIn("filesystem.prepare", action_types)
        self.assertLess(action_types.index("filesystem.prepare"), action_types.index("files.sync"))
        self.assertLess(action_types.index("filesystem.prepare"), action_types.index("compose.apply"))
        action = next(item for item in plan["actions"] if item["type"] == "filesystem.prepare")
        self.assertEqual(action["params"], transition)
        self.assertIn("filesystem.v1", plan["required_capabilities"])

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
            "min_version": "v0.5.0",
            "source_compatibility": {
                "min_version": "v0.5.0",
                "max_version_inclusive": "v0.6.0",
                "supported_versions": ["v0.5.0", "v0.5.1", "v0.5.2", "v0.6.0"],
            },
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
            settings = V2Settings(data_root=tmpdir, secret_key="upgrade-compiler", app_version="v0.5.1")
            database = V2Database(settings)
            database.initialize()
            from app.upgrade_runner.lease import LeaseManager

            LeaseManager(settings.sqlite_path, "runner-a").update_runner_state("v0.3.1")
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
            settings = V2Settings(data_root=tmpdir, secret_key="runner-state", runner_version="v0.3.1")
            database = V2Database(settings)
            database.initialize()
            LeaseManager(settings.sqlite_path, "runner-a").update_runner_state("v0.3.1")
            runner = UpgradeService(settings, TaskService(database)).component_catalog()["components"][0]

            self.assertEqual(runner["protocol_version"], 1)
            self.assertIn("backup.v1", runner["capabilities"])
            self.assertIn("compose.project.v1", runner["capabilities"])
            self.assertTrue(runner["compatible"])
            self.assertTrue(runner["heartbeat_at"])


if __name__ == "__main__":
    unittest.main()
