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
RUNNER_VERSION_FILE = ROOT / 'RUNNER_VERSION'
OUTPUT_DIR = Path('/data/upgrade-packages/components')
PRODUCT = 'smartx-upgrade-runner'
COMPONENT = 'upgrade-runner'
LOCAL_IMAGE = 'smartx-storage-forecast-upgrade-runner:local'
RELEASE_IMAGE_REPO = 'nazawsze/smartx-hci-capacity-insight-upgrade-runner'
DEFAULT_MIN_VERSION = 'v0.1.0'


def run(command: list[str], cwd: Path = ROOT) -> str:
    completed = subprocess.run(command, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"Command failed ({completed.returncode}): {' '.join(command)}\n{completed.stdout[-4000:]}")
    return completed.stdout


def normalize_version(value: str) -> str:
    version = value.strip()
    if not version.startswith('v'):
        version = 'v' + version
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+(?:[A-Za-z0-9._-]+)?', version):
        raise SystemExit(f'Invalid component version: {value!r}')
    return version


def read_default_version() -> str:
    if RUNNER_VERSION_FILE.exists():
        return normalize_version(RUNNER_VERSION_FILE.read_text(encoding='utf-8'))
    return 'v0.2.2'


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def build_package(version: str, min_version: str, output_dir: Path, build_image: bool) -> Path:
    image = f'{RELEASE_IMAGE_REPO}:{version}'
    if build_image:
        run(['docker', 'compose', '-f', 'docker-compose.yml', 'build', COMPONENT])
        run(['docker', 'tag', LOCAL_IMAGE, image])
    else:
        run(['docker', 'image', 'inspect', image])

    work = output_dir / f'smartx-upgrade-runner-{version}'
    package = output_dir / f'smartx-upgrade-runner-{version}.tar.gz'
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    (work / 'images').mkdir()
    image_file = work / 'images' / 'upgrade-runner.tar'
    run(['docker', 'save', '-o', str(image_file), image])

    manifest = {
        'product': PRODUCT,
        'component': COMPONENT,
        'version': version,
        'min_version': min_version,
        'package_type': 'component',
        'restart_services': [COMPONENT],
        'release_notes': f'{COMPONENT} {version}: safe backup, no-deps restart, docker-socket compose path handling.',
        'images': [
            {
                'service': COMPONENT,
                'image': image,
                'file': 'images/upgrade-runner.tar',
                'sha256': sha256_file(image_file),
            }
        ],
    }
    (work / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (work / 'release-notes.md').write_text(
        f'# {COMPONENT} {version}\n\n'
        '- Upgrade backup excludes /data/upgrades, /data/backups, /data/exports and Prometheus runtime WAL.\n'
        '- Platform service restart uses docker compose up --no-deps to avoid recreating Prometheus.\n'
        '- Compose execution rewrites relative bind mounts for Docker socket host paths.\n',
        encoding='utf-8',
    )
    if package.exists():
        package.unlink()
    with tarfile.open(package, 'w:gz', compresslevel=1) as archive:
        for member in ['manifest.json', 'release-notes.md', 'images/upgrade-runner.tar']:
            archive.add(work / member, arcname=member)
    (output_dir / f'{package.name}.sha256').write_text(f'{sha256_file(package)}  {package.name}\n', encoding='utf-8')
    print(package)
    print(sha256_file(package))
    return package


def main() -> None:
    parser = argparse.ArgumentParser(description='Build upgrade-runner component package.')
    parser.add_argument('--version', default=read_default_version())
    parser.add_argument('--min-version', default=DEFAULT_MIN_VERSION)
    parser.add_argument('--output-dir', type=Path, default=OUTPUT_DIR)
    parser.add_argument('--no-build', action='store_true')
    args = parser.parse_args()
    version = normalize_version(args.version)
    min_version = normalize_version(args.min_version)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    build_package(version, min_version, args.output_dir, build_image=not args.no_build)


if __name__ == '__main__':
    main()
