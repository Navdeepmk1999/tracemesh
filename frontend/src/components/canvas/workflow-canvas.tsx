"use client";

import {
  addEdge,
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type DefaultEdgeOptions,
  type Edge,
  type IsValidConnection,
  type OnConnectEnd,
} from "@xyflow/react";
import { AlertTriangle, LoaderCircle, MousePointerClick, Play, Save, X } from "lucide-react";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type DragEvent,
} from "react";

import "@xyflow/react/dist/style.css";

import { createNode, nodeTypes, type WorkflowNode, type WorkflowNodeType } from "@/components/nodes";
import { useExecutionTrace, type TraceState } from "@/hooks/use-execution-trace";
import { ApiError, createApiClient, type ApiClient, type TokenProvider } from "@/lib/api/client";
import { getSupabaseAccessToken } from "@/lib/api/token";
import type { ApiWorkflow } from "@/lib/api/types";
import { cn } from "@/lib/cn";

import { connectionError } from "./graph-rules";
import { applyIdMap, fromApi, isDirty, SyncError, syncGraph, type GraphSnapshot } from "./graph-sync";
import { NODE_DRAG_MIME, NodePalette } from "./node-palette";
import { RunStateContext } from "./run-state";

const NODE_TYPES = new Set<string>(Object.keys(nodeTypes));

const defaultEdgeOptions: DefaultEdgeOptions = {
  type: "smoothstep",
  markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
  style: { strokeWidth: 2 },
};

// Approximate rendered sizes (see components/nodes), for placing new nodes.
const NODE_SIZES: Record<WorkflowNodeType, { width: number; height: number }> = {
  trigger: { width: 208, height: 84 },
  agent: { width: 256, height: 136 },
  webhook: { width: 224, height: 80 },
};

const MINIMAP_COLORS: Record<WorkflowNodeType, string> = {
  trigger: "#10b981",
  agent: "#8b5cf6",
  webhook: "#f59e0b",
};

const noopSubscribe = () => () => {};

type WorkflowCanvasProps = {
  workflowId: string;
  /** Where the backend JWT comes from; the signed-in Supabase session by default. */
  getToken?: TokenProvider;
};

export function WorkflowCanvas({ workflowId, getToken = getSupabaseAccessToken }: WorkflowCanvasProps) {
  // Client-only: React Flow resolves colorMode="system" from matchMedia, which
  // the server can't know, so server HTML would hydrate with the wrong theme
  // class. The server sends a placeholder; the canvas mounts in the browser.
  const isClient = useSyncExternalStore(noopSubscribe, () => true, () => false);
  if (!isClient) return <CanvasPlaceholder />;

  return (
    // Keyed by workflow so navigating between workflows starts fresh state.
    <ReactFlowProvider key={workflowId}>
      <WorkflowLoader workflowId={workflowId} getToken={getToken} />
    </ReactFlowProvider>
  );
}

function CanvasPlaceholder({ children }: { children?: React.ReactNode }) {
  return (
    <div className="flex h-full w-full items-center justify-center bg-zinc-50 dark:bg-zinc-900" aria-busy={!children}>
      {children ?? <LoaderCircle className="size-6 animate-spin text-zinc-400" aria-label="Loading workflow" />}
    </div>
  );
}

type Loaded = { workflow: ApiWorkflow } & ReturnType<typeof fromApi>;

/** Fetches the workflow, then mounts the canvas with it, so React Flow's
 * fitView frames the real graph on first render. */
function WorkflowLoader({ workflowId, getToken }: { workflowId: string; getToken: TokenProvider }) {
  const router = useRouter();
  const api = useMemo(() => createApiClient(getToken), [getToken]);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.getWorkflow(workflowId), api.listNodes(workflowId), api.listEdges(workflowId)])
      .then(([workflow, nodes, edges]) => {
        if (!cancelled) setLoaded({ workflow, ...fromApi(nodes, edges) });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const apiError = err instanceof ApiError ? err : new ApiError(0, "Couldn't load this workflow");
        if (apiError.status === 401) {
          router.replace(`/login?next=${encodeURIComponent(`/workflows/${workflowId}`)}`);
          return;
        }
        setError(apiError);
      });
    return () => {
      cancelled = true;
    };
  }, [api, workflowId, attempt, router]);

  if (loaded) return <Canvas api={api} getToken={getToken} {...loaded} />;
  if (!error) return <CanvasPlaceholder />;

  // A malformed id is a 422 from the API; to the user it's also "not found".
  const notFound = error.status === 404 || error.status === 422;
  return (
    <CanvasPlaceholder>
      <div className="max-w-sm text-center">
        <AlertTriangle className="mx-auto mb-3 size-6 text-amber-500" aria-hidden />
        <p className="font-medium">{notFound ? "Workflow not found" : "Couldn't load this workflow"}</p>
        <p className="mt-1 text-sm text-zinc-500">
          {notFound ? "It may have been deleted, or it belongs to another account." : error.message}
        </p>
        {!notFound && (
          <button
            type="button"
            onClick={() => {
              setError(null);
              setAttempt((n) => n + 1);
            }}
            className="mt-4 rounded-md border border-zinc-300 px-3 py-1.5 text-sm hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Try again
          </button>
        )}
      </div>
    </CanvasPlaceholder>
  );
}

