from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import get_settings

# Deterministic constraint names so Alembic autogenerate produces stable diffs.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def pooler_connect_args() -> dict[str, Any]:
    """asyncpg settings required behind Supavisor in transaction mode.

    In transaction mode consecutive statements may run on different backend
    connections, so server-side prepared statements can't be reused. Disable
    asyncpg's statement cache and give each prepared statement a unique name
    to avoid "prepared statement already exists" errors.
    """
    return {
        "statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    }


def create_engine(url: str, echo: bool = False) -> AsyncEngine:
    return create_async_engine(
        url,
        echo=echo,
        # Supavisor does the pooling; a second pool on our side would hold
        # connections the pooler expects back after each transaction.
        poolclass=NullPool,
        connect_args=pooler_connect_args(),
    )


settings = get_settings()
engine = create_engine(settings.database_url, echo=settings.db_echo)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session that rolls back on error."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
