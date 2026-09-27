from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_runner_delivery_consistency.py"
REPO_ACTIONS_SOURCE = (ROOT / "backend" / "app" / "upgrade_runner" / "actions.py").read_text(encoding="utf-8")

_spec = importlib.util.spec_from_file_location("verify_runner_delivery_consistency", SCRIPT)
gate = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(gate)


def _tar_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, content in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def _image_archive(version: str, actions_source: str, *, include_actions: bool = True, include_version: bool = True) -> bytes:
    entries: dict[str, bytes] = {}
    if include_version:
        entries["app/RUNNER_VERSION"] = (version + "\n").encode("utf-8")
    if include_actions:
        entries["app/app/upgrade_runner/actions.py"] = actions_source.encode("utf-8")
    layer = _tar_bytes(entries)
    docker_manifest = [
        {
            "Config": "blobs/sha256/config",
            "RepoTags": [f"{gate.RUNNER_IMAGE_REPO}:{version}"],
            "Layers": ["blobs/sha256/layer0"],
        }
    ]
    return _tar_bytes(
        {
            "manifest.json": json.dumps(docker_manifest).encode("utf-8"),
            "blobs/sha256/layer0": layer,
            "blobs/sha256/config": b"{}",
        }
    )


def _make_package(
    path: Path,
    version: str,
    *,
    image_version: str | None = None,
    actions_source: str = REPO_ACTIONS_SOURCE,
    archive_rel: str = "images/upgrade-runner.tar",
    sha_override: str | None = None,
    include_image_entry: bool = True,
    min_runner_version: str | None = None,
    include_actions_in_image: bool = True,
    include_version_in_image: bool = True,
) -> Path:
    image_bytes = _image_archive(
        image_version or version,
        actions_source,
        include_actions=include_actions_in_image,
        include_version=include_version_in_image,
    )
    manifest: dict = {
        "schema_version": "3",
        "product": "smartx-upgrade-runner",
        "component": "upgrade-runner",
        "version": version,
        "min_version": version if min_runner_version is None else min_runner_version,
        "package_type": "component",
        "compatibility": {"min_runner_version": version if min_runner_version is None else min_runner_version},
        "components": [{"type": "runner", "services": ["upgrade-runner"], "images": []}],
    }
    if include_image_entry:
        manifest["components"][0]["images"].append(
            {
                "service": "upgrade-runner",
                "image": f"{gate.RUNNER_IMAGE_REPO}:{version}",
                "archive": archive_rel,
                "sha256": sha_override or hashlib.sha256(image_bytes).hexdigest(),
            }
        )
    with tarfile.open(path, "w:gz") as archive:
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_bytes)
        archive.addfile(info, io.BytesIO(manifest_bytes))
        if include_image_entry:
            image_info = tarfile.TarInfo(archive_rel)
            image_info.size = len(image_bytes)
            archive.addfile(image_info, io.BytesIO(image_bytes))
    return path


class RepoChecksTest(unittest.TestCase):
    def test_repo_version_is_parseable(self):
        version = gate.read_repo_runner_version()
        self.assertTrue(version.startswith("v"))
        self.assertEqual(version, (ROOT / "RUNNER_VERSION").read_text(encoding="utf-8").strip())

    def test_repo_actions_parsed_from_source_without_import(self):
        actions = gate.parse_repo_actions()
        self.assertIn(gate.REQUIRED_ACTION, actions)
        self.assertGreaterEqual(len(actions), 20)
        self.assertEqual(len(actions), len(set(actions)))

    def test_source_compose_literal_tags_pass(self):
        version = gate.read_repo_runner_version()
        results = gate.check_source_compose(version)
        self.assertEqual({item["status"] for item in results}, {"PASS"})
        self.assertEqual(len(results), len(gate.SOURCE_COMPOSE_FILES))

    def test_verify_skips_optional_checks_without_arguments(self):
        result = gate.verify()
        self.assertTrue(result["ok"])
        self.assertIn("package_image", result["skipped"])
        self.assertIn("dockerhub_tag", result["skipped"])
        self.assertEqual(result["failures"], [])


