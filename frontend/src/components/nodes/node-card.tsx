import { Handle, Position } from "@xyflow/react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

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
      )}
    >
      {input && <Handle type="target" position={Position.Left} className={handle} />}

      <div className={cn("flex items-center gap-2 px-3 py-2", headerClassName)}>
        <Icon className="size-4 shrink-0" aria-hidden />
        <div className="min-w-0">
          <div className="text-[10px] font-semibold tracking-wider uppercase opacity-75">{kind}</div>
          <div className="truncate text-sm font-medium">{label}</div>
        </div>
      </div>
      {children && <div className="px-3 pb-3 text-xs">{children}</div>}

      {output && <Handle type="source" position={Position.Right} className={handle} />}
    </div>
  );
}
