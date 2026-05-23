from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    dev_payment_bypass: bool = True
    app_base_url: str = "http://localhost:8000"

    stripe_secret_key: str | None = None
    stripe_currency: str = "usd"
    stripe_low_severity_cents: int = 50
    stripe_medium_severity_cents: int = 50
    stripe_high_severity_cents: int = 50

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
    senso_content_type_id: str | None = None
    senso_publish_destination: str = "cited-md"
    nimble_api_key: str | None = None

    langsmith_tracing: bool = True
    langsmith_api_key: str | None = None
    langsmith_project: str = "docs-gap-agent"
    langsmith_endpoint: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
