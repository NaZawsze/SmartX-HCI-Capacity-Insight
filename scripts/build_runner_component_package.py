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
    return 'v0.3.1'


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_runner_image(image: str) -> None:
    script = r'''
import tempfile
from pathlib import Path

from app.upgrade_runner.actions import ActionContext, default_handlers, filesystem_prepare
from app.upgrade_runner.engine import UpgradeEngine
from app.upgrade_runner.store import TaskStore
from app.upgrade_protocol.constants import RUNNER_CAPABILITIES

handlers = default_handlers()
required_handlers = {
    "filesystem.prepare",
    "task.migrate_runtime_state",
    "task.sync_runtime_state",
    "post_upgrade.schedule_cleanup",
    "post_upgrade.schedule_collection",
    "runner.schedule_target_runtime_handoff",
}
missing = sorted(required_handlers - set(handlers))
if missing:
    raise SystemExit(f"missing runner handlers: {missing}")
if "filesystem.v1" not in RUNNER_CAPABILITIES or "task.recovery.v1" not in RUNNER_CAPABILITIES:
    raise SystemExit("runner capabilities missing filesystem/task recovery")

with tempfile.TemporaryDirectory() as tmpdir:
    root = Path(tmpdir)
    legacy_project = root / "legacy-project"
    target_project = root / "target" / "project"
    legacy_project.mkdir()
    (legacy_project / ".env").write_text(
        "SMARTX_SECRET_KEY=legacy\nSMARTX_IMAGE_TAG=v0.5.1\nSMARTX_RUNNER_IMAGE_TAG=v0.3.0\n",
        encoding="utf-8",
    )
    context = ActionContext.minimal(root)
    result = filesystem_prepare(
        {
            "params": {
                "project_path": str(target_project),
                "env_file_migration": {
                    "target": str(target_project / ".env"),
                    "legacy_candidates": [str(legacy_project / ".env")],
                    "preserve_existing": True,
                    "sanitize_image_tags": True,
                    "fallback_defaults": True,
                },
            }
        },
        context.as_dict(),
    )
    env_text = (target_project / ".env").read_text(encoding="utf-8")
    if result.get("env_file", {}).get("status") != "copied":
        raise SystemExit(f"env_file_migration did not copy legacy env: {result!r}")
    if "SMARTX_IMAGE_TAG=" in env_text or "SMARTX_RUNNER_IMAGE_TAG=" in env_text:
        raise SystemExit("env_file_migration did not sanitize image tag env keys")

with tempfile.TemporaryDirectory() as tmpdir:
    root = Path(tmpdir)
    legacy_task_dir = root / "legacy-upgrades" / "upgrade-verify"
    target_task_dir = root / "target-upgrades" / "upgrade-verify"
    store = TaskStore(legacy_task_dir)
    store.save(
        {
            "task_id": "upgrade-verify",
            "status": "pending",
            "execution_plan": {
                "actions": [
                    {
                        "id": "migrate-task-state",
                        "type": "task.migrate_runtime_state",
                        "params": {"target_task_dir": str(target_task_dir)},
                        "status": "pending",
                        "attempt": 0,
                        "checkpoint": {},
                        "result": {},
                    },
                    {
                        "id": "sync-task-state",
                        "type": "task.sync_runtime_state",
                        "params": {},
                        "status": "pending",
                        "attempt": 0,
                        "checkpoint": {},
                        "result": {},
                    },
                ]
            },
        }
    )
    result = UpgradeEngine(
        store,
        handlers={
            "task.migrate_runtime_state": handlers["task.migrate_runtime_state"],
            "task.sync_runtime_state": handlers["task.sync_runtime_state"],
        },
        context=ActionContext.minimal(root).as_dict(),
    ).run()
    if result.get("status") != "success":
        raise SystemExit(f"task mirror verification did not finish: {result!r}")
    mirrored = TaskStore(target_task_dir).load()
    if mirrored.get("status") != "success":
        raise SystemExit(f"task mirror did not receive final success: {mirrored!r}")

print("SMARTX_RUNNER_VERIFY_OK")
'''
    run([
        'docker',
        'run',
        '--rm',
        '--entrypoint',
        'python',
        image,
        '-c',
        script,
    ])


def _run_compose_build_with_env() -> None:
    env_file = ROOT / ".env"
    created = False
    if not env_file.exists():
        env_file.write_text("", encoding="utf-8")
        created = True
    try:
        run(['docker', 'compose', '-f', 'docker-compose.yml', 'build', COMPONENT])
    finally:
        if created:
            env_file.unlink(missing_ok=True)


def build_package(version: str, min_version: str, output_dir: Path, build_image: bool) -> Path:
    image = f'{RELEASE_IMAGE_REPO}:{version}'
    if build_image:
        _run_compose_build_with_env()
    else:
        run(['docker', 'image', 'inspect', image])
    verify_runner_image(image)

    work = output_dir / f'smartx-upgrade-runner-{version}'
    package = output_dir / f'smartx-upgrade-runner-{version}.tar.gz'
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    (work / 'images').mkdir()
    image_file = work / 'images' / 'upgrade-runner.tar'
    run(['docker', 'save', '-o', str(image_file), image])

    manifest = {
        'schema_version': '3',
        'minimum_runner_protocol': 1,
        'required_capabilities': [],
        'product': PRODUCT,
        'package_id': f'{PRODUCT}-{version}',
        'component': COMPONENT,
        'version': version,
        'min_version': min_version,
        'package_type': 'component',
        'bootstrap_runner': {
            'enabled': True,
            'target_project': 'smartx-hci-capacity-insight',
            'target_network': 'smartx-hci-capacity-insight-net',
            'target_subnet': '10.249.251.0/24',
            'target_root': '/data/smartx-storage-forecast',
        },
        'components': [
            {
                'type': 'runner',
                'services': [COMPONENT],
                'images': [
                    {
                        'service': COMPONENT,
                        'image': image,
                        'archive': 'images/upgrade-runner.tar',
                        'sha256': sha256_file(image_file),
                    }
                ],
            }
        ],
        'project_files': False,
        'restart_services': [COMPONENT],
        'compatibility': {'min_runner_version': min_version},
        'notes': 'release-notes.md',
        'release_notes': f'{COMPONENT} {version}: safe backup, no-deps restart, docker-socket compose path handling.',
    }
    (work / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (work / 'release-notes.md').write_text(
        f'# {COMPONENT} {version}\n\n'
        '- Upgrade backup excludes /data/upgrades, /data/backups, /data/exports and Prometheus runtime WAL.\n'
        '- Platform service restart uses docker compose up --no-deps to avoid recreating Prometheus.\n'
        '- Compose execution rewrites relative bind mounts for Docker socket host paths.\n',
        encoding='utf-8',
    )
    members = ['manifest.json', 'release-notes.md', 'images/upgrade-runner.tar']
    (work / 'checksums.sha256').write_text(
        '\n'.join(f'{sha256_file(work / member)}  {member}' for member in members) + '\n',
        encoding='utf-8',
    )
    members.append('checksums.sha256')
    if package.exists():
        package.unlink()
    with tarfile.open(package, 'w:gz', compresslevel=1) as archive:
        for member in members:
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
