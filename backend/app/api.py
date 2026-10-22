"""Tenant-scoped REST API.

Every query is filtered by the caller's user_id: workflows directly, nodes and
executions by joining to their workflow. A resource owned by someone else is
reported as 404, not 403, so ids don't reveal what other tenants have.
"""

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.broker import publish_task
from app.dag import InvalidDAGError, build_dag_payload
from app.database import get_db
from app.models import Execution, ExecutionStatus, Node, Workflow
from app.pydantic_schemas import (
    ExecutionQueued,
    ExecutionRead,
    NodeCreate,
    NodeRead,
    NodeUpdate,
    WorkflowCreate,
    WorkflowRead,
    WorkflowUpdate,
)

router = APIRouter()

DB = Annotated[AsyncSession, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


def _not_found(kind: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{kind} not found")


def _apply_update(obj: Any, update: BaseModel, required: set[str]) -> None:
    """Copy fields the client actually sent; reject nulls for NOT NULL columns."""
    data = update.model_dump(exclude_unset=True)
    for field in required & data.keys():
        if data[field] is None:
            raise HTTPException(status_code=422, detail=f"{field} cannot be null")
    for field, value in data.items():
        setattr(obj, field, value)


async def get_owned_workflow(db: AsyncSession, user_id: uuid.UUID, workflow_id: uuid.UUID) -> Workflow:
    workflow = await db.scalar(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.user_id == user_id)
    )
    if workflow is None:
        raise _not_found("workflow")
    return workflow


async def get_owned_node(
    db: AsyncSession, user_id: uuid.UUID, workflow_id: uuid.UUID, node_id: uuid.UUID
) -> Node:
    node = await db.scalar(
        select(Node)
        .join(Workflow, Node.workflow_id == Workflow.id)
        .where(Node.id == node_id, Node.workflow_id == workflow_id, Workflow.user_id == user_id)
    )
    if node is None:
        raise _not_found("node")
    return node


# --- Workflows ---------------------------------------------------------------


@router.post("/workflows", response_model=WorkflowRead, status_code=status.HTTP_201_CREATED, tags=["workflows"])
async def create_workflow(body: WorkflowCreate, user_id: CurrentUser, db: DB) -> Workflow:
    workflow = Workflow(user_id=user_id, **body.model_dump())
    db.add(workflow)
    await db.commit()
    await db.refresh(workflow)
    return workflow


@router.get("/workflows", response_model=list[WorkflowRead], tags=["workflows"])
async def list_workflows(user_id: CurrentUser, db: DB, limit: Limit = 50, offset: Offset = 0) -> list[Workflow]:
    result = await db.scalars(
        select(Workflow)
        .where(Workflow.user_id == user_id)
        .order_by(Workflow.created_at.desc(), Workflow.id)
        .limit(limit)
        .offset(offset)
    )
    return list(result)


@router.get("/workflows/{workflow_id}", response_model=WorkflowRead, tags=["workflows"])
async def get_workflow(workflow_id: uuid.UUID, user_id: CurrentUser, db: DB) -> Workflow:
    return await get_owned_workflow(db, user_id, workflow_id)


@router.patch("/workflows/{workflow_id}", response_model=WorkflowRead, tags=["workflows"])
async def update_workflow(workflow_id: uuid.UUID, body: WorkflowUpdate, user_id: CurrentUser, db: DB) -> Workflow:
    workflow = await get_owned_workflow(db, user_id, workflow_id)
    _apply_update(workflow, body, required={"name"})
    await db.commit()
    await db.refresh(workflow)
    return workflow


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["workflows"])
async def delete_workflow(workflow_id: uuid.UUID, user_id: CurrentUser, db: DB) -> Response:
    workflow = await get_owned_workflow(db, user_id, workflow_id)
    # Nodes and executions go with it (ON DELETE CASCADE).
    await db.delete(workflow)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Nodes -------------------------------------------------------------------


@router.post(
    "/workflows/{workflow_id}/nodes",
    response_model=NodeRead,
    status_code=status.HTTP_201_CREATED,
    tags=["nodes"],
)
async def create_node(workflow_id: uuid.UUID, body: NodeCreate, user_id: CurrentUser, db: DB) -> Node:
    workflow = await get_owned_workflow(db, user_id, workflow_id)
    node = Node(workflow_id=workflow.id, **body.model_dump())
    db.add(node)
    await db.commit()
    await db.refresh(node)
    return node


