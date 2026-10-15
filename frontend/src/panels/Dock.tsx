/** Right hand workbench — the "Manager" panel of the reference editor.
 *
 * A tab strip over the inspector, AI, agent, data and simulation panels.
 */

import { useEditor, type DockTab } from "../store";
import { translate } from "../i18n";
import Inspector from "./Inspector";
import PlotPanel from "./PlotPanel";
import AIPanel from "./AIPanel";
import AgentPanel from "./AgentPanel";
import DataPanel from "./DataPanel";
import SimulationPanel from "./SimulationPanel";
import {
  IconSparkle,
  IconStar,
  IconTerminal,
  IconGrid,
  IconCube,
  IconImage,
  IconPanelRight,
} from "../components/Icons";

const TABS: Array<{ id: DockTab; label: string; icon: typeof IconCube }> = [
  { id: "inspector", label: "dockInspector", icon: IconCube },
  { id: "plot", label: "dockPlot", icon: IconImage },
  { id: "ai", label: "dockAI", icon: IconStar },
  { id: "agent", label: "dockAgent", icon: IconSparkle },
  { id: "data", label: "dockData", icon: IconGrid },
  { id: "simulation", label: "dockSimulation", icon: IconTerminal },
];

export default function Dock() {
  const { lang, dockTab, setDockTab, dockOpen, setDockOpen } = useEditor();

  // Collapsed: a thin handle on the right edge, so the canvas keeps the full
  // window width.  Expanding restores a responsive 18rem..21rem workbench.
  if (!dockOpen) {
    return (
      <div className="relative flex h-full shrink-0 items-start border-l border-line bg-panel">
        <button
          type="button"
          onClick={() => setDockOpen(true)}
          title={translate(lang, "showDock")}
          className="absolute -left-3 top-3 z-20 flex h-8 w-6 items-center justify-center rounded border border-line bg-panel text-[rgb(var(--c-text-dim))] shadow transition hover:text-accent"
        >
          <IconPanelRight size={13} />
        </button>
      </div>
    );
  }

  return (
    <aside className="relative flex h-full w-72 shrink-0 flex-col border-l border-line bg-panel xl:w-80">
      <button
        type="button"
        onClick={() => setDockOpen(false)}
        title={translate(lang, "hideDock")}
        className="absolute -left-3 top-3 z-20 flex h-8 w-6 items-center justify-center rounded border border-line bg-panel text-[rgb(var(--c-text-dim))] shadow transition hover:text-accent"
      >
        <IconPanelRight size={13} className="scale-x-[-1]" />
      </button>
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
        {dockTab === "plot" && <PlotPanel />}
        {dockTab === "ai" && <AIPanel />}
        {dockTab === "agent" && <AgentPanel />}
        {dockTab === "data" && <DataPanel />}
        {dockTab === "simulation" && <SimulationPanel />}
      </div>
    </aside>
  );
}
