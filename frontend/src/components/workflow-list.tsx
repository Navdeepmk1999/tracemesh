"use client";

import { ArrowRight, LoaderCircle, Plus, Workflow } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ApiError, createApiClient } from "@/lib/api/client";
import { getSupabaseAccessToken } from "@/lib/api/token";
import type { ApiWorkflow } from "@/lib/api/types";

export function WorkflowList() {
  const router = useRouter();
  const api = useMemo(() => createApiClient(getSupabaseAccessToken), []);
  const [workflows, setWorkflows] = useState<ApiWorkflow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    api.listWorkflows().then(setWorkflows, (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) router.replace("/login?next=/workflows");
      else setError(err instanceof Error ? err.message : "Couldn't load workflows");
    });
  }, [api, router]);

  async function create() {
    setCreating(true);
    try {
      const workflow = await api.createWorkflow("Untitled workflow");
      router.push(`/workflows/${workflow.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't create a workflow");
      setCreating(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-10">
      <div className="mb-6 flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Workflows</h1>
        <button
          type="button"
          onClick={create}
          disabled={creating}
          className="flex items-center gap-1.5 rounded-md bg-violet-600 px-3 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-60"
        >
          {creating ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : <Plus className="size-4" aria-hidden />}
          New workflow
        </button>
      </div>

      {error && (
        <p role="alert" className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">
          {error}
        </p>
      )}

      {workflows === null && !error && (
        <div className="flex justify-center py-12">
          <LoaderCircle className="size-6 animate-spin text-zinc-400" aria-label="Loading workflows" />
        </div>
      )}

      {workflows?.length === 0 && (
        <div className="rounded-lg border border-dashed border-zinc-300 px-6 py-12 text-center text-zinc-500 dark:border-zinc-700">
          No workflows yet. Create one to open the canvas.
        </div>
      )}

      {workflows && workflows.length > 0 && (
        <ul className="divide-y divide-zinc-200 overflow-hidden rounded-lg border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
          {workflows.map((w) => (
            <li key={w.id}>
              <Link
                href={`/workflows/${w.id}`}
                className="group flex items-center gap-3 px-4 py-3 hover:bg-zinc-50 dark:hover:bg-zinc-900"
              >
                <Workflow className="size-4 shrink-0 text-violet-500" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{w.name}</span>
                  <span className="block text-xs text-zinc-500">
                    Created {new Date(w.created_at).toLocaleString()}
                  </span>
                </span>
                <ArrowRight className="size-4 text-zinc-300 group-hover:text-zinc-600" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