type CanvasProps = Loaded & { api: ApiClient; getToken: TokenProvider };

function Canvas({ api, getToken, workflow, nodes: initialNodes, edges: initialEdges, snapshot }: CanvasProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<WorkflowNode>(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(initialEdges);
  const { screenToFlowPosition, getNodes, getEdges, getIntersectingNodes } = useReactFlow<WorkflowNode, Edge>();
  const wrapper = useRef<HTMLDivElement>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // --- Persistence --------------------------------------------------------

  const [saved, setSaved] = useState<GraphSnapshot>(snapshot);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const dirty = useMemo(() => isDirty(saved, nodes, edges), [saved, nodes, edges]);

  /** Push local changes to the API. Resolves true if everything saved. */
  const save = useCallback(async (): Promise<boolean> => {
    if (savingRef.current) return false;
    savingRef.current = true;
    setSaving(true);
    let ok = true;
    try {
      // Read the latest graph at call time, not from a stale render.
      let result;
      try {
        result = await syncGraph(api, workflow.id, saved, getNodes(), getEdges());
      } catch (err) {
        if (!(err instanceof SyncError)) throw err;
        ok = false;
        result = err.partial; // keep what did save, so a retry only redoes the rest
        setNotice(`Save failed: ${err.message}`);
      }
      const { idMap } = result;
      // Swap local ids for server ids, via functional updates so edits made
      // while the save was in flight are kept.
      setNodes((nds) => applyIdMap(idMap, nds, []).nodes);
      setEdges((eds) => applyIdMap(idMap, [], eds).edges);
      setSaved(result.snapshot);
    } catch (err) {
      ok = false;
      setNotice(`Save failed: ${err instanceof Error ? err.message : "unknown error"}`);
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
    return ok;
  }, [api, workflow.id, saved, getNodes, getEdges, setNodes, setEdges]);

  // Cmd/Ctrl+S saves instead of opening the browser's "Save page" dialog.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void save();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [save]);

  // Warn before closing the tab with unsaved changes.
  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  // --- Execution ----------------------------------------------------------

  const [executionId, setExecutionId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const trace = useExecutionTrace(executionId, getToken);
  const runActive =
    starting || (executionId !== null && trace.connection !== "error" && !["COMPLETED", "FAILED"].includes(trace.status ?? ""));

  const execute = useCallback(async () => {
    setStarting(true);
    try {
      // The worker runs what the server has, so unsaved edits go first.
      if (dirty && !(await save())) return;
      if (getNodes().length === 0) {
        setNotice("Add at least one node before running");
        return;
      }
      const queued = await api.execute(workflow.id);
      setExecutionId(queued.execution_id);
    } catch (err) {
      setNotice(`Couldn't start the run: ${err instanceof Error ? err.message : "unknown error"}`);
    } finally {
      setStarting(false);
    }
  }, [api, workflow.id, dirty, save, getNodes]);

  // Animate edges flowing into a running node.
  const renderedEdges = useMemo(
    () => edges.map((e) => (trace.nodes[e.target]?.status === "RUNNING" ? { ...e, animated: true } : e)),
    [edges, trace.nodes],
  );

  // --- Editing ------------------------------------------------------------

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 4000);
    return () => clearTimeout(timer);
  }, [notice]);

  // Runs while dragging a connection: an invalid target handle is shown red
  // and the drop is refused.
  const isValidConnection: IsValidConnection = useCallback(
    (connection) => connectionError(connection, getNodes(), getEdges()) === null,
    [getNodes, getEdges],
  );

  const onConnect = useCallback(
    (connection: Connection) => setEdges((eds) => addEdge({ ...connection, id: crypto.randomUUID() }, eds)),
    [setEdges],
  );

  // Say *why* a drop on a handle was refused, instead of silently ignoring it.
  const onConnectEnd: OnConnectEnd = useCallback(
    (_event, state) => {
      if (state.isValid !== false || !state.fromNode || !state.toNode) return;
      const fromSource = state.fromHandle?.type === "source";
      const connection = {
        source: fromSource ? state.fromNode.id : state.toNode.id,
        target: fromSource ? state.toNode.id : state.fromNode.id,
        sourceHandle: null,
        targetHandle: null,
      };
      setNotice(connectionError(connection, getNodes(), getEdges()) ?? "Those handles can't be connected");
    },
    [getNodes, getEdges],
  );

  const addNodeAt = useCallback(
    (type: WorkflowNodeType, position: { x: number; y: number }) => {
      const node = createNode(type, position);
      // Select only the new node, so it's obvious where it landed.
      setNodes((nds) => [...nds.map((n) => ({ ...n, selected: false })), { ...node, selected: true }]);
    },
    [setNodes],
  );

  const onDragOver = useCallback((event: DragEvent) => {
    if (!event.dataTransfer.types.includes(NODE_DRAG_MIME)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: DragEvent) => {
      const type = event.dataTransfer.getData(NODE_DRAG_MIME);
      if (!NODE_TYPES.has(type)) return;
      event.preventDefault();
      // Screen pixels -> canvas coordinates, accounting for pan and zoom.
      addNodeAt(type as WorkflowNodeType, screenToFlowPosition({ x: event.clientX, y: event.clientY }));
    },
    [addNodeAt, screenToFlowPosition],
  );

  // Click/keyboard path: the nearest free spot to the middle of the view.
  // Landing on top of a node would hide its handles and make it hard to grab.
  const addNodeAtCenter = useCallback(
    (type: WorkflowNodeType) => {
      const rect = wrapper.current?.getBoundingClientRect();
      if (!rect) return;
      const center = screenToFlowPosition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 });
      const size = NODE_SIZES[type];
      const origin = { x: center.x - size.width / 2, y: center.y - size.height / 2 };
      const GAP = 32;

      // Scan rows below, then above, the center for a gap.
      for (let step = 0; step < 24; step++) {
        const dy = Math.ceil(step / 2) * (size.height + GAP) * (step % 2 ? 1 : -1);
        const candidate = { x: origin.x, y: origin.y + dy };
        const box = { ...candidate, width: size.width + GAP, height: size.height + GAP };
        if (getIntersectingNodes(box, true).length === 0) {
          addNodeAt(type, candidate);
          return;
        }
      }
      addNodeAt(type, origin); // canvas is crowded everywhere nearby; just place it
    },
    [addNodeAt, getIntersectingNodes, screenToFlowPosition],
  );

  return (
    <RunStateContext.Provider value={trace.nodes}>
      <div ref={wrapper} className="h-full w-full">
        <ReactFlow<WorkflowNode, Edge>
          nodes={nodes}
          edges={renderedEdges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onConnectEnd={onConnectEnd}
          isValidConnection={isValidConnection}
          onDrop={onDrop}
          onDragOver={onDragOver}
          defaultEdgeOptions={defaultEdgeOptions}
          deleteKeyCode={["Backspace", "Delete"]}
          snapToGrid
          snapGrid={[16, 16]}
          fitView
          fitViewOptions={{ padding: 0.3, maxZoom: 1 }}
          minZoom={0.2}
          colorMode="system"
        >
          <Background variant={BackgroundVariant.Dots} gap={16} size={1.5} />
          <Controls showInteractive={false} />
          <MiniMap
            pannable
            zoomable
            className="hidden! sm:block!"
            nodeColor={(n) => MINIMAP_COLORS[n.type as WorkflowNodeType] ?? "#a1a1aa"}
          />

          <Panel position="top-left">
            <NodePalette onAdd={addNodeAtCenter} />
          </Panel>

          <Panel position="top-right">
            <Toolbar
              name={workflow.name}
              dirty={dirty}
              saving={saving}
              runActive={runActive}
              starting={starting}
              onSave={() => void save()}
              onExecute={() => void execute()}
            />
          </Panel>

          {executionId && (
            <Panel position="bottom-center" className="mb-16!">
              <RunPanel
                executionId={executionId}
                trace={trace}
                total={nodes.length}
                onDismiss={runActive ? undefined : () => setExecutionId(null)}
              />
            </Panel>
          )}

          {nodes.length === 0 && (
            <Panel position="top-center" className="pointer-events-none mt-40!">
              <div className="flex items-center gap-2 rounded-lg border border-dashed border-zinc-300 bg-white/90 px-4 py-3 text-sm text-zinc-500 dark:border-zinc-700 dark:bg-zinc-900/90">
                <MousePointerClick className="size-4" aria-hidden />
                Drag a node from the palette to start building.
              </div>
            </Panel>
          )}

          {notice && (
            <Panel position="bottom-center">
              <div
                role="alert"
                className="rounded-md bg-zinc-900 px-3 py-2 text-sm text-white shadow-lg dark:bg-zinc-100 dark:text-zinc-900"
              >
                {notice}
              </div>
            </Panel>
          )}
        </ReactFlow>
      </div>
    </RunStateContext.Provider>
  );
}

