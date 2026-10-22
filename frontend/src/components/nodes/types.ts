import type { Edge, Node } from "@xyflow/react";

export type TriggerData = {
  label: string;
  event: "manual" | "schedule" | "http";
  schedule?: string;
};

export type AgentData = {
  label: string;
  model: string;
  instructions: string;
};

export type WebhookData = {
  label: string;
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  url: string;
};

// The node `type` strings double as the backend `node_type` values in PR 7.
export type TriggerFlowNode = Node<TriggerData, "trigger">;
export type AgentFlowNode = Node<AgentData, "agent">;
export type WebhookFlowNode = Node<WebhookData, "webhook">;

export type WorkflowNode = TriggerFlowNode | AgentFlowNode | WebhookFlowNode;
export type WorkflowNodeType = WorkflowNode["type"];
export type WorkflowEdge = Edge;
