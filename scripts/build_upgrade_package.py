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
RELEASE_NAMESPACE = "nazawsze"
PLATFORM_IMAGES = [
    ("web-api", "smartx-storage-forecast-web-api", "smartx-hci-capacity-insight-web-api", "images/web-api.tar", True),
    ("collector-worker", "smartx-storage-forecast-collector-worker", "smartx-hci-capacity-insight-collector-worker", "images/collector-worker.tar", True),
    ("frontend", "smartx-storage-forecast-frontend", "smartx-hci-capacity-insight-frontend", "images/frontend.tar", True),
    ("upgrade-runner", "smartx-storage-forecast-upgrade-runner", "smartx-hci-capacity-insight-upgrade-runner", "images/upgrade-runner.tar", False),
]
PROJECT_FILES = [
    "docker-compose.offline.yml",
    "docker-compose.release.yml",
    "docker-compose.yml",
    "prometheus/prometheus.yml",
    "pre_install.sh",
    "README.md",
    "README.zh-CN.md",
]
PROJECT_DIRS = ["docs", "scripts"]
SENSITIVE_PATTERNS = (
    re.compile(r"(^|/)\.env($|[./])", re.I),
    re.compile(r"smartx\.db", re.I),
    re.compile(r"(^|/)(data|backups|upgrades)($|/)", re.I),
    re.compile(r"(^|/)prometheus(/(data|wal|chunks_head|queries\.active|.*\.tmp)|$)", re.I),
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
        (ROOT / "backend/app/core/config.py", f'DEFAULT_APP_VERSION = "{version}"'),
        (ROOT / "docker-compose.offline.yml", f"SMARTX_IMAGE_TAG:-{version}"),
        (ROOT / "docker-compose.release.yml", f"SMARTX_IMAGE_TAG:-{version}"),
    ]
    for path, expected in checks:
        assert_contains(path, expected)
    offline_text = (ROOT / "docker-compose.offline.yml").read_text(encoding="utf-8")
    if "SMARTX_IMAGE_TAG:-latest" in offline_text:
        raise SystemExit("docker-compose.offline.yml must not default to latest.")
    print(f"Version metadata OK: {version}")


def release_image(repository: str, version: str) -> str:
    return f"{RELEASE_NAMESPACE}/{repository}:{version}"


