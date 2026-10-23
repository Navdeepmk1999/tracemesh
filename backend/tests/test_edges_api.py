"""Edge CRUD and the graph rules enforced on write (app/api.py validate_edge)."""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import Edge


def edge_body(source, target):
    return {"source_node_id": source["id"], "target_node_id": target["id"]}


async def test_edge_crud(client, alice, build_workflow):
    workflow, (a, b, c), _ = await build_workflow(alice, nodes=["trigger", "agent", "webhook"])
    base = f"/workflows/{workflow['id']}/edges"

    r = await client.post(base, json=edge_body(a, b), headers=alice.headers)
    assert r.status_code == 201
    edge = r.json()
    assert (edge["source_node_id"], edge["target_node_id"]) == (a["id"], b["id"])

    assert (await client.get(f"{base}/{edge['id']}", headers=alice.headers)).json() == edge
    assert [e["id"] for e in (await client.get(base, headers=alice.headers)).json()] == [edge["id"]]

    r = await client.patch(f"{base}/{edge['id']}", json={"target_node_id": c["id"]}, headers=alice.headers)
    assert r.status_code == 200 and r.json()["target_node_id"] == c["id"]

    assert (await client.delete(f"{base}/{edge['id']}", headers=alice.headers)).status_code == 204
    assert (await client.get(base, headers=alice.headers)).json() == []


async def test_self_loop_rejected(client, alice, build_workflow):
    workflow, (a,), _ = await build_workflow(alice, nodes=["agent"])
    r = await client.post(f"/workflows/{workflow['id']}/edges", json=edge_body(a, a), headers=alice.headers)
    assert r.status_code == 422


async def test_duplicate_edge_conflicts(client, alice, build_workflow):
    workflow, (a, b), _ = await build_workflow(alice, nodes=["agent", "agent"], edges=[(0, 1)])
    r = await client.post(f"/workflows/{workflow['id']}/edges", json=edge_body(a, b), headers=alice.headers)
    assert r.status_code == 409


@pytest.mark.parametrize(
    ("edges", "closing"),
    [
        pytest.param([(0, 1)], (1, 0), id="two-node"),
        pytest.param([(0, 1), (1, 2)], (2, 0), id="three-node"),
        pytest.param([(0, 1), (1, 2), (2, 3), (0, 3)], (3, 1), id="through-diamond"),
    ],
)
async def test_edge_closing_a_cycle_is_rejected(client, alice, build_workflow, db_session, edges, closing):
    workflow, nodes, _ = await build_workflow(alice, nodes=["agent"] * 4, edges=edges)
    s, t = closing
    r = await client.post(f"/workflows/{workflow['id']}/edges", json=edge_body(nodes[s], nodes[t]), headers=alice.headers)
    assert r.status_code == 422
    assert "cycle" in r.json()["detail"]
    async with db_session() as session:
        assert await session.scalar(select(func.count()).select_from(Edge)) == len(edges)


async def test_patch_into_a_cycle_is_rejected(client, alice, build_workflow):
    # a->b->c plus a shortcut a->c; re-pointing the shortcut to c->a closes
    # a->b->c->a, even though the edge being edited is excluded from the check.
    workflow, (a, b, c), _ = await build_workflow(alice, nodes=["agent"] * 3, edges=[(0, 1), (1, 2)])
    r = await client.post(f"/workflows/{workflow['id']}/edges", json=edge_body(a, c), headers=alice.headers)
    ac = r.json()
    r = await client.patch(
        f"/workflows/{workflow['id']}/edges/{ac['id']}",
        json={"source_node_id": c["id"], "target_node_id": a["id"]},
        headers=alice.headers,
    )
    assert r.status_code == 422


async def test_patch_that_removes_the_old_edge_is_not_a_cycle(client, alice, build_workflow):
    # Replacing a->b with b->a is fine: the edge being replaced is excluded.
    workflow, (a, b), (ab,) = await build_workflow(alice, nodes=["agent", "agent"], edges=[(0, 1)])
    r = await client.patch(
        f"/workflows/{workflow['id']}/edges/{ab['id']}",
        json={"source_node_id": b["id"], "target_node_id": a["id"]},
        headers=alice.headers,
    )
    assert r.status_code == 200


async def test_edge_to_a_node_in_another_workflow_is_rejected(client, alice, build_workflow):
    w1, (a,), _ = await build_workflow(alice, nodes=["agent"])
    _, (foreign,), _ = await build_workflow(alice, nodes=["agent"])
    r = await client.post(f"/workflows/{w1['id']}/edges", json=edge_body(a, foreign), headers=alice.headers)
    assert r.status_code == 422


async def test_database_rejects_cross_workflow_edges(alice, build_workflow, db_session):
    # Defense in depth: even bypassing the API, composite FKs pin both
    # endpoints of an edge to the edge's own workflow.
    w1, (a,), _ = await build_workflow(alice, nodes=["agent"])
    _, (foreign,), _ = await build_workflow(alice, nodes=["agent"])
    with pytest.raises(IntegrityError):
        async with db_session() as s, s.begin():
            s.add(Edge(workflow_id=uuid.UUID(w1["id"]), source_node_id=uuid.UUID(a["id"]),
                       target_node_id=uuid.UUID(foreign["id"])))


async def test_deleting_a_node_deletes_its_edges(client, alice, build_workflow):
    workflow, (a, b, c), _ = await build_workflow(alice, nodes=["agent"] * 3, edges=[(0, 1), (1, 2)])
    await client.delete(f"/workflows/{workflow['id']}/nodes/{b['id']}", headers=alice.headers)
    assert (await client.get(f"/workflows/{workflow['id']}/edges", headers=alice.headers)).json() == []


async def test_other_users_cannot_touch_edges(client, alice, bob, build_workflow):
    workflow, (a, b, c), (ab,) = await build_workflow(alice, nodes=["agent"] * 3, edges=[(0, 1)])
    base = f"/workflows/{workflow['id']}/edges"
    for method, url, body in [
        ("GET", base, None),
        ("POST", base, edge_body(b, c)),
        ("GET", f"{base}/{ab['id']}", None),
        ("PATCH", f"{base}/{ab['id']}", {"target_node_id": c["id"]}),
        ("DELETE", f"{base}/{ab['id']}", None),
    ]:
        r = await client.request(method, url, json=body, headers=bob.headers)
        assert r.status_code == 404, f"{method} {url}"
    assert len((await client.get(base, headers=alice.headers)).json()) == 1
