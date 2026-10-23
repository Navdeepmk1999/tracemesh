"""POST /workflows/{id}/execute and execution reads (RabbitMQ mocked)."""

import uuid
from unittest.mock import AsyncMock

from sqlalchemy import func, select

from app.models import Edge, Execution, ExecutionStatus, NodeRun


async def test_execute_queues_a_pending_execution(client, alice, build_workflow, published, db_session):
    workflow, nodes, _ = await build_workflow(alice, nodes=["trigger", "agent", "webhook"], edges=[(0, 1), (1, 2)])

    r = await client.post(f"/workflows/{workflow['id']}/execute", headers=alice.headers)

    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "PENDING"
    execution_id = uuid.UUID(body["execution_id"])

    async with db_session() as s:
        execution = await s.get(Execution, execution_id)
        assert execution.status is ExecutionStatus.PENDING
        assert str(execution.workflow_id) == workflow["id"]
        runs = (await s.scalars(select(NodeRun).where(NodeRun.execution_id == execution_id))).all()
    # One PENDING node run per node, created atomically with the execution.
    assert sorted(str(r.node_id) for r in runs) == sorted(n["id"] for n in nodes)
    assert {r.status for r in runs} == {ExecutionStatus.PENDING}


async def test_execute_publishes_the_dag_payload(client, alice, build_workflow, published):
    workflow, (t, a, w), _ = await build_workflow(
        alice, nodes=["trigger", ("agent", {"model": "m"}), "webhook"], edges=[(0, 1), (1, 2)]
    )
    r = await client.post(f"/workflows/{workflow['id']}/execute", headers=alice.headers)

    assert len(published) == 1
    payload = published[0]
    assert payload["execution_id"] == r.json()["execution_id"]
    assert payload["workflow_id"] == workflow["id"]
    assert payload["user_id"] == str(alice.id)
    assert payload["order"] == [t["id"], a["id"], w["id"]]
    agent = next(n for n in payload["nodes"] if n["id"] == a["id"])
    assert agent == {"id": a["id"], "node_type": "agent", "config": {"model": "m"}, "depends_on": [t["id"]]}


async def test_execute_empty_workflow_is_rejected(client, alice, build_workflow, published, db_session):
    workflow, _, _ = await build_workflow(alice)
    r = await client.post(f"/workflows/{workflow['id']}/execute", headers=alice.headers)
    assert r.status_code == 422
    assert published == []
    async with db_session() as s:
        assert await s.scalar(select(func.count()).select_from(Execution)) == 0


async def test_execute_cyclic_workflow_is_rejected_without_side_effects(
    client, alice, build_workflow, published, db_session
):
    # The edge API refuses cycles, so plant one directly (as a race between
    # two concurrent edge writes could): execute must still refuse it.
    workflow, (a, b), _ = await build_workflow(alice, nodes=["agent", "agent"], edges=[(0, 1)])
    async with db_session() as s, s.begin():
        s.add(Edge(workflow_id=uuid.UUID(workflow["id"]), source_node_id=uuid.UUID(b["id"]),
                   target_node_id=uuid.UUID(a["id"])))

    r = await client.post(f"/workflows/{workflow['id']}/execute", headers=alice.headers)

    assert r.status_code == 422
    assert "cycle" in r.json()["detail"]
    assert published == []
    async with db_session() as s:
        assert await s.scalar(select(func.count()).select_from(Execution)) == 0


async def test_broker_failure_marks_execution_failed(client, alice, build_workflow, monkeypatch, db_session):
    monkeypatch.setattr("app.api.publish_task", AsyncMock(side_effect=ConnectionError("broker down")))
    workflow, _, _ = await build_workflow(alice, nodes=["agent"])

    r = await client.post(f"/workflows/{workflow['id']}/execute", headers=alice.headers)

    assert r.status_code == 503
    async with db_session() as s:
        execution = await s.scalar(select(Execution))
    # Nothing will ever pick it up, so it must not sit in PENDING.
    assert execution.status is ExecutionStatus.FAILED
    assert execution.completed_at is not None
    assert "broker down" in execution.error_message


async def test_execute_someone_elses_workflow_is_404(client, alice, bob, build_workflow, published):
    workflow, _, _ = await build_workflow(alice, nodes=["agent"])
    r = await client.post(f"/workflows/{workflow['id']}/execute", headers=bob.headers)
    assert r.status_code == 404
    assert published == []


async def test_get_and_list_executions(client, alice, build_workflow):
    workflow, _, _ = await build_workflow(alice, nodes=["agent"])
    first = (await client.post(f"/workflows/{workflow['id']}/execute", headers=alice.headers)).json()
    second = (await client.post(f"/workflows/{workflow['id']}/execute", headers=alice.headers)).json()

    r = await client.get(f"/executions/{first['execution_id']}", headers=alice.headers)
    assert r.status_code == 200
    assert r.json() == {
        "id": first["execution_id"],
        "workflow_id": workflow["id"],
        "status": "PENDING",
        "started_at": None,
        "completed_at": None,
        "error_message": None,
    }

    r = await client.get(f"/workflows/{workflow['id']}/executions", headers=alice.headers)
    assert {e["id"] for e in r.json()} == {first["execution_id"], second["execution_id"]}


async def test_executions_are_private(client, alice, bob, build_workflow):
    workflow, _, _ = await build_workflow(alice, nodes=["agent"])
    queued = (await client.post(f"/workflows/{workflow['id']}/execute", headers=alice.headers)).json()
    assert (await client.get(f"/executions/{queued['execution_id']}", headers=bob.headers)).status_code == 404
    assert (await client.get(f"/executions/{uuid.uuid4()}", headers=alice.headers)).status_code == 404
