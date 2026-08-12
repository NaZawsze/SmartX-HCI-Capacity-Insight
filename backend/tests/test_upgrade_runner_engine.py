from __future__ import annotations

import tempfile
import unittest
import hashlib
import json
import os
import tarfile
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


class UpgradeLeaseTest(unittest.TestCase):
    def test_lease_prevents_concurrent_owner_and_allows_expired_takeover(self) -> None:
        from app.upgrade_runner.lease import LeaseManager

        with tempfile.TemporaryDirectory() as tmpdir:
            database = Path(tmpdir) / "smartx.db"
            now = datetime(2026, 6, 10, tzinfo=timezone.utc)
            first = LeaseManager(database, "runner-a", ttl_seconds=30)
            second = LeaseManager(database, "runner-b", ttl_seconds=30)

            self.assertTrue(first.acquire("upgrade-1", revision=1, now=now))
            self.assertFalse(second.acquire("upgrade-1", revision=1, now=now + timedelta(seconds=5)))
            self.assertTrue(second.acquire("upgrade-1", revision=1, now=now + timedelta(seconds=31)))
            self.assertEqual(second.get("upgrade-1")["lease_owner"], "runner-b")

    def test_runner_heartbeat_records_protocol_and_capabilities(self) -> None:
        from app.upgrade_runner.lease import LeaseManager

        with tempfile.TemporaryDirectory() as tmpdir:
            database = Path(tmpdir) / "smartx.db"
            manager = LeaseManager(database, "runner-a")
            manager.update_runner_state("v0.3.1")
            state = manager.runner_state()

            self.assertEqual(state["runner_version"], "v0.3.1")
            self.assertEqual(state["protocol_version"], 1)
            self.assertIn("backup.v1", state["capabilities"])
            self.assertIn("compose.project.v1", state["capabilities"])


def _safe_extract_for_test(archive: tarfile.TarFile, destination: Path) -> None:
    try:
        archive.extractall(destination, filter="data")
    except TypeError:
        archive.extractall(destination)


