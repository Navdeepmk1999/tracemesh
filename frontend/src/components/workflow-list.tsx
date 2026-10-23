"use client";

import { ArrowRight, LoaderCircle, Pencil, Plus, Trash2, Workflow } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { Modal } from "@/components/ui/modal";
import { ApiError, createApiClient, type ApiClient } from "@/lib/api/client";
import { getSupabaseAccessToken } from "@/lib/api/token";
import type { ApiWorkflow } from "@/lib/api/types";

const MAX_NAME_LENGTH = 255; // backend limit (WorkflowName)
const DEFAULT_NAME = "Untitled Workflow"; // backend default for a blank name

type Dialog =
  | { kind: "create" }
  | { kind: "rename"; workflow: ApiWorkflow }
  | { kind: "delete"; workflow: ApiWorkflow }
  | null;

function message(err: unknown, fallback: string) {
  if (err instanceof ApiError && err.status === 0) return err.message; // network/CORS
  return err instanceof Error && err.message ? err.message : fallback;
}

export function WorkflowList() {
  const router = useRouter();
  const api = useMemo(() => createApiClient(getSupabaseAccessToken), []);
  const [workflows, setWorkflows] = useState<ApiWorkflow[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const toLogin = useCallback(() => router.replace("/login?next=/workflows"), [router]);

  // State is only set from the promise callbacks, so this can run in an effect.
  const fetchList = useCallback(() => {
    api.listWorkflows().then(setWorkflows, (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) toLogin();
      else setLoadError(message(err, "Couldn't load your workflows."));
    });
  }, [api, toLogin]);

  useEffect(fetchList, [fetchList]);

  function retry() {
    setLoadError(null);
    setWorkflows(null); // back to the spinner
    fetchList();
  }

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 4000);
    return () => clearTimeout(timer);
  }, [notice]);

  const remove = (id: string) => setWorkflows((list) => list?.filter((w) => w.id !== id) ?? list);

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-10">
      <div className="mb-6 flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Workflows</h1>
        <button
          type="button"
          onClick={() => setDialog({ kind: "create" })}
          className="flex items-center gap-1.5 rounded-md bg-violet-600 px-3 py-2 text-sm font-medium text-white hover:bg-violet-500"
        >
          <Plus className="size-4" aria-hidden />
          New workflow
        </button>
      </div>

      {notice && (
        <p role="status" className="mb-4 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300">
          {notice}
        </p>
      )}

      {loadError && (
        <div role="alert" className="flex items-center justify-between gap-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">
          <span>{loadError}</span>
          <button type="button" onClick={retry} className="shrink-0 font-medium underline">
            Try again
          </button>
        </div>
      )}

      {workflows === null && !loadError && (
        <div className="flex justify-center py-12">
          <LoaderCircle className="size-6 animate-spin text-zinc-400" aria-label="Loading workflows" />
        </div>
      )}

      {workflows?.length === 0 && (
        <div className="rounded-lg border border-dashed border-zinc-300 px-6 py-12 text-center dark:border-zinc-700">
          <p className="text-zinc-500">No workflows yet.</p>
          <button
            type="button"
            onClick={() => setDialog({ kind: "create" })}
            className="mt-3 text-sm font-medium text-violet-700 hover:underline dark:text-violet-400"
          >
            Create your first workflow
          </button>
        </div>
      )}

      {workflows && workflows.length > 0 && (
        <ul className="divide-y divide-zinc-200 rounded-lg border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
          {workflows.map((w) => (
            <li key={w.id} className="group flex items-center gap-1 pr-2 hover:bg-zinc-50 dark:hover:bg-zinc-900">
              <Link href={`/workflows/${w.id}`} className="flex min-w-0 flex-1 items-center gap-3 px-4 py-3">
                <Workflow className="size-4 shrink-0 text-violet-500" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{w.name}</span>
                  <span className="block text-xs text-zinc-500">Created {new Date(w.created_at).toLocaleString()}</span>
                </span>
                <ArrowRight className="size-4 shrink-0 text-zinc-300 group-hover:text-zinc-600" aria-hidden />
              </Link>
              <IconButton label={`Rename ${w.name}`} onClick={() => setDialog({ kind: "rename", workflow: w })}>
                <Pencil className="size-4" />
              </IconButton>
              <IconButton label={`Delete ${w.name}`} danger onClick={() => setDialog({ kind: "delete", workflow: w })}>
                <Trash2 className="size-4" />
              </IconButton>
            </li>
          ))}
        </ul>
      )}

      {dialog?.kind === "create" && (
        <NameDialog
          title="New workflow"
          submitLabel="Create"
          initialName=""
          allowBlank
          onClose={() => setDialog(null)}
          onUnauthorized={toLogin}
          onSubmit={async (name) => {
            const created = await api.createWorkflow(name);
            setWorkflows((list) => (list ? [created, ...list] : [created]));
            router.push(`/workflows/${created.id}`);
          }}
        />
      )}

      {dialog?.kind === "rename" && (
        <NameDialog
          title="Rename workflow"
          submitLabel="Save"
          initialName={dialog.workflow.name}
          onClose={() => setDialog(null)}
          onUnauthorized={toLogin}
          onGone={() => {
            remove(dialog.workflow.id);
            setNotice("That workflow no longer exists.");
          }}
          onSubmit={async (name) => {
            const updated = await api.renameWorkflow(dialog.workflow.id, name);
            setWorkflows((list) => list?.map((w) => (w.id === updated.id ? updated : w)) ?? list);
            setDialog(null);
          }}
        />
      )}

      {dialog?.kind === "delete" && (
        <DeleteDialog
          workflow={dialog.workflow}
          api={api}
          onClose={() => setDialog(null)}
          onUnauthorized={toLogin}
          onDeleted={() => {
            remove(dialog.workflow.id);
            setNotice(`Deleted “${dialog.workflow.name}”.`);
            setDialog(null);
          }}
        />
      )}
    </div>
  );
}

