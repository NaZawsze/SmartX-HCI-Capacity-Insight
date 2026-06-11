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
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
RUNNER_VERSION_FILE = ROOT / "RUNNER_VERSION"
PACKAGE_DIR = Path("/data/upgrade-packages")
PRODUCT = "smartx-storage-forecast"
DEFAULT_MIN_VERSION = "v0.5.0"
RELEASE_NAMESPACE = "nazawsze"
PLATFORM_IMAGES = [
    ("web-api", "smartx-storage-forecast-web-api", "smartx-hci-capacity-insight-web-api", "images/web-api.tar", True),
    ("collector-worker", "smartx-storage-forecast-collector-worker", "smartx-hci-capacity-insight-collector-worker", "images/collector-worker.tar", True),
    ("frontend", "smartx-storage-forecast-frontend", "smartx-hci-capacity-insight-frontend", "images/frontend.tar", True),
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
MIGRATION_REGISTRY = ROOT / "backend/app/v2/upgrade/migrations/registry.json"
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


def read_runner_version() -> str:
    version = RUNNER_VERSION_FILE.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:[A-Za-z0-9._-]+)?", version):
        raise SystemExit(f"Invalid RUNNER_VERSION value: {version!r}")
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
    runner_version = read_runner_version()
    checks = [
        (ROOT / "README.md", f"Version: `{version}`"),
        (ROOT / "README.zh-CN.md", f"版本：`{version}`"),
        (ROOT / "backend/app/core/config.py", f'DEFAULT_APP_VERSION = "{version}"'),
        (ROOT / "docker-compose.offline.yml", f"SMARTX_IMAGE_TAG:-{version}"),
        (ROOT / "docker-compose.release.yml", f"SMARTX_IMAGE_TAG:-{version}"),
        (ROOT / "docker-compose.offline.yml", f"SMARTX_RUNNER_IMAGE_TAG:-{runner_version}"),
        (ROOT / "docker-compose.release.yml", f"SMARTX_RUNNER_IMAGE_TAG:-{runner_version}"),
    ]
    for path, expected in checks:
        assert_contains(path, expected)
    offline_text = (ROOT / "docker-compose.offline.yml").read_text(encoding="utf-8")
    if "SMARTX_IMAGE_TAG:-latest" in offline_text:
        raise SystemExit("docker-compose.offline.yml must not default to latest.")
    if "smartx-hci-capacity-insight-upgrade-runner:${SMARTX_IMAGE_TAG" in offline_text:
        raise SystemExit("upgrade-runner must not use SMARTX_IMAGE_TAG.")
    upgrade_text = (ROOT / "docker-compose.upgrade.yml").read_text(encoding="utf-8")
    for service, _, release_repository, _, _ in PLATFORM_IMAGES:
        expected = release_image(release_repository, version)
        if expected not in upgrade_text:
            raise SystemExit(f"docker-compose.upgrade.yml missing {expected}.")
    print(f"Version metadata OK: {version}")


def release_image(repository: str, version: str) -> str:
    return f"{RELEASE_NAMESPACE}/{repository}:{version}"


def docker_build(version: str, *, include_frontend: bool) -> None:
    services = ["web-api", "collector-worker"] + (["frontend"] if include_frontend else [])
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


def _version_tuple(value: str) -> tuple[int, int, int, str]:
    version = value.strip()
    if version.startswith("v"):
        version = version[1:]
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)(.*)", version)
    if not match:
        raise SystemExit(f"Invalid version value: {value!r}")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)), match.group(4) or "")


def _load_migration_registry(path: Path = MIGRATION_REGISTRY) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit(f"Migration registry must be a list: {path}")
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            raise SystemExit(f"Migration registry item must be an object: {path}")
        step_id = str(item.get("id") or "").strip()
        version = str(item.get("version") or "").strip()
        description = str(item.get("description") or "").strip()
        if not step_id or not version or not description:
            raise SystemExit(f"Migration step requires id, version and description: {item!r}")
        _version_tuple(version)
        if step_id in seen_ids:
            raise SystemExit(f"Duplicate migration step id: {step_id}")
        seen_ids.add(step_id)
        database = str(item.get("database") or "sqlite").strip()
        if database != "sqlite":
            raise SystemExit(f"Unsupported migration database for {step_id}: {database}")
        sql = item.get("sql") or []
        if not isinstance(sql, list) or not all(isinstance(statement, str) for statement in sql):
            raise SystemExit(f"Migration step sql must be a string array: {step_id}")
        operations = item.get("operations") or []
        if not isinstance(operations, list):
            raise SystemExit(f"Migration step operations must be an array: {step_id}")
        for operation in operations:
            if not isinstance(operation, dict):
                raise SystemExit(f"Migration operation must be an object: {step_id}")
            action = str(operation.get("action") or "").strip()
            if action != "add_column_if_missing":
                raise SystemExit(f"Unsupported migration operation for {step_id}: {action}")
            table = str(operation.get("table") or "").strip()
            column = str(operation.get("column") or "").strip()
            definition = str(operation.get("definition") or "").strip()
            if not table or not column or not definition:
                raise SystemExit(f"add_column_if_missing requires table, column and definition: {step_id}")
        result.append(
            {
                "id": step_id,
                "version": version,
                "description": description,
                "database": database,
                "sql": sql,
                "operations": operations,
            }
        )
    return sorted(result, key=lambda step: _version_tuple(str(step["version"])))


