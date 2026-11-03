import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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

    # Redis for live trace Pub/Sub, e.g. rediss://default:<token>@<host>.upstash.io:6379
    redis_url: str

    # Browser origins allowed by CORS: a JSON list (["https://app.example.com"]) or
    # comma-separated. Browsers send the origin as scheme://host[:port] with no
    # path, so entries must match that exactly; see _parse_origins.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_origins(cls, value: Any) -> Any:
        """Accept a JSON list or comma-separated origins, normalised.

        A trailing slash or stray whitespace (easy to paste into a dashboard)
        would otherwise never match the browser's Origin header, and every
        preflight would fail with 400 "Disallowed CORS origin".
        """
        if isinstance(value, str):
            text = value.strip()
            value = json.loads(text) if text.startswith("[") else text.split(",")
        if isinstance(value, list):
            value = [o.strip().rstrip("/") if isinstance(o, str) else o for o in value]
            value = [o for o in value if o != ""]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
