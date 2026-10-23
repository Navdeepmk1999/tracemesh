"""DAG ordering and cycle rejection (app/dag.py). Pure unit tests, no I/O."""

import random
import uuid

import pytest

from app.dag import InvalidDAGError, build_dag_payload, topological_order
from app.models import Edge, Execution, Node, Workflow


def ids(n):
    return [uuid.uuid4() for _ in range(n)]


def assert_respects(order, edges):
    pos = {node_id: i for i, node_id in enumerate(order)}
    for source, target in edges:
        assert pos[str(source)] < pos[str(target)], f"{source} must run before {target}"


def test_linear_chain():
    a, b, c = ids(3)
    assert topological_order([c, b, a], [(a, b), (b, c)]) == [str(a), str(b), str(c)]


def test_diamond_respects_all_edges():
    a, b, c, d = ids(4)
    edges = [(a, b), (a, c), (b, d), (c, d)]
    order = topological_order([a, b, c, d], edges)
    assert len(order) == 4 and order[0] == str(a) and order[-1] == str(d)
    assert_respects(order, edges)


def test_disconnected_nodes_are_included():
    a, b, lone = ids(3)
    order = topological_order([a, b, lone], [(a, b)])
    assert set(order) == {str(a), str(b), str(lone)}
    assert_respects(order, [(a, b)])


def test_no_edges():
    nodes = ids(3)
    assert sorted(topological_order(nodes, [])) == sorted(map(str, nodes))


def test_order_is_deterministic_regardless_of_input_order():
    nodes = ids(8)
    edges = [(nodes[0], nodes[3]), (nodes[1], nodes[3]), (nodes[3], nodes[6]), (nodes[2], nodes[7])]
    expected = topological_order(nodes, edges)
    for seed in range(5):
        shuffled_nodes, shuffled_edges = nodes[:], edges[:]
        random.Random(seed).shuffle(shuffled_nodes)
        random.Random(seed).shuffle(shuffled_edges)
        assert topological_order(shuffled_nodes, shuffled_edges) == expected


@pytest.mark.parametrize(
    "edge_indexes",
    [
        pytest.param([(0, 1), (1, 0)], id="two-cycle"),
        pytest.param([(0, 1), (1, 2), (2, 0)], id="three-cycle"),
        pytest.param([(0, 1), (1, 2), (2, 3), (3, 1)], id="cycle-behind-an-entry"),
        pytest.param([(0, 0)], id="self-loop"),
    ],
)
def test_cycles_are_rejected(edge_indexes):
    nodes = ids(4)
    edges = [(nodes[s], nodes[t]) for s, t in edge_indexes]
    with pytest.raises(InvalidDAGError, match="cycle"):
        topological_order(nodes, edges)


def test_cycle_error_names_the_cycle():
    a, b, c = ids(3)
    with pytest.raises(InvalidDAGError) as excinfo:
        topological_order([a, b, c], [(a, b), (b, c), (c, a)])
    message = str(excinfo.value)
    assert all(str(n) in message for n in (a, b, c))


def test_edges_may_reference_nodes_not_passed_explicitly():
    # Used by the API's edge validation, which passes edges only.
    a, b = ids(2)
    assert topological_order([], [(a, b)]) == [str(a), str(b)]


def test_build_dag_payload():
    workflow = Workflow(id=uuid.uuid4(), user_id=uuid.uuid4(), name="w")
    a, b, c = (Node(id=i, workflow_id=workflow.id, node_type=t, config_json={"k": t})
               for i, t in zip(ids(3), ["trigger", "agent", "webhook"]))
    edges = [Edge(id=uuid.uuid4(), workflow_id=workflow.id, source_node_id=x.id, target_node_id=y.id)
             for x, y in [(a, b), (b, c)]]
    execution = Execution(id=uuid.uuid4(), workflow_id=workflow.id)

    payload = build_dag_payload(workflow, [c, a, b], edges, execution)

    assert payload["execution_id"] == str(execution.id)
    assert payload["workflow_id"] == str(workflow.id)
    assert payload["user_id"] == str(workflow.user_id)
    assert payload["order"] == [str(a.id), str(b.id), str(c.id)]
    by_id = {n["id"]: n for n in payload["nodes"]}
    assert by_id[str(a.id)] == {"id": str(a.id), "node_type": "trigger", "config": {"k": "trigger"}, "depends_on": []}
    assert by_id[str(c.id)]["depends_on"] == [str(b.id)]
    assert {(e["source"], e["target"]) for e in payload["edges"]} == {(str(a.id), str(b.id)), (str(b.id), str(c.id))}


def test_build_dag_payload_rejects_cycles():
    workflow = Workflow(id=uuid.uuid4(), user_id=uuid.uuid4(), name="w")
    a, b = (Node(id=i, workflow_id=workflow.id, node_type="agent", config_json={}) for i in ids(2))
    edges = [Edge(id=uuid.uuid4(), workflow_id=workflow.id, source_node_id=x.id, target_node_id=y.id)
             for x, y in [(a, b), (b, a)]]
    with pytest.raises(InvalidDAGError):
        build_dag_payload(workflow, [a, b], edges, Execution(id=uuid.uuid4(), workflow_id=workflow.id))
