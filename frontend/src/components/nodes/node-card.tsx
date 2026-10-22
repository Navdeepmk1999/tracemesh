import { Handle, Position } from "@xyflow/react";
import { CircleCheck, CircleX, Clock, LoaderCircle, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { useNodeRunState } from "@/components/canvas/run-state";
import { cn } from "@/lib/cn";
import type { ExecutionStatus } from "@/lib/api/types";

const RUN_STYLES: Record<ExecutionStatus, string> = {
  PENDING: "opacity-60",
  RUNNING: "ring-2 ring-sky-400 ring-offset-2 ring-offset-white shadow-lg shadow-sky-500/20 dark:ring-offset-zinc-950",
  COMPLETED: "ring-2 ring-emerald-500/70",
  FAILED: "border-red-500! ring-2 ring-red-500 shadow-lg shadow-red-500/20",
};

const RUN_BADGES: Record<ExecutionStatus, { icon: LucideIcon; className: string; label: string }> = {
  PENDING: { icon: Clock, className: "bg-zinc-100 text-zinc-500 dark:bg-zinc-800", label: "Waiting" },
  RUNNING: { icon: LoaderCircle, className: "bg-sky-500 text-white [&>svg]:animate-spin", label: "Running" },
  COMPLETED: { icon: CircleCheck, className: "bg-emerald-500 text-white", label: "Completed" },
  FAILED: { icon: CircleX, className: "bg-red-500 text-white", label: "Failed" },
};

type NodeCardProps = {
  icon: LucideIcon;
  kind: string;
  label: string;
  selected?: boolean;
  /** Has an input handle (left). Triggers don't: they start a workflow. */
  input?: boolean;
  /** Has an output handle (right). */
  output?: boolean;
  className?: string;
  headerClassName?: string;
  handleClassName?: string;
  children?: ReactNode;
};

/** Shared shell; each node type supplies its own colors, shape and body. */
export function NodeCard({
  icon: Icon,
  kind,
  label,
  selected,
  input = true,
  output = true,
  className,
  headerClassName,
  handleClassName,
  children,
}: NodeCardProps) {
  const run = useNodeRunState();
  const badge = run && RUN_BADGES[run.status];
  const handle = cn(
    "size-3! border-2! border-white! dark:border-zinc-950! transition-transform hover:scale-150",
    handleClassName,
  );

  return (
    <div
      className={cn(
        "relative border bg-white text-zinc-900 shadow-sm transition-shadow dark:bg-zinc-900 dark:text-zinc-100",
        selected && "shadow-lg ring-2 ring-offset-2 ring-offset-white dark:ring-offset-zinc-950",
        className,
        // Last, so run state wins over the type's own border/ring colors.
        run && RUN_STYLES[run.status],
      )}
    >
      {badge && (
        <span
          role="status"
          aria-label={badge.label}
          title={badge.label}
          className={cn("absolute -top-2.5 -right-2.5 z-10 flex size-5 items-center justify-center rounded-full shadow", badge.className)}
        >
          <badge.icon className="size-3.5" aria-hidden />
        </span>
      )}
      {input && <Handle type="target" position={Position.Left} className={handle} />}

      <div className={cn("flex items-center gap-2 px-3 py-2", headerClassName)}>
        <Icon className="size-4 shrink-0" aria-hidden />
        <div className="min-w-0">
          <div className="text-[10px] font-semibold tracking-wider uppercase opacity-75">{kind}</div>
          <div className="truncate text-sm font-medium">{label}</div>
        </div>
      </div>
      {children && <div className="px-3 pb-3 text-xs">{children}</div>}
      {run?.status === "FAILED" && run.error && (
        <p className="mx-3 mb-3 line-clamp-3 rounded bg-red-50 px-2 py-1 text-[11px] leading-snug text-red-700 dark:bg-red-950/60 dark:text-red-300" title={run.error}>
          {run.error}
        </p>
      )}

      {output && <Handle type="source" position={Position.Right} className={handle} />}
    </div>
  );
}
