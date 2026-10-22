import type { Edge } from "@xyflow/react";

import { createNode, nodeTypes, type WorkflowNode, type WorkflowNodeType } from "@/components/nodes";
import type { ApiClient } from "@/lib/api/client";
import type { ApiEdge, ApiNode } from "@/lib/api/types";

/**
 * Mapping between React Flow state and the REST API.
 *
 * A node is stored as node_type = its React Flow type, and config_json =
 * its data plus its canvas position. The worker passes config_json through
 * untouched, so display fields living there is harmless.
 */

const KNOWN_TYPES = new Set<string>(Object.keys(nodeTypes));

/** What the server last confirmed, keyed by server id. */
export type GraphSnapshot = {
  nodes: Map<string, string>; // id -> stable JSON of config_json
  edges: Map<string, { source: string; target: string }>;
};

function stableStringify(value: unknown): string {
  return JSON.stringify(value, (_key, v) =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => a.localeCompare(b)))
      : v,
  );
}

function nodeConfig(node: WorkflowNode): Record<string, unknown> {
  // Rounded: sub-pixel drags shouldn't count as unsaved changes.
  return { ...node.data, position: { x: Math.round(node.position.x), y: Math.round(node.position.y) } };
}

function isPosition(value: unknown): value is { x: number; y: number } {
  const p = value as { x?: unknown; y?: unknown } | null;
  return typeof p?.x === "number" && typeof p?.y === "number";
}

function toFlowNode(apiNode: ApiNode, index: number): WorkflowNode {
  // Nodes created outside the canvas (e.g. straight through the API) may
  // have a type the canvas doesn't know, or no position: render them as
  // agents, laid out on a grid, rather than dropping them.
  const type = (KNOWN_TYPES.has(apiNode.node_type) ? apiNode.node_type : "agent") as WorkflowNodeType;
  const { position, ...rest } = apiNode.config_json;
  const fallback = { x: (index % 4) * 320, y: Math.floor(index / 4) * 200 };
  const node = createNode(type, isPosition(position) ? position : fallback, apiNode.id);
  const label = type === apiNode.node_type ? undefined : apiNode.node_type;
  return { ...node, data: { ...node.data, ...(label && { label }), ...rest } } as WorkflowNode;
}

export function snapshotOf(nodes: WorkflowNode[], edges: Edge[]): GraphSnapshot {
  return {
    nodes: new Map(nodes.map((n) => [n.id, stableStringify(nodeConfig(n))])),
    edges: new Map(edges.map((e) => [e.id, { source: e.source, target: e.target }])),
  };
}

export function fromApi(apiNodes: ApiNode[], apiEdges: ApiEdge[]) {
  const nodes = apiNodes.map(toFlowNode);
  const edges: Edge[] = apiEdges.map((e) => ({ id: e.id, source: e.source_node_id, target: e.target_node_id }));
  return { nodes, edges, snapshot: snapshotOf(nodes, edges) };
}

export function isDirty(saved: GraphSnapshot, nodes: WorkflowNode[], edges: Edge[]): boolean {
  if (nodes.length !== saved.nodes.size || edges.length !== saved.edges.size) return true;
  return (
    nodes.some((n) => saved.nodes.get(n.id) !== stableStringify(nodeConfig(n))) ||
    edges.some((e) => !saved.edges.has(e.id))
  );
}

export type SyncResult = {
  snapshot: GraphSnapshot;
  /** Local id -> server id for everything created in this sync. */
  idMap: Map<string, string>;
};

/** Thrown when a sync fails partway; `partial` records what did succeed. */
export class SyncError extends Error {
  constructor(
    readonly cause: unknown,
    readonly partial: SyncResult,
  ) {
    super(cause instanceof Error ? cause.message : "Save failed");
    this.name = "SyncError";
  }
}

/**
 * Push the difference between `saved` and the current graph to the API.
 *
 * Order matters for the server's edge validation: removals first (so an
 * edge being replaced can't trip the duplicate or cycle checks), then nodes,
 * then new edges, which need their endpoints' server ids. The snapshot is
 * advanced per successful call, so after a failure, saving again only
 * retries what is left.
 */
export async function syncGraph(
  api: ApiClient,
  workflowId: string,
  saved: GraphSnapshot,
  nodes: WorkflowNode[],
  edges: Edge[],
): Promise<SyncResult> {
  const next: GraphSnapshot = { nodes: new Map(saved.nodes), edges: new Map(saved.edges) };
  const idMap = new Map<string, string>();
  const result = { snapshot: next, idMap };

  async function phase<T>(items: T[], run: (item: T) => Promise<void>) {
    const outcomes = await Promise.allSettled(items.map(run));
    const failure = outcomes.find((o): o is PromiseRejectedResult => o.status === "rejected");
    if (failure) throw new SyncError(failure.reason, result);
  }

  const nodeIds = new Set(nodes.map((n) => n.id));
  const edgeIds = new Set(edges.map((e) => e.id));

  // 1. Removed edges.
  await phase(
    [...saved.edges.keys()].filter((id) => !edgeIds.has(id)),
    async (id) => {
      await api.deleteEdge(workflowId, id);
      next.edges.delete(id);
    },
  );

  // 2. Removed nodes. The server cascades their edges, so drop those too.
  await phase(
    [...saved.nodes.keys()].filter((id) => !nodeIds.has(id)),
    async (id) => {
      await api.deleteNode(workflowId, id);
      next.nodes.delete(id);
      for (const [edgeId, e] of next.edges) if (e.source === id || e.target === id) next.edges.delete(edgeId);
    },
  );

  // 3. New nodes (local ids; the server assigns the real ones).
  await phase(
    nodes.filter((n) => !saved.nodes.has(n.id)),
    async (node) => {
      const config = nodeConfig(node);
      const created = await api.createNode(workflowId, { node_type: node.type, config_json: config });
      idMap.set(node.id, created.id);
      next.nodes.set(created.id, stableStringify(config));
    },
  );

  // 4. Moved or edited nodes.
  await phase(
    nodes.filter((n) => saved.nodes.has(n.id) && saved.nodes.get(n.id) !== stableStringify(nodeConfig(n))),
    async (node) => {
      const config = nodeConfig(node);
      await api.updateNode(workflowId, node.id, { config_json: config });
      next.nodes.set(node.id, stableStringify(config));
    },
  );

  // 5. New edges, pointed at server node ids.
  const serverId = (id: string) => idMap.get(id) ?? id;
  await phase(
    edges.filter((e) => !saved.edges.has(e.id)),
    async (edge) => {
      const source = serverId(edge.source);
      const target = serverId(edge.target);
      const created = await api.createEdge(workflowId, source, target);
      idMap.set(edge.id, created.id);
      next.edges.set(created.id, { source, target });
    },
  );

  return result;
}

/** Rewrite local ids to server ids after a (possibly partial) sync. */
export function applyIdMap(idMap: Map<string, string>, nodes: WorkflowNode[], edges: Edge[]) {
  if (idMap.size === 0) return { nodes, edges };
  const map = (id: string) => idMap.get(id) ?? id;
  return {
    nodes: nodes.map((n) => (idMap.has(n.id) ? { ...n, id: map(n.id) } : n)),
    edges: edges.map((e) =>
      idMap.has(e.id) || idMap.has(e.source) || idMap.has(e.target)
        ? { ...e, id: map(e.id), source: map(e.source), target: map(e.target) }
        : e,
    ),
  };
}
