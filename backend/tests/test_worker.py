"""Worker message handling (app/worker.py) against the real DB and fake Redis.

No RabbitMQ: handle_message is driven with a fake incoming message that
records how it was settled (ack / nack / reject).
"""

import json
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update

from app import worker
from app.models import Execution, ExecutionStatus, NodeRun


class FakeMessage:
    def __init__(self, payload, *, redelivered=False, raw: bytes | None = None):
        self.body = raw if raw is not None else json.dumps(payload).encode()
        self.message_id = uuid.uuid4().hex
        self.redelivered = redelivered
        self.ack = AsyncMock()
        self.nack = AsyncMock()
        self.reject = AsyncMock()

    @property
    def settled(self):
        calls = {name: getattr(self, name) for name in ("ack", "nack", "reject")}
        done = [(name, mock.call_args) for name, mock in calls.items() if mock.await_count]
        assert len(done) == 1, f"message settled {len(done)} times: {done}"
        return done[0]


@pytest.fixture(autouse=True)
def instant_nodes(monkeypatch):
    monkeypatch.setattr(worker, "SIMULATED_SECONDS_PER_NODE", 0)


@pytest.fixture
async def queued(client, alice, build_workflow, published):
    """Queue an execution through the API; returns (payload, node ids)."""

    async def queue(nodes=("trigger", "agent", "webhook"), edges=((0, 1), (1, 2))):
        workflow, created, _ = await build_workflow(alice, nodes=list(nodes), edges=list(edges))
        await client.post(f"/workflows/{workflow['id']}/execute", headers=alice.headers)
        return published[-1], [n["id"] for n in created]

    return queue


@pytest.fixture
async def traces(fake_redis):
    """Returns a function that drains trace events published since its last call."""
    pubsub = fake_redis.pubsub()
    await pubsub.psubscribe("trace:*")

    async def drain():
        events, idle = [], 0
        # get_message returns None both when idle and for control messages
        # (e.g. the psubscribe confirmation), so stop only after a quiet spell.
        while idle < 5:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.02)
            if message is None:
                idle += 1
                continue
            idle = 0
            events.append(json.loads(message["data"]))
        return events

    yield drain
    await pubsub.aclose()


async def load(db_session, execution_id):
    async with db_session() as s:
        execution = await s.get(Execution, uuid.UUID(execution_id))
        runs = {str(r.node_id): r for r in await s.scalars(
            select(NodeRun).where(NodeRun.execution_id == uuid.UUID(execution_id)))}
    return execution, runs


async def test_successful_run(queued, traces, db_session):
    payload, (t, a, w) = await queued()
    message = FakeMessage(payload)

    await worker.handle_message(message)

    assert message.settled[0] == "ack"
    execution, runs = await load(db_session, payload["execution_id"])
    assert execution.status is ExecutionStatus.COMPLETED
    assert execution.started_at and execution.completed_at and execution.error_message is None
    assert {r.status for r in runs.values()} == {ExecutionStatus.COMPLETED}

    events = await traces()
    assert [(e["event"], e.get("node_id")) for e in events] == [
        ("execution.started", None),
        ("node.started", t), ("node.completed", t),
        ("node.started", a), ("node.completed", a),
        ("node.started", w), ("node.completed", w),
        ("execution.completed", None),
    ]
    assert [e["seq"] for e in events] == list(range(1, 9))
    assert all(e["execution_id"] == payload["execution_id"] for e in events)
    assert events[0]["order"] == [t, a, w]


async def test_finished_executions_are_acked_and_skipped(queued, traces, db_session):
    payload, _ = await queued()
    await worker.handle_message(FakeMessage(payload))
    await traces()  # discard the first run's events
    first, _ = await load(db_session, payload["execution_id"])

    duplicate = FakeMessage(payload, redelivered=True)
    await worker.handle_message(duplicate)

    assert duplicate.settled[0] == "ack"
    again, _ = await load(db_session, payload["execution_id"])
    assert (again.status, again.completed_at) == (ExecutionStatus.COMPLETED, first.completed_at)
    assert await traces() == []  # no re-run, no new events


async def test_failed_executions_are_not_retried(queued, db_session):
    payload, _ = await queued()
    async with db_session() as s, s.begin():
        await s.execute(update(Execution).where(Execution.id == uuid.UUID(payload["execution_id"]))
                        .values(status=ExecutionStatus.FAILED, error_message="earlier failure"))
    message = FakeMessage(payload)
    await worker.handle_message(message)
    assert message.settled[0] == "ack"
    execution, _ = await load(db_session, payload["execution_id"])
    assert (execution.status, execution.error_message) == (ExecutionStatus.FAILED, "earlier failure")


