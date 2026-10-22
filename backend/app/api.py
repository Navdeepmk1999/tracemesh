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
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.broker import publish_task
from app.dag import InvalidDAGError, build_dag_payload, topological_order
from app.database import get_db
from app.models import Edge, Execution, ExecutionStatus, Node, NodeRun, Workflow
from app.pydantic_schemas import (
    EdgeCreate,
    EdgeRead,
    EdgeUpdate,
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


async def get_owned_edge(
    db: AsyncSession, user_id: uuid.UUID, workflow_id: uuid.UUID, edge_id: uuid.UUID
) -> Edge:
    edge = await db.scalar(
        select(Edge)
        .join(Workflow, Edge.workflow_id == Workflow.id)
        .where(Edge.id == edge_id, Edge.workflow_id == workflow_id, Workflow.user_id == user_id)
    )
    if edge is None:
        raise _not_found("edge")
    return edge


async def validate_edge(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    source: uuid.UUID,
    target: uuid.UUID,
    *,
    replacing: uuid.UUID | None = None,
) -> None:
    """Reject edges that are self-loops, leave the workflow, duplicate an
    existing edge, or would close a cycle. `replacing` is the id of an edge
    being updated, which is left out of the duplicate and cycle checks."""
    if source == target:
        raise HTTPException(status_code=422, detail="an edge cannot connect a node to itself")

    found = await db.scalar(
        select(func.count()).select_from(Node).where(Node.workflow_id == workflow_id, Node.id.in_([source, target]))
    )
    if found != 2:
        raise HTTPException(status_code=422, detail="source and target must be nodes of this workflow")

    existing = [
        (e.source_node_id, e.target_node_id)
        for e in await db.scalars(select(Edge).where(Edge.workflow_id == workflow_id))
        if e.id != replacing
    ]
    if (source, target) in existing:
        raise HTTPException(status_code=409, detail="edge already exists")
    try:
        topological_order([], [*existing, (source, target)])
    except InvalidDAGError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def commit_edge(db: AsyncSession, edge: Edge) -> Edge:
    try:
        await db.commit()
    except IntegrityError as exc:
        # A concurrent request inserted the same edge after validate_edge ran.
        await db.rollback()
        raise HTTPException(status_code=409, detail="edge already exists") from exc
    await db.refresh(edge)
    return edge


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
    # Its edges go with it (ON DELETE CASCADE).
    await db.delete(node)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Edges -------------------------------------------------------------------


@router.post(
    "/workflows/{workflow_id}/edges",
    response_model=EdgeRead,
    status_code=status.HTTP_201_CREATED,
    tags=["edges"],
)
async def create_edge(workflow_id: uuid.UUID, body: EdgeCreate, user_id: CurrentUser, db: DB) -> Edge:
    workflow = await get_owned_workflow(db, user_id, workflow_id)
    await validate_edge(db, workflow.id, body.source_node_id, body.target_node_id)
    edge = Edge(workflow_id=workflow.id, **body.model_dump())
    db.add(edge)
    return await commit_edge(db, edge)


@router.get("/workflows/{workflow_id}/edges", response_model=list[EdgeRead], tags=["edges"])
async def list_edges(
    workflow_id: uuid.UUID, user_id: CurrentUser, db: DB, limit: Limit = 200, offset: Offset = 0
) -> list[Edge]:
    workflow = await get_owned_workflow(db, user_id, workflow_id)
    result = await db.scalars(
        select(Edge).where(Edge.workflow_id == workflow.id).order_by(Edge.id).limit(limit).offset(offset)
    )
    return list(result)


@router.get("/workflows/{workflow_id}/edges/{edge_id}", response_model=EdgeRead, tags=["edges"])
async def get_edge(workflow_id: uuid.UUID, edge_id: uuid.UUID, user_id: CurrentUser, db: DB) -> Edge:
    return await get_owned_edge(db, user_id, workflow_id, edge_id)


@router.patch("/workflows/{workflow_id}/edges/{edge_id}", response_model=EdgeRead, tags=["edges"])
async def update_edge(
    workflow_id: uuid.UUID, edge_id: uuid.UUID, body: EdgeUpdate, user_id: CurrentUser, db: DB
) -> Edge:
    edge = await get_owned_edge(db, user_id, workflow_id, edge_id)
    source = body.source_node_id or edge.source_node_id
    target = body.target_node_id or edge.target_node_id
    await validate_edge(db, edge.workflow_id, source, target, replacing=edge.id)
    edge.source_node_id, edge.target_node_id = source, target
    return await commit_edge(db, edge)


@router.delete(
    "/workflows/{workflow_id}/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["edges"]
)
async def delete_edge(workflow_id: uuid.UUID, edge_id: uuid.UUID, user_id: CurrentUser, db: DB) -> Response:
    edge = await get_owned_edge(db, user_id, workflow_id, edge_id)
    await db.delete(edge)
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
    edges = list(await db.scalars(select(Edge).where(Edge.workflow_id == workflow.id)))

    execution = Execution(id=uuid.uuid4(), workflow_id=workflow.id, status=ExecutionStatus.PENDING)
    # Validate the graph before writing anything, so a bad DAG leaves no record.
    try:
        payload = build_dag_payload(workflow, nodes, edges, execution)
    except InvalidDAGError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Commit before publishing: the worker must be able to find the row as
    # soon as it receives the message.
    db.add(execution)
    # One PENDING row per node, committed atomically with the execution, so
    # hydration always has a complete picture of the run.
    db.add_all(NodeRun(execution_id=execution.id, node_id=n.id) for n in nodes)
    await db.commit()

    try:
        await publish_task(payload)
    except Exception as exc:
        # The broker never accepted the task, so nothing will pick it up.
        execution.status = ExecutionStatus.FAILED
        execution.completed_at = datetime.now(timezone.utc)
        execution.error_message = f"could not queue execution: {type(exc).__name__}: {exc}"
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