@router.get("/workflows/{workflow_id}/nodes", response_model=list[NodeRead], tags=["nodes"])
async def list_nodes(
    workflow_id: uuid.UUID, user_id: CurrentUser, db: DB, limit: Limit = 200, offset: Offset = 0
) -> list[Node]:
    workflow = await get_owned_workflow(db, user_id, workflow_id)
    result = await db.scalars(
        select(Node).where(Node.workflow_id == workflow.id).order_by(Node.id).limit(limit).offset(offset)
    )
    return list(result)


@router.get("/workflows/{workflow_id}/nodes/{node_id}", response_model=NodeRead, tags=["nodes"])
async def get_node(workflow_id: uuid.UUID, node_id: uuid.UUID, user_id: CurrentUser, db: DB) -> Node:
    return await get_owned_node(db, user_id, workflow_id, node_id)


@router.patch("/workflows/{workflow_id}/nodes/{node_id}", response_model=NodeRead, tags=["nodes"])
async def update_node(
    workflow_id: uuid.UUID, node_id: uuid.UUID, body: NodeUpdate, user_id: CurrentUser, db: DB
) -> Node:
    node = await get_owned_node(db, user_id, workflow_id, node_id)
    _apply_update(node, body, required={"node_type", "config_json"})
    await db.commit()
    await db.refresh(node)
    return node


@router.delete(
    "/workflows/{workflow_id}/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["nodes"]
)
async def delete_node(workflow_id: uuid.UUID, node_id: uuid.UUID, user_id: CurrentUser, db: DB) -> Response:
    node = await get_owned_node(db, user_id, workflow_id, node_id)
    await db.delete(node)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Executions --------------------------------------------------------------


@router.post(
    "/workflows/{workflow_id}/execute",
    response_model=ExecutionQueued,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["executions"],
)
async def execute_workflow(workflow_id: uuid.UUID, user_id: CurrentUser, db: DB) -> ExecutionQueued:
    workflow = await get_owned_workflow(db, user_id, workflow_id)
    nodes = list(await db.scalars(select(Node).where(Node.workflow_id == workflow.id)))
    if not nodes:
        raise HTTPException(status_code=422, detail="workflow has no nodes")

    execution = Execution(id=uuid.uuid4(), workflow_id=workflow.id, status=ExecutionStatus.PENDING)
    # Validate the graph before writing anything, so a bad DAG leaves no record.
    try:
        payload = build_dag_payload(workflow, nodes, execution)
    except InvalidDAGError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Commit before publishing: the worker must be able to find the row as
    # soon as it receives the message.
    db.add(execution)
    await db.commit()

    try:
        await publish_task(payload)
    except Exception as exc:
        # The broker never accepted the task, so nothing will pick it up.
        execution.status = ExecutionStatus.FAILED
        execution.completed_at = datetime.now(timezone.utc)
        await db.commit()
        raise HTTPException(status_code=503, detail="could not queue execution") from exc

    return ExecutionQueued(execution_id=execution.id, status=execution.status)


@router.get("/workflows/{workflow_id}/executions", response_model=list[ExecutionRead], tags=["executions"])
async def list_executions(
    workflow_id: uuid.UUID, user_id: CurrentUser, db: DB, limit: Limit = 50, offset: Offset = 0
) -> list[Execution]:
    workflow = await get_owned_workflow(db, user_id, workflow_id)
    result = await db.scalars(
        select(Execution)
        .where(Execution.workflow_id == workflow.id)
        .order_by(Execution.started_at.desc().nulls_first(), Execution.id)
        .limit(limit)
        .offset(offset)
    )
    return list(result)


@router.get("/executions/{execution_id}", response_model=ExecutionRead, tags=["executions"])
async def get_execution(execution_id: uuid.UUID, user_id: CurrentUser, db: DB) -> Execution:
    execution = await db.scalar(
        select(Execution)
        .join(Workflow, Execution.workflow_id == Workflow.id)
        .where(Execution.id == execution_id, Workflow.user_id == user_id)
    )
    if execution is None:
        raise _not_found("execution")
    return execution
