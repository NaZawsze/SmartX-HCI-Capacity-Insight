from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
