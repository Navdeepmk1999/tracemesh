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
import { MousePointerClick } from "lucide-react";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore, type DragEvent } from "react";

import "@xyflow/react/dist/style.css";

import { createNode, nodeTypes, type WorkflowNode, type WorkflowNodeType } from "@/components/nodes";

import { connectionError } from "./graph-rules";
import { NODE_DRAG_MIME, NodePalette } from "./node-palette";

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

// A starter graph so the canvas isn't empty on first open. PR 7 replaces this
// with the workflow loaded from the API. Fixed ids keep it stable across
// remounts (e.g. React strict mode).
function starterGraph(): { nodes: WorkflowNode[]; edges: Edge[] } {
  const trigger = createNode("trigger", { x: 0, y: 64 }, "00000000-0000-4000-8000-000000000001");
  const agent = createNode("agent", { x: 288, y: 32 }, "00000000-0000-4000-8000-000000000002");
  const webhook = createNode("webhook", { x: 640, y: 64 }, "00000000-0000-4000-8000-000000000003");
  agent.data = {
    label: "Research agent",
    model: "claude-sonnet-5-5",
    instructions: "Summarize the incoming request and draft a reply.",
  };
  webhook.data = { label: "Notify Slack", method: "POST", url: "https://hooks.example.com/tracemesh" };
  return {
    nodes: [trigger, agent, webhook],
    edges: [
      { id: "00000000-0000-4000-8000-0000000000e1", source: trigger.id, target: agent.id },
      { id: "00000000-0000-4000-8000-0000000000e2", source: agent.id, target: webhook.id },
    ],
  };
}

const noopSubscribe = () => () => {};

export function WorkflowCanvas({ workflowId }: { workflowId: string }) {
  // Client-only: React Flow resolves colorMode="system" from matchMedia, which
  // the server can't know, so server HTML would hydrate with the wrong theme
  // class. The server sends a placeholder; the canvas mounts in the browser.
  const isClient = useSyncExternalStore(noopSubscribe, () => true, () => false);
  if (!isClient) {
    return <div className="h-full w-full animate-pulse bg-zinc-50 dark:bg-zinc-900" aria-busy="true" />;
  }

  return (
    // Keyed by workflow so navigating between workflows starts fresh state.
    <ReactFlowProvider key={workflowId}>
      <Canvas />
    </ReactFlowProvider>
  );
}

function Canvas() {
  const [initial] = useState(starterGraph);
  const [nodes, setNodes, onNodesChange] = useNodesState<WorkflowNode>(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(initial.edges);
  const { screenToFlowPosition, getNodes, getEdges, getIntersectingNodes } = useReactFlow<WorkflowNode, Edge>();
  const wrapper = useRef<HTMLDivElement>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 3000);
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
    <div ref={wrapper} className="h-full w-full">
      <ReactFlow<WorkflowNode, Edge>
        nodes={nodes}
        edges={edges}
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

        <Panel position="top-right" className="hidden md:block">
          <div className="rounded-lg border border-zinc-200 bg-white/95 px-3 py-2 text-xs text-zinc-500 shadow-sm dark:border-zinc-800 dark:bg-zinc-900/95">
            {nodes.length} nodes · {edges.length} connections
            <span className="mx-1.5">·</span>
            Drag from a handle to connect · Backspace deletes
          </div>
        </Panel>

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
              role="status"
              className="rounded-md bg-zinc-900 px-3 py-2 text-sm text-white shadow-lg dark:bg-zinc-100 dark:text-zinc-900"
            >
              {notice}
            </div>
          </Panel>
        )}
      </ReactFlow>
    </div>
  );
}