def _write_upgrade_business_db(
    path: Path,
    *,
    towers: int = 0,
    clusters: int = 0,
    vm_latest: int = 0,
    vm_volumes: int = 0,
    collection_runs: int = 0,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS towers (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS clusters (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS vm_latest (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS vm_volumes (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS collection_runs (id INTEGER PRIMARY KEY, status TEXT)")
        conn.execute("INSERT INTO users (username) VALUES ('admin')")
        for index in range(towers):
            conn.execute("INSERT INTO towers (name) VALUES (?)", (f"tower-{index}",))
        for index in range(clusters):
            conn.execute("INSERT INTO clusters (name) VALUES (?)", (f"cluster-{index}",))
        for index in range(vm_latest):
            conn.execute("INSERT INTO vm_latest (name) VALUES (?)", (f"vm-{index}",))
        for index in range(vm_volumes):
            conn.execute("INSERT INTO vm_volumes (name) VALUES (?)", (f"volume-{index}",))
        for index in range(collection_runs):
            conn.execute("INSERT INTO collection_runs (status) VALUES (?)", (f"run-{index}",))


def _count_upgrade_business_db(path: Path) -> dict[str, int]:
    with sqlite3.connect(path) as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("users", "towers", "clusters", "vm_latest", "vm_volumes", "collection_runs")
        }


def _write_upgrade_credential_db(path: Path, encrypted_password: str = "encrypted-password") -> None:
    _write_upgrade_business_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute("ALTER TABLE towers ADD COLUMN password_encrypted TEXT")
        conn.execute("ALTER TABLE towers ADD COLUMN api_token_encrypted TEXT")
        conn.execute(
            "INSERT INTO towers (name, password_encrypted, api_token_encrypted) VALUES (?, ?, ?)",
            ("tower-with-credentials", encrypted_password, None),
        )

    def test_runner_executes_requested_recovery_rollback(self) -> None:
        from app.upgrade_runner.main import RunnerSettings, run_pending_once
        from app.upgrade_runner.store import TaskStore
        from app.v2.config import V2Settings
        from app.v2.database import V2Database

        rollback_calls: list[dict] = []

        def rollback(action, _context):
            rollback_calls.append(action)
            return {"checkpoint": {"restored": True}}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            v2_settings = V2Settings(data_root=root, secret_key="rollback-runner")
            database_path = v2_settings.sqlite_path
            V2Database(v2_settings).initialize()
            task_dir = root / "upgrades" / "upgrade-1"
            TaskStore(task_dir).save(
                {
                    "task_id": "upgrade-1",
                    "status": "recovery_required",
                    "recovery_command": "rollback",
                    "package_path": str(root / "package"),
                    "execution_plan": {
                        "protocol_version": 1,
                        "required_capabilities": [],
                        "actions": [
                            {
                                "id": "sync",
                                "type": "files.sync",
                                "status": "succeeded",
                                "attempt": 1,
                                "checkpoint": {},
                                "result": {"backup_path": "/backup/project"},
                            }
                        ],
                    },
                }
            )
            settings = RunnerSettings(
                database_path=database_path,
                upgrades_path=root / "upgrades",
                data_path=root,
                exports_path=root / "exports",
                backups_path=root / "backups",
                compose_runtime_path=root / "runtime",
                prometheus_path=root / "prometheus",
                project_path=root / "project",
                compose_file="docker-compose.offline.yml",
                compose_project="test",
            )
            count = run_pending_once(settings, handlers={"rollback.restore": rollback}, owner="runner-a")

            self.assertEqual(count, 1)
            self.assertEqual(TaskStore(task_dir).load()["status"], "rolled_back")
            self.assertEqual(len(rollback_calls), 1)


class UpgradeEngineTest(unittest.TestCase):
    def _task(self, actions: list[dict]) -> dict:
        return {
            "task_id": "upgrade-1",
            "status": "pending",
            "execution_plan": {
                "protocol_version": 1,
                "required_capabilities": [],
                "actions": actions,
            },
        }

    def test_runner_executes_package_less_post_cleanup_task(self) -> None:
        from app.upgrade_runner.main import RunnerSettings, run_pending_once
        from app.upgrade_runner.store import TaskStore
        from app.v2.config import V2Settings
        from app.v2.database import V2Database

        calls: list[Path] = []

        def cleanup(_action, context):
            calls.append(context["action_context"].package_path)
            return {"ok": True}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            v2_settings = V2Settings(data_root=root, secret_key="post-cleanup-runner")
            V2Database(v2_settings).initialize()
            task_dir = root / "upgrades" / "post-cleanup-upgrade-1"
            TaskStore(task_dir).save(
                {
                    "task_id": "post-cleanup-upgrade-1",
                    "status": "pending",
                    "target_version": "v0.5.2",
                    "task_type": "post_upgrade_cleanup",
                    "manifest": {"package_type": "post_upgrade_cleanup"},
                    "execution_plan": {
                        "protocol_version": 1,
                        "required_capabilities": [],
                        "actions": [
                            {
                                "id": "post-cleanup-precheck-target-health",
                                "type": "post_cleanup.precheck_target_health",
                                "status": "pending",
                                "attempt": 0,
                                "checkpoint": {},
                                "result": {},
                            }
                        ],
                    },
                }
            )
            settings = RunnerSettings(
                database_path=v2_settings.sqlite_path,
                upgrades_path=root / "upgrades",
                data_path=root,
                exports_path=root / "exports",
                backups_path=root / "backups",
                compose_runtime_path=root / "runtime",
                prometheus_path=root / "prometheus",
                project_path=root / "project",
                compose_file="docker-compose.offline.yml",
                compose_project="test",
            )

            count = run_pending_once(settings, handlers={"post_cleanup.precheck_target_health": cleanup}, owner="runner-a")

            self.assertEqual(count, 1)
            self.assertEqual(TaskStore(task_dir).load()["status"], "success")
            self.assertEqual(calls, [task_dir / "package"])

    def test_engine_resumes_safe_running_action_and_skips_completed_actions(self) -> None:
        from app.upgrade_runner.engine import UpgradeEngine
        from app.upgrade_runner.store import TaskStore

        calls: list[str] = []

        def handler(action, _context):
            calls.append(action["id"])
            return {"ok": True, "checkpoint": {"done": True}}

        with tempfile.TemporaryDirectory() as tmpdir:
            store = TaskStore(Path(tmpdir) / "upgrade-1")
            store.save(
                self._task(
                    [
                        {"id": "backup", "type": "backup.create", "status": "succeeded", "attempt": 1, "checkpoint": {}, "result": {}},
                        {"id": "load", "type": "image.load", "status": "running", "attempt": 1, "checkpoint": {}, "result": {}},
                    ]
                )
            )
            result = UpgradeEngine(store, handlers={"image.load": handler}).run()

            self.assertEqual(result["status"], "success")
            self.assertTrue(result.get("finished_at"))
            self.assertEqual(calls, ["load"])
            self.assertEqual(result["execution_plan"]["actions"][1]["attempt"], 2)

    def test_task_mirror_writes_subsequent_saves_to_new_task_directory(self) -> None:
        from app.upgrade_runner.engine import UpgradeEngine
        from app.upgrade_runner.store import TaskStore

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy_dir = root / "legacy-upgrades" / "upgrade-1"
            target_dir = root / "target-upgrades" / "upgrade-1"
            store = TaskStore(legacy_dir)
            store.save(
                self._task(
                    [
                        {
                            "id": "migrate-task-state",
                            "type": "task.migrate_runtime_state",
                            "params": {"target_task_dir": str(target_dir)},
                            "status": "pending",
                            "attempt": 0,
                            "checkpoint": {},
                            "result": {},
                        },
                        {
                            "id": "sync-task-state",
                            "type": "task.sync_runtime_state",
                            "params": {},
                            "status": "pending",
                            "attempt": 0,
                            "checkpoint": {},
                            "result": {},
                        },
                    ]
                )
            )

            def migrate(_action, _context):
                return {"mirror_task_dir": str(target_dir), "checkpoint": {"mirror_task_dir": str(target_dir)}}

            def sync(_action, _context):
                self.assertTrue((target_dir / "task.json").is_file())
                return {"synced": True}

            result = UpgradeEngine(
                store,
                handlers={"task.migrate_runtime_state": migrate, "task.sync_runtime_state": sync},
            ).run()

            mirrored = TaskStore(target_dir).load()
            self.assertEqual(result["status"], "success")
            self.assertEqual(mirrored["status"], "success")
            self.assertEqual(mirrored["task_id"], "upgrade-1")

    def test_action_context_maps_upgrades_before_generic_data_mount(self) -> None:
        from app.upgrade_runner.actions import ActionContext

        context = ActionContext(
            package_path=Path("/package"),
            project_path=Path("/data/smartx-storage-forecast/project"),
            data_path=Path("/data"),
            upgrades_path=Path("/data/upgrades"),
            backups_path=Path("/data/backups"),
            exports_path=Path("/data/exports"),
            compose_runtime_path=Path("/data/compose-runtime"),
            prometheus_path=Path("/prometheus-data"),
            compose_file="docker-compose.release.yml",
            compose_project="smartx-hci-capacity-insight",
            executor=None,  # type: ignore[arg-type]
            host_data_path=Path("/data/smartx-storage-forecast/app"),
            host_upgrades_path=Path("/data/smartx-storage-forecast/upgrades"),
        )

        self.assertEqual(
            context.docker_host_path(Path("/data/upgrades/upgrade-1/task.json")),
            Path("/data/smartx-storage-forecast/upgrades/upgrade-1/task.json"),
        )
        self.assertEqual(
            context.docker_host_path(Path("/data/smartx-storage-forecast/upgrades/upgrade-1/task.json")),
            Path("/data/smartx-storage-forecast/upgrades/upgrade-1/task.json"),
        )

    def test_task_migrate_runtime_state_uses_host_upgrades_path_for_target(self) -> None:
        from app.upgrade_runner.actions import ActionContext, task_migrate_runtime_state

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            context = ActionContext.minimal(root)
            context.upgrades_path = root / "legacy-upgrades"
            context.host_upgrades_path = root / "target-upgrades"
            context.task_id = "upgrade-1"
            source = context.upgrades_path / "upgrade-1"
            source.mkdir(parents=True)
            (source / "task.json").write_text('{"task_id":"upgrade-1"}', encoding="utf-8")

            result = task_migrate_runtime_state(
                {"params": {"target_upgrades_path": str(context.upgrades_path)}},
                context.as_dict(),
            )

            target = context.host_upgrades_path / "upgrade-1"
            self.assertEqual(Path(result["mirror_task_dir"]), target)
            self.assertTrue((target / "task.json").is_file())

    def test_task_migrate_runtime_state_uses_manifest_absolute_target_without_legacy_data_mapping(self) -> None:
        from app.upgrade_runner.actions import ActionContext, task_migrate_runtime_state

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_root = root / "data" / "upgrades"
            target_root = root / "data" / "smartx-storage-forecast" / "upgrades"
            legacy_host_data = root / "data" / "smartx-capacity-insight-data" / "app"
            context = ActionContext.minimal(root)
            context.data_path = root / "data"
            context.upgrades_path = source_root
            context.host_data_path = legacy_host_data
            context.host_upgrades_path = None
            context.task_id = "upgrade-1"
            source = source_root / "upgrade-1"
            source.mkdir(parents=True)
            (source / "task.json").write_text('{"task_id":"upgrade-1"}', encoding="utf-8")

            result = task_migrate_runtime_state(
                {"params": {"target_upgrades_path": str(target_root)}},
                context.as_dict(),
            )

            self.assertEqual(Path(result["mirror_task_dir"]), target_root / "upgrade-1")
            self.assertTrue((target_root / "upgrade-1" / "task.json").is_file())
            self.assertNotIn("smartx-capacity-insight-data", result["mirror_task_dir"])

    def test_task_migrate_runtime_state_preserves_existing_upgrade_history(self) -> None:
        from app.upgrade_runner.actions import ActionContext, task_migrate_runtime_state

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_root = root / "data" / "upgrades"
            target_root = root / "data" / "smartx-storage-forecast" / "upgrades"
            context = ActionContext.minimal(root)
            context.data_path = root / "data"
            context.upgrades_path = source_root
            context.host_upgrades_path = None
            context.task_id = "upgrade-v052"

            for task_id, kind in [
                ("upgrade-v051u2", "platform"),
                ("upgrade-runner-v031", "component"),
                ("upgrade-v052", "platform"),
            ]:
                task_dir = source_root / task_id
                task_dir.mkdir(parents=True)
                (task_dir / "task.json").write_text(json.dumps({"task_id": task_id, "kind": kind}), encoding="utf-8")
            ignored = source_root / "not-a-task"
            ignored.mkdir(parents=True)
            (ignored / "README.txt").write_text("ignore", encoding="utf-8")

            result = task_migrate_runtime_state(
                {"params": {"target_upgrades_path": str(target_root)}},
                context.as_dict(),
            )

            self.assertEqual(Path(result["mirror_task_dir"]), target_root / "upgrade-v052")
            self.assertTrue((target_root / "upgrade-v051u2" / "task.json").is_file())
            self.assertTrue((target_root / "upgrade-runner-v031" / "task.json").is_file())
            self.assertTrue((target_root / "upgrade-v052" / "task.json").is_file())
            self.assertFalse((target_root / "not-a-task").exists())

    def test_task_sync_runtime_state_uses_manifest_absolute_target_without_legacy_data_mapping(self) -> None:
        from app.upgrade_runner.actions import ActionContext, task_sync_runtime_state

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target_root = root / "data" / "smartx-storage-forecast" / "upgrades"
            task_dir = target_root / "upgrade-1"
            task_dir.mkdir(parents=True)
            (task_dir / "task.json").write_text('{"task_id":"upgrade-1"}', encoding="utf-8")
            context = ActionContext.minimal(root)
            context.data_path = root / "data"
            context.host_data_path = root / "data" / "smartx-capacity-insight-data" / "app"
            context.host_upgrades_path = None
            context.task_id = "upgrade-1"

            result = task_sync_runtime_state(
                {"params": {"target_upgrades_path": str(target_root)}},
                context.as_dict(),
            )

            self.assertEqual(result["task_file"], str(task_dir / "task.json"))

    def test_runner_handoff_target_runtime_writes_target_compose_and_recreates_runner(self) -> None:
        from app.upgrade_runner.actions import ActionContext, runner_handoff_target_runtime

        class Executor:
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def run(self, command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
                self.commands.append(command)

            def output(self, command: list[str], *, cwd: Path | None = None) -> str:
                self.commands.append(command)
                return ""

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            context = ActionContext.minimal(root, executor=Executor())
            context.host_project_path = root / "target" / "project"
            context.host_data_path = root / "target" / "app"
            context.host_upgrades_path = root / "target" / "upgrades"
            context.host_backups_path = root / "target" / "backups"
            context.host_compose_runtime_path = root / "target" / "compose-runtime"
            context.host_prometheus_path = root / "target" / "prometheus"

            result = runner_handoff_target_runtime(
                {
                    "params": {
                        "image": "repo/upgrade-runner:v0.3.1",
                        "compose_project": "smartx-hci-capacity-insight",
                        "network_name": "smartx-hci-capacity-insight-net",
                        "subnet": "10.249.251.0/24",
                    }
                },
                context.as_dict(),
            )

            compose_path = context.host_compose_runtime_path / "docker-compose.runner-upgrade.yml"
            content = compose_path.read_text(encoding="utf-8")
            self.assertIn("repo/upgrade-runner:v0.3.1", content)
            self.assertIn(f"- {context.host_upgrades_path}:/data/upgrades", content)
            self.assertIn(f"SMARTX_HOST_UPGRADES_PATH: {context.host_upgrades_path}", content)
            self.assertTrue(any("--project-name" in command and "smartx-hci-capacity-insight" in command for command in context.executor.commands))
            self.assertEqual(result["compose_file"], str(compose_path))

    def test_runner_schedule_target_runtime_handoff_launches_helper_after_parent_success(self) -> None:
        from app.upgrade_runner.actions import ActionContext, runner_schedule_target_runtime_handoff

        class Executor:
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def run(self, command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
                self.commands.append(command)

            def output(self, command: list[str], *, cwd: Path | None = None) -> str:
                self.commands.append(command)
                return ""

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target_root = root / "data" / "smartx-storage-forecast"
            target_task_dir = target_root / "upgrades" / "upgrade-1"
            target_task_dir.mkdir(parents=True)
            (target_task_dir / "task.json").write_text('{"task_id":"upgrade-1","status":"running"}', encoding="utf-8")
            context = ActionContext.minimal(root, executor=Executor())
            context.task_id = "upgrade-1"

            result = runner_schedule_target_runtime_handoff(
                {
                    "params": {
                        "image": "repo/upgrade-runner:v0.3.1",
                        "compose_project": "smartx-hci-capacity-insight",
                        "network_name": "smartx-hci-capacity-insight-net",
                        "project_path": str(target_root / "project"),
                        "app_data_path": str(target_root / "app"),
                        "upgrades_path": str(target_root / "upgrades"),
                        "backups_path": str(target_root / "backups"),
                        "exports_path": str(target_root / "exports"),
                        "compose_runtime_path": str(target_root / "compose-runtime"),
                        "prometheus_data_path": str(target_root / "prometheus"),
                    }
                },
                {**context.as_dict(), "task_mirror_dir": str(target_task_dir)},
            )

            compose_path = target_root / "compose-runtime" / "docker-compose.runner-upgrade.yml"
            compose_text = compose_path.read_text(encoding="utf-8")
            self.assertIn("repo/upgrade-runner:v0.3.1", compose_text)
            self.assertIn(f"SMARTX_PROJECT_PATH: {target_root / 'project'}", compose_text)
            self.assertIn(f"SMARTX_HOST_UPGRADES_PATH: {target_root / 'upgrades'}", compose_text)
            self.assertIn(f"- {target_root / 'upgrades'}:/data/upgrades", compose_text)
            self.assertNotIn("/data/upgrades:/data/upgrades", compose_text)

            docker_run = next(command for command in context.executor.commands if command[:3] == ["docker", "run", "-d"])
            self.assertIn("smartx-runner-cutover-upgrade-1", docker_run)
            self.assertIn(f"{target_task_dir}:/runner-cutover/task:ro", docker_run)
            self.assertIn(f"{target_root / 'compose-runtime'}:/runner-cutover/runtime:ro", docker_run)
            self.assertIn("repo/upgrade-runner:v0.3.1", docker_run)
            self.assertEqual(result["helper_container"], "smartx-runner-cutover-upgrade-1")
            self.assertEqual(result["compose_file"], str(compose_path))

    def test_runner_stop_legacy_runtime_removes_only_old_runner_after_handoff(self) -> None:
        from app.upgrade_runner.actions import ActionContext, runner_stop_legacy_runtime

        class Executor:
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def output(self, command: list[str], *, cwd: Path | None = None) -> str:
                self.commands.append(command)
                if command == ["docker", "inspect", "smartx-storage-forecast-upgrade-runner-1"]:
                    return json.dumps(
                        [
                            {
                                "Id": "old-runner-id",
                                "Name": "/smartx-storage-forecast-upgrade-runner-1",
                                "State": {"Status": "running", "Running": True},
                                "Config": {
                                    "Labels": {
                                        "com.docker.compose.project": "smartx-storage-forecast",
                                        "com.docker.compose.service": "upgrade-runner",
                                    }
                                },
                            }
                        ]
                    )
                raise AssertionError(f"unexpected output command: {command}")

            def run(self, command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
                self.commands.append(command)

        executor = Executor()
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ActionContext.minimal(Path(tmpdir), executor=executor)
            context.current_container_id = "new-runner-id"

            result = runner_stop_legacy_runtime(
                {
                    "params": {
                        "legacy_project": "smartx-storage-forecast",
                        "legacy_runner_container": "smartx-storage-forecast-upgrade-runner-1",
                        "target_project": "smartx-hci-capacity-insight",
                    }
                },
                context.as_dict(),
            )

        self.assertEqual(result["container"], "smartx-storage-forecast-upgrade-runner-1")
        self.assertEqual(result["container_id"], "old-runner-id")
        self.assertEqual(result["status"], "removed")
        self.assertTrue(result["stopped"])
        self.assertTrue(result["removed"])
        self.assertIn(["docker", "stop", "old-runner-id"], executor.commands)
        self.assertIn(["docker", "rm", "old-runner-id"], executor.commands)

    def test_runner_stop_legacy_runtime_refuses_current_container(self) -> None:
        from app.upgrade_runner.actions import ActionContext, runner_stop_legacy_runtime

        class Executor:
            def output(self, command: list[str], *, cwd: Path | None = None) -> str:
                return json.dumps(
                    [
                        {
                            "Id": "current-runner-id",
                            "Name": "/smartx-storage-forecast-upgrade-runner-1",
                            "State": {"Status": "running", "Running": True},
                            "Config": {
                                "Labels": {
                                    "com.docker.compose.project": "smartx-storage-forecast",
                                    "com.docker.compose.service": "upgrade-runner",
                                }
                            },
                        }
                    ]
                )

            def run(self, command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
                raise AssertionError("current runner must not be removed")

        with tempfile.TemporaryDirectory() as tmpdir:
            context = ActionContext.minimal(Path(tmpdir), executor=Executor())
            context.current_container_id = "current-runner-id"

            with self.assertRaisesRegex(RuntimeError, "不允许停止当前 runner"):
                runner_stop_legacy_runtime(
                    {
                        "params": {
                            "legacy_project": "smartx-storage-forecast",
                            "legacy_runner_container": "smartx-storage-forecast-upgrade-runner-1",
                            "target_project": "smartx-hci-capacity-insight",
                        }
                    },
                    context.as_dict(),
                )

    def test_legacy_cleanup_rejects_when_current_runner_still_mounts_legacy_paths(self) -> None:
        from app.upgrade_runner.actions import ActionContext, legacy_cleanup

        class Executor:
            def output(self, command: list[str], *, cwd: Path | None = None) -> str:
                if command[:2] == ["docker", "inspect"]:
                    return json.dumps(
                        [
                            {
                                "Mounts": [
                                    {"Source": "/opt/smartx-storage-forecast", "Destination": "/opt/smartx-storage-forecast"},
                                ]
                            }
                        ]
                    )
                return ""

            def run(self, command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
                return None

        with tempfile.TemporaryDirectory() as tmpdir:
            context = ActionContext.minimal(Path(tmpdir), executor=Executor())
            context.current_container_id = "runner-container"

            with self.assertRaisesRegex(RuntimeError, "当前 runner 仍挂载待清理旧路径，必须先完成 runner handoff：/opt/smartx-storage-forecast"):
                legacy_cleanup(
                    {
                        "params": {
                            "legacy_projects": [],
                            "legacy_networks": [],
                            "legacy_paths": [str(Path(tmpdir) / "legacy")],
                            "target_app_residual_paths": [],
                            "protected_paths": [str(Path(tmpdir) / "target")],
                        }
                    },
                    context.as_dict(),
                )

    def test_filesystem_cleanup_legacy_paths_uses_host_helper_without_deleting_current_mount(self) -> None:
        from app.upgrade_runner.actions import ActionContext, filesystem_cleanup_legacy_paths

        class Executor:
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def output(self, command: list[str], *, cwd: Path | None = None) -> str:
                self.commands.append(command)
                if command[:3] == ["docker", "run", "--rm"]:
                    return json.dumps([{"path": str(legacy_container_mount), "status": "deleted"}])
                raise AssertionError(f"unexpected output command: {command}")

            def run(self, command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
                self.commands.append(command)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy_container_mount = root / "data" / "upgrades"
            target_host_upgrades = root / "data" / "smartx-storage-forecast" / "upgrades"
            legacy_container_mount.mkdir(parents=True)
            target_host_upgrades.mkdir(parents=True)
            marker = legacy_container_mount / "target-task.json"
            marker.write_text("must survive; this is the current runner mount", encoding="utf-8")
            executor = Executor()
            context = ActionContext.minimal(root, executor=executor)
            context.upgrades_path = legacy_container_mount
            context.host_upgrades_path = target_host_upgrades

            result = filesystem_cleanup_legacy_paths(
                {
                    "params": {
                        "paths": [str(legacy_container_mount)],
                        "protected_paths": [str(root / "data" / "smartx-storage-forecast")],
                        "helper_image": "repo/web-api:v0.5.2",
                    }
                },
                context.as_dict(),
            )

            self.assertTrue(marker.exists())
            docker_run = next(command for command in executor.commands if command[:3] == ["docker", "run", "--rm"])
            self.assertIn("-v", docker_run)
            self.assertIn("/:/host", " ".join(docker_run))
            self.assertIn("repo/web-api:v0.5.2", docker_run)
            self.assertEqual(result["paths"], [{"path": str(legacy_container_mount), "status": "deleted"}])

    def test_filesystem_cleanup_target_residuals_skips_active_target_mountpoints(self) -> None:
        from app.upgrade_runner.actions import ActionContext, filesystem_cleanup_target_app_residuals

        class Executor:
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def output(self, command: list[str], *, cwd: Path | None = None) -> str:
                self.commands.append(command)
                raise AssertionError("active target mountpoints must be skipped before helper cleanup")

            def run(self, command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
                self.commands.append(command)
                raise AssertionError("active target mountpoints must not be removed directly")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            host_data = root / "data" / "smartx-storage-forecast" / "app"
            host_upgrades = root / "data" / "smartx-storage-forecast" / "upgrades"
            mountpoint = host_data / "upgrades"
            mountpoint.mkdir(parents=True)
            host_upgrades.mkdir(parents=True)
            marker = mountpoint / "mountpoint-marker"
            marker.write_text("keep", encoding="utf-8")
            executor = Executor()
            context = ActionContext.minimal(root, executor=executor)
            context.host_data_path = host_data
            context.host_upgrades_path = host_upgrades
            context.upgrades_path = Path("/data/upgrades")

            result = filesystem_cleanup_target_app_residuals(
                {
                    "params": {
                        "paths": [str(mountpoint)],
                        "protected_paths": [str(root / "data" / "smartx-storage-forecast")],
                        "helper_image": "repo/web-api:v0.5.2",
                    }
                },
                context.as_dict(),
            )

            self.assertTrue(marker.exists())
            self.assertEqual(executor.commands, [])
            self.assertEqual(result["paths"], [{"path": str(mountpoint), "status": "skipped", "reason": "active target mountpoint"}])

    def test_runner_projects_action_progress_while_task_is_running(self) -> None:
        from app.upgrade_runner.main import RunnerSettings, run_pending_once
        from app.upgrade_runner.store import TaskStore
        from app.v2.config import V2Settings
        from app.v2.database import V2Database

        observed_steps: list[list[dict]] = []

        def backup(_action, _context):
            return {"ok": True}

        def load_image(_action, context):
            database_path = Path(context["database_path"])
            with sqlite3.connect(database_path) as connection:
                row = connection.execute("SELECT progress, steps_json FROM tasks WHERE id = 'upgrade-1'").fetchone()
            self.assertIsNotNone(row)
            observed_steps.append(json.loads(row[1]))
            return {"ok": True}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            v2_settings = V2Settings(data_root=root, secret_key="runner-progress")
            V2Database(v2_settings).initialize()
            task_dir = root / "upgrades" / "upgrade-1"
            TaskStore(task_dir).save(
                self._task(
                    [
                        {"id": "backup", "type": "backup.create", "status": "pending", "checkpoint": {}, "result": {}},
                        {"id": "load-image-1", "type": "image.load", "status": "pending", "checkpoint": {}, "result": {}},
                    ]
                )
                | {"package_path": str(root / "package")}
            )
            settings = RunnerSettings(
                database_path=v2_settings.sqlite_path,
                upgrades_path=root / "upgrades",
                data_path=root,
                exports_path=root / "exports",
                backups_path=root / "backups",
                compose_runtime_path=root / "runtime",
                prometheus_path=root / "prometheus",
                project_path=root / "project",
                compose_file="docker-compose.offline.yml",
                compose_project="test",
            )

            run_pending_once(settings, handlers={"backup.create": backup, "image.load": load_image}, owner="runner-a")

            self.assertEqual(observed_steps[0][0]["status"], "succeeded")
            self.assertEqual(observed_steps[0][1]["status"], "running")

    def test_interrupted_sandbox_action_requires_operator_recovery(self) -> None:
        from app.upgrade_runner.engine import UpgradeEngine
        from app.upgrade_runner.store import TaskStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = TaskStore(Path(tmpdir) / "upgrade-1")
            store.save(
                self._task(
                    [
                        {
                            "id": "migration",
                            "type": "script.run_sandboxed",
                            "status": "running",
                            "attempt": 1,
                            "params": {"completion_marker": None},
                            "checkpoint": {"started": True},
                            "result": {},
                        }
                    ]
                )
            )
            result = UpgradeEngine(store, handlers={}).run()

            self.assertEqual(result["status"], "recovery_required")
            self.assertEqual(result["recovery_status"], "recovery_required")
            self.assertEqual(result["available_recovery_actions"], ["continue", "rollback", "fail"])

    def test_health_failure_triggers_single_automatic_rollback(self) -> None:
        from app.upgrade_runner.engine import UpgradeEngine
        from app.upgrade_runner.store import TaskStore

        rollback_calls: list[dict] = []
        health_calls = 0

        def fail_health(_action, _context):
            nonlocal health_calls
            health_calls += 1
            if health_calls == 1:
                raise RuntimeError("health failed")
            return {"checkpoint": {"healthy": True}}

        def rollback(action, _context):
            rollback_calls.append(action)
            return {"checkpoint": {"restored": True}}

        with tempfile.TemporaryDirectory() as tmpdir:
            store = TaskStore(Path(tmpdir) / "upgrade-1")
            store.save(
                self._task(
                    [
                        {
                            "id": "sync",
                            "type": "files.sync",
                            "status": "succeeded",
                            "attempt": 1,
                            "checkpoint": {},
                            "result": {
                                "backup_path": "/backup/project",
                                "checkpoint": {
                                    "files": [
                                        {"path": "new.conf", "backup": None},
                                    ]
                                },
                            },
                        },
                        {
                            "id": "override",
                            "type": "compose.override",
                            "status": "succeeded",
                            "attempt": 1,
                            "checkpoint": {},
                            "result": {"path": "/runtime/override.yml"},
                        },
                        {
                            "id": "apply",
                            "type": "compose.apply",
                            "status": "succeeded",
                            "attempt": 1,
                            "checkpoint": {},
                            "result": {"services": ["web-api", "frontend"]},
                        },
                        {
                            "id": "health",
                            "type": "health.http",
                            "status": "pending",
                            "attempt": 0,
                            "checkpoint": {},
                            "result": {},
                        },
                    ]
                )
            )
            result = UpgradeEngine(
                store,
                handlers={"health.http": fail_health, "rollback.restore": rollback},
            ).run()

            self.assertEqual(result["status"], "rolled_back")
            self.assertEqual(result["rollback_attempts"], 1)
            self.assertEqual(health_calls, 2)
            self.assertEqual(len(rollback_calls), 1)
            self.assertEqual(rollback_calls[0]["params"]["project_backup_path"], "/backup/project")
            self.assertEqual(rollback_calls[0]["params"]["project_files"], [{"path": "new.conf", "backup": None}])
            self.assertEqual(rollback_calls[0]["params"]["services"], ["web-api", "frontend"])

    def test_automatic_rollback_requires_post_rollback_health_check(self) -> None:
        from app.upgrade_runner.engine import UpgradeEngine
        from app.upgrade_runner.store import TaskStore

        rollback_calls = 0

        def fail_health(_action, _context):
            raise RuntimeError("still unhealthy")

        def rollback(_action, _context):
            nonlocal rollback_calls
            rollback_calls += 1
            return {"checkpoint": {"restored": True}}

        with tempfile.TemporaryDirectory() as tmpdir:
            store = TaskStore(Path(tmpdir) / "upgrade-1")
            store.save(
                self._task(
                    [
                        {
                            "id": "health",
                            "type": "health.http",
                            "status": "pending",
                            "attempt": 0,
                            "checkpoint": {},
                            "result": {},
                        }
                    ]
                )
            )
            result = UpgradeEngine(
                store,
                handlers={"health.http": fail_health, "rollback.restore": rollback},
            ).run()

            self.assertEqual(result["status"], "rollback_failed")
            self.assertEqual(result["recovery_status"], "recovery_required")
            self.assertEqual(result["rollback_attempts"], 1)
            self.assertEqual(rollback_calls, 1)


class UpgradeActionTest(unittest.TestCase):
    def test_backup_create_uses_consistent_sqlite_snapshot_with_wal_data(self) -> None:
        from app.upgrade_runner.actions import ActionContext, backup_create

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            context = ActionContext.minimal(root)
            connection = sqlite3.connect(context.data_path / "smartx.db")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA wal_autocheckpoint=0")
            connection.execute("CREATE TABLE sample (value TEXT)")
            connection.execute("INSERT INTO sample VALUES ('from-wal')")
            connection.commit()

            result = backup_create({"params": {"scope": "platform"}}, context.as_dict())
            extracted = root / "extracted"
            extracted.mkdir()
            with tarfile.open(result["path"], mode="r:gz") as archive:
                _safe_extract_for_test(archive, extracted)
            with sqlite3.connect(extracted / "app" / "smartx.db") as backup:
                value = backup.execute("SELECT value FROM sample").fetchone()[0]
            connection.close()

            self.assertEqual(value, "from-wal")

    def test_image_load_validates_sha_before_running_docker(self) -> None:
        from app.upgrade_runner.actions import ActionContext, CommandExecutor, image_load

        class FakeExecutor(CommandExecutor):
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def run(self, command, *, cwd=None, timeout=None):
                self.commands.append(command)

        with tempfile.TemporaryDirectory() as tmpdir:
            package = Path(tmpdir) / "package"
            package.mkdir()
            archive = package / "image.tar"
            archive.write_bytes(b"image")
            executor = FakeExecutor()
            context = ActionContext.minimal(Path(tmpdir), executor=executor, package_path=package)
            result = image_load(
                {
                    "params": {
                        "archive": "image.tar",
                        "sha256": hashlib.sha256(b"image").hexdigest(),
                        "image": "repo/image:v1",
                    }
                },
                context.as_dict(),
            )

            self.assertEqual(executor.commands, [["docker", "load", "-i", str(archive)]])
            self.assertEqual(result["checkpoint"]["sha256"], hashlib.sha256(b"image").hexdigest())

    def test_files_sync_records_each_file_and_rejects_unlisted_paths(self) -> None:
        from app.upgrade_runner.actions import ActionContext, files_sync

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = root / "package"
            project = root / "project"
            (package / "project").mkdir(parents=True)
            (package / "project" / "docker-compose.offline.yml").write_text("new", encoding="utf-8")
            project.mkdir()
            (project / "docker-compose.offline.yml").write_text("old", encoding="utf-8")
            context = ActionContext.minimal(root, package_path=package, project_path=project)

            result = files_sync(
                {
                    "params": {"source": "project", "files": ["docker-compose.offline.yml"]},
                    "checkpoint": {},
                },
                context.as_dict(),
            )
            self.assertEqual((project / "docker-compose.offline.yml").read_text(encoding="utf-8"), "new")
            self.assertEqual(result["checkpoint"]["files"][0]["path"], "docker-compose.offline.yml")

            with self.assertRaisesRegex(ValueError, "白名单"):
                files_sync(
                    {"params": {"source": "project", "files": ["../.env"]}, "checkpoint": {}},
                    context.as_dict(),
                )

    def test_files_sync_can_target_project_subdirectory(self) -> None:
        from app.upgrade_runner.actions import ActionContext, files_sync

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            context = ActionContext.minimal(root)
            source = context.package_path / "config"
            source.mkdir(parents=True)
            (source / "prometheus.yml").write_text("global:\n  scrape_interval: 15s\n", encoding="utf-8")

            result = files_sync(
                {
                    "id": "sync-prometheus-config",
                    "type": "files.sync",
                    "params": {"source": "config", "target": "prometheus", "files": ["prometheus.yml"]},
                    "checkpoint": {},
                },
                context.as_dict(),
            )

            self.assertEqual((context.project_path / "prometheus" / "prometheus.yml").read_text(encoding="utf-8"), "global:\n  scrape_interval: 15s\n")
            self.assertEqual(result["checkpoint"]["files"][0]["path"], "prometheus/prometheus.yml")

    def test_files_sync_replaces_stale_directory_when_package_path_is_file(self) -> None:
        from app.upgrade_runner.actions import ActionContext, files_sync

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            context = ActionContext.minimal(root)
            source = context.package_path / "project" / "prometheus"
            source.mkdir(parents=True)
            (source / "prometheus.yml").write_text("global:\n  scrape_interval: 15s\n", encoding="utf-8")
            stale_directory = context.project_path / "prometheus" / "prometheus.yml"
            stale_directory.mkdir(parents=True)
            (stale_directory / "leftover").write_text("created by bind mount", encoding="utf-8")

            result = files_sync(
                {
                    "id": "sync-project-files",
                    "type": "files.sync",
                    "params": {"source": "project", "files": ["prometheus/prometheus.yml"]},
                    "checkpoint": {},
                },
                context.as_dict(),
            )

            self.assertTrue((context.project_path / "prometheus" / "prometheus.yml").is_file())
            self.assertEqual((context.project_path / "prometheus" / "prometheus.yml").read_text(encoding="utf-8"), "global:\n  scrape_interval: 15s\n")
            backup = Path(result["checkpoint"]["files"][0]["backup"])
            self.assertTrue((backup / "leftover").is_file())

    def test_filesystem_prepare_creates_single_root_layout_and_copies_legacy_data(self) -> None:
        from app.upgrade_runner.actions import ActionContext, filesystem_prepare

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy_app = root / "legacy-app"
            legacy_prometheus = root / "legacy-prometheus"
            legacy_app.mkdir()
            legacy_prometheus.mkdir()
            (legacy_app / "smartx.db").write_text("legacy-db", encoding="utf-8")
            (legacy_app / "upgrade-runner.version").write_text("v0.3.1", encoding="utf-8")
            (legacy_prometheus / "01ABC" / "chunks").mkdir(parents=True)
            (legacy_prometheus / "01ABC" / "meta.json").write_text("{}", encoding="utf-8")
            context = ActionContext.minimal(root)

            result = filesystem_prepare(
                {
                    "params": {
                        "target_root": str(root / "target"),
                        "project_path": str(context.project_path),
                        "app_data_path": str(context.data_path),
                        "prometheus_data_path": str(context.prometheus_path),
                        "upgrades_path": str(root / "upgrades"),
                        "backups_path": str(context.backups_path),
                        "exports_path": str(root / "exports"),
                        "compose_runtime_path": str(context.compose_runtime_path),
                        "legacy_app_data_paths": [str(legacy_app)],
                        "legacy_prometheus_data_paths": [str(legacy_prometheus)],
                    }
                },
                context.as_dict(),
            )

            self.assertEqual((context.data_path / "smartx.db").read_text(encoding="utf-8"), "legacy-db")
            self.assertEqual((context.data_path / "upgrade-runner.version").read_text(encoding="utf-8"), "v0.3.1")
            self.assertEqual((context.prometheus_path / "01ABC" / "meta.json").read_text(encoding="utf-8"), "{}")
            self.assertTrue((root / "upgrades").is_dir())
            self.assertTrue((root / "exports").is_dir())
            self.assertTrue(result["checkpoint"]["completed"])
            self.assertIn(str(legacy_app), result["copied_app_sources"])
            self.assertIn(str(legacy_prometheus), result["copied_prometheus_sources"])

    def test_filesystem_prepare_switches_context_and_keeps_packaged_prometheus_config(self) -> None:
        from app.upgrade_runner.actions import ActionContext, CommandExecutor, filesystem_prepare

        class Executor(CommandExecutor):
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def run(self, command, *, cwd=None, timeout=None):
                self.commands.append(command)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = root / "package"
            (package / "project" / "prometheus").mkdir(parents=True)
            (package / "project" / "prometheus" / "prometheus.yml").write_text("global: {}\n", encoding="utf-8")
            context = ActionContext.minimal(root, executor=Executor(), package_path=package)
            original_project_path = context.project_path
            original_compose_runtime_path = context.compose_runtime_path
            target_root = root / "target"

            result = filesystem_prepare(
                {
                    "params": {
                        "project_path": str(target_root / "project"),
                        "app_data_path": str(target_root / "app"),
                        "prometheus_data_path": str(target_root / "prometheus"),
                        "upgrades_path": str(target_root / "upgrades"),
                        "backups_path": str(target_root / "backups"),
                        "exports_path": str(target_root / "exports"),
                        "compose_runtime_path": str(target_root / "compose-runtime"),
                        "legacy_app_data_paths": [],
                        "legacy_prometheus_data_paths": [],
                        "helper_image": "helper:image",
                    }
                },
                context.as_dict(),
            )

            self.assertEqual(context.project_path, original_project_path)
            self.assertEqual(context.compose_runtime_path, original_compose_runtime_path)
            self.assertIn(str(package / "project"), result["copied_project_sources"])
            command = context.executor.commands[0]
            self.assertIn(f"{package / 'project'}:/from:ro", command)
            self.assertIn(f"{target_root / 'project'}:/to", command)
            self.assertIn("SMARTX_SKIP_NAMES=.env", command)
            self.assertNotIn("prometheus", next(value for value in command if value.startswith("SMARTX_SKIP_NAMES=")))

    def test_filesystem_prepare_does_not_overwrite_existing_target_data(self) -> None:
        from app.upgrade_runner.actions import ActionContext, filesystem_prepare

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy_app = root / "legacy-app"
            legacy_prometheus = root / "legacy-prometheus"
            legacy_app.mkdir()
            legacy_prometheus.mkdir()
            (legacy_app / "smartx.db").write_text("legacy-db", encoding="utf-8")
            (legacy_prometheus / "01ABC").mkdir()
            (legacy_prometheus / "01ABC" / "meta.json").write_text("legacy", encoding="utf-8")
            context = ActionContext.minimal(root)
            (context.data_path / "smartx.db").write_text("target-db", encoding="utf-8")
            (context.prometheus_path / "01ABC").mkdir()
            (context.prometheus_path / "01ABC" / "meta.json").write_text("target", encoding="utf-8")

            result = filesystem_prepare(
                {
                    "params": {
                        "app_data_path": str(context.data_path),
                        "prometheus_data_path": str(context.prometheus_path),
                        "legacy_app_data_paths": [str(legacy_app)],
                        "legacy_prometheus_data_paths": [str(legacy_prometheus)],
                    }
                },
                context.as_dict(),
            )

            self.assertEqual((context.data_path / "smartx.db").read_text(encoding="utf-8"), "target-db")
            self.assertEqual((context.prometheus_path / "01ABC" / "meta.json").read_text(encoding="utf-8"), "target")
            self.assertEqual(result["copied_app_sources"], [])
            self.assertEqual(result["copied_prometheus_sources"], [])

    def test_filesystem_prepare_replaces_empty_target_db_with_legacy_business_db(self) -> None:
        from app.upgrade_runner.actions import ActionContext, filesystem_prepare

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy_app = root / "legacy-app"
            context = ActionContext.minimal(root)
            _write_upgrade_business_db(
                legacy_app / "smartx.db",
                towers=1,
                clusters=1,
                vm_latest=2,
                vm_volumes=3,
                collection_runs=4,
            )
            _write_upgrade_business_db(context.data_path / "smartx.db", collection_runs=1)

            result = filesystem_prepare(
                {
                    "params": {
                        "app_data_path": str(context.data_path),
                        "legacy_app_data_paths": [str(legacy_app)],
                    }
                },
                context.as_dict(),
            )

            self.assertEqual(
                _count_upgrade_business_db(context.data_path / "smartx.db"),
                {"users": 1, "towers": 1, "clusters": 1, "vm_latest": 2, "vm_volumes": 3, "collection_runs": 4},
            )
            backups = sorted(context.data_path.glob("smartx.db.pre-upg038-empty-target.*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(result["copied_app_sources"], [str(legacy_app)])
            self.assertTrue(result["replaced_empty_target_db"])
            self.assertEqual(result["target_db_counts_before"]["vm_latest"], 0)
            self.assertEqual(result["target_db_counts_after"]["vm_latest"], 2)

    def test_filesystem_prepare_fails_on_conflicting_business_databases(self) -> None:
        from app.upgrade_runner.actions import ActionContext, filesystem_prepare

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy_app = root / "legacy-app"
            context = ActionContext.minimal(root)
            _write_upgrade_business_db(legacy_app / "smartx.db", towers=1, clusters=1, vm_latest=2, vm_volumes=3)
            _write_upgrade_business_db(context.data_path / "smartx.db", towers=1, clusters=1, vm_latest=9, vm_volumes=3)

            with self.assertRaisesRegex(RuntimeError, "业务数据库冲突"):
                filesystem_prepare(
                    {
                        "params": {
                            "app_data_path": str(context.data_path),
                            "legacy_app_data_paths": [str(legacy_app)],
                        }
                    },
                    context.as_dict(),
                )

            self.assertEqual(_count_upgrade_business_db(context.data_path / "smartx.db")["vm_latest"], 9)

    def test_post_cleanup_verify_blocks_empty_target_after_legacy_business_data(self) -> None:
        from unittest import mock

        from app.upgrade_runner.actions import ActionContext, post_cleanup_verify

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "ok": True,
                        "version": "v0.5.2",
                        "runner_version": "v0.3.1",
                        "checks": {"directories": True, "database": True, "prometheus": True},
                    }
                ).encode("utf-8")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            context = ActionContext.minimal(root)
            legacy_app = root / "legacy-app"
            _write_upgrade_business_db(legacy_app / "smartx.db", towers=1, clusters=1, vm_latest=2, vm_volumes=3)
            _write_upgrade_business_db(context.data_path / "smartx.db", collection_runs=1)

            with mock.patch("app.upgrade_runner.actions.urllib.request.urlopen", return_value=Response()):
                with self.assertRaisesRegex(RuntimeError, "业务数据迁移校验失败"):
                    post_cleanup_verify(
                        {
                            "params": {
                                "health_url": "http://web-api:8000/api/system/health",
                                "required_health": {
                                    "version": "v0.5.2",
                                    "runner_version": "v0.3.1",
                                    "checks": ["directories", "database", "prometheus"],
                                },
                                "data_migration_guard": {
                                    "target_db_path": str(context.data_path / "smartx.db"),
                                    "legacy_db_paths": [str(legacy_app / "smartx.db")],
                                },
                            }
                        },
                        context.as_dict(),
                    )

    def test_post_cleanup_guard_maps_host_target_db_after_runner_handoff(self) -> None:
        from app.upgrade_runner.actions import ActionContext, post_cleanup_verify

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            context = ActionContext.minimal(root)
            host_target_app = root / "host" / "data" / "smartx-storage-forecast" / "app"
            context.host_data_path = host_target_app
            _write_upgrade_business_db(
                context.data_path / "smartx.db",
                towers=1,
                clusters=1,
                vm_latest=523,
                vm_volumes=89530,
                collection_runs=37,
            )

            result = post_cleanup_verify(
                {
                    "params": {
                        "data_migration_guard": {
                            "target_db_path": str(host_target_app / "smartx.db"),
                            "legacy_db_paths": [str(context.data_path / "smartx.db")],
                        },
                    }
                },
                context.as_dict(),
            )

            guard = result["data_migration_guard"]
            self.assertTrue(guard["configured"])
            self.assertFalse(guard["required"])
            self.assertEqual(guard["skipped_reason"], "legacy_sources_unavailable_after_handoff")
            self.assertEqual(guard["target_db_counts"]["path"], str(context.data_path / "smartx.db"))
            self.assertEqual(guard["target_db_counts"]["counts"]["vm_latest"], 523)
            self.assertEqual(guard["ignored_legacy_db_paths"][0]["reason"], "same_as_target_after_handoff")

    def test_post_cleanup_guard_allows_empty_target_when_parent_source_was_empty(self) -> None:
        from app.upgrade_runner.actions import ActionContext, post_cleanup_verify

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            context = ActionContext.minimal(root)
            context.task_id = "post-cleanup-upgrade-empty-source"
            host_target_app = root / "host" / "data" / "smartx-storage-forecast" / "app"
            context.host_data_path = host_target_app
            parent_task_id = "upgrade-empty-source"
            _write_upgrade_business_db(context.data_path / "smartx.db")
            parent_task_dir = context.upgrades_path / parent_task_id
            parent_task_dir.mkdir(parents=True)
            (parent_task_dir / "task.json").write_text(
                json.dumps(
                    {
                        "task_id": parent_task_id,
                        "execution_plan": {
                            "actions": [
                                {
                                    "type": "filesystem.prepare",
                                    "status": "succeeded",
                                    "checkpoint": {
                                        "source_db_counts": {
                                            "users": 1,
                                            "towers": 0,
                                            "clusters": 0,
                                            "vm_latest": 0,
                                            "vm_volumes": 0,
                                            "collection_runs": 0,
                                        },
                                        "target_db_counts_after": {
                                            "users": 1,
                                            "towers": 0,
                                            "clusters": 0,
                                            "vm_latest": 0,
                                            "vm_volumes": 0,
                                            "collection_runs": 0,
                                        },
                                    },
                                }
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = post_cleanup_verify(
                {
                    "params": {
                        "parent_task_id": parent_task_id,
                        "data_migration_guard": {
                            "target_db_path": str(host_target_app / "smartx.db"),
                            "legacy_db_paths": [str(context.data_path / "smartx.db")],
                        },
                    }
                },
                context.as_dict(),
            )

            guard = result["data_migration_guard"]
            self.assertTrue(guard["configured"])
            self.assertFalse(guard["required"])
            self.assertEqual(guard["skipped_reason"], "parent_source_had_no_business_data")
            self.assertEqual(guard["parent_migration_checkpoint"]["source_db_counts"]["towers"], 0)
            self.assertEqual(guard["ignored_legacy_db_paths"][0]["reason"], "same_as_target_after_handoff")

    def test_post_cleanup_guard_still_fails_when_readable_legacy_has_more_business_rows(self) -> None:
        from app.upgrade_runner.actions import ActionContext, post_cleanup_verify

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            context = ActionContext.minimal(root)
            host_target_app = root / "host" / "data" / "smartx-storage-forecast" / "app"
            legacy_app = root / "legacy" / "app"
            context.host_data_path = host_target_app
            _write_upgrade_business_db(context.data_path / "smartx.db", towers=1, clusters=1, vm_latest=2, vm_volumes=3)
            _write_upgrade_business_db(legacy_app / "smartx.db", towers=1, clusters=1, vm_latest=9, vm_volumes=3)

            with self.assertRaisesRegex(RuntimeError, "目标库业务计数小于旧业务库"):
                post_cleanup_verify(
                    {
                        "params": {
                            "data_migration_guard": {
                                "target_db_path": str(host_target_app / "smartx.db"),
                                "legacy_db_paths": [str(legacy_app / "smartx.db")],
                            },
                        }
                    },
                    context.as_dict(),
                )

    def test_filesystem_prepare_creates_host_target_before_helper_copy(self) -> None:
        from app.upgrade_runner.actions import ActionContext, CommandExecutor, filesystem_prepare

        class Executor(CommandExecutor):
            def __init__(self, expected_target: Path) -> None:
                self.expected_target = expected_target
                self.commands: list[list[str]] = []

            def run(self, command, *, cwd=None, timeout=None):
                self.commands.append(command)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "host" / "prometheus"
            context = ActionContext.minimal(root, executor=Executor(target))

            result = filesystem_prepare(
                {
                    "params": {
                        "prometheus_data_path": str(target),
                        "legacy_app_data_paths": [],
                        "legacy_prometheus_data_paths": [str(root / "missing-prometheus")],
                        "helper_image": "helper:image",
                    }
                },
                context.as_dict(),
            )

            self.assertEqual(result["copied_prometheus_sources"], [str(root / "missing-prometheus")])
            self.assertTrue(context.executor.commands)
            flattened = " ".join(context.executor.commands[0])
            self.assertIn(f"{target}:/to", flattened)

    def test_filesystem_prepare_migrates_legacy_env_file_to_target_project(self) -> None:
        from app.upgrade_runner.actions import ActionContext, filesystem_prepare

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy_project = root / "legacy-project"
            target_project = root / "target" / "project"
            legacy_project.mkdir()
            (legacy_project / ".env").write_text(
                "\n".join(
                    [
                        "SMARTX_SECRET_KEY=legacy-secret",
                        "SMARTX_CREDENTIAL_KEY=legacy-credential",
                        "SMARTX_ADMIN_USER=admin",
                        "SMARTX_IMAGE_TAG=v0.5.1u2",
                        "SMARTX_RUNNER_IMAGE_TAG=v0.3.0",
                        "SMARTX_APP_VERSION=v0.5.1u2",
                        "SMARTX_RUNNER_VERSION=v0.3.0",
                        "SMARTX_PROMETHEUS_URL=http://prometheus:9090",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            context = ActionContext.minimal(root)

            result = filesystem_prepare(
                {
                    "params": {
                        "project_path": str(target_project),
                        "env_file_migration": {
                            "target": str(target_project / ".env"),
                            "legacy_candidates": [str(legacy_project / ".env")],
                            "preserve_existing": True,
                            "sanitize_image_tags": True,
                        },
                    }
                },
                context.as_dict(),
            )

            env_text = (target_project / ".env").read_text(encoding="utf-8")
            self.assertIn("SMARTX_SECRET_KEY=legacy-secret", env_text)
            self.assertIn("SMARTX_CREDENTIAL_KEY=legacy-credential", env_text)
            self.assertIn("SMARTX_PROMETHEUS_URL=http://prometheus:9090", env_text)
            self.assertNotIn("SMARTX_IMAGE_TAG=", env_text)
            self.assertNotIn("SMARTX_RUNNER_IMAGE_TAG=", env_text)
            self.assertNotIn("SMARTX_APP_VERSION=", env_text)
            self.assertNotIn("SMARTX_RUNNER_VERSION=", env_text)
            self.assertEqual(result["env_file"]["status"], "copied")
            self.assertEqual(result["env_file"]["source"], str(legacy_project / ".env"))
            self.assertEqual((target_project / ".env").stat().st_mode & 0o777, 0o600)

    def test_filesystem_prepare_sanitizes_existing_target_env_without_overwriting_runtime_config(self) -> None:
        from app.upgrade_runner.actions import ActionContext, filesystem_prepare

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy_project = root / "legacy-project"
            target_project = root / "target" / "project"
            legacy_project.mkdir()
            target_project.mkdir(parents=True)
            (legacy_project / ".env").write_text("SMARTX_SECRET_KEY=legacy\n", encoding="utf-8")
            (target_project / ".env").write_text(
                "\n".join(
                    [
                        "SMARTX_SECRET_KEY=target",
                        "SMARTX_CREDENTIAL_KEY=target-credential",
                        "SMARTX_IMAGE_TAG=v0.5.1u2",
                        "SMARTX_RUNNER_IMAGE_TAG=v0.3.0",
                        "SMARTX_APP_VERSION=v0.5.1u2",
                        "SMARTX_RUNNER_VERSION=v0.3.0",
                        "SMARTX_PROMETHEUS_URL=http://prometheus:9090",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            context = ActionContext.minimal(root)

            result = filesystem_prepare(
                {
                    "params": {
                        "project_path": str(target_project),
                        "env_file_migration": {
                            "target": str(target_project / ".env"),
                            "legacy_candidates": [str(legacy_project / ".env")],
                            "preserve_existing": True,
                        },
                    }
                },
                context.as_dict(),
            )

            env_text = (target_project / ".env").read_text(encoding="utf-8")
            self.assertIn("SMARTX_SECRET_KEY=target", env_text)
            self.assertIn("SMARTX_CREDENTIAL_KEY=target-credential", env_text)
            self.assertIn("SMARTX_PROMETHEUS_URL=http://prometheus:9090", env_text)
            self.assertNotIn("SMARTX_IMAGE_TAG=", env_text)
            self.assertNotIn("SMARTX_RUNNER_IMAGE_TAG=", env_text)
            self.assertNotIn("SMARTX_APP_VERSION=", env_text)
            self.assertNotIn("SMARTX_RUNNER_VERSION=", env_text)
            self.assertEqual(result["env_file"]["status"], "sanitized_existing")

    def test_filesystem_prepare_uses_legacy_env_matching_migrated_tower_credentials(self) -> None:
        from app.upgrade_runner.actions import ActionContext, CommandExecutor, filesystem_prepare

        class CredentialExecutor(CommandExecutor):
            def __init__(self, compatible_env: Path) -> None:
                self.compatible_env = compatible_env
                self.validation_commands: list[list[str]] = []

            def run(self, command, *, cwd=None, timeout=None):
                return None

            def output(self, command, *, cwd=None):
                self.validation_commands.append(command)
                compatible_mount = f"{self.compatible_env}:/check/runtime.env:ro"
                return json.dumps(
                    {
                        "encrypted_credentials": 1,
                        "authenticated_credentials": 1,
                        "unauthenticated_credentials": 0,
                        "compatible": compatible_mount in command,
                    }
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy_project = root / "legacy-project"
            legacy_app = root / "legacy-app"
            target_project = root / "target" / "project"
            target_app = root / "target" / "app"
            legacy_project.mkdir()
            target_project.mkdir(parents=True)
            legacy_env = legacy_project / ".env"
            legacy_env.write_text(
                "SMARTX_SECRET_KEY=legacy-secret\nSMARTX_CREDENTIAL_KEY=legacy-credential\n",
                encoding="utf-8",
            )
            (target_project / ".env").write_text(
                "SMARTX_SECRET_KEY=stale-target\nSMARTX_CREDENTIAL_KEY=stale-target\n",
                encoding="utf-8",
            )
            _write_upgrade_credential_db(legacy_app / "smartx.db")
            executor = CredentialExecutor(legacy_env)
            context = ActionContext.minimal(root, executor=executor)

            result = filesystem_prepare(
                {
                    "params": {
                        "project_path": str(target_project),
                        "app_data_path": str(target_app),
                        "legacy_app_data_paths": [str(legacy_app)],
                        "legacy_prometheus_data_paths": [],
                        "helper_image": "helper:image",
                        "env_file_migration": {
                            "target": str(target_project / ".env"),
                            "legacy_candidates": [str(legacy_env)],
                            "preserve_existing": True,
                            "require_credential_decryption": True,
                        },
                    }
                },
                context.as_dict(),
            )

            self.assertEqual(result["env_file"]["status"], "copied")
            self.assertEqual(result["env_file"]["source"], str(legacy_env))
            self.assertTrue(result["env_file"]["credential_guard"]["compatible"])
            self.assertIn("SMARTX_SECRET_KEY=legacy-secret", (target_project / ".env").read_text(encoding="utf-8"))
            self.assertTrue(executor.validation_commands)

    def test_filesystem_prepare_keeps_target_root_database_on_same_host_path_for_credential_helper(self) -> None:
        from app.upgrade_runner.actions import ActionContext, CommandExecutor, filesystem_prepare

        class CredentialExecutor(CommandExecutor):
            def __init__(self) -> None:
                self.validation_commands: list[list[str]] = []

            def run(self, command, *, cwd=None, timeout=None):
                return None

            def output(self, command, *, cwd=None):
                self.validation_commands.append(command)
                return json.dumps(
                    {
                        "encrypted_credentials": 1,
                        "authenticated_credentials": 1,
                        "unauthenticated_credentials": 0,
                        "compatible": True,
                    }
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            context = ActionContext.minimal(root, executor=CredentialExecutor())
            context.host_data_path = root / "host-legacy-app"
            target_root = context.data_path / "smartx-storage-forecast"
            target_app = target_root / "app"
            target_project = target_root / "project"
            legacy_app = root / "legacy-app"
            legacy_project = root / "legacy-project"
            legacy_project.mkdir()
            legacy_env = legacy_project / ".env"
            legacy_env.write_text("SMARTX_SECRET_KEY=legacy-secret\n", encoding="utf-8")
            _write_upgrade_credential_db(legacy_app / "smartx.db")

            result = filesystem_prepare(
                {
                    "params": {
                        "target_root": str(target_root),
                        "project_path": str(target_project),
                        "app_data_path": str(target_app),
                        "legacy_app_data_paths": [str(legacy_app)],
                        "legacy_prometheus_data_paths": [],
                        "helper_image": "helper:image",
                        "env_file_migration": {
                            "target": str(target_project / ".env"),
                            "legacy_candidates": [str(legacy_env)],
                            "require_credential_decryption": True,
                        },
                    }
                },
                context.as_dict(),
            )

            expected_mount = f"{target_app / 'smartx.db'}:/check/smartx.db:ro"
            wrong_mount = f"{context.host_data_path / 'smartx-storage-forecast/app/smartx.db'}:/check/smartx.db:ro"
            flattened = [item for command in context.executor.validation_commands for item in command]
            self.assertIn(expected_mount, flattened)
            self.assertNotIn(wrong_mount, flattened)
            self.assertEqual(result["env_file"]["credential_guard"]["validation_mode"], "authenticated_decryption")

    def test_filesystem_prepare_preserves_legacy_env_for_unauthenticated_xor_credentials(self) -> None:
        from app.upgrade_runner.actions import ActionContext, CommandExecutor, filesystem_prepare

        class XorCredentialExecutor(CommandExecutor):
            def run(self, command, *, cwd=None, timeout=None):
                return None

            def output(self, command, *, cwd=None):
                return json.dumps(
                    {
                        "encrypted_credentials": 1,
                        "authenticated_credentials": 0,
                        "unauthenticated_credentials": 1,
                        "compatible": True,
                    }
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy_project = root / "legacy-project"
            legacy_app = root / "legacy-app"
            target_project = root / "target" / "project"
            target_app = root / "target" / "app"
            legacy_project.mkdir()
            target_project.mkdir(parents=True)
            legacy_env = legacy_project / ".env"
            legacy_env.write_text("SMARTX_SECRET_KEY=legacy-source-key\n", encoding="utf-8")
            (target_project / ".env").write_text("SMARTX_SECRET_KEY=stale-target-key\n", encoding="utf-8")
            _write_upgrade_credential_db(legacy_app / "smartx.db", encrypted_password="xor-ciphertext")
            context = ActionContext.minimal(root, executor=XorCredentialExecutor())

            result = filesystem_prepare(
                {
                    "params": {
                        "project_path": str(target_project),
                        "app_data_path": str(target_app),
                        "legacy_app_data_paths": [str(legacy_app)],
                        "legacy_prometheus_data_paths": [],
                        "helper_image": "helper:image",
                        "env_file_migration": {
                            "target": str(target_project / ".env"),
                            "legacy_candidates": [str(legacy_env)],
                            "require_credential_decryption": True,
                        },
                    }
                },
                context.as_dict(),
            )

            self.assertEqual(result["env_file"]["source"], str(legacy_env))
            self.assertEqual(result["env_file"]["credential_guard"].get("validation_mode"), "source_pair_preserved")
            self.assertIn("legacy-source-key", (target_project / ".env").read_text(encoding="utf-8"))

    def test_filesystem_prepare_rejects_target_env_false_positive_for_migrated_xor_credentials(self) -> None:
        from app.upgrade_runner.actions import ActionContext, CommandExecutor, filesystem_prepare

        class FalsePositiveExecutor(CommandExecutor):
            def run(self, command, *, cwd=None, timeout=None):
                return None

            def output(self, command, *, cwd=None):
                return json.dumps(
                    {
                        "encrypted_credentials": 1,
                        "authenticated_credentials": 0,
                        "unauthenticated_credentials": 1,
                        "compatible": True,
                    }
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy_app = root / "legacy-app"
            target_project = root / "target" / "project"
            target_app = root / "target" / "app"
            target_project.mkdir(parents=True)
            (target_project / ".env").write_text("SMARTX_SECRET_KEY=stale-target-key\n", encoding="utf-8")
            _write_upgrade_credential_db(legacy_app / "smartx.db", encrypted_password="xor-ciphertext")
            context = ActionContext.minimal(root, executor=FalsePositiveExecutor())

            with self.assertRaisesRegex(RuntimeError, r"XOR.*旧环境.*\.env"):
                filesystem_prepare(
                    {
                        "params": {
                            "project_path": str(target_project),
                            "app_data_path": str(target_app),
                            "legacy_app_data_paths": [str(legacy_app)],
                            "legacy_prometheus_data_paths": [],
                            "helper_image": "helper:image",
                            "env_file_migration": {
                                "target": str(target_project / ".env"),
                                "legacy_candidates": [str(root / "missing" / ".env")],
                                "require_credential_decryption": True,
                            },
                        }
                    },
                    context.as_dict(),
                )

    def test_filesystem_prepare_fails_closed_for_incomplete_tower_credential_schema(self) -> None:
        from app.upgrade_runner.actions import ActionContext, filesystem_prepare

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target_app = root / "target" / "app"
            target_project = root / "target" / "project"
            target_app.mkdir(parents=True)
            with sqlite3.connect(target_app / "smartx.db") as connection:
                connection.execute("CREATE TABLE towers (id INTEGER PRIMARY KEY, password_encrypted TEXT)")
                connection.execute("INSERT INTO towers (password_encrypted) VALUES ('ciphertext')")
            context = ActionContext.minimal(root)

            with self.assertRaisesRegex(RuntimeError, "Tower.*schema|Tower.*字段"):
                filesystem_prepare(
                    {
                        "params": {
                            "project_path": str(target_project),
                            "app_data_path": str(target_app),
                            "legacy_app_data_paths": [],
                            "legacy_prometheus_data_paths": [],
                            "env_file_migration": {
                                "target": str(target_project / ".env"),
                                "legacy_candidates": [],
                                "fallback_defaults": True,
                                "require_credential_decryption": True,
                            },
                        }
                    },
                    context.as_dict(),
                )

    def test_filesystem_prepare_fails_closed_when_credential_database_is_unreadable(self) -> None:
        from app.upgrade_runner.actions import ActionContext, filesystem_prepare

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target_app = root / "target" / "app"
            target_project = root / "target" / "project"
            target_app.mkdir(parents=True)
            (target_app / "smartx.db").write_bytes(b"not-a-sqlite-database")
            context = ActionContext.minimal(root)

            with self.assertRaisesRegex(RuntimeError, "Tower.*数据库|SQLite"):
                filesystem_prepare(
                    {
                        "params": {
                            "project_path": str(target_project),
                            "app_data_path": str(target_app),
                            "legacy_app_data_paths": [],
                            "legacy_prometheus_data_paths": [],
                            "env_file_migration": {
                                "target": str(target_project / ".env"),
                                "legacy_candidates": [],
                                "fallback_defaults": True,
                                "require_credential_decryption": True,
                            },
                        }
                    },
                    context.as_dict(),
                )

    def test_filesystem_prepare_rejects_encrypted_tower_credentials_without_matching_env(self) -> None:
        from app.upgrade_runner.actions import ActionContext, CommandExecutor, filesystem_prepare

        class IncompatibleCredentialExecutor(CommandExecutor):
            def run(self, command, *, cwd=None, timeout=None):
                return None

            def output(self, command, *, cwd=None):
                return json.dumps({"encrypted_credentials": 1, "compatible": False})

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy_app = root / "legacy-app"
            target_project = root / "target" / "project"
            target_app = root / "target" / "app"
            target_project.mkdir(parents=True)
            (target_project / ".env").write_text(
                "SMARTX_SECRET_KEY=stale-target\nSMARTX_CREDENTIAL_KEY=stale-target\n",
                encoding="utf-8",
            )
            _write_upgrade_credential_db(legacy_app / "smartx.db")
            context = ActionContext.minimal(root, executor=IncompatibleCredentialExecutor())

            with self.assertRaisesRegex(RuntimeError, "Tower.*凭据.*密钥"):
                filesystem_prepare(
                    {
                        "params": {
                            "project_path": str(target_project),
                            "app_data_path": str(target_app),
                            "legacy_app_data_paths": [str(legacy_app)],
                            "legacy_prometheus_data_paths": [],
                            "helper_image": "helper:image",
                            "env_file_migration": {
                                "target": str(target_project / ".env"),
                                "legacy_candidates": [str(root / "missing" / ".env")],
                                "preserve_existing": True,
                                "fallback_defaults": True,
                                "require_credential_decryption": True,
                            },
                        }
                    },
                    context.as_dict(),
                )

    @unittest.skipUnless(
        os.environ.get("SMARTX_RUN_DOCKER_CREDENTIAL_TEST") == "1",
        "set SMARTX_RUN_DOCKER_CREDENTIAL_TEST=1 to run the Docker credential guard integration test",
    )
    def test_credential_guard_uses_web_api_runtime_decryption(self) -> None:
        from app.upgrade_runner.actions import (
            ActionContext,
            _check_env_credential_compatibility,
        )

        helper_image = os.environ.get(
            "SMARTX_CREDENTIAL_HELPER_IMAGE",
            "nazawsze/smartx-hci-capacity-insight-web-api:v0.5.2",
        )
        fixture_script = """
import base64
import hashlib
import os
import sqlite3
from cryptography.fernet import Fernet

seed = os.environ["SMARTX_CREDENTIAL_KEY"]
key = base64.urlsafe_b64encode(hashlib.sha256(seed.encode("utf-8")).digest())
ciphertext = Fernet(key).encrypt(b"fixture-password").decode("ascii")
with sqlite3.connect("/fixture/smartx.db") as connection:
    connection.execute(
        "CREATE TABLE towers (id INTEGER PRIMARY KEY, password_encrypted TEXT, api_token_encrypted TEXT)"
    )
    connection.execute(
        "INSERT INTO towers (password_encrypted, api_token_encrypted) VALUES (?, NULL)",
        (ciphertext,),
    )
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            good_env = root / "good.env"
            bad_env = root / "bad.env"
            good_env.write_text(
                "SMARTX_SECRET_KEY=legacy-secret\nSMARTX_CREDENTIAL_KEY=legacy-credential\n",
                encoding="utf-8",
            )
            bad_env.write_text(
                "SMARTX_SECRET_KEY=wrong-secret\nSMARTX_CREDENTIAL_KEY=wrong-credential\n",
                encoding="utf-8",
            )
            context = ActionContext.minimal(root)
            context.executor.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network=none",
                    "-v",
                    f"{root}:/fixture",
                    "--env-file",
                    str(good_env),
                    "--entrypoint",
                    "python",
                    helper_image,
                    "-c",
                    fixture_script,
                ]
            )

            good = _check_env_credential_compatibility(
                database_path=root / "smartx.db",
                env_path=good_env,
                helper_image=helper_image,
                context=context,
            )
            bad = _check_env_credential_compatibility(
                database_path=root / "smartx.db",
                env_path=bad_env,
                helper_image=helper_image,
                context=context,
            )

            self.assertEqual(
                good,
                {
                    "encrypted_credentials": 1,
                    "authenticated_credentials": 1,
                    "unauthenticated_credentials": 0,
                    "compatible": True,
                },
            )
            self.assertEqual(
                bad,
                {
                    "encrypted_credentials": 1,
                    "authenticated_credentials": 1,
                    "unauthenticated_credentials": 0,
                    "compatible": False,
                },
            )

    def test_filesystem_prepare_creates_minimal_env_when_legacy_env_is_missing(self) -> None:
        from app.upgrade_runner.actions import ActionContext, filesystem_prepare

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target_project = root / "target" / "project"
            context = ActionContext.minimal(root)

            result = filesystem_prepare(
                {
                    "params": {
                        "project_path": str(target_project),
                        "env_file_migration": {
                            "target": str(target_project / ".env"),
                            "legacy_candidates": [str(root / "missing" / ".env")],
                            "preserve_existing": True,
                            "fallback_defaults": True,
                        },
                    }
                },
                context.as_dict(),
            )

            env_text = (target_project / ".env").read_text(encoding="utf-8")
            self.assertIn("SMARTX_SECRET_KEY=replace-with-a-long-random-secret", env_text)
            self.assertIn("SMARTX_CREDENTIAL_KEY=replace-with-a-different-long-random-secret", env_text)
            self.assertIn("SMARTX_DB_PATH=/data/smartx.db", env_text)
            self.assertEqual(result["env_file"]["status"], "created")

    def test_filesystem_prepare_fails_when_prometheus_chown_helper_fails(self) -> None:
        from app.upgrade_runner.actions import ActionContext, CommandExecutor, filesystem_prepare

        class FailingChownExecutor(CommandExecutor):
            def run(self, command, *, cwd=None, timeout=None):
                if "SMARTX_CHOWN_UID=65534" in command:
                    raise RuntimeError("chown helper failed")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            context = ActionContext.minimal(root, executor=FailingChownExecutor())
            target_prometheus = root / "target" / "prometheus"

            with self.assertRaises(RuntimeError) as caught:
                filesystem_prepare(
                    {
                        "params": {
                            "prometheus_data_path": str(target_prometheus),
                            "legacy_app_data_paths": [],
                            "legacy_prometheus_data_paths": [],
                            "helper_image": "helper:image",
                        }
                    },
                    context.as_dict(),
                )

            self.assertIn("Prometheus 数据目录权限修复失败", str(caught.exception))
            self.assertIn(str(target_prometheus), str(caught.exception))

    def test_files_sync_persists_each_file_checkpoint_before_next_copy(self) -> None:
        from app.upgrade_runner.actions import ActionContext, files_sync
        from app.upgrade_runner.engine import UpgradeEngine
        from app.upgrade_runner.store import TaskStore

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = root / "package"
            source = package / "project"
            project = root / "project"
            source.mkdir(parents=True)
            project.mkdir()
            (source / "first.conf").write_text("first", encoding="utf-8")
            (source / "second.conf").write_text("second", encoding="utf-8")
            context = ActionContext.minimal(root, package_path=package, project_path=project)
            store = TaskStore(root / "upgrade-1")
            store.save(
                {
                    "task_id": "upgrade-1",
                    "status": "pending",
                    "execution_plan": {
                        "protocol_version": 1,
                        "required_capabilities": ["files.sync"],
                        "actions": [
                            {
                                "id": "sync",
                                "type": "files.sync",
                                "status": "pending",
                                "attempt": 0,
                                "params": {"source": "project", "files": ["first.conf", "second.conf"]},
                                "checkpoint": {},
                                "result": {},
                            }
                        ],
                    },
                }
            )
            original_copy = __import__("shutil").copy2
            copies = 0

            def interrupt_second_copy(source_path, target_path):
                nonlocal copies
                copies += 1
                if copies == 2:
                    raise RuntimeError("interrupted")
                return original_copy(source_path, target_path)

            with patch("app.upgrade_runner.actions.shutil.copy2", side_effect=interrupt_second_copy):
                result = UpgradeEngine(
                    store,
                    handlers={"files.sync": files_sync},
                    context=context.as_dict(),
                ).run()

            self.assertEqual(result["status"], "failed")
            checkpoint = store.load()["execution_plan"]["actions"][0]["checkpoint"]
            self.assertEqual([item["path"] for item in checkpoint["files"]], ["first.conf"])

    def test_engine_records_action_start_and_finish_timestamps(self) -> None:
        from app.upgrade_runner.engine import UpgradeEngine
        from app.upgrade_runner.store import TaskStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = TaskStore(Path(tmpdir) / "upgrade-1")
            store.save(
                {
                    "task_id": "upgrade-1",
                    "status": "pending",
                    "execution_plan": {
                        "protocol_version": 1,
                        "required_capabilities": ["checkpoint.write"],
                        "actions": [
                        {
                            "id": "checkpoint",
                            "type": "checkpoint.write",
                            "status": "pending",
                            "attempt": 0,
                            "checkpoint": {},
                            "result": {},
                        }
                        ],
                    },
                }
            )
            result = UpgradeEngine(
                store,
                handlers={"checkpoint.write": lambda _action, _context: {"checkpoint": {"done": True}}},
            ).run()
            action = result["execution_plan"]["actions"][0]

            self.assertTrue(action["started_at"])
            self.assertTrue(action["finished_at"])

    def test_unknown_action_marks_task_failed_instead_of_crashing_runner(self) -> None:
        from app.upgrade_runner.engine import UpgradeEngine
        from app.upgrade_runner.store import TaskStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = TaskStore(Path(tmpdir) / "upgrade-1")
            store.save(
                {
                    "task_id": "upgrade-1",
                    "status": "pending",
                    "execution_plan": {
                        "protocol_version": 1,
                        "required_capabilities": ["future.action"],
                        "actions": [
                            {
                                "id": "future",
                                "type": "future.action",
                                "status": "pending",
                                "attempt": 0,
                                "checkpoint": {},
                                "result": {},
                            }
                        ],
                    },
                }
            )

            result = UpgradeEngine(store, handlers={}).run()

            self.assertEqual(result["status"], "failed")
            self.assertIn("不支持动作", result["error"])

    def test_sandbox_command_has_security_boundaries_and_no_docker_socket(self) -> None:
        from app.upgrade_runner.actions import ActionContext, CommandExecutor
        from app.upgrade_runner.sandbox import run_sandboxed_script

        class FakeExecutor(CommandExecutor):
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def run(self, command, *, cwd=None, timeout=None):
                self.commands.append(command)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = root / "package"
            package.mkdir()
            script = package / "migrate.py"
            script.write_text("print('ok')", encoding="utf-8")
            executor = FakeExecutor()
            context = ActionContext.minimal(root, executor=executor, package_path=package)
            host_data_path = root / "host-data"
            host_backups_path = root / "host-backups"
            host_prometheus_path = root / "host-prometheus"
            host_data_path.mkdir()
            host_backups_path.mkdir()
            host_prometheus_path.mkdir()
            context.host_data_path = host_data_path
            context.host_backups_path = host_backups_path
            context.host_prometheus_path = host_prometheus_path
            result = run_sandboxed_script(
                {
                    "params": {
                        "script": "migrate.py",
                        "sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
                        "image": "repo/web-api:v1",
                        "mounts": [
                            {"source": str(context.data_path), "target": "/data", "mode": "rw"},
                            {"source": str(context.backups_path), "target": "/data/backups", "mode": "rw"},
                            {"source": str(context.prometheus_path), "target": "/prometheus", "mode": "ro"},
                        ],
                        "timeout_seconds": 900,
                    }
                },
                context.as_dict(),
            )
            command = executor.commands[0]
            self.assertIn("--network=none", command)
            self.assertIn("--read-only", command)
            self.assertIn("--cap-drop=ALL", command)
            self.assertIn("no-new-privileges", command)
            self.assertNotIn("/var/run/docker.sock", " ".join(command))
            self.assertIn(f"{host_data_path}:/data:rw", command)
            self.assertIn(f"{host_backups_path}:/data/backups:rw", command)
            self.assertIn(f"{host_prometheus_path}:/prometheus:ro", command)
            self.assertNotIn(f"{context.data_path}:/data:rw", command)
            self.assertEqual(result["checkpoint"]["completed"], True)

            with self.assertRaisesRegex(ValueError, "禁止挂载"):
                run_sandboxed_script(
                    {
                        "params": {
                            "script": "migrate.py",
                            "sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
                            "image": "repo/web-api:v1",
                            "mounts": [
                                {"source": str(context.data_path / "exports"), "target": "/exports", "mode": "ro"},
                            ],
                        }
                    },
                    context.as_dict(),
                )

    def test_rollback_restores_old_files_removes_new_files_and_recreates_services(self) -> None:
        from app.upgrade_runner.actions import ActionContext, CommandExecutor, files_sync, rollback_restore

        class FakeExecutor(CommandExecutor):
            def __init__(self) -> None:
                self.commands: list[tuple[list[str], Path | None]] = []

            def run(self, command, *, cwd=None, timeout=None):
                self.commands.append((command, cwd))

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = root / "package"
            project = root / "project"
            source = package / "project"
            source.mkdir(parents=True)
            project.mkdir()
            (source / "existing.conf").write_text("new-existing", encoding="utf-8")
            (source / "added.conf").write_text("new-added", encoding="utf-8")
            (project / "existing.conf").write_text("old-existing", encoding="utf-8")
            executor = FakeExecutor()
            context = ActionContext.minimal(root, executor=executor, package_path=package, project_path=project)
            (context.data_path / "smartx.db").write_text("new-database", encoding="utf-8")
            (context.prometheus_path / "block-1").mkdir(parents=True)
            (context.prometheus_path / "block-1" / "meta.json").write_text("new-prometheus", encoding="utf-8")
            backup_source = root / "backup-source"
            (backup_source / "app").mkdir(parents=True)
            (backup_source / "prometheus" / "block-1").mkdir(parents=True)
            (backup_source / "app" / "smartx.db").write_text("old-database", encoding="utf-8")
            (backup_source / "prometheus" / "block-1" / "meta.json").write_text("old-prometheus", encoding="utf-8")
            backup_archive = root / "upgrade-backup.tar.gz"
            with tarfile.open(backup_archive, mode="w:gz") as archive:
                archive.add(backup_source / "app" / "smartx.db", arcname="app/smartx.db")
                archive.add(backup_source / "prometheus", arcname="prometheus")

            sync_result = files_sync(
                {
                    "params": {"source": "project", "files": ["existing.conf", "added.conf"]},
                    "checkpoint": {},
                },
                context.as_dict(),
            )
            override = context.compose_runtime_path / "docker-compose.upgrade-task.yml"
            override.write_text("services: {}\n", encoding="utf-8")

            rollback_restore(
                {
                    "params": {
                        "project_backup_path": sync_result["backup_path"],
                        "project_files": sync_result["checkpoint"]["files"],
                        "override_path": str(override),
                        "backup_path": str(backup_archive),
                        "backup_scope": "bundle",
                        "services": ["web-api", "frontend"],
                    }
                },
                context.as_dict(),
            )

            self.assertEqual((project / "existing.conf").read_text(encoding="utf-8"), "old-existing")
            self.assertFalse((project / "added.conf").exists())
            self.assertFalse(override.exists())
            self.assertEqual((context.data_path / "smartx.db").read_text(encoding="utf-8"), "old-database")
            self.assertEqual(
                (context.prometheus_path / "block-1" / "meta.json").read_text(encoding="utf-8"),
                "old-prometheus",
            )
            self.assertEqual(
                executor.commands,
                [
                    (
                        [
                            "docker",
                            "compose",
                            "-f",
                            "docker-compose.offline.yml",
                            "--project-name",
                            "smartx-hci-capacity-insight",
                            "stop",
                            "web-api",
                            "frontend",
                        ],
                        project,
                    ),
                    (
                        [
                            "docker",
                            "compose",
                            "-f",
                            "docker-compose.offline.yml",
                            "--project-name",
                            "smartx-hci-capacity-insight",
                            "up",
                            "-d",
                            "--no-deps",
                            "--force-recreate",
                            "web-api",
                            "frontend",
                        ],
                        project,
                    )
                ],
            )

    def test_http_health_check_retries_until_service_is_ready(self) -> None:
        from app.upgrade_runner.actions import health_http

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        calls = 0

        def urlopen(_url, timeout):
            nonlocal calls
            calls += 1
            self.assertEqual(timeout, 3)
            if calls < 3:
                raise OSError("not ready")
            return Response()

        with patch("app.upgrade_runner.actions.urllib.request.urlopen", side_effect=urlopen), patch(
            "app.upgrade_runner.actions.time.sleep"
        ) as sleep:
            result = health_http(
                {
                    "params": {
                        "url": "http://web-api:8000/api/system/health",
                        "expected_status": 200,
                        "attempts": 3,
                        "delay_seconds": 0.1,
                        "timeout_seconds": 3,
                    }
                },
                {},
            )

        self.assertEqual(result["status"], 200)
        self.assertEqual(calls, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_compose_apply_uses_configured_project_name(self) -> None:
        from app.upgrade_runner.actions import ActionContext, compose_apply

        class Executor:
            def __init__(self) -> None:
                self.commands: list[tuple[list[str], Path | None]] = []

            def run(self, command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
                self.commands.append((command, cwd))

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            executor = Executor()
            context = ActionContext.minimal(root, executor=executor)
            context.task_id = "upgrade-apply"
            context.compose_project = "smartx-hci-capacity-insight"
            override = context.compose_runtime_path / "docker-compose.upgrade-apply.yml"
            override.write_text("services:\n  web-api:\n    image: repo/web-api:v0.5.1u1\n", encoding="utf-8")

            result = compose_apply({"params": {"services": ["web-api", "frontend"]}}, context.as_dict())

            self.assertEqual(result["services"], ["web-api", "frontend"])
            self.assertEqual(
                executor.commands,
                [
                    (
                        [
                            "docker",
                            "compose",
                            "-f",
                            "docker-compose.offline.yml",
                            "-f",
                            str(override),
                            "--project-name",
                            "smartx-hci-capacity-insight",
                            "up",
                            "-d",
                            "--no-deps",
                            "web-api",
                            "frontend",
                        ],
                        context.project_path,
                    )
                ],
            )

    def test_compose_project_migrate_removes_old_project_and_safe_network(self) -> None:
        from app.upgrade_runner.actions import ActionContext, compose_project_migrate

        class Executor:
            def __init__(self) -> None:
                self.commands: list[tuple[list[str], Path | None]] = []

            def run(self, command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
                self.commands.append((command, cwd))

            def output(self, command: list[str], *, cwd: Path | None = None) -> str:
                self.commands.append((command, cwd))
                if command[:2] == ["docker", "ps"]:
                    return "old-web\nold-runner\n"
                if command[:3] == ["docker", "network", "inspect"]:
                    return json.dumps(
                        [
                            {
                                "Name": "smartx-storage-forecast_smartx-net",
                                "Containers": {},
                            }
                        ]
                    )
                return ""

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            executor = Executor()
            context = ActionContext.minimal(root, executor=executor)
            context.compose_project = "smartx-hci-capacity-insight"

            result = compose_project_migrate(
                {
                    "params": {
                        "transitions": [
                            {
                                "from_project": "smartx-storage-forecast",
                                "from_network": "smartx-storage-forecast_smartx-net",
                                "to_project": "smartx-hci-capacity-insight",
                                "to_network": "smartx-hci-capacity-insight-net",
                            }
                        ]
                    }
                },
                context.as_dict(),
            )

            self.assertEqual(result["migrated_projects"], ["smartx-storage-forecast"])
            self.assertEqual(result["removed_networks"], ["smartx-storage-forecast_smartx-net"])
            self.assertEqual(
                executor.commands,
                [
                    (
                        [
                            "docker",
                            "ps",
                            "-a",
                            "--filter",
                            "label=com.docker.compose.project=smartx-storage-forecast",
                            "--format",
                            "{{.ID}}",
                        ],
                        None,
                    ),
                    (["docker", "stop", "old-web", "old-runner"], None),
                    (["docker", "rm", "old-web", "old-runner"], None),
                    (["docker", "network", "inspect", "smartx-storage-forecast_smartx-net"], None),
                    (["docker", "network", "rm", "smartx-storage-forecast_smartx-net"], None),
                ],
            )

    def test_compose_project_migrate_runs_embedded_directory_transition_first(self) -> None:
        from app.upgrade_runner.actions import ActionContext, compose_project_migrate

        class Executor:
            def __init__(self) -> None:
                self.commands: list[tuple[list[str], Path | None]] = []

            def run(self, command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
                self.commands.append((command, cwd))

            def output(self, command: list[str], *, cwd: Path | None = None) -> str:
                self.commands.append((command, cwd))
                if command[:2] == ["docker", "ps"]:
                    return ""
                if command[:3] == ["docker", "network", "inspect"]:
                    return json.dumps([{"Name": "old_net", "Containers": {}}])
                return ""

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy_app = root / "legacy-app"
            legacy_app.mkdir()
            (legacy_app / "smartx.db").write_text("legacy-db", encoding="utf-8")
            executor = Executor()
            context = ActionContext.minimal(root, executor=executor)

            result = compose_project_migrate(
                {
                    "params": {
                        "transitions": [
                            {
                                "from_project": "old",
                                "from_network": "old_net",
                                "to_project": "new",
                                "to_network": "new_net",
                                "directory_transition": {
                                    "app_data_path": str(context.data_path),
                                    "prometheus_data_path": str(context.prometheus_path),
                                    "legacy_app_data_paths": [str(legacy_app)],
                                    "legacy_prometheus_data_paths": [],
                                },
                            }
                        ]
                    }
                },
                context.as_dict(),
            )

            self.assertEqual((context.data_path / "smartx.db").read_text(encoding="utf-8"), "legacy-db")
            self.assertTrue(result["prepared_layouts"])
            self.assertIn((["docker", "network", "rm", "old_net"], None), executor.commands)

    def test_compose_project_migrate_does_not_stop_current_runner_container(self) -> None:
        from app.upgrade_runner.actions import ActionContext, compose_project_migrate

        class Executor:
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def run(self, command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
                self.commands.append(command)

            def output(self, command: list[str], *, cwd: Path | None = None) -> str:
                if command[:2] == ["docker", "ps"]:
                    return "runner123\nweb456\n"
                if command[:3] == ["docker", "network", "inspect"]:
                    return json.dumps(
                        [
                            {
                                "Name": "old_net",
                                "Containers": {
                                    "runner123": {"Name": "smartx-storage-forecast-upgrade-runner-1"},
                                },
                            }
                        ]
                    )
                return ""

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = Executor()
            context = ActionContext.minimal(Path(tmpdir), executor=executor)
            context.current_container_id = "runner123"

            result = compose_project_migrate(
                {
                    "params": {
                        "transitions": [
                            {
                                "from_project": "smartx-storage-forecast",
                                "from_network": "old_net",
                                "to_project": "smartx-hci-capacity-insight",
                                "to_network": "smartx-hci-capacity-insight-net",
                            }
                        ]
                    }
                },
                context.as_dict(),
            )

            self.assertIn(["docker", "stop", "web456"], executor.commands)
            self.assertIn(["docker", "rm", "web456"], executor.commands)
            self.assertNotIn(["docker", "stop", "runner123"], executor.commands)
            self.assertEqual(result["removed_networks"], [])
            self.assertIn("old_net", result["skipped"])

    def test_compose_apply_connects_current_runner_to_new_web_api_network(self) -> None:
        from app.upgrade_runner.actions import ActionContext, compose_apply

        class Executor:
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def run(self, command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
                self.commands.append(command)

            def output(self, command: list[str], *, cwd: Path | None = None) -> str:
                if command[:2] == ["docker", "ps"]:
                    return "web123\n"
                if command[:2] == ["docker", "inspect"] and command[-1] == "web123":
                    return json.dumps([{"NetworkSettings": {"Networks": {"smartx-hci-capacity-insight-net": {}}}}])
                return "[]"

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            executor = Executor()
            context = ActionContext.minimal(root, executor=executor)
            context.current_container_id = "runner123"
            (context.compose_runtime_path / "docker-compose.upgrade-task.yml").write_text("services: {}\n", encoding="utf-8")

            result = compose_apply({"params": {"services": ["web-api", "frontend"]}}, context.as_dict())

            self.assertIn(["docker", "network", "connect", "smartx-hci-capacity-insight-net", "runner123"], executor.commands)
            self.assertEqual(result["connected_networks"], ["smartx-hci-capacity-insight-net"])

    def test_compose_project_migrate_removes_old_project_containers_attached_to_old_network(self) -> None:
        from app.upgrade_runner.actions import ActionContext, compose_project_migrate

        class Executor:
            def __init__(self) -> None:
                self.commands: list[tuple[list[str], Path | None]] = []

            def run(self, command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
                self.commands.append((command, cwd))

            def output(self, command: list[str], *, cwd: Path | None = None) -> str:
                self.commands.append((command, cwd))
                if command[:2] == ["docker", "ps"]:
                    return ""
                if command[:3] == ["docker", "network", "inspect"]:
                    return json.dumps(
                        [
                            {
                                "Name": "smartx-storage-forecast_smartx-net",
                                "Containers": {
                                    "old-web-id": {"Name": "smartx-storage-forecast-web-api-1"},
                                    "old-fe-id": {"Name": "smartx-storage-forecast-frontend-1"},
                                },
                            }
                        ]
                    )
                return ""

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = Executor()
            context = ActionContext.minimal(Path(tmpdir), executor=executor)
            context.compose_project = "smartx-hci-capacity-insight"

            result = compose_project_migrate(
                {
                    "params": {
                        "transitions": [
                            {
                                "from_project": "smartx-storage-forecast",
                                "from_network": "smartx-storage-forecast_smartx-net",
                                "to_project": "smartx-hci-capacity-insight",
                                "to_network": "smartx-hci-capacity-insight-net",
                            }
                        ]
                    }
                },
                context.as_dict(),
            )

            self.assertEqual(result["migrated_projects"], ["smartx-storage-forecast"])
            self.assertEqual(result["removed_networks"], ["smartx-storage-forecast_smartx-net"])
            self.assertIn((["docker", "stop", "old-web-id", "old-fe-id"], None), executor.commands)
            self.assertIn((["docker", "rm", "old-web-id", "old-fe-id"], None), executor.commands)

    def test_compose_project_migrate_blocks_network_with_external_containers(self) -> None:
        from app.upgrade_runner.actions import ActionContext, compose_project_migrate

        class Executor:
            def run(self, command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
                raise AssertionError(f"unexpected run: {command}")

            def output(self, command: list[str], *, cwd: Path | None = None) -> str:
                if command[:2] == ["docker", "ps"]:
                    return ""
                if command[:3] == ["docker", "network", "inspect"]:
                    return json.dumps(
                        [
                            {
                                "Name": "smartx-storage-forecast_smartx-net",
                                "Containers": {"abc": {"Name": "manual-container"}},
                            }
                        ]
                    )
                return ""

        with tempfile.TemporaryDirectory() as tmpdir:
            context = ActionContext.minimal(Path(tmpdir), executor=Executor())

            with self.assertRaisesRegex(RuntimeError, "manual-container"):
                compose_project_migrate(
                    {
                        "params": {
                            "transitions": [
                                {
                                    "from_project": "smartx-storage-forecast",
                                    "from_network": "smartx-storage-forecast_smartx-net",
                                    "to_project": "smartx-hci-capacity-insight",
                                    "to_network": "smartx-hci-capacity-insight-net",
                                }
                            ]
                        }
                    },
                    context.as_dict(),
                )

    def test_legacy_cleanup_removes_allowlisted_residuals_after_health_passes(self) -> None:
        from unittest import mock

        from app.upgrade_runner.actions import ActionContext, legacy_cleanup

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "ok": True,
                        "version": "v0.5.2",
                        "runner_version": "v0.3.1",
                        "checks": {"directories": True, "database": True, "prometheus": True},
                    }
                ).encode("utf-8")

        class Executor:
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def run(self, command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
                self.commands.append(command)

            def output(self, command: list[str], *, cwd: Path | None = None) -> str:
                self.commands.append(command)
                if command[:2] == ["docker", "ps"]:
                    return "old-runner\n"
                if command[:3] == ["docker", "network", "inspect"]:
                    return json.dumps(
                        [
                            {
                                "Name": "smartx-storage-forecast_smartx-net",
                                "Containers": {"old-runner": {"Name": "smartx-storage-forecast-upgrade-runner-1"}},
                            }
                        ]
                    )
                return ""

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy_path = root / "data" / "upgrades"
            residual_path = root / "data" / "smartx-storage-forecast" / "app" / "upgrades"
            protected_root = root / "data" / "smartx-storage-forecast"
            legacy_path.mkdir(parents=True)
            residual_path.mkdir(parents=True)
            executor = Executor()
            context = ActionContext.minimal(root, executor=executor)
            context.compose_project = "smartx-hci-capacity-insight"

            with mock.patch("app.upgrade_runner.actions.urllib.request.urlopen", return_value=Response()):
                result = legacy_cleanup(
                    {
                        "params": {
                            "health_url": "http://web-api:8000/api/system/health",
                            "legacy_projects": ["smartx-storage-forecast"],
                            "legacy_networks": ["smartx-storage-forecast_smartx-net"],
                            "legacy_paths": [str(legacy_path)],
                            "target_app_residual_paths": [str(residual_path)],
                            "protected_paths": [str(protected_root)],
                            "required_health": {
                                "version": "v0.5.2",
                                "runner_version": "v0.3.1",
                                "checks": ["directories", "database", "prometheus"],
                            },
                        }
                    },
                    context.as_dict(),
                )

            self.assertFalse(legacy_path.exists())
            self.assertFalse(residual_path.exists())
            self.assertIn(["docker", "stop", "old-runner"], executor.commands)
            self.assertIn(["docker", "rm", "old-runner"], executor.commands)
            self.assertIn(["docker", "network", "rm", "smartx-storage-forecast_smartx-net"], executor.commands)
            self.assertEqual({item["status"] for item in result["paths"]}, {"deleted"})

    def test_legacy_cleanup_removes_legacy_named_container_without_project_label(self) -> None:
        from unittest import mock

        from app.upgrade_runner.actions import ActionContext, legacy_cleanup

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "ok": True,
                        "version": "v0.5.2",
                        "runner_version": "v0.3.1",
                        "checks": {"directories": True, "database": True, "prometheus": True},
                    }
                ).encode("utf-8")

        class Executor:
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def run(self, command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
                self.commands.append(command)

            def output(self, command: list[str], *, cwd: Path | None = None) -> str:
                self.commands.append(command)
                if command[:2] == ["docker", "ps"] and "--filter" in command:
                    if "label=com.docker.compose.project=smartx-storage-forecast" in command:
                        return ""
                    if "name=smartx-storage-forecast-" in command:
                        return "old-runner\n"
                if command[:3] == ["docker", "network", "inspect"]:
                    return json.dumps([{"Name": "smartx-storage-forecast_smartx-net", "Containers": {}}])
                return ""

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy_path = root / "opt" / "smartx-storage-forecast"
            protected_root = root / "data" / "smartx-storage-forecast"
            legacy_path.mkdir(parents=True)
            protected_root.mkdir(parents=True)
            executor = Executor()
            context = ActionContext.minimal(root, executor=executor)
            context.compose_project = "smartx-hci-capacity-insight"

            with mock.patch("app.upgrade_runner.actions.urllib.request.urlopen", return_value=Response()):
                result = legacy_cleanup(
                    {
                        "params": {
                            "health_url": "http://web-api:8000/api/system/health",
                            "legacy_projects": ["smartx-storage-forecast"],
                            "legacy_networks": ["smartx-storage-forecast_smartx-net"],
                            "legacy_paths": [str(legacy_path)],
                            "protected_paths": [str(protected_root)],
                            "required_health": {
                                "version": "v0.5.2",
                                "runner_version": "v0.3.1",
                                "checks": ["directories", "database", "prometheus"],
                            },
                        }
                    },
                    context.as_dict(),
                )

            self.assertFalse(legacy_path.exists())
            self.assertIn(["docker", "stop", "old-runner"], executor.commands)
            self.assertIn(["docker", "rm", "old-runner"], executor.commands)
            self.assertEqual(result["removed_projects"], ["smartx-storage-forecast"])

    def test_legacy_cleanup_rejects_unsafe_paths(self) -> None:
        from app.upgrade_runner.actions import ActionContext, legacy_cleanup

        with tempfile.TemporaryDirectory() as tmpdir:
            context = ActionContext.minimal(Path(tmpdir))

            with self.assertRaisesRegex(ValueError, "不允许清理"):
                legacy_cleanup(
                    {
                        "params": {
                            "legacy_projects": [],
                            "legacy_networks": [],
                            "legacy_paths": ["/data"],
                            "target_app_residual_paths": [],
                            "protected_paths": ["/data/smartx-storage-forecast"],
                        }
                    },
                    context.as_dict(),
                )

    def test_post_upgrade_collection_marker_is_idempotent_in_target_runtime(self) -> None:
        from app.upgrade_runner.actions import ActionContext, post_upgrade_schedule_collection

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            context = ActionContext.minimal(root)
            context.task_id = "upgrade-auto-collection"
            target_upgrades = root / "target-upgrades"
            action = {
                "params": {
                    "target_upgrades_path": str(target_upgrades),
                    "target_version": "v0.5.2",
                }
            }

            first = post_upgrade_schedule_collection(action, context.as_dict())
            marker_path = target_upgrades / context.task_id / "post-upgrade-collection.json"
            marker = json.loads(marker_path.read_text(encoding="utf-8"))

            self.assertEqual(first["task_id"], "post-upgrade-collection-upgrade-auto-collection")
            self.assertEqual(marker["status"], "pending")
            self.assertEqual(marker["parent_upgrade_task_id"], context.task_id)
            self.assertEqual(marker["target_version"], "v0.5.2")

            marker["status"] = "success"
            marker_path.write_text(json.dumps(marker), encoding="utf-8")
            second = post_upgrade_schedule_collection(action, context.as_dict())

            self.assertEqual(second["status"], "success")
            self.assertEqual(json.loads(marker_path.read_text(encoding="utf-8"))["status"], "success")


if __name__ == "__main__":
    unittest.main()
