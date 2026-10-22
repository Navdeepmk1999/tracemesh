import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import ExecutionStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Workflows ---------------------------------------------------------------


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class WorkflowRead(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime


# --- Nodes -------------------------------------------------------------------


class NodeCreate(BaseModel):
    # workflow_id comes from the URL path, never the body, so a client can't
    # attach a node to a workflow it doesn't own.
    node_type: str = Field(min_length=1, max_length=100)
    config_json: dict[str, Any] = Field(default_factory=dict)


class NodeUpdate(BaseModel):
    node_type: str | None = Field(default=None, min_length=1, max_length=100)
    config_json: dict[str, Any] | None = None


class NodeRead(ORMModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    node_type: str
    config_json: dict[str, Any]


# --- Edges -------------------------------------------------------------------


class EdgeCreate(BaseModel):
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID

    @model_validator(mode="after")
    def _no_self_loop(self) -> "EdgeCreate":
        if self.source_node_id == self.target_node_id:
            raise ValueError("an edge cannot connect a node to itself")
        return self


class EdgeUpdate(BaseModel):
    source_node_id: uuid.UUID | None = None
    target_node_id: uuid.UUID | None = None


class EdgeRead(ORMModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID


# --- Executions --------------------------------------------------------------


class NodeRunRead(ORMModel):
    node_id: uuid.UUID
    node_type: str
    status: ExecutionStatus
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None


class ExecutionQueued(BaseModel):
    # Status starts as PENDING; the worker owns all later transitions.
    execution_id: uuid.UUID
    status: ExecutionStatus


class ExecutionRead(ORMModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    status: ExecutionStatus
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
