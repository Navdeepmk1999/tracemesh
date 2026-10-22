import type { NodeProps } from "@xyflow/react";
import { Webhook } from "lucide-react";
import { memo } from "react";

import { cn } from "@/lib/cn";

import { NodeCard } from "./node-card";
import type { WebhookFlowNode } from "./types";

const METHOD_COLORS: Record<WebhookFlowNode["data"]["method"], string> = {
  GET: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  POST: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  PUT: "bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300",
  PATCH: "bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300",
  DELETE: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
};

/** An outbound HTTP call: square corners and a thick accent edge. */
export const WebhookNode = memo(function WebhookNode({ data, selected }: NodeProps<WebhookFlowNode>) {
  return (
    <NodeCard
      icon={Webhook}
      kind="Webhook"
      label={data.label}
      selected={selected}
      className="w-56 rounded-sm border-l-4 border-amber-300 border-l-amber-500 ring-amber-500 dark:border-amber-800 dark:border-l-amber-500"
      headerClassName="text-amber-700 dark:text-amber-300"
      handleClassName="bg-amber-500!"
    >
      <div className="flex min-w-0 items-center gap-1.5">
        <span className={cn("rounded px-1.5 py-0.5 font-mono text-[10px] font-bold", METHOD_COLORS[data.method])}>
          {data.method}
        </span>
        <code className="truncate font-mono text-[11px] text-zinc-600 dark:text-zinc-400" title={data.url}>
          {data.url}
        </code>
      </div>
    </NodeCard>
  );
});
