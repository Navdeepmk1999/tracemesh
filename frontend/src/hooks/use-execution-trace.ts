"use client";

import { useEffect, useReducer } from "react";

import { WS_URL, type TokenProvider } from "@/lib/api/client";
import type { ExecutionStatus, TraceEvent } from "@/lib/api/types";

export type NodeRunState = { status: ExecutionStatus; error?: string | null };

export type TraceState = {
  /** connecting: socket opening/authenticating; live: streaming; closed:
   * the server ended the stream normally; error: gave up. */
  connection: "idle" | "connecting" | "live" | "closed" | "error";
  status: ExecutionStatus | null;
  nodes: Record<string, NodeRunState>;
  error: string | null;
};

const INITIAL: TraceState = { connection: "idle", status: null, nodes: {}, error: null };
const MAX_RECONNECTS = 5;

// Higher = further along. Events can arrive that the hydrated snapshot
// already reflects (the backend subscribes before it snapshots), so a node
// never moves backwards except on an explicit restart (execution.started).
const RANK: Record<ExecutionStatus, number> = { PENDING: 0, RUNNING: 1, COMPLETED: 2, FAILED: 2 };

function setNode(state: TraceState, id: string, next: NodeRunState): TraceState {
  const current = state.nodes[id];
  if (current && RANK[current.status] > RANK[next.status]) return state;
  return { ...state, nodes: { ...state.nodes, [id]: next } };
}

type Action =
  | { type: "reset" }
  | { type: "connecting" }
  | { type: "event"; event: TraceEvent }
  | { type: "closed" }
  | { type: "error"; error: string };

function reducer(state: TraceState, action: Action): TraceState {
  switch (action.type) {
    case "reset":
      return { ...INITIAL, connection: "connecting" };
    case "connecting":
      return { ...state, connection: "connecting" };
    case "closed":
      return { ...state, connection: "closed" };
    case "error":
      return { ...state, connection: "error", error: action.error };
    case "event": {
      const e = action.event;
      const live = { ...state, connection: "live" as const };
      switch (e.event) {
        case "state.hydrated":
          // Authoritative: replaces whatever we had (e.g. after a reconnect).
          return {
            ...live,
            status: e.execution.status,
            error: e.execution.error_message,
            nodes: Object.fromEntries(e.nodes.map((n) => [n.node_id, { status: n.status, error: n.error_message }])),
          };
        case "execution.started":
          // A (re)start: every node goes back to PENDING.
          return {
            ...live,
            status: "RUNNING",
            error: null,
            nodes: Object.fromEntries(e.order.map((id) => [id, { status: "PENDING" as const }])),
          };
        case "node.started":
          return setNode(live, e.node_id, { status: "RUNNING" });
        case "node.completed":
          return setNode(live, e.node_id, { status: "COMPLETED" });
        case "node.failed":
          return setNode(live, e.node_id, { status: "FAILED", error: e.error });
        case "execution.completed":
          return { ...live, status: "COMPLETED" };
        case "execution.failed":
          return { ...live, status: "FAILED", error: e.error };
        default:
          return state;
      }
    }
  }
}

/**
 * Stream an execution's trace from /ws/executions/{id}.
 *
 * Protocol (backend/app/websockets.py): send {"type":"auth","token"} first;
 * receive state.hydrated, then live events; the server closes with 1000 when
 * the run ends, 1008 on auth/ownership failure, 1011 if its stream breaks.
 * On 1011 or a dropped connection this reconnects with backoff, and the new
 * state.hydrated catches up on anything missed.
 */
export function useExecutionTrace(executionId: string | null, getToken: TokenProvider): TraceState {
  const [state, dispatch] = useReducer(reducer, INITIAL);

  useEffect(() => {
    if (!executionId) return;
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    let finished = false; // terminal event seen, or effect cleaned up
    let disposed = false;

    dispatch({ type: "reset" });

    function connect() {
      const ws = new WebSocket(`${WS_URL}/ws/executions/${encodeURIComponent(executionId!)}`);
      socket = ws;

      ws.onopen = async () => {
        try {
          const token = await getToken();
          if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "auth", token }));
        } catch (err) {
          finished = true;
          dispatch({ type: "error", error: err instanceof Error ? err.message : "Not signed in" });
          ws.close();
        }
      };

      ws.onmessage = (message) => {
        let event: TraceEvent;
        try {
          event = JSON.parse(message.data);
        } catch {
          return; // not ours; ignore rather than tear down the stream
        }
        attempts = 0; // healthy stream: reset the backoff
        dispatch({ type: "event", event });
        if (event.event === "execution.completed" || event.event === "execution.failed") finished = true;
        if (event.event === "state.hydrated" && ["COMPLETED", "FAILED"].includes(event.execution.status)) {
          finished = true;
        }
      };

      ws.onclose = (close) => {
        if (disposed) return;
        if (close.code === 1008) {
          finished = true;
          dispatch({ type: "error", error: `Not allowed to view this run: ${close.reason || "policy violation"}` });
          return;
        }
        if (finished || close.code === 1000) {
          dispatch({ type: "closed" });
          return;
        }
        if (attempts >= MAX_RECONNECTS) {
          dispatch({ type: "error", error: "Lost the live connection to this run" });
          return;
        }
        attempts += 1;
        dispatch({ type: "connecting" });
        retryTimer = setTimeout(connect, Math.min(500 * 2 ** attempts, 8000));
      };
    }

    connect();
    return () => {
      disposed = true;
      finished = true;
      clearTimeout(retryTimer);
      socket?.close(1000);
    };
  }, [executionId, getToken]);

  return executionId ? state : INITIAL;
}