function IconButton({
  label,
  onClick,
  danger,
  children,
}: {
  label: string;
  onClick: () => void;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={
        danger
          ? "rounded-md p-2 text-zinc-400 hover:bg-red-50 hover:text-red-600 focus-visible:text-red-600 dark:hover:bg-red-950/50"
          : "rounded-md p-2 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 focus-visible:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
      }
    >
      {children}
    </button>
  );
}

type NameDialogProps = {
  title: string;
  submitLabel: string;
  initialName: string;
  /** Create allows a blank name (the backend fills in the default). */
  allowBlank?: boolean;
  onSubmit: (name: string) => Promise<void>;
  onClose: () => void;
  onUnauthorized: () => void;
  /** The workflow was deleted elsewhere (404). */
  onGone?: () => void;
};

function NameDialog({ title, submitLabel, initialName, allowBlank, onSubmit, onClose, onUnauthorized, onGone }: NameDialogProps) {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget).get("name") ?? "").trim();
    if (!name && !allowBlank) {
      setError("Give the workflow a name.");
      return;
    }
    if (name.length > MAX_NAME_LENGTH) {
      setError(`Keep it under ${MAX_NAME_LENGTH} characters.`);
      return;
    }
    setPending(true);
    setError(null);
    try {
      await onSubmit(name);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return onUnauthorized();
      if (err instanceof ApiError && err.status === 404 && onGone) {
        onGone();
        return onClose();
      }
      setError(message(err, "Something went wrong. Try again."));
      setPending(false);
    }
  }

  return (
    <Modal title={title} onClose={onClose} busy={pending}>
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="workflow-name" className="text-sm font-medium">
            Name
          </label>
          <input
            id="workflow-name"
            name="name"
            defaultValue={initialName}
            placeholder={allowBlank ? DEFAULT_NAME : undefined}
            maxLength={MAX_NAME_LENGTH}
            data-autofocus
            onFocus={(e) => e.currentTarget.select()}
            aria-invalid={error ? true : undefined}
            className="rounded-md border border-zinc-300 bg-white px-3 py-2 outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-500/30 dark:border-zinc-700 dark:bg-zinc-950"
          />
        </div>
        {error && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={pending}
            className="rounded-md px-3 py-2 text-sm font-medium hover:bg-zinc-100 disabled:opacity-50 dark:hover:bg-zinc-800"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={pending}
            className="flex items-center gap-1.5 rounded-md bg-violet-600 px-3 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-60"
          >
            {pending && <LoaderCircle className="size-4 animate-spin" aria-hidden />}
            {submitLabel}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function DeleteDialog({
  workflow,
  api,
  onClose,
  onDeleted,
  onUnauthorized,
}: {
  workflow: ApiWorkflow;
  api: ApiClient;
  onClose: () => void;
  onDeleted: () => void;
  onUnauthorized: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function confirm() {
    setPending(true);
    setError(null);
    try {
      await api.deleteWorkflow(workflow.id);
      onDeleted();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return onUnauthorized();
      // Already gone (another tab, another device): same end state.
      if (err instanceof ApiError && err.status === 404) return onDeleted();
      setError(message(err, "Couldn't delete the workflow. Try again."));
      setPending(false);
    }
  }

  return (
    <Modal title="Delete workflow?" onClose={onClose} busy={pending}>
      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        <span className="font-medium text-zinc-900 dark:text-zinc-100">“{workflow.name}”</span> and all of its nodes,
        connections and run history will be permanently deleted.
      </p>
      {error && (
        <p role="alert" className="mt-3 text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
      <div className="mt-5 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          disabled={pending}
          data-autofocus // the safe choice gets focus
          className="rounded-md px-3 py-2 text-sm font-medium hover:bg-zinc-100 disabled:opacity-50 dark:hover:bg-zinc-800"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={confirm}
          disabled={pending}
          className="flex items-center gap-1.5 rounded-md bg-red-600 px-3 py-2 text-sm font-medium text-white hover:bg-red-500 disabled:opacity-60"
        >
          {pending && <LoaderCircle className="size-4 animate-spin" aria-hidden />}
          Delete
        </button>
      </div>
    </Modal>
  );
}
