import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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
    workflow_id: uuid.UUID
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


# --- Executions --------------------------------------------------------------


class ExecutionCreate(BaseModel):
    # Status starts as PENDING; the orchestrator owns all later transitions.
    workflow_id: uuid.UUID


class ExecutionRead(ORMModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    status: ExecutionStatus
    started_at: datetime | None
    completed_at: datetime | None
