/** Node library drawer: searchable, category grouped, bilingual palette. */

import { useMemo } from "react";
import { useEditor } from "../store";
import { translate } from "../i18n";
import type { NodeSpec } from "../types";

function matches(spec: NodeSpec, needle: string): boolean {
  if (!needle) return true;
  const haystack = [
    spec.name,
    spec.name_zh,
    spec.type,
    spec.category,
    spec.category_zh,
    spec.description,
    spec.description_en,
    ...spec.tags,
    ...spec.aliases,
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(needle.toLowerCase());
}

export default function NodePalette() {
  const { specs, search, setSearch, addNode, lang } = useEditor();

  const grouped = useMemo(() => {
    const buckets: Record<string, NodeSpec[]> = {};
    for (const spec of Object.values(specs)) {
      if (!matches(spec, search)) continue;
      (buckets[spec.category] ??= []).push(spec);
    }
    return Object.entries(buckets).sort((a, b) => a[0].localeCompare(b[0]));
  }, [specs, search]);

  const displayName = (spec: NodeSpec) =>
    lang === "zh" ? spec.name_zh || spec.name : spec.name;
  const displayCategory = (category: string) => {
    const sample = Object.values(specs).find((spec) => spec.category === category);
    if (!sample) return category;
    return lang === "zh" ? sample.category_zh || category : category;
  };
  const displayDescription = (spec: NodeSpec) =>
    lang === "zh" ? spec.description : spec.description_en || spec.description;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 px-3 py-2">
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={translate(lang, "search")}
          className="cml-widget"
        />
        <div className="mt-1.5 text-[10px] text-[rgb(var(--c-text-faint))]">
          {Object.keys(specs).length} {translate(lang, "nodes")} ·{" "}
          {grouped.length} {translate(lang, "category")} · {translate(lang, "dragHint")}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {grouped.length === 0 && (
          <p className="px-2 py-4 text-xs text-[rgb(var(--c-text-faint))]">
            {translate(lang, "emptyWorkflow")}
          </p>
        )}
        {grouped.map(([category, items]) => (
          <section key={category} className="mb-2">
            <h3 className="sticky top-0 z-10 bg-panel px-1 py-1 text-[10px] font-semibold uppercase tracking-wide text-accent">
              {displayCategory(category)}
              <span className="ml-1 text-[rgb(var(--c-text-faint))]">({items.length})</span>
            </h3>
            <ul className="space-y-0.5">
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
                    title={displayDescription(spec)}
                    className="w-full rounded-md border border-line bg-panel2 px-2 py-1.5 text-left transition hover:border-accent"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-[11px] font-medium text-[rgb(var(--c-text))]">
                        {displayName(spec)}
                      </span>
                      <span className="ml-1 shrink-0 rounded bg-line px-1 text-[8px] text-[rgb(var(--c-text-dim))]">
                        {spec.icon || spec.type.slice(0, 2).toUpperCase()}
                      </span>
                    </div>
                    <div className="mt-0.5 flex gap-2 text-[8px] text-[rgb(var(--c-text-faint))]">
                      <span>
                        {spec.inputs.length} {translate(lang, "nodeIn")}
                      </span>
                      <span>
                        {spec.outputs.length} {translate(lang, "nodeOut")}
                      </span>
                      <span>v{spec.version}</span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
