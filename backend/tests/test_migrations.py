"""The migration chain and the SQLAlchemy models describe the same schema.

(The session fixture already ran downgrade-to-base then upgrade-to-head.)
"""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text

from app.database import Base, engine


async def test_models_match_migrations():
    def diff(sync_conn):
        context = MigrationContext.configure(sync_conn, opts={"compare_type": True})
        return compare_metadata(context, Base.metadata)

    async with engine.connect() as conn:
        differences = await conn.run_sync(diff)
    assert differences == [], f"models and migrations disagree; generate a migration: {differences}"


async def test_every_public_table_has_row_level_security():
    # On Supabase the public schema is served over PostgREST to anyone with
    # the (public) anon key; a table without RLS is readable and writable by
    # everyone. Any new table must enable RLS in its migration.
    async with engine.connect() as conn:
        rows = (await conn.execute(text("""
            SELECT c.relname, c.relrowsecurity
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
        """))).all()
    assert rows, "no tables found"
    assert [name for name, rls in rows if not rls] == []
