import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ExecutionStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Supabase auth user (JWT `sub`) that owns this workflow. Every API query
    # filters on it; nodes and executions inherit ownership through workflow_id.
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    nodes: Mapped[list["Node"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", passive_deletes=True
    )
    edges: Mapped[list["Edge"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", passive_deletes=True
    )
    executions: Mapped[list["Execution"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", passive_deletes=True
    )


class Node(Base):
    __tablename__ = "nodes"
    # Target for edges' composite foreign keys (see Edge).
    __table_args__ = (UniqueConstraint("workflow_id", "id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_type: Mapped[str] = mapped_column(String(100), nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    workflow: Mapped[Workflow] = relationship(back_populates="nodes")


class Edge(Base):
    """A dependency: target_node runs after source_node."""

    __tablename__ = "edges"
    __table_args__ = (
        # Composite FKs pin both endpoints to this edge's workflow, so the
        # database itself rejects edges that cross workflows (or tenants).
        ForeignKeyConstraint(
            ["workflow_id", "source_node_id"],
            ["nodes.workflow_id", "nodes.id"],
            ondelete="CASCADE",
            name="fk_edges_source_node_nodes",
        ),
        ForeignKeyConstraint(
            ["workflow_id", "target_node_id"],
            ["nodes.workflow_id", "nodes.id"],
            ondelete="CASCADE",
            name="fk_edges_target_node_nodes",
        ),
        UniqueConstraint("source_node_id", "target_node_id"),
        CheckConstraint("source_node_id <> target_node_id", name="no_self_loop"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    target_node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    workflow: Mapped[Workflow] = relationship(back_populates="edges")


class Execution(Base):
    __tablename__ = "executions"

    id: Mapped[uuid.UUID] = uuid_pk()
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus, name="execution_status"),
        nullable=False,
        default=ExecutionStatus.PENDING,
        server_default=ExecutionStatus.PENDING.value,
        index=True,
    )
    # Nullable: a PENDING execution has not started yet.
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Why a FAILED execution failed; cleared when an execution is (re)claimed.
    error_message: Mapped[str | None] = mapped_column(String)

    workflow: Mapped[Workflow] = relationship(back_populates="executions")
    node_runs: Mapped[list["NodeRun"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan", passive_deletes=True
    )


class NodeRun(Base):
    """Status of one node within one execution.

    Rows are created PENDING with the execution, then updated by the worker
    before each trace event, so the table is never behind the live stream.
    That makes it the source for WebSocket state hydration.
    """

    __tablename__ = "node_runs"
    __table_args__ = (UniqueConstraint("execution_id", "node_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("executions.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Same lifecycle as an execution; reuses the execution_status type.
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus, name="execution_status"),
        nullable=False,
        default=ExecutionStatus.PENDING,
        server_default=ExecutionStatus.PENDING.value,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(String)

    execution: Mapped[Execution] = relationship(back_populates="node_runs")
    node: Mapped[Node] = relationship()
