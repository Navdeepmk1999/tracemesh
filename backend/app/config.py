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

    # Supabase Auth. Legacy projects sign user JWTs with HS256 and this shared
    # secret (Project Settings > API > JWT Secret).
    supabase_jwt_secret: str | None = None
    # https://<project-ref>.supabase.co. Enables verifying asymmetric (ES256/RS256)
    # tokens against the project's JWKS, and checks the token issuer.
    supabase_url: str | None = None
    jwt_audience: str = "authenticated"

    # AMQP broker, e.g. amqps://<user>:<password>@<host>/<vhost> (CloudAMQP)
    rabbitmq_url: str
    # Unacked messages a single worker may hold at once.
    worker_prefetch_count: int = 1

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
