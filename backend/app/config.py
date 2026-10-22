from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TraceMesh API"
    environment: str = "development"

    # Supabase Supavisor pooler, transaction mode (port 6543), e.g.
    # postgresql+asyncpg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
    database_url: str
    # Optional direct or session-mode URL for Alembic. Falls back to database_url.
    migration_database_url: str | None = None
    db_echo: bool = False

    # AMQP broker, e.g. amqps://<user>:<password>@<host>/<vhost> (CloudAMQP)
    rabbitmq_url: str
    # Unacked messages a single worker may hold at once.
    worker_prefetch_count: int = 1

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
