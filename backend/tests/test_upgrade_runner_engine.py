from __future__ import annotations

import tempfile
import unittest
import hashlib
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
            manager.update_runner_state("v0.3.0")
            state = manager.runner_state()

            self.assertEqual(state["runner_version"], "v0.3.0")
            self.assertEqual(state["protocol_version"], 1)
            self.assertIn("backup.create", state["capabilities"])


def _safe_extract_for_test(archive: tarfile.TarFile, destination: Path) -> None:
    try:
        archive.extractall(destination, filter="data")
    except TypeError:
        archive.extractall(destination)

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
            self.assertEqual(calls, ["load"])
            self.assertEqual(result["execution_plan"]["actions"][1]["attempt"], 2)

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
                            "smartx-storage-forecast",
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
                            "smartx-storage-forecast",
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


if __name__ == "__main__":
    unittest.main()
