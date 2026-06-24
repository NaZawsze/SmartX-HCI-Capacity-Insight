from functools import lru_cache
from pathlib import Path
import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

IMAGE_VERSION_FILE = Path("/app/VERSION")
RUNNER_VERSION_FILE = Path("/app/RUNNER_VERSION")
DEFAULT_APP_VERSION = "v0.5.1"
DEFAULT_RUNNER_VERSION = "v0.3.0"


def read_app_version(version_file: Path = IMAGE_VERSION_FILE) -> str:
    if version_file.exists():
        version = version_file.read_text(encoding="utf-8").strip()
        if version:
            return version
    return os.environ.get("SMARTX_APP_VERSION", DEFAULT_APP_VERSION).strip() or DEFAULT_APP_VERSION


def read_runner_version(version_file: Path = RUNNER_VERSION_FILE) -> str:
    if version_file.exists():
        version = version_file.read_text(encoding="utf-8").strip()
        if version:
            return version
    return os.environ.get("SMARTX_RUNNER_VERSION", DEFAULT_RUNNER_VERSION).strip() or DEFAULT_RUNNER_VERSION


class Settings(BaseSettings):
    app_name: str = "SmartX Storage Forecast"
    environment: str = "production"
    data_path: Path = Field(default=Path("/data"), alias="SMARTX_DATA_PATH")
    db_path: Path = Field(default=Path("/data/smartx.db"), alias="SMARTX_DB_PATH")
    prometheus_data_path: Path = Field(default=Path("/prometheus-data"), alias="SMARTX_PROMETHEUS_DATA_PATH")
    secret_key: str = Field(default="change-me-in-production", alias="SMARTX_SECRET_KEY")
    credential_key: str | None = Field(default=None, alias="SMARTX_CREDENTIAL_KEY")
    admin_user: str = Field(default="admin", alias="SMARTX_ADMIN_USER")
    admin_password: str = Field(default="password", alias="SMARTX_ADMIN_PASSWORD")
    prometheus_url: str = Field(default="http://prometheus:9090", alias="SMARTX_PROMETHEUS_URL")
    collection_timezone: str = Field(default="Asia/Shanghai", alias="SMARTX_COLLECTION_TIMEZONE")
    collection_hour: int = Field(default=2, alias="SMARTX_COLLECTION_HOUR")
    collection_minute: int = Field(default=10, alias="SMARTX_COLLECTION_MINUTE")
    cors_origins: str = Field(default="*", alias="SMARTX_CORS_ORIGINS")
    token_ttl_minutes: int = Field(default=720, alias="SMARTX_TOKEN_TTL_MINUTES")
    upgrade_path: Path = Field(default=Path("/data/upgrades"), alias="SMARTX_UPGRADE_PATH")
    backup_path: Path = Field(default=Path("/data/backups"), alias="SMARTX_BACKUP_PATH")
    export_path: Path = Field(default=Path("/data/exports"), alias="SMARTX_EXPORT_PATH")
    runtime_path: Path = Field(default=Path("/data/compose-runtime"), alias="SMARTX_RUNTIME_PATH")
    project_path: Path = Field(default=Path("/opt/smartx-storage-forecast"), alias="SMARTX_PROJECT_PATH")
    compose_file: str = Field(default="docker-compose.yml", alias="SMARTX_COMPOSE_FILE")
    compose_project_name: str = Field(default="smartx-hci-capacity-insight", alias="SMARTX_COMPOSE_PROJECT_NAME")
    app_version: str = Field(default_factory=read_app_version)
    runner_version: str = Field(default_factory=read_runner_version, alias="SMARTX_RUNNER_VERSION")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
