"""Turn a workflow's nodes into the DAG payload the worker executes.

Edges live in each node's config as `"depends_on": ["<node uuid>", ...]`.
"""

import uuid
from graphlib import CycleError, TopologicalSorter
from typing import Any

from app.models import Execution, Node, Workflow


class InvalidDAGError(ValueError):
    pass


def _dependencies(node: Node, node_ids: set[str]) -> list[str]:
    raw = (node.config_json or {}).get("depends_on", [])
    if not isinstance(raw, list):
        raise InvalidDAGError(f"node {node.id}: depends_on must be a list of node ids")
    deps: list[str] = []
    for dep in raw:
        try:
            dep_id = str(uuid.UUID(str(dep)))
        except ValueError:
            raise InvalidDAGError(f"node {node.id}: {dep!r} is not a node id") from None
        if dep_id not in node_ids:
            raise InvalidDAGError(f"node {node.id}: depends on {dep_id}, which is not in this workflow")
        deps.append(dep_id)
    return deps


def build_dag_payload(workflow: Workflow, nodes: list[Node], execution: Execution) -> dict[str, Any]:
    node_ids = {str(n.id) for n in nodes}
    graph = {str(n.id): _dependencies(n, node_ids) for n in nodes}
    try:
        # Sort ids first so the order is deterministic for identical graphs.
        order = list(TopologicalSorter({k: graph[k] for k in sorted(graph)}).static_order())
    except CycleError as exc:
        raise InvalidDAGError(f"workflow contains a cycle: {' -> '.join(exc.args[1])}") from None

    return {
        "execution_id": str(execution.id),
        "workflow_id": str(workflow.id),
        "user_id": str(workflow.user_id),
        "nodes": [
            {
                "id": str(n.id),
                "node_type": n.node_type,
                "config": n.config_json,
                "depends_on": graph[str(n.id)],
            }
            for n in nodes
        ],
        # Node ids in an order where every node follows its dependencies.
        "order": order,
    }