type ToolbarProps = {
  name: string;
  dirty: boolean;
  saving: boolean;
  runActive: boolean;
  starting: boolean;
  onSave: () => void;
  onExecute: () => void;
};

function Toolbar({ name, dirty, saving, runActive, starting, onSave, onExecute }: ToolbarProps) {
  const saveState = saving ? "Saving…" : dirty ? "Unsaved changes" : "All changes saved";
  return (
    <div className="flex items-center gap-2 rounded-lg border border-zinc-200 bg-white/95 p-1.5 pl-3 shadow-sm backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/95">
      <div className="mr-1 hidden min-w-0 flex-col md:flex">
        <span className="max-w-48 truncate text-sm font-medium" title={name}>
          {name}
        </span>
        <span className={cn("text-[11px]", dirty && !saving ? "text-amber-600 dark:text-amber-400" : "text-zinc-500")}>
          {saveState}
        </span>
      </div>
      <button
        type="button"
        onClick={onSave}
        disabled={!dirty || saving}
        title="Save (⌘S)"
        className="flex items-center gap-1.5 rounded-md border border-zinc-300 px-2.5 py-1.5 text-sm font-medium hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
      >
        {saving ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : <Save className="size-4" aria-hidden />}
        Save
      </button>
      <button
        type="button"
        onClick={onExecute}
        disabled={runActive || saving}
        title={dirty ? "Saves your changes, then runs the workflow" : "Run the workflow"}
        className="flex items-center gap-1.5 rounded-md bg-violet-600 px-2.5 py-1.5 text-sm font-medium text-white hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {runActive ? (
          <LoaderCircle className="size-4 animate-spin" aria-hidden />
        ) : (
          <Play className="size-4" aria-hidden />
        )}
        {starting ? "Starting…" : runActive ? "Running…" : "Execute"}
      </button>
    </div>
  );
}

