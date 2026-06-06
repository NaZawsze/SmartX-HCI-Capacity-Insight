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


class V2PackageBuilderTest(unittest.TestCase):
    def test_platform_upgrade_builder_emits_v2_manifest_with_components(self) -> None:
        builder = _load_script("build_upgrade_package.py")
        builder.run = _fake_docker_run

        with tempfile.TemporaryDirectory() as tmpdir:
            package = builder.build_package(
                "v0.4.1",
                min_version="v0.4.0",
                output_dir=Path(tmpdir),
                build_images=False,
                include_frontend_build=False,
            )

            with tarfile.open(package, mode="r:gz") as archive:
                names = set(archive.getnames())
                manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))

        self.assertEqual(manifest["schema_version"], "2")
        self.assertEqual(manifest["package_id"], "smartx-capacity-insight-v0.4.1")
        self.assertEqual(manifest["version"], "v0.4.1")
        self.assertEqual(manifest["compatibility"]["min_platform_version"], "v0.4.0")
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
        self.assertFalse(any(name.startswith("project/.env") or name.endswith("smartx.db") for name in names))

    def test_runner_component_builder_emits_v2_manifest_with_runner_component(self) -> None:
        builder = _load_script("build_runner_component_package.py")
        builder.run = _fake_docker_run

        with tempfile.TemporaryDirectory() as tmpdir:
            package = builder.build_package("v0.2.2", "v0.2.1", Path(tmpdir), build_image=False)

            with tarfile.open(package, mode="r:gz") as archive:
                manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))

        self.assertEqual(manifest["schema_version"], "2")
        self.assertEqual(manifest["package_id"], "smartx-upgrade-runner-v0.2.2")
        self.assertEqual(manifest["version"], "v0.2.2")
        self.assertEqual(manifest["compatibility"]["min_runner_version"], "v0.2.1")
        self.assertEqual(manifest["restart_services"], ["upgrade-runner"])
        self.assertIs(manifest["project_files"], False)
        self.assertEqual([component["type"] for component in manifest["components"]], ["runner"])
        runner = manifest["components"][0]
        self.assertEqual(runner["services"], ["upgrade-runner"])
        self.assertEqual(runner["images"][0]["archive"], "images/upgrade-runner.tar")
        self.assertEqual(runner["images"][0]["image"], "nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.2.2")
