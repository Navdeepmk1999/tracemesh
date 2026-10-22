"use client";

import { useNodeId } from "@xyflow/react";
import { createContext, useContext } from "react";

import type { NodeRunState } from "@/hooks/use-execution-trace";

/**
 * Live run status per node id. Kept out of node.data on purpose: run state
 * isn't part of the workflow, so it must not mark the graph as unsaved or
 * end up in config_json.
 */
export const RunStateContext = createContext<Record<string, NodeRunState>>({});

/** Run status of the node being rendered, if a run is being shown. */
export function useNodeRunState(): NodeRunState | undefined {
  const nodeId = useNodeId();
  const runs = useContext(RunStateContext);
  return nodeId ? runs[nodeId] : undefined;
}
