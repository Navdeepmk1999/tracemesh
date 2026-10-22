"""Turn a workflow's nodes and edges into the DAG payload the worker executes."""

import uuid
from collections.abc import Iterable
from graphlib import CycleError, TopologicalSorter
from typing import Any

from app.models import Edge, Execution, Node, Workflow


class InvalidDAGError(ValueError):
    pass


def _dependency_graph(
    node_ids: Iterable[uuid.UUID], edges: Iterable[tuple[uuid.UUID, uuid.UUID]]
) -> dict[str, list[str]]:
    """Map each node id to the ids it depends on (its edges' sources)."""
    graph: dict[str, list[str]] = {str(n): [] for n in node_ids}
    for source, target in edges:
        graph.setdefault(str(target), []).append(str(source))
        graph.setdefault(str(source), [])
    return graph


def topological_order(
    node_ids: Iterable[uuid.UUID], edges: Iterable[tuple[uuid.UUID, uuid.UUID]]
) -> list[str]:
    """Node ids ordered so every node follows its dependencies.

    Raises InvalidDAGError naming the cycle if there is one.
    """
    graph = _dependency_graph(node_ids, edges)
    # Sort ids first so the order is deterministic for identical graphs.
    sorter = TopologicalSorter({k: sorted(graph[k]) for k in sorted(graph)})
    try:
        return list(sorter.static_order())
    except CycleError as exc:
        raise InvalidDAGError(f"workflow contains a cycle: {' -> '.join(exc.args[1])}") from None


def build_dag_payload(
    workflow: Workflow, nodes: list[Node], edges: list[Edge], execution: Execution
) -> dict[str, Any]:
    # Edges can only reference nodes of the same workflow (composite FKs), so
    # the only thing left to validate here is acyclicity.
    edge_pairs = [(e.source_node_id, e.target_node_id) for e in edges]
    order = topological_order((n.id for n in nodes), edge_pairs)
    graph = _dependency_graph((n.id for n in nodes), edge_pairs)

    return {
        "execution_id": str(execution.id),
        "workflow_id": str(workflow.id),
        "user_id": str(workflow.user_id),
        "nodes": [
            {
                "id": str(n.id),
                "node_type": n.node_type,
                "config": n.config_json,
                "depends_on": sorted(graph[str(n.id)]),
            }
            for n in nodes
        ],
        "edges": [
            {"id": str(e.id), "source": str(e.source_node_id), "target": str(e.target_node_id)}
            for e in edges
        ],
        # Node ids in an order where every node follows its dependencies.
        "order": order,
    }
