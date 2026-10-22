// Wire types for the FastAPI backend (backend/app/pydantic_schemas.py).

export type ExecutionStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";

export type ApiWorkflow = {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
};

export type ApiNode = {
  id: string;
  workflow_id: string;
  node_type: string;
  config_json: Record<string, unknown>;
};

export type ApiEdge = {
  id: string;
  workflow_id: string;
  source_node_id: string;
  target_node_id: string;
};

export type ApiExecution = {
  id: string;
  workflow_id: string;
  status: ExecutionStatus;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
};

export type ApiExecutionQueued = { execution_id: string; status: ExecutionStatus };

export type ApiNodeRun = {
  node_id: string;
  node_type: string;
  status: ExecutionStatus;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
};

// --- WebSocket trace events (backend/app/worker.py, app/websockets.py) -----

type TraceBase = { execution_id: string; timestamp: string };
type NodeEventBase = TraceBase & { seq: number; node_id: string; node_type: string; index: number; total: number };

export type TraceEvent =
  | (TraceBase & { event: "state.hydrated"; execution: ApiExecution; nodes: ApiNodeRun[] })
  | (TraceBase & { event: "execution.started"; seq: number; order: string[]; node_count: number; redelivered: boolean })
  | (NodeEventBase & { event: "node.started" })
  | (NodeEventBase & { event: "node.completed"; duration_ms: number })
  | (NodeEventBase & { event: "node.failed"; duration_ms: number; error: string })
  | (TraceBase & { event: "execution.completed"; seq: number; duration_ms: number })
  | (TraceBase & { event: "execution.failed"; seq: number; duration_ms: number; error: string });
