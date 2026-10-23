"""Workflow and node CRUD, and strict per-user isolation."""

import uuid

from sqlalchemy import func, select

from app.models import Node, Workflow


async def test_create_and_get_workflow(client, alice):
    r = await client.post("/workflows", json={"name": "Research", "description": "d"}, headers=alice.headers)
    assert r.status_code == 201
    created = r.json()
    assert created["name"] == "Research" and created["description"] == "d"
    uuid.UUID(created["id"])

    r = await client.get(f"/workflows/{created['id']}", headers=alice.headers)
    assert r.status_code == 200 and r.json() == created


async def test_workflow_is_owned_by_the_token_subject(client, alice, db_session):
    r = await client.post("/workflows", json={"name": "mine"}, headers=alice.headers)
    async with db_session() as s:
        row = await s.get(Workflow, uuid.UUID(r.json()["id"]))
    assert row.user_id == alice.id


async def test_list_workflows_newest_first_and_paginated(client, alice):
    for name in ("one", "two", "three"):
        await client.post("/workflows", json={"name": name}, headers=alice.headers)

    r = await client.get("/workflows", headers=alice.headers)
    assert [w["name"] for w in r.json()] == ["three", "two", "one"]

    r = await client.get("/workflows?limit=2&offset=1", headers=alice.headers)
    assert [w["name"] for w in r.json()] == ["two", "one"]

    assert (await client.get("/workflows?limit=0", headers=alice.headers)).status_code == 422
    assert (await client.get("/workflows?limit=201", headers=alice.headers)).status_code == 422


async def test_update_workflow(client, alice, build_workflow):
    workflow, _, _ = await build_workflow(alice)
    r = await client.patch(f"/workflows/{workflow['id']}", json={"name": "renamed"}, headers=alice.headers)
    assert r.status_code == 200
    assert r.json()["name"] == "renamed"
    assert r.json()["description"] == workflow["description"]  # untouched field kept


async def test_update_workflow_rejects_null_name(client, alice, build_workflow):
    workflow, _, _ = await build_workflow(alice)
    r = await client.patch(f"/workflows/{workflow['id']}", json={"name": None}, headers=alice.headers)
    assert r.status_code == 422


async def test_create_workflow_validates_name(client, alice):
    assert (await client.post("/workflows", json={"name": ""}, headers=alice.headers)).status_code == 422
    assert (await client.post("/workflows", json={}, headers=alice.headers)).status_code == 422


async def test_delete_workflow_cascades_to_nodes(client, alice, build_workflow, db_session):
    workflow, nodes, _ = await build_workflow(alice, nodes=["agent", "agent"], edges=[(0, 1)])
    r = await client.delete(f"/workflows/{workflow['id']}", headers=alice.headers)
    assert r.status_code == 204
    assert (await client.get(f"/workflows/{workflow['id']}", headers=alice.headers)).status_code == 404
    async with db_session() as s:
        assert await s.scalar(select(func.count()).select_from(Node)) == 0


async def test_malformed_workflow_id_is_422(client, alice):
    assert (await client.get("/workflows/not-a-uuid", headers=alice.headers)).status_code == 422


# --- Nodes -----------------------------------------------------------------------


async def test_node_crud(client, alice, build_workflow):
    workflow, _, _ = await build_workflow(alice)
    base = f"/workflows/{workflow['id']}/nodes"

    r = await client.post(base, json={"node_type": "agent", "config_json": {"model": "m"}}, headers=alice.headers)
    assert r.status_code == 201
    node = r.json()
    assert node["workflow_id"] == workflow["id"] and node["config_json"] == {"model": "m"}

    assert (await client.get(f"{base}/{node['id']}", headers=alice.headers)).json() == node
    assert [n["id"] for n in (await client.get(base, headers=alice.headers)).json()] == [node["id"]]

    r = await client.patch(f"{base}/{node['id']}", json={"config_json": {"model": "n"}}, headers=alice.headers)
    assert r.json()["config_json"] == {"model": "n"} and r.json()["node_type"] == "agent"

    assert (await client.delete(f"{base}/{node['id']}", headers=alice.headers)).status_code == 204
    assert (await client.get(f"{base}/{node['id']}", headers=alice.headers)).status_code == 404


async def test_node_config_defaults_to_empty_object(client, alice, build_workflow):
    workflow, _, _ = await build_workflow(alice)
    r = await client.post(f"/workflows/{workflow['id']}/nodes", json={"node_type": "agent"}, headers=alice.headers)
    assert r.json()["config_json"] == {}


async def test_node_update_rejects_nulls(client, alice, build_workflow):
    workflow, (node,), _ = await build_workflow(alice, nodes=["agent"])
    url = f"/workflows/{workflow['id']}/nodes/{node['id']}"
    assert (await client.patch(url, json={"config_json": None}, headers=alice.headers)).status_code == 422
    assert (await client.patch(url, json={"node_type": None}, headers=alice.headers)).status_code == 422


async def test_node_workflow_comes_from_the_path_not_the_body(client, alice, build_workflow):
    target, _, _ = await build_workflow(alice, name="target")
    other, _, _ = await build_workflow(alice, name="other")
    r = await client.post(
        f"/workflows/{target['id']}/nodes",
        json={"node_type": "agent", "workflow_id": other["id"]},
        headers=alice.headers,
    )
    assert r.status_code == 201
    assert r.json()["workflow_id"] == target["id"]


async def test_node_is_not_reachable_through_another_workflow_path(client, alice, build_workflow):
    w1, (node,), _ = await build_workflow(alice, nodes=["agent"])
    w2, _, _ = await build_workflow(alice)
    r = await client.get(f"/workflows/{w2['id']}/nodes/{node['id']}", headers=alice.headers)
    assert r.status_code == 404


# --- Tenant isolation -------------------------------------------------------------


async def test_other_users_see_nothing(client, alice, bob, build_workflow, db_session):
    workflow, (node,), _ = await build_workflow(alice, nodes=["agent"])
    w, n = workflow["id"], node["id"]

    assert (await client.get("/workflows", headers=bob.headers)).json() == []
    attempts = [
        ("GET", f"/workflows/{w}", None),
        ("PATCH", f"/workflows/{w}", {"name": "pwned"}),
        ("DELETE", f"/workflows/{w}", None),
        ("GET", f"/workflows/{w}/nodes", None),
        ("POST", f"/workflows/{w}/nodes", {"node_type": "agent"}),
        ("GET", f"/workflows/{w}/nodes/{n}", None),
        ("PATCH", f"/workflows/{w}/nodes/{n}", {"config_json": {"x": 1}}),
        ("DELETE", f"/workflows/{w}/nodes/{n}", None),
        ("GET", f"/workflows/{w}/edges", None),
        ("POST", f"/workflows/{w}/execute", None),
        ("GET", f"/workflows/{w}/executions", None),
    ]
    for method, url, body in attempts:
        r = await client.request(method, url, json=body, headers=bob.headers)
        # 404, not 403: ids must not reveal that another tenant's data exists.
        assert r.status_code == 404, f"{method} {url} -> {r.status_code}"

    # And nothing changed.
    async with db_session() as s:
        row = await s.get(Workflow, uuid.UUID(w))
        assert row.name == "test workflow"
        assert await s.scalar(select(func.count()).select_from(Node)) == 1
        assert (await s.get(Node, uuid.UUID(n))).config_json == {}
