"""enable rls on public tables

Supabase serves the public schema over its REST API (PostgREST), and by
default grants the anon and authenticated roles full access to tables
created there. With RLS off, anyone holding the anon key (which ships in the
frontend bundle) could read and write every tenant's rows directly,
bypassing the API's user_id checks entirely.

RLS is enabled with no policies, so those roles see and change nothing, and
their grants are revoked as a second layer. The backend is unaffected: it
connects as the tables' owner (postgres), which RLS doesn't apply to.

Revision ID: 4ec12bc82981
Revises: ab2999f584ab
Create Date: 2026-10-22 21:55:14.374237

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4ec12bc82981'
down_revision: Union[str, Sequence[str], None] = 'ab2999f584ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = ("workflows", "nodes", "edges", "executions", "node_runs", "alembic_version")
CLIENT_ROLES = ("anon", "authenticated")


def upgrade() -> None:
    """Upgrade schema."""
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    # The roles only exist on Supabase; plain Postgres (tests, CI) skips this.
    roles = ", ".join(CLIENT_ROLES)
    op.execute(f"""
        DO $$
        BEGIN
            IF (SELECT count(*) FROM pg_roles WHERE rolname IN ('anon', 'authenticated')) = 2 THEN
                REVOKE ALL ON TABLE {", ".join(TABLES)} FROM {roles};
            END IF;
        END $$;
    """)


def downgrade() -> None:
    """Downgrade schema."""
    # Deliberately does not re-grant anon/authenticated: rolling back this
    # migration must not re-open the tables to the public REST API.
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