def _selected_migration_steps(registry: list[dict[str, Any]], *, min_version: str, target_version: str) -> list[dict[str, Any]]:
    source = _version_tuple(min_version)
    target = _version_tuple(target_version)
    return [
        dict(step)
        for step in registry
        if source < _version_tuple(str(step["version"])) <= target
    ]


def _migration_runner_source(steps: list[dict[str, Any]]) -> str:
    payload = json.dumps(steps, ensure_ascii=False, sort_keys=True, indent=2)
    return f'''#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


STEPS = json.loads({payload!r})
DB_PATH = Path(os.environ.get("SMARTX_DB_PATH") or "/data/smartx.db")
SCRIPT_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id TEXT PRIMARY KEY,
            version TEXT NOT NULL,
            description TEXT NOT NULL,
            script_sha256 TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    columns = {{row[1] for row in conn.execute("PRAGMA table_info(schema_migrations)").fetchall()}}
    if "id" not in columns and "name" in columns:
        rows = conn.execute("SELECT name, applied_at FROM schema_migrations").fetchall()
        conn.execute("ALTER TABLE schema_migrations RENAME TO schema_migrations_legacy")
        conn.execute(
            """
            CREATE TABLE schema_migrations (
                id TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                description TEXT NOT NULL,
                script_sha256 TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for name, applied_at in rows:
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (id, version, description, script_sha256, applied_at) VALUES (?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))",
                (name, "legacy", name, "", applied_at),
            )
        conn.execute("DROP TABLE schema_migrations_legacy")


def already_applied(conn: sqlite3.Connection, step_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM schema_migrations WHERE id = ?", (step_id,)).fetchone()
    return row is not None


def quote_identifier(value: str) -> str:
    cleaned = str(value)
    if not cleaned:
        raise ValueError("empty identifier")
    return '"' + cleaned.replace('"', '""') + '"'


def has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({{quote_identifier(table)}})").fetchall()
    return any(str(row[1]) == column for row in rows)


def apply_operation(conn: sqlite3.Connection, operation: dict) -> None:
    action = str(operation.get("action") or "")
    if action == "add_column_if_missing":
        table = str(operation["table"])
        column = str(operation["column"])
        definition = str(operation["definition"])
        if not has_column(conn, table, column):
            conn.execute(f"ALTER TABLE {{quote_identifier(table)}} ADD COLUMN {{quote_identifier(column)}} {{definition}}")
        return
    raise ValueError(f"Unsupported migration operation: {{action}}")


def apply_step(conn: sqlite3.Connection, step: dict) -> None:
    step_id = str(step["id"])
    if already_applied(conn, step_id):
        print(f"skip {{step_id}}")
        return
    for statement in step.get("sql") or []:
        sql = str(statement).strip()
        if sql:
            conn.execute(sql)
    for operation in step.get("operations") or []:
        apply_operation(conn, operation)
    conn.execute(
        "INSERT INTO schema_migrations (id, version, description, script_sha256, applied_at) VALUES (?, ?, ?, ?, ?)",
        (
            step_id,
            str(step["version"]),
            str(step["description"]),
            str(step.get("script_sha256") or SCRIPT_SHA256),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    print(f"applied {{step_id}}")


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"SQLite database not found: {{DB_PATH}}")
    with sqlite3.connect(DB_PATH) as conn:
        ensure_schema_migrations(conn)
        for step in STEPS:
            apply_step(conn, step)


if __name__ == "__main__":
    main()
'''


def write_migration_runner(path: Path, steps: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    source = _migration_runner_source(steps)
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)
    digest = sha256_file(path)
    public_steps = []
    for step in steps:
        public_steps.append(
            {
                "id": step["id"],
                "version": step["version"],
                "description": step["description"],
                "script_sha256": digest,
            }
        )
    return digest, public_steps


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
import sys

package_dir = Path(sys.argv[1])
project_root = Path(sys.argv[2])
backup_root = Path(sys.argv[3])
override_path = Path(sys.argv[4])
version = sys.argv[5]
manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
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

project_files = manifest.get("project_file_list") or []
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

services = {{}}
for component in manifest.get("components", []):
    if component.get("type") != "platform":
        continue
    for item in component.get("images", []):
        if item.get("service") in {{"web-api", "collector-worker", "frontend"}}:
            services[item["service"]] = item["image"]
lines = ["services:"]
for service in ("web-api", "collector-worker", "frontend"):
    image = services.get(service)
    if image:
        lines.append(f"  {{service}}:")
        lines.append(f"    image: {{image}}")
override_path.write_text("\\n".join(lines) + "\\n", encoding="utf-8")


