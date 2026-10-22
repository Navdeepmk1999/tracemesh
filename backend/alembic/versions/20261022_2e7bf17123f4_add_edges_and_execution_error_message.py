"""add edges and execution error_message

Revision ID: 2e7bf17123f4
Revises: 2a9412a721e3
Create Date: 2026-10-22 16:20:47.351383

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2e7bf17123f4'
down_revision: Union[str, Sequence[str], None] = '2a9412a721e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Must exist before edges: it is the target of edges' composite FKs.
    op.create_unique_constraint(op.f('uq_nodes_workflow_id'), 'nodes', ['workflow_id', 'id'])
    op.create_table('edges',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('workflow_id', sa.UUID(), nullable=False),
    sa.Column('source_node_id', sa.UUID(), nullable=False),
    sa.Column('target_node_id', sa.UUID(), nullable=False),
    sa.CheckConstraint('source_node_id <> target_node_id', name=op.f('ck_edges_no_self_loop')),
    sa.ForeignKeyConstraint(['workflow_id', 'source_node_id'], ['nodes.workflow_id', 'nodes.id'], name='fk_edges_source_node_nodes', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workflow_id', 'target_node_id'], ['nodes.workflow_id', 'nodes.id'], name='fk_edges_target_node_nodes', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], name=op.f('fk_edges_workflow_id_workflows'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_edges')),
    sa.UniqueConstraint('source_node_id', 'target_node_id', name=op.f('uq_edges_source_node_id'))
    )
    op.create_index(op.f('ix_edges_target_node_id'), 'edges', ['target_node_id'], unique=False)
    op.create_index(op.f('ix_edges_workflow_id'), 'edges', ['workflow_id'], unique=False)
    op.add_column('executions', sa.Column('error_message', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('executions', 'error_message')
    op.drop_index(op.f('ix_edges_workflow_id'), table_name='edges')
    op.drop_index(op.f('ix_edges_target_node_id'), table_name='edges')
    op.drop_table('edges')
    # Only droppable once the edges FKs that reference it are gone.
    op.drop_constraint(op.f('uq_nodes_workflow_id'), 'nodes', type_='unique')

