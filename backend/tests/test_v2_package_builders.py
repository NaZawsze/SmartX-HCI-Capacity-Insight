from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_docker_run(command: list[str], cwd: Path = ROOT) -> str:
    if command[:2] == ["docker", "run"]:
        return "SMARTX_V2_HEALTH_OK\n"
    if command[:2] == ["docker", "save"] and "-o" in command:
        output = Path(command[command.index("-o") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(("fake-image:" + command[-1]).encode("utf-8"))
        return ""
    if command[:3] == ["docker", "image", "inspect"]:
        return "{}"
    return ""


class _RunRecorder:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], cwd: Path = ROOT) -> str:
        self.commands.append(command)
        return _fake_docker_run(command, cwd=cwd)


class V2PackageBuilderTest(unittest.TestCase):
    def test_platform_upgrade_builder_emits_v2_manifest_with_components(self) -> None:
        builder = _load_script("build_upgrade_package.py")
        builder.run = _fake_docker_run

        with tempfile.TemporaryDirectory() as tmpdir:
            package = builder.build_package(
                "v0.5.1",
                min_version="v0.5.1",
                output_dir=Path(tmpdir),
                build_images=False,
                include_frontend_build=False,
            )

            with tarfile.open(package, mode="r:gz") as archive:
                names = set(archive.getnames())
                manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))

        self.assertEqual(manifest["schema_version"], "3")
        self.assertEqual(manifest["minimum_runner_protocol"], 1)
        self.assertIn("backup.create", manifest["required_capabilities"])
        self.assertNotIn("script.sandbox.v1", manifest["required_capabilities"])
        self.assertEqual(manifest["package_id"], "smartx-capacity-insight-v0.5.1")
        self.assertEqual(manifest["version"], "v0.5.1")
        self.assertEqual(manifest["compatibility"]["min_platform_version"], "v0.5.1")
        self.assertIs(manifest["project_files"], True)
        self.assertIs(manifest["database_migration"], False)
        self.assertNotIn("migration", manifest)
        self.assertEqual(manifest["restart_services"], ["web-api", "collector-worker", "frontend"])
        self.assertEqual([component["type"] for component in manifest["components"]], ["platform"])
        platform = manifest["components"][0]
        self.assertEqual(platform["services"], ["web-api", "collector-worker", "frontend"])
        self.assertEqual(
            {image["archive"] for image in platform["images"]},
            {"images/web-api.tar", "images/collector-worker.tar", "images/frontend.tar"},
        )
        self.assertNotIn("images/upgrade-runner.tar", names)
        self.assertNotIn("scripts/migrate.sh", names)
        self.assertIn("checksums.sha256", names)
        self.assertFalse(any(name.startswith("project/.env") or name.endswith("smartx.db") for name in names))
        from app.v2.upgrade.compiler import compile_execution_plan

        plan = compile_execution_plan(manifest).to_dict()
        self.assertNotIn("script.run_sandboxed", {action["type"] for action in plan["actions"]})

    def test_platform_builder_includes_intermediate_sqlite_migrations_for_cross_version_upgrade(self) -> None:
        builder = _load_script("build_upgrade_package.py")
        builder.run = _fake_docker_run

        with tempfile.TemporaryDirectory() as tmpdir:
            registry = Path(tmpdir) / "registry.json"
            registry.write_text(
                json.dumps(
                    [
                        {
                            "id": "20260612_v0_5_2_sqlite_schema",
                            "version": "v0.5.2",
                            "description": "Add v0.5.2 SQLite schema",
                            "database": "sqlite",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            package = builder.build_package(
                "v0.5.3",
                min_version="v0.5.1",
                output_dir=Path(tmpdir),
                build_images=False,
                include_frontend_build=False,
                migration_registry=registry,
                check_version_metadata=False,
            )

            with tarfile.open(package, mode="r:gz") as archive:
                names = set(archive.getnames())
                manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))
                runner = archive.extractfile("migrations/run_migrations.py").read().decode("utf-8")

        self.assertIs(manifest["database_migration"], True)
        self.assertIn("script.sandbox.v1", manifest["required_capabilities"])
        self.assertEqual(manifest["migration"]["script"], "migrations/run_migrations.py")
        self.assertEqual([step["id"] for step in manifest["migration_steps"]], ["20260612_v0_5_2_sqlite_schema"])
        self.assertEqual(manifest["migration_steps"][0]["version"], "v0.5.2")
        self.assertTrue(manifest["migration_steps"][0]["script_sha256"])
        self.assertIn("migrations/run_migrations.py", names)
        self.assertIn("20260612_v0_5_2_sqlite_schema", runner)
        self.assertIn("schema_migrations", runner)
        from app.v2.upgrade.compiler import compile_execution_plan

        plan = compile_execution_plan(manifest).to_dict()
        self.assertIn("script.run_sandboxed", {action["type"] for action in plan["actions"]})

    def test_platform_builder_skips_intermediate_migrations_at_or_below_source_version(self) -> None:
        builder = _load_script("build_upgrade_package.py")
        builder.run = _fake_docker_run

        with tempfile.TemporaryDirectory() as tmpdir:
            registry = Path(tmpdir) / "registry.json"
            registry.write_text(
                json.dumps(
                    [
                        {
                            "id": "20260612_v0_5_2_sqlite_schema",
                            "version": "v0.5.2",
                            "description": "Add v0.5.2 SQLite schema",
                            "database": "sqlite",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            package = builder.build_package(
                "v0.5.3",
                min_version="v0.5.2",
                output_dir=Path(tmpdir),
                build_images=False,
                include_frontend_build=False,
                migration_registry=registry,
                check_version_metadata=False,
            )

            with tarfile.open(package, mode="r:gz") as archive:
                names = set(archive.getnames())
                manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))

        self.assertIs(manifest["database_migration"], False)
        self.assertNotIn("migration", manifest)
        self.assertNotIn("migration_steps", manifest)
        self.assertNotIn("migrations/run_migrations.py", names)

    def test_generated_migration_runner_records_steps_idempotently(self) -> None:
        builder = _load_script("build_upgrade_package.py")
        steps = [
            {
                "id": "20260612_v0_5_2_sqlite_schema",
                "version": "v0.5.2",
                "description": "Add v0.5.2 SQLite schema",
                "database": "sqlite",
                "sql": ["CREATE TABLE IF NOT EXISTS migration_probe (id TEXT PRIMARY KEY)"],
                "operations": [
                    {
                        "action": "add_column_if_missing",
                        "table": "migration_probe",
                        "column": "note",
                        "definition": "TEXT",
                    }
                ],
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            script_path = tmp / "run_migrations.py"
            _, public_steps = builder.write_migration_runner(script_path, steps)
            data_dir = tmp / "data"
            data_dir.mkdir()
            database_path = data_dir / "smartx.db"
            sqlite3.connect(database_path).close()
            env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"), "SMARTX_DB_PATH": str(database_path)}

            first = subprocess.run(
                ["python3", str(script_path)],
                cwd=tmp,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            second = subprocess.run(
                ["python3", str(script_path)],
                cwd=tmp,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            with sqlite3.connect(database_path) as conn:
                rows = conn.execute("SELECT id, version, description, script_sha256 FROM schema_migrations").fetchall()
                probe = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'migration_probe'").fetchone()
                columns = {row[1] for row in conn.execute("PRAGMA table_info(migration_probe)").fetchall()}
            self.assertEqual(rows, [("20260612_v0_5_2_sqlite_schema", "v0.5.2", "Add v0.5.2 SQLite schema", public_steps[0]["script_sha256"])])
            self.assertIsNotNone(probe)
            self.assertIn("note", columns)
            self.assertIn("applied 20260612_v0_5_2_sqlite_schema", first.stdout)
            self.assertIn("skip 20260612_v0_5_2_sqlite_schema", second.stdout)

    def test_migration_registry_rejects_invalid_sql_shape(self) -> None:
        builder = _load_script("build_upgrade_package.py")

        with tempfile.TemporaryDirectory() as tmpdir:
            registry = Path(tmpdir) / "registry.json"
            registry.write_text(
                json.dumps(
                    [
                        {
                            "id": "bad_sql",
                            "version": "v0.5.2",
                            "description": "Bad SQL",
                            "database": "sqlite",
                            "sql": "CREATE TABLE bad_sql (id TEXT)",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(SystemExit) as caught:
                builder._load_migration_registry(registry)

        self.assertIn("sql must be a string array", str(caught.exception))

    def test_migration_registry_rejects_invalid_operations(self) -> None:
        builder = _load_script("build_upgrade_package.py")

        with tempfile.TemporaryDirectory() as tmpdir:
            registry = Path(tmpdir) / "registry.json"
            registry.write_text(
                json.dumps(
                    [
                        {
                            "id": "bad_operation",
                            "version": "v0.5.2",
                            "description": "Bad operation",
                            "database": "sqlite",
                            "operations": [{"action": "drop_everything"}],
                        }
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(SystemExit) as caught:
                builder._load_migration_registry(registry)

        self.assertIn("Unsupported migration operation", str(caught.exception))

    def test_migration_registry_rejects_duplicate_ids(self) -> None:
        builder = _load_script("build_upgrade_package.py")

        with tempfile.TemporaryDirectory() as tmpdir:
            registry = Path(tmpdir) / "registry.json"
            registry.write_text(
                json.dumps(
                    [
                        {"id": "dup", "version": "v0.5.2", "description": "A", "database": "sqlite"},
                        {"id": "dup", "version": "v0.5.3", "description": "B", "database": "sqlite"},
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(SystemExit) as caught:
                builder._load_migration_registry(registry)

        self.assertIn("Duplicate migration step id", str(caught.exception))

    def test_runner_component_builder_emits_v2_manifest_with_runner_component(self) -> None:
        builder = _load_script("build_runner_component_package.py")
        recorder = _RunRecorder()
        builder.run = recorder

        with tempfile.TemporaryDirectory() as tmpdir:
            package = builder.build_package("v0.3.0", "v0.2.1", Path(tmpdir), build_image=False)

            with tarfile.open(package, mode="r:gz") as archive:
                names = set(archive.getnames())
                manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))

        self.assertEqual(manifest["schema_version"], "3")
        self.assertEqual(manifest["minimum_runner_protocol"], 1)
        self.assertEqual(manifest["required_capabilities"], [])
        self.assertEqual(manifest["package_id"], "smartx-upgrade-runner-v0.3.0")
        self.assertEqual(manifest["version"], "v0.3.0")
        self.assertEqual(manifest["compatibility"]["min_runner_version"], "v0.2.1")
        self.assertEqual(manifest["restart_services"], ["upgrade-runner"])
        self.assertIs(manifest["project_files"], False)
        self.assertEqual([component["type"] for component in manifest["components"]], ["runner"])
        runner = manifest["components"][0]
        self.assertEqual(runner["services"], ["upgrade-runner"])
        self.assertEqual(runner["images"][0]["archive"], "images/upgrade-runner.tar")
        self.assertEqual(runner["images"][0]["image"], "nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.0")
        self.assertIn("checksums.sha256", names)
        self.assertIn(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "python",
                "nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.0",
                "-c",
                "import app.upgrade_runner.main; import app.upgrade_protocol.models",
            ],
            recorder.commands,
        )

    def test_prometheus_component_builder_emits_observability_manifest(self) -> None:
        builder = _load_script("build_prometheus_component_package.py")
        builder.run = _fake_docker_run

        with tempfile.TemporaryDirectory() as tmpdir:
            package = builder.build_package("v2.55.1", "v2.55.1", Path(tmpdir), pull_image=False)

            with tarfile.open(package, mode="r:gz") as archive:
                names = set(archive.getnames())
                manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))

        self.assertEqual(manifest["schema_version"], "3")
        self.assertEqual(manifest["minimum_runner_protocol"], 1)
        self.assertNotIn("image.load", manifest["required_capabilities"])
        self.assertIn("health.prometheus", manifest["required_capabilities"])
        self.assertEqual(manifest["package_id"], "smartx-prometheus-v2.55.1")
        self.assertEqual(manifest["version"], "v2.55.1")
        self.assertEqual(manifest["compatibility"]["min_prometheus_version"], "v2.55.1")
        self.assertEqual(manifest["restart_services"], ["prometheus"])
        self.assertIs(manifest["project_files"], False)
        self.assertEqual([component["type"] for component in manifest["components"]], ["observability"])
        observability = manifest["components"][0]
        self.assertEqual(observability["services"], ["prometheus"])
        self.assertEqual(observability["images"][0]["image"], "prom/prometheus:v2.55.1")
        self.assertNotIn("archive", observability["images"][0])
        self.assertEqual(manifest["file_sets"][0]["source"], "config")
        self.assertEqual(manifest["file_sets"][0]["target"], "prometheus")
        self.assertNotIn("images/prometheus.tar", names)
        self.assertIn("config/prometheus.yml", names)
        self.assertIn("health/queries.json", names)
        self.assertIn("checksums.sha256", names)
        self.assertNotIn("images/web-api.tar", names)
        self.assertNotIn("images/upgrade-runner.tar", names)

    def test_prometheus_component_builder_can_emit_offline_image_tar(self) -> None:
        builder = _load_script("build_prometheus_component_package.py")
        builder.run = _fake_docker_run

        with tempfile.TemporaryDirectory() as tmpdir:
            package = builder.build_package("v2.55.1", "v2.55.1", Path(tmpdir), pull_image=False, offline_image=True)

            with tarfile.open(package, mode="r:gz") as archive:
                names = set(archive.getnames())
                manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))

        image = manifest["components"][0]["images"][0]
        self.assertIn("image.load", manifest["required_capabilities"])
        self.assertEqual(image["archive"], "images/prometheus.tar")
        self.assertTrue(image["sha256"])
        self.assertIn("images/prometheus.tar", names)

    def test_bundle_builder_combines_platform_and_observability_without_runner(self) -> None:
        builder = _load_script("build_bundle_upgrade_package.py")
        platform_builder = _load_script("build_upgrade_package.py")
        prometheus_builder = _load_script("build_prometheus_component_package.py")
        platform_builder.run = _fake_docker_run
        prometheus_builder.run = _fake_docker_run
        builder.load_platform_builder = lambda: platform_builder
        builder.load_prometheus_builder = lambda: prometheus_builder

        with tempfile.TemporaryDirectory() as tmpdir:
            package = builder.build_package(
                platform_version="v0.5.1",
                prometheus_version="v2.55.1",
                min_platform_version="v0.5.1",
                min_prometheus_version="v2.55.1",
                output_dir=Path(tmpdir),
                build_platform_images=False,
                include_frontend_build=False,
                pull_prometheus=False,
                offline_prometheus_image=False,
            )

            with tarfile.open(package, mode="r:gz") as archive:
                names = set(archive.getnames())
                manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))

        self.assertEqual(manifest["schema_version"], "3")
        self.assertEqual(manifest["package_type"], "bundle")
        self.assertEqual([component["type"] for component in manifest["components"]], ["platform", "observability"])
        self.assertEqual(manifest["project_source"], "platform/project")
        self.assertNotIn("migration", manifest)
        self.assertIn("platform/images/web-api.tar", names)
        self.assertNotIn("observability/images/prometheus.tar", names)
        self.assertIn("platform/project/docker-compose.offline.yml", names)
        self.assertNotIn("platform/migrations/migrate.sh", names)
        self.assertIn("checksums.sha256", names)
        self.assertNotIn("images/upgrade-runner.tar", names)
        self.assertNotIn("runner", {component["type"] for component in manifest["components"]})
        from app.v2.upgrade.compiler import compile_execution_plan

        plan = compile_execution_plan(manifest).to_dict()
        self.assertNotIn("script.run_sandboxed", {action["type"] for action in plan["actions"]})
        file_syncs = [action for action in plan["actions"] if action["type"] == "files.sync"]
        self.assertTrue(any(action["params"]["source"] == "observability/config" and action["params"].get("target") == "prometheus" for action in file_syncs))
        sync_action = next(action for action in plan["actions"] if action["type"] == "files.sync")
        self.assertEqual(sync_action["params"]["source"], "platform/project")

    def test_bundle_builder_preserves_platform_migration_steps(self) -> None:
        builder = _load_script("build_bundle_upgrade_package.py")
        platform_builder = _load_script("build_upgrade_package.py")
        prometheus_builder = _load_script("build_prometheus_component_package.py")
        platform_builder.run = _fake_docker_run
        prometheus_builder.run = _fake_docker_run

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            registry = tmp / "registry.json"
            registry.write_text(
                json.dumps(
                    [
                        {
                            "id": "20260612_v0_5_2_sqlite_schema",
                            "version": "v0.5.2",
                            "description": "Add v0.5.2 SQLite schema",
                            "database": "sqlite",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            original_build_package = platform_builder.build_package

            def build_platform_with_registry(*args, **kwargs):
                kwargs["migration_registry"] = registry
                kwargs["check_version_metadata"] = False
                return original_build_package(*args, **kwargs)

            platform_builder.build_package = build_platform_with_registry
            builder.load_platform_builder = lambda: platform_builder
            builder.load_prometheus_builder = lambda: prometheus_builder

            package = builder.build_package(
                platform_version="v0.5.3",
                prometheus_version="v2.55.1",
                min_platform_version="v0.5.1",
                min_prometheus_version="v2.55.1",
                output_dir=tmp,
                build_platform_images=False,
                include_frontend_build=False,
                pull_prometheus=False,
                offline_prometheus_image=False,
            )

            with tarfile.open(package, mode="r:gz") as archive:
                names = set(archive.getnames())
                manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))

        self.assertIs(manifest["database_migration"], True)
        self.assertEqual(manifest["migration"]["script"], "platform/migrations/run_migrations.py")
        self.assertEqual([step["id"] for step in manifest["migration_steps"]], ["20260612_v0_5_2_sqlite_schema"])
        self.assertIn("platform/migrations/run_migrations.py", names)
        self.assertNotIn("platform/migrations/migrate.sh", names)

        from app.v2.upgrade.compiler import compile_execution_plan

        plan = compile_execution_plan(manifest).to_dict()
        self.assertIn("script.run_sandboxed", {action["type"] for action in plan["actions"]})

    def test_bundle_builder_rejects_required_migration_without_script(self) -> None:
        builder = _load_script("build_bundle_upgrade_package.py")
        platform_builder = _load_script("build_upgrade_package.py")
        prometheus_builder = _load_script("build_prometheus_component_package.py")
        platform_builder.run = _fake_docker_run
        prometheus_builder.run = _fake_docker_run

        original_build_package = platform_builder.build_package

        def build_platform_without_script(*args, **kwargs):
            package = original_build_package(*args, **kwargs)
            with tarfile.open(package, "r:gz") as source:
                members = {member.name: source.extractfile(member).read() for member in source.getmembers() if member.isfile()}
            manifest = json.loads(members["manifest.json"].decode("utf-8"))
            manifest["database_migration"] = True
            manifest["migration"] = {"required": True}
            members["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            patched = Path(package).with_name("patched-platform.tar.gz")
            with tarfile.open(patched, "w:gz") as target:
                for name, payload in members.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    target.addfile(info, io.BytesIO(payload))
            return patched

        import io

        platform_builder.build_package = build_platform_without_script
        builder.load_platform_builder = lambda: platform_builder
        builder.load_prometheus_builder = lambda: prometheus_builder

        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as caught:
                builder.build_package(
                    platform_version="v0.5.1",
                    prometheus_version="v2.55.1",
                    min_platform_version="v0.5.1",
                    min_prometheus_version="v2.55.1",
                    output_dir=Path(tmpdir),
                    build_platform_images=False,
                    include_frontend_build=False,
                    pull_prometheus=False,
                    offline_prometheus_image=False,
                )

        self.assertIn("缺少 migration.script", str(caught.exception))
