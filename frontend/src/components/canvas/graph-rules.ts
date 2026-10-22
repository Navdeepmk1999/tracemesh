import type { Connection, Edge } from "@xyflow/react";

import type { WorkflowNode } from "@/components/nodes";

/**
 * Why a connection is not allowed, or null if it is. Mirrors the backend's
 * edge validation (app/api.py) so the canvas can't build a graph the API
 * would reject: no self-loops, no duplicates, no cycles.
 */
export function connectionError(
  connection: Connection | Edge,
  nodes: WorkflowNode[],
  edges: Edge[],
): string | null {
  const { source, target } = connection;
  if (!source || !target) return "Incomplete connection";
  if (source === target) return "A node can't connect to itself";

  const targetNode = nodes.find((n) => n.id === target);
  if (targetNode?.type === "trigger") return "Triggers start a workflow and can't have inputs";

  if (edges.some((e) => e.source === source && e.target === target)) return "These nodes are already connected";
  if (reaches(target, source, edges)) return "That connection would create a cycle";
  return null;
}

/** Is `to` reachable from `from` by following edges forward? */
function reaches(from: string, to: string, edges: Edge[]): boolean {
  const outgoing = new Map<string, string[]>();
  for (const e of edges) outgoing.set(e.source, [...(outgoing.get(e.source) ?? []), e.target]);

  const seen = new Set<string>();
  const stack = [from];
  while (stack.length) {
    const id = stack.pop()!;
    if (id === to) return true;
    if (seen.has(id)) continue;
    seen.add(id);
    stack.push(...(outgoing.get(id) ?? []));
  }
  return false;
}
