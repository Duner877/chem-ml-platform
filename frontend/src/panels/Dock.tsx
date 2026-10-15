/** Right hand workbench — the "Manager" panel of the reference editor.
 *
 * A tab strip over the inspector, AI, agent, data and simulation panels.
 */

import { useEditor, type DockTab } from "../store";
import { translate } from "../i18n";
import Inspector from "./Inspector";
import AIPanel from "./AIPanel";
import AgentPanel from "./AgentPanel";
import DataPanel from "./DataPanel";
import SimulationPanel from "./SimulationPanel";
import { IconSparkle, IconStar, IconTerminal, IconGrid, IconCube } from "../components/Icons";

const TABS: Array<{ id: DockTab; label: string; icon: typeof IconCube }> = [
  { id: "inspector", label: "dockInspector", icon: IconCube },
  { id: "ai", label: "dockAI", icon: IconStar },
  { id: "agent", label: "dockAgent", icon: IconSparkle },
  { id: "data", label: "dockData", icon: IconGrid },
  { id: "simulation", label: "dockSimulation", icon: IconTerminal },
];

export default function Dock() {
  const { lang, dockTab, setDockTab } = useEditor();

  return (
    <aside className="flex h-full w-80 shrink-0 flex-col border-l border-line bg-panel">
      <nav className="flex shrink-0 border-b border-line">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setDockTab(tab.id)}
              title={translate(lang, tab.label)}
              className={`flex flex-1 items-center justify-center gap-1 py-2 text-[10px] transition ${
                dockTab === tab.id
                  ? "border-b-2 border-accent text-accent"
                  : "border-b-2 border-transparent text-[rgb(var(--c-text-dim))] hover:text-[rgb(var(--c-text))]"
              }`}
            >
              <Icon size={13} />
              <span className="hidden xl:inline">{translate(lang, tab.label)}</span>
            </button>
          );
        })}
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
