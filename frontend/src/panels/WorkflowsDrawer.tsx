/** Workflow drawer: the shipped demo workflows, loadable in one click. */

import { useEffect, useState } from "react";
import { useEditor } from "../store";
import { translate } from "../i18n";
import { api } from "../api";
import type { WorkflowSummary } from "../types";

export default function WorkflowsDrawer() {
  const { lang, loadWorkflow, pushLog } = useEditor();
  const [demos, setDemos] = useState<WorkflowSummary[]>([]);

  useEffect(() => {
    let cancelled = false;
    api
      .workflows()
      .then((payload) => {
        if (!cancelled) setDemos(payload);
      })
      .catch(() => setDemos([]));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
      {demos.length === 0 && (
        <p className="py-4 text-xs text-[rgb(var(--c-text-faint))]">
          {translate(lang, "workflowEmpty")}
        </p>
      )}
      <ul className="space-y-1.5">
        {demos.map((demo) => (
          <li
            key={demo.file}
            className="flex items-center gap-2 rounded-md border border-line bg-panel2 px-2.5 py-2"
          >
            <div className="min-w-0 flex-1">
              <div className="truncate text-[11px] font-medium text-[rgb(var(--c-text))]">
                {demo.name}
              </div>
              <div className="mt-0.5 truncate text-[9px] text-[rgb(var(--c-text-faint))]">
                {demo.description || demo.file}
              </div>
              <div className="mt-0.5 text-[9px] text-[rgb(var(--c-text-faint))]">
                {demo.nodes} {translate(lang, "nodes")} · {demo.edges}{" "}
                {translate(lang, "edges")}
              </div>
            </div>
            <button
              type="button"
              onClick={() => {
                api
                  .workflow(demo.file)
                  .then((payload) => {
                    loadWorkflow(payload as { nodes?: unknown[]; edges?: unknown[] });
                    pushLog(`$ loaded ${demo.file}`);
                  })
                  .catch((error) => pushLog(`! ${(error as Error).message}`));
              }}
              className="shrink-0 rounded-md bg-accent px-2.5 py-1 text-[10px] font-semibold text-onAccent transition hover:bg-accent/85"
            >
              {translate(lang, "workflowLoad")}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
