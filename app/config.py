from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    dev_payment_bypass: bool = True

    github_token: str | None = None
    github_notify_token: str | None = None

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    clickhouse_host: str | None = None
    clickhouse_port: int = 8443
    clickhouse_user: str = "default"
    clickhouse_password: str | None = None
    clickhouse_database: str = "default"
    clickhouse_secure: bool = True

    senso_api_key: str | None = None
    nimble_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
