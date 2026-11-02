import { useNodeId, useReactFlow } from "@xyflow/react";
import { useCallback, useRef, type KeyboardEvent } from "react";

import { cn } from "@/lib/cn";

import type { WorkflowNodeType } from "./types";

/** Name a node gets when created, and falls back to if its name is cleared. */
export const DEFAULT_NODE_LABELS: Record<WorkflowNodeType, string> = {
  trigger: "Manual trigger",
  agent: "New agent",
  webhook: "Send webhook",
};

const MAX_LABEL_LENGTH = 80;

type NodeLabelInputProps = {
  value: string;
  /** Used when the name is left blank. */
  fallback: string;
  /** Node kind, for the accessible name ("Agent name"). */
  kind: string;
};

/**
 * The node's title as an inline text field. Edits go straight into the
 * node's data.label in React Flow state, so they mark the workflow as
 * unsaved and are persisted by the canvas's normal Save.
 */
export function NodeLabelInput({ value, fallback, kind }: NodeLabelInputProps) {
  const nodeId = useNodeId();
  const { setNodes } = useReactFlow();
  // The name when editing started, for Escape; and a flag so the blur that
  // Escape triggers doesn't write the abandoned edit back.
  const original = useRef(value);
  const reverting = useRef(false);

  const setLabel = useCallback(
    (label: string) => {
      setNodes((nodes) => nodes.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, label } } : n)));
    },
    [nodeId, setNodes],
  );

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.currentTarget.blur();
    } else if (event.key === "Escape") {
      reverting.current = true;
      setLabel(original.current);
      event.currentTarget.blur();
    }
  }

  return (
    <input
      // nodrag: selecting text mustn't drag the node. nopan: double-clicking
      // a word mustn't zoom the canvas.
      className={cn(
        "nodrag nopan -mx-1 block w-full min-w-0 truncate rounded-sm border-b border-transparent bg-transparent px-1",
        "cursor-text text-sm font-medium text-inherit outline-none transition-colors placeholder:text-current placeholder:opacity-50",
        "hover:border-current/25 focus:border-current/60",
      )}
      value={value}
      placeholder={fallback}
      maxLength={MAX_LABEL_LENGTH}
      spellCheck={false}
      aria-label={`${kind} name`}
      onFocus={() => {
        original.current = value;
      }}
      onChange={(event) => setLabel(event.target.value)}
      onBlur={(event) => {
        if (reverting.current) {
          reverting.current = false;
          return;
        }
        const raw = event.target.value;
        const name = raw.trim() || fallback;
        if (name !== raw) setLabel(name);
      }}
      onKeyDown={onKeyDown}
    />
  );
}
