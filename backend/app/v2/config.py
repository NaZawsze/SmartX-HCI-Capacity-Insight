from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


IMAGE_VERSION_FILE = Path("/app/VERSION")
RUNNER_VERSION_FILE = Path("/app/RUNNER_VERSION")
DEFAULT_APP_VERSION = "v0.5.0"
DEFAULT_RUNNER_VERSION = "v0.3.0"
DEFAULT_DATA_ROOT = Path("/data")
DEFAULT_SQLITE_PATH = DEFAULT_DATA_ROOT / "smartx.db"
DEFAULT_PROMETHEUS_DATA_PATH = Path("/prometheus-data")


def read_version(version_file: Path, env_name: str, default: str) -> str:
    if version_file.exists():
        version = version_file.read_text(encoding="utf-8").strip()
        if version:
            return version
    return os.environ.get(env_name, default).strip() or default


@dataclass(frozen=True)
class V2Settings:
    data_root: Path = DEFAULT_DATA_ROOT
    db_path_override: Path | None = field(
        default_factory=lambda: Path(value) if (value := os.environ.get("SMARTX_DB_PATH")) else None
    )
    prometheus_data_path_override: Path | None = field(
        default_factory=lambda: Path(value) if (value := os.environ.get("SMARTX_PROMETHEUS_DATA_PATH")) else None
    )
    secret_key: str = field(default_factory=lambda: os.environ.get("SMARTX_SECRET_KEY", "change-me-in-production"))
    credential_key: str | None = field(default_factory=lambda: os.environ.get("SMARTX_CREDENTIAL_KEY"))
    admin_user: str = field(default_factory=lambda: os.environ.get("SMARTX_ADMIN_USER", "admin"))
    admin_password: str = field(default_factory=lambda: os.environ.get("SMARTX_ADMIN_PASSWORD", "password"))
    timezone: str = field(default_factory=lambda: os.environ.get("SMARTX_COLLECTION_TIMEZONE", "Asia/Shanghai"))
    prometheus_url: str = field(default_factory=lambda: os.environ.get("SMARTX_PROMETHEUS_URL", "http://prometheus:9090"))
    compose_file: str = field(default_factory=lambda: os.environ.get("SMARTX_COMPOSE_FILE", "docker-compose.offline.yml"))
    compose_project_name: str = field(default_factory=lambda: os.environ.get("SMARTX_COMPOSE_PROJECT_NAME", "smartx-storage-forecast"))
    app_version: str = field(default_factory=lambda: read_version(IMAGE_VERSION_FILE, "SMARTX_APP_VERSION", DEFAULT_APP_VERSION))
    runner_version: str = field(default_factory=lambda: read_version(RUNNER_VERSION_FILE, "SMARTX_RUNNER_VERSION", DEFAULT_RUNNER_VERSION))
    token_ttl_minutes: int = field(default_factory=lambda: int(os.environ.get("SMARTX_TOKEN_TTL_MINUTES", "720")))

    def __post_init__(self) -> None:
        data_root = Path(self.data_root)
        object.__setattr__(self, "data_root", data_root)
        if self.db_path_override is not None:
            object.__setattr__(self, "db_path_override", Path(self.db_path_override))
            if data_root != DEFAULT_DATA_ROOT and Path(self.db_path_override) == DEFAULT_SQLITE_PATH:
                object.__setattr__(self, "db_path_override", None)
        elif data_root == DEFAULT_DATA_ROOT:
            object.__setattr__(self, "db_path_override", DEFAULT_SQLITE_PATH)
        if self.prometheus_data_path_override is not None:
            object.__setattr__(self, "prometheus_data_path_override", Path(self.prometheus_data_path_override))
            if data_root != DEFAULT_DATA_ROOT and Path(self.prometheus_data_path_override) == DEFAULT_PROMETHEUS_DATA_PATH:
                object.__setattr__(self, "prometheus_data_path_override", None)
        elif data_root == DEFAULT_DATA_ROOT:
            object.__setattr__(self, "prometheus_data_path_override", DEFAULT_PROMETHEUS_DATA_PATH)

    @property
    def app_data_dir(self) -> Path:
        return self.data_root / "smartx-capacity-insight-data" / "app"

    @property
    def sqlite_dir(self) -> Path:
        if self.db_path_override is not None:
            return self.db_path_override.parent
        return self.app_data_dir

    @property
    def sqlite_path(self) -> Path:
        if self.db_path_override is not None:
            return self.db_path_override
        return self.sqlite_dir / "smartx.db"

    @property
    def prometheus_data_dir(self) -> Path:
        if self.prometheus_data_path_override is not None:
            return self.prometheus_data_path_override
        return self.data_root / "smartx-capacity-insight-data" / "prometheus"

    @property
    def upgrades_dir(self) -> Path:
        return self.data_root / "upgrades"

    @property
    def backups_dir(self) -> Path:
        return self.data_root / "backups"

    @property
    def exports_dir(self) -> Path:
        return self.data_root / "exports"

    @property
    def reports_dir(self) -> Path:
        return self.exports_dir / "reports"

    @property
    def migrations_dir(self) -> Path:
        return self.exports_dir / "migrations"

    @property
    def imports_dir(self) -> Path:
        return self.exports_dir / "imports"

    @property
    def migration_tasks_dir(self) -> Path:
        return self.exports_dir / "migration-tasks"

    @property
    def compose_runtime_dir(self) -> Path:
        return self.data_root / "compose-runtime"

    def required_directories(self) -> list[Path]:
        return [
            self.sqlite_dir,
            self.prometheus_data_dir,
            self.upgrades_dir,
            self.backups_dir,
            self.reports_dir,
            self.migrations_dir,
            self.imports_dir,
            self.migration_tasks_dir,
            self.compose_runtime_dir,
        ]

    def ensure_directories(self) -> None:
        for directory in self.required_directories():
            directory.mkdir(parents=True, exist_ok=True)


def settings_from_environment() -> V2Settings:
    data_root = Path(os.environ.get("SMARTX_DATA_ROOT", os.environ.get("SMARTX_DATA_PATH", "/data")))
    db_path = os.environ.get("SMARTX_DB_PATH")
    if data_root != Path("/data") and db_path == "/data/smartx.db":
        db_path = None
    prometheus_data_path = os.environ.get("SMARTX_PROMETHEUS_DATA_PATH")
    return V2Settings(
        data_root=data_root,
        db_path_override=Path(db_path) if db_path else None,
        prometheus_data_path_override=Path(prometheus_data_path) if prometheus_data_path else None,
    )
