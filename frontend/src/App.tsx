/** Application shell — the ComfyUI-style frame:
 *
 *   ┌──────────────────────────────────────────────────────────────┐
 *   │ TopBar (brand · menus · workflow · manager/theme/lang)       │
 *   ├──────┬───────────────────────────────────────────┬───────────┤
 *   │ rail │  canvas (React Flow, dots grid)           │  Dock     │
 *   │ +    │  + floating drawers (library / workflows) │  (Manager)│
 *   │drawer│  + console drawer + bottom run bar        │           │
 *   └──────┴───────────────────────────────────────────┴───────────┘
 */

import { useCallback, useEffect } from "react";
import {
  Background,
  MiniMap,
  ReactFlow,
  useReactFlow,
  type Connection,
  type Edge,
  type IsValidConnection,
} from "@xyflow/react";

import NodePalette from "./panels/NodePalette";
import WorkflowsDrawer from "./panels/WorkflowsDrawer";
import Dock from "./panels/Dock";
import Console from "./panels/Console";
import Marketplace from "./panels/Marketplace";
import ScientificNodeCard from "./nodes/ScientificNodeCard";
import TopBar from "./components/TopBar";
import IconRail from "./components/IconRail";
import BottomBar from "./components/BottomBar";
import Drawer from "./components/Drawer";
import AboutDialog from "./components/AboutDialog";
import { useEditor, useThemeTokens } from "./store";
import { api } from "./api";
import { translate } from "./i18n";

const nodeTypes = { scientific: ScientificNodeCard };

/** ``"44 56 82"`` -> ``"rgb(44, 56, 82)"`` (SVG props need a literal colour). */
function rgb(channels: string): string {
  return `rgb(${channels.split(/\s+/).join(", ")})`;
}

export default function App() {
  const {
    specs,
    nodes,
    edges,
    setSpecs,
    setSelected,
    marketplaceOpen,
    setDockTab,
    onNodesChange,
    onEdgesChange,
    onConnect,
    setBackend,
    backend,
    lang,
    leftDrawer,
    setLeftDrawer,
    consoleOpen,
    setConsoleOpen,
    canvasLocked,
    addNode,
  } = useEditor();
  const tokens = useThemeTokens();

  const { screenToFlowPosition, fitView } = useReactFlow();

  // Bootstrap: fetch the node catalogue and the backend health.
  useEffect(() => {
    // ``?lang=en`` starts the editor in English (deep link / smoke test).
    const requestedLang = new URLSearchParams(window.location.search).get("lang");
    if (requestedLang === "en" || requestedLang === "zh") {
      useEditor.getState().setLang(requestedLang);
    }

    api
      .nodes()
      .then((payload) => {
        setSpecs(payload);
        // Deep link: ``?workflow=<file>`` loads a demo straight into the
        // canvas.  It must run *after* the specs are in the store, otherwise
        // ``loadWorkflow`` cannot resolve the node types (also used by the UI
        // smoke tests).
        const requested = new URLSearchParams(window.location.search).get("workflow");
        if (requested) {
          api
            .workflow(requested)
            .then((workflow) => {
              useEditor
                .getState()
                .loadWorkflow(workflow as { nodes?: unknown[]; edges?: unknown[] });
            })
            .catch(() => setBackend("offline"));
        }
      })
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
      addNode(type, position);
    },
    [screenToFlowPosition, specs, addNode]
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
    <div className="flex h-full flex-col overflow-hidden bg-canvas">
      <TopBar />

      <div className="flex min-h-0 flex-1">
        {/* canvas + floating overlays -------------------------------------- */}
        <div className="relative min-w-0 flex-1">
          {backend === "offline" && (
            <div className="absolute inset-x-0 top-0 z-30 bg-bad/90 px-3 py-1 text-center text-[11px] text-onAccent">
              Backend offline — start the API with{" "}
              <code className="font-mono">uvicorn backend.app:app --port 8000</code>
            </div>
          )}

          <main className="absolute inset-0">
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
              nodesDraggable={!canvasLocked}
              nodesConnectable={!canvasLocked}
              defaultEdgeOptions={{ animated: true }}
              proOptions={{ hideAttribution: true }}
            >
              <Background gap={18} size={1} color={rgb(tokens.grid)} />
              <MiniMap
                pannable
                zoomable
                maskColor={rgb(tokens.minimap)}
                nodeColor={() => rgb(tokens.panel2)}
              />
            </ReactFlow>

            {nodes.length === 0 && (
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2 text-center">
                <h1 className="text-base font-semibold text-[rgb(var(--c-text-dim))]">
                  {translate(lang, "emptyTitle")}
                </h1>
                <p className="max-w-sm text-[11px] leading-relaxed text-[rgb(var(--c-text-faint))]">
                  {translate(lang, "emptyHint")}
                </p>
              </div>
            )}
          </main>

          {/* left icon rail + floating drawers ------------------------------- */}
          <IconRail />
          {leftDrawer === "nodes" && (
            <Drawer
              title={translate(lang, "drawerNodes")}
              subtitle={`${Object.keys(specs).length} ${translate(lang, "nodes")}`}
              side="left"
              onClose={() => setLeftDrawer(null)}
            >
              <NodePalette />
            </Drawer>
          )}
          {leftDrawer === "workflows" && (
            <Drawer
              title={translate(lang, "drawerWorkflows")}
              side="left"
              onClose={() => setLeftDrawer(null)}
            >
              <WorkflowsDrawer />
            </Drawer>
          )}

          {/* console drawer -------------------------------------------------- */}
          {consoleOpen && (
            <Drawer
              title={translate(lang, "console")}
              side="bottom"
              height="h-56"
              onClose={() => setConsoleOpen(false)}
            >
              <Console />
            </Drawer>
          )}

          <BottomBar />
        </div>

        {/* right workbench dock --------------------------------------------- */}
        <Dock />
      </div>

      {marketplaceOpen && <Marketplace />}
      <AboutDialog />
    </div>
  );
}
