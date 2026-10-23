"""The migration chain and the SQLAlchemy models describe the same schema.

(The session fixture already ran downgrade-to-base then upgrade-to-head.)
"""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.database import Base, engine


async def test_models_match_migrations():
    def diff(sync_conn):
        context = MigrationContext.configure(sync_conn, opts={"compare_type": True})
        return compare_metadata(context, Base.metadata)

    async with engine.connect() as conn:
        differences = await conn.run_sync(diff)
    assert differences == [], f"models and migrations disagree; generate a migration: {differences}"
