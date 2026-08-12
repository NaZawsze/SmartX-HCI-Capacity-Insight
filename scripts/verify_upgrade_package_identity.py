#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tarfile
import tempfile
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
IMAGE_IDENTITY_MARKER = "SMARTX_IMAGE_IDENTITY:"


def run(command: list[str], cwd: Path = ROOT) -> str:
    completed = subprocess.run(command, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"Command failed ({completed.returncode}): {' '.join(command)}\n{completed.stdout[-4000:]}")
    return completed.stdout


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version_tuple(value: str) -> tuple[int, int, int, str]:
    version = value.strip()
    if version.startswith("v"):
        version = version[1:]
    head, suffix = version, ""
    for index, char in enumerate(version):
        if not (char.isdigit() or char == "."):
            head, suffix = version[:index], version[index:]
            break
    parts = head.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise SystemExit(f"Invalid version value: {value!r}")
    return (int(parts[0]), int(parts[1]), int(parts[2]), suffix)


def _expected_web_api_runner_baseline(version: str) -> str:
    if _version_tuple(version) < _version_tuple("v0.5.2"):
        return "v0.3.0"
    return "v0.3.1"


def _safe_extract(package: Path, destination: Path) -> None:
    with tarfile.open(package, mode="r:gz") as archive:
        for member in archive.getmembers():
            relative = Path(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                raise SystemExit(f"Unsafe package member: {member.name}")
        try:
            archive.extractall(destination, filter="data")
        except TypeError:
            archive.extractall(destination)


def _verify_checksums(root: Path) -> None:
    checksums = root / "checksums.sha256"
    if not checksums.is_file():
        raise SystemExit("Package missing checksums.sha256")
    for line in checksums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, rel = line.split(None, 1)
        target = root / rel.strip()
        if not target.is_file():
            raise SystemExit(f"Checksum target missing: {rel}")
        actual = sha256_file(target)
        if actual != expected:
            raise SystemExit(f"Checksum mismatch for {rel}: expected {expected}, got {actual}")


def _loaded_image_reference(output: str) -> str:
    for line in reversed(output.splitlines()):
        line = line.strip()
        for prefix in ("Loaded image: ", "Loaded image ID: "):
            if line.startswith(prefix):
                return line[len(prefix):].strip()
    raise SystemExit(f"docker load output did not include loaded image reference: {output[-1000:]}")


def _read_web_api_image_identity(image: str) -> dict[str, Any]:
    script = f"""
import json
from pathlib import Path

def read_file(path):
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None

payload = {{
    "version_file": read_file("/app/VERSION"),
    "runner_version_file": read_file("/app/RUNNER_VERSION"),
    "core_default_app_version": None,
    "core_default_runner_version": None,
    "v2_default_app_version": None,
    "v2_default_runner_version": None,
}}
try:
    from app.core import config as core_config
    payload["core_default_app_version"] = getattr(core_config, "DEFAULT_APP_VERSION", None)
    payload["core_default_runner_version"] = getattr(core_config, "DEFAULT_RUNNER_VERSION", None)
except Exception as exc:
    payload["core_config_error"] = str(exc)
try:
    from app.v2 import config as v2_config
    payload["v2_default_app_version"] = getattr(v2_config, "DEFAULT_APP_VERSION", None)
    payload["v2_default_runner_version"] = getattr(v2_config, "DEFAULT_RUNNER_VERSION", None)
except Exception as exc:
    payload["v2_config_error"] = str(exc)
print("{IMAGE_IDENTITY_MARKER}" + json.dumps(payload, sort_keys=True))
"""
    output = run(["docker", "run", "--rm", "--entrypoint", "python", image, "-c", script])
    for line in output.splitlines():
        if line.startswith(IMAGE_IDENTITY_MARKER):
            payload = json.loads(line[len(IMAGE_IDENTITY_MARKER):])
            if not isinstance(payload, dict):
                raise SystemExit(f"web-api image identity is not an object: {image}")
            return payload
    raise SystemExit(f"web-api image identity missing from {image}: {output[-1000:]}")


def _assert_web_api_identity(identity: dict[str, Any], *, image: str, version: str) -> None:
    expected_runner = _expected_web_api_runner_baseline(version)
    expected = {
        "version_file": version,
        "runner_version_file": expected_runner,
        "core_default_app_version": version,
        "core_default_runner_version": expected_runner,
        "v2_default_app_version": version,
        "v2_default_runner_version": expected_runner,
    }
    mismatches = [
        f"{key}: expected {expected_value!r}, got {identity.get(key)!r}"
        for key, expected_value in expected.items()
        if identity.get(key) != expected_value
    ]
    if mismatches:
        raise SystemExit(f"web-api image identity mismatch for package image {image}: " + "; ".join(mismatches))


def _web_api_archive(manifest: dict[str, Any]) -> str:
    for component in manifest.get("components") or []:
        if component.get("type") != "platform":
            continue
        for image in component.get("images") or []:
            if image.get("service") == "web-api" and image.get("archive"):
                return str(image["archive"])
    raise SystemExit("Package manifest does not declare an archived web-api image")


def verify_package(package: Path, *, expected_version: str | None = None) -> dict[str, Any]:
    package = Path(package)
    if not package.is_file():
        raise SystemExit(f"Package not found: {package}")
    cleanup_tags: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="smartx-package-identity-") as tmpdir:
            root = Path(tmpdir)
            _safe_extract(package, root)
            _verify_checksums(root)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            version = str(manifest.get("version") or "")
            if expected_version and version != expected_version:
                raise SystemExit(f"Package version mismatch: expected {expected_version}, got {version}")
            archive_rel = _web_api_archive(manifest)
            image_tar = root / archive_rel
            if not image_tar.is_file():
                raise SystemExit(f"Package missing web-api image archive: {archive_rel}")
            loaded = _loaded_image_reference(run(["docker", "load", "-i", str(image_tar)]))
            temporary_tag = f"smartx-package-identity:{version.lstrip('v').replace('.', '-')}-{uuid.uuid4().hex[:12]}"
            run(["docker", "tag", loaded, temporary_tag])
            cleanup_tags.append(temporary_tag)
            identity = _read_web_api_image_identity(temporary_tag)
            _assert_web_api_identity(identity, image=temporary_tag, version=version)
            return {
                "package": str(package),
                "version": version,
                "web_api_archive": archive_rel,
                "web_api_loaded_image": loaded,
                "web_api_identity": identity,
            }
    finally:
        for tag in cleanup_tags:
            try:
                run(["docker", "image", "rm", "-f", tag])
            except SystemExit:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify upgrade package image identity from package image tar files.")
    parser.add_argument("package", type=Path)
    parser.add_argument("--expected-version")
    args = parser.parse_args()
    result = verify_package(args.package, expected_version=args.expected_version)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
