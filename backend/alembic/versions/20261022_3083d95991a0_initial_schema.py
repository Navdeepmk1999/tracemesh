"""initial schema

Revision ID: 3083d95991a0
Revises:
Create Date: 2026-10-22 10:00:34.544137

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '3083d95991a0'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

execution_status = postgresql.ENUM(
    'PENDING', 'RUNNING', 'COMPLETED', 'FAILED', name='execution_status'
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'workflows',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_workflows')),
    )
    op.create_table(
        'nodes',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('workflow_id', sa.UUID(), nullable=False),
        sa.Column('node_type', sa.String(length=100), nullable=False),
        sa.Column('config_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], name=op.f('fk_nodes_workflow_id_workflows'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_nodes')),
    )
    op.create_index(op.f('ix_nodes_workflow_id'), 'nodes', ['workflow_id'], unique=False)
    op.create_table(
        'executions',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('workflow_id', sa.UUID(), nullable=False),
        sa.Column('status', execution_status, server_default='PENDING', nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], name=op.f('fk_executions_workflow_id_workflows'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_executions')),
    )
    op.create_index(op.f('ix_executions_status'), 'executions', ['status'], unique=False)
    op.create_index(op.f('ix_executions_workflow_id'), 'executions', ['workflow_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_executions_workflow_id'), table_name='executions')
    op.drop_index(op.f('ix_executions_status'), table_name='executions')
    op.drop_table('executions')
    op.drop_index(op.f('ix_nodes_workflow_id'), table_name='nodes')
    op.drop_table('nodes')
    op.drop_table('workflows')
    execution_status.drop(op.get_bind(), checkfirst=True)
