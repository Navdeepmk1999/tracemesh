import type { NodeProps } from "@xyflow/react";
import { Zap } from "lucide-react";
import { memo } from "react";

import { NodeCard } from "./node-card";
import type { TriggerFlowNode } from "./types";

const EVENT_LABELS: Record<TriggerFlowNode["data"]["event"], string> = {
  manual: "Run manually",
  schedule: "On a schedule",
  http: "On HTTP request",
};

/** Entry point of a workflow: output only, rounded "start" shape. */
export const TriggerNode = memo(function TriggerNode({ data, selected }: NodeProps<TriggerFlowNode>) {
  return (
    <NodeCard
      icon={Zap}
      kind="Trigger"
      label={data.label}
      selected={selected}
      input={false}
      className="w-52 rounded-l-[1.75rem] rounded-r-lg border-emerald-300 ring-emerald-500 dark:border-emerald-800"
      headerClassName="rounded-l-[1.7rem] rounded-r-md text-emerald-700 dark:text-emerald-300"
      handleClassName="bg-emerald-500!"
    >
      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-0.5 font-medium text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
        <span className="size-1.5 rounded-full bg-emerald-500" aria-hidden />
        {EVENT_LABELS[data.event]}
        {data.event === "schedule" && data.schedule && <code className="font-mono">{data.schedule}</code>}
      </span>
    </NodeCard>
  );
});
