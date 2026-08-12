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
        if "SMARTX_IMAGE_IDENTITY" in " ".join(command):
            image = command[command.index("--entrypoint") + 2] if "--entrypoint" in command else command[-2]
            version = image.rsplit(":", 1)[-1]
            if version == "v0.5.1u2":
                runner_version = "v0.3.0"
            else:
                runner_version = "v0.3.1"
            if version:
                return (
                    f'SMARTX_IMAGE_IDENTITY:{{"version_file":"{version}",'
                    f'"runner_version_file":"{runner_version}",'
                    f'"core_default_app_version":"{version}",'
                    f'"core_default_runner_version":"{runner_version}",'
                    f'"v2_default_app_version":"{version}",'
                    f'"v2_default_runner_version":"{runner_version}"}}\n'
                )
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
    def test_frontend_docker_context_excludes_local_build_artifacts(self) -> None:
        dockerignore = ROOT / "frontend/.dockerignore"
        self.assertTrue(dockerignore.is_file())
        ignored = {line.strip() for line in dockerignore.read_text(encoding="utf-8").splitlines() if line.strip()}

        self.assertIn("node_modules", ignored)
        self.assertIn("dist", ignored)
        self.assertIn("coverage", ignored)
        self.assertIn("*.tsbuildinfo", ignored)

    def test_platform_upgrade_builder_emits_v2_manifest_with_components(self) -> None:
        builder = _load_script("build_upgrade_package.py")
        builder.run = _fake_docker_run

        with tempfile.TemporaryDirectory() as tmpdir:
            package = builder.build_package(
                "v0.5.2",
                min_version="v0.5.0",
                output_dir=Path(tmpdir),
                build_images=False,
                allow_existing_images=True,
                include_frontend_build=False,
            )

            with tarfile.open(package, mode="r:gz") as archive:
                names = set(archive.getnames())
                manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))
                release_notes = archive.extractfile("release-notes.md").read().decode("utf-8")
                release_compose = archive.extractfile("project/docker-compose.release.yml").read().decode("utf-8")
                offline_compose = archive.extractfile("project/docker-compose.offline.yml").read().decode("utf-8")
                dev_compose = archive.extractfile("project/docker-compose.yml").read().decode("utf-8")

        self.assertEqual(manifest["schema_version"], "3")
        self.assertEqual(manifest["minimum_runner_protocol"], 1)
        self.assertEqual(manifest["minimum_runner_version"], "v0.3.1")
        self.assertIn("backup.v1", manifest["required_capabilities"])
        self.assertNotIn("filesystem.v1", manifest["required_capabilities"])
        self.assertIn("compose.v1", manifest["required_capabilities"])
        self.assertIn("compose.project.v1", manifest["required_capabilities"])
        self.assertNotIn("backup.create", manifest["required_capabilities"])
        self.assertNotIn("compose.project_migrate.v1", manifest["required_capabilities"])
        self.assertNotIn("script.sandbox.v1", manifest["required_capabilities"])
        self.assertEqual(manifest["package_id"], "smartx-capacity-insight-v0.5.2")
        self.assertEqual(manifest["version"], "v0.5.2")
        self.assertEqual(manifest["min_version"], "v0.5.0")
        self.assertEqual(manifest["compatibility"]["min_platform_version"], "v0.5.0")
        self.assertEqual(manifest["source_compatibility"]["supported_versions"], ["v0.5.0", "v0.5.1", "v0.5.1u1", "v0.5.1u2", "v0.5.2"])
        self.assertTrue(manifest["source_compatibility"]["allow_same_version"])
        self.assertEqual(
            manifest["environment_transitions"],
            [
                {
                    "from_project": "smartx-storage-forecast",
                    "from_network": "smartx-storage-forecast_smartx-net",
                    "to_project": "smartx-hci-capacity-insight",
                    "to_network": "smartx-hci-capacity-insight-net",
                    "versions": ["v0.5.0", "v0.5.1", "v0.5.1u1", "v0.5.1u2"],
                    "directory_transition": {
                        "target_root": "/data/smartx-storage-forecast",
                        "project_path": "/data/smartx-storage-forecast/project",
                        "app_data_path": "/data/smartx-storage-forecast/app",
                        "prometheus_data_path": "/data/smartx-storage-forecast/prometheus",
                        "upgrades_path": "/data/smartx-storage-forecast/upgrades",
                        "backups_path": "/data/smartx-storage-forecast/backups",
                        "exports_path": "/data/smartx-storage-forecast/exports",
                        "compose_runtime_path": "/data/smartx-storage-forecast/compose-runtime",
                        "legacy_app_data_paths": ["/data/smartx-capacity-insight-data/app", "/data"],
                        "legacy_prometheus_data_paths": ["/data/smartx-capacity-insight-data/prometheus", "/prometheus-data"],
                        "env_file_migration": {
                            "target": "/data/smartx-storage-forecast/project/.env",
                            "legacy_candidates": ["/opt/smartx-storage-forecast/.env"],
                            "preserve_existing": True,
                            "sanitize_image_tags": True,
                            "fallback_defaults": True,
                            "require_credential_decryption": True,
                        },
                        "helper_image": "nazawsze/smartx-hci-capacity-insight-web-api:v0.5.2",
                    },
                }
            ],
        )
        self.assertEqual(
            manifest["directory_transition"],
            {
                "target_root": "/data/smartx-storage-forecast",
                "project_path": "/data/smartx-storage-forecast/project",
                "app_data_path": "/data/smartx-storage-forecast/app",
                "prometheus_data_path": "/data/smartx-storage-forecast/prometheus",
                "upgrades_path": "/data/smartx-storage-forecast/upgrades",
                "backups_path": "/data/smartx-storage-forecast/backups",
                "exports_path": "/data/smartx-storage-forecast/exports",
                "compose_runtime_path": "/data/smartx-storage-forecast/compose-runtime",
                "legacy_app_data_paths": ["/data/smartx-capacity-insight-data/app", "/data"],
                "legacy_prometheus_data_paths": ["/data/smartx-capacity-insight-data/prometheus", "/prometheus-data"],
                "env_file_migration": {
                    "target": "/data/smartx-storage-forecast/project/.env",
                    "legacy_candidates": ["/opt/smartx-storage-forecast/.env"],
                    "preserve_existing": True,
                    "sanitize_image_tags": True,
                    "fallback_defaults": True,
                    "require_credential_decryption": True,
                },
                "helper_image": "nazawsze/smartx-hci-capacity-insight-web-api:v0.5.2",
            },
        )
        self.assertEqual(
            manifest["legacy_cleanup"],
            {
                "helper_image": "nazawsze/smartx-hci-capacity-insight-web-api:v0.5.2",
                "legacy_projects": ["smartx-storage-forecast"],
                "legacy_networks": ["smartx-storage-forecast_smartx-net"],
                "legacy_paths": [
                    "/opt/smartx-storage-forecast",
                    "/data/upgrades",
                    "/data/backups",
                    "/data/exports",
                    "/data/compose-runtime",
                    "/data/smartx-capacity-insight-data",
                    "/prometheus-data",
                ],
                "target_app_residual_paths": [],
                "protected_paths": [
                    "/data/smartx-storage-forecast",
                    "/data/smartx-storage-forecast/project",
                    "/data/smartx-storage-forecast/app",
                    "/data/smartx-storage-forecast/prometheus",
                    "/data/smartx-storage-forecast/upgrades",
                    "/data/smartx-storage-forecast/backups",
                    "/data/smartx-storage-forecast/exports",
                    "/data/smartx-storage-forecast/compose-runtime",
                ],
                "required_health": {
                    "version": "v0.5.2",
                    "runner_version": "v0.3.1",
                    "checks": ["directories", "database", "prometheus"],
                },
                "data_migration_guard": {
                    "target_db_path": "/data/smartx-storage-forecast/app/smartx.db",
                    "legacy_db_paths": [
                        "/data/smartx-capacity-insight-data/app/smartx.db",
                        "/data/smartx.db",
                    ],
                },
            },
        )
        self.assertIs(manifest["project_files"], True)
        self.assertIs(manifest["database_migration"], False)
        self.assertNotIn("migration", manifest)
        self.assertEqual(manifest["restart_services"], ["web-api", "collector-worker", "frontend", "prometheus", "upgrade-runner"])
        self.assertEqual([component["type"] for component in manifest["components"]], ["platform"])
        platform = manifest["components"][0]
        self.assertEqual(platform["services"], ["web-api", "collector-worker", "frontend", "prometheus", "upgrade-runner"])
        self.assertEqual(
            {image["archive"] for image in platform["images"]},
            {"images/web-api.tar", "images/collector-worker.tar", "images/frontend.tar", None},
        )
        self.assertEqual({image["service"] for image in platform["images"]}, {"web-api", "collector-worker", "frontend", "upgrade-runner"})
        runner_image = next(image for image in platform["images"] if image["service"] == "upgrade-runner")
        self.assertEqual(runner_image["image"], "nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.1")
        self.assertIsNone(runner_image.get("archive"))
        self.assertNotIn("images/prometheus.tar", names)
        self.assertNotIn("images/upgrade-runner.tar", names)
        self.assertNotIn("scripts/migrate.sh", names)
        self.assertIn("checksums.sha256", names)
        self.assertFalse(any(name.startswith("project/.env") or name.endswith("smartx.db") for name in names))
        self.assertIn("/data/smartx-storage-forecast/project", release_compose)
        self.assertIn("/data/smartx-storage-forecast/prometheus:/prometheus", release_compose)
        self.assertIn("subnet: 10.249.251.0/24", release_compose)
        self.assertNotIn("/opt/smartx-storage-forecast", release_compose)
        self.assertNotIn("/data/smartx-capacity-insight-data", release_compose)
        self.assertNotIn("- /data/compose-runtime:", release_compose)
        self.assertNotIn("SMARTX_HOST_COMPOSE_RUNTIME_PATH: /data/compose-runtime", release_compose)
        for compose_text in (release_compose, offline_compose, dev_compose):
            self.assertNotIn("SMARTX_IMAGE_TAG", compose_text)
            self.assertNotIn("SMARTX_RUNNER_IMAGE_TAG", compose_text)
            self.assertIn("smartx-hci-capacity-insight-web-api:v0.5.2", compose_text)
            self.assertIn("smartx-hci-capacity-insight-collector-worker:v0.5.2", compose_text)
            self.assertIn("smartx-hci-capacity-insight-frontend:v0.5.2", compose_text)
            self.assertIn("smartx-hci-capacity-insight-upgrade-runner:v0.3.1", compose_text)
            self.assertIn("prom/prometheus:v2.55.1", compose_text)
            self.assertIn("chmod 600 /data/smartx-storage-forecast/project/.env", compose_text)
            self.assertIn("exec python -m app.upgrade_runner.main", compose_text)
            web_api_section = compose_text.split("  web-api:\n", 1)[1].split("  collector-worker:\n", 1)[0]
            self.assertIn("chmod 600 /run/smartx-runtime.env", web_api_section)
            self.assertIn("exec uvicorn app.v2.main:app --host 0.0.0.0 --port 8000", web_api_section)
            self.assertIn("/data/smartx-storage-forecast/project/.env:/run/smartx-runtime.env", web_api_section)
        self.assertIn("/data/smartx-storage-forecast", release_notes)
        from app.v2.upgrade.compiler import compile_execution_plan

        plan = compile_execution_plan(manifest).to_dict()
        self.assertNotIn("script.run_sandboxed", {action["type"] for action in plan["actions"]})
        action_types = [action["type"] for action in plan["actions"]]
        self.assertIn("filesystem.prepare", action_types)
        self.assertIn("compose.project_migrate", action_types)
        self.assertLess(action_types.index("filesystem.prepare"), action_types.index("files.sync"))
        self.assertLess(action_types.index("compose.project_migrate"), action_types.index("compose.apply"))
        self.assertLess(action_types.index("filesystem.prepare"), action_types.index("compose.apply"))
        self.assertIn("compose.project.v1", plan["required_capabilities"])
        self.assertIn("filesystem.v1", plan["required_capabilities"])
        self.assertIn("task.recovery.v1", plan["required_capabilities"])
        self.assertNotIn("runner.handoff.v1", manifest["required_capabilities"])
        self.assertNotIn("compose.project_migrate.v1", plan["required_capabilities"])
        self.assertIn("task.migrate_runtime_state", action_types)
        self.assertIn("task.sync_runtime_state", action_types)
        self.assertTrue(manifest["post_upgrade"]["auto_collection"])
        self.assertIn("post_upgrade.schedule_collection", action_types)
        self.assertIn("post_upgrade.schedule_cleanup", action_types)
        self.assertIn("runner.schedule_target_runtime_handoff", action_types)
        self.assertNotIn("runner.handoff_target_runtime", action_types)
        self.assertNotIn("runner.stop_legacy_runtime", action_types)
        self.assertNotIn("legacy.cleanup", action_types)
        self.assertLess(action_types.index("files.sync"), action_types.index("task.migrate_runtime_state"))
        self.assertLess(action_types.index("task.migrate_runtime_state"), action_types.index("compose.override"))
        self.assertLess(action_types.index("health.http"), action_types.index("task.sync_runtime_state"))
        self.assertLess(action_types.index("task.sync_runtime_state"), action_types.index("post_upgrade.schedule_collection"))
        self.assertLess(action_types.index("post_upgrade.schedule_collection"), action_types.index("post_upgrade.schedule_cleanup"))
        self.assertLess(action_types.index("task.sync_runtime_state"), action_types.index("post_upgrade.schedule_cleanup"))
        self.assertLess(action_types.index("post_upgrade.schedule_cleanup"), action_types.index("runner.schedule_target_runtime_handoff"))
        schedule = next(action for action in plan["actions"] if action["type"] == "post_upgrade.schedule_cleanup")
        self.assertEqual(schedule["params"]["parent_task_status"], "success")
        self.assertEqual(schedule["params"]["cleanup_task_type"], "post_upgrade_cleanup")
        cutover = next(action for action in plan["actions"] if action["type"] == "runner.schedule_target_runtime_handoff")
        self.assertEqual(cutover["params"]["image"], "nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.1")
        self.assertEqual(cutover["params"]["compose_project"], "smartx-hci-capacity-insight")
        self.assertEqual(cutover["params"]["network_name"], "smartx-hci-capacity-insight-net")
        self.assertEqual(cutover["params"]["project_path"], "/data/smartx-storage-forecast/project")
        self.assertEqual(cutover["params"]["upgrades_path"], "/data/smartx-storage-forecast/upgrades")
        self.assertEqual(cutover["params"]["compose_runtime_path"], "/data/smartx-storage-forecast/compose-runtime")
        compose_override = next(action for action in plan["actions"] if action["type"] == "compose.override")
        override_images = {image["service"]: image["image"] for image in compose_override["params"]["images"]}
        self.assertEqual(override_images["upgrade-runner"], "nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.1")
        compose_apply = next(action for action in plan["actions"] if action["type"] == "compose.apply")
        self.assertEqual(compose_apply["params"]["services"], ["collector-worker", "frontend", "prometheus", "web-api"])

    def test_v051u2_package_does_not_include_legacy_cleanup(self) -> None:
        builder = _load_script("build_upgrade_package.py")
        builder.run = _fake_docker_run

        with tempfile.TemporaryDirectory() as tmpdir:
            package = builder.build_package(
                "v0.5.1u2",
                min_version="v0.5.0",
                output_dir=Path(tmpdir),
                build_images=False,
                allow_existing_images=True,
                include_frontend_build=False,
                check_version_metadata=False,
            )

            with tarfile.open(package, mode="r:gz") as archive:
                manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))

        self.assertNotIn("legacy_cleanup", manifest)

    def test_v051u2_bridge_package_keeps_runner_v030_compatibility(self) -> None:
        builder = _load_script("build_upgrade_package.py")
        builder.run = _fake_docker_run

        with tempfile.TemporaryDirectory() as tmpdir:
            package = builder.build_package(
                "v0.5.1u2",
                min_version="v0.5.0",
                output_dir=Path(tmpdir),
                build_images=False,
                allow_existing_images=True,
                include_frontend_build=False,
                check_version_metadata=False,
            )

            with tarfile.open(package, mode="r:gz") as archive:
                manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))
                release_compose = archive.extractfile("project/docker-compose.release.yml").read().decode("utf-8")
                dev_compose = archive.extractfile("project/docker-compose.yml").read().decode("utf-8")
                offline_compose = archive.extractfile("project/docker-compose.offline.yml").read().decode("utf-8")

        self.assertNotIn("minimum_runner_version", manifest)
        self.assertNotIn("environment_transitions", manifest)
        self.assertNotIn("legacy_cleanup", manifest)
        self.assertNotIn("runner.handoff.v1", manifest["required_capabilities"])
        self.assertNotIn("compose.project.v1", manifest["required_capabilities"])
        self.assertNotIn("backup.v1", manifest["required_capabilities"])
        self.assertNotIn("image.v1", manifest["required_capabilities"])
        self.assertNotIn("files.v1", manifest["required_capabilities"])
        self.assertNotIn("compose.v1", manifest["required_capabilities"])
        self.assertNotIn("health.v1", manifest["required_capabilities"])
        self.assertNotIn("rollback.v1", manifest["required_capabilities"])
        from app.v2.upgrade.compiler import compile_execution_plan

        action_types = [action["type"] for action in compile_execution_plan(manifest).to_dict()["actions"]]
        self.assertNotIn("runner.stop_legacy_runtime", action_types)
        self.assertNotIn("legacy.cleanup", action_types)
        self.assertEqual(
            manifest["source_compatibility"]["supported_versions"],
            ["v0.5.0", "v0.5.1", "v0.5.1u1", "v0.5.1u2"],
        )
        for compose_text in (release_compose, dev_compose, offline_compose):
            self.assertIn("name: smartx-storage-forecast", compose_text)
            self.assertIn("SMARTX_COMPOSE_PROJECT_NAME: smartx-storage-forecast", compose_text)
            self.assertIn("SMARTX_PROJECT_PATH: /opt/smartx-storage-forecast", compose_text)
            self.assertIn("/data/smartx-capacity-insight-data/app:/data", compose_text)
            self.assertIn("/data/upgrades:/data/upgrades", compose_text)
            self.assertIn("/data/backups:/data/backups", compose_text)
            self.assertIn("/data/exports:/data/exports", compose_text)
            self.assertIn("/data/compose-runtime:/data/compose-runtime", compose_text)
            self.assertIn("/prometheus-data:/prometheus-data", compose_text)
            self.assertIn("name: smartx-storage-forecast_smartx-net", compose_text)
            self.assertIn("subnet: 10.249.249.0/24", compose_text)
            self.assertNotIn("SMARTX_IMAGE_TAG", compose_text)
            self.assertNotIn("SMARTX_RUNNER_IMAGE_TAG", compose_text)
            self.assertIn("web-api:v0.5.1u2", compose_text)
            self.assertIn("collector-worker:v0.5.1u2", compose_text)
            self.assertIn("frontend:v0.5.1u2", compose_text)
            self.assertIn("upgrade-runner:v0.3.0", compose_text)
            self.assertIn("chmod 600 /opt/smartx-storage-forecast/.env", compose_text)
            self.assertIn("exec python -m app.upgrade_runner.main", compose_text)
            web_api_section = compose_text.split("  web-api:\n", 1)[1].split("  collector-worker:\n", 1)[0]
            self.assertIn("chmod 600 /run/smartx-runtime.env", web_api_section)
            self.assertIn("exec uvicorn app.v2.main:app --host 0.0.0.0 --port 8000", web_api_section)
            self.assertIn("/opt/smartx-storage-forecast/.env:/run/smartx-runtime.env", web_api_section)
            self.assertNotIn("smartx-hci-capacity-insight-net", compose_text)
            self.assertNotIn("/data/smartx-storage-forecast", compose_text)
            self.assertNotIn("10.249.251.0/24", compose_text)

    def test_v051u2_bridge_package_builds_with_temporary_version_metadata(self) -> None:
        builder = _load_script("build_upgrade_package.py")
        builder.run = _fake_docker_run

        with tempfile.TemporaryDirectory() as tmpdir:
            package = builder.build_package(
                "v0.5.1u2",
                min_version="v0.5.0",
                output_dir=Path(tmpdir),
                build_images=False,
                allow_existing_images=True,
                include_frontend_build=False,
            )

            with tarfile.open(package, mode="r:gz") as archive:
                readme = archive.extractfile("project/README.md").read().decode("utf-8")
                manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))

        self.assertEqual(manifest["version"], "v0.5.1u2")
        self.assertIn("Version: `v0.5.1u2`", readme)

    def test_platform_builder_rejects_no_build_without_explicit_existing_image_allowance(self) -> None:
        builder = _load_script("build_upgrade_package.py")
        builder.run = _fake_docker_run

        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(SystemExit) as caught:
                builder.build_package(
                    "v0.5.1u2",
                    min_version="v0.5.0",
                    output_dir=Path(tmpdir),
                    build_images=False,
                    include_frontend_build=False,
                    check_version_metadata=False,
                )

        self.assertIn("--allow-existing-images", str(caught.exception))

    def test_docker_build_temporarily_writes_target_version_metadata_and_restores_sources(self) -> None:
        builder = _load_script("build_upgrade_package.py")
        original_version = builder.VERSION_FILE.read_text(encoding="utf-8")
        original_runner = builder.RUNNER_VERSION_FILE.read_text(encoding="utf-8")
        original_core = (ROOT / "backend/app/core/config.py").read_text(encoding="utf-8")
        original_v2 = (ROOT / "backend/app/v2/config.py").read_text(encoding="utf-8")
        observed: dict[str, str | list[str]] = {}

        def observe_build(command: list[str], cwd: Path = ROOT) -> str:
            observed["command"] = command
            observed["version_file"] = builder.VERSION_FILE.read_text(encoding="utf-8").strip()
            observed["runner_version_file"] = builder.RUNNER_VERSION_FILE.read_text(encoding="utf-8").strip()
            observed["core_config"] = (ROOT / "backend/app/core/config.py").read_text(encoding="utf-8")
            observed["v2_config"] = (ROOT / "backend/app/v2/config.py").read_text(encoding="utf-8")
            return ""

        builder.run = observe_build

        builder.docker_build("v0.5.1u2", include_frontend=False)

        self.assertEqual(observed["version_file"], "v0.5.1u2")
        self.assertEqual(observed["runner_version_file"], "v0.3.0")
        self.assertIn('DEFAULT_APP_VERSION = "v0.5.1u2"', str(observed["core_config"]))
        self.assertIn('DEFAULT_RUNNER_VERSION = "v0.3.0"', str(observed["core_config"]))
        self.assertIn('DEFAULT_APP_VERSION = "v0.5.1u2"', str(observed["v2_config"]))
        self.assertIn('DEFAULT_RUNNER_VERSION = "v0.3.0"', str(observed["v2_config"]))
        self.assertEqual(observed["command"][:3], ["env", "SMARTX_IMAGE_TAG=v0.5.1u2", "SMARTX_RUNNER_IMAGE_TAG=v0.3.0"])
        self.assertEqual(builder.VERSION_FILE.read_text(encoding="utf-8"), original_version)
        self.assertEqual(builder.RUNNER_VERSION_FILE.read_text(encoding="utf-8"), original_runner)
        self.assertEqual((ROOT / "backend/app/core/config.py").read_text(encoding="utf-8"), original_core)
        self.assertEqual((ROOT / "backend/app/v2/config.py").read_text(encoding="utf-8"), original_v2)

    def test_docker_build_creates_temporary_empty_env_file_when_missing_and_removes_it(self) -> None:
        builder = _load_script("build_upgrade_package.py")

        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            builder.ENV_FILE = env_file
            observed: dict[str, bool | str] = {}

            def observe_build(command: list[str], cwd: Path = ROOT) -> str:
                observed["env_exists_during_build"] = env_file.exists()
                observed["env_content_during_build"] = env_file.read_text(encoding="utf-8")
                return ""

            builder.run = observe_build

            builder.docker_build("v0.5.1u2", include_frontend=False)

            self.assertIs(observed["env_exists_during_build"], True)
            self.assertEqual(observed["env_content_during_build"], "")
            self.assertFalse(env_file.exists())

    def test_docker_build_keeps_existing_env_file_unchanged(self) -> None:
        builder = _load_script("build_upgrade_package.py")

        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text("SMARTX_SECRET_KEY=keep-me\n", encoding="utf-8")
            builder.ENV_FILE = env_file

            def observe_build(command: list[str], cwd: Path = ROOT) -> str:
                self.assertEqual(env_file.read_text(encoding="utf-8"), "SMARTX_SECRET_KEY=keep-me\n")
                return ""

            builder.run = observe_build

            builder.docker_build("v0.5.1u2", include_frontend=False)

            self.assertEqual(env_file.read_text(encoding="utf-8"), "SMARTX_SECRET_KEY=keep-me\n")

    def test_platform_builder_rejects_v051u2_web_api_image_with_v052_identity(self) -> None:
        builder = _load_script("build_upgrade_package.py")

        def polluted_run(command: list[str], cwd: Path = ROOT) -> str:
            if command[:2] == ["docker", "run"] and "SMARTX_IMAGE_IDENTITY" in " ".join(command):
                return (
                    'SMARTX_IMAGE_IDENTITY:{"version_file":"v0.5.2",'
                    '"runner_version_file":"v0.3.1",'
                    '"core_default_app_version":"v0.5.2",'
                    '"core_default_runner_version":"v0.3.1",'
                    '"v2_default_app_version":"v0.5.2",'
                    '"v2_default_runner_version":"v0.3.1"}\n'
                )
            return _fake_docker_run(command, cwd=cwd)

        builder.run = polluted_run

        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(SystemExit) as caught:
                builder.build_package(
                    "v0.5.1u2",
                    min_version="v0.5.0",
                    output_dir=Path(tmpdir),
                    build_images=False,
                    allow_existing_images=True,
                    include_frontend_build=False,
                    check_version_metadata=False,
                )

        self.assertIn("web-api image identity mismatch", str(caught.exception))
        self.assertIn("v0.5.1u2", str(caught.exception))
        self.assertIn("v0.5.2", str(caught.exception))

    def test_platform_builder_accepts_version_specific_web_api_runner_baseline(self) -> None:
        builder = _load_script("build_upgrade_package.py")
        builder.run = _fake_docker_run

        with tempfile.TemporaryDirectory() as tmpdir:
            package_v051u2 = builder.build_package(
                "v0.5.1u2",
                min_version="v0.5.0",
                output_dir=Path(tmpdir),
                build_images=False,
                allow_existing_images=True,
                include_frontend_build=False,
                check_version_metadata=False,
            )
            package_v052 = builder.build_package(
                "v0.5.2",
                min_version="v0.5.0",
                output_dir=Path(tmpdir),
                build_images=False,
                allow_existing_images=True,
                include_frontend_build=False,
                check_version_metadata=False,
            )

            with tarfile.open(package_v051u2, mode="r:gz") as archive:
                manifest_v051u2 = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))
            with tarfile.open(package_v052, mode="r:gz") as archive:
                manifest_v052 = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))

        self.assertNotIn("minimum_runner_version", manifest_v051u2)
        self.assertEqual(manifest_v052["minimum_runner_version"], "v0.3.1")

    def test_package_identity_verifier_loads_package_image_tar(self) -> None:
        builder = _load_script("build_upgrade_package.py")
        builder.run = _fake_docker_run
        verifier = _load_script("verify_upgrade_package_identity.py")
        commands: list[list[str]] = []

        def verifier_run(command: list[str], cwd: Path = ROOT) -> str:
            commands.append(command)
            if command[:2] == ["docker", "load"]:
                return "Loaded image: package-loaded-web-api:v0.5.1u2\n"
            if command[:2] == ["docker", "run"] and "SMARTX_IMAGE_IDENTITY" in " ".join(command):
                return (
                    'SMARTX_IMAGE_IDENTITY:{"version_file":"v0.5.1u2",'
                    '"runner_version_file":"v0.3.0",'
                    '"core_default_app_version":"v0.5.1u2",'
                    '"core_default_runner_version":"v0.3.0",'
                    '"v2_default_app_version":"v0.5.1u2",'
                    '"v2_default_runner_version":"v0.3.0"}\n'
                )
            if command[:3] == ["docker", "image", "rm"]:
                return ""
            return ""

        verifier.run = verifier_run

        with tempfile.TemporaryDirectory() as tmpdir:
            package = builder.build_package(
                "v0.5.1u2",
                min_version="v0.5.0",
                output_dir=Path(tmpdir),
                build_images=False,
                allow_existing_images=True,
                include_frontend_build=False,
                check_version_metadata=False,
            )

            result = verifier.verify_package(package, expected_version="v0.5.1u2")

        self.assertEqual(result["version"], "v0.5.1u2")
        self.assertEqual(result["web_api_identity"]["version_file"], "v0.5.1u2")
        self.assertTrue(any(command[:2] == ["docker", "load"] and "images/web-api.tar" in command[-1] for command in commands))
        self.assertFalse(any("nazawsze/smartx-hci-capacity-insight-web-api:v0.5.1u2" in command for command in commands))

    def test_platform_builder_includes_intermediate_sqlite_migrations_for_cross_version_upgrade(self) -> None:
        builder = _load_script("build_upgrade_package.py")
        builder.run = _fake_docker_run

        with tempfile.TemporaryDirectory() as tmpdir:
            registry = Path(tmpdir) / "registry.json"
            registry.write_text(
                json.dumps(
                    [
                        {
                            "id": "20260612_v0_5_3_sqlite_schema",
                            "version": "v0.5.3",
                            "description": "Add v0.5.3 SQLite schema",
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
                allow_existing_images=True,
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
        self.assertEqual([step["id"] for step in manifest["migration_steps"]], ["20260612_v0_5_3_sqlite_schema"])
        self.assertEqual(manifest["migration_steps"][0]["version"], "v0.5.3")
        self.assertTrue(manifest["migration_steps"][0]["script_sha256"])
        self.assertIn("migrations/run_migrations.py", names)
        self.assertIn("20260612_v0_5_3_sqlite_schema", runner)
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
                            "id": "20260612_v0_5_3_sqlite_schema",
                            "version": "v0.5.3",
                            "description": "Add v0.5.3 SQLite schema",
                            "database": "sqlite",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            package = builder.build_package(
                "v0.5.3",
                min_version="v0.5.3",
                output_dir=Path(tmpdir),
                build_images=False,
                allow_existing_images=True,
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
                "id": "20260612_v0_5_3_sqlite_schema",
                "version": "v0.5.3",
                "description": "Add v0.5.3 SQLite schema",
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
            self.assertEqual(rows, [("20260612_v0_5_3_sqlite_schema", "v0.5.3", "Add v0.5.3 SQLite schema", public_steps[0]["script_sha256"])])
            self.assertIsNotNone(probe)
            self.assertIn("note", columns)
            self.assertIn("applied 20260612_v0_5_3_sqlite_schema", first.stdout)
            self.assertIn("skip 20260612_v0_5_3_sqlite_schema", second.stdout)

    def test_migration_registry_rejects_invalid_sql_shape(self) -> None:
        builder = _load_script("build_upgrade_package.py")

        with tempfile.TemporaryDirectory() as tmpdir:
            registry = Path(tmpdir) / "registry.json"
            registry.write_text(
                json.dumps(
                    [
                        {
                            "id": "bad_sql",
                            "version": "v0.5.3",
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
                            "version": "v0.5.3",
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
                        {"id": "dup", "version": "v0.5.3", "description": "A", "database": "sqlite"},
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
            package = builder.build_package("v0.3.1", "v0.2.1", Path(tmpdir), build_image=False)

            with tarfile.open(package, mode="r:gz") as archive:
                names = set(archive.getnames())
                manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))

        self.assertEqual(manifest["schema_version"], "3")
        self.assertEqual(manifest["minimum_runner_protocol"], 1)
        self.assertEqual(manifest["required_capabilities"], [])
        self.assertEqual(manifest["package_id"], "smartx-upgrade-runner-v0.3.1")
        self.assertEqual(manifest["version"], "v0.3.1")
        self.assertEqual(manifest["compatibility"]["min_runner_version"], "v0.2.1")
        self.assertEqual(manifest["restart_services"], ["upgrade-runner"])
        self.assertIs(manifest["project_files"], False)
        self.assertEqual(
            manifest["bootstrap_runner"],
            {
                "enabled": True,
                "target_project": "smartx-hci-capacity-insight",
                "target_network": "smartx-hci-capacity-insight-net",
                "target_subnet": "10.249.251.0/24",
                "target_root": "/data/smartx-storage-forecast",
            },
        )
        self.assertEqual([component["type"] for component in manifest["components"]], ["runner"])
        runner = manifest["components"][0]
        self.assertEqual(runner["services"], ["upgrade-runner"])
        self.assertEqual(runner["images"][0]["archive"], "images/upgrade-runner.tar")
        self.assertEqual(runner["images"][0]["image"], "nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.1")
        self.assertIn("checksums.sha256", names)
        verify_commands = [
            command
            for command in recorder.commands
            if command[:5] == ["docker", "run", "--rm", "--entrypoint", "python"]
            and command[5] == "nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.1"
        ]
        self.assertTrue(verify_commands)
        verify_script = verify_commands[0][-1]
        self.assertIn("post_upgrade.schedule_cleanup", verify_script)
        self.assertIn("post_upgrade.schedule_collection", verify_script)
        self.assertIn("runner.schedule_target_runtime_handoff", verify_script)
        self.assertIn("filesystem_prepare", verify_script)
        self.assertIn("env_file_migration", verify_script)
        self.assertIn("default_handlers", verify_script)

    def test_runner_component_builder_creates_temporary_env_for_compose_build(self) -> None:
        builder = _load_script("build_runner_component_package.py")
        env_file = builder.ROOT / ".env"
        original = env_file.read_text(encoding="utf-8") if env_file.exists() else None
        observations: list[tuple[str, bool, str]] = []

        def fake_run(command: list[str], cwd: Path = ROOT) -> str:
            if command[:5] == ["docker", "compose", "-f", "docker-compose.yml", "build"]:
                observations.append(("build", env_file.exists(), env_file.read_text(encoding="utf-8") if env_file.exists() else ""))
            if command[:2] == ["docker", "save"] and "-o" in command:
                output = Path(command[command.index("-o") + 1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(("fake-image:" + command[-1]).encode("utf-8"))
            return ""

        try:
            if env_file.exists():
                env_file.unlink()
            with tempfile.TemporaryDirectory() as tmpdir:
                builder.run = fake_run
                builder.build_package("v0.3.1", "v0.1.0", Path(tmpdir), build_image=True)

            self.assertEqual(observations, [("build", True, "")])
            self.assertFalse(env_file.exists())
        finally:
            if original is not None:
                env_file.write_text(original, encoding="utf-8")
            elif env_file.exists():
                env_file.unlink()

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
        self.assertNotIn("image.v1", manifest["required_capabilities"])
        self.assertIn("health.v1", manifest["required_capabilities"])
        self.assertNotIn("health.prometheus", manifest["required_capabilities"])
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
        self.assertIn("image.v1", manifest["required_capabilities"])
        self.assertNotIn("image.load", manifest["required_capabilities"])
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
                platform_version="v0.5.2",
                prometheus_version="v2.55.1",
                min_platform_version="v0.5.2",
                min_prometheus_version="v2.55.1",
                output_dir=Path(tmpdir),
                build_platform_images=False,
                include_frontend_build=False,
                allow_existing_images=True,
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

    def test_bundle_builder_preserves_v052_platform_transition_metadata(self) -> None:
        builder = _load_script("build_bundle_upgrade_package.py")
        platform_builder = _load_script("build_upgrade_package.py")
        prometheus_builder = _load_script("build_prometheus_component_package.py")
        platform_builder.run = _fake_docker_run
        prometheus_builder.run = _fake_docker_run
        builder.load_platform_builder = lambda: platform_builder
        builder.load_prometheus_builder = lambda: prometheus_builder

        with tempfile.TemporaryDirectory() as tmpdir:
            package = builder.build_package(
                platform_version="v0.5.2",
                prometheus_version="v2.55.1",
                min_platform_version="v0.5.0",
                min_prometheus_version="v2.55.1",
                output_dir=Path(tmpdir),
                build_platform_images=False,
                include_frontend_build=False,
                allow_existing_images=True,
                pull_prometheus=False,
                offline_prometheus_image=False,
            )

            with tarfile.open(package, mode="r:gz") as archive:
                manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))
                release_compose = archive.extractfile("platform/project/docker-compose.release.yml").read().decode("utf-8")

        self.assertEqual(manifest["minimum_runner_version"], "v0.3.1")
        self.assertIn("directory_transition", manifest)
        self.assertIn("environment_transitions", manifest)
        self.assertIn("legacy_cleanup", manifest)
        self.assertEqual(
            manifest["post_upgrade"],
            {
                "auto_collection": True,
                "create_cleanup_task": True,
                "cleanup_task_policy": "after_platform_health_success",
                "cleanup_failure_severity": "warning",
            },
        )
        self.assertEqual(manifest["directory_transition"]["target_root"], "/data/smartx-storage-forecast")
        self.assertEqual(manifest["legacy_cleanup"]["legacy_projects"], ["smartx-storage-forecast"])
        self.assertEqual(manifest["source_compatibility"]["supported_versions"], ["v0.5.0", "v0.5.1", "v0.5.1u1", "v0.5.1u2", "v0.5.2"])
        self.assertNotIn("SMARTX_IMAGE_TAG", release_compose)
        self.assertNotIn("SMARTX_RUNNER_IMAGE_TAG", release_compose)

        from app.v2.upgrade.compiler import compile_execution_plan

        action_types = [action["type"] for action in compile_execution_plan(manifest).to_dict()["actions"]]
        self.assertIn("filesystem.prepare", action_types)
        self.assertIn("compose.project_migrate", action_types)
        self.assertIn("task.migrate_runtime_state", action_types)
        self.assertIn("post_upgrade.schedule_collection", action_types)
        self.assertIn("post_upgrade.schedule_cleanup", action_types)
        self.assertIn("runner.schedule_target_runtime_handoff", action_types)

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
                            "id": "20260612_v0_5_3_sqlite_schema",
                            "version": "v0.5.3",
                            "description": "Add v0.5.3 SQLite schema",
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
                min_platform_version="v0.5.2",
                min_prometheus_version="v2.55.1",
                output_dir=tmp,
                build_platform_images=False,
                include_frontend_build=False,
                allow_existing_images=True,
                pull_prometheus=False,
                offline_prometheus_image=False,
            )

            with tarfile.open(package, mode="r:gz") as archive:
                names = set(archive.getnames())
                manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))

        self.assertIs(manifest["database_migration"], True)
        self.assertEqual(manifest["migration"]["script"], "platform/migrations/run_migrations.py")
        self.assertEqual([step["id"] for step in manifest["migration_steps"]], ["20260612_v0_5_3_sqlite_schema"])
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
                    platform_version="v0.5.2",
                    prometheus_version="v2.55.1",
                    min_platform_version="v0.5.2",
                    min_prometheus_version="v2.55.1",
                    output_dir=Path(tmpdir),
                    build_platform_images=False,
                    include_frontend_build=False,
                    allow_existing_images=True,
                    pull_prometheus=False,
                    offline_prometheus_image=False,
                )

        self.assertIn("缺少 migration.script", str(caught.exception))
