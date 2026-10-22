"use client";

import { Bot, GripVertical, Webhook, Zap, type LucideIcon } from "lucide-react";
import type { DragEvent } from "react";

import type { WorkflowNodeType } from "@/components/nodes";
import { cn } from "@/lib/cn";

export const NODE_DRAG_MIME = "application/x-tracemesh-node";

const ITEMS: { type: WorkflowNodeType; label: string; hint: string; icon: LucideIcon; tone: string }[] = [
  {
    type: "trigger",
    label: "Trigger",
    hint: "Starts the workflow",
    icon: Zap,
    tone: "text-emerald-600 bg-emerald-50 dark:text-emerald-300 dark:bg-emerald-950",
  },
  {
    type: "agent",
    label: "Agent",
    hint: "Runs an LLM step",
    icon: Bot,
    tone: "text-violet-600 bg-violet-50 dark:text-violet-300 dark:bg-violet-950",
  },
  {
    type: "webhook",
    label: "Webhook",
    hint: "Calls an HTTP endpoint",
    icon: Webhook,
    tone: "text-amber-600 bg-amber-50 dark:text-amber-300 dark:bg-amber-950",
  },
];

type NodePaletteProps = {
  /** Click (or Enter/Space) adds the node at the center of the view: the
   * keyboard and touch path, since HTML drag-and-drop needs a mouse. */
  onAdd: (type: WorkflowNodeType) => void;
};

export function NodePalette({ onAdd }: NodePaletteProps) {
  function onDragStart(event: DragEvent, type: WorkflowNodeType) {
    event.dataTransfer.setData(NODE_DRAG_MIME, type);
    event.dataTransfer.effectAllowed = "move";
  }

  return (
    <div className="w-48 rounded-lg border border-zinc-200 bg-white/95 p-2 shadow-sm backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/95">
      <div className="px-1 pb-2 text-[11px] font-semibold tracking-wider text-zinc-500 uppercase">Add nodes</div>
      <ul className="flex flex-col gap-1">
        {ITEMS.map(({ type, label, hint, icon: Icon, tone }) => (
          <li key={type}>
            <button
              type="button"
              draggable
              onDragStart={(e) => onDragStart(e, type)}
              onClick={() => onAdd(type)}
              title={`Drag onto the canvas, or click to add a ${label.toLowerCase()}`}
              className="group flex w-full cursor-grab items-center gap-2 rounded-md p-1.5 text-left hover:bg-zinc-100 active:cursor-grabbing dark:hover:bg-zinc-800"
            >
              <span className={cn("flex size-7 shrink-0 items-center justify-center rounded-md", tone)}>
                <Icon className="size-4" aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium">{label}</span>
                <span className="block truncate text-[11px] text-zinc-500">{hint}</span>
              </span>
              <GripVertical className="size-4 text-zinc-300 group-hover:text-zinc-500" aria-hidden />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
