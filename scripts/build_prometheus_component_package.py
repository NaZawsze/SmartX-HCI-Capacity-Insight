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

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = Path("/data/upgrade-packages/components")
PRODUCT = "smartx-prometheus"
COMPONENT = "prometheus"
IMAGE_REPO = "prom/prometheus"
DEFAULT_VERSION = "v2.55.1"
DEFAULT_MIN_VERSION = "v2.55.1"


def run(command: list[str], cwd: Path = ROOT) -> str:
    completed = subprocess.run(command, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"Command failed ({completed.returncode}): {' '.join(command)}\n{completed.stdout[-4000:]}")
    return completed.stdout


def normalize_version(value: str) -> str:
    version = value.strip()
    if not version.startswith("v"):
        version = "v" + version
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:[A-Za-z0-9._-]+)?", version):
        raise SystemExit(f"Invalid Prometheus version: {value!r}")
    return version


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_package(version: str, min_version: str, output_dir: Path, pull_image: bool, offline_image: bool = False) -> Path:
    image = f"{IMAGE_REPO}:{version}"
    if offline_image and pull_image:
        run(["docker", "pull", image])
    elif offline_image:
        run(["docker", "image", "inspect", image])

    work = output_dir / f"{PRODUCT}-{version}"
    package = output_dir / f"{PRODUCT}-{version}.tar.gz"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    image_file = work / "images" / "prometheus.tar"
    image_manifest = {
        "service": COMPONENT,
        "image": image,
    }
    if offline_image:
        (work / "images").mkdir()
        run(["docker", "save", "-o", str(image_file), image])
        image_manifest.update({"archive": "images/prometheus.tar", "sha256": sha256_file(image_file)})
    (work / "config").mkdir()
    (work / "health").mkdir()
    config_file = work / "config" / "prometheus.yml"
    shutil.copy2(ROOT / "prometheus" / "prometheus.yml", config_file)
    queries_file = work / "health" / "queries.json"
    queries_file.write_text(
        json.dumps(
            {
                "instant": [{"query": "up", "require_data": True}],
                "historical": [
                    {
                        "query": "smartx_vm_storage_used_bytes",
                        "range_seconds": 86400,
                        "step_seconds": 300,
                        "require_data": True,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": "3",
        "minimum_runner_protocol": 1,
        "required_capabilities": [
            "backup.create",
            "compose.override",
            "compose.apply",
            "health.prometheus",
            "rollback.restore",
        ],
        "product": PRODUCT,
        "package_id": f"{PRODUCT}-{version}",
        "component": COMPONENT,
        "version": version,
        "min_version": min_version,
        "package_type": "component",
        "components": [
            {
                "type": "observability",
                "services": [COMPONENT],
                "images": [image_manifest],
            }
        ],
        "file_sets": [
            {
                "id": "prometheus-config",
                "source": "config",
                "target": "prometheus",
                "files": ["prometheus.yml"],
                "checksums": {"prometheus.yml": sha256_file(config_file)},
            }
        ],
        "health": {
            "queries": "health/queries.json",
            "instant": [{"query": "up", "require_data": True}],
            "historical": [
                {
                    "query": "smartx_vm_storage_used_bytes",
                    "range_seconds": 86400,
                    "step_seconds": 300,
                    "require_data": True,
                }
            ],
        },
        "project_files": False,
        "restart_services": [COMPONENT],
        "compatibility": {"min_prometheus_version": min_version},
        "notes": "release-notes.md",
        "release_notes": f"Prometheus {version}: observability component package with data-directory precheck.",
    }
    if offline_image:
        manifest["required_capabilities"].insert(1, "image.load")
    (work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (work / "release-notes.md").write_text(
        f"# Prometheus {version}\n\n"
        "- This package upgrades only the Prometheus observability component.\n"
        "- The upgrade precheck validates the Prometheus data directory before restart.\n"
        "- Historical data blocks are not packaged and are preserved in the mounted data directory.\n",
        encoding="utf-8",
    )
    members = ["manifest.json", "release-notes.md", "config/prometheus.yml", "health/queries.json"]
    if offline_image:
        members.append("images/prometheus.tar")
    (work / "checksums.sha256").write_text(
        "\n".join(f"{sha256_file(work / member)}  {member}" for member in members) + "\n",
        encoding="utf-8",
    )
    members.append("checksums.sha256")
    if package.exists():
        package.unlink()
    with tarfile.open(package, "w:gz", compresslevel=1) as archive:
        for member in members:
            archive.add(work / member, arcname=member)
    (output_dir / f"{package.name}.sha256").write_text(f"{sha256_file(package)}  {package.name}\n", encoding="utf-8")
    print(package)
    print(sha256_file(package))
    return package


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Prometheus observability component package.")
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--min-version", default=DEFAULT_MIN_VERSION)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--no-pull", action="store_true", help="Do not pull the Prometheus image when building an offline image package.")
    parser.add_argument("--offline-image", action="store_true", help="Include images/prometheus.tar for offline environments. Default packages reference the image only.")
    args = parser.parse_args()
    version = normalize_version(args.version)
    min_version = normalize_version(args.min_version)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    build_package(version, min_version, args.output_dir, pull_image=not args.no_pull, offline_image=args.offline_image)


if __name__ == "__main__":
    main()