def docker_build(version: str, *, include_frontend: bool) -> None:
    services = ["web-api", "collector-worker", "upgrade-runner"] + (["frontend"] if include_frontend else [])
    run(["docker", "compose", "-f", "docker-compose.yml", "build", *services])
    for service, local_repository, release_repository, _, _ in PLATFORM_IMAGES:
        if service == "frontend" and not include_frontend:
            continue
        run(["docker", "tag", f"{local_repository}:local", release_image(release_repository, version)])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_migrate_script(path: Path, version: str) -> None:
    script = f'''#!/bin/sh
set -eu

PROJECT_ROOT="${{SMARTX_PROJECT_PATH:-/opt/smartx-storage-forecast}}"
PACKAGE_DIR="$(pwd)"
VERSION="{version}"
BACKUP_ROOT="${{SMARTX_DATA_PATH:-/data}}/backups/project-files-before-${{VERSION}}-$(date +%Y%m%d%H%M%S)"
OVERRIDE="$PROJECT_ROOT/docker-compose.upgrade.yml"

python3 - "$PACKAGE_DIR" "$PROJECT_ROOT" "$BACKUP_ROOT" "$OVERRIDE" "$VERSION" <<'PY'
from pathlib import Path
import json
import shutil
import subprocess
import sys

package_dir = Path(sys.argv[1])
project_root = Path(sys.argv[2])
backup_root = Path(sys.argv[3])
override_path = Path(sys.argv[4])
version = sys.argv[5]
manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
active_upgrade_task = package_dir.parent.name

blocked_parts = {{"data", "backups", "upgrades", "__pycache__"}}
blocked_words = ("credential", "secret", "password", "tower_password", "access_key", "token")

def safe_rel(value):
    rel = Path(str(value))
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise RuntimeError(f"项目文件路径不安全：{{value}}")
    lowered = rel.as_posix().lower()
    if rel.name == ".env" or any(part.lower() in blocked_parts for part in rel.parts):
        raise RuntimeError(f"项目文件路径禁止同步：{{value}}")
    if lowered.endswith("smartx.db") or any(word in lowered for word in blocked_words):
        raise RuntimeError(f"项目文件路径疑似包含敏感信息：{{value}}")
    return rel

project_files = manifest.get("project_files") or []
if not project_files:
    raise RuntimeError("升级包缺少 project_files。")

copied = []
missing_before = []
for item in project_files:
    rel = safe_rel(item)
    source = package_dir / "project" / rel
    if not source.is_file():
        raise RuntimeError(f"升级包缺少项目文件：{{rel}}")
    target = project_root / rel
    if target.exists():
        backup = backup_root / rel
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
    else:
        missing_before.append(str(rel))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    copied.append(str(rel))

services = {{
    item["service"]: item["image"]
    for item in manifest.get("images", [])
    if item.get("service") in {{"web-api", "collector-worker", "frontend"}}
}}
lines = ["services:"]
for service in ("web-api", "collector-worker", "frontend"):
    image = services.get(service)
    if image:
        lines.append(f"  {{service}}:")
        lines.append(f"    image: {{image}}")
override_path.write_text("\\n".join(lines) + "\\n", encoding="utf-8")

def migrate_legacy_artifacts():
    image = next((item.get("image") for item in manifest.get("images", []) if item.get("service") == "upgrade-runner"), None)
    image = image or next((item.get("image") for item in manifest.get("images", []) if item.get("service") == "web-api"), None)
    if not image:
        return "未找到可执行镜像，跳过旧运行产物整理"
    host_script = "\\n".join([
        "from pathlib import Path",
        "import json",
        "import shutil",
        "import sys",
        "",
        "root = Path('/host-data')",
        "app = root / 'smartx-capacity-insight-data' / 'app'",
        "active_task = sys.argv[1]",
        "version = sys.argv[2]",
        "targets = [",
        "    ('backups', root / 'backups'),",
        "    ('exports', root / 'exports'),",
        "    ('compose-runtime', root / 'compose-runtime'),",
        "]",
        "for _, target in [('upgrades', root / 'upgrades'), *targets]:",
        "    target.mkdir(parents=True, exist_ok=True)",
        "",
        "def copy_tree_contents(source, target):",
        "    if not source.exists() or not source.is_dir():",
        "        return 0",
        "    copied = 0",
        "    for child in source.iterdir():",
        "        dest = target / child.name",
        "        if child.is_dir():",
        "            if dest.exists():",
        "                copied += copy_tree_contents(child, dest)",
        "            else:",
        "                shutil.copytree(child, dest)",
        "                copied += 1",
        "        elif not dest.exists():",
        "            if child.name.startswith('docker-compose.runner-upgrade.yml'):",
        "                continue",
        "            dest.parent.mkdir(parents=True, exist_ok=True)",
        "            shutil.copy2(child, dest)",
        "            copied += 1",
        "    return copied",
        "",
        "def sync_runtime_compose():",
        "    runtime = root / 'compose-runtime'",
        "    project = root / 'SmartX-HCI-Capacity-Insight-main'",
        "    packaged_project = Path('/package-project')",
        "    candidates = [",
        "        packaged_project / 'docker-compose.offline.yml',",
        "        project / 'docker-compose.offline.yml',",
        "    ]",
        "    for source in candidates:",
        "        if source.is_file():",
        "            target = runtime / 'docker-compose.offline.yml'",
        "            target.parent.mkdir(parents=True, exist_ok=True)",
        "            shutil.copy2(source, target)",
        "            break",
        "    runner_override = runtime / 'docker-compose.runner-upgrade.yml'",
        "    if runner_override.exists():",
        "        backup = runtime / ('docker-compose.runner-upgrade.yml.before-' + version)",
        "        if not backup.exists():",
        "            shutil.copy2(runner_override, backup)",
        "        runner_override.unlink()",
        "        return 'runtime-compose:已刷新 offline compose，并清理旧 runner override'",
        "    return 'runtime-compose:已刷新 offline compose'",
        "",
        "def task_updated_at(path):",
        "    try:",
        "        return json.loads(path.read_text(encoding='utf-8')).get('updated_at') or ''",
        "    except Exception:",
        "        return ''",
        "",
        "def copy_task_file_if_newer(src, dst):",
        "    if not src.is_file():",
        "        return False",
        "    if dst.exists() and task_updated_at(dst) >= task_updated_at(src):",
        "        return False",
        "    dst.parent.mkdir(parents=True, exist_ok=True)",
        "    shutil.copy2(src, dst)",
        "    return True",
        "",
        "def migrate_upgrade_records(source, target):",
        "    if not source.exists() or not source.is_dir():",
        "        return 'upgrades:无旧目录'",
        "    copied = 0",
        "    cleaned = 0",
        "    for task_dir in source.iterdir():",
        "        if not task_dir.is_dir():",
        "            continue",
        "        dest_task = target / task_dir.name",
        "        dest_task.mkdir(parents=True, exist_ok=True)",
        "        for rel in ('task.json', 'manifest.json', 'package/manifest.json', 'package/release-notes.md'):",
        "            src = task_dir / rel",
        "            if src.is_file():",
        "                dst = dest_task / rel",
        "                if rel == 'task.json':",
        "                    if copy_task_file_if_newer(src, dst):",
        "                        copied += 1",
        "                elif not dst.exists():",
        "                    dst.parent.mkdir(parents=True, exist_ok=True)",
        "                    shutil.copy2(src, dst)",
        "                    copied += 1",
        "        if task_dir.name == active_task:",
        "            continue",
        "        for rel in ('upload.tar.gz', 'package/images'):",
        "            src = task_dir / rel",
        "            if src.is_dir():",
        "                shutil.rmtree(src, ignore_errors=True)",
        "                cleaned += 1",
        "            elif src.exists():",
        "                src.unlink(missing_ok=True)",
        "                cleaned += 1",
        "    return 'upgrades:复制记录 %s 个，清理旧缓存 %s 项' % (copied, cleaned)",
        "",
        "messages = [sync_runtime_compose(), migrate_upgrade_records(app / 'upgrades', root / 'upgrades')]",
        "for name, target in targets:",
        "    messages.append('%s:复制 %s 项' % (name, copy_tree_contents(app / name, target)))",
        "print('；'.join(messages))",
    ])
    completed = subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", "/data:/host-data",
            "-v", str(package_dir / "project") + ":/package-project:ro",
            image,
            "python", "-c", host_script, active_upgrade_task, version,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        return "旧运行产物整理未完成：" + completed.stdout[-1000:]
    return completed.stdout.strip() or "旧运行产物整理完成"

artifact_message = migrate_legacy_artifacts()

print(f"已同步项目文件 {{len(copied)}} 个。")
print(f"项目文件备份目录：{{backup_root}}")
if missing_before:
    print("升级前不存在的项目文件：" + ", ".join(missing_before))
print("运行产物目录整理：" + artifact_message)
print(f"已写入 {{version}} 镜像覆盖配置到 {{override_path}}")
PY
'''
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