async def test_node_failure_fails_the_execution(client, alice, build_workflow, published, traces, db_session):
    workflow, (t, a, w), _ = await build_workflow(
        alice, nodes=["trigger", ("agent", {"simulate_failure": "model overloaded"}), "webhook"],
        edges=[(0, 1), (1, 2)],
    )
    await client.post(f"/workflows/{workflow['id']}/execute", headers=alice.headers)
    payload = published[-1]
    message = FakeMessage(payload)

    await worker.handle_message(message)

    # A failed run is a final answer: ack, don't redeliver.
    assert message.settled[0] == "ack"
    execution, runs = await load(db_session, payload["execution_id"])
    assert execution.status is ExecutionStatus.FAILED
    assert "RuntimeError: model overloaded" in execution.error_message
    assert a["id"] in execution.error_message
    assert runs[t["id"]].status is ExecutionStatus.COMPLETED
    assert runs[a["id"]].status is ExecutionStatus.FAILED
    assert runs[a["id"]].error_message == execution.error_message
    assert runs[w["id"]].status is ExecutionStatus.PENDING  # never started

    events = await traces()
    assert [e["event"] for e in events][-2:] == ["node.failed", "execution.failed"]
    assert not any(e.get("node_id") == w["id"] for e in events)


async def test_redelivered_running_execution_is_rerun_from_scratch(queued, db_session):
    payload, (t, a, w) = await queued()
    eid = uuid.UUID(payload["execution_id"])
    # Simulate a worker that crashed mid-run: execution RUNNING, partial progress.
    async with db_session() as s, s.begin():
        await s.execute(update(Execution).where(Execution.id == eid).values(status=ExecutionStatus.RUNNING))
        await s.execute(update(NodeRun).where(NodeRun.execution_id == eid, NodeRun.node_id == uuid.UUID(t))
                        .values(status=ExecutionStatus.COMPLETED))

    claimed = await worker.claim_execution(eid)
    assert claimed
    _, runs = await load(db_session, payload["execution_id"])
    assert {r.status for r in runs.values()} == {ExecutionStatus.PENDING}  # stale progress cleared

    message = FakeMessage(payload, redelivered=True)
    await worker.handle_message(message)
    assert message.settled[0] == "ack"
    execution, runs = await load(db_session, payload["execution_id"])
    assert execution.status is ExecutionStatus.COMPLETED


async def test_unknown_execution_is_acked(queued, db_session):
    payload, _ = await queued()
    payload = {**payload, "execution_id": str(uuid.uuid4())}  # e.g. workflow deleted meanwhile
    message = FakeMessage(payload)
    await worker.handle_message(message)
    assert message.settled[0] == "ack"


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(b"not json{", id="not-json"),
        pytest.param(json.dumps({"nodes": [], "order": []}).encode(), id="missing-execution-id"),
        pytest.param(json.dumps({"execution_id": "nope", "nodes": [], "order": []}).encode(), id="bad-uuid"),
        pytest.param(json.dumps({"execution_id": str(uuid.uuid4()), "nodes": [{"id": "a"}], "order": ["b"]}).encode(),
                     id="order-mismatch"),
    ],
)
async def test_malformed_messages_are_dead_lettered(raw):
    message = FakeMessage(None, raw=raw)
    await worker.handle_message(message)
    name, call = message.settled
    assert name == "reject" and call.kwargs == {"requeue": False}


async def test_database_outage_requeues_once(queued, monkeypatch):
    payload, _ = await queued()
    monkeypatch.setattr(worker, "claim_execution", AsyncMock(side_effect=ConnectionError("db down")))

    first = FakeMessage(payload)
    await worker.handle_message(first)
    assert first.settled == ("nack", first.nack.call_args)
    assert first.nack.call_args.kwargs == {"requeue": True}

    retry = FakeMessage(payload, redelivered=True)
    await worker.handle_message(retry)
    assert retry.nack.call_args.kwargs == {"requeue": False}  # second failure -> DLQ


async def test_telemetry_outage_does_not_fail_the_run(queued, monkeypatch, db_session):
    payload, _ = await queued()
    monkeypatch.setattr(worker, "publish_trace", AsyncMock(side_effect=ConnectionError("redis down")))
    message = FakeMessage(payload)

    await worker.handle_message(message)

    assert message.settled[0] == "ack"
    execution, _ = await load(db_session, payload["execution_id"])
    assert execution.status is ExecutionStatus.COMPLETED

