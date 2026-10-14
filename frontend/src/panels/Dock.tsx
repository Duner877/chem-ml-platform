/** Right hand workbench: a tab strip over the inspector, AI, agent, data and
 *  simulation panels. */

import { useEditor, type DockTab } from "../store";
import { translate } from "../i18n";
import Inspector from "./Inspector";
import AIPanel from "./AIPanel";
import AgentPanel from "./AgentPanel";
import DataPanel from "./DataPanel";
import SimulationPanel from "./SimulationPanel";

const TABS: Array<{ id: DockTab; label: string; icon: string }> = [
  { id: "inspector", label: "dockInspector", icon: "🔧" },
  { id: "ai", label: "dockAI", icon: "🤖" },
  { id: "agent", label: "dockAgent", icon: "✦" },
  { id: "data", label: "dockData", icon: "🗄" },
  { id: "simulation", label: "dockSimulation", icon: "⚛" },
];

export default function Dock() {
  const { lang, dockTab, setDockTab } = useEditor();

  return (
    <aside className="flex h-full w-80 shrink-0 flex-col border-l border-line bg-panel">
      <nav className="flex shrink-0 border-b border-line">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setDockTab(tab.id)}
            title={translate(lang, tab.label)}
            className={`flex flex-1 items-center justify-center gap-1 py-2 text-[10px] transition ${
              dockTab === tab.id
                ? "border-b-2 border-accent text-accent"
                : "border-b-2 border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <span>{tab.icon}</span>
            <span className="hidden xl:inline">{translate(lang, tab.label)}</span>
          </button>
        ))}
      </nav>

      <div className="min-h-0 flex-1">
        {dockTab === "inspector" && <Inspector />}
        {dockTab === "ai" && <AIPanel />}
        {dockTab === "agent" && <AgentPanel />}
        {dockTab === "data" && <DataPanel />}
        {dockTab === "simulation" && <SimulationPanel />}
      </div>
    </aside>
  );
}
