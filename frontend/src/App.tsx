/** Application shell: toolbar + palette + canvas + inspector + console. */

import { useCallback, useEffect } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  addEdge,
  useReactFlow,
  type Connection,
  type Edge,
  type IsValidConnection,
} from "@xyflow/react";

import NodePalette from "./panels/NodePalette";
import Dock from "./panels/Dock";
import Console from "./panels/Console";
import Marketplace from "./panels/Marketplace";
import Toolbar from "./Toolbar";
import ScientificNodeCard from "./nodes/ScientificNodeCard";
import { useEditor } from "./store";
import { api } from "./api";

const nodeTypes = { scientific: ScientificNodeCard };

export default function App() {
  const {
    specs,
    nodes,
    edges,
    selectedId,
    setSpecs,
    setSelected,
    marketplaceOpen,
    setDockTab,
    onNodesChange,
    onEdgesChange,
    onConnect,
    setBackend,
    backend,
  } = useEditor();

  const { screenToFlowPosition, fitView } = useReactFlow();

  // Bootstrap: fetch the node catalogue and the backend health.
  useEffect(() => {
    api
      .nodes()
      .then(setSpecs)
      .catch(() => setBackend("offline"));
    api
      .health()
      .then(() => setBackend("online"))
      .catch(() => setBackend("offline"));
  }, [setSpecs, setBackend]);

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const type = event.dataTransfer.getData("application/chemml-node");
      if (!type || !specs[type]) return;
      const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
      useEditor.getState().addNode(type, position);
    },
    [screenToFlowPosition, specs]
  );

  const isValidConnection: IsValidConnection<Edge> = useCallback(
    (connection: Connection | Edge) =>
      connection.source !== connection.target &&
      !edges.some(
        (edge) =>
          edge.source === connection.source &&
          edge.target === connection.target &&
          edge.sourceHandle === connection.sourceHandle &&
          edge.targetHandle === connection.targetHandle
      ),
    [edges]
  );

  return (
    <div className="flex h-full flex-col">
      <Toolbar />

      <div className="flex min-h-0 flex-1">
        <NodePalette />

        <main className="relative min-w-0 flex-1">
          {backend === "offline" && (
            <div className="absolute inset-x-0 top-0 z-20 bg-bad/90 px-3 py-1 text-center text-[11px] text-canvas">
              Backend offline — start the API with{" "}
              <code className="font-mono">uvicorn backend.app:app --port 8000</code>
            </div>
          )}

          {nodes.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
              <div className="text-5xl">🧬</div>
              <h1 className="text-lg font-semibold text-slate-200">
                Chem ML Platform
              </h1>
              <p className="max-w-md text-xs leading-relaxed text-slate-500">
                {Object.keys(specs).length} scientific nodes · 5 demo workflows ·
                unified scientific foundation models, cloud / local AI switching,
                a scientific data catalog, a simulation job queue and an
                autonomous scientific agent. Drag a node or ask the agent.
              </p>
              <p className="text-[11px] text-slate-600">
                Drag a node from the left palette, connect the ports, press Run —
                or open the right dock's Agent tab.
              </p>
            </div>
          ) : (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              isValidConnection={isValidConnection}
              onDrop={onDrop}
              onDragOver={onDragOver}
              onNodeClick={(_, node) => {
                setSelected(node.id);
                setDockTab("inspector");
              }}
              onPaneClick={() => setSelected(null)}
              onInit={() => window.setTimeout(() => fitView({ padding: 0.2 }), 60)}
              fitView
              minZoom={0.2}
              maxZoom={2.5}
              defaultEdgeOptions={{ animated: true }}
              proOptions={{ hideAttribution: true }}
            >
              <Background gap={18} size={1} color="#1b2740" />
              <MiniMap
                pannable
                zoomable
                maskColor="rgba(11,17,32,0.75)"
                nodeColor={() => "#23304d"}
              />
              <Controls showInteractive={false} />
            </ReactFlow>
          )}
        </main>

        <Dock />
      </div>

      {marketplaceOpen && <Marketplace />}

      <Console />
    </div>
  );
}
