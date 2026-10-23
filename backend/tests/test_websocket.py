"""/ws/executions/{id}: auth handshake, state hydration and trace streaming."""

import asyncio
import json
import uuid
from datetime import datetime, timezone

import pytest
from httpx_ws import WebSocketDisconnect, WebSocketUpgradeError
from sqlalchemy import update

from app import websockets as ws_module
from app.models import Execution, ExecutionStatus, NodeRun
from app.telemetry import trace_channel

from .conftest import make_token, ws_connect

RECV_TIMEOUT = 2


@pytest.fixture
async def run(client, alice, build_workflow):
    """A queued 3-node execution owned by alice: (execution_id, [node ids])."""
    workflow, nodes, _ = await build_workflow(alice, nodes=["trigger", "agent", "webhook"], edges=[(0, 1), (1, 2)])
    r = await client.post(f"/workflows/{workflow['id']}/execute", headers=alice.headers)
    return r.json()["execution_id"], [n["id"] for n in nodes]


async def set_state(db_session, execution_id, status, node_statuses=(), error=None):
    now = datetime.now(timezone.utc)
    async with db_session() as s, s.begin():
        await s.execute(
            update(Execution)
            .where(Execution.id == uuid.UUID(execution_id))
            .values(status=status, started_at=now, error_message=error,
                    completed_at=now if status in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED) else None)
        )
        for node_id, node_status, node_error in node_statuses:
            await s.execute(
                update(NodeRun)
                .where(NodeRun.execution_id == uuid.UUID(execution_id), NodeRun.node_id == uuid.UUID(node_id))
                .values(status=node_status, error_message=node_error)
            )


async def auth(ws, token):
    await ws.send_text(json.dumps({"type": "auth", "token": token}))


async def recv(ws):
    return json.loads(await ws.receive_text(timeout=RECV_TIMEOUT))


async def expect_close(ws, code):
    with pytest.raises(WebSocketDisconnect) as excinfo:
        await ws.receive_text(timeout=RECV_TIMEOUT)
    assert excinfo.value.code == code, excinfo.value.reason
    return excinfo.value.reason


# --- Auth & isolation ------------------------------------------------------------


@pytest.mark.parametrize(
    ("first_message", "reason"),
    [
        pytest.param(json.dumps({"type": "auth", "token": "garbage"}), "invalid or expired token", id="bad-token"),
        pytest.param(json.dumps({"type": "auth", "token": make_token(uuid.uuid4(), expires_in=-120)}),
                     "invalid or expired token", id="expired-token"),
        pytest.param(json.dumps({"type": "hello"}), "first message must be", id="not-an-auth-message"),
        pytest.param(json.dumps({"type": "auth"}), "first message must be", id="missing-token"),
        pytest.param("plain text", "first message must be JSON", id="not-json"),
    ],
)
async def test_bad_handshake_closes_with_policy_violation(run, first_message, reason):
    execution_id, _ = run
    async with ws_connect(f"/ws/executions/{execution_id}") as ws:
        await ws.send_text(first_message)
        assert reason in await expect_close(ws, 1008)


async def test_auth_timeout_closes_with_policy_violation(run, monkeypatch):
    monkeypatch.setattr(ws_module, "AUTH_TIMEOUT_SECONDS", 0.2)
    execution_id, _ = run
    async with ws_connect(f"/ws/executions/{execution_id}") as ws:
        assert await expect_close(ws, 1008) == "authentication timed out"


async def test_another_users_execution_is_refused(run, bob):
    execution_id, _ = run
    async with ws_connect(f"/ws/executions/{execution_id}") as ws:
        await auth(ws, bob.token)
        # Same answer as for a nonexistent id: nothing about other tenants leaks.
        assert await expect_close(ws, 1008) == "execution not found"


async def test_unknown_execution_is_refused(alice):
    async with ws_connect(f"/ws/executions/{uuid.uuid4()}") as ws:
        await auth(ws, alice.token)
        assert await expect_close(ws, 1008) == "execution not found"


def leaf_exception(exc: BaseException) -> BaseException:
    while isinstance(exc, BaseExceptionGroup):
        exc = exc.exceptions[0]
    return exc


async def test_malformed_execution_id_is_rejected_before_upgrade():
    try:
        async with ws_connect("/ws/executions/not-a-uuid"):
            pytest.fail("connection was accepted")
    except BaseException as exc:  # noqa: BLE001 - anyio may wrap it in a group
        leaf = leaf_exception(exc)
    # In-process the rejection surfaces as a 1008 close; a real server
    # answers the upgrade with HTTP 403 instead.
    assert isinstance(leaf, WebSocketDisconnect | WebSocketUpgradeError), repr(leaf)
    if isinstance(leaf, WebSocketDisconnect):
        assert leaf.code == 1008


async def test_refused_connections_never_subscribe(run, bob, fake_redis):
    execution_id, _ = run
    async with ws_connect(f"/ws/executions/{execution_id}") as ws:
        await auth(ws, bob.token)
        await expect_close(ws, 1008)
    assert (await fake_redis.pubsub_numsub(trace_channel(execution_id)))[0][1] == 0


# --- Hydration -----------------------------------------------------------------------