class ImageArchiveTest(unittest.TestCase):
    def _payload(self, **kwargs):
        return gate.inspect_image_archive(_image_archive(**kwargs))

    def test_extracted_payload_matches_repo(self):
        version = gate.read_repo_runner_version()
        payload = self._payload(version=version, actions_source=REPO_ACTIONS_SOURCE)
        self.assertEqual(payload["runner_version"], version)
        self.assertEqual(payload["actions_md5"], gate.md5_file(gate.ACTIONS_FILE))
        self.assertEqual(payload["actions"], gate.parse_repo_actions())
        self.assertEqual(payload["layer_count"], 1)

    def test_compare_probe_passes_for_matching_payload(self):
        version = gate.read_repo_runner_version()
        payload = self._payload(version=version, actions_source=REPO_ACTIONS_SOURCE)
        results = gate.compare_probe(payload, version, gate.parse_repo_actions(), "package image")
        self.assertEqual({item["status"] for item in results}, {"PASS"})

    def test_foreign_actions_source_fails(self):
        version = gate.read_repo_runner_version()
        payload = self._payload(version=version, actions_source=REPO_ACTIONS_SOURCE + "\n# foreign build\n")
        results = gate.compare_probe(payload, version, gate.parse_repo_actions(), "package image")
        self.assertIn("FAIL", {item["status"] for item in results})

    def test_image_version_mismatch_fails(self):
        version = gate.read_repo_runner_version()
        payload = self._payload(version="v0.3.1", actions_source=REPO_ACTIONS_SOURCE)
        results = gate.compare_probe(payload, version, gate.parse_repo_actions(), "package image")
        self.assertIn("FAIL", {item["status"] for item in results})

    def test_missing_version_file_reports_incomplete_payload(self):
        version = gate.read_repo_runner_version()
        payload = self._payload(version=version, actions_source=REPO_ACTIONS_SOURCE, include_version=False)
        self.assertIsNone(payload.get("runner_version"))


class PackageManifestTest(unittest.TestCase):
    def test_matching_package_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            version = gate.read_repo_runner_version()
            package = _make_package(Path(tmpdir) / "runner.tar.gz", version)
            results, archive_rel = gate.check_package_manifest(package, version)
        self.assertEqual(archive_rel, "images/upgrade-runner.tar")
        self.assertEqual({item["status"] for item in results}, {"PASS"})

    def test_version_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            version = gate.read_repo_runner_version()
            package = _make_package(Path(tmpdir) / "runner.tar.gz", "v0.3.1")
            results, _ = gate.check_package_manifest(package, version)
        self.assertIn("FAIL", {item["status"] for item in results})

    def test_archive_sha_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            version = gate.read_repo_runner_version()
            package = _make_package(Path(tmpdir) / "runner.tar.gz", version, sha_override="0" * 64)
            results, _ = gate.check_package_manifest(package, version)
        self.assertIn("FAIL", {item["status"] for item in results})

    def test_missing_image_entry_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            version = gate.read_repo_runner_version()
            package = _make_package(Path(tmpdir) / "runner.tar.gz", version, include_image_entry=False)
            results, archive_rel = gate.check_package_manifest(package, version)
        self.assertIsNone(archive_rel)
        self.assertIn("FAIL", {item["status"] for item in results})

    def test_min_runner_version_above_own_version_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            version = gate.read_repo_runner_version()
            package = _make_package(Path(tmpdir) / "runner.tar.gz", version, min_runner_version="v9.9.9")
            results, _ = gate.check_package_manifest(package, version)
        self.assertIn("FAIL", {item["status"] for item in results})

    def test_lower_min_runner_version_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            version = gate.read_repo_runner_version()
            package = _make_package(Path(tmpdir) / "runner.tar.gz", version, min_runner_version="v0.1.0")
            results, _ = gate.check_package_manifest(package, version)
        self.assertEqual({item["status"] for item in results}, {"PASS"})


class VerifyEndToEndTest(unittest.TestCase):
    def test_matching_package_is_ok(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            version = gate.read_repo_runner_version()
            package = _make_package(Path(tmpdir) / "runner.tar.gz", version, min_runner_version="v0.1.0")
            result = gate.verify(package=package)
        self.assertTrue(result["ok"], result["checks"])
        self.assertEqual(result["failures"], [])

    def test_package_with_different_image_version_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            version = gate.read_repo_runner_version()
            package = _make_package(Path(tmpdir) / "runner.tar.gz", version, image_version="v0.3.1")
            result = gate.verify(package=package)
        self.assertFalse(result["ok"])
        self.assertIn("package_image", result["failures"])

    def test_package_image_without_repo_sources_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            version = gate.read_repo_runner_version()
            package = _make_package(
                Path(tmpdir) / "runner.tar.gz", version, include_actions_in_image=False
            )
            result = gate.verify(package=package)
        self.assertFalse(result["ok"])
        self.assertIn("package_image", result["failures"])


class CliTest(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def test_repo_only_run_exits_zero(self):
        completed = self._run()
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("skipped checks", completed.stdout)

    def test_matching_package_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            version = gate.read_repo_runner_version()
            package = _make_package(Path(tmpdir) / "runner.tar.gz", version, min_runner_version="v0.1.0")
            completed = self._run("--package", str(package))
        self.assertEqual(completed.returncode, 0, completed.stdout)

    def test_failing_package_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            package = _make_package(Path(tmpdir) / "runner.tar.gz", "v0.3.1")
            completed = self._run("--package", str(package))
        self.assertEqual(completed.returncode, 1, completed.stdout)
        self.assertIn("FAILED checks", completed.stdout)

    def test_json_output_is_machine_readable(self):
        completed = self._run("--json")
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["runner_version"], gate.read_repo_runner_version())


if __name__ == "__main__":
    unittest.main()
