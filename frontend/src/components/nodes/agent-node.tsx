import type { NodeProps } from "@xyflow/react";
import { Bot } from "lucide-react";
import { memo } from "react";

import { NodeCard } from "./node-card";
import type { AgentFlowNode } from "./types";

/** An LLM agent step: the widest card, with a solid header band. */
export const AgentNode = memo(function AgentNode({ data, selected }: NodeProps<AgentFlowNode>) {
  return (
    <NodeCard
      icon={Bot}
      kind="Agent"
      label={data.label}
      selected={selected}
      // No overflow-hidden here: handles sit centered on the card edge, and
      // clipping half of each one makes it impossible to grab.
      className="w-64 rounded-xl border-violet-300 ring-violet-500 dark:border-violet-800"
      headerClassName="mb-2 rounded-t-[11px] bg-gradient-to-r from-violet-600 to-indigo-600 text-white"
      handleClassName="bg-violet-500!"
    >
      <span className="inline-block rounded bg-violet-50 px-1.5 py-0.5 font-mono text-[11px] text-violet-700 dark:bg-violet-950 dark:text-violet-300">
        {data.model}
      </span>
      {data.instructions && (
        <p className="mt-2 line-clamp-2 leading-relaxed text-zinc-600 dark:text-zinc-400">{data.instructions}</p>
      )}
    </NodeCard>
  );
});
