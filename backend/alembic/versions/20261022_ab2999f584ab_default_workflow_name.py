"""default workflow name

Revision ID: ab2999f584ab
Revises: ee74b04de32c
Create Date: 2026-10-22 21:55:14.160147

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ab2999f584ab'
down_revision: Union[str, Sequence[str], None] = 'ee74b04de32c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "workflows",
        "name",
        server_default="Untitled Workflow",
        existing_type=sa.String(length=255),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "workflows",
        "name",
        server_default=None,
        existing_type=sa.String(length=255),
        existing_nullable=False,
    )
