"""Live execution traces over WebSocket.

Protocol for /ws/executions/{execution_id}:

1. Client connects, then sends {"type": "auth", "token": "<supabase jwt>"}
   within AUTH_TIMEOUT_SECONDS. The token travels in a message rather than
   the URL so it never lands in access logs.
2. Server replies with one `state.hydrated` event: the execution and every
   node run as stored in the database.
3. Server forwards each trace event from Redis (see app/worker.py), then
   closes with 1000 after execution.completed / execution.failed. If the
   execution had already finished at hydration, it closes right away.

Any auth or ownership failure closes with 1008 (policy violation).

Ordering: we subscribe to Redis *before* reading the database, so no event
published after the snapshot can be missed. Events published in between are
delivered after the snapshot too, so a client may see a transition the
snapshot already reflects. Apply events as idempotent state updates.
"""

import asyncio
import json
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic_core import to_json
from redis.asyncio.client import PubSub
from sqlalchemy import select

from app.auth import InvalidToken, user_id_from_token
from app.database import SessionLocal
from app.models import Execution, ExecutionStatus, Node, NodeRun, Workflow
from app.pydantic_schemas import ExecutionRead, NodeRunRead
from app.telemetry import get_redis, trace_channel

router = APIRouter()

AUTH_TIMEOUT_SECONDS = 10
# How long one Redis read waits before looping; also bounds how quickly
# redis-py gets to run its connection health checks.
REDIS_POLL_SECONDS = 1.0
TERMINAL_STATUSES = {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED}
TERMINAL_EVENTS = {"execution.completed", "execution.failed"}


class PolicyViolation(Exception):
    """Closes the socket with 1008; str() becomes the close reason."""


async def authenticate(websocket: WebSocket) -> uuid.UUID:
    try:
        message = await asyncio.wait_for(websocket.receive_json(), timeout=AUTH_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        raise PolicyViolation("authentication timed out") from None
    except (json.JSONDecodeError, KeyError):
        raise PolicyViolation("first message must be JSON") from None

    if not isinstance(message, dict) or message.get("type") != "auth" or not isinstance(message.get("token"), str):
        raise PolicyViolation('first message must be {"type": "auth", "token": "<jwt>"}')
    try:
        # Off the event loop: verification may fetch the JWKS over the network.
        return await asyncio.to_thread(user_id_from_token, message["token"])
    except InvalidToken:
        raise PolicyViolation("invalid or expired token") from None


async def load_snapshot(user_id: uuid.UUID, execution_id: uuid.UUID) -> dict[str, Any] | None:
    """The execution and its node runs, or None if the user doesn't own it.

    Uses a short-lived session so no pooler connection is held while the
    socket streams.
    """
    async with SessionLocal() as session:
        execution = await session.scalar(
            select(Execution)
            .join(Workflow, Execution.workflow_id == Workflow.id)
            .where(Execution.id == execution_id, Workflow.user_id == user_id)
        )
        if execution is None:
            return None
        rows = await session.execute(
            select(NodeRun, Node.node_type)
            .join(Node, NodeRun.node_id == Node.id)
            .where(NodeRun.execution_id == execution_id)
            .order_by(NodeRun.started_at.asc().nulls_last(), NodeRun.node_id)
        )
        nodes = [
            NodeRunRead(
                node_id=run.node_id,
                node_type=node_type,
                status=run.status,
                started_at=run.started_at,
                completed_at=run.completed_at,
                error_message=run.error_message,
            ).model_dump(mode="json")
            for run, node_type in rows
        ]
    return {
        "event": "state.hydrated",
        "execution_id": str(execution_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "execution": ExecutionRead.model_validate(execution).model_dump(mode="json"),
        "nodes": nodes,
    }


async def forward_traces(websocket: WebSocket, pubsub: PubSub) -> None:
    """Relay Redis messages verbatim until the execution finishes."""
    while True:
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=REDIS_POLL_SECONDS)
        if message is None:
            continue
        data: str = message["data"]
        await websocket.send_text(data)
        with suppress(ValueError, AttributeError):
            if json.loads(data).get("event") in TERMINAL_EVENTS:
                return


async def wait_for_disconnect(websocket: WebSocket) -> None:
    """Drain client messages (they're ignored) until the client goes away."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return


@router.websocket("/ws/executions/{execution_id}")
async def execution_trace(websocket: WebSocket, execution_id: uuid.UUID) -> None:
    # Accept first: only an accepted socket can send the 1008 close code.
    await websocket.accept()
    pubsub: PubSub | None = None
    try:
        user_id = await authenticate(websocket)

        pubsub = get_redis().pubsub()
        # Subscribe before the snapshot; nothing is sent to the client until
        # load_snapshot has confirmed ownership.
        await pubsub.subscribe(trace_channel(execution_id))
        snapshot = await load_snapshot(user_id, execution_id)
        if snapshot is None:
            # Same response whether it doesn't exist or belongs to someone
            # else, so ids reveal nothing about other tenants.
            raise PolicyViolation("execution not found")

        await websocket.send_text(to_json(snapshot).decode())
        if ExecutionStatus(snapshot["execution"]["status"]) in TERMINAL_STATUSES:
            await websocket.close(code=status.WS_1000_NORMAL_CLOSURE, reason="execution finished")
            return

        forwarder = asyncio.create_task(forward_traces(websocket, pubsub))
        watcher = asyncio.create_task(wait_for_disconnect(websocket))
        done, pending = await asyncio.wait({forwarder, watcher}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        if forwarder in done:
            forwarder.result()  # re-raise Redis/send errors
            await websocket.close(code=status.WS_1000_NORMAL_CLOSURE, reason="execution finished")
    except PolicyViolation as exc:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(exc))
    except WebSocketDisconnect:
        pass
    except Exception:
        # Redis or database failure mid-stream: tell the client to reconnect
        # (it will re-hydrate) instead of leaving the socket silent.
        with suppress(Exception):
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="trace stream unavailable")
        raise
    finally:
        if pubsub is not None:
            # Runs on every exit path, including client disconnects, so the
            # Redis subscription and its connection are always released.
            with suppress(Exception):
                await pubsub.unsubscribe()
            await pubsub.aclose()