print(f"已同步项目文件 {{len(copied)}} 个。")
print(f"项目文件备份目录：{{backup_root}}")
if missing_before:
    print("升级前不存在的项目文件：" + ", ".join(missing_before))
print(f"已写入 {{version}} 镜像覆盖配置到 {{override_path}}")
PY
'''
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


def assert_safe_members(members: Iterable[str]) -> None:
    bad = [member for member in members if any(pattern.search(member) for pattern in SENSITIVE_PATTERNS)]
    if bad:
        raise SystemExit("Sensitive paths refused in package: " + ", ".join(bad))


def collect_project_files(version: str, *, check_version_metadata: bool = True) -> list[str]:
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
    if check_version_metadata:
        offline_text = (ROOT / "docker-compose.offline.yml").read_text(encoding="utf-8")
        if f"SMARTX_IMAGE_TAG:-{version}" not in offline_text:
            raise SystemExit("docker-compose.offline.yml default tag does not match VERSION.")
        if "SMARTX_IMAGE_TAG:-latest" in offline_text:
            raise SystemExit("docker-compose.offline.yml must not default to latest.")
    return result


def build_package(
    version: str,
    *,
    min_version: str,
    output_dir: Path,
    build_images: bool,
    include_frontend_build: bool,
    migration_registry: Path | None = None,
    check_version_metadata: bool = True,
) -> Path:
    if check_version_metadata:
        check_versions(version)
    if build_images:
        docker_build(version, include_frontend=include_frontend_build)

    work = output_dir / f"smartx-capacity-insight-upgrade-{version}"
    package = output_dir / f"smartx-capacity-insight-upgrade-{version}.tar.gz"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    (work / "images").mkdir()

    manifest_images = []
    for service, _, release_repository, rel_path, restart in PLATFORM_IMAGES:
        image = release_image(release_repository, version)
        target = work / rel_path
        run(["docker", "save", "-o", str(target), image])
        item = {
            "service": service,
            "image": image,
            "archive": rel_path,
            "sha256": sha256_file(target),
        }
        if not restart:
            item["restart"] = False
        manifest_images.append(item)

    project_files = collect_project_files(version, check_version_metadata=check_version_metadata)
    for rel in project_files:
        target = work / "project" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)

    selected_migrations = _selected_migration_steps(_load_migration_registry(migration_registry or MIGRATION_REGISTRY), min_version=min_version, target_version=version)
    migration_runner = work / "migrations" / "run_migrations.py"
    migration_sha = ""
    migration_steps: list[dict[str, Any]] = []
    if selected_migrations:
        migration_sha, migration_steps = write_migration_runner(migration_runner, selected_migrations)

    manifest = {
        "schema_version": "3",
        "minimum_runner_protocol": 1,
        "required_capabilities": [
            "backup.create",
            "image.load",
            "files.sync",
            "compose.override",
            "compose.apply",
            "health.http",
            "rollback.restore",
        ],
        "product": PRODUCT,
        "package_id": f"smartx-capacity-insight-{version}",
        "version": version,
        "min_version": min_version,
        "package_type": "platform",
        "database_migration": bool(selected_migrations),
        "components": [
            {
                "type": "platform",
                "services": ["web-api", "collector-worker", "frontend"],
                "images": manifest_images,
            }
        ],
        "project_files": True,
        "project_file_list": project_files,
        "restart_services": ["web-api", "collector-worker", "frontend"],
        "compatibility": {"min_platform_version": min_version},
        "notes": "release-notes.md",
        "release_notes": f"{version} platform upgrade package.",
    }
    if selected_migrations:
        manifest["required_capabilities"].append("script.sandbox.v1")
        manifest["migration_steps"] = migration_steps
        manifest["migration"] = {
            "required": True,
            "script": "migrations/run_migrations.py",
            "sha256": migration_sha,
            "image_service": "web-api",
            "timeout_seconds": 900,
            "mounts": [
                {"source": "/data", "target": "/data", "mode": "rw"},
                {"source": "/data/backups", "target": "/data/backups", "mode": "rw"},
            ],
        }
    (work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (work / "release-notes.md").write_text(
        f"# {version}\n\n"
        "- Platform upgrade package for web-api, collector-worker, and frontend.\n"
        "- Syncs whitelisted project files such as compose, docs, and scripts.\n"
        "- Writes image overrides into docker-compose.upgrade.yml before service restart.\n\n"
        "This package does not include upgrade-runner, .env, databases, Prometheus data, Tower credentials, or runtime data.\n",
        encoding="utf-8",
    )

    members = [
        "manifest.json",
        "release-notes.md",
        "images/web-api.tar",
        "images/collector-worker.tar",
        "images/frontend.tar",
        *[f"project/{rel}" for rel in project_files],
    ]
    if selected_migrations:
        members.append("migrations/run_migrations.py")
    checksum_lines = [f"{sha256_file(work / member)}  {member}" for member in members]
    (work / "checksums.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    members.append("checksums.sha256")
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
