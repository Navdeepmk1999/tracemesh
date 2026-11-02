import type { NodeTypes } from "@xyflow/react";

import { AgentNode } from "./agent-node";
import { DEFAULT_NODE_LABELS } from "./node-label-input";
import { TriggerNode } from "./trigger-node";
import { WebhookNode } from "./webhook-node";
import type { WorkflowNode, WorkflowNodeType } from "./types";

export { AgentNode, DEFAULT_NODE_LABELS, TriggerNode, WebhookNode };
export type * from "./types";

// Module-level and stable: React Flow re-mounts every node if this object
// changes identity between renders.
export const nodeTypes = {
  trigger: TriggerNode,
  agent: AgentNode,
  webhook: WebhookNode,
} satisfies NodeTypes;

/** Default data for a freshly dropped node of each type. */
export function createNode(
  type: WorkflowNodeType,
  position: { x: number; y: number },
  // UUIDs, so ids carry over to the backend in PR 7.
  id: string = crypto.randomUUID(),
): WorkflowNode {
  switch (type) {
    case "trigger":
      return { id, type, position, data: { label: DEFAULT_NODE_LABELS.trigger, event: "manual" } };
    case "agent":
      return {
        id,
        type,
        position,
        data: { label: DEFAULT_NODE_LABELS.agent, model: "claude-sonnet-5-5", instructions: "Describe what this agent should do." },
      };
    case "webhook":
      return { id, type, position, data: { label: DEFAULT_NODE_LABELS.webhook, method: "POST", url: "https://example.com/hook" } };
  }
}
