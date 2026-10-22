import type {
  ApiEdge,
  ApiExecution,
  ApiExecutionQueued,
  ApiNode,
  ApiWorkflow,
} from "./types";

// Defaults match the backend's dev server; override per environment.
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
export const WS_URL = (process.env.NEXT_PUBLIC_WS_URL ?? API_URL.replace(/^http/, "ws")).replace(/\/$/, "");

/** Returns a current Supabase access token (a JWT). */
export type TokenProvider = () => Promise<string>;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** FastAPI errors are {"detail": string} or, for validation, {"detail": [{msg}]}. */
function describeError(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
  return `Request failed (${status})`;
}

export function createApiClient(getToken: TokenProvider) {
  async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const token = await getToken();
    let response: Response;
    try {
      response = await fetch(`${API_URL}${path}`, {
        method,
        headers: {
          Authorization: `Bearer ${token}`,
          ...(body !== undefined && { "Content-Type": "application/json" }),
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
        cache: "no-store",
      });
    } catch {
      // fetch only rejects on network failure (or a CORS refusal).
      throw new ApiError(0, `Can't reach the API at ${API_URL}`);
    }
    if (response.status === 204) return undefined as T;
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new ApiError(response.status, describeError(response.status, data));
    return data as T;
  }

  const wf = (id: string) => `/workflows/${encodeURIComponent(id)}`;

  return {
    listWorkflows: () => request<ApiWorkflow[]>("GET", "/workflows"),
    createWorkflow: (name: string) => request<ApiWorkflow>("POST", "/workflows", { name }),
    getWorkflow: (id: string) => request<ApiWorkflow>("GET", wf(id)),

    listNodes: (workflowId: string) => request<ApiNode[]>("GET", `${wf(workflowId)}/nodes?limit=200`),
    createNode: (workflowId: string, node: Pick<ApiNode, "node_type" | "config_json">) =>
      request<ApiNode>("POST", `${wf(workflowId)}/nodes`, node),
    updateNode: (workflowId: string, nodeId: string, patch: Partial<Pick<ApiNode, "config_json">>) =>
      request<ApiNode>("PATCH", `${wf(workflowId)}/nodes/${nodeId}`, patch),
    deleteNode: (workflowId: string, nodeId: string) =>
      request<void>("DELETE", `${wf(workflowId)}/nodes/${nodeId}`),

    listEdges: (workflowId: string) => request<ApiEdge[]>("GET", `${wf(workflowId)}/edges?limit=200`),
    createEdge: (workflowId: string, source: string, target: string) =>
      request<ApiEdge>("POST", `${wf(workflowId)}/edges`, { source_node_id: source, target_node_id: target }),
    deleteEdge: (workflowId: string, edgeId: string) =>
      request<void>("DELETE", `${wf(workflowId)}/edges/${edgeId}`),

    execute: (workflowId: string) => request<ApiExecutionQueued>("POST", `${wf(workflowId)}/execute`),
    getExecution: (executionId: string) => request<ApiExecution>("GET", `/executions/${executionId}`),
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
