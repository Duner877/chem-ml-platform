/** Left icon rail — the ComfyUI-style vertical launcher strip.
 *
 * Sits *over* the canvas (an overlay, not a layout column) and toggles the
 * floating drawers, exactly like the reference editor.
 */

import { useEditor } from "../store";
import { translate } from "../i18n";
import {
  IconCube,
  IconFolder,
  IconGrid,
  IconKey,
  IconSparkle,
  IconTerminal,
} from "./Icons";

interface RailButton {
  id: string;
  label: string;
  icon: typeof IconCube;
  onSelect: () => void;
  active: boolean;
  /** Draws a small amber dot: the button has something to act on. */
  alert?: boolean;
}

export default function IconRail() {
  const {
    lang,
    leftDrawer,
    toggleLeftDrawer,
    consoleOpen,
    setConsoleOpen,
    setMarketplace,
    dockTab,
    setDockTab,
    setDockOpen,
    credentialCount,
  } = useEditor();

  function openTab(tab: "agent" | "apikey") {
    // Clicking a rail entry on a collapsed dock must not look like it worked.
    if (!useEditor.getState().dockOpen) setDockOpen(true);
    setDockTab(tab);
  }

  const top: RailButton[] = [
    {
      id: "nodes",
      label: translate(lang, "railNodes"),
      icon: IconCube,
      onSelect: () => toggleLeftDrawer("nodes"),
      active: leftDrawer === "nodes",
    },
    {
      id: "workflows",
      label: translate(lang, "railWorkflows"),
      icon: IconFolder,
      onSelect: () => toggleLeftDrawer("workflows"),
      active: leftDrawer === "workflows",
    },
    {
      id: "agent",
      label: translate(lang, "dockAgent"),
      icon: IconSparkle,
      onSelect: () => openTab("agent"),
      active: dockTab === "agent",
    },
    {
      id: "apikey",
      label: translate(lang, "dockApiKey"),
      icon: IconKey,
      onSelect: () => openTab("apikey"),
      active: dockTab === "apikey",
      alert: credentialCount === 0,
    },
  ];

  const bottom: RailButton[] = [
    {
      id: "marketplace",
      label: translate(lang, "railMarketplace"),
      icon: IconGrid,
      onSelect: () => setMarketplace(true),
      active: false,
    },
    {
      id: "console",
      label: translate(lang, "railConsole"),
      icon: IconTerminal,
      onSelect: () => setConsoleOpen(!consoleOpen),
      active: consoleOpen,
    },
  ];

  function render(button: RailButton) {
    const Icon = button.icon;
    return (
      <button
        key={button.id}
        type="button"
        title={button.label}
        aria-label={button.label}
        onClick={button.onSelect}
        className={`relative flex h-9 w-9 items-center justify-center rounded-md transition ${
          button.active
            ? "bg-accent/15 text-accent"
            : button.alert
              ? "text-warn hover:bg-panel2 hover:text-warn"
              : "text-[rgb(var(--c-text-dim))] hover:bg-panel2 hover:text-[rgb(var(--c-text))]"
        }`}
      >
        <Icon size={17} />
        {button.alert && (
          <span
            aria-hidden="true"
            className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-warn"
          />
        )}
      </button>
    );
  }

  return (
    <nav className="pointer-events-auto absolute left-2 top-2 z-20 flex flex-col items-center gap-1 rounded-lg border border-line bg-panel/95 p-1 backdrop-blur">
      {top.map(render)}
      <div className="my-0.5 h-px w-6 bg-line" />
      {bottom.map(render)}
    </nav>
  );
}