const RUN_TONES: Record<string, string> = {
  PENDING: "bg-zinc-400",
  RUNNING: "bg-sky-500 animate-pulse",
  COMPLETED: "bg-emerald-500",
  FAILED: "bg-red-500",
};

function RunPanel({
  executionId,
  trace,
  total,
  onDismiss,
}: {
  executionId: string;
  trace: TraceState;
  total: number;
  onDismiss?: () => void;
}) {
  const done = Object.values(trace.nodes).filter((n) => n.status === "COMPLETED").length;
  const label =
    trace.connection === "error"
      ? "Disconnected"
      : trace.status === null
        ? "Connecting…"
        : trace.status.charAt(0) + trace.status.slice(1).toLowerCase();

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex max-w-[min(32rem,calc(100vw-2rem))] items-start gap-3 rounded-lg border border-zinc-200 bg-white/95 px-3 py-2 text-sm shadow-lg backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/95"
    >
      <span
        className={cn(
          "mt-1.5 size-2 shrink-0 rounded-full",
          trace.connection === "error" ? "bg-amber-500" : RUN_TONES[trace.status ?? "PENDING"],
        )}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="font-medium">{label}</span>
          <span className="text-xs text-zinc-500">
            {done}/{Object.keys(trace.nodes).length || total} nodes ·{" "}
            <code className="font-mono" title={executionId}>
              {executionId.slice(0, 8)}
            </code>
            {trace.connection === "connecting" && trace.status && " · reconnecting…"}
          </span>
        </div>
        {trace.error && <p className="mt-0.5 line-clamp-2 text-xs text-red-600 dark:text-red-400">{trace.error}</p>}
      </div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Clear run results"
          className="rounded p-0.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800"
        >
          <X className="size-4" />
        </button>
      )}
    </div>
  );
}
