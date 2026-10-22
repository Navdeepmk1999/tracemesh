"""add node_runs

Revision ID: ee74b04de32c
Revises: 2e7bf17123f4
Create Date: 2026-10-22 16:28:47.738826

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'ee74b04de32c'
down_revision: Union[str, Sequence[str], None] = '2e7bf17123f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # status reuses the execution_status type created in the initial migration.
    op.create_table('node_runs',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('execution_id', sa.UUID(), nullable=False),
    sa.Column('node_id', sa.UUID(), nullable=False),
    sa.Column('status', postgresql.ENUM(name='execution_status', create_type=False), server_default='PENDING', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_message', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['execution_id'], ['executions.id'], name=op.f('fk_node_runs_execution_id_executions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['node_id'], ['nodes.id'], name=op.f('fk_node_runs_node_id_nodes'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_node_runs')),
    sa.UniqueConstraint('execution_id', 'node_id', name=op.f('uq_node_runs_execution_id'))
    )
    op.create_index(op.f('ix_node_runs_node_id'), 'node_runs', ['node_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_node_runs_node_id'), table_name='node_runs')
    op.drop_table('node_runs')