def assert_safe_members(members: Iterable[str]) -> None:
    bad = [member for member in members if any(pattern.search(member) for pattern in SENSITIVE_PATTERNS)]
    if bad:
        raise SystemExit("Sensitive paths refused in package: " + ", ".join(bad))


def collect_project_files(version: str) -> list[str]:
    files: set[str] = set(PROJECT_FILES)
    for directory in PROJECT_DIRS:
        root = ROOT / directory
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT)
            if "__pycache__" in relative.parts:
                continue
            if path.name.startswith("._") or path.name == ".DS_Store":
                continue
            files.add(relative.as_posix())
    result = sorted(files)
    assert_safe_members([f"project/{item}" for item in result])
    for rel in result:
        source = ROOT / rel
        if not source.is_file():
            raise SystemExit(f"Project file missing: {rel}")
        if rel.endswith((".pyc", ".pyo")) or "__pycache__" in Path(rel).parts:
            raise SystemExit(f"Compiled cache refused in project package: {rel}")
    offline_text = (ROOT / "docker-compose.offline.yml").read_text(encoding="utf-8")
    if f"SMARTX_IMAGE_TAG:-{version}" not in offline_text:
        raise SystemExit("docker-compose.offline.yml default tag does not match VERSION.")
    if "SMARTX_IMAGE_TAG:-latest" in offline_text:
        raise SystemExit("docker-compose.offline.yml must not default to latest.")
    return result


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
    for service, _, release_repository, rel_path, restart in PLATFORM_IMAGES:
        image = release_image(release_repository, version)
        target = work / rel_path
        run(["docker", "save", "-o", str(target), image])
        item = {
            "service": service,
            "image": image,
            "file": rel_path,
            "sha256": sha256_file(target),
        }
        if not restart:
            item["restart"] = False
        manifest_images.append(item)

    project_files = collect_project_files(version)
    for rel in project_files:
        target = work / "project" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)

    write_migrate_script(work / "scripts/migrate.sh", version)
    manifest = {
        "product": PRODUCT,
        "version": version,
        "min_version": min_version,
        "package_type": "platform",
        "database_migration": True,
        "restart_services": ["web-api", "collector-worker", "frontend"],
        "release_notes": f"{version} platform upgrade package.",
        "project_files": project_files,
        "images": manifest_images,
    }
    (work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (work / "release-notes.md").write_text(
        f"# {version}\n\n"
        "- Platform upgrade package for web-api, collector-worker, frontend, and the offline upgrade-runner image.\n"
        "- Syncs whitelisted project files such as compose, docs, and scripts.\n"
        "- Writes image overrides into docker-compose.upgrade.yml before service restart.\n\n"
        "This package does not include .env, databases, Prometheus data, Tower credentials, or runtime data.\n",
        encoding="utf-8",
    )

    members = [
        "manifest.json",
        "release-notes.md",
        "images/web-api.tar",
        "images/collector-worker.tar",
        "images/frontend.tar",
        "images/upgrade-runner.tar",
        "scripts/migrate.sh",
        *[f"project/{rel}" for rel in project_files],
    ]
    assert_safe_members(members)
    if package.exists():
        package.unlink()
    with tarfile.open(package, "w:gz", compresslevel=1) as archive:
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
