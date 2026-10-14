/** Left panel: searchable, category grouped node palette. */

import { useMemo } from "react";
import { useEditor } from "../store";
import { translate } from "../i18n";
import type { NodeSpec } from "../types";

function matches(spec: NodeSpec, needle: string): boolean {
  if (!needle) return true;
  const haystack = [
    spec.name,
    spec.type,
    spec.category,
    spec.description,
    ...spec.tags,
    ...spec.aliases,
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(needle.toLowerCase());
}

export default function NodePalette() {
  const { specs, categories, search, setSearch, addNode, lang } = useEditor();

  const grouped = useMemo(() => {
    const buckets: Record<string, NodeSpec[]> = {};
    for (const spec of Object.values(specs)) {
      if (!matches(spec, search)) continue;
      (buckets[spec.category] ??= []).push(spec);
    }
    return Object.entries(buckets).sort((a, b) => a[0].localeCompare(b[0]));
  }, [specs, search]);

  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r border-line bg-panel">
      <header className="border-b border-line px-3 py-3">
        <h2 className="text-sm font-semibold text-slate-200">
          {translate(lang, "palette")}
        </h2>
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={translate(lang, "search")}
          className="mt-2 w-full rounded-md border border-line bg-canvas px-2 py-1.5 text-xs text-slate-200 outline-none placeholder:text-slate-500 focus:border-accent"
        />
        <div className="mt-2 text-[10px] text-slate-500">
          {Object.keys(specs).length} {translate(lang, "nodes")} ·{" "}
          {categories.length} {translate(lang, "category")}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-2 py-2">
        {grouped.length === 0 && (
          <p className="px-2 py-4 text-xs text-slate-500">
            {translate(lang, "emptyWorkflow")}
          </p>
        )}
        {grouped.map(([category, items]) => (
          <section key={category} className="mb-3">
            <h3 className="sticky top-0 z-10 bg-panel px-1 py-1 text-[11px] font-semibold uppercase tracking-wide text-accent/80">
              {category}
              <span className="ml-1 text-slate-500">({items.length})</span>
            </h3>
            <ul className="space-y-1">
              {items.map((spec) => (
                <li key={spec.type}>
                  <button
                    type="button"
                    draggable
                    onDragStart={(event) => {
                      event.dataTransfer.setData("application/chemml-node", spec.type);
                      event.dataTransfer.effectAllowed = "move";
                    }}
                    onClick={() => addNode(spec.type)}
                    title={spec.description}
                    className="w-full rounded-md border border-line bg-panel2 px-2 py-1.5 text-left transition hover:border-accent hover:bg-panel"
                  >
                    <div className="flex items-center justify-between">
                      <span className="truncate text-xs font-medium text-slate-100">
                        {spec.name}
                      </span>
                      <span className="ml-1 shrink-0 rounded bg-line px-1 text-[9px] text-slate-300">
                        {spec.icon || spec.type.slice(0, 2).toUpperCase()}
                      </span>
                    </div>
                    <div className="mt-0.5 flex gap-2 text-[9px] text-slate-500">
                      <span>in {spec.inputs.length}</span>
                      <span>out {spec.outputs.length}</span>
                      <span>v{spec.version}</span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </aside>
  );
}
