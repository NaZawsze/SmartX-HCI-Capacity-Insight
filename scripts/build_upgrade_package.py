#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
PACKAGE_DIR = Path("/data/upgrade-packages")
PRODUCT = "smartx-storage-forecast"
DEFAULT_MIN_VERSION = "0.3.0"
PLATFORM_IMAGES = [
    ("web-api", "smartx-storage-forecast-web-api", "images/web-api.tar"),
    ("collector-worker", "smartx-storage-forecast-collector-worker", "images/collector-worker.tar"),
    ("frontend", "smartx-storage-forecast-frontend", "images/frontend.tar"),
]
SENSITIVE_PATTERNS = (
    re.compile(r"(^|/)\.env($|[./])", re.I),
    re.compile(r"smartx\.db", re.I),
    re.compile(r"(^|/)(data|prometheus|backups|upgrades)($|/)", re.I),
    re.compile(r"credential|secret|password|tower_password|access_key|token", re.I),
)


def read_version() -> str:
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:[A-Za-z0-9._-]+)?", version):
        raise SystemExit(f"Invalid VERSION value: {version!r}")
    return version


def run(command: list[str], cwd: Path = ROOT) -> str:
    completed = subprocess.run(command, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"Command failed ({completed.returncode}): {' '.join(command)}\n{completed.stdout[-4000:]}")
    return completed.stdout


def assert_contains(path: Path, expected: str) -> None:
    text = path.read_text(encoding="utf-8")
    if expected not in text:
        raise SystemExit(f"Version check failed: {path.relative_to(ROOT)} missing {expected!r}")


def check_versions(version: str) -> None:
    checks = [
        (ROOT / "README.md", f"Version: `{version}`"),
        (ROOT / "README.zh-CN.md", f"版本：`{version}`"),
        (ROOT / "backend/app/core/config.py", f'default="{version}"'),
        (ROOT / "docker-compose.yml", f'SMARTX_APP_VERSION: "{version}"'),
        (ROOT / "docker-compose.offline.yml", f'SMARTX_APP_VERSION: "{version}"'),
        (ROOT / "docker-compose.release.yml", f'SMARTX_APP_VERSION: "{version}"'),
        (ROOT / "docker-compose.release.yml", f"SMARTX_IMAGE_TAG:-{version}"),
    ]
    for path, expected in checks:
        assert_contains(path, expected)
    print(f"Version metadata OK: {version}")


def docker_build(version: str, *, include_frontend: bool) -> None:
    services = ["web-api", "collector-worker"] + (["frontend"] if include_frontend else [])
    run(["docker", "compose", "-f", "docker-compose.yml", "build", *services])
    for service, repository, _ in PLATFORM_IMAGES:
        if service == "frontend" and not include_frontend:
            continue
        run(["docker", "tag", f"{repository}:local", f"{repository}:{version}"])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_migrate_script(path: Path, version: str) -> None:
    script = f'''#!/bin/sh
set -eu

OVERRIDE="${{SMARTX_PROJECT_PATH:-/opt/smartx-storage-forecast}}/docker-compose.upgrade.yml"
python3 - "$OVERRIDE" <<'PY'
from pathlib import Path
import sys

version = "{version}"
path = Path(sys.argv[1])
services = {{
    "web-api": f"smartx-storage-forecast-web-api:{{version}}",
    "collector-worker": f"smartx-storage-forecast-collector-worker:{{version}}",
    "frontend": f"smartx-storage-forecast-frontend:{{version}}",
}}

lines = ["services:"]
for service, image in services.items():
    lines.append(f"  {{service}}:")
    lines.append(f"    image: {{image}}")
    if service in {{"web-api", "collector-worker"}}:
        lines.append("    environment:")
        lines.append(f'      SMARTX_APP_VERSION: "{{version}}"')

path.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
PY

echo "已写入 {version} 版本环境变量到 ${{OVERRIDE}}"
'''
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


def assert_safe_members(members: Iterable[str]) -> None:
    bad = [member for member in members if any(pattern.search(member) for pattern in SENSITIVE_PATTERNS)]
    if bad:
        raise SystemExit("Sensitive paths refused in package: " + ", ".join(bad))


def build_package(version: str, *, min_version: str, output_dir: Path, build_images: bool, include_frontend_build: bool) -> Path:
    check_versions(version)
    if build_images:
        docker_build(version, include_frontend=include_frontend_build)

    work = output_dir / f"smartx-capacity-insight-upgrade-{version}"
    package = output_dir / f"smartx-capacity-insight-upgrade-{version}.tar.gz"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    (work / "images").mkdir()
    (work / "scripts").mkdir()

    manifest_images = []
    for service, repository, rel_path in PLATFORM_IMAGES:
        image = f"{repository}:{version}"
        target = work / rel_path
        run(["docker", "save", "-o", str(target), image])
        manifest_images.append({
            "service": service,
            "image": image,
            "file": rel_path,
            "sha256": sha256_file(target),
        })

    write_migrate_script(work / "scripts/migrate.sh", version)
    manifest = {
        "product": PRODUCT,
        "version": version,
        "min_version": min_version,
        "package_type": "platform",
        "database_migration": True,
        "restart_services": ["web-api", "collector-worker", "frontend"],
        "release_notes": f"{version} platform upgrade package.",
        "images": manifest_images,
    }
    (work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (work / "release-notes.md").write_text(
        f"# {version}\n\n"
        "- Platform upgrade package for web-api, collector-worker, and frontend.\n"
        "- Writes SMARTX_APP_VERSION into docker-compose.upgrade.yml before service restart.\n\n"
        "This package does not include .env, databases, Prometheus data, Tower credentials, or runtime data.\n",
        encoding="utf-8",
    )

    members = ["manifest.json", "release-notes.md", "images/web-api.tar", "images/collector-worker.tar", "images/frontend.tar", "scripts/migrate.sh"]
    assert_safe_members(members)
    if package.exists():
        package.unlink()
    with tarfile.open(package, "w:gz") as archive:
        for member in members:
            archive.add(work / member, arcname=member)

    package_sha = sha256_file(package)
    (output_dir / f"{package.name}.sha256").write_text(f"{package_sha}  {package.name}\n", encoding="utf-8")
    print(package)
    print(package_sha)
    return package


def main() -> None:
    parser = argparse.ArgumentParser(description="Build SmartX Capacity Insight offline upgrade package.")
    parser.add_argument("--check-version", action="store_true", help="Only validate version metadata and exit.")
    parser.add_argument("--no-build", action="store_true", help="Reuse existing docker images instead of building them.")
    parser.add_argument("--skip-frontend-build", action="store_true", help="Do not build frontend image before packaging.")
    parser.add_argument("--min-version", default=DEFAULT_MIN_VERSION)
    parser.add_argument("--output-dir", type=Path, default=PACKAGE_DIR)
    args = parser.parse_args()

    version = read_version()
    if args.check_version:
        check_versions(version)
        return
    args.output_dir.mkdir(parents=True, exist_ok=True)
    build_package(version, min_version=args.min_version, output_dir=args.output_dir, build_images=not args.no_build, include_frontend_build=not args.skip_frontend_build)


if __name__ == "__main__":
    main()
