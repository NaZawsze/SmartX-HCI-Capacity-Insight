from __future__ import annotations

import importlib.util
import json
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
                "v0.5.0",
                min_version="v0.5.0",
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
        self.assertEqual(manifest["package_id"], "smartx-capacity-insight-v0.5.0")
        self.assertEqual(manifest["version"], "v0.5.0")
        self.assertEqual(manifest["compatibility"]["min_platform_version"], "v0.5.0")
        self.assertIs(manifest["project_files"], True)
        self.assertEqual(manifest["migration"]["script"], "scripts/migrate.sh")
        self.assertEqual(manifest["restart_services"], ["web-api", "collector-worker", "frontend"])
        self.assertEqual([component["type"] for component in manifest["components"]], ["platform"])
        platform = manifest["components"][0]
        self.assertEqual(platform["services"], ["web-api", "collector-worker", "frontend"])
        self.assertEqual(
            {image["archive"] for image in platform["images"]},
            {"images/web-api.tar", "images/collector-worker.tar", "images/frontend.tar"},
        )
        self.assertNotIn("images/upgrade-runner.tar", names)
        self.assertIn("checksums.sha256", names)
        self.assertFalse(any(name.startswith("project/.env") or name.endswith("smartx.db") for name in names))

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
                platform_version="v0.5.0",
                prometheus_version="v2.55.1",
                min_platform_version="v0.5.0",
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
        self.assertEqual(manifest["migration"]["script"], "platform/migrations/migrate.sh")
        self.assertIn("platform/images/web-api.tar", names)
        self.assertNotIn("observability/images/prometheus.tar", names)
        self.assertIn("platform/project/docker-compose.offline.yml", names)
        self.assertIn("checksums.sha256", names)
        self.assertNotIn("images/upgrade-runner.tar", names)
        self.assertNotIn("runner", {component["type"] for component in manifest["components"]})
        from app.v2.upgrade.compiler import compile_execution_plan

        plan = compile_execution_plan(manifest).to_dict()
        file_syncs = [action for action in plan["actions"] if action["type"] == "files.sync"]
        self.assertTrue(any(action["params"]["source"] == "observability/config" and action["params"].get("target") == "prometheus" for action in file_syncs))
        sync_action = next(action for action in plan["actions"] if action["type"] == "files.sync")
        self.assertEqual(sync_action["params"]["source"], "platform/project")