async def test_hydrates_a_pending_execution(run, alice):
    execution_id, node_ids = run
    async with ws_connect(f"/ws/executions/{execution_id}") as ws:
        await auth(ws, alice.token)
        snapshot = await recv(ws)

    assert snapshot["event"] == "state.hydrated"
    assert snapshot["execution_id"] == execution_id
    assert snapshot["execution"]["id"] == execution_id
    assert snapshot["execution"]["status"] == "PENDING"
    assert sorted(n["node_id"] for n in snapshot["nodes"]) == sorted(node_ids)
    assert {n["status"] for n in snapshot["nodes"]} == {"PENDING"}
    assert {n["node_type"] for n in snapshot["nodes"]} == {"trigger", "agent", "webhook"}


async def test_hydrates_mid_run_progress_from_the_database(run, alice, db_session):
    execution_id, (t, a, w) = run
    await set_state(db_session, execution_id, ExecutionStatus.RUNNING, [
        (t, ExecutionStatus.COMPLETED, None),
        (a, ExecutionStatus.RUNNING, None),
    ])
    async with ws_connect(f"/ws/executions/{execution_id}") as ws:
        await auth(ws, alice.token)
        snapshot = await recv(ws)

    assert snapshot["execution"]["status"] == "RUNNING"
    statuses = {n["node_id"]: n["status"] for n in snapshot["nodes"]}
    assert statuses == {t: "COMPLETED", a: "RUNNING", w: "PENDING"}


async def test_finished_execution_hydrates_then_closes_normally(run, alice, db_session):
    execution_id, (t, a, w) = run
    await set_state(db_session, execution_id, ExecutionStatus.FAILED, [
        (t, ExecutionStatus.COMPLETED, None),
        (a, ExecutionStatus.FAILED, "RuntimeError: boom"),
    ], error="node failed")
    async with ws_connect(f"/ws/executions/{execution_id}") as ws:
        await auth(ws, alice.token)
        snapshot = await recv(ws)
        # Nothing more will ever be published, so the server hangs up.
        assert await expect_close(ws, 1000) == "execution finished"

    assert snapshot["execution"]["status"] == "FAILED"
    assert snapshot["execution"]["error_message"] == "node failed"
    failed = next(n for n in snapshot["nodes"] if n["node_id"] == a)
    assert failed == {**failed, "status": "FAILED", "error_message": "RuntimeError: boom"}


# --- Streaming --------------------------------------------------------------------------


async def test_streams_trace_events_after_hydration(run, alice, db_session, fake_redis):
    execution_id, (t, a, w) = run
    await set_state(db_session, execution_id, ExecutionStatus.RUNNING)
    channel = trace_channel(execution_id)
    events = [
        {"event": "node.started", "seq": 1, "node_id": t},
        {"event": "node.completed", "seq": 2, "node_id": t},
        {"event": "execution.completed", "seq": 3},
    ]

    async with ws_connect(f"/ws/executions/{execution_id}") as ws:
        await auth(ws, alice.token)
        assert (await recv(ws))["event"] == "state.hydrated"
        # The server subscribed before snapshotting, so it's listening now.
        assert (await fake_redis.pubsub_numsub(channel))[0][1] == 1
        for event in events:
            await fake_redis.publish(channel, json.dumps(event))
        received = [await recv(ws) for _ in events]
        # The terminal event ends the stream.
        assert await expect_close(ws, 1000) == "execution finished"

    assert received == events  # forwarded verbatim, in order


async def test_events_for_other_executions_are_not_forwarded(run, alice, db_session, fake_redis):
    execution_id, _ = run
    await set_state(db_session, execution_id, ExecutionStatus.RUNNING)
    async with ws_connect(f"/ws/executions/{execution_id}") as ws:
        await auth(ws, alice.token)
        await recv(ws)
        await fake_redis.publish(trace_channel(uuid.uuid4()), json.dumps({"event": "node.started"}))
        await fake_redis.publish(trace_channel(execution_id), json.dumps({"event": "execution.failed"}))
        assert (await recv(ws))["event"] == "execution.failed"


async def test_subscription_is_released_when_the_client_disconnects(run, alice, db_session, fake_redis):
    execution_id, _ = run
    await set_state(db_session, execution_id, ExecutionStatus.RUNNING)
    channel = trace_channel(execution_id)

    async with ws_connect(f"/ws/executions/{execution_id}") as ws:
        await auth(ws, alice.token)
        await recv(ws)
        assert (await fake_redis.pubsub_numsub(channel))[0][1] == 1
    # Client went away mid-run; the server must drop its subscription.
    for _ in range(50):
        if (await fake_redis.pubsub_numsub(channel))[0][1] == 0:
            break
        await asyncio.sleep(0.02)
    assert (await fake_redis.pubsub_numsub(channel))[0][1] == 0


async def test_redis_failure_mid_stream_closes_with_internal_error(run, alice, db_session, monkeypatch):
    execution_id, _ = run
    await set_state(db_session, execution_id, ExecutionStatus.RUNNING)

    async def broken_forward(websocket, pubsub):
        raise ConnectionError("redis went away")

    monkeypatch.setattr(ws_module, "forward_traces", broken_forward)
    async with ws_connect(f"/ws/executions/{execution_id}") as ws:
        await auth(ws, alice.token)
        await recv(ws)
        # 1011 tells the client to reconnect (and re-hydrate).
        await expect_close(ws, 1011)
