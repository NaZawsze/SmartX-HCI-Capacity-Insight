#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
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
ENV_FILE = ROOT / ".env"
PACKAGE_DIR = Path("/data/upgrade-packages")
PRODUCT = "smartx-storage-forecast"
DEFAULT_MIN_VERSION = "v0.5.0"
RELEASE_NAMESPACE = "nazawsze"
TARGET_COMPOSE_PROJECT = "smartx-hci-capacity-insight"
TARGET_COMPOSE_NETWORK = "smartx-hci-capacity-insight-net"
TARGET_INSTALL_ROOT = "/data/smartx-storage-forecast"
TARGET_PROJECT_PATH = f"{TARGET_INSTALL_ROOT}/project"
TARGET_APP_DATA_PATH = f"{TARGET_INSTALL_ROOT}/app"
TARGET_PROMETHEUS_DATA_PATH = f"{TARGET_INSTALL_ROOT}/prometheus"
TARGET_UPGRADES_PATH = f"{TARGET_INSTALL_ROOT}/upgrades"
TARGET_BACKUPS_PATH = f"{TARGET_INSTALL_ROOT}/backups"
TARGET_EXPORTS_PATH = f"{TARGET_INSTALL_ROOT}/exports"
TARGET_COMPOSE_RUNTIME_PATH = f"{TARGET_INSTALL_ROOT}/compose-runtime"
LEGACY_COMPOSE_PROJECT = "smartx-storage-forecast"
LEGACY_COMPOSE_NETWORK = "smartx-storage-forecast_smartx-net"
LEGACY_PROJECT_PATH = "/opt/smartx-storage-forecast"
PATCH_SOURCE_VERSIONS = {
    "v0.5.1": ["v0.5.1u1", "v0.5.1u2"],
}
PLATFORM_IMAGES = [
    ("web-api", "smartx-hci-capacity-insight-web-api", "images/web-api.tar", True),
    ("collector-worker", "smartx-hci-capacity-insight-collector-worker", "images/collector-worker.tar", True),
    ("frontend", "smartx-hci-capacity-insight-frontend", "images/frontend.tar", True),
]
BASE_PLATFORM_SERVICES = ["web-api", "collector-worker", "frontend"]
PROMETHEUS_SERVICE = "prometheus"
UPGRADE_RUNNER_SERVICE = "upgrade-runner"
LEGACY_PLATFORM_CAPABILITIES = [
    "backup.create",
    "image.load",
    "files.sync",
    "compose.override",
    "compose.apply",
    "health.http",
    "rollback.restore",
]
MODERN_PLATFORM_CAPABILITIES = [
    "backup.v1",
    "image.v1",
    "files.v1",
    "compose.v1",
    "health.v1",
    "rollback.v1",
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
IMAGE_IDENTITY_MARKER = "SMARTX_IMAGE_IDENTITY:"


LEGACY_PROJECT_FILE_VALUES = [
    (TARGET_PROJECT_PATH, "/opt/smartx-storage-forecast"),
    (TARGET_APP_DATA_PATH, "/data/smartx-capacity-insight-data/app"),
    (TARGET_UPGRADES_PATH, "/data/upgrades"),
    (TARGET_BACKUPS_PATH, "/data/backups"),
    (TARGET_EXPORTS_PATH, "/data/exports"),
    (TARGET_COMPOSE_RUNTIME_PATH, "/data/compose-runtime"),
    (TARGET_PROMETHEUS_DATA_PATH, "/prometheus-data"),
    (TARGET_INSTALL_ROOT, "/opt/smartx-storage-forecast"),
    (TARGET_COMPOSE_NETWORK, LEGACY_COMPOSE_NETWORK),
    (TARGET_COMPOSE_PROJECT, LEGACY_COMPOSE_PROJECT),
    ("10.249.251.0/24", "10.249.249.0/24"),
    ("SMARTX_IMAGE_TAG:-v0.5.2", "SMARTX_IMAGE_TAG:-{version}"),
    ("SMARTX_RUNNER_IMAGE_TAG:-v0.3.1", "SMARTX_RUNNER_IMAGE_TAG:-v0.3.0"),
]


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
    for service, release_repository, _, _ in PLATFORM_IMAGES:
        expected = release_image(release_repository, version)
        if expected not in upgrade_text:
            raise SystemExit(f"docker-compose.upgrade.yml missing {expected}.")
    print(f"Version metadata OK: {version}")


def release_image(repository: str, version: str) -> str:
    return f"{RELEASE_NAMESPACE}/{repository}:{version}"


def _replace_default_version_constants(text: str, *, app_version: str, runner_version: str) -> str:
    text = re.sub(r'DEFAULT_APP_VERSION = "[^"]+"', f'DEFAULT_APP_VERSION = "{app_version}"', text)
    text = re.sub(r'DEFAULT_RUNNER_VERSION = "[^"]+"', f'DEFAULT_RUNNER_VERSION = "{runner_version}"', text)
    return text


def _replace_readme_version(text: str, *, app_version: str) -> str:
    text = re.sub(r"Version: `[^`]+`", f"Version: `{app_version}`", text)
    text = re.sub(r"版本：`[^`]+`", f"版本：`{app_version}`", text)
    return text


def _replace_compose_version_tags(text: str, *, app_version: str, runner_version: str) -> str:
    text = re.sub(r"SMARTX_IMAGE_TAG:-[^}]+", f"SMARTX_IMAGE_TAG:-{app_version}", text)
    text = re.sub(r"SMARTX_RUNNER_IMAGE_TAG:-[^}]+", f"SMARTX_RUNNER_IMAGE_TAG:-{runner_version}", text)
    text = re.sub(
        r"smartx-hci-capacity-insight-web-api:v[0-9A-Za-z._-]+",
        f"smartx-hci-capacity-insight-web-api:{app_version}",
        text,
    )
    text = re.sub(
        r"smartx-hci-capacity-insight-collector-worker:v[0-9A-Za-z._-]+",
        f"smartx-hci-capacity-insight-collector-worker:{app_version}",
        text,
    )
    text = re.sub(
        r"smartx-hci-capacity-insight-frontend:v[0-9A-Za-z._-]+",
        f"smartx-hci-capacity-insight-frontend:{app_version}",
        text,
    )
    return text


@contextlib.contextmanager
def temporary_image_version_metadata(version: str):
    runner_version = _expected_web_api_runner_baseline(version)
    paths = [
        VERSION_FILE,
        RUNNER_VERSION_FILE,
        ROOT / "backend/app/core/config.py",
        ROOT / "backend/app/v2/config.py",
        ROOT / "README.md",
        ROOT / "README.zh-CN.md",
        ROOT / "docker-compose.yml",
        ROOT / "docker-compose.offline.yml",
        ROOT / "docker-compose.release.yml",
        ROOT / "docker-compose.upgrade.yml",
    ]
    original = {path: path.read_text(encoding="utf-8") for path in paths}
    try:
        VERSION_FILE.write_text(version + "\n", encoding="utf-8")
        RUNNER_VERSION_FILE.write_text(runner_version + "\n", encoding="utf-8")
        for path in (ROOT / "backend/app/core/config.py", ROOT / "backend/app/v2/config.py"):
            path.write_text(
                _replace_default_version_constants(original[path], app_version=version, runner_version=runner_version),
                encoding="utf-8",
            )
        for path in (ROOT / "README.md", ROOT / "README.zh-CN.md"):
            path.write_text(_replace_readme_version(original[path], app_version=version), encoding="utf-8")
        for path in (
            ROOT / "docker-compose.yml",
            ROOT / "docker-compose.offline.yml",
            ROOT / "docker-compose.release.yml",
            ROOT / "docker-compose.upgrade.yml",
        ):
            path.write_text(
                _replace_compose_version_tags(original[path], app_version=version, runner_version=runner_version),
                encoding="utf-8",
            )
        yield runner_version
    finally:
        for path, text in original.items():
            path.write_text(text, encoding="utf-8")


@contextlib.contextmanager
def temporary_compose_env_file():
    existed = ENV_FILE.exists()
    if existed:
        yield
        return
    try:
        ENV_FILE.write_text("", encoding="utf-8")
        yield
    finally:
        if ENV_FILE.exists():
            ENV_FILE.unlink()


def docker_build(version: str, *, include_frontend: bool) -> None:
    services = ["web-api", "collector-worker"] + (["frontend"] if include_frontend else [])
    with temporary_image_version_metadata(version) as runner_version, temporary_compose_env_file():
        run(
            [
                "env",
                f"SMARTX_IMAGE_TAG={version}",
                f"SMARTX_RUNNER_IMAGE_TAG={runner_version}",
                "docker",
                "compose",
                "-f",
                "docker-compose.yml",
                "build",
                *services,
            ],
            cwd=ROOT,
        )


def validate_release_images(version: str) -> None:
    web_api_image = release_image("smartx-hci-capacity-insight-web-api", version)
    marker = "SMARTX_V2_HEALTH_OK"
    script = (
        "from app.v2.main import app\n"
        "paths={getattr(route, 'path', '') for route in app.routes}\n"
        "import importlib.util\n"
        "assert importlib.util.find_spec('app.v2.api') is not None, 'missing app.v2.api'\n"
        "assert '/api/system/health' in paths, 'missing /api/system/health'\n"
        f"print('{marker}')\n"
    )
    output = run(["docker", "run", "--rm", "--entrypoint", "python", web_api_image, "-c", script])
    if marker not in output:
        raise SystemExit(f"web-api image validation failed: {web_api_image} missing /api/system/health")
    validate_platform_image_identity(version)


def _expected_web_api_runner_baseline(version: str) -> str:
    if _version_tuple(version) < _version_tuple("v0.5.2"):
        return "v0.3.0"
    return read_runner_version()


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


def _assert_web_api_image_identity(*, image: str, version: str) -> dict[str, Any]:
    identity = _read_web_api_image_identity(image)
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
        raise SystemExit(f"web-api image identity mismatch for {image}: " + "; ".join(mismatches))
    return identity


def validate_platform_image_identity(version: str) -> None:
    _assert_web_api_image_identity(
        image=release_image("smartx-hci-capacity-insight-web-api", version),
        version=version,
    )


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


def _source_compatibility(*, min_version: str, target_version: str) -> dict[str, Any]:
    supported_versions = _supported_source_versions(min_version, target_version)
    supported_paths = [f"{version} -> {target_version}" for version in supported_versions]
    return {
        "min_version": min_version,
        "max_version_inclusive": target_version,
        "target_version": target_version,
        "allow_same_version": True,
        "supported_versions": supported_versions,
        "message": f"支持 {', '.join(supported_paths)}" if supported_paths else f"支持 {min_version} 至 {target_version} 升级到 {target_version}",
    }


def _environment_transitions(*, min_version: str, target_version: str) -> list[dict[str, Any]]:
    supported = _supported_source_versions(min_version, target_version)
    legacy_versions = [version for version in supported if _version_tuple(version) < _version_tuple("v0.5.2")]
    if _version_tuple(target_version) < _version_tuple("v0.5.2") or not legacy_versions:
        return []
    return [
        {
            "from_project": LEGACY_COMPOSE_PROJECT,
            "from_network": LEGACY_COMPOSE_NETWORK,
            "to_project": TARGET_COMPOSE_PROJECT,
            "to_network": TARGET_COMPOSE_NETWORK,
            "versions": legacy_versions,
        }
    ]


def _directory_transition(*, target_version: str) -> dict[str, Any]:
    if _version_tuple(target_version) < _version_tuple("v0.5.2"):
        return {}
    return {
        "target_root": TARGET_INSTALL_ROOT,
        "project_path": TARGET_PROJECT_PATH,
        "app_data_path": TARGET_APP_DATA_PATH,
        "prometheus_data_path": TARGET_PROMETHEUS_DATA_PATH,
        "upgrades_path": TARGET_UPGRADES_PATH,
        "backups_path": TARGET_BACKUPS_PATH,
        "exports_path": TARGET_EXPORTS_PATH,
        "compose_runtime_path": TARGET_COMPOSE_RUNTIME_PATH,
        "legacy_app_data_paths": ["/data/smartx-capacity-insight-data/app", "/data"],
        "legacy_prometheus_data_paths": ["/data/smartx-capacity-insight-data/prometheus", "/prometheus-data"],
        "env_file_migration": {
            "target": f"{TARGET_PROJECT_PATH}/.env",
            "legacy_candidates": [f"{LEGACY_PROJECT_PATH}/.env"],
            "preserve_existing": True,
            "sanitize_image_tags": True,
            "fallback_defaults": True,
            "require_credential_decryption": True,
        },
        "helper_image": release_image("smartx-hci-capacity-insight-web-api", target_version),
    }


def _legacy_cleanup(*, target_version: str) -> dict[str, Any]:
    if _version_tuple(target_version) < _version_tuple("v0.5.2"):
        return {}
    return {
        "helper_image": release_image("smartx-hci-capacity-insight-web-api", target_version),
        "legacy_projects": [LEGACY_COMPOSE_PROJECT],
        "legacy_networks": [LEGACY_COMPOSE_NETWORK],
        "legacy_paths": [
            "/opt/smartx-storage-forecast",
            "/data/upgrades",
            "/data/backups",
            "/data/exports",
            "/data/compose-runtime",
            "/data/smartx-capacity-insight-data",
            "/prometheus-data",
        ],
        "target_app_residual_paths": [],
        "protected_paths": [
            TARGET_INSTALL_ROOT,
            TARGET_PROJECT_PATH,
            TARGET_APP_DATA_PATH,
            TARGET_PROMETHEUS_DATA_PATH,
            TARGET_UPGRADES_PATH,
            TARGET_BACKUPS_PATH,
            TARGET_EXPORTS_PATH,
            TARGET_COMPOSE_RUNTIME_PATH,
        ],
        "required_health": {
            "version": target_version,
            "runner_version": read_runner_version(),
            "checks": ["directories", "database", "prometheus"],
        },
        "data_migration_guard": {
            "target_db_path": f"{TARGET_APP_DATA_PATH}/smartx.db",
            "legacy_db_paths": [
                "/data/smartx-capacity-insight-data/app/smartx.db",
                "/data/smartx.db",
            ],
        },
    }


def _post_upgrade(*, target_version: str, legacy_cleanup: dict[str, Any]) -> dict[str, Any]:
    if _version_tuple(target_version) < _version_tuple("v0.5.2") or not legacy_cleanup:
        return {}
    return {
        "auto_collection": True,
        "create_cleanup_task": True,
        "cleanup_task_policy": "after_platform_health_success",
        "cleanup_failure_severity": "warning",
    }


def _platform_services_for_version(version: str) -> list[str]:
    services = list(BASE_PLATFORM_SERVICES)
    if _version_tuple(version) >= _version_tuple("v0.5.2"):
        services.append(PROMETHEUS_SERVICE)
        services.append(UPGRADE_RUNNER_SERVICE)
    return services


def _supported_source_versions(min_version: str, target_version: str) -> list[str]:
    try:
        min_tuple = _version_tuple(min_version)
        target_tuple = _version_tuple(target_version)
    except SystemExit:
        return []
    min_major, min_minor, min_patch, _ = min_tuple
    target_major, target_minor, target_patch, _ = target_tuple
    if (min_major, min_minor) != (target_major, target_minor) or min_patch > target_patch:
        return []
    versions: list[str] = []
    for patch in range(min_patch, target_patch + 1):
        version = f"v{min_major}.{min_minor}.{patch}"
        candidates = [version, *PATCH_SOURCE_VERSIONS.get(version, [])]
        versions.extend(
            candidate
            for candidate in candidates
            if min_tuple <= _version_tuple(candidate) <= target_tuple
        )
    return sorted(dict.fromkeys(versions), key=_version_tuple)


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

PROJECT_ROOT="${{SMARTX_PROJECT_PATH:-/data/smartx-storage-forecast/project}}"
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


def _project_file_override(rel: str, *, version: str) -> str | None:
    if rel not in {"docker-compose.offline.yml", "docker-compose.release.yml", "docker-compose.yml"}:
        return None
    text = (ROOT / rel).read_text(encoding="utf-8")
    runner_version = _expected_web_api_runner_baseline(version)
    if _version_tuple(version) < _version_tuple("v0.5.2"):
        for old, new in LEGACY_PROJECT_FILE_VALUES:
            text = text.replace(old, new.format(version=version))
    return _render_packaged_compose_tags(text, app_version=version, runner_version=runner_version)


def _render_packaged_compose_tags(text: str, *, app_version: str, runner_version: str) -> str:
    text = re.sub(
        r"\$\{SMARTX_IMAGE_PREFIX:-([^}]+)\}/([^:\s]+):\$\{SMARTX_IMAGE_TAG:-[^}]+}",
        rf"\1/\2:{app_version}",
        text,
    )
    text = re.sub(
        r"\$\{SMARTX_RUNNER_IMAGE_PREFIX:-([^}]+)\}/([^:\s]+):\$\{SMARTX_RUNNER_IMAGE_TAG:-[^}]+}",
        rf"\1/\2:{runner_version}",
        text,
    )
    text = re.sub(
        r"\$\{SMARTX_IMAGE_PREFIX:-([^}]+)\}/([^:\s]+):\$\{SMARTX_RUNNER_IMAGE_TAG:-[^}]+}",
        rf"\1/\2:{runner_version}",
        text,
    )
    return text


def _assert_project_files_match_version(version: str, project_dir: Path) -> None:
    compose_files = [
        project_dir / "docker-compose.release.yml",
        project_dir / "docker-compose.offline.yml",
        project_dir / "docker-compose.yml",
    ]
    if _version_tuple(version) < _version_tuple("v0.5.2"):
        required = [
            "name: smartx-storage-forecast",
            "SMARTX_COMPOSE_PROJECT_NAME: smartx-storage-forecast",
            "SMARTX_PROJECT_PATH: /opt/smartx-storage-forecast",
            "/data/smartx-capacity-insight-data/app:/data",
            "/data/upgrades:/data/upgrades",
            "/data/backups:/data/backups",
            "/data/exports:/data/exports",
            "/data/compose-runtime:/data/compose-runtime",
            "/prometheus-data:/prometheus-data",
            "name: smartx-storage-forecast_smartx-net",
            "subnet: 10.249.249.0/24",
            f":{version}",
            ":v0.3.0",
        ]
        forbidden = [
            "smartx-hci-capacity-insight-net",
            "/data/smartx-storage-forecast",
            "10.249.251.0/24",
            "SMARTX_IMAGE_TAG",
            "SMARTX_RUNNER_IMAGE_TAG",
        ]
    else:
        required = [
            "name: smartx-hci-capacity-insight",
            "SMARTX_COMPOSE_PROJECT_NAME: smartx-hci-capacity-insight",
            "SMARTX_PROJECT_PATH: /data/smartx-storage-forecast/project",
            "/data/smartx-storage-forecast/app:/data",
            "name: smartx-hci-capacity-insight-net",
            "subnet: 10.249.251.0/24",
            f":{version}",
            f":{read_runner_version()}",
        ]
        forbidden = ["SMARTX_IMAGE_TAG", "SMARTX_RUNNER_IMAGE_TAG"]
    for path in compose_files:
        text = path.read_text(encoding="utf-8")
        missing = [item for item in required if item not in text]
        if missing:
            raise SystemExit(f"{path.relative_to(project_dir.parent)} does not match {version}: missing {', '.join(missing)}")
        present = [item for item in forbidden if item in text]
        if present:
            raise SystemExit(f"{path.relative_to(project_dir.parent)} does not match {version}: contains {', '.join(present)}")


def build_package(
    version: str,
    *,
    min_version: str,
    output_dir: Path,
    build_images: bool,
    include_frontend_build: bool,
    allow_existing_images: bool = False,
    migration_registry: Path | None = None,
    check_version_metadata: bool = True,
) -> Path:
    if check_version_metadata:
        with temporary_image_version_metadata(version):
            check_versions(version)
            return build_package(
                version,
                min_version=min_version,
                output_dir=output_dir,
                build_images=build_images,
                include_frontend_build=include_frontend_build,
                allow_existing_images=allow_existing_images,
                migration_registry=migration_registry,
                check_version_metadata=False,
            )
    if build_images:
        docker_build(version, include_frontend=include_frontend_build)
    elif not allow_existing_images:
        raise SystemExit("--no-build requires --allow-existing-images so polluted local tags cannot be reused silently.")
    validate_release_images(version)

    work = output_dir / f"smartx-capacity-insight-upgrade-{version}"
    package = output_dir / f"smartx-capacity-insight-upgrade-{version}.tar.gz"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    (work / "images").mkdir()

    manifest_images = []
    for service, release_repository, rel_path, restart in PLATFORM_IMAGES:
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
    if _version_tuple(version) >= _version_tuple("v0.5.2"):
        manifest_images.append(
            {
                "service": UPGRADE_RUNNER_SERVICE,
                "image": release_image("smartx-hci-capacity-insight-upgrade-runner", read_runner_version()),
                "archive": None,
            }
        )

    project_files = collect_project_files(version, check_version_metadata=check_version_metadata)
    for rel in project_files:
        target = work / "project" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        override = _project_file_override(rel, version=version)
        if override is None:
            shutil.copy2(ROOT / rel, target)
        else:
            target.write_text(override, encoding="utf-8")
    _assert_project_files_match_version(version, work / "project")

    selected_migrations = _selected_migration_steps(_load_migration_registry(migration_registry or MIGRATION_REGISTRY), min_version=min_version, target_version=version)
    environment_transitions = _environment_transitions(min_version=min_version, target_version=version)
    directory_transition = _directory_transition(target_version=version)
    legacy_cleanup = _legacy_cleanup(target_version=version)
    post_upgrade = _post_upgrade(target_version=version, legacy_cleanup=legacy_cleanup)
    migration_runner = work / "migrations" / "run_migrations.py"
    migration_sha = ""
    migration_steps: list[dict[str, Any]] = []
    if selected_migrations:
        migration_sha, migration_steps = write_migration_runner(migration_runner, selected_migrations)

    is_modern_platform_package = _version_tuple(version) >= _version_tuple("v0.5.2")
    manifest = {
        "schema_version": "3",
        "minimum_runner_protocol": 1,
        "required_capabilities": list(MODERN_PLATFORM_CAPABILITIES if is_modern_platform_package else LEGACY_PLATFORM_CAPABILITIES),
        "product": PRODUCT,
        "package_id": f"smartx-capacity-insight-{version}",
        "version": version,
        "min_version": min_version,
        "package_type": "platform",
        "database_migration": bool(selected_migrations),
        "components": [
            {
                "type": "platform",
                "services": _platform_services_for_version(version),
                "images": manifest_images,
            }
        ],
        "project_files": True,
        "project_file_list": project_files,
        "restart_services": _platform_services_for_version(version),
        "compatibility": {"min_platform_version": min_version},
        "source_compatibility": _source_compatibility(min_version=min_version, target_version=version),
        "notes": "release-notes.md",
        "release_notes": f"{version} platform upgrade package.",
    }
    if is_modern_platform_package:
        manifest["minimum_runner_version"] = read_runner_version()
    if environment_transitions:
        if directory_transition:
            environment_transitions = [
                {**transition, "directory_transition": directory_transition}
                for transition in environment_transitions
            ]
        manifest["required_capabilities"].append("compose.project.v1")
        manifest["environment_transitions"] = environment_transitions
    if directory_transition:
        manifest["directory_transition"] = directory_transition
    if legacy_cleanup:
        manifest["legacy_cleanup"] = legacy_cleanup
    if post_upgrade:
        manifest["post_upgrade"] = post_upgrade
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
    compatibility = _source_compatibility(min_version=min_version, target_version=version)
    migration_note = (
        "本包不包含 SQLite schema 迁移脚本；manifest 中 `database_migration=false`，且不包含 "
        "`migration`、`migration_steps` 或 `script.sandbox.v1`。"
        if not selected_migrations
        else f"本包包含累计 SQLite schema 迁移脚本 `migrations/run_migrations.py`，由 upgrade-runner {read_runner_version()} 以单脚本沙箱方式执行。"
    )
    migration_tree = "\n└── migrations/\n    └── run_migrations.py" if selected_migrations else ""
    runner_scope_note = (
        f"- 最低 Runner 版本：`{read_runner_version()}`；预检查不满足时会阻止升级，并提示先升级 upgrade-runner。\n"
        if is_modern_platform_package
        else "- Runner 要求：兼容现有 upgrade-runner v0.3.0 能力；本桥包不要求先升级 runner。\n"
    )
    (work / "release-notes.md").write_text(
        f"# SmartX HCI Capacity Insight {version} 升级包说明\n\n"
        "## 适用范围\n\n"
        f"- 目标版本：`{version}`。\n"
        f"- 最低来源版本：`{min_version}`。\n"
        f"{runner_scope_note}"
        f"- 兼容升级路径：{compatibility['message']}。\n"
        "- 支持同版本应用，用于修复安装、重同步镜像、项目文件和运行时 override。\n"
        "- 仅适用于 v2 同架构升级流程；v1 或 v0.4.x 现场请通过数据迁移进入 v2。\n\n"
        "## 本次更新与修复\n\n"
        "- 优化容量增长速率计算，日报表与报表页面的日/月/季度增长展示更贴近实际预算场景。\n"
        "- 修复虚拟机页面首次加载时趋势图重复加载的问题，避免同一 VM 在初始化阶段重复请求趋势、详情和卷数据。\n"
        "- 修复平台升级页已完成升级包无法删除的问题；运行中或需要恢复处理的任务仍禁止删除。\n"
        "- v0.5.2 平台 compose 重建会同时启动 `prometheus` 服务；Prometheus 镜像不进入本包，预检查会确认目标机已有 `prom/prometheus:v2.55.1`。\n"
        f"- v0.5.2 平台升级会准备单根目录 `{TARGET_INSTALL_ROOT}`，并将旧 app 数据和 Prometheus 历史指标迁入 `{TARGET_APP_DATA_PATH}` / `{TARGET_PROMETHEUS_DATA_PATH}`。\n"
        f"- 升级执行前由 upgrade-runner {read_runner_version()} 迁移旧 Compose project/network：`{LEGACY_COMPOSE_PROJECT}` / `{LEGACY_COMPOSE_NETWORK}` -> `{TARGET_COMPOSE_PROJECT}` / `{TARGET_COMPOSE_NETWORK}`，避免同网段网络重叠。\n"
        "- 同步服务状态、观测组件版本、compose project/network、报表数据质量、文档和升级包兼容说明相关更新。\n\n"
        "## 升级包组成\n\n"
        "```text\n"
        f"smartx-capacity-insight-upgrade-{version}.tar.gz\n"
        "├── manifest.json\n"
        "├── checksums.sha256\n"
        "├── release-notes.md\n"
        "├── images/\n"
        "│   ├── web-api.tar\n"
        "│   ├── collector-worker.tar\n"
        "│   └── frontend.tar\n"
        "└── project/\n"
        "    ├── docker-compose.yml\n"
        "    ├── docker-compose.offline.yml\n"
        "    ├── docker-compose.release.yml\n"
        "    ├── README.md\n"
        "    ├── README.zh-CN.md\n"
        "    ├── docs/\n"
        "    ├── prometheus/\n"
        "    └── scripts/"
        f"{migration_tree}\n"
        "```\n\n"
        "## 执行动作\n\n"
        "- 创建升级前备份。\n"
        "- 校验 `checksums.sha256` 中列出的包内文件。\n"
        "- 加载 `web-api`、`collector-worker`、`frontend` 镜像。\n"
        f"- 创建 `{TARGET_INSTALL_ROOT}` 单根目录结构，目标已有数据时不覆盖。\n"
        "- 同步白名单内项目文件。\n"
        "- 写入运行时升级 override，并 recreate 平台服务和 Prometheus 服务。\n"
        "- 如来源版本仍使用旧 Compose project/network，则停止并删除旧 project 容器，确认旧网络没有外部容器后删除旧网络，再创建新 project/network。\n"
        "- 执行 HTTP 健康检查，失败时按升级中心策略触发一次自动回滚。\n\n"
        "## 数据库迁移\n\n"
        f"{migration_note}\n\n"
        "## 不包含内容\n\n"
        "本包不包含 `upgrade-runner`、`.env`、SQLite 数据库、Prometheus 历史数据、备份、导出文件、Tower 凭据、token、客户现场数据或其他运行时数据。\n",
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
    parser.add_argument("--allow-existing-images", action="store_true", help="Allow --no-build to reuse existing images after strict image identity checks.")
    parser.add_argument("--skip-frontend-build", action="store_true", help="Do not build frontend image before packaging.")
    parser.add_argument("--min-version", default=DEFAULT_MIN_VERSION)
    parser.add_argument("--output-dir", type=Path, default=PACKAGE_DIR)
    args = parser.parse_args()

    version = read_version()
    if args.check_version:
        check_versions(version)
        return
    args.output_dir.mkdir(parents=True, exist_ok=True)
    build_package(
        version,
        min_version=args.min_version,
        output_dir=args.output_dir,
        build_images=not args.no_build,
        allow_existing_images=args.allow_existing_images,
        include_frontend_build=not args.skip_frontend_build,
    )


if __name__ == "__main__":
    main()
